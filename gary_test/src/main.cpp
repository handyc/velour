// Velour test sketch for Gary (ESP8266).
//
// Goal of this sketch: prove the entire Wi-Fi → Velour API → Velour
// database loop works for one specific ESP8266 device. There are NO
// real sensor reads in this file — every "reading" is a synthetic
// value derived from millis() so the test is self-contained and runs
// without any breadboard hardware attached.
//
// What it does on boot:
//   1. Brings up Wi-Fi using credentials from wifi_secrets.h
//   2. Constructs a VelourClient pointed at the configured base URL
//   3. Sends one immediate "boot" reading so something appears in
//      the Velour UI within a few seconds of power-on
//
// What it does in loop():
//   - Every 30 seconds, queues four synthetic readings (test_temp_c,
//     test_humidity, test_soil_moisture, test_pulse) and POSTs them
//     to the Velour /api/nodes/<slug>/report/ endpoint.
//   - Logs every step to the serial monitor at 115200 baud, including
//     the HTTP status of every report attempt and the JSON response
//     body if any.
//
// Once this sketch is flashing data into Velour cleanly, you can
// either (a) merge the additive bits into Gary's "real" sketch, or
// (b) just rewrite Gary's main sketch on top of this one and add
// the actual sensor reads back in.

#include <Arduino.h>
#include <Wire.h>
#if defined(ESP32)
  #include <WebServer.h>
  #include <ESPmDNS.h>
#elif defined(ESP8266)
  #include <ESP8266WebServer.h>
  #include <ESP8266mDNS.h>
#endif
#include "wifi_secrets.h"
#include "velour_client.h"

#ifdef NODE_HAS_LORA
  #include <SPI.h>
  #include <LoRa.h>
  // ESP32 ROM miniz — tdefl (compress) and tinfl (decompress)
  // without malloc. We use tdefl_compress_mem_to_mem() which works
  // with caller-provided buffers.
  #include <esp32/rom/miniz.h>
  // TTGO T3 V1.6.1 LoRa pins
  #define LORA_SCK   5
  #define LORA_MISO  19
  #define LORA_MOSI  27
  #define LORA_CS    18
  #define LORA_RST   23
  #define LORA_DIO0  26
  #define LORA_FREQ  868E6

  bool loraReady = false;
  unsigned long lastLoraSendAt = 0;
  unsigned long loraPacketsSent = 0;
  unsigned long loraPacketsRecv = 0;
  unsigned long loraScreensRecv = 0;
  int loraLastRssi = 0;
  char loraLastMsg[64] = "";

  // 868 MHz EU duty cycle: 1% = 36s airtime/hour max.
  // Hazel sends 2000-char screen every 20 min.
  // Mabel sends 2000-char screen every 30 min.
  #ifdef NODE_LORA_ROLE_SENDER
    #define LORA_SCREEN_INTERVAL_MS 30000   // Mabel: 30s
    #define LORA_SCREEN_OFFSET_MS   15000   // start 15s after boot
  #else
    #define LORA_SCREEN_INTERVAL_MS 30000   // Hazel: 30s
    #define LORA_SCREEN_OFFSET_MS       0   // start immediately
  #endif
  unsigned long lastLoraScreenAt = 0;

  #define LORA_MAX_PAYLOAD 222

  // Reassembly buffer for incoming multi-packet screens
  #define LORA_SCREEN_SIZE 501  // 500 chars — fits in ~3 packets
  static char loraScreenBuf[LORA_SCREEN_SIZE];   // received screen (null-terminated)
  static uint8_t loraRxFragBuf[4096];             // compressed fragment accumulator
  static int loraRxFragCount = 0;
  static int loraRxFragTotal = 0;
  static size_t loraRxFragLen = 0;

  // Ticker scroll state — pixel-level smooth scrolling.
  // Scrolls 2px every 5ms = 400px/sec = 100 chars/sec at 4px/char.
  static int loraTickerPx = 0;         // pixel offset (negative = scrolled left)
  static unsigned long lastTickerScrollAt = 0;
  static bool loraScreenReady = true;  // start true for test message

  // Compress a buffer using deflate (ESP32 ROM miniz).
  // Returns compressed size, or 0 on failure. Output buffer must
  // be at least as large as input (compressed can occasionally be
  // larger for tiny inputs).
  // tdefl flags: best compression, zlib-compatible output
  #define LORA_TDEFL_FLAGS (TDEFL_WRITE_ZLIB_HEADER | 4095)

  static size_t loraCompress(const uint8_t* in, size_t inLen,
                              uint8_t* out, size_t outCap) {
      size_t r = tdefl_compress_mem_to_mem(out, outCap, in, inLen,
                                            LORA_TDEFL_FLAGS);
      return (r == 0 && inLen > 0) ? 0 : r;  // 0 = failure
  }

  static size_t loraDecompress(const uint8_t* in, size_t inLen,
                                uint8_t* out, size_t outCap) {
      size_t r = tinfl_decompress_mem_to_mem(out, outCap, in, inLen,
                                              TINFL_FLAG_PARSE_ZLIB_HEADER);
      return (r == TINFL_DECOMPRESS_MEM_TO_MEM_FAILED) ? 0 : r;
  }

  // Packet type markers — first byte of every LoRa packet.
  #define LORA_PKT_BEACON  0x01   // short text message
  #define LORA_PKT_SCREEN  0x02   // compressed screen fragment

  // Send a short beacon/ack message (prefixed with type byte).
  static void loraSendBeacon(const char* msg) {
      LoRa.beginPacket();
      LoRa.write(LORA_PKT_BEACON);
      LoRa.print(msg);
      LoRa.endPacket();
      loraPacketsSent++;
  }

  // Send a (possibly large) buffer over LoRa in multiple packets.
  // Each packet: [type:1][seq:1][total:1][payload:up to 219]
  // Compresses first, then fragments.
  static int loraSendCompressed(const char* data, size_t len) {
      // Try compression; fall back to raw if it fails
      static uint8_t compBuf[4096];
      size_t compLen = loraCompress((const uint8_t*)data, len,
                                    compBuf, sizeof(compBuf));
      const uint8_t* sendBuf;
      size_t sendLen;

      if (compLen > 0 && compLen < len) {
          sendBuf = compBuf;
          sendLen = compLen;
          Serial.print("[lora] compressed ");
          Serial.print(len);
          Serial.print(" -> ");
          Serial.print(compLen);
          Serial.println(" bytes");
      } else {
          // Compression failed or expanded — send raw
          sendBuf = (const uint8_t*)data;
          sendLen = len;
          Serial.print("[lora] sending raw ");
          Serial.print(len);
          Serial.println(" bytes (compression failed/expanded)");
      }

      int maxPayload = LORA_MAX_PAYLOAD - 3;  // 3 bytes header: type+seq+total
      int totalPkts = (sendLen + maxPayload - 1) / maxPayload;
      if (totalPkts > 255) {
          Serial.println("[lora] too many packets, truncating");
          totalPkts = 255;
      }

      Serial.print("[lora] sending ");
      Serial.print(totalPkts);
      Serial.println(" packets");

      for (int i = 0; i < totalPkts; i++) {
          int offset = i * maxPayload;
          int chunk = sendLen - offset;
          if (chunk > maxPayload) chunk = maxPayload;

          LoRa.beginPacket();
          LoRa.write(LORA_PKT_SCREEN);
          LoRa.write((uint8_t)i);
          LoRa.write((uint8_t)totalPkts);
          LoRa.write(sendBuf + offset, chunk);
          LoRa.endPacket();
          loraPacketsSent++;

          if (i < totalPkts - 1) delay(500);  // 500ms gap — easy on power supply
      }
      LoRa.receive();  // ensure radio is back in RX mode
      return totalPkts;
  }
#endif

// Optional OLED display support. Enable by defining NODE_HAS_OLED in
// wifi_secrets.h (or via build_flags) for nodes that have an SSD1306
// 128x64 screen wired to software I2C. The pins default to SCL=14
// (D5) and SDA=12 (D6), matching the user's verified u8g2 demo; both
// are overridable via NODE_OLED_SCL / NODE_OLED_SDA.
// Optional decision tree inference. Enable via NODE_HAS_DECISION_TREE
// in build_flags. The tree is downloaded from Velour's
// /api/nodes/<slug>/model.json endpoint on boot and inference runs
// locally every tick cycle. Results are reported back in the heartbeat.
#ifdef NODE_HAS_DECISION_TREE
  #include "tiny_tree.h"
  TinyTree decisionTree;
  bool treeLoaded = false;
  int lastPrediction = -1;
  int lastConfidence = 0;
  const char* lastClassName = "?";
#endif

#ifdef NODE_HAS_OLED
  #include <U8g2lib.h>
  #include <qrcode.h>
  #if defined(NODE_OLED_HW_I2C)
    // ESP32 boards with HW I2C (e.g. TTGO T3 V1.6.1: SDA=21, SCL=22)
    U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
  #else
    // ESP8266 boards with SW I2C (e.g. Terry: SCL=14, SDA=12)
    #ifndef NODE_OLED_SCL
      #define NODE_OLED_SCL 14
    #endif
    #ifndef NODE_OLED_SDA
      #define NODE_OLED_SDA 12
    #endif
    U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(
        U8G2_R0, NODE_OLED_SCL, NODE_OLED_SDA, U8X8_PIN_NONE);
  #endif
#endif

// Default HTTP port for the local web server. Per-device overrides go in
// wifi_secrets.h — each node in the fleet can have its own port so the
// same binary can be reverse-proxied cleanly by a front-end velour later.
// Gary uses the default (80); Larry is the first with a custom port.
#ifndef NODE_HTTP_PORT
#define NODE_HTTP_PORT 80
#endif

#define REPORT_INTERVAL_MS  (30UL * 1000UL)
// Local AHT read cadence, independent of Velour reporting. The built-in
// web page polls /data.json every second; 2s sensor reads keep the data
// fresh without pounding the I2C bus or the AHT's ~75ms measurement cycle.
#define AHT_READ_INTERVAL_MS  (2UL * 1000UL)
// How often to ask Velour whether a new firmware is available. 60 minutes
// is a reasonable balance between "operator doesn't wait forever after an
// upload" and "we don't hammer the server". First check also runs once
// shortly after boot so a fresh flash picks up any pending update fast.
#define OTA_CHECK_INTERVAL_MS  (60UL * 60UL * 1000UL)
#define FIRMWARE_VERSION    "v0.6.4"

// How often to fetch Identity's mood from Velour. 60 seconds keeps the
// display reasonably fresh without hammering the server.
#define MOOD_FETCH_INTERVAL_MS  (60UL * 1000UL)

#define AHT_ADDR        0x38
#define AHT10_INIT_CMD  0xE1
#define AHT20_INIT_CMD  0xBE

VelourClient velour(VELOUR_URL, NODE_SLUG, NODE_TOKEN);
#if defined(ESP32)
WebServer httpd(NODE_HTTP_PORT);
#elif defined(ESP8266)
ESP8266WebServer httpd(NODE_HTTP_PORT);
#endif

unsigned long lastReportAt = 0;
unsigned long lastOtaCheckAt = 0;
unsigned long lastAhtReadAt = 0;
unsigned long bootMs = 0;
int reportCount = 0;

// Identity mood state — fetched from Velour's /api/nodes/<slug>/identity.json
// on a 60-second cadence. Nodes with OLEDs use this to reflect Velour's
// emotional state on the display.
char identityMood[24] = "unknown";
float identityIntensity = 0.5f;
unsigned long lastMoodFetchAt = 0;
bool moodFetched = false;

// Mood category for the sprite expression. Computed from identityMood[]
// after each successful fetch.
enum MoodCategory { MOOD_HAPPY, MOOD_WORRIED, MOOD_NEUTRAL };
MoodCategory moodCategory = MOOD_NEUTRAL;

static void categorizeMood() {
    if (strcmp(identityMood, "contemplative") == 0 ||
        strcmp(identityMood, "content") == 0 ||
        strcmp(identityMood, "curious") == 0 ||
        strcmp(identityMood, "serene") == 0) {
        moodCategory = MOOD_HAPPY;
    } else if (strcmp(identityMood, "concerned") == 0 ||
               strcmp(identityMood, "anxious") == 0 ||
               strcmp(identityMood, "restless") == 0) {
        moodCategory = MOOD_WORRIED;
    } else {
        moodCategory = MOOD_NEUTRAL;
    }
}

// Sensor state — populated by ahtRead() on its own timer so both the
// Velour heartbeat and the local web server read from the same cache.
bool ahtPresent = false;
const char* ahtKindLabel = "unknown";
float ahtTempC = -999.0f;
float ahtHumidityPct = -999.0f;
unsigned long ahtLastReadMs = 0;


// ---------------------------------------------------------------------
// AHT10 / AHT20 sensor probe.
//
// AHT10 and AHT20 share the same I2C address (0x38), the same
// measurement trigger (0xAC 0x33 0x00), and the same 6-byte response
// format. The only difference is the calibration init command:
//
//   AHT10: 0xE1 0x08 0x00
//   AHT20: 0xBE 0x08 0x00
//
// We send AHT10's init first, check the status byte (bit 3 = calibrated).
// If not calibrated, we send the AHT20 init and check again. Whichever
// one succeeds is the chip we have. The actual measurement code is
// shared because the byte layout is identical.
// ---------------------------------------------------------------------

static bool ahtSendInit(uint8_t cmd) {
    Wire.beginTransmission(AHT_ADDR);
    Wire.write(cmd);
    Wire.write(0x08);
    Wire.write(0x00);
    if (Wire.endTransmission() != 0) {
        return false;
    }
    delay(20);
    return true;
}

static uint8_t ahtStatus() {
    Wire.requestFrom((uint8_t)AHT_ADDR, (uint8_t)1);
    if (Wire.available()) {
        return Wire.read();
    }
    return 0xFF;
}

static bool ahtIsCalibrated(uint8_t status) {
    return (status & 0x08) != 0;
}

static bool ahtTriggerAndRead(float& tempC, float& humidityPct) {
    Wire.beginTransmission(AHT_ADDR);
    Wire.write(0xAC);
    Wire.write(0x33);
    Wire.write(0x00);
    if (Wire.endTransmission() != 0) {
        return false;
    }
    delay(85);   // measurement takes ~75ms; 85 is safe margin

    Wire.requestFrom((uint8_t)AHT_ADDR, (uint8_t)6);
    if (Wire.available() < 6) {
        return false;
    }
    uint8_t buf[6];
    for (int i = 0; i < 6; i++) {
        buf[i] = Wire.read();
    }
    if (buf[0] & 0x80) {
        // busy bit still set — measurement not ready
        return false;
    }

    uint32_t rawH = ((uint32_t)buf[1] << 12)
                  | ((uint32_t)buf[2] << 4)
                  | ((uint32_t)buf[3] >> 4);
    uint32_t rawT = ((uint32_t)(buf[3] & 0x0F) << 16)
                  | ((uint32_t)buf[4] << 8)
                  | (uint32_t)buf[5];

    humidityPct = (float)rawH * 100.0f / 1048576.0f;
    tempC       = (float)rawT * 200.0f / 1048576.0f - 50.0f;
    return true;
}

static void ahtSetup() {
    Serial.println();
    Serial.println("[aht] Probing I2C bus for AHT10/AHT20 at 0x38...");

    // ESP8266 default I2C pins: SDA=GPIO4 (D2), SCL=GPIO5 (D1)
    Wire.begin();
    delay(40);  // sensor power-on stabilization

    // Quick presence check.
    Wire.beginTransmission(AHT_ADDR);
    if (Wire.endTransmission() != 0) {
        Serial.println("[aht] No device responded at 0x38. Check wiring (SDA=D2, SCL=D1, VCC=3.3V, GND).");
        ahtPresent = false;
        return;
    }
    Serial.println("[aht] Something is at 0x38.");

    // Try AHT10 init first.
    Serial.println("[aht] Sending AHT10 init (0xE1 0x08 0x00)...");
    if (ahtSendInit(AHT10_INIT_CMD)) {
        uint8_t s = ahtStatus();
        Serial.print("[aht]   status after AHT10 init: 0x");
        Serial.println(s, HEX);
        if (ahtIsCalibrated(s)) {
            Serial.println("[aht]   calibration bit set — chip is AHT10");
            ahtKindLabel = "AHT10";
            ahtPresent = true;
            return;
        }
    } else {
        Serial.println("[aht]   AHT10 init NACK");
    }

    // Fall through: try AHT20 init.
    Serial.println("[aht] Sending AHT20 init (0xBE 0x08 0x00)...");
    if (ahtSendInit(AHT20_INIT_CMD)) {
        uint8_t s = ahtStatus();
        Serial.print("[aht]   status after AHT20 init: 0x");
        Serial.println(s, HEX);
        if (ahtIsCalibrated(s)) {
            Serial.println("[aht]   calibration bit set — chip is AHT20");
            ahtKindLabel = "AHT20";
            ahtPresent = true;
            return;
        }
    } else {
        Serial.println("[aht]   AHT20 init NACK");
    }

    Serial.println("[aht] Could not calibrate the sensor with either init. Reads will likely be invalid.");
    ahtPresent = false;
}

static void ahtRead() {
    if (!ahtPresent) {
        ahtTempC = -999.0f;
        ahtHumidityPct = -999.0f;
        return;
    }
    if (ahtTriggerAndRead(ahtTempC, ahtHumidityPct)) {
        ahtLastReadMs = millis();
    } else {
        // Don't overwrite the last known good reading — the web page
        // keeps showing the last value with an age indicator instead.
        Serial.println("[aht] read failed this tick");
    }
}


// ---------------------------------------------------------------------
// Decision tree download + inference. Optional per-node.
// Downloads the tree from /api/nodes/<slug>/model.json on boot,
// parses it into TinyTree, and runs inference every report cycle.
// Results are reported back in the heartbeat via velour_client.
// ---------------------------------------------------------------------

#ifdef NODE_HAS_DECISION_TREE

static void downloadDecisionTree() {
    if (WiFi.status() != WL_CONNECTED) return;

    String url = velour.baseUrl();
    while (url.endsWith("/")) url.remove(url.length() - 1);
    url += "/api/nodes/";
    url += NODE_SLUG;
    url += "/model.json?token=";
    url += NODE_TOKEN;

    Serial.print("[tree] downloading from ");
    Serial.println(url);

    HTTPClient http;
    WiFiClient client;
#if defined(ESP32)
    http.begin(url);
#elif defined(ESP8266)
    http.begin(client, url);
#endif
    http.setTimeout(15000);
    int status = http.GET();
    if (status != 200) {
        Serial.print("[tree] HTTP ");
        Serial.println(status);
        http.end();
        return;
    }

    String body = http.getString();
    http.end();

    Serial.print("[tree] received ");
    Serial.print(body.length());
    Serial.println(" bytes");

    if (decisionTree.loadFromJson(body.c_str(), body.length())) {
        treeLoaded = true;
        Serial.print("[tree] loaded ");
        Serial.print(decisionTree.nodeCount());
        Serial.print(" nodes, ");
        Serial.print(decisionTree.classCount());
        Serial.println(" classes");
        for (int i = 0; i < decisionTree.classCount(); i++) {
            Serial.print("[tree]   class ");
            Serial.print(i);
            Serial.print(": ");
            Serial.println(decisionTree.className(i));
        }
    } else {
        Serial.println("[tree] parse failed");
    }
}

static void runDecisionTreeInference() {
    if (!treeLoaded) return;

    // Build feature vector — same order as
    // oracle/inference.py:FEATURE_NAMES
    float features[8];
    // mood_group — use 0 (contemplative) as default since the node
    // doesn't know its own mood (that's a Velour-side concept)
    features[0] = 0.0f;
    // tod_group — approximate from hour
    int hour = (millis() / 3600000UL) % 24;  // crude; no RTC
    features[1] = (hour < 11) ? 0.0f : (hour < 17) ? 1.0f : (hour < 22) ? 2.0f : 3.0f;
    // moon_group — unknown on device, use 0
    features[2] = 0.0f;
    // open_concern_count — unknown on device
    features[3] = 0.0f;
    // nodes_total — device doesn't know fleet size
    features[4] = 1.0f;
    // nodes_silent
    features[5] = 0.0f;
    // upcoming_events — unknown
    features[6] = 0.0f;
    // upcoming_holidays — unknown
    features[7] = 0.0f;

    // Override with real sensor data when available
    if (ahtPresent && ahtTempC > -100.0f) {
        // Use temp as a proxy for a more useful feature in the
        // future when per-node lobes are trained on real data.
        // For now this just exercises the inference path.
        features[0] = ahtTempC / 10.0f;  // scale to ~2.0 range
    }

    lastPrediction = decisionTree.predict(features);
    lastConfidence = decisionTree.leafSamples();
    if (lastPrediction >= 0) {
        lastClassName = decisionTree.className(lastPrediction);
    } else {
        lastClassName = "?";
    }

    Serial.print("[tree] prediction: ");
    Serial.print(lastClassName);
    Serial.print(" (confidence: ");
    Serial.print(lastConfidence);
    Serial.println(" samples)");
}

#endif  // NODE_HAS_DECISION_TREE


// ---------------------------------------------------------------------
// Identity mood fetch — lightweight GET to /api/nodes/<slug>/identity.json
// to find out how Velour is feeling. Same auth as every other node API
// endpoint (bearer token in the query string).
// ---------------------------------------------------------------------

static void fetchIdentityMood() {
    if (WiFi.status() != WL_CONNECTED) return;

    String url = velour.baseUrl();
    while (url.endsWith("/")) url.remove(url.length() - 1);
    url += "/api/nodes/";
    url += NODE_SLUG;
    url += "/identity.json?token=";
    url += NODE_TOKEN;

    HTTPClient http;
    WiFiClient client;
#if defined(ESP32)
    http.begin(url);
#elif defined(ESP8266)
    http.begin(client, url);
#endif
    http.setTimeout(10000);
    int status = http.GET();
    if (status != 200) {
        Serial.print("[mood] HTTP ");
        Serial.println(status);
        http.end();
        return;
    }

    String body = http.getString();
    http.end();

    // Minimal JSON parse — we only need "mood" and "mood_intensity".
    // The response is small and shaped like:
    //   {"mood": "contemplative", "mood_intensity": 0.72, "name": "Velour"}
    // Hand-parsing avoids pulling in ArduinoJson.
    int moodIdx = body.indexOf("\"mood\"");
    if (moodIdx < 0) return;
    int colonIdx = body.indexOf(':', moodIdx + 5);
    if (colonIdx < 0) return;
    int quoteStart = body.indexOf('"', colonIdx);
    if (quoteStart < 0) return;
    int quoteEnd = body.indexOf('"', quoteStart + 1);
    if (quoteEnd < 0 || quoteEnd - quoteStart - 1 <= 0) return;

    String mood = body.substring(quoteStart + 1, quoteEnd);
    mood.toCharArray(identityMood, sizeof(identityMood));

    // Parse mood_intensity (float after "mood_intensity":)
    int intIdx = body.indexOf("\"mood_intensity\"");
    if (intIdx >= 0) {
        int ic = body.indexOf(':', intIdx + 15);
        if (ic >= 0) {
            // Skip whitespace after colon
            int vs = ic + 1;
            while (vs < (int)body.length() && body[vs] == ' ') vs++;
            int ve = vs;
            while (ve < (int)body.length() &&
                   (body[ve] == '.' || (body[ve] >= '0' && body[ve] <= '9')))
                ve++;
            if (ve > vs) {
                identityIntensity = body.substring(vs, ve).toFloat();
            }
        }
    }

    moodFetched = true;
    categorizeMood();

    Serial.print("[mood] ");
    Serial.print(identityMood);
    Serial.print(" (intensity ");
    Serial.print(identityIntensity, 2);
    Serial.println(")");
}


// ---------------------------------------------------------------------
// OLED display — optional per-node. Software I2C pins, 128x64
// SSD1306. Renders a tiny dashboard: slug + IP + fw version at the
// top, live temp/humidity in big digits if the AHT is present,
// uptime + rssi at the bottom.
// ---------------------------------------------------------------------

#ifdef NODE_HAS_OLED

static void oledSetup() {
    u8g2.begin();
    u8g2.setContrast(180);
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_4x6_mr);
    u8g2.setFontPosTop();
    u8g2.drawStr(0, 0, "booting...");
    u8g2.sendBuffer();
    Serial.println("[oled] initialized");
}

// Called from loop() at a modest cadence — redrawing at 60 fps is
// pointless for a status page and would burn CPU cycles that the
// web server and velour client need.
static unsigned long lastOledRedrawAt = 0;
#ifdef NODE_HAS_LORA
#define OLED_REDRAW_INTERVAL_MS 33   // ~30fps for smooth ticker scrolling
#else
#define OLED_REDRAW_INTERVAL_MS 500  // other nodes: low-power 2fps
#endif

static void oledRedraw() {
    if (millis() - lastOledRedrawAt < OLED_REDRAW_INTERVAL_MS) return;
    lastOledRedrawAt = millis();

    // ---- Display: SSD1306 128x64 ----
    // Coordinates: (0,0) = top-left, x: 0-127, y: 0-63
    // Using setFontPosTop() so y = top edge of glyph (not baseline).
    //
    // Font: u8g2_font_4x6_tf — 4px wide, 6px total height.
    // With setFontPosTop(), each glyph occupies y to y+5 (6 rows).
    // Line spacing: 10px → 6 lines at y = 0, 10, 20, 30, 40, 50.
    // Bottom of last line: 50+5 = 55, leaving 8px margin at bottom.
    // Max chars per full line: 128/4 = 32.
    // Sprite at x=112 → lines 2-3 text stops at x=108 → 27 chars.
    //
    // Sprite: 14px wide at x=114, starts y=10, spans to y=24.

    // u8g2_font_4x6_mr: 4px wide monospaced, 6px cell height, reduced
    // ASCII (32-127). Guaranteed fixed-width on the 128x64 SSD1306.
    //
    // setFontPosTop() makes y = top edge of glyph. Each glyph is 6px
    // tall. Line spacing of 11px guarantees 5px gap between lines.
    // 5 lines at y = 0, 11, 22, 33, 44. Bottom of last: 44+5 = 49.
    // Remaining 15px (y=50-63) is empty bottom margin.
    // Max chars per line: 128 / 4 = 32.
    // Lines 2-3 near sprite: 108 / 4 = 27 chars max.
    u8g2.setFont(u8g2_font_4x6_mr);
    u8g2.setFontPosTop();

    // Line 1 (y=0): node name + version — single string
    {
        static char line1[33];
        snprintf(line1, sizeof(line1), "%s %s", NODE_SLUG, FIRMWARE_VERSION);
        u8g2.drawStr(0, 0, line1);
    }

    // Line 2 (y=11): IP + rssi
    if (WiFi.status() == WL_CONNECTED) {
        static char ipline[33];
        WiFi.localIP().toString().toCharArray(ipline, 16);
        // Append rssi to IP line to save a row
        {
            int len = strlen(ipline);
            snprintf(ipline + len, sizeof(ipline) - len,
                     " rssi %d", WiFi.RSSI());
        }
        u8g2.drawStr(0, 10, ipline);
    } else {
        u8g2.drawStr(0, 10, "no wifi");
    }

    // Line 3 (y=22): Identity mood
    if (moodFetched) {
        static char mbuf[28];
        snprintf(mbuf, sizeof(mbuf), "mood: %s", identityMood);
        u8g2.drawStr(0, 22, mbuf);
    }

    // Line 4 (y=33): decision tree
#ifdef NODE_HAS_DECISION_TREE
    if (treeLoaded && lastPrediction >= 0) {
        static char dbuf[33];
        snprintf(dbuf, sizeof(dbuf), "AI: %s (%d)",
                 lastClassName, lastConfidence);
        u8g2.drawStr(0, 33, dbuf);
    }
#endif

    // Line 5 (y=44): LoRa status or uptime
#ifdef NODE_HAS_LORA
    {
        static char lbuf[33];
        if (loraReady) {
            snprintf(lbuf, sizeof(lbuf), "LoRa tx:%lu rx:%lu %ddB",
                     loraPacketsSent, loraPacketsRecv, loraLastRssi);
        } else {
            snprintf(lbuf, sizeof(lbuf), "LoRa: offline");
        }
        u8g2.drawStr(0, 44, lbuf);
    }

    // Line 6 (y=55): smooth pixel-scrolling ticker of last received screen.
    // u8g2 accepts negative x — text clips at the display edge.
    // 1px every 25ms = 40px/sec = 10 chars/sec at 4px/char.
    if (loraScreenReady && loraScreenBuf[0]) {
        if (millis() - lastTickerScrollAt >= 5) {
            lastTickerScrollAt = millis();
            loraTickerPx -= 2;
            int totalWidth = strlen(loraScreenBuf) * 4;  // 4px per char
            if (loraTickerPx < -totalWidth) loraTickerPx = 128;
        }
        u8g2.drawStr(loraTickerPx, 55, loraScreenBuf);
    }
#else
    {
        unsigned long upS = (millis() - bootMs) / 1000;
        static char footer[33];
        snprintf(footer, sizeof(footer), "up %lus", upS);
        u8g2.drawStr(0, 44, footer);
    }
#endif

    // --- Animated sprite ---
    //
    // Two styles selected at compile time:
    //   Terry: Space Invaders / Lego robot (yellow head, blue body)
    //   Mabel/Hazel: chibi 1960s flight attendant (NODE_SPRITE_MABEL)
    //
    // Both use the same animation phases: 0=idle, 1=nod, 2=wave, 3=blink
    {
        static uint8_t spriteFrame = 0;
        spriteFrame = (spriteFrame + 1) % 16;
        int phase = spriteFrame / 4;

#ifdef NODE_SPRITE_MABEL
        // ---- Chibi flight attendant (Mabel / Hazel) ----
        // 24px wide, ~32px tall. Enormous kawaii head, tiny body.
        // Cute mini pillbox hat, styled hair with flips, huge sparkle
        // eyes, rosy cheeks, peter-pan collar, fitted dress, tiny shoes.
        int sx = 100;       // x anchor (24px wide, ends at x=123)
        int hy = 0;         // head anchor (20 rows)
        int by = 20;        // body anchor (12 rows)
        int nod = (phase == 1) ? -1 : 0;

        // ---- HEAD (20 rows, chibi oversized) ----

        // Mini pillbox hat (hy+0 to hy+1): small and cute
        u8g2.drawBox(sx + 7, hy + nod, 10, 1);      // hat top
        u8g2.drawBox(sx + 6, hy + nod + 1, 12, 1);   // hat brim

        // Hair top (hy+2 to hy+3): voluminous, rounded
        u8g2.drawBox(sx + 4, hy + nod + 2, 16, 1);
        u8g2.drawBox(sx + 3, hy + nod + 3, 18, 1);

        // Hair + forehead (hy+4 to hy+6)
        u8g2.drawBox(sx + 2, hy + nod + 4, 20, 3);

        // Face + hair frame (hy+7 to hy+15): big round face
        u8g2.drawBox(sx + 1, hy + nod + 7, 22, 9);

        // Eyes (hy+8 to hy+12): huge 6x5 kawaii eyes
        u8g2.setDrawColor(0);
        if (phase == 3) {
            // Blink: happy ^_^ squint
            u8g2.drawBox(sx + 4, hy + nod + 10, 6, 1);
            u8g2.drawPixel(sx + 3, hy + nod + 11);
            u8g2.drawPixel(sx + 10, hy + nod + 11);
            u8g2.drawBox(sx + 14, hy + nod + 10, 6, 1);
            u8g2.drawPixel(sx + 13, hy + nod + 11);
            u8g2.drawPixel(sx + 20, hy + nod + 11);
        } else {
            // Open: 6x5 big sparkly eyes
            u8g2.drawBox(sx + 4, hy + nod + 8, 6, 5);
            u8g2.drawBox(sx + 14, hy + nod + 8, 6, 5);
        }
        u8g2.setDrawColor(1);
        if (phase != 3) {
            // Big sparkle: 3x2 highlight upper-left + 1px lower-right
            u8g2.drawBox(sx + 4, hy + nod + 8, 3, 2);
            u8g2.drawPixel(sx + 9, hy + nod + 12);
            u8g2.drawBox(sx + 14, hy + nod + 8, 3, 2);
            u8g2.drawPixel(sx + 19, hy + nod + 12);
        }

        // Rosy cheeks — 2px blush spots
        u8g2.drawBox(sx + 2, hy + nod + 13, 2, 1);
        u8g2.drawBox(sx + 20, hy + nod + 13, 2, 1);

        // Mouth (hy+14): tiny kawaii mouth — single row
        u8g2.setDrawColor(0);
        if (moodCategory == MOOD_HAPPY) {
            // Happy: ω cat-mouth
            u8g2.drawPixel(sx + 9, hy + nod + 14);
            u8g2.drawPixel(sx + 14, hy + nod + 14);
            u8g2.drawPixel(sx + 11, hy + nod + 15);
            u8g2.drawPixel(sx + 12, hy + nod + 15);
        } else if (moodCategory == MOOD_WORRIED) {
            u8g2.drawBox(sx + 10, hy + nod + 14, 4, 1);
            u8g2.drawPixel(sx + 9, hy + nod + 15);
            u8g2.drawPixel(sx + 14, hy + nod + 15);
        } else {
            u8g2.drawBox(sx + 10, hy + nod + 14, 4, 1);
        }
        u8g2.setDrawColor(1);

        // Chin (hy+16 to hy+17): face rounds off
        u8g2.drawBox(sx + 2, hy + nod + 16, 20, 1);
        u8g2.drawBox(sx + 4, hy + nod + 17, 16, 1);

        // Hair flips (hy+18 to hy+19): cute styled ends
        u8g2.drawBox(sx + 1, hy + nod + 16, 2, 3);   // left hair
        u8g2.drawBox(sx + 21, hy + nod + 16, 2, 3);   // right hair
        u8g2.drawPixel(sx, hy + nod + 18);             // left flip out
        u8g2.drawPixel(sx + 23, hy + nod + 18);        // right flip out
        u8g2.drawPixel(sx, hy + nod + 19);             // left flip tip
        u8g2.drawPixel(sx + 23, hy + nod + 19);        // right flip tip

        // ---- BODY (12 rows, never moves) ----

        // Neck (by+0)
        u8g2.drawBox(sx + 9, by, 6, 1);

        // Peter-pan collar (by+1)
        u8g2.drawBox(sx + 6, by + 1, 12, 1);
        u8g2.drawPixel(sx + 5, by + 1);
        u8g2.drawPixel(sx + 18, by + 1);

        // Fitted dress bodice (by+2 to by+5)
        u8g2.drawBox(sx + 6, by + 2, 12, 4);

        // Arms
        if (phase == 2) {
            u8g2.drawBox(sx + 4, by + 3, 2, 3);
            u8g2.drawPixel(sx + 18, by + 3);
            u8g2.drawPixel(sx + 19, by + 2);
            u8g2.drawPixel(sx + 20, by + 1);
            u8g2.drawPixel(sx + 21, by + 1);
        } else {
            u8g2.drawBox(sx + 4, by + 3, 2, 3);
            u8g2.drawBox(sx + 18, by + 3, 2, 3);
        }

        // Cute short skirt (by+6 to by+8): gentle flare
        u8g2.drawBox(sx + 5, by + 6, 14, 1);
        u8g2.drawBox(sx + 4, by + 7, 16, 1);
        u8g2.drawBox(sx + 3, by + 8, 18, 1);

        // Slim legs (by+9 to by+10)
        u8g2.drawBox(sx + 8, by + 9, 2, 2);
        u8g2.drawBox(sx + 14, by + 9, 2, 2);

        // Tiny shoes (by+11)
        u8g2.drawBox(sx + 7, by + 11, 3, 1);
        u8g2.drawBox(sx + 14, by + 11, 3, 1);

#else
        // ---- Terry: Space Invaders / Lego robot ----
        // 20px wide. Head in yellow zone (y=1-15), body in blue (y=16+).
        int sx = 103;
        int hy = 1;
        int by = 16;
        int nod = (phase == 1) ? -1 : 0;

        // Horns
        u8g2.drawPixel(sx + 5, hy + nod);
        u8g2.drawPixel(sx + 5, hy + nod + 1);
        if (phase == 2) {
            u8g2.drawPixel(sx + 13, hy + nod);
            u8g2.drawPixel(sx + 14, hy + nod + 1);
        } else {
            u8g2.drawPixel(sx + 14, hy + nod);
            u8g2.drawPixel(sx + 14, hy + nod + 1);
        }

        // Cranium
        u8g2.drawBox(sx + 3, hy + nod + 2, 14, 1);
        u8g2.drawBox(sx + 2, hy + nod + 3, 16, 1);
        u8g2.drawBox(sx + 1, hy + nod + 4, 18, 2);

        // Eyes
        u8g2.drawBox(sx + 1, hy + nod + 6, 18, 4);
        u8g2.setDrawColor(0);
        if (phase == 3) {
            u8g2.drawBox(sx + 3, hy + nod + 7, 5, 1);
            u8g2.drawPixel(sx + 2, hy + nod + 8);
            u8g2.drawPixel(sx + 8, hy + nod + 8);
            u8g2.drawBox(sx + 12, hy + nod + 7, 5, 1);
            u8g2.drawPixel(sx + 11, hy + nod + 8);
            u8g2.drawPixel(sx + 17, hy + nod + 8);
        } else {
            u8g2.drawBox(sx + 3, hy + nod + 6, 5, 4);
            u8g2.drawBox(sx + 12, hy + nod + 6, 5, 4);
        }
        u8g2.setDrawColor(1);
        if (phase != 3) {
            u8g2.drawBox(sx + 3, hy + nod + 6, 2, 2);
            u8g2.drawBox(sx + 12, hy + nod + 6, 2, 2);
        }

        // Mouth
        u8g2.drawBox(sx + 1, hy + nod + 10, 18, 3);
        u8g2.setDrawColor(0);
        if (moodCategory == MOOD_HAPPY) {
            u8g2.drawPixel(sx + 7, hy + nod + 10);
            u8g2.drawPixel(sx + 12, hy + nod + 10);
            u8g2.drawBox(sx + 8, hy + nod + 11, 4, 1);
        } else if (moodCategory == MOOD_WORRIED) {
            u8g2.drawBox(sx + 8, hy + nod + 10, 4, 1);
            u8g2.drawPixel(sx + 7, hy + nod + 11);
            u8g2.drawPixel(sx + 12, hy + nod + 11);
        } else {
            u8g2.drawBox(sx + 8, hy + nod + 11, 4, 1);
        }
        u8g2.setDrawColor(1);

        // Jaw
        u8g2.drawBox(sx + 2, hy + nod + 13, 16, 1);
        u8g2.drawBox(sx + 3, hy + nod + 14, 14, 1);

        // Body
        u8g2.drawBox(sx + 6, by, 8, 1);
        u8g2.drawBox(sx + 2, by + 1, 16, 7);
        if (phase == 2) {
            u8g2.drawBox(sx, by + 4, 2, 4);
            u8g2.drawPixel(sx + 18, by + 3);
            u8g2.drawPixel(sx + 19, by + 2);
            u8g2.drawPixel(sx + 19, by + 1);
        } else {
            u8g2.drawBox(sx, by + 4, 2, 4);
            u8g2.drawBox(sx + 18, by + 4, 2, 4);
        }
        u8g2.drawBox(sx + 3, by + 8, 14, 1);
        u8g2.drawBox(sx + 4, by + 9, 4, 1);
        u8g2.drawBox(sx + 12, by + 9, 4, 1);
        u8g2.drawBox(sx + 3, by + 10, 4, 1);
        u8g2.drawBox(sx + 13, by + 10, 4, 1);
        u8g2.drawBox(sx + 2, by + 11, 4, 1);
        u8g2.drawBox(sx + 14, by + 11, 4, 1);
        u8g2.drawBox(sx + 1, by + 12, 5, 1);
        u8g2.drawBox(sx + 14, by + 12, 5, 1);
#endif
    }

    // --- QR code (32x32 area, bottom-right) ---
    // QR Version 1 = 21x21 modules. Drawn at 1px per module, centered
    // in the 32x32 area with a quiet zone border. Generated once on
    // boot, cached as pixel flags.
    {
        static bool qrReady = false;
        static uint8_t qrPixels[21 * 3];  // 21 rows × 21 bits → 3 bytes/row
        if (!qrReady) {
            QRCode qrcode;
            uint8_t qrcodeData[qrcode_getBufferSize(1)];
            qrcode_initText(&qrcode, qrcodeData, 1, ECC_LOW, "http://h8r.nl");
            // Pack into bit array for fast redraw
            for (int y = 0; y < 21; y++) {
                qrPixels[y * 3] = 0;
                qrPixels[y * 3 + 1] = 0;
                qrPixels[y * 3 + 2] = 0;
                for (int x = 0; x < 21; x++) {
                    if (qrcode_getModule(&qrcode, x, y)) {
                        qrPixels[y * 3 + (x / 8)] |= (1 << (x % 8));
                    }
                }
            }
            qrReady = true;
        }
        // Draw centered in 32x32 area at (96, 29) — shifted up 3px to clear ticker.
        int qx = 96 + 5;
        int qy = 29 + 5;
        for (int row = 0; row < 21; row++) {
            for (int col = 0; col < 21; col++) {
                if (qrPixels[row * 3 + (col / 8)] & (1 << (col % 8))) {
                    u8g2.drawPixel(qx + col, qy + row);
                }
            }
        }
    }

    u8g2.sendBuffer();
}

#endif  // NODE_HAS_OLED


// ---------------------------------------------------------------------
// Local web server — serves a small self-contained HTML page (embedded
// in PROGMEM to keep it out of RAM) that polls /data.json every second
// and renders Gary's current temperature + humidity in the browser.
// ---------------------------------------------------------------------

// Raw string literal — PROGMEM-stored HTML+CSS+JS. Total size targeted
// well under the 50KB ceiling (actual: ~2-3KB). Single file, no external
// resources, no CDN, works entirely off Gary's flash.
static const char INDEX_HTML[] PROGMEM = R"HTML(<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gary — live</title>
<style>
  html, body { margin: 0; padding: 0; background: #0d1117; color: #c9d1d9;
               font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }
  .wrap { max-width: 560px; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.1rem; font-weight: 500; color: #8b949e; margin: 0 0 1.5rem; }
  .big { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 1.2rem 1.4rem; }
  .card .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
                 color: #6e7681; }
  .card .value { font-size: 2.8rem; font-weight: 300; color: #58a6ff;
                 line-height: 1.1; margin-top: 0.25rem;
                 font-variant-numeric: tabular-nums; }
  .card .unit { font-size: 1rem; color: #8b949e; margin-left: 0.2rem; }
  .mood { margin-top: 1rem; background: #161b22; border: 1px solid #30363d;
          border-radius: 8px; padding: 0.8rem 1.2rem; }
  .mood .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
                 color: #6e7681; }
  .mood .value { font-size: 1.4rem; font-weight: 300; color: #d2a8ff;
                 line-height: 1.3; margin-top: 0.15rem; }
  .mood .intensity { font-size: 0.78rem; color: #6e7681;
                     font-family: ui-monospace, Menlo, monospace; margin-top: 0.2rem; }
  .meta { margin-top: 1.5rem; font-size: 0.78rem; color: #6e7681;
          font-family: ui-monospace, Menlo, monospace; line-height: 1.6; }
  .meta span { color: #8b949e; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
         background: #2ea043; margin-right: 0.4rem; vertical-align: middle;
         animation: p 1.4s ease-in-out infinite; }
  @keyframes p { 0%,100% { opacity: 0.35 } 50% { opacity: 1 } }
  .stale .value { color: #6e7681; }
  .stale .dot { background: #d29922; animation: none; }
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot" id="dot"></span><span id="status">connecting…</span></h1>
  <div class="big">
    <div class="card" id="tempcard">
      <div class="label">Temperature</div>
      <div class="value"><span id="temp">—</span><span class="unit">°C</span></div>
    </div>
    <div class="card" id="humcard">
      <div class="label">Humidity</div>
      <div class="value"><span id="hum">—</span><span class="unit">%</span></div>
    </div>
  </div>
  <div class="mood" id="moodcard" style="display:none">
    <div class="label">Velour's mood</div>
    <div class="value" id="mood">—</div>
    <div class="intensity">intensity <span id="mood_int">—</span></div>
  </div>
  <div class="meta">
    <div><span>sensor</span> <span id="sensor">—</span></div>
    <div><span>firmware</span> <span id="fw">—</span></div>
    <div><span>uptime</span> <span id="uptime">—</span></div>
    <div><span>rssi</span> <span id="rssi">—</span> dBm</div>
    <div><span>heap</span> <span id="heap">—</span> bytes</div>
    <div><span>last reading</span> <span id="age">—</span></div>
  </div>
</div>
<script>
function fmt(n, d) { return (typeof n === 'number') ? n.toFixed(d) : '—'; }
function ageText(s) {
  if (s < 0) return '—';
  if (s < 2) return 'just now';
  if (s < 60) return s.toFixed(0) + 's ago';
  return Math.floor(s/60) + 'm ago';
}
function uptimeText(s) {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  var h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + 'h ' + m + 'm';
}
async function poll() {
  try {
    var r = await fetch('/data.json', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var d = await r.json();
    document.getElementById('status').textContent = 'live';
    document.getElementById('temp').textContent = fmt(d.temp_c, 2);
    document.getElementById('hum').textContent  = fmt(d.humidity, 1);
    document.getElementById('sensor').textContent = d.sensor || '—';
    document.getElementById('fw').textContent = d.fw || '—';
    document.getElementById('uptime').textContent = uptimeText(d.uptime_s || 0);
    document.getElementById('rssi').textContent = d.rssi != null ? d.rssi : '—';
    document.getElementById('heap').textContent = d.free_heap != null ? d.free_heap : '—';
    if (d.identity_mood) {
      document.getElementById('moodcard').style.display = '';
      document.getElementById('mood').textContent = d.identity_mood;
      document.getElementById('mood_int').textContent = fmt(d.identity_intensity, 2);
    }
    var ageS = (d.last_read_ms_ago || 0) / 1000;
    document.getElementById('age').textContent = ageText(ageS);
    var stale = ageS > 10;
    document.getElementById('tempcard').classList.toggle('stale', stale);
    document.getElementById('humcard').classList.toggle('stale', stale);
  } catch (e) {
    document.getElementById('status').textContent = 'offline — retry…';
  }
}
poll();
setInterval(poll, 1000);
</script>
</body>
</html>)HTML";


static void handleRoot() {
    httpd.send_P(200, PSTR("text/html; charset=utf-8"), INDEX_HTML);
}

static void handleDataJson() {
    // Hand-rolled JSON so we don't pull in ArduinoJson. The shape is
    // tiny and fixed, and we already have a similar pattern for the
    // Velour payload in velour_client.cpp.
    unsigned long now = millis();
    unsigned long ageMs = (ahtLastReadMs > 0) ? (now - ahtLastReadMs) : 0;

    String s;
    s.reserve(256);
    s = "{\"temp_c\":";
    s += (ahtPresent && ahtTempC > -100.0f) ? String(ahtTempC, 2) : "null";
    s += ",\"humidity\":";
    s += (ahtPresent && ahtHumidityPct > -100.0f) ? String(ahtHumidityPct, 1) : "null";
    s += ",\"sensor\":\"";
    s += ahtKindLabel;
    s += "\",\"fw\":\"";
    s += FIRMWARE_VERSION;
    s += "\",\"uptime_s\":";
    s += String(now / 1000);
    s += ",\"free_heap\":";
    s += String(ESP.getFreeHeap());
    s += ",\"rssi\":";
    s += (WiFi.status() == WL_CONNECTED) ? String(WiFi.RSSI()) : "null";
    s += ",\"last_read_ms_ago\":";
    s += String(ageMs);
    if (moodFetched) {
        s += ",\"identity_mood\":\"";
        s += identityMood;
        s += "\",\"identity_intensity\":";
        s += String(identityIntensity, 2);
    }

#ifdef NODE_HAS_DECISION_TREE
    s += ",\"tree_loaded\":";
    s += treeLoaded ? "true" : "false";
    s += ",\"tree_nodes\":";
    s += String(decisionTree.nodeCount());
    s += ",\"tree_classes\":";
    s += String(decisionTree.classCount());
    if (lastPrediction >= 0) {
        s += ",\"tree_prediction\":\"";
        s += lastClassName;
        s += "\",\"tree_confidence\":";
        s += String(lastConfidence);
    }
#endif

    s += "}";

    httpd.sendHeader("Cache-Control", "no-store");
    httpd.send(200, "application/json", s);
}

static void handleNotFound() {
    httpd.send(404, "text/plain", "not found");
}

static void httpdSetup() {
    httpd.on("/",          HTTP_GET, handleRoot);
    httpd.on("/data.json", HTTP_GET, handleDataJson);
    httpd.onNotFound(handleNotFound);
    httpd.begin();
    Serial.print("[httpd] listening on http://");
    Serial.print(WiFi.localIP());
    Serial.print(":");
    Serial.print(NODE_HTTP_PORT);
    Serial.println("/");

    // mDNS so the page is reachable at http://<slug>.local:<port>/ from
    // any device on the same Wi-Fi, without having to look up the IP.
    // Gary's hostname on the LAN becomes NODE_SLUG.local. Non-port-80
    // nodes need the explicit port in the URL (browsers don't honor the
    // port hint from mDNS service discovery on their own).
    if (MDNS.begin(NODE_SLUG)) {
        MDNS.addService("http", "tcp", NODE_HTTP_PORT);
        Serial.print("[mdns] registered http://");
        Serial.print(NODE_SLUG);
        Serial.print(".local");
        if (NODE_HTTP_PORT != 80) {
            Serial.print(":");
            Serial.print(NODE_HTTP_PORT);
        }
        Serial.println("/");
    } else {
        Serial.println("[mdns] failed to register — use the IP directly.");
    }
}


// ---------------------------------------------------------------------
// Wi-Fi setup with verbose status reporting.
// ---------------------------------------------------------------------

static void connectWiFi() {
    Serial.println();
    Serial.println("[wifi] Connecting to: " + String(WIFI_SSID));
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > 30000) {
            Serial.println();
            Serial.println("[wifi] FAILED — 30s timeout. Check SSID + password.");
            Serial.print("[wifi] Status code: ");
            Serial.println(WiFi.status());
            return;
        }
        delay(500);
        Serial.print('.');
    }

    Serial.println();
    Serial.print("[wifi] Connected. Local IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("[wifi] Gateway:           ");
    Serial.println(WiFi.gatewayIP());
    Serial.print("[wifi] DNS:               ");
    Serial.println(WiFi.dnsIP());
    Serial.print("[wifi] RSSI:              ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
}


// ---------------------------------------------------------------------
// Verbose Velour report wrapper. Logs the request, the HTTP status,
// the pending count after, and the elapsed time.
// ---------------------------------------------------------------------

// ---------------------------------------------------------------------
// OTA check wrapper. Logs the result of the check — if an update is
// available, velour.checkForUpdate() won't return (the ESP reboots into
// the new firmware mid-call).
// ---------------------------------------------------------------------

static void velourOtaCheck(const char* reason) {
    Serial.println();
    Serial.print("[ota] ");
    Serial.print(reason);
    Serial.println(" — checking for update...");
    VelourClient::OtaResult r = velour.checkForUpdate();
    switch (r) {
        case VelourClient::VELOUR_OTA_UP_TO_DATE:
            Serial.println("[ota] up to date.");
            break;
        case VelourClient::VELOUR_OTA_NO_FIRMWARE:
            Serial.println("[ota] no firmware assigned to this hardware profile.");
            break;
        case VelourClient::VELOUR_OTA_NO_NETWORK:
            Serial.println("[ota] no network — will retry next interval.");
            break;
        case VelourClient::VELOUR_OTA_CHECK_FAILED:
            Serial.println("[ota] check failed — HTTP or parse error.");
            break;
        case VelourClient::VELOUR_OTA_UPDATE_FAILED:
            Serial.print("[ota] update attempted but failed: ");
#if defined(ESP8266)
            Serial.println(ESPhttpUpdate.getLastErrorString());
#else
            Serial.println(httpUpdate.getLastErrorString());
#endif
            break;
    }
}


static void velourReport(const char* label) {
    int pendingBefore = velour.pending();
    unsigned long t0 = millis();
    int status = velour.report();
    unsigned long elapsed = millis() - t0;

    Serial.println();
    Serial.print("[velour] ");
    Serial.print(label);
    Serial.print(" → POST ");
    Serial.print(velour.baseUrl());
    Serial.print("/api/nodes/");
    Serial.print(NODE_SLUG);
    Serial.println("/report/");
    Serial.print("[velour] pending before: ");
    Serial.println(pendingBefore);
    Serial.print("[velour] HTTP status:    ");
    Serial.println(status);
    Serial.print("[velour] elapsed:        ");
    Serial.print(elapsed);
    Serial.println(" ms");

    switch (status) {
        case 200:
            Serial.println("[velour] OK — readings stored.");
            break;
        case 401:
            Serial.println("[velour] UNAUTHORIZED — token mismatch. Check NODE_TOKEN.");
            break;
        case 403:
            Serial.println("[velour] FORBIDDEN — node is disabled in Velour.");
            break;
        case 404:
            Serial.println("[velour] NOT FOUND — slug mismatch. Check NODE_SLUG.");
            break;
        case -1:
            Serial.println("[velour] CLIENT ERROR — no Wi-Fi or DNS or unreachable host.");
            break;
        default:
            Serial.println("[velour] Unexpected status. See Velour logs.");
    }
}


// ---------------------------------------------------------------------
// LoRa — ping/pong between Mabel (sender) and Hazel (receiver)
// ---------------------------------------------------------------------

#ifdef NODE_HAS_LORA

// Generate 2000 random A-Za-z0-9 characters for testing
static void loraGenerateTestScreen(char* buf, int len) {
    static const char charset[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    for (int i = 0; i < len - 1; i++) {
        buf[i] = charset[random(sizeof(charset) - 1)];
    }
    buf[len - 1] = '\0';
}

static void loraSetup() {
    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
    LoRa.setPins(LORA_CS, LORA_RST, LORA_DIO0);
    if (LoRa.begin(LORA_FREQ)) {
        LoRa.setSpreadingFactor(7);
        LoRa.setSignalBandwidth(125E3);
        LoRa.setCodingRate4(5);
        LoRa.setTxPower(2);  // low power (2dBm) to reduce current draw
        loraReady = true;
        // Offset the first send so the twins don't transmit simultaneously
        lastLoraScreenAt = millis() - LORA_SCREEN_INTERVAL_MS + LORA_SCREEN_OFFSET_MS;
        Serial.println("[lora] initialized at 868 MHz");
        Serial.print("[lora] first screen send in ");
        Serial.print(LORA_SCREEN_OFFSET_MS / 1000);
        Serial.println("s");
        snprintf(loraScreenBuf, LORA_SCREEN_SIZE,
                 "  ~~~ waiting for LoRa transmission from twin ~~~  "
                 "  %s is online at 868 MHz, SF7, 125kHz BW.  ",
                 NODE_SLUG);
    } else {
        Serial.println("[lora] FAILED to initialize");
    }
}

static void loraLoop() {
    if (!loraReady) return;

    // --- Receive: type-tagged packets ---
    int packetSize = LoRa.parsePacket();
    if (packetSize >= 2) {
        uint8_t pktType = LoRa.read();
        loraLastRssi = LoRa.packetRssi();
        loraPacketsRecv++;

        if (pktType == LORA_PKT_SCREEN && packetSize >= 4) {
            // Screen fragment: [type][seq][total][payload...]
            uint8_t seq = LoRa.read();
            uint8_t total = LoRa.read();

            if (seq == 0) {
                loraRxFragCount = 0;
                loraRxFragTotal = total;
                loraRxFragLen = 0;
            }
            while (LoRa.available() && loraRxFragLen < sizeof(loraRxFragBuf)) {
                loraRxFragBuf[loraRxFragLen++] = LoRa.read();
            }
            loraRxFragCount++;

            Serial.print("[lora] frag ");
            Serial.print(seq + 1);
            Serial.print("/");
            Serial.print(total);
            Serial.print(" (");
            Serial.print(loraRxFragLen);
            Serial.print(" bytes) rssi=");
            Serial.println(loraLastRssi);

            if (loraRxFragCount >= loraRxFragTotal) {
                Serial.print("[lora] all ");
                Serial.print(loraRxFragTotal);
                Serial.print(" fragments, ");
                Serial.print(loraRxFragLen);
                Serial.println(" bytes");

                // Try decompress; fall back to raw
                static uint8_t decompBuf[LORA_SCREEN_SIZE + 64];
                size_t decompLen = loraDecompress(
                    loraRxFragBuf, loraRxFragLen,
                    decompBuf, sizeof(decompBuf));
                if (decompLen > 0 && decompLen < LORA_SCREEN_SIZE) {
                    memcpy(loraScreenBuf, decompBuf, decompLen);
                    loraScreenBuf[decompLen] = '\0';
                    Serial.print("[lora] decompressed: ");
                    Serial.println(decompLen);
                } else if (loraRxFragLen > 0 && loraRxFragLen < LORA_SCREEN_SIZE) {
                    memcpy(loraScreenBuf, loraRxFragBuf, loraRxFragLen);
                    loraScreenBuf[loraRxFragLen] = '\0';
                    Serial.print("[lora] raw fallback: ");
                    Serial.println(loraRxFragLen);
                } else {
                    Serial.println("[lora] discard — too large or empty");
                    loraRxFragLen = 0;
                    loraRxFragCount = 0;
                    return;
                }
                loraScreenReady = true;
                loraTickerPx = 128;
                loraScreensRecv++;
                loraRxFragLen = 0;
                loraRxFragCount = 0;
            }
        } else {
            // Beacon or ACK: [type][text...]
            int i = 0;
            while (LoRa.available() && i < (int)sizeof(loraLastMsg) - 1) {
                loraLastMsg[i++] = (char)LoRa.read();
            }
            loraLastMsg[i] = '\0';
            Serial.print("[lora] recv: ");
            Serial.print(loraLastMsg);
            Serial.print(" rssi=");
            Serial.println(loraLastRssi);
        }
        velour.addReading("lora_rx", (float)loraPacketsRecv);
        velour.addReading("lora_rssi", (float)loraLastRssi);
    }

    // --- Send: 2000-char screen at the node's interval ---
    if (millis() - lastLoraScreenAt >= LORA_SCREEN_INTERVAL_MS) {
        lastLoraScreenAt = millis();
        static char txScreen[LORA_SCREEN_SIZE];
        loraGenerateTestScreen(txScreen, LORA_SCREEN_SIZE);
        int pkts = loraSendCompressed(txScreen, strlen(txScreen));
        // Force radio back to receive mode after transmitting
        LoRa.receive();
        if (pkts > 0) {
            Serial.print("[lora] sent screen: ");
            Serial.print(pkts);
            Serial.println(" packets, back to RX mode");
            velour.addReading("lora_tx", (float)loraPacketsSent);
        }
    }
}

#endif  // NODE_HAS_LORA


// ---------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println();
    Serial.println("===========================================");
    Serial.println("  velour test sketch for gary (ESP8266)");
    Serial.print  ("  firmware: ");
    Serial.println(FIRMWARE_VERSION);
    Serial.print  ("  velour:   ");
    Serial.println(VELOUR_URL);
    Serial.print  ("  node:     ");
    Serial.println(NODE_SLUG);
    Serial.println("===========================================");

    bootMs = millis();
#ifdef NODE_HAS_HEARTBEAT
    pinMode(LED_BUILTIN, OUTPUT);
#endif
#ifdef NODE_HAS_OLED
    oledSetup();
#endif
    ahtSetup();
    connectWiFi();

    velour.setFirmwareVersion(FIRMWARE_VERSION);

    // Discover Velour's actual port — it may not be on the default if
    // another process was holding that port when Velour last started.
    velour.discover();

    // Bring up the local web server. This is purely additive — it
    // coexists with the Velour reporting + OTA flow without interfering.
    // Gary is now reachable at http://<his-LAN-IP>/ from any device on
    // the same Wi-Fi network.
    httpdSetup();

#ifdef NODE_HAS_LORA
    loraSetup();
#endif

    // Seed the AHT cache with one reading so /data.json isn't empty
    // from the moment the web server comes up.
    ahtRead();

#ifdef NODE_HAS_DECISION_TREE
    // Download the trained decision tree from Velour's model.json
    // endpoint. This is the edge-AI deployment path: Velour trains
    // centrally, the node downloads the result, and runs inference
    // locally.
    downloadDecisionTree();
#endif

    // Fetch Identity's mood on boot so the OLED has something to show
    // before the first periodic fetch fires.
    fetchIdentityMood();
    lastMoodFetchAt = millis();

    // Send one reading immediately so something lands in the Velour UI
    // within seconds of boot, not at the first 30-second tick.
    velour.addReading("boot", 1.0f);
    if (ahtPresent) {
        velour.addReading("aht_present", 1.0f);
    }
    velourReport("BOOT");

    // Opportunistic OTA check shortly after boot. If a newer firmware
    // has been uploaded while this one was offline, we pick it up on
    // the first post-boot wake — no need to wait an hour. If the call
    // finds an update, it never returns (ESP reboots).
    delay(2000);
    velourOtaCheck("boot");
    lastOtaCheckAt = millis();
}


// ---------------------------------------------------------------------
// Loop
// ---------------------------------------------------------------------

void loop() {
    // Service the local web server on every loop tick. This is the
    // ESP8266WebServer pattern: handleClient() must be called frequently
    // or incoming connections stall. It's non-blocking — returns
    // immediately if there's nothing to do.
    httpd.handleClient();
#if defined(ESP8266)
    MDNS.update();  // ESP32 mDNS doesn't need this
#endif

#ifdef NODE_HAS_OLED
    oledRedraw();
#endif

#ifdef NODE_HAS_HEARTBEAT
    {
        unsigned long phase = millis() % 830;
        bool on = (phase < 80) || (phase >= 180 && phase < 300);
        digitalWrite(LED_BUILTIN, on ? LOW : HIGH);
    }
#endif

#ifdef NODE_HAS_LORA
    loraLoop();
#endif

    // Faster AHT read on its own cadence, decoupled from Velour reporting.
    // Both the web page and the Velour heartbeat read from the same cache
    // (ahtTempC / ahtHumidityPct), so the Velour report at 30s intervals
    // always has a value that's at most AHT_READ_INTERVAL_MS stale.
    if (millis() - lastAhtReadAt >= AHT_READ_INTERVAL_MS) {
        lastAhtReadAt = millis();
        ahtRead();
    }

    // Periodic Identity mood fetch — keeps the OLED sprite in sync with
    // Velour's emotional state.
    if (millis() - lastMoodFetchAt >= MOOD_FETCH_INTERVAL_MS) {
        lastMoodFetchAt = millis();
        fetchIdentityMood();
    }

    if (millis() - lastReportAt >= REPORT_INTERVAL_MS) {
        lastReportAt = millis();
        reportCount += 1;

        float test_pulse = (float)(reportCount % 100);

        Serial.println();
        Serial.print("[aht] kind: ");
        Serial.print(ahtKindLabel);
        Serial.print("  temp: ");
        Serial.print(ahtTempC, 2);
        Serial.print("°C  humidity: ");
        Serial.print(ahtHumidityPct, 2);
        Serial.println("%");

        if (ahtPresent && ahtTempC > -100.0f) {
            velour.addReading("aht_temp_c",   ahtTempC);
            velour.addReading("aht_humidity", ahtHumidityPct);
        }
        velour.addReading("test_pulse", test_pulse);
        velour.addReading("ota_delivered", 2.0f);

#ifdef NODE_HAS_DECISION_TREE
        // Run inference on the loaded decision tree and report the
        // decision back to Velour alongside the sensor readings.
        runDecisionTreeInference();
        if (lastPrediction >= 0) {
            velour.addReading("tree_prediction", (float)lastPrediction);
            velour.addReading("tree_confidence", (float)lastConfidence);
        }
#endif

        char label[32];
        snprintf(label, sizeof(label), "tick #%d", reportCount);
        velourReport(label);
    }

    // Periodic OTA check, once per OTA_CHECK_INTERVAL_MS.
    if (millis() - lastOtaCheckAt >= OTA_CHECK_INTERVAL_MS) {
        lastOtaCheckAt = millis();
        velourOtaCheck("periodic");
    }

    // If Wi-Fi drops, try to reconnect. (autoReconnect handles most of
    // this, but the explicit check makes serial output clearer.)
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[wifi] dropped — reconnecting");
        connectWiFi();
    }

    // Short delay keeps the CPU from spinning but still lets handleClient()
    // respond within ~30ms, which is imperceptible in the browser.
    delay(30);
}

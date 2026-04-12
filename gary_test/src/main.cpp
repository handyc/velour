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
#include <ESP8266WebServer.h>
#include <ESP8266mDNS.h>
#include "wifi_secrets.h"
#include "velour_client.h"

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
  #ifndef NODE_OLED_SCL
    #define NODE_OLED_SCL 14
  #endif
  #ifndef NODE_OLED_SDA
    #define NODE_OLED_SDA 12
  #endif
  U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(
      U8G2_R0, NODE_OLED_SCL, NODE_OLED_SDA, U8X8_PIN_NONE);
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
#define FIRMWARE_VERSION    "gary-test-0.3.2-local-web"

#define AHT_ADDR        0x38
#define AHT10_INIT_CMD  0xE1
#define AHT20_INIT_CMD  0xBE

VelourClient velour(VELOUR_URL, NODE_SLUG, NODE_TOKEN);
ESP8266WebServer httpd(NODE_HTTP_PORT);

unsigned long lastReportAt = 0;
unsigned long lastOtaCheckAt = 0;
unsigned long lastAhtReadAt = 0;
unsigned long bootMs = 0;
int reportCount = 0;

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

    String url = VELOUR_URL;
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
    u8g2.setFont(u8g2_font_6x10_tf);
    u8g2.drawStr(0, 10, "Velour node");
    u8g2.drawStr(0, 24, NODE_SLUG);
    u8g2.drawStr(0, 38, FIRMWARE_VERSION);
    u8g2.drawStr(0, 58, "booting...");
    u8g2.sendBuffer();
    Serial.println("[oled] initialized");
}

// Called from loop() at a modest cadence — redrawing at 60 fps is
// pointless for a status page and would burn CPU cycles that the
// web server and velour client need.
static unsigned long lastOledRedrawAt = 0;
#define OLED_REDRAW_INTERVAL_MS 500

static void oledRedraw() {
    if (millis() - lastOledRedrawAt < OLED_REDRAW_INTERVAL_MS) return;
    lastOledRedrawAt = millis();

    u8g2.clearBuffer();

    // Line 1: slug (big) + firmware version (small)
    u8g2.setFont(u8g2_font_6x13B_tf);
    u8g2.drawStr(0, 12, NODE_SLUG);
    u8g2.setFont(u8g2_font_5x8_tf);
    u8g2.drawStr(68, 12, FIRMWARE_VERSION);

    // Line 2: IP address (monospace)
    u8g2.setFont(u8g2_font_5x8_tf);
    if (WiFi.status() == WL_CONNECTED) {
        String ip = WiFi.localIP().toString();
        u8g2.drawStr(0, 23, ip.c_str());
    } else {
        u8g2.drawStr(0, 23, "no wifi");
    }

    // Big temp / humidity block in the middle.
    u8g2.setFont(u8g2_font_logisoso16_tf);
    char tbuf[16];
    char hbuf[16];
    if (ahtPresent && ahtTempC > -100.0f) {
        snprintf(tbuf, sizeof(tbuf), "%.1fC", ahtTempC);
        snprintf(hbuf, sizeof(hbuf), "%.0f%%", ahtHumidityPct);
    } else {
        snprintf(tbuf, sizeof(tbuf), "-- C");
        snprintf(hbuf, sizeof(hbuf), "-- %%");
    }
    u8g2.drawStr(0,  46, tbuf);
    u8g2.drawStr(70, 46, hbuf);

    // Decision tree output (if active)
#ifdef NODE_HAS_DECISION_TREE
    if (treeLoaded && lastPrediction >= 0) {
        u8g2.setFont(u8g2_font_5x8_tf);
        char dbuf[40];
        snprintf(dbuf, sizeof(dbuf), "AI: %s (%d)",
                 lastClassName, lastConfidence);
        u8g2.drawStr(0, 54, dbuf);
    }
#endif

    // Animated sprite — a little happy robot in the top-right corner.
    // Cycles through: neutral → bounce → wave → blink. Drawn with
    // u8g2 primitives (no bitmap data). The frame counter advances
    // on every OLED redraw (500ms), so the animation is ~2 seconds
    // per cycle. Constant resources: no allocation, no timers.
    {
        static uint8_t spriteFrame = 0;
        spriteFrame = (spriteFrame + 1) % 16;  // 16 half-seconds = 8 second cycle
        int phase = spriteFrame / 4;  // 0=neutral, 1=bounce, 2=wave, 3=blink

        int sx = 110;  // top-right corner
        int sy = 1;
        int bounce = (phase == 1) ? -2 : 0;

        // Head
        u8g2.drawCircle(sx + 8, sy + 7 + bounce, 7);

        // Eyes
        if (phase == 3) {
            // Blink — horizontal lines
            u8g2.drawHLine(sx + 4, sy + 6 + bounce, 3);
            u8g2.drawHLine(sx + 10, sy + 6 + bounce, 3);
        } else {
            // Open — dots
            u8g2.drawDisc(sx + 5, sy + 5 + bounce, 1);
            u8g2.drawDisc(sx + 11, sy + 5 + bounce, 1);
        }

        // Smile
        u8g2.drawPixel(sx + 5, sy + 10 + bounce);
        u8g2.drawHLine(sx + 6, sy + 11 + bounce, 5);
        u8g2.drawPixel(sx + 11, sy + 10 + bounce);

        // Body (vertical line from neck)
        int by = sy + 15 + bounce;
        u8g2.drawVLine(sx + 8, by, 6);

        // Arms
        if (phase == 2) {
            // Wave — right arm raised, left arm down
            u8g2.drawLine(sx + 8, by + 1, sx + 15, by - 3);
            u8g2.drawPixel(sx + 15, by - 4);  // hand wave
            u8g2.drawLine(sx + 8, by + 1, sx + 2, by + 4);
        } else {
            // Both arms down
            u8g2.drawLine(sx + 8, by + 1, sx + 3, by + 5);
            u8g2.drawLine(sx + 8, by + 1, sx + 13, by + 5);
        }

        // Legs
        u8g2.drawLine(sx + 8, by + 5, sx + 5, by + 10);
        u8g2.drawLine(sx + 8, by + 5, sx + 11, by + 10);

        // Feet
        u8g2.drawHLine(sx + 3, by + 10, 3);
        u8g2.drawHLine(sx + 10, by + 10, 3);
    }

    // Footer: uptime + rssi
    u8g2.setFont(u8g2_font_5x8_tf);
    unsigned long upS = (millis() - bootMs) / 1000;
    char footer[32];
    if (WiFi.status() == WL_CONNECTED) {
        snprintf(footer, sizeof(footer), "up %lus  rssi %d",
                 upS, WiFi.RSSI());
    } else {
        snprintf(footer, sizeof(footer), "up %lus  offline", upS);
    }
    u8g2.drawStr(0, 62, footer);

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
    Serial.print(VELOUR_URL);
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
#ifdef NODE_HAS_OLED
    oledSetup();
#endif
    ahtSetup();
    connectWiFi();

    velour.setFirmwareVersion(FIRMWARE_VERSION);

    // Bring up the local web server. This is purely additive — it
    // coexists with the Velour reporting + OTA flow without interfering.
    // Gary is now reachable at http://<his-LAN-IP>/ from any device on
    // the same Wi-Fi network.
    httpdSetup();

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
    MDNS.update();

#ifdef NODE_HAS_OLED
    // Redraw the OLED on its own cadence (every 500ms). Non-blocking —
    // it early-returns until the interval has elapsed.
    oledRedraw();
#endif

    // Faster AHT read on its own cadence, decoupled from Velour reporting.
    // Both the web page and the Velour heartbeat read from the same cache
    // (ahtTempC / ahtHumidityPct), so the Velour report at 30s intervals
    // always has a value that's at most AHT_READ_INTERVAL_MS stale.
    if (millis() - lastAhtReadAt >= AHT_READ_INTERVAL_MS) {
        lastAhtReadAt = millis();
        ahtRead();
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

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
#include "wifi_secrets.h"
#include "velour_client.h"

#define REPORT_INTERVAL_MS  (30UL * 1000UL)
#define FIRMWARE_VERSION    "gary-test-0.2.0-aht"

#define AHT_ADDR        0x38
#define AHT10_INIT_CMD  0xE1
#define AHT20_INIT_CMD  0xBE

VelourClient velour(VELOUR_URL, NODE_SLUG, NODE_TOKEN);

unsigned long lastReportAt = 0;
unsigned long bootMs = 0;
int reportCount = 0;

// Sensor state — populated by readAHT() each report cycle.
bool ahtPresent = false;
const char* ahtKindLabel = "unknown";
float ahtTempC = -999.0f;
float ahtHumidityPct = -999.0f;


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
    if (!ahtTriggerAndRead(ahtTempC, ahtHumidityPct)) {
        Serial.println("[aht] read failed this tick");
        ahtTempC = -999.0f;
        ahtHumidityPct = -999.0f;
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
    ahtSetup();
    connectWiFi();

    velour.setFirmwareVersion(FIRMWARE_VERSION);

    // Send one reading immediately so something lands in the Velour UI
    // within seconds of boot, not at the first 30-second tick.
    velour.addReading("boot", 1.0f);
    if (ahtPresent) {
        velour.addReading("aht_present", 1.0f);
    }
    velourReport("BOOT");
}


// ---------------------------------------------------------------------
// Loop
// ---------------------------------------------------------------------

void loop() {
    if (millis() - lastReportAt >= REPORT_INTERVAL_MS) {
        lastReportAt = millis();
        reportCount += 1;

        // Synthetic readings — pure functions of time. Kept for the
        // pulse channel so the Velour UI shows obvious change.
        float ms = (float)(millis() - bootMs);
        float test_pulse         = (float)(reportCount % 100);

        // Real sensor read.
        ahtRead();

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

        char label[32];
        snprintf(label, sizeof(label), "tick #%d", reportCount);
        velourReport(label);
    }

    // If Wi-Fi drops, try to reconnect. (autoReconnect handles most of
    // this, but the explicit check makes serial output clearer.)
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[wifi] dropped — reconnecting");
        connectWiFi();
    }

    delay(100);
}

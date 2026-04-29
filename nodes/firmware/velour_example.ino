// velour_example.ino — minimal sketch showing how to add velour telemetry
// reporting to any ESP8266 or ESP32 project. Drop this file, plus
// velour_client.h and velour_client.cpp, into a new Arduino IDE sketch
// folder, or copy them into an existing project alongside your own .ino.
//
// What this example does:
//   1. Connects to WiFi
//   2. Creates a VelourClient configured for one specific node in velour
//   3. In loop(), reads a couple of sample "sensors" (hard-coded values
//      here — replace with your real sensor reads), queues them as
//      readings, and posts them to velour every 60 seconds.
//
// Your existing firmware — pumps, relays, misting timers, control loops
// — does NOT need to be rewritten. Keep all of that code. Just add:
//
//     #include "velour_client.h"
//     VelourClient velour(...);
//     velour.addReading("my_sensor", value);
//     velour.report();
//
// wherever makes sense in your own loop. The client is additive.

#include "velour_client.h"

// -----------------------------------------------------------------------
// CUSTOMIZE THESE
// -----------------------------------------------------------------------

const char* WIFI_SSID     = "your-wifi-ssid";
const char* WIFI_PASSWORD = "your-wifi-password";

// Point this at your velour instance. Examples:
//   "http://192.168.1.50:7777"         // local dev
//   "https://velour.example.com"           // prod, via nginx
// NO trailing slash, NO /api/nodes path — the client appends that.
const char* VELOUR_URL = "http://192.168.1.50:7777";

// From the velour fleet page: /nodes/<slug>/ — grab the slug and token
// from the detail view. The token is 48 chars; rotating it on the web UI
// invalidates this one.
const char* NODE_SLUG   = "gary";
const char* NODE_TOKEN  = "PASTE_THE_48_CHAR_TOKEN_HERE";

const char* FIRMWARE_VERSION = "gary-example-0.1.0";

const unsigned long REPORT_INTERVAL_MS = 60UL * 1000UL;   // every minute

// -----------------------------------------------------------------------

VelourClient velour(VELOUR_URL, NODE_SLUG, NODE_TOKEN);

unsigned long lastReportAt = 0;


void connectWiFi() {
    Serial.print("Connecting to WiFi");
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        Serial.print(".");
        delay(500);
    }
    Serial.println();
    Serial.print("Connected. IP: ");
    Serial.println(WiFi.localIP());
}


void setup() {
    Serial.begin(115200);
    delay(100);
    connectWiFi();
    velour.setFirmwareVersion(FIRMWARE_VERSION);
    // Send one reading immediately so you see it land in the velour UI
    // within seconds of booting, not at the first REPORT_INTERVAL tick.
    velour.addReading("boot", 1.0f);
    int initStatus = velour.report();
    Serial.print("Initial velour report: HTTP ");
    Serial.println(initStatus);
}


void loop() {
    // ---- Replace these with your real sensor reads. ----
    // The temperature / humidity / soil lines below are pure placeholders
    // so the example is self-contained and won't crash without hardware
    // attached. Real code would read a DHT22, a capacitive soil sensor,
    // a BH1750, etc. here.
    float tempC          = 22.0f + (float)(millis() % 1000) / 1000.0f;
    float humidity       = 55.0f + (float)(millis() % 500)  / 100.0f;
    float soilMoisture   = 40.0f + (float)(millis() % 3000) / 100.0f;
    // ----------------------------------------------------

    // Your own control logic still runs here. Nothing below touches it.
    // For example, you might decide whether to run a pump based on
    // soilMoisture, fire a relay, and log the decision to velour as a
    // separate "pump_state" reading so the fleet dashboard sees it.

    if (millis() - lastReportAt >= REPORT_INTERVAL_MS) {
        lastReportAt = millis();

        velour.addReading("temp_c",          tempC);
        velour.addReading("humidity",        humidity);
        velour.addReading("soil_moisture",   soilMoisture);

        int status = velour.report();
        Serial.print("velour report: HTTP ");
        Serial.print(status);
        Serial.print(" (pending ");
        Serial.print(velour.pending());
        Serial.println(" after send)");
    }

    delay(100);
}

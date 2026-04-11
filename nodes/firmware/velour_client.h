// velour_client.h — drop-in telemetry client for ESP8266 / ESP32 nodes
//
// Designed to coexist with your existing firmware, NOT replace it. Add
// a VelourClient to any .ino file, feed it readings whenever your own
// sensor loop has them, call report() on whatever cadence you want, and
// velour logs the data. Your control logic, pin assignments, and local
// decision-making stay exactly where they are.
//
// Usage:
//
//   #include "velour_client.h"
//
//   VelourClient velour(
//       "http://velour.lucdh.nl",      // base URL (no trailing /api/nodes)
//       "gary",                         // node slug from /nodes/gary/
//       "paste-48-char-token-here"      // node.api_token from the detail page
//   );
//
//   void setup() {
//     WiFi.begin(SSID, PASS);
//     while (WiFi.status() != WL_CONNECTED) delay(250);
//     velour.setFirmwareVersion("gary-0.3.0");
//   }
//
//   void loop() {
//     float tempC = readTempSensor();
//     velour.addReading("temp_c", tempC);
//     velour.addReading("soil_moisture_1", readSoil(A0));
//     int status = velour.report();  // HTTP status, or -1 on client error
//     delay(60000);                  // once per minute
//   }
//
// The client batches up to VELOUR_MAX_READINGS values before each
// report() call. Call report() with zero pending readings to send a
// heartbeat (velour updates last_seen_at but stores no data).

#ifndef VELOUR_CLIENT_H
#define VELOUR_CLIENT_H

#include <Arduino.h>

#if defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClient.h>
#else
  #error "velour_client requires ESP8266 or ESP32 (Arduino core)"
#endif

#ifndef VELOUR_MAX_READINGS
#define VELOUR_MAX_READINGS 16
#endif

struct VelourReading {
    const char* channel;
    float value;
};

class VelourClient {
public:
    VelourClient(const char* baseUrl, const char* slug, const char* apiToken);

    // Queue a reading for the next report() call. Returns false if the
    // buffer is full — flush with report() and try again if that happens.
    bool addReading(const char* channel, float value);

    // Send the pending batch to velour. Returns HTTP status code on
    // success (200 = stored), or -1 for pre-send errors (no WiFi, etc.).
    // Clears the pending batch either way — retries are the caller's
    // responsibility. Works as a heartbeat when called with no pending
    // readings.
    int report();

    // Optional: set the firmware version string sent on each report.
    // Velour stores it in Node.firmware_version so you can tell which
    // version each device is actually running.
    void setFirmwareVersion(const char* version);

    // How many readings are currently queued.
    int pending() const { return _count; }

    // Drop the pending batch without sending it.
    void clear() { _count = 0; }

private:
    const char* _baseUrl;
    const char* _slug;
    const char* _apiToken;
    const char* _firmwareVersion;
    VelourReading _readings[VELOUR_MAX_READINGS];
    int _count;

    String _buildUrl() const;
    String _buildPayload() const;
};

#endif  // VELOUR_CLIENT_H

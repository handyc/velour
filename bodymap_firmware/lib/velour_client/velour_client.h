// velour_client.h — drop-in telemetry client for ESP8266 / ESP32 nodes
//
// Designed to coexist with your existing firmware, NOT replace it. Add
// a VelourClient to any .ino file, feed it readings whenever your own
// sensor loop has them, call report() on whatever cadence you want, and
// velour logs the data. Your control logic, pin assignments, and local
// decision-making stay exactly where they are.
//
// Usage (admin-provisioned, Gary-style):
//
//   #include "velour_client.h"
//
//   VelourClient velour(
//       "http://velour.example.com",      // base URL (no trailing /api/nodes)
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
// Usage (self-provisioned, identical-firmware fleets like bodymap):
//
//   VelourClient velour("http://velour.example.com");
//
//   void setup() {
//     WiFi.begin(SSID, PASS);
//     while (WiFi.status() != WL_CONNECTED) delay(250);
//     if (!velour.loadStoredCredentials()) {
//       velour.registerSelf(
//           "shared-provisioning-secret",   // from velour settings
//           "Bodymap Node v1",              // HardwareProfile.name
//           "bodymap"                       // fleet / Experiment.slug
//       );
//       // Credentials are persisted to LittleFS; survives reboot.
//     }
//     velour.setFirmwareVersion("bodymap-0.1.0");
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
  #include <HTTPUpdate.h>
  #include <LittleFS.h>
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <ESP8266httpUpdate.h>
  #include <WiFiClient.h>
  #include <LittleFS.h>
#else
  #error "velour_client requires ESP8266 or ESP32 (Arduino core)"
#endif

#ifndef VELOUR_MAX_READINGS
#define VELOUR_MAX_READINGS 16
#endif

// Path on LittleFS where self-registered nodes persist their credentials.
// Two lines: slug, then api_token. Plain text — these values are already
// per-device secrets and the flash isn't readable off-chip without physical
// access anyway.
#ifndef VELOUR_CREDS_PATH
#define VELOUR_CREDS_PATH "/velour_creds.txt"
#endif

// Path on LittleFS where fetchSensorConfig() caches the last successful
// response. Used on boot when the server is unreachable so the node
// still comes up with its previously-known channel layout.
#ifndef VELOUR_SENSOR_CONFIG_PATH
#define VELOUR_SENSOR_CONFIG_PATH "/sensor_config.json"
#endif

struct VelourReading {
    const char* channel;
    float value;
};

class VelourClient {
public:
    // Admin-provisioned constructor: slug and api token are known at compile
    // time (baked into build_flags / secrets.ini). This is the original
    // usage pattern — Gary, Hazel, and Mabel all use it.
    VelourClient(const char* baseUrl, const char* slug, const char* apiToken);

    // Runtime-provisioned constructor: starts with no identity. Call
    // loadStoredCredentials() or registerSelf() in setup() before using
    // the other methods. report() and checkForUpdate() no-op (return -1)
    // when no identity is present.
    explicit VelourClient(const char* baseUrl);

    // True once slug + api token are set (either from the compile-time
    // constructor, loadStoredCredentials(), or a successful registerSelf()).
    bool hasIdentity() const { return _slug.length() && _apiToken.length(); }

    const char* slug()  const { return _slug.c_str(); }
    const char* token() const { return _apiToken.c_str(); }

    // Load slug + token from LittleFS if a prior registerSelf() wrote them.
    // Returns true on success. Mounts LittleFS on first call.
    bool loadStoredCredentials();

    // Persist the current slug + token to LittleFS. Called automatically
    // after a successful registerSelf() but exposed for operators who want
    // to pre-seed credentials over serial.
    bool saveCredentials();

    // Forget any stored credentials. Next registerSelf() will get a fresh
    // entry from velour (unless the same MAC is still registered, in which
    // case the server returns the existing slug+token — idempotent).
    bool clearStoredCredentials();

    enum RegisterResult {
        REG_OK             = 0,  // slug + token received, stored to flash
        REG_NO_NETWORK     = 1,  // WiFi not connected
        REG_HTTP_FAILED    = 2,  // HTTP layer error or non-2xx from server
        REG_BAD_RESPONSE   = 3,  // 2xx but body missing slug / api_token
        REG_REJECTED       = 4,  // server returned 4xx (bad secret, bad MAC, etc.)
        REG_DISABLED       = 5,  // server returned 503 (registration not enabled)
    };

    // Call velour's /api/nodes/register with this node's MAC address. On
    // success, stores the returned slug + api_token to LittleFS and makes
    // hasIdentity() true. Safe to call repeatedly — velour is idempotent
    // on MAC, so a re-register returns the existing credentials.
    //
    // provisioningSecret must match settings.VELOUR_PROVISIONING_SECRET on
    // the server. hardwareProfile must match an existing HardwareProfile.name
    // (create it via the admin UI first). fleet is optional and corresponds
    // to Experiment.slug — if it matches an existing Experiment, the new
    // node attaches to it.
    RegisterResult registerSelf(
        const char* provisioningSecret,
        const char* hardwareProfile,
        const char* fleet = nullptr
    );

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

    // Ask velour whether a newer firmware is available for this node's
    // hardware profile, and if so, download and apply it. On success the
    // ESP reboots into the new firmware and this call never returns.
    //
    // Return values (when it DOES return, meaning no update was applied):
    //   VELOUR_OTA_UP_TO_DATE   — running firmware matches the active one
    //   VELOUR_OTA_NO_FIRMWARE  — velour has no active firmware for this profile
    //   VELOUR_OTA_NO_NETWORK   — WiFi down
    //   VELOUR_OTA_CHECK_FAILED — HTTP error on the check endpoint
    //   VELOUR_OTA_UPDATE_FAILED — update was attempted but failed (bad bin,
    //                              insufficient flash, etc.). Serial output
    //                              from ESPhttpUpdate has the details.
    //
    // Call this periodically from loop() — maybe once per hour — after you
    // know WiFi is up. Requires setFirmwareVersion() to have been called.
    enum OtaResult {
        VELOUR_OTA_UP_TO_DATE = 0,
        VELOUR_OTA_NO_FIRMWARE = 1,
        VELOUR_OTA_NO_NETWORK = 2,
        VELOUR_OTA_CHECK_FAILED = 3,
        VELOUR_OTA_UPDATE_FAILED = 4,
    };
    OtaResult checkForUpdate();

    // How many readings are currently queued.
    int pending() const { return _count; }

    // Drop the pending batch without sending it.
    void clear() { _count = 0; }

    // Port discovery: probe a list of candidate ports on the configured
    // host for the /api/nodes/discover endpoint. If one responds with
    // {"velour":true}, update _baseUrl in place. Call once after WiFi
    // connects. Returns true if a working port was found.
    //
    // Default candidate list: 7777, 7778, 7779, 8000, 8080, 8888.
    // Override with VELOUR_DISCOVER_PORTS in build_flags if needed.
    bool discover();

    // The base URL currently in use (after discover() may have changed it).
    const char* baseUrl() const { return _resolvedUrl.length() ? _resolvedUrl.c_str() : _baseUrl; }

    // Fetch /bodymap/api/config/<slug>/ — the per-node sensor channel
    // list served by the Velour bodymap app. On success the response is
    // written into `out` and cached to LittleFS at VELOUR_SENSOR_CONFIG_PATH.
    // On failure (no WiFi, HTTP error, no identity) the cached copy is
    // loaded instead if one exists, so the node still comes up with its
    // last known channel layout. Returns true when `out` has been
    // populated either from the server or the cache.
    bool fetchSensorConfig(String& out);

private:
    const char* _baseUrl;
    String _slug;           // mutable so registerSelf() / loadStoredCredentials() can set it
    String _apiToken;       // ditto
    const char* _firmwareVersion;
    String _resolvedUrl;    // set by discover() if the port changed
    VelourReading _readings[VELOUR_MAX_READINGS];
    int _count;
    bool _fsMounted;        // lazy LittleFS.begin()

    String _effectiveBase() const;
    String _buildUrl() const;
    String _buildPayload() const;
    bool   _ensureFs();
};

#endif  // VELOUR_CLIENT_H

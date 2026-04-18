// bodymap v0 — boot, join WiFi, register with Velour, report a heartbeat.
//
// Everything IMU-related is deliberately stubbed. Once the GY-95T is
// soldered, uncomment the imu.begin() / imu.update() / addReading() lines
// marked TODO and the v0 pipeline becomes the real sensor pipeline.

#include <Arduino.h>
#include <WiFi.h>

#include "wifi_secrets.h"
#include "velour_client.h"
#include "gy95t.h"
#include "motion_buffer.h"
#include "motion_net.h"
#include "motion_cluster.h"
#include "sensors.h"

static VelourClient velour(VELOUR_BASE_URL);
static GY95T imu;
static MotionBuffer motion;
static MotionNet net;
static MotionCluster cluster;
static SensorRegistry sensors;

// IMU sampling target — matches GY-95T's advertised 100 Hz native rate.
// Clustering math wants consistent cadence, not raw speed, so locking
// this at 10 ms in the main loop is fine until we move sampling into a
// dedicated FreeRTOS task on core 0.
static const uint32_t IMU_SAMPLE_PERIOD_MS = 10;
static uint32_t _lastSampleMs = 0;

// Heartbeat cadence while the IMU is stubbed. Once real samples flow
// we'll want something closer to 50 Hz, batched per report — but for v0
// this just proves WiFi + Velour + OTA plumbing work end-to-end.
static const uint32_t REPORT_INTERVAL_MS = 10000;
static uint32_t _lastReport = 0;

// ESP-NOW broadcast cadence. Each packet carries a 3s downsampled window
// of gyro data; 1 Hz gives peers overlapping views without flooding the
// radio. Easy to tune later — the clustering layer works on windows not
// individual packets.
static const uint32_t BROADCAST_INTERVAL_MS = 1000;
static uint32_t _lastBroadcast = 0;

// Clustering pass cadence. Cheap to run (3x3 math on ≤16 peers), so we
// keep it in-step with broadcasts — after each broadcast tick we update
// our own view of who we seem to be linked to.
static const uint32_t CLUSTER_INTERVAL_MS = 1000;
static uint32_t _lastCluster = 0;

static void connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[wifi] joining ");
    Serial.print(WIFI_SSID);
    const uint32_t deadline = millis() + 30000;
    while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
        delay(250);
        Serial.print('.');
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
        Serial.print("[wifi] ip=");
        Serial.print(WiFi.localIP());
        Serial.print(" mac=");
        Serial.println(WiFi.macAddress());
    } else {
        // A node that can't reach WiFi is useless for clustering; reboot
        // and try again rather than spinning in a half-broken state.
        Serial.println("[wifi] join failed — restarting");
        delay(2000);
        ESP.restart();
    }
}

static void ensureVelourIdentity() {
    if (velour.loadStoredCredentials()) {
        Serial.print("[velour] stored identity: ");
        Serial.println(velour.slug());
        return;
    }

    Serial.println("[velour] no stored identity — calling registerSelf()");
    VelourClient::RegisterResult r = velour.registerSelf(
        VELOUR_PROVISIONING_SECRET,
        BODYMAP_HARDWARE_PROFILE,
        BODYMAP_FLEET
    );
    switch (r) {
        case VelourClient::REG_OK:
            Serial.print("[velour] registered as ");
            Serial.println(velour.slug());
            break;
        case VelourClient::REG_DISABLED:
            Serial.println("[velour] server has registration disabled (VELOUR_PROVISIONING_SECRET unset)");
            break;
        case VelourClient::REG_REJECTED:
            Serial.println("[velour] server rejected registration — check secret / MAC / hardware profile");
            break;
        case VelourClient::REG_NO_NETWORK:
            Serial.println("[velour] no network during registration");
            break;
        case VelourClient::REG_HTTP_FAILED:
            Serial.println("[velour] HTTP failure during registration");
            break;
        case VelourClient::REG_BAD_RESPONSE:
            Serial.println("[velour] server response missing slug/api_token");
            break;
    }
}

void setup() {
    Serial.begin(115200);
    // USB-CDC needs a moment to enumerate on the host before our first
    // prints come through. Otherwise early boot logs get eaten.
    delay(800);
    Serial.println();
    Serial.println("[boot] bodymap " BODYMAP_FIRMWARE_VERSION);

    connectWiFi();
    ensureVelourIdentity();
    velour.setFirmwareVersion(BODYMAP_FIRMWARE_VERSION);

    // ESP-NOW must come up AFTER WiFi — it locks to the station's
    // channel, and if WiFi isn't associated yet there's no channel to
    // lock to. Non-fatal if it fails; node still reports to Velour.
    if (!net.begin()) {
        Serial.println("[net] ESP-NOW init failed — continuing without mesh");
    } else {
        Serial.println("[net] ESP-NOW up, broadcast peer registered");
    }

    // TODO: wire up the GY-95T once it's soldered. Until then imu.update()
    // is a no-op and no readings flow through the loop below.
    // imu.begin(Serial1, 115200);

    // Per-node sensor layout comes from the server's bodymap app
    // (NodeSensorConfig.channels). fetchSensorConfig() also caches the
    // response to LittleFS, so on the next boot we can come up with the
    // last known layout even if the server is unreachable.
    String configJson;
    if (velour.fetchSensorConfig(configJson)) {
        int n = sensors.loadFromJson(configJson);
        Serial.print("[sensors] loaded ");
        Serial.print(n);
        Serial.println(" channel(s) from config");
    } else {
        Serial.println("[sensors] no config available (server + cache both empty)");
    }
}

void loop() {
    const uint32_t now = millis();

    // 100 Hz sample tick. imu.update() returns true when a new frame was
    // decoded; we push that into the motion buffer for the clustering
    // layer to consume. Stubbed IMU means update() is always false, so
    // the buffer stays empty — which is the correct dormant state.
    if (now - _lastSampleMs >= IMU_SAMPLE_PERIOD_MS) {
        _lastSampleMs = now;
        // TODO: enable once the GY-95T is soldered.
        // if (imu.update()) {
        //     GyroSample s = { imu.lastSampleMs, imu.gx, imu.gy, imu.gz };
        //     motion.push(s);
        // }
    }

    if (now - _lastBroadcast >= BROADCAST_INTERVAL_MS) {
        _lastBroadcast = now;
        // No-op while the IMU is stubbed (buffer stays empty so there's
        // nothing to broadcast). Goes live automatically once imu.update()
        // starts pushing samples.
        net.broadcast(motion);
    }

    if (now - _lastCluster >= CLUSTER_INTERVAL_MS) {
        _lastCluster = now;
        cluster.compute(motion, net);
    }

    if (now - _lastReport >= REPORT_INTERVAL_MS) {
        _lastReport = now;

        // Heartbeat channel confirms the node is alive end-to-end.
        velour.addReading("heartbeat", 1.0f);
        // buf_fill lets us watch the motion buffer ramp up from the
        // Velour dashboard — stays 0 until the IMU goes live, then
        // should climb to 1.0 within ~5s of sampling starting.
        velour.addReading("buf_fill",
            (float)motion.size() / (float)BODYMAP_MOTION_BUFFER_SAMPLES);
        // Mesh-health channels — how many peers we've heard from, and
        // how many packets have flowed either way this session.
        velour.addReading("peer_count", (float)net.peerCount());
        velour.addReading("pkts_tx",    (float)net.packetsSent());
        velour.addReading("pkts_rx",    (float)net.packetsReceived());
        // Clustering summary — top correlation with any peer, and how
        // many peers exceed the "probably linked" threshold. Once IMUs
        // are live these are the channels to watch for role discovery.
        const PeerLink* top = cluster.strongestLink();
        velour.addReading("top_rho",       top ? top->linkStrength : 0.0f);
        velour.addReading("n_strong_links", (float)cluster.strongLinkCount());

        // Server-configured per-node channels (digital/analog/ATtiny
        // peripherals). No-op if the config was empty or couldn't load.
        sensors.sampleAll(velour);

        int status = velour.report();
        Serial.print("[velour] report -> ");
        Serial.println(status);
    }

    // Yield briefly so the Arduino core can service WiFi / USB-CDC. Much
    // shorter than IMU_SAMPLE_PERIOD_MS so we don't jitter the tick.
    delay(1);
}

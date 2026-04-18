// bodymap_hud — ESP32-S3 HUD node firmware.
//
// Pulls a tiny payload from /bodymap/api/hud/<slug>/ every few seconds
// and paints it on a 128x64 SSD1306 over I2C. The OLED reflects off a
// half-silvered prism / acrylic in front of one eye, so the user sees
// the Velour glance overlaid on the real world.
//
// Hardware (default):
//   SSD1306 SDA -> GPIO4
//   SSD1306 SCL -> GPIO5
//   VCC/GND     -> 3V3/GND
// Override via BODYMAP_HUD_I2C_SDA / BODYMAP_HUD_I2C_SCL in build_flags.
//
// Optics orientation: with a beamsplitter in front of the eye, the
// image is typically horizontally flipped by the reflection. The SSD1306
// driver can't mirror a single axis, but setFlipMode(1) flips 180° which
// is what a correctly-oriented rig needs. Wrong rig geometry → flip
// the value. Wire up the physical rig first, then set the flag.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <U8g2lib.h>
#include <Wire.h>

#include "velour_client.h"
#include "wifi_secrets.h"

#ifndef BODYMAP_HUD_I2C_SDA
#define BODYMAP_HUD_I2C_SDA 4
#endif
#ifndef BODYMAP_HUD_I2C_SCL
#define BODYMAP_HUD_I2C_SCL 5
#endif
#ifndef BODYMAP_HUD_FLIP_MODE
#define BODYMAP_HUD_FLIP_MODE 1
#endif
#ifndef BODYMAP_HUD_POLL_MS
#define BODYMAP_HUD_POLL_MS 2000
#endif

U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, /*reset=*/U8X8_PIN_NONE);

VelourClient velour(VELOUR_BASE_URL);

static uint32_t last_poll = 0;

struct HudPayload {
    String time;
    String date;
    String mood;
    String line[3];
    uint8_t n_lines = 0;
};

static HudPayload payload;

static void paint_boot_splash(const char* msg) {
    oled.clearBuffer();
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(0, 12, "bodymap-hud");
    oled.setFont(u8g2_font_5x7_tf);
    oled.drawStr(0, 28, msg);
    oled.sendBuffer();
}

static void paint_hud(const HudPayload& p) {
    oled.clearBuffer();

    // Top row: big clock on the left, mood glyph right.
    oled.setFont(u8g2_font_logisoso16_tr);
    if (p.time.length()) oled.drawStr(0, 18, p.time.c_str());

    oled.setFont(u8g2_font_6x10_tf);
    if (p.mood.length()) {
        int w = oled.getStrWidth(p.mood.c_str());
        oled.drawStr(128 - w, 10, p.mood.c_str());
    }
    if (p.date.length()) {
        int w = oled.getStrWidth(p.date.c_str());
        oled.drawStr(128 - w, 22, p.date.c_str());
    }

    // Three-line body.
    oled.setFont(u8g2_font_6x10_tf);
    for (uint8_t i = 0; i < p.n_lines; i++) {
        oled.drawStr(0, 36 + i * 11, p.line[i].c_str());
    }

    oled.sendBuffer();
}

// Fetch /bodymap/api/hud/<slug>/ with Bearer auth. Populates `out` on
// success. Keeps all JSON work on the stack — the payload is small.
static bool fetch_hud(HudPayload& out) {
    if (WiFi.status() != WL_CONNECTED) return false;
    if (!velour.hasIdentity()) return false;

    String url = String(velour.baseUrl()) + "/bodymap/api/hud/" + velour.slug() + "/";
    HTTPClient http;
    if (!http.begin(url)) return false;
    http.addHeader("Authorization", String("Bearer ") + velour.token());
    http.setTimeout(4000);

    int code = http.GET();
    bool ok = false;
    if (code == 200) {
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, http.getString());
        if (!err) {
            out.time = doc["time"] | "";
            out.date = doc["date"] | "";
            out.mood = doc["mood"] | "";
            JsonArray lines = doc["lines"].as<JsonArray>();
            out.n_lines = 0;
            for (JsonVariant v : lines) {
                if (out.n_lines >= 3) break;
                out.line[out.n_lines++] = v.as<const char*>();
            }
            ok = true;
        }
    }
    http.end();
    return ok;
}

void setup() {
    Serial.begin(115200);
    delay(300);

    Wire.begin(BODYMAP_HUD_I2C_SDA, BODYMAP_HUD_I2C_SCL);
    oled.begin();
    oled.setFlipMode(BODYMAP_HUD_FLIP_MODE);
    oled.enableUTF8Print();
    paint_boot_splash("wifi...");

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) delay(250);

    paint_boot_splash("register...");
    if (!velour.loadStoredCredentials()) {
        velour.registerSelf(VELOUR_PROVISIONING_SECRET,
                            BODYMAP_HARDWARE_PROFILE,
                            BODYMAP_FLEET);
    }
    velour.setFirmwareVersion(BODYMAP_FIRMWARE_VERSION);

    paint_boot_splash(velour.hasIdentity() ? velour.slug() : "no identity");
}

void loop() {
    uint32_t now = millis();
    if (now - last_poll >= BODYMAP_HUD_POLL_MS) {
        last_poll = now;
        if (fetch_hud(payload)) {
            paint_hud(payload);
        }
    }
    delay(50);
}

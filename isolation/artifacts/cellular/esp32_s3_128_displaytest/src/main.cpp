// display_test_80x160 — sanity check on the *known-good* 80×160
// ST7735 panel using identical wiring to the 128×128 setup.
//
// If this lights up: the 128×128 panel is dead.
// If this stays white: the problem is on the ESP32-S3 / wiring side.
//
// Wiring (unchanged):
//   TFT GND  → GND       TFT VCC  → 3V3
//   TFT SCL  → GPIO 12   TFT SDA  → GPIO 11
//   TFT RES  → GPIO  6   TFT DC   → GPIO  4
//   TFT CS   → GPIO  5   TFT BLK  → GPIO  7

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

#define PIN_SCK   12
#define PIN_MOSI  11
#define PIN_DC     4
#define PIN_CS     5
#define PIN_RST    6
#define PIN_BL     7

// Mini 80×160 panel — landscape orientation gives us 160×80.
#define PANEL_W   160
#define PANEL_H    80

static SPIClass hspi(FSPI);
static Adafruit_ST7735 tft(&hspi, PIN_CS, PIN_DC, PIN_RST);

static void corners() {
    Serial.println("[stage] corners + frame");
    tft.fillScreen(ST77XX_BLACK);
    tft.drawRect(0, 0, PANEL_W, PANEL_H, ST77XX_WHITE);
    const int s = 16;
    tft.fillRect(0,            0,            s, s, ST77XX_RED);
    tft.fillRect(PANEL_W - s,  0,            s, s, ST77XX_GREEN);
    tft.fillRect(0,            PANEL_H - s,  s, s, ST77XX_BLUE);
    tft.fillRect(PANEL_W - s,  PANEL_H - s,  s, s, ST77XX_YELLOW);
}

static void color_bars() {
    Serial.println("[stage] 8-color vertical bars");
    tft.fillScreen(ST77XX_BLACK);
    const int bar_w = PANEL_W / 8;
    uint16_t bars[8] = {
        ST77XX_RED, ST77XX_ORANGE, ST77XX_YELLOW, ST77XX_GREEN,
        ST77XX_CYAN, ST77XX_BLUE, ST77XX_MAGENTA, ST77XX_WHITE
    };
    for (int i = 0; i < 8; i++) {
        tft.fillRect(i * bar_w, 0, bar_w, PANEL_H, bars[i]);
    }
}

static void hello() {
    Serial.println("[stage] text 'HELLO 80x160'");
    tft.fillScreen(ST77XX_BLACK);
    tft.setTextColor(ST77XX_WHITE);
    tft.setTextSize(2);
    tft.setCursor(8, 16);
    tft.print("HELLO");
    tft.setTextSize(1);
    tft.setCursor(8, 44);
    tft.print("80 x 160");
    tft.setCursor(8, 56);
    tft.print("ST7735 minigreentab");
}

static void fill(uint16_t c, const char *name, uint32_t hold_ms) {
    Serial.printf("[stage] fill %s\n", name);
    tft.fillScreen(c);
    delay(hold_ms);
}

void setup() {
    Serial.begin(115200);
    uint32_t t0 = millis();
    while (!Serial && (millis() - t0) < 2000) delay(10);
    Serial.println("\n========================================");
    Serial.println(" ST7735 80x160 sanity test (mini)");
    Serial.println("========================================");
    Serial.printf("pins: SCK=%d MOSI=%d DC=%d CS=%d RST=%d BL=%d\n",
                  PIN_SCK, PIN_MOSI, PIN_DC, PIN_CS, PIN_RST, PIN_BL);

    pinMode(PIN_BL, OUTPUT);
    digitalWrite(PIN_BL, HIGH);

    hspi.begin(PIN_SCK, -1, PIN_MOSI, PIN_CS);

    Serial.println("[boot] tft.initR(INITR_MINI160x80)");
    tft.initR(INITR_MINI160x80);
    tft.setRotation(1);              // landscape, USB-C side at top
    tft.invertDisplay(true);         // mini160x80 is inverted by default
    tft.fillScreen(ST77XX_BLACK);
    delay(500);
}

void loop() {
    fill(ST77XX_RED,   "RED",   800);
    fill(ST77XX_GREEN, "GREEN", 800);
    fill(ST77XX_BLUE,  "BLUE",  800);
    fill(ST77XX_WHITE, "WHITE", 800);
    fill(ST77XX_BLACK, "BLACK", 800);
    corners();
    delay(2500);
    color_bars();
    delay(2500);
    hello();
    delay(2500);
}

// bodymap display demo — ESP32-S3 SuperMini + ST7735S 80x160 IPS module
//
// Module:   generic 8-pin 0.96" IPS, 80x160, ST7735S controller, 4-wire SPI,
//           3.3 V logic, 65K colors. The cheap AliExpress variant labelled
//           either "ST7735S" or "ST7735" — same silicon behaviour.
//
// Wiring (module pin → SuperMini GPIO):
//
//   GND  ── GND
//   VCC  ── 3V3
//   SCL  ── GPIO 12   (HSPI / SPI clock)
//   SDA  ── GPIO 11   (HSPI / SPI MOSI)
//   RES  ── GPIO 6
//   DC   ── GPIO 4
//   CS   ── GPIO 5
//   BLK  ── GPIO 7    (tie to 3V3 if you don't want PWM brightness control)
//
// These pins deliberately avoid GPIO 8/9 (reserved for I2C in the main
// bodymap firmware) and the ADC-heavy 0..3 range, so the same wiring can
// live on a node that later runs the main firmware with an I2C sensor.
//
// Demo content: splash → live scrolling sparkline + header/footer. Proves
// the display works end-to-end and showcases a realistic "status panel"
// layout the main firmware could adopt when it grows a display option.

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

// ---- Pin map --------------------------------------------------------------
#define PIN_SCK   12
#define PIN_MOSI  11
#define PIN_DC     4
#define PIN_CS     5
#define PIN_RST    6
#define PIN_BL     7

// Adafruit_ST7735 doesn't ship a COLOR_DARKGREY constant (only the
// named primaries and a couple of pastels). Define the one we use for
// muted labels — RGB565, ~50 % grey.
#define COLOR_DARKGREY 0x7BEF

// The 0.96" 80x160 module is wired with a 24-pixel column offset and a
// 0-pixel row offset at the default rotation. INITR_MINI160x80 applies
// that offset automatically; we then rotate to landscape (160 wide, 80
// tall) so the sparkline has room to breathe.
#define TFT_W 160
#define TFT_H 80

static Adafruit_ST7735 tft(PIN_CS, PIN_DC, PIN_MOSI, PIN_SCK, PIN_RST);

// Sparkline state — ring buffer of recent values, one per x column.
static uint8_t spark[TFT_W] = {0};
static int sparkHead = 0;

// Header/footer geometry.
static const int HEADER_H = 12;
static const int FOOTER_H = 10;
static const int PLOT_Y   = HEADER_H;
static const int PLOT_H   = TFT_H - HEADER_H - FOOTER_H;

// Throttle full redraws so the loop doesn't melt when the SPI bus is fast.
static const uint32_t FRAME_PERIOD_MS = 40;       // ~25 fps
static uint32_t _lastFrame = 0;
static uint32_t _bootMs = 0;


static void splash() {
    tft.fillScreen(ST77XX_BLACK);
    tft.setTextWrap(false);

    tft.setTextColor(ST77XX_CYAN);
    tft.setTextSize(2);
    tft.setCursor(12, 18);
    tft.print("bodymap");

    tft.setTextColor(ST77XX_WHITE);
    tft.setTextSize(1);
    tft.setCursor(12, 42);
    tft.print("display demo");

    tft.setTextColor(COLOR_DARKGREY);
    tft.setCursor(12, 58);
    tft.print("st7735s / esp32-s3");

    // Color bar across the bottom — 160 columns, one pixel-wide each,
    // sweeping the 16-bit color space to prove all channels work.
    for (int x = 0; x < TFT_W; x++) {
        uint8_t r = map(x, 0, TFT_W - 1, 0, 31);
        uint8_t g = map(x, 0, TFT_W - 1, 0, 63);
        uint8_t b = map(x, 0, TFT_W - 1, 31, 0);
        uint16_t c = (r << 11) | (g << 5) | b;
        tft.drawFastVLine(x, TFT_H - 4, 4, c);
    }

    delay(1500);
}


static void drawHeader(uint32_t now) {
    tft.fillRect(0, 0, TFT_W, HEADER_H, ST77XX_BLACK);
    tft.drawFastHLine(0, HEADER_H - 1, TFT_W, 0x18C3);  // subtle separator

    tft.setTextColor(ST77XX_CYAN);
    tft.setTextSize(1);
    tft.setCursor(2, 2);
    tft.print("bodymap");

    // Animated heartbeat dot — pulses once per second, proves the loop is
    // actually running and not just pushing a static frame.
    uint16_t phase = (now / 40) % 50;
    uint8_t  br    = (phase < 25) ? (phase * 10) : ((50 - phase) * 10);
    uint16_t c     = tft.color565(br, 0, 0);
    tft.fillCircle(TFT_W - 6, 5, 3, c);
}


static void drawFooter(uint32_t now) {
    tft.fillRect(0, TFT_H - FOOTER_H, TFT_W, FOOTER_H, ST77XX_BLACK);

    uint32_t uptimeS = (now - _bootMs) / 1000;
    tft.setTextColor(COLOR_DARKGREY);
    tft.setTextSize(1);
    tft.setCursor(2, TFT_H - FOOTER_H + 1);
    tft.printf("t+%lus", (unsigned long)uptimeS);

    // Right-aligned free-heap readout. Useful diagnostic and a live
    // reminder that the demo is a real firmware, not a canned animation.
    char buf[16];
    snprintf(buf, sizeof(buf), "%u kB", (unsigned)(ESP.getFreeHeap() / 1024));
    int w = strlen(buf) * 6;
    tft.setCursor(TFT_W - w - 2, TFT_H - FOOTER_H + 1);
    tft.print(buf);
}


// Synthesise a sensor-like reading on the fly. Two sines plus a touch of
// noise gives the sparkline visible motion without pretending to be real
// data. When the main firmware gains a display, swap this for the latest
// IMU or sensor-channel reading.
static uint8_t syntheticSample(uint32_t now) {
    float t = (now - _bootMs) * 0.001f;
    float v = 0.5f + 0.35f * sinf(t * 2.0f)
                   + 0.12f * sinf(t * 7.3f + 1.1f);
    v += (random(0, 40) - 20) * 0.005f;
    if (v < 0.0f) v = 0.0f;
    if (v > 1.0f) v = 1.0f;
    return (uint8_t)(v * (PLOT_H - 1));
}


static void drawSparkline(uint32_t now) {
    // Advance the ring, push a new sample at the head.
    spark[sparkHead] = syntheticSample(now);
    sparkHead = (sparkHead + 1) % TFT_W;

    tft.fillRect(0, PLOT_Y, TFT_W, PLOT_H, ST77XX_BLACK);

    // Render newest-on-the-right by walking the ring backwards from head.
    int x = TFT_W - 1;
    int idx = (sparkHead - 1 + TFT_W) % TFT_W;
    uint8_t prev = spark[idx];
    while (x >= 0) {
        uint8_t v = spark[idx];
        int y0 = PLOT_Y + PLOT_H - 1 - prev;
        int y1 = PLOT_Y + PLOT_H - 1 - v;
        // drawLine handles the zero-length case (same pixel) correctly.
        tft.drawLine(x + 1, y0, x, y1, ST77XX_GREEN);
        prev = v;
        idx = (idx - 1 + TFT_W) % TFT_W;
        x--;
    }
}


void setup() {
    Serial.begin(115200);
    _bootMs = millis();

    pinMode(PIN_BL, OUTPUT);
    digitalWrite(PIN_BL, HIGH);   // backlight full-on; wire to LEDC for dimming

    tft.initR(INITR_MINI160x80);
    tft.setSPISpeed(27000000);    // 27 MHz — reliable across cheap modules
    tft.setRotation(3);           // landscape, ribbon at the left edge
    tft.invertDisplay(true);      // most 0.96" MINI160x80 panels ship inverted

    splash();
    tft.fillScreen(ST77XX_BLACK);

    // Seed the sparkline so the first frame isn't a wall of zeros.
    for (int i = 0; i < TFT_W; i++) spark[i] = PLOT_H / 2;

    Serial.println("[display] st7735s demo ready");
}


void loop() {
    uint32_t now = millis();
    if (now - _lastFrame < FRAME_PERIOD_MS) return;
    _lastFrame = now;

    drawHeader(now);
    drawSparkline(now);
    drawFooter(now);
}

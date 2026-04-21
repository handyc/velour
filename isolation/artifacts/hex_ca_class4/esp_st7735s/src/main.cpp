// Hex-CA class-4 — ESP8266 + ESP32 target for Isolation hex-ca-class4.
//
// Runs the same pipeline as pi4.py and c_compact.c on a cheap 0.96"
// ST7735S 80x160 IPS module. K=4 colours, 6-neighbour hex, 36x20
// toroidal grid with a visual half-cell offset on odd rows.
//
// The 16 KB rule table lives in RAM; both boards have plenty of
// headroom (~40 KB free on ESP8266, ~300 KB on ESP32). No WiFi, no
// network — this artifact is the terminal stage of the pipeline, run
// locally from a random seed.
//
// Wiring matches bodymap_firmware/examples/display_st7735s/ — see
// the comment block in that file's main.cpp for the pin table.
//
// Build & flash (from this directory):
//   pio run -e esp8266 -t upload            # NodeMCU v2
//   pio run -e esp32s3 -t upload            # ESP32-S3 SuperMini

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

#if defined(ARDUINO_ARCH_ESP32)
  #define PIN_SCK  12
  #define PIN_MOSI 11
  #define PIN_DC    4
  #define PIN_CS    5
  #define PIN_RST   6
  #define PIN_BL    7
  #define SPI_HZ   27000000UL
#elif defined(ARDUINO_ARCH_ESP8266)
  #define PIN_SCK  14    // D5 — HSPI CLK (fixed)
  #define PIN_MOSI 13    // D7 — HSPI MOSI (fixed)
  #define PIN_DC    5    // D1
  #define PIN_CS    4    // D2
  #define PIN_RST  16    // D0
  #define PIN_BL   -1    // tie BLK pad directly to 3V3
  #define SPI_HZ   20000000UL
#else
  #error "Unsupported architecture — add a pin map for this board"
#endif

// Grid + cell geometry. 36 wide × 20 tall at 4-px cells gives a 144×80
// hex face plus 8 px of left/right padding on the 160-wide landscape
// screen. Odd rows shift by 2 px to suggest the hex offset.
#define K     4
#define GW    36
#define GH    20
#define CELL  4
#define XPAD  8
#define RULE_LEN 16384   // K ** 7

static Adafruit_ST7735 tft(PIN_CS, PIN_DC, PIN_MOSI, PIN_SCK, PIN_RST);

static uint8_t rule[RULE_LEN];
static uint8_t grid[GH][GW];
static uint8_t ngrid[GH][GW];

// Neighbour deltas for the offset-coordinate hex layout.
// Even rows and odd rows have the same set of dy's but different dx's.
static const int8_t DY[6]  = {-1, -1,  0,  0,  1,  1};
static const int8_t DXE[6] = {-1,  0, -1,  1, -1,  0};
static const int8_t DXO[6] = { 0,  1, -1,  1,  0,  1};

// RGB565 palette chosen to echo the ANSI 256 colours in pi4.py:
//   232 near-black, 22 deep green, 94 burnt orange, 208 bright amber.
static const uint16_t PALETTE[K] = {
    0x1082,   // near-black
    0x0320,   // deep green
    0x8200,   // burnt orange
    0xFC40,   // bright amber
};


static void initRule(uint32_t seed) {
    randomSeed(seed);
    for (int i = 0; i < RULE_LEN; i++) rule[i] = random(K);
    for (int y = 0; y < GH; y++)
        for (int x = 0; x < GW; x++)
            grid[y][x] = random(K);
}


static inline void drawCell(int x, int y, uint8_t c) {
    int px = XPAD + x * CELL + ((y & 1) ? (CELL / 2) : 0);
    int py = y * CELL;
    tft.fillRect(px, py, CELL, CELL, PALETTE[c]);
}


static void stepGrid() {
    for (int y = 0; y < GH; y++) {
        const int8_t *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < GW; x++) {
            int idx = grid[y][x];
            for (int k = 0; k < 6; k++) {
                int ny = (y + DY[k] + GH) % GH;
                int nx = (x + dx[k] + GW) % GW;
                idx = idx * K + grid[ny][nx];
            }
            ngrid[y][x] = rule[idx];
        }
    }
    // Draw only cells that changed — keeps the SPI bus quiet and the
    // frame rate sane even when the dynamics are busy.
    for (int y = 0; y < GH; y++) {
        for (int x = 0; x < GW; x++) {
            if (ngrid[y][x] != grid[y][x]) drawCell(x, y, ngrid[y][x]);
            grid[y][x] = ngrid[y][x];
        }
    }
}


void setup() {
    Serial.begin(115200);
    delay(50);

    if (PIN_BL >= 0) {
        pinMode(PIN_BL, OUTPUT);
        digitalWrite(PIN_BL, HIGH);
    }

    tft.initR(INITR_MINI160x80);
    tft.setSPISpeed(SPI_HZ);
    tft.setRotation(3);          // landscape, ribbon at the left
    tft.invertDisplay(true);
    tft.fillScreen(ST77XX_BLACK);

    // Seed mixes boot time with the floating ADC pin so a fresh power-on
    // gets a different rule than the last one. No external entropy source
    // required.
#if defined(ARDUINO_ARCH_ESP8266)
    uint32_t seed = micros() ^ analogRead(A0);
#else
    uint32_t seed = micros() ^ analogRead(1);
#endif
    Serial.printf("[hex-ca] seed=%u\n", (unsigned)seed);
    initRule(seed);

    // Paint initial grid in one pass so stepGrid's diff-draw has something
    // to compare against.
    for (int y = 0; y < GH; y++)
        for (int x = 0; x < GW; x++)
            drawCell(x, y, grid[y][x]);
}


void loop() {
    stepGrid();
    delay(60);
}

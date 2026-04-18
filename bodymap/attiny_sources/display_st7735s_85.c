// display_st7735s — ATtiny85 driver for the common 8-pin 0.96" IPS
// ST7735S module (80x160, 65K colors, 4-wire SPI). Shows that an
// 8 KB / 512 B MCU can drive the same panel the ESP32-S3 runs, with
// a minimal hand-rolled init + rect-fill + a scanning-dot animation
// instead of Adafruit_GFX.
//
// Wiring (module pin → tiny85 DIP pin):
//   GND  ── GND   (pin 4)
//   VCC  ── VCC   (pin 8)   3.3 V
//   SCL  ── PB2   (pin 7)   USI USCK (SCK)
//   SDA  ── PB0   (pin 5)   USI DO   (MOSI)
//   RES  ── PB3   (pin 2)
//   DC   ── PB4   (pin 3)
//   CS   ── GND             permanently selected — we're the only slave
//   BLK  ── VCC             backlight always on
//
// PB1 and PB5 (RESET) are left free so a sensor input could be added
// alongside the display in a future template.
//
// Demo: startup color-bar sweep across the top 10 rows, then a single
// lit dot scans back and forth along the middle of the screen at ~4 Hz.
// Proves the init sequence, address-window + pixel writes, and the
// main loop all work end-to-end.

#define F_CPU 8000000UL
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>

// ---- Pin macros -----------------------------------------------------------
#define PIN_MOSI PB0
#define PIN_SCK  PB2
#define PIN_RST  PB3
#define PIN_DC   PB4

#define RST_HI()  (PORTB |=  _BV(PIN_RST))
#define RST_LO()  (PORTB &= ~_BV(PIN_RST))
#define DC_HI()   (PORTB |=  _BV(PIN_DC))
#define DC_LO()   (PORTB &= ~_BV(PIN_DC))

// ---- Panel geometry -------------------------------------------------------
// Portrait orientation (the default after reset with MADCTL=0x00):
// 80 px wide, 160 px tall. The MINI 0.96" variant has a 24-pixel column
// offset baked into the panel wiring — addresses start at x=24, not 0.
#define PANEL_W     80
#define PANEL_H    160
#define COL_OFFSET  24
#define ROW_OFFSET   0

// ---- USI SPI master (bit-banged, ~1 MHz at F_CPU=8 MHz) ------------------
static void spi_init(void) {
    DDRB  |=  _BV(PIN_MOSI) | _BV(PIN_SCK);
    PORTB &= ~_BV(PIN_SCK);  // SCK idles low — SPI mode 0
    // USI three-wire mode, software clock strobe (USITC).
    USICR = _BV(USIWM0) | _BV(USICS1);
}

static void spi_send(uint8_t b) {
    USIDR = b;
    USISR = _BV(USIOIF);  // clear overflow flag, counter = 0
    // Toggle USCK 16 times (= 8 data bits, rising + falling edges).
    // USITC flips the clock pin; USICLK ticks the USI counter.
    do {
        USICR = _BV(USIWM0) | _BV(USICS1) | _BV(USICLK) | _BV(USITC);
    } while (!(USISR & _BV(USIOIF)));
}

static void write_cmd(uint8_t c) { DC_LO(); spi_send(c); }
static void write_data(uint8_t d) { DC_HI(); spi_send(d); }

// ---- ST7735S init sequence ------------------------------------------------
// Minimal-but-reliable subset of the Adafruit INITR_MINI160x80 list.
// Gamma and most of the power-control registers are left at reset
// defaults — image is slightly less saturated than Adafruit's tuned
// version but perfectly readable on the cheap AliExpress panels.
static void panel_reset(void) {
    RST_HI(); _delay_ms(10);
    RST_LO(); _delay_ms(10);
    RST_HI(); _delay_ms(120);
}

static void panel_init(void) {
    panel_reset();

    write_cmd(0x01);            // SWRESET — software reset
    _delay_ms(150);

    write_cmd(0x11);            // SLPOUT — exit sleep
    _delay_ms(150);

    write_cmd(0x3A);            // COLMOD — pixel format
    write_data(0x05);           //   16-bit/pixel RGB565

    write_cmd(0x36);            // MADCTL — memory access control
    write_data(0x00);           //   portrait, RGB, top-to-bottom

    write_cmd(0x21);            // INVON — required for MINI160x80
                                //   (IPS panels invert vs TN defaults)

    write_cmd(0xB1);            // FRMCTR1 — normal-mode frame rate
    write_data(0x01);           //   ~79 Hz
    write_data(0x2C);
    write_data(0x2D);

    write_cmd(0xB4);            // INVCTR — display inversion control
    write_data(0x07);

    write_cmd(0xC0);            // PWCTR1 — power control 1
    write_data(0xA2);
    write_data(0x02);
    write_data(0x84);

    write_cmd(0xC1);            // PWCTR2 — power control 2
    write_data(0xC5);

    write_cmd(0xC5);            // VMCTR1 — VCOM
    write_data(0x0E);

    write_cmd(0x13);            // NORON — normal display mode
    _delay_ms(10);

    write_cmd(0x29);            // DISPON — display on
    _delay_ms(100);
}

// ---- Drawing primitives ---------------------------------------------------
static void set_window(uint8_t x0, uint8_t y0, uint8_t x1, uint8_t y1) {
    write_cmd(0x2A);                           // CASET — column range
    write_data(0);
    write_data(x0 + COL_OFFSET);
    write_data(0);
    write_data(x1 + COL_OFFSET);

    write_cmd(0x2B);                           // RASET — row range
    write_data(0);
    write_data(y0 + ROW_OFFSET);
    write_data(0);
    write_data(y1 + ROW_OFFSET);

    write_cmd(0x2C);                           // RAMWR — begin pixel stream
}

static void fill_rect(uint8_t x, uint8_t y, uint8_t w, uint8_t h,
                      uint16_t color) {
    if (w == 0 || h == 0) return;
    set_window(x, y, x + w - 1, y + h - 1);
    uint8_t hi = color >> 8;
    uint8_t lo = color & 0xFF;
    DC_HI();
    for (uint16_t n = (uint16_t)w * (uint16_t)h; n; n--) {
        spi_send(hi);
        spi_send(lo);
    }
}

static void put_pixel(uint8_t x, uint8_t y, uint16_t color) {
    fill_rect(x, y, 1, 1, color);
}

// ---- Color table ----------------------------------------------------------
// RGB565: rrrrr.gggggg.bbbbb
static const uint16_t BAR_COLORS[] PROGMEM = {
    0xF800,  // red
    0xFD20,  // orange
    0xFFE0,  // yellow
    0x07E0,  // green
    0x07FF,  // cyan
    0x001F,  // blue
    0x781F,  // magenta
    0xFFFF,  // white
};
#define BAR_N (sizeof(BAR_COLORS) / sizeof(BAR_COLORS[0]))

// ---- Main -----------------------------------------------------------------
int main(void) {
    // Outputs: MOSI, SCK, RST, DC. PB1 / PB5 left as inputs.
    DDRB  |= _BV(PIN_MOSI) | _BV(PIN_SCK) | _BV(PIN_RST) | _BV(PIN_DC);

    spi_init();
    panel_init();

    // Black background everywhere.
    fill_rect(0, 0, PANEL_W, PANEL_H, 0x0000);

    // Color bar — 8 vertical stripes, top 12 rows.
    uint8_t stripe_w = PANEL_W / BAR_N;  // 10 px each at W=80
    for (uint8_t i = 0; i < BAR_N; i++) {
        uint16_t c = pgm_read_word(&BAR_COLORS[i]);
        fill_rect(i * stripe_w, 0, stripe_w, 12, c);
    }

    // Scanning-dot animation. A 4-px-tall green line sweeps left-to-
    // right across row ~y=PANEL_H/2 and back, clearing the previous
    // position each step so no trail accumulates.
    const uint8_t sweep_y = PANEL_H / 2 - 2;
    const uint8_t sweep_h = 4;
    int8_t dir = 1;
    int16_t x = 0;
    for (;;) {
        // Erase previous 4x4 block.
        fill_rect((uint8_t)x, sweep_y, 4, sweep_h, 0x0000);

        x += dir * 2;
        if (x >= PANEL_W - 4) { x = PANEL_W - 4; dir = -1; }
        if (x <= 0)           { x = 0;           dir =  1; }

        fill_rect((uint8_t)x, sweep_y, 4, sweep_h, 0x07E0);

        // Also blink one pixel of the color bar to show the main loop
        // is alive and the MCU is not just stuck mid-init.
        static uint8_t tick = 0;
        tick++;
        uint16_t c = (tick & 1) ? 0xFFFF : 0x0000;
        put_pixel(PANEL_W - 1, 0, c);

        _delay_ms(40);
    }
}

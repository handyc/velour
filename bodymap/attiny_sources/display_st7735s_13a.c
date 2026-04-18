// display_st7735s — ATtiny13a driver for the 0.96" 80x160 ST7735S
// IPS module. Same panel and same init sequence as the '85 variant,
// but with bit-banged SPI: the '13a has no USI peripheral, so every
// bit is toggled in software. Still fits in the 1 KB flash budget.
//
// Wiring (module pin → tiny13a DIP pin):
//   GND  ── GND   (pin 4)
//   VCC  ── VCC   (pin 8)   3.3 V
//   SCL  ── PB2   (pin 7)   SPI SCK
//   SDA  ── PB0   (pin 5)   SPI MOSI
//   RES  ── PB3   (pin 2)
//   DC   ── PB4   (pin 3)
//   CS   ── GND             permanently selected — only slave
//   BLK  ── VCC             backlight always on
//
// PB1 and PB5 (RESET) are left free for future expansion.
//
// Clock: targets 9.6 MHz — unprogram the CKDIV8 fuse first (the same
// step the other '13a templates document). At the 1.2 MHz default
// the boot paint of the whole 80x160 takes ~3 s, tolerable but slow;
// at 9.6 MHz it's ~400 ms and the sweep animation is lively.
//
// Demo: startup color-bar sweep across the top 12 rows, then a lit
// green dot scans back and forth along the middle of the screen.
// Shows the init, the address-window writes, and the main loop all
// work end-to-end on a chip 1/8th the size of the '85.

#define F_CPU 9600000UL
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>

// ---- Pin macros -----------------------------------------------------------
#define PIN_MOSI PB0
#define PIN_SCK  PB2
#define PIN_RST  PB3
#define PIN_DC   PB4

#define MOSI_HI() (PORTB |=  _BV(PIN_MOSI))
#define MOSI_LO() (PORTB &= ~_BV(PIN_MOSI))
#define SCK_HI()  (PORTB |=  _BV(PIN_SCK))
#define SCK_LO()  (PORTB &= ~_BV(PIN_SCK))
#define RST_HI()  (PORTB |=  _BV(PIN_RST))
#define RST_LO()  (PORTB &= ~_BV(PIN_RST))
#define DC_HI()   (PORTB |=  _BV(PIN_DC))
#define DC_LO()   (PORTB &= ~_BV(PIN_DC))

// ---- Panel geometry -------------------------------------------------------
// Landscape orientation (MADCTL=0x60 below, MX+MV). 160 wide, 80 tall —
// the computer-screen aspect ratio. Swapping the axes also swaps the
// panel-wiring offset: the MINI 0.96"'s 24-px dead band moves from the
// X start to the Y start, so addresses begin at (0, 24) instead of (24, 0).
#define PANEL_W    160
#define PANEL_H     80
#define COL_OFFSET   0
#define ROW_OFFSET  24

// ---- Bit-banged SPI master -----------------------------------------------
// SPI mode 0: CPOL=0, CPHA=0. SCK idles low. Data latched on SCK
// rising edge, MSB first. Unrolled would be ~16 bytes smaller but
// the loop costs nothing here — still 654/1024 bytes with -Os.
static void spi_send(uint8_t b) {
    for (uint8_t i = 0; i < 8; i++) {
        if (b & 0x80) MOSI_HI(); else MOSI_LO();
        SCK_HI();
        b <<= 1;
        SCK_LO();
    }
}

static void write_cmd(uint8_t c)  { DC_LO(); spi_send(c); }
static void write_data(uint8_t d) { DC_HI(); spi_send(d); }

// ---- ST7735S init sequence ------------------------------------------------
// Minimal subset of the Adafruit INITR_MINI160x80 list. Gamma and
// most power-control registers stay at their reset defaults —
// picture is slightly less saturated than the '85 template but
// perfectly readable on the cheap AliExpress panels.
static void panel_reset(void) {
    RST_HI(); _delay_ms(10);
    RST_LO(); _delay_ms(10);
    RST_HI(); _delay_ms(120);
}

static void panel_init(void) {
    panel_reset();

    write_cmd(0x01);            // SWRESET
    _delay_ms(150);

    write_cmd(0x11);            // SLPOUT
    _delay_ms(150);

    write_cmd(0x3A);            // COLMOD — 16-bit RGB565
    write_data(0x05);

    write_cmd(0x36);            // MADCTL — landscape (MX+MV), RGB
    write_data(0x60);

    write_cmd(0x21);            // INVON — required for MINI160x80

    write_cmd(0xB1);            // FRMCTR1 — ~79 Hz
    write_data(0x01);
    write_data(0x2C);
    write_data(0x2D);

    write_cmd(0xB4);            // INVCTR
    write_data(0x07);

    write_cmd(0xC0);            // PWCTR1
    write_data(0xA2);
    write_data(0x02);
    write_data(0x84);

    write_cmd(0xC1);            // PWCTR2
    write_data(0xC5);

    write_cmd(0xC5);            // VMCTR1
    write_data(0x0E);

    write_cmd(0x13);            // NORON
    _delay_ms(10);

    write_cmd(0x29);            // DISPON
    _delay_ms(100);
}

// ---- Drawing primitives ---------------------------------------------------
static void set_window(uint8_t x0, uint8_t y0, uint8_t x1, uint8_t y1) {
    write_cmd(0x2A);                           // CASET
    write_data(0); write_data(x0 + COL_OFFSET);
    write_data(0); write_data(x1 + COL_OFFSET);

    write_cmd(0x2B);                           // RASET
    write_data(0); write_data(y0 + ROW_OFFSET);
    write_data(0); write_data(y1 + ROW_OFFSET);

    write_cmd(0x2C);                           // RAMWR
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
    DDRB |= _BV(PIN_MOSI) | _BV(PIN_SCK) | _BV(PIN_RST) | _BV(PIN_DC);
    PORTB &= ~_BV(PIN_SCK);  // SCK idles low

    panel_init();

    // Black background.
    fill_rect(0, 0, PANEL_W, PANEL_H, 0x0000);

    // Color bar — 8 vertical stripes, top 12 rows.
    uint8_t stripe_w = PANEL_W / BAR_N;
    for (uint8_t i = 0; i < BAR_N; i++) {
        uint16_t c = pgm_read_word(&BAR_COLORS[i]);
        fill_rect(i * stripe_w, 0, stripe_w, 12, c);
    }

    // Scanning-dot animation — 4x4 green block sweeps across the
    // middle row, erasing the previous position each step.
    const uint8_t sweep_y = PANEL_H / 2 - 2;
    const uint8_t sweep_h = 4;
    int8_t dir = 1;
    int16_t x = 0;
    for (;;) {
        fill_rect((uint8_t)x, sweep_y, 4, sweep_h, 0x0000);

        x += dir * 2;
        if (x >= PANEL_W - 4) { x = PANEL_W - 4; dir = -1; }
        if (x <= 0)           { x = 0;           dir =  1; }

        fill_rect((uint8_t)x, sweep_y, 4, sweep_h, 0x07E0);

        // Alive-blinker pixel at top-right — confirms the main loop
        // is running, not just the init.
        static uint8_t tick = 0;
        tick++;
        uint16_t c = (tick & 1) ? 0xFFFF : 0x0000;
        put_pixel(PANEL_W - 1, 0, c);

        _delay_ms(40);
    }
}

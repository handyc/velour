// rule110_st7735s — Rule 110 1-D CA plotted as a space-time diagram
// on the 0.96" 80x160 ST7735S IPS panel, driven by an ATtiny13a.
//
// Same bit-banged SPI wiring as display_st7735s_13a. Instead of the
// scanning-dot demo, each generation of a 160-cell Rule 110 automaton
// is painted as one pixel row; rows cycle top-to-bottom so the panel
// always shows the last 80 generations.
//
// Wiring (module pin → '13a DIP pin):
//   GND  ── GND   (pin 4)
//   VCC  ── VCC   (pin 8)    3.3 V
//   SCL  ── PB2   (pin 7)    SPI SCK
//   SDA  ── PB0   (pin 5)    SPI MOSI
//   RES  ── PB3   (pin 2)
//   DC   ── PB4   (pin 3)
//   CS   ── GND              permanently selected
//   BLK  ── VCC              backlight always on
//
// Rule 110 (01101110 = 0x6E), 160 cells wide, zero-padded boundaries.
// Seed = single alive cell at the right edge — gives the classic
// self-similar triangular wedge growing leftward.
//
// Colors rotate each generation so the time axis reads as a smooth
// hue ramp. Dead = black, alive = (generation % palette_len).

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
#define PANEL_W    160
#define PANEL_H     80
#define COL_OFFSET   0
#define ROW_OFFSET  24

// ---- Bit-banged SPI master ------------------------------------------------
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

// ---- ST7735S init ---------------------------------------------------------
static void panel_reset(void) {
    RST_HI(); _delay_ms(10);
    RST_LO(); _delay_ms(10);
    RST_HI(); _delay_ms(120);
}

static void panel_init(void) {
    panel_reset();
    write_cmd(0x01); _delay_ms(150);       // SWRESET
    write_cmd(0x11); _delay_ms(150);       // SLPOUT
    write_cmd(0x3A); write_data(0x05);     // COLMOD = RGB565
    write_cmd(0x36); write_data(0x60);     // MADCTL = landscape, RGB
    write_cmd(0x21);                       // INVON (required for MINI160x80)
    write_cmd(0xB1); write_data(0x01); write_data(0x2C); write_data(0x2D);
    write_cmd(0xB4); write_data(0x07);
    write_cmd(0xC0); write_data(0xA2); write_data(0x02); write_data(0x84);
    write_cmd(0xC1); write_data(0xC5);
    write_cmd(0xC5); write_data(0x0E);
    write_cmd(0x13); _delay_ms(10);        // NORON
    write_cmd(0x29); _delay_ms(100);       // DISPON
}

static void set_window(uint8_t x0, uint8_t y0, uint8_t x1, uint8_t y1) {
    write_cmd(0x2A);
    write_data(0); write_data(x0 + COL_OFFSET);
    write_data(0); write_data(x1 + COL_OFFSET);
    write_cmd(0x2B);
    write_data(0); write_data(y0 + ROW_OFFSET);
    write_data(0); write_data(y1 + ROW_OFFSET);
    write_cmd(0x2C);
}

static void fill_rect(uint8_t x, uint8_t y, uint8_t w, uint8_t h,
                      uint16_t color) {
    if (w == 0 || h == 0) return;
    set_window(x, y, x + w - 1, y + h - 1);
    uint8_t hi = color >> 8, lo = color & 0xFF;
    DC_HI();
    for (uint16_t n = (uint16_t)w * (uint16_t)h; n; n--) {
        spi_send(hi);
        spi_send(lo);
    }
}

// ---- Rule 110 CA ----------------------------------------------------------
// 160 cells, packed into 20 bytes (LSB-first within each byte).
#define N_CELLS 160
#define N_BYTES (N_CELLS / 8)

static uint8_t row[N_BYTES];
static uint8_t nxt[N_BYTES];

static inline uint8_t cell_at(const uint8_t* r, int16_t i) {
    if (i < 0 || i >= N_CELLS) return 0;             // zero-padded edges
    return (r[i >> 3] >> (i & 7)) & 1;
}
static inline void set_cell(uint8_t* r, int16_t i, uint8_t v) {
    uint8_t m = (uint8_t)(1u << (i & 7));
    if (v) r[i >> 3] |= m;
    else   r[i >> 3] &= (uint8_t)~m;
}

static void step_rule110(void) {
    for (int16_t i = 0; i < N_CELLS; i++) {
        uint8_t l = cell_at(row, i - 1);
        uint8_t s = cell_at(row, i);
        uint8_t r = cell_at(row, i + 1);
        uint8_t pat = (uint8_t)((l << 2) | (s << 1) | r);
        set_cell(nxt, i, (0x6Eu >> pat) & 1u);       // Rule 110 = 01101110
    }
    for (uint8_t k = 0; k < N_BYTES; k++) row[k] = nxt[k];
}

// ---- Palette --------------------------------------------------------------
// 8-step hue ramp, rotates so the time axis reads as colour drift.
static const uint16_t PAL[] PROGMEM = {
    0xF800, 0xFD20, 0xFFE0, 0x07E0, 0x07FF, 0x001F, 0x781F, 0xFFFF,
};
#define PAL_N (sizeof(PAL) / sizeof(PAL[0]))

// ---- Main -----------------------------------------------------------------
int main(void) {
    DDRB |= _BV(PIN_MOSI) | _BV(PIN_SCK) | _BV(PIN_RST) | _BV(PIN_DC);
    PORTB &= ~_BV(PIN_SCK);                          // SCK idles low

    panel_init();
    fill_rect(0, 0, PANEL_W, PANEL_H, 0x0000);

    // Seed: single alive cell at the right edge. Produces the classic
    // leftward-growing Rule 110 wedge.
    for (uint8_t k = 0; k < N_BYTES; k++) row[k] = 0;
    set_cell(row, N_CELLS - 1, 1);

    uint16_t gen = 0;
    for (;;) {
        uint8_t y = (uint8_t)(gen % PANEL_H);
        uint16_t on = pgm_read_word(&PAL[gen % PAL_N]);
        uint8_t on_hi = on >> 8, on_lo = on & 0xFF;

        set_window(0, y, PANEL_W - 1, y);
        DC_HI();
        for (uint8_t i = 0; i < PANEL_W; i++) {
            if (cell_at(row, i)) { spi_send(on_hi); spi_send(on_lo); }
            else                 { spi_send(0x00);  spi_send(0x00);  }
        }

        step_rule110();
        gen++;

        // Periodic reseed so the panel doesn't just end up stable.
        // Classic Rule 110 from a single seed fills the wedge by
        // gen ≈ 160, then runs out of frontier. Reseeding every 320
        // generations keeps the display alive indefinitely.
        if (gen % 320u == 0u) {
            for (uint8_t k = 0; k < N_BYTES; k++) row[k] = 0;
            set_cell(row, N_CELLS - 1, 1);
        }

        _delay_ms(20);
    }
}

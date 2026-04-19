// rule110_gm009605 — Rule 110 1-D CA plotted as a space-time diagram
// on the GM009605 (SSD1306 128x64 mono OLED), driven by an ATtiny13a
// via bit-banged I2C.
//
// Same wiring as display_gm009605_13a:
//   GND  ── GND   (pin 4)
//   VCC  ── VCC   (pin 8)    3.3 V
//   SCL  ── PB2   (pin 7)
//   SDA  ── PB0   (pin 5)
//
// Geometry choice: 32 CA cells × 4 px/cell = 128 px wide. Each byte
// sent to the OLED covers 8 vertical pixels of one column, so we
// draw one 8-row page at a time by accumulating 8 successive
// generations into a 32-byte "column byte" buffer and committing
// them as one I2C page write. With 8 pages we show the last 64
// generations; after page 7 we wrap to page 0 and overwrite.
//
// SRAM budget (of 64 B):  row[4] + nxt[4] + col[32] + stack ≈ 48 B.

#define F_CPU 9600000UL
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>

// ---- Bit-banged I2C -------------------------------------------------------
static inline void sda_hi(void) { DDRB &= ~_BV(PB0); }
static inline void sda_lo(void) { DDRB |=  _BV(PB0); PORTB &= ~_BV(PB0); }
static inline void scl_hi(void) { DDRB &= ~_BV(PB2); }
static inline void scl_lo(void) { DDRB |=  _BV(PB2); PORTB &= ~_BV(PB2); }

static void i2c_start(void) { sda_hi(); scl_hi(); sda_lo(); scl_lo(); }
static void i2c_stop(void)  { sda_lo(); scl_hi(); sda_hi(); }

static void i2c_write(uint8_t b) {
    for (uint8_t i = 0; i < 8; i++) {
        if (b & 0x80) sda_hi(); else sda_lo();
        scl_hi();
        scl_lo();
        b <<= 1;
    }
    sda_hi();                                        // release for ACK
    scl_hi();
    scl_lo();
}

#define OLED_WR 0x78

static void oled_cmd(uint8_t c) {
    i2c_start();
    i2c_write(OLED_WR);
    i2c_write(0x00);                                 // command stream
    i2c_write(c);
    i2c_stop();
}

static void oled_data_begin(void) {
    i2c_start();
    i2c_write(OLED_WR);
    i2c_write(0x40);                                 // data stream
}

// ---- SSD1306 init ---------------------------------------------------------
static const uint8_t INIT[] PROGMEM = {
    0xAE, 0x20, 0x00, 0xB0, 0xC8,
    0x00, 0x10, 0x40, 0x81, 0x7F,
    0xA1, 0xA6, 0xA8, 0x3F, 0xA4,
    0xD3, 0x00, 0xD5, 0x80, 0xD9, 0xF1,
    0xDA, 0x12, 0xDB, 0x40, 0x8D, 0x14, 0xAF,
};

static void oled_init(void) {
    _delay_ms(50);
    for (uint8_t i = 0; i < sizeof(INIT); i++) {
        oled_cmd(pgm_read_byte(&INIT[i]));
    }
}

static void oled_goto(uint8_t page, uint8_t col) {
    oled_cmd(0xB0 | (page & 0x07));
    oled_cmd(0x00 | (col  & 0x0F));                  // col low nibble
    oled_cmd(0x10 | ((col >> 4) & 0x0F));            // col high nibble
}

// ---- Rule 110 CA ----------------------------------------------------------
// 32 cells, packed LSB-first into 4 bytes. Zero-padded boundaries.
#define N_CELLS 32
#define N_BYTES 4

static uint8_t row[N_BYTES];
static uint8_t nxt[N_BYTES];
static uint8_t col[N_CELLS];                         // page-under-construction

static inline uint8_t cell_at(const uint8_t* r, int8_t i) {
    if (i < 0 || i >= N_CELLS) return 0;
    return (r[i >> 3] >> (i & 7)) & 1u;
}
static inline void set_cell(uint8_t* r, int8_t i, uint8_t v) {
    uint8_t m = (uint8_t)(1u << (i & 7));
    if (v) r[i >> 3] |= m;
    else   r[i >> 3] &= (uint8_t)~m;
}

static void step_rule110(void) {
    for (int8_t i = 0; i < N_CELLS; i++) {
        uint8_t l = cell_at(row, (int8_t)(i - 1));
        uint8_t s = cell_at(row, i);
        uint8_t r = cell_at(row, (int8_t)(i + 1));
        uint8_t pat = (uint8_t)((l << 2) | (s << 1) | r);
        set_cell(nxt, i, (0x6Eu >> pat) & 1u);       // Rule 110 = 01101110
    }
    for (uint8_t k = 0; k < N_BYTES; k++) row[k] = nxt[k];
}

// ---- Main -----------------------------------------------------------------
int main(void) {
    PORTB &= ~(_BV(PB0) | _BV(PB2));                 // driven-low target = 0
    oled_init();

    // Clear the whole screen once.
    for (uint8_t p = 0; p < 8; p++) {
        oled_goto(p, 0);
        oled_data_begin();
        for (uint8_t c = 0; c < 128; c++) i2c_write(0x00);
        i2c_stop();
    }

    // Seed: single alive cell at the right edge.
    for (uint8_t k = 0; k < N_BYTES; k++) row[k] = 0;
    set_cell(row, N_CELLS - 1, 1);

    uint8_t page = 0;
    uint16_t gen = 0;
    for (;;) {
        // Accumulate 8 generations into col[] as vertical byte patterns,
        // then commit as one page. Each CA cell spans 4 screen columns.
        for (uint8_t k = 0; k < N_CELLS; k++) col[k] = 0;
        for (uint8_t bit = 0; bit < 8; bit++) {
            for (uint8_t i = 0; i < N_CELLS; i++) {
                if (cell_at(row, (int8_t)i)) col[i] |= (uint8_t)(1u << bit);
            }
            step_rule110();
            gen++;
            // Keep the pattern lively: re-seed whenever the wedge has
            // likely exhausted the left boundary.
            if ((gen % 120u) == 0u) {
                for (uint8_t k = 0; k < N_BYTES; k++) row[k] = 0;
                set_cell(row, N_CELLS - 1, 1);
            }
        }

        oled_goto(page, 0);
        oled_data_begin();
        for (uint8_t i = 0; i < N_CELLS; i++) {
            // 4× horizontal replication: 32 cells × 4 = 128 columns.
            uint8_t b = col[i];
            i2c_write(b); i2c_write(b); i2c_write(b); i2c_write(b);
        }
        i2c_stop();

        page = (uint8_t)((page + 1) & 7u);
        _delay_ms(30);
    }
}

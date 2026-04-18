// display_gm009605 — ATtiny13a driver for the GM009605 v4.3 module
// (128x64 SSD1306 OLED, I2C, 4 pins). Smaller and less wired than
// the ST7735S variant: only SDA and SCL come out of the chip, so
// PB1/PB3/PB4 stay free for a sensor input, a gate output, and an
// LED — plus the panel is 1 bit/pixel so a frame is 1024 bytes not
// 25,600.
//
// Wiring (module pin → tiny13a DIP pin):
//   GND  ── GND   (pin 4)
//   VCC  ── VCC   (pin 8)   3.3 V (or 5 V — module has its own regulator)
//   SCL  ── PB2   (pin 7)
//   SDA  ── PB0   (pin 5)
//
// Pullups: the module has weak internal ones, but add 4.7k to VCC
// on both lines for reliable signalling at longer wire lengths.
//
// Clock: targets 9.6 MHz — unprogram the CKDIV8 fuse. At the stock
// 1.2 MHz the demo still runs, just at ~1 Hz frame rate instead of
// ~8 Hz.
//
// Demo: eight vertical bands along the top page encode 0x00..0xFF
// in a binary ruler (so you can eyeball column alignment), then a
// single-column "sweep" marches left-to-right across the middle
// page and back. A one-column blinker in the top-right corner
// flashes every frame to prove the main loop is alive.

#define F_CPU 9600000UL
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>

// ---- Bit-banged I2C master ------------------------------------------------
// Open-drain discipline: the line is driven low by setting DDRB, and
// released to the pullup by clearing DDRB (DDR=0 + PORT=0 → pin is
// Hi-Z input, pullup wins).
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
    // ACK bit — release SDA, pulse SCL, ignore the result. The
    // SSD1306 always acks a well-formed write, and if it doesn't
    // there's nothing useful we could do anyway.
    sda_hi();
    scl_hi();
    scl_lo();
}

// ---- SSD1306 command / data wrappers --------------------------------------
// 0x78 = 0x3C (the module's fixed 7-bit address) shifted left with
// the I2C write bit (R/W=0) in the LSB.
#define OLED_WR 0x78

static void oled_cmd(uint8_t c) {
    i2c_start();
    i2c_write(OLED_WR);
    i2c_write(0x00);     // control byte: Co=0, D/C=0 → command stream
    i2c_write(c);
    i2c_stop();
}

static void oled_data_begin(void) {
    i2c_start();
    i2c_write(OLED_WR);
    i2c_write(0x40);     // control byte: D/C=1 → data stream
}

// ---- Init sequence --------------------------------------------------------
// Shortest reliable SSD1306 init for the 128x64 variant. Lifted from
// the common Adafruit / u8g2 init lists, trimmed to the minimum the
// GM009605 v4.3 actually needs.
static const uint8_t INIT[] PROGMEM = {
    0xAE,            // DISPLAY_OFF
    0x20, 0x00,      // MEM_MODE = horizontal addressing
    0xB0,            // page start = 0
    0xC8,            // COM output scan direction, remapped
    0x00, 0x10,      // column address low / high nibble = 0
    0x40,            // start line = 0
    0x81, 0x7F,      // CONTRAST = 0x7F (mid-range)
    0xA1,            // segment remap
    0xA6,            // normal (non-inverted) display
    0xA8, 0x3F,      // multiplex = 63 (i.e. 64 rows)
    0xA4,            // follow RAM (not forced-on)
    0xD3, 0x00,      // display offset = 0
    0xD5, 0x80,      // clock divide ratio / oscillator
    0xD9, 0xF1,      // precharge period
    0xDA, 0x12,      // COM pin hardware config
    0xDB, 0x40,      // VCOMH deselect
    0x8D, 0x14,      // charge pump on
    0xAF,            // DISPLAY_ON
};

static void oled_init(void) {
    _delay_ms(50);
    for (uint8_t i = 0; i < sizeof(INIT); i++) {
        oled_cmd(pgm_read_byte(&INIT[i]));
    }
}

// ---- Drawing helpers ------------------------------------------------------
// The SSD1306's "horizontal addressing" mode auto-increments the
// column pointer for us, so a whole-page write is one I2C transaction
// of 128 data bytes.

static void oled_goto(uint8_t page, uint8_t col) {
    oled_cmd(0xB0 | (page & 0x07));
    oled_cmd(0x00 | (col  & 0x0F));          // low nibble
    oled_cmd(0x10 | ((col >> 4) & 0x0F));    // high nibble
}

static void oled_fill_page(uint8_t page, uint8_t byte) {
    oled_goto(page, 0);
    oled_data_begin();
    for (uint8_t col = 0; col < 128; col++) i2c_write(byte);
    i2c_stop();
}

static void oled_clear(void) {
    for (uint8_t p = 0; p < 8; p++) oled_fill_page(p, 0x00);
}

// ---- Main -----------------------------------------------------------------
int main(void) {
    PORTB &= ~(_BV(PB0) | _BV(PB2));  // both driven-low targets = 0
    oled_init();
    oled_clear();

    // Top page ruler: each 16-column block lights a different bit
    // pattern, walking through 0x01, 0x03, 0x07, …, 0xFF. Useful
    // as a visual alignment guide.
    oled_goto(0, 0);
    oled_data_begin();
    for (uint8_t i = 0; i < 8; i++) {
        uint8_t pat = (uint8_t)((1u << (i + 1)) - 1u);  // 0x01, 0x03, …, 0xFF
        for (uint8_t col = 0; col < 16; col++) i2c_write(pat);
    }
    i2c_stop();

    // Animation loop — a single-column bar sweeps across page 3
    // (roughly vertical middle), leaving the previous column blank
    // so no trail accumulates. Top-right pixel blinks every frame.
    int8_t dir = 1;
    uint8_t x = 0;
    uint8_t tick = 0;
    for (;;) {
        // Erase previous position.
        oled_goto(3, x);
        oled_data_begin();
        i2c_write(0x00);
        i2c_stop();

        if (dir > 0) { if (x >= 127) { x = 127; dir = -1; } else x++; }
        else         { if (x == 0)   { x = 0;   dir =  1; } else x--; }

        // Draw new position.
        oled_goto(3, x);
        oled_data_begin();
        i2c_write(0xFF);
        i2c_stop();

        // Alive-blinker at top-right corner.
        oled_goto(0, 127);
        oled_data_begin();
        i2c_write((tick++ & 1) ? 0xFF : 0x00);
        i2c_stop();

        _delay_ms(40);
    }
}

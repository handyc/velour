// i2c_slave_skeleton — the canonical "ATtiny85 as I2C coprocessor" shape.
//
// Pin map (fixed by USI peripheral — can't be reassigned):
//   PB0 = SDA  (I2C data)       — pull-up to 3.3V
//   PB2 = SCL  (I2C clock)      — pull-up to 3.3V
//   PB3 = ADC3 — signal input   (user-free analog pin)
//   PB4 = ADC2 — parameter pot  (user-free analog pin)
//   PB1 = user-free digital I/O (drive an LED, read a switch, etc.)
//
// The bodymap ESP reads two bytes from this slave's I2C address each
// round-robin tick; those bytes are the hi/lo of `output_value` below.
// Everything you can dream up as a filter/transform goes inside the
// USER TRANSFORM block at the bottom of main().
//
// This file is a skeleton: it compiles, it enumerates on the bus, and
// it responds to reads. The USI-as-I2C-slave code is well-trodden
// (AVR312 app note) — it's long but it's boilerplate, and you don't
// need to touch it. All the creativity goes in the tiny marked zone.

#define F_CPU 8000000UL
#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/atomic.h>

// ---- Configure this -------------------------------------------------------
#define I2C_SLAVE_ADDR  0x08    // 7-bit address
// ---------------------------------------------------------------------------

// Two-byte output register. ESP reads [hi, lo].
static volatile uint16_t output_value = 0;

// --- Minimal USI I2C slave (read-only, 2 bytes per transaction) -----------
// Adapted from Atmel AVR312. Handles Start → address match → two data
// bytes → Stop. No write-to-slave path since we don't need one yet.

#define USI_SLAVE_CHECK_ADDRESS      0
#define USI_SLAVE_SEND_DATA          1
#define USI_SLAVE_REQUEST_REPLY_FROM 2

static volatile uint8_t usi_state = USI_SLAVE_CHECK_ADDRESS;
static volatile uint8_t byte_index = 0;

static inline void usi_release_sda(void) {
    DDRB  &= ~_BV(PB0);
    PORTB &= ~_BV(PB0);
}

static inline void usi_drive_sda(void) {
    DDRB  |= _BV(PB0);
}

static void usi_i2c_init(uint8_t addr) {
    (void)addr;  // address is compared in ISR via I2C_SLAVE_ADDR
    DDRB  |= _BV(PB2);                   // SCL output (initially)
    DDRB  &= ~_BV(PB0);                  // SDA input
    PORTB |= _BV(PB2) | _BV(PB0);        // pullups (weak — real pullups on the bus)

    USICR = _BV(USISIE) | _BV(USIWM1) | _BV(USICS1);
    USISR = 0xF0;                        // clear flags, counter=0
}

ISR(USI_START_vect) {
    usi_state = USI_SLAVE_CHECK_ADDRESS;
    DDRB &= ~_BV(PB0);                   // SDA input until we know
    while ((PINB & _BV(PB2)) && !(PINB & _BV(PB0))) { }
    USICR = _BV(USISIE) | _BV(USIOIE) | _BV(USIWM1) | _BV(USIWM0) | _BV(USICS1);
    USISR = _BV(USISIF) | _BV(USIOIF) | _BV(USIPF) | _BV(USIDC);
}

ISR(USI_OVF_vect) {
    switch (usi_state) {
    case USI_SLAVE_CHECK_ADDRESS: {
        uint8_t addr = USIDR >> 1;
        uint8_t read = USIDR & 0x01;
        if (addr == I2C_SLAVE_ADDR && read) {
            USIDR = 0;                         // ACK
            usi_drive_sda();
            USISR = (1<<USIOIF)|(0<<USICNT0)|(0<<USICNT1)|(0<<USICNT2)|(0<<USICNT3);
            USISR |= _BV(USIOIF);
            byte_index = 0;
            usi_state = USI_SLAVE_SEND_DATA;
        } else {
            USICR = _BV(USISIE) | _BV(USIWM1) | _BV(USICS1);
            USISR = _BV(USISIF);
        }
        break;
    }
    case USI_SLAVE_SEND_DATA: {
        uint16_t snapshot;
        ATOMIC_BLOCK(ATOMIC_RESTORESTATE) { snapshot = output_value; }
        USIDR = (byte_index == 0) ? (uint8_t)(snapshot >> 8) : (uint8_t)snapshot;
        byte_index = (byte_index + 1) & 0x01;
        usi_drive_sda();
        USISR = _BV(USIOIF);
        usi_state = USI_SLAVE_REQUEST_REPLY_FROM;
        break;
    }
    case USI_SLAVE_REQUEST_REPLY_FROM: {
        usi_release_sda();
        USISR = _BV(USIOIF);
        usi_state = USI_SLAVE_SEND_DATA;
        break;
    }
    }
}

// --- ADC helper ------------------------------------------------------------
static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

// --- main ------------------------------------------------------------------
int main(void) {
    ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1);
    usi_i2c_init(I2C_SLAVE_ADDR);
    sei();

    while (1) {
        uint16_t pot    = adc_read(2);   // ADC2 = PB4  — parameter knob
        uint16_t signal = adc_read(3);   // ADC3 = PB3  — signal in

        // ── USER TRANSFORM ────────────────────────────────────────────────
        // Whatever you compute here ends up as the 16-bit value the ESP
        // reads over I2C on the next poll tick. Toy example: scale the
        // signal by the pot (0…1023 each → 0…~64K).
        uint16_t out = (uint16_t)(((uint32_t)signal * (uint32_t)pot) >> 4);
        // ── end USER TRANSFORM ────────────────────────────────────────────

        ATOMIC_BLOCK(ATOMIC_RESTORESTATE) { output_value = out; }
    }
}

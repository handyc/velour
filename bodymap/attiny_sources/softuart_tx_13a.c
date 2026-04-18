// softuart_tx_13a — bit-bang UART TX on the '13a, paired with
// bodymap firmware's AttinySoftUartSensor on the ESP32 side.
//
// The ATtiny13a has no USI and no hardware UART, so when we want to
// stream sensor data to the ESP32 we have to time the bits ourselves.
// This template reads ADC3 (PB3) and pushes a 3-byte frame out PB0
// every ~100 ms:
//
//   0xA5    start-of-frame magic
//   hi      top 8 bits of a 16-bit value
//   lo      bottom 8 bits
//
// The value is the ADC reading left-shifted to fill 16 bits (ADC is
// only 10 bits natively, so the low 6 bits are zero) — the ESP32 side
// divides by 65535 to get [0, 1] regardless of the source's actual
// resolution, which keeps this template a drop-in replacement for any
// other '13a that wants to report a 16-bit-ish value.
//
// Pin map:
//   PB0 = TX        — wire to an ESP32 GPIO configured as softuart RX
//   PB3 = signal    — ADC3, 0..VCC
//
// Baud: 1200. At F_CPU=1.2 MHz that's 1000 cycles/bit, which lands
// cleanly on _delay_us(833) per bit (within 1% of the target — the
// ESP32 UART's sampling tolerance is much wider).
//
// Flash footprint: ~250 bytes, comfortably inside the 1 KB '13a.

#define F_CPU 1200000UL

#include <avr/io.h>
#include <util/delay.h>

// One bit at 1200 baud = 833.33 microseconds. _delay_us's argument is
// a compile-time constant, so we round to the nearest integer that
// still gives us < 1% total skew over an 8-bit frame.
#define BIT_US 833

static void uart_tx_byte(uint8_t b) {
    // Start bit.
    PORTB &= ~_BV(PB0);
    _delay_us(BIT_US);

    // 8 data bits, LSB first — the standard 8N1 convention.
    for (uint8_t i = 0; i < 8; i++) {
        if (b & 0x01) PORTB |=  _BV(PB0);
        else          PORTB &= ~_BV(PB0);
        b >>= 1;
        _delay_us(BIT_US);
    }

    // Stop bit (idle high) + one bit of guard so the next start bit's
    // falling edge is unambiguous at the receiver.
    PORTB |= _BV(PB0);
    _delay_us(BIT_US);
    _delay_us(BIT_US);
}

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    // PB0 = output, idle high (UART convention).
    DDRB  |= _BV(PB0);
    PORTB |= _BV(PB0);

    // ADC on, /16 prescaler (≈75 kHz sample clock at F_CPU=1.2 MHz —
    // inside the '13a's recommended 50–200 kHz ADC range).
    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    while (1) {
        uint16_t sig = adc_read(3);      // 10-bit, 0..1023
        uint16_t val = sig << 6;         // promote to full 16-bit range

        uart_tx_byte(0xA5);
        uart_tx_byte((uint8_t)(val >> 8));
        uart_tx_byte((uint8_t)(val & 0xFF));

        // Inter-frame pause — gives the receiver time to decode the
        // previous frame and keeps our radio footprint (if any) quiet
        // between transmissions. ~10 frames/s is plenty for envelope
        // / flex / pressure data that feeds a 0.1 Hz report cadence.
        _delay_ms(90);
    }
}

// lut_fb_13a — two-input LUT with a feedback bit.
//
// Adds one bit of internal state to lut_filter_13a, turning a
// combinational truth table into a sequential filter. Each LUT
// entry now produces TWO output bits: C (goes to PB0) and a
// "carry" bit that is latched and XORed into the A input on the
// next cycle. So instead of 16 pure boolean functions you get 256
// little 1-state state machines — some latch, some oscillate,
// some wait for B before advancing, etc.
//
// Wiring:
//   PB0 = C output
//   PB1 = carry / feedback register (visible LED)
//   PB2 = LUT selector pot (ADC1), full 8-bit index 0..255
//   PB3 = A input (button to GND, press = logical 1)
//   PB4 = B input (button to GND, press = logical 1)
//
// Clocks at ~20 Hz so the state transitions are walkable by eye.
// Drop the delay if you want to feed audio-rate state through it.
//
// LUT encoding: for inputs (a_eff, b) packed as ab = (a_eff<<1)|b,
// bits (2*ab + 0) and (2*ab + 1) of the selected index are the
// C and carry outputs respectively. Pot sweeps the whole 256-LUT
// space; notable families:
//   idx = 0x00 — every output 0 (dead cell)
//   idx = 0x55 — carry=0, C = AND variations
//   idx = 0xCC — C = A, carry = A (straight through)
//   idx = 0xAA — C = NOT B, carry = 0
//   idx = 0xFF — both outputs always 1 (pinned)
//   ...and 250 others the user gets to explore.

#define F_CPU 1200000UL
#include <avr/io.h>
#include <util/delay.h>

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    DDRB  |= _BV(PB0) | _BV(PB1);
    PORTB |= _BV(PB3) | _BV(PB4);    // pull-ups on button inputs

    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    uint8_t fb = 0;

    while (1) {
        uint8_t idx = (uint8_t)(adc_read(1) >> 2);   // 0..255

        // Buttons are active-low: idle (open) = 0, pressed = 1.
        uint8_t a = (PINB & _BV(PB3)) ? 0 : 1;
        uint8_t b = (PINB & _BV(PB4)) ? 0 : 1;

        uint8_t a_eff = a ^ fb;
        uint8_t ab    = (uint8_t)((a_eff << 1) | b);
        uint8_t pair  = (idx >> (ab * 2)) & 0x03;
        uint8_t c     = pair & 0x01;
        uint8_t carry = (pair >> 1) & 0x01;

        if (c)     PORTB |=  _BV(PB0); else PORTB &= ~_BV(PB0);
        if (carry) PORTB |=  _BV(PB1); else PORTB &= ~_BV(PB1);

        fb = carry;

        _delay_ms(50);
    }
}

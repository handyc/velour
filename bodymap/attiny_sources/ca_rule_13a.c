// ca_rule_13a — elementary cellular-automaton cell in a chip.
//
// Three inputs (L, C, R) on three GPIOs, one output (C_new) on a
// fourth. The pot selects one of the 256 Wolfram-style 3-input
// rules. The mapping is purely combinational — the output updates
// continuously, no clock. Chain N of these together by wiring each
// chip's PB0 into the next chip's R (and the previous chip's L
// into PB1) and you have a 1-D cellular automaton in hardware;
// add a periodic "latch" signal to make the evolution discrete.
//
// Rule encoding: for neighborhood bits (l, c, r), new cell =
//   bit((l<<2)|(c<<1)|r)  of the rule index (0..255).
// So Rule 30 is 0b00011110, Rule 90 is 0b01011010, Rule 110 is
// 0b01101110 (Turing-complete). The pot sweeps all 256 rules.
//
// Pin map:
//   PB0 = C_new output
//   PB1 = L neighbor input (button / wire)
//   PB2 = rule selector pot (ADC1)
//   PB3 = C   current-cell input (button / wire)
//   PB4 = R   neighbor input (button / wire)
//
// All three inputs use internal pull-ups and are active-low (open /
// not-driven = 0, pulled to GND = 1). That way an unconnected chip
// sees (0,0,0) → output is rule bit 0.

#define F_CPU 1200000UL
#include <avr/io.h>

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    DDRB  |= _BV(PB0);
    PORTB |= _BV(PB1) | _BV(PB3) | _BV(PB4);   // pull-ups on inputs

    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    while (1) {
        uint8_t rule = (uint8_t)(adc_read(1) >> 2);   // 0..255

        uint8_t l = (PINB & _BV(PB1)) ? 0 : 1;
        uint8_t c = (PINB & _BV(PB3)) ? 0 : 1;
        uint8_t r = (PINB & _BV(PB4)) ? 0 : 1;

        uint8_t lcr = (uint8_t)((l << 2) | (c << 1) | r);
        uint8_t out = (rule >> lcr) & 0x01;

        if (out) PORTB |=  _BV(PB0); else PORTB &= ~_BV(PB0);
    }
}

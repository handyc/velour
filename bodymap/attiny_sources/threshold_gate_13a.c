// threshold_gate_13a — comparator with hysteresis on the '13a.
//
// Same behavior as threshold_gate.c (the '85 version) — squeezed into
// 1 KB flash. The '13a has the same ADC-pin mapping as the '85 for the
// channels we use, so layout notes port directly.
//
// Pin map:
//   PB0 = gate out       (high when signal > threshold)
//   PB1 = transition LED (toggles on every edge)
//   PB2 = threshold pot  (ADC1)
//   PB3 = signal in      (ADC3)

#define F_CPU 1200000UL
#include <avr/io.h>

#define HYST_BITS 2

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    DDRB  |= _BV(PB0) | _BV(PB1);
    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    uint8_t gate = 0;
    while (1) {
        uint16_t thresh = adc_read(1);
        uint16_t signal = adc_read(3);
        uint16_t lo = (thresh >= (1u << HYST_BITS)) ? (thresh - (1u << HYST_BITS)) : 0;
        uint16_t hi = thresh + (1u << HYST_BITS);

        if (!gate && signal > hi) { gate = 1; PORTB ^= _BV(PB1); }
        if (gate && signal < lo)  { gate = 0; PORTB ^= _BV(PB1); }

        if (gate) PORTB |=  _BV(PB0);
        else      PORTB &= ~_BV(PB0);
    }
}

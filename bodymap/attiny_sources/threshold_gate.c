// threshold_gate — analog input crosses a pot-set threshold → digital pulse.
//
// Pin map:
//   PB0 = digital gate output  (high when input > threshold)
//   PB1 = status LED (blinks on transitions, helps tune the pot live)
//   PB2 = threshold pot       (ADC1)
//   PB3 = signal input        (ADC3) — piezo, mic envelope, photocell, etc.
//
// Classic comparator with a little hysteresis so it doesn't chatter on
// noisy inputs. Tweak HYST_BITS below to make the gate more/less jittery.

#define F_CPU 8000000UL
#include <avr/io.h>

#define HYST_BITS 2   // ±4 counts of hysteresis on a 10-bit reading

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    DDRB  |= _BV(PB0) | _BV(PB1);
    ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1);

    uint8_t gate = 0;
    while (1) {
        uint16_t thresh = adc_read(1);   // PB2
        uint16_t signal = adc_read(3);   // PB3
        uint16_t lo = (thresh >= (1u << HYST_BITS)) ? (thresh - (1u << HYST_BITS)) : 0;
        uint16_t hi = thresh + (1u << HYST_BITS);

        if (!gate && signal > hi) { gate = 1; PORTB ^= _BV(PB1); }
        if (gate && signal < lo)  { gate = 0; PORTB ^= _BV(PB1); }

        if (gate) PORTB |=  _BV(PB0);
        else      PORTB &= ~_BV(PB0);
    }
}

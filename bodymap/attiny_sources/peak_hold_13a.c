// peak_hold_13a — max detector with pot-controlled decay, '13a edition.
//
// Pin map:
//   PB0 = PWM held-peak output
//   PB2 = decay pot (ADC1)  — right = slower decay
//   PB3 = signal in (ADC3)
//
// Latches the highest reading and decays slowly. Turns a brief event
// (tap, snap, footfall) into a sustained level on PB0 that a slower
// reader can see.

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
    TCCR0A = _BV(COM0A1) | _BV(WGM00) | _BV(WGM01);
    TCCR0B = _BV(CS01);
    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    uint16_t peak = 0;
    uint16_t tick = 0;

    while (1) {
        uint16_t signal = adc_read(3);
        uint16_t decay  = adc_read(1);

        if (signal > peak) peak = signal;

        uint16_t every = 1 + decay;
        if (++tick >= every) { tick = 0; if (peak) peak--; }

        OCR0A = (uint8_t)(peak >> 2);
    }
}

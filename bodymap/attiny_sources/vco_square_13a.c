// vco_square_13a — pot-controlled square wave generator.
//
// 1.2 MHz CPU is slow enough that audio frequencies need tight loops —
// this covers roughly 50 Hz to 2 kHz. Good enough for a piezo chirper,
// an optical tachometer reference, or a test pulse for the ESP's ADC.
//
// Pin map:
//   PB0 = square wave output
//   PB2 = frequency pot (ADC1)
//   PB4 = duty cycle pot (ADC2)

#define F_CPU 1200000UL
#include <avr/io.h>
#include <util/delay_basic.h>

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    DDRB  |= _BV(PB0);
    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    while (1) {
        uint16_t freq_pot = adc_read(1);
        uint16_t duty_pot = adc_read(2);

        uint16_t period_loops = 4 + ((600UL * freq_pot) >> 10);
        uint16_t hi = (uint16_t)(((uint32_t)period_loops * duty_pot) >> 10);
        if (hi == 0) hi = 1;
        uint16_t lo = period_loops - hi;
        if (lo == 0) lo = 1;

        PORTB |=  _BV(PB0); _delay_loop_2(hi);
        PORTB &= ~_BV(PB0); _delay_loop_2(lo);
    }
}

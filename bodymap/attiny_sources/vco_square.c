// vco_square — pot-controlled square wave generator.
//
// Pin map:
//   PB0 = square wave output    (audio freq, ~50 Hz – 8 kHz)
//   PB2 = frequency pot (ADC1)  — right = higher note
//   PB4 = waveform pot (ADC2)   — duty cycle 5–95%
//
// Hook PB0 through a small cap to a piezo buzzer for a proper oscillator
// toy, or into an ESP ADC as a known-frequency reference signal. The
// code uses busy-wait delays because Timer0 is reserved for fast PWM
// duty control (you can swap to Timer1-driven CTC if you want cleaner
// frequencies).

#define F_CPU 8000000UL
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
    ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1);

    while (1) {
        uint16_t freq_pot = adc_read(1);   // 0..1023
        uint16_t duty_pot = adc_read(2);   // 0..1023

        // 4..2000 loop-cycle periods total, split into hi/lo by duty.
        uint16_t period_loops = 4 + ((2000UL * freq_pot) >> 10);
        uint16_t hi = (uint16_t)(((uint32_t)period_loops * duty_pot) >> 10);
        if (hi == 0) hi = 1;
        uint16_t lo = period_loops - hi;
        if (lo == 0) lo = 1;

        PORTB |=  _BV(PB0);
        _delay_loop_2(hi);
        PORTB &= ~_BV(PB0);
        _delay_loop_2(lo);
    }
}

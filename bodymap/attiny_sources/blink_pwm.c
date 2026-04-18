// blink_pwm — simplest possible template. A pot fades an LED.
//
// Pin map:
//   PB0 = PWM output       (hook an LED + resistor to ground)
//   PB2 = pot wiper (ADC1) (tie 3.3V and GND to the pot ends)
//
// Turn the pot, the LED gets brighter or dimmer. No filter, no memory —
// just raw pot → PWM. The simplest thing that demonstrates the whole
// toolchain (ADC + Timer0 PWM + avr-libc) works.

#define F_CPU 8000000UL
#include <avr/io.h>

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    DDRB  |= _BV(PB0);                       // PB0 = output
    TCCR0A = _BV(COM0A1) | _BV(WGM00) | _BV(WGM01);  // fast PWM on OC0A
    TCCR0B = _BV(CS01);                      // clk/8 → ~3.9 kHz PWM
    ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1);    // ADC on, /64 prescaler

    while (1) {
        uint16_t pot = adc_read(1);          // ADC1 = PB2
        OCR0A = (uint8_t)(pot >> 2);         // 10-bit → 8-bit duty
    }
}

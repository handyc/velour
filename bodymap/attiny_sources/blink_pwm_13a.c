// blink_pwm_13a — ATtiny13a version of the blink/PWM starter.
//
// The '13a is smaller than the '85 in every way: 1 KB flash, 64 bytes
// RAM, no USI peripheral (so no I2C slave without software-banging),
// Timer0 only. Out of the box CKDIV8 fuse is set, so the CPU runs at
// 1.2 MHz from the 9.6 MHz internal oscillator — clear the fuse in
// the flash dialog if you want the full 9.6 MHz.
//
// Pin map (same as the '85 templates — the shared ADC/PWM pinout is
// intentional so designs can be prototyped on an '85 and squeezed
// down to a '13a once they're stable):
//   PB0 = PWM output (OC0A)
//   PB2 = pot wiper  (ADC1)

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
    TCCR0A = _BV(COM0A1) | _BV(WGM00) | _BV(WGM01);  // fast PWM on OC0A
    TCCR0B = _BV(CS01);                              // clk/8 PWM
    ADCSRA = _BV(ADEN) | _BV(ADPS2);                 // ADC on, /16 prescaler

    while (1) {
        uint16_t pot = adc_read(1);
        OCR0A = (uint8_t)(pot >> 2);
    }
}

// lut_filter_13a — two-input digital filter with pot-selected truth table.
//
// A and B are digital inputs, C is the output. The pot on PB2 picks
// one of the 16 possible boolean functions of two inputs. Because
// every 2-input boolean function corresponds to a 4-bit truth table,
// the LUT *index* is literally its own truth table — C is just
// bit((A<<1)|B) of the selected index.
//
// Pot sweep, roughly:
//   0 = FALSE        4 = NOT A AND B  8 = NOR           12 = NOT A
//   1 = AND          5 = B            9 = XNOR          13 = NOT A OR B
//   2 = A AND NOT B  6 = XOR         10 = NOT B         14 = NAND
//   3 = A            7 = OR          11 = A OR NOT B    15 = TRUE
//
// PB1 fades dim → bright as you sweep (brightness = idx * 16), so you
// can roughly feel where you are in the LUT list without a display.
//
// Pin map:
//   PB0 = output C
//   PB1 = LUT index indicator (OC0B PWM, 0..240)
//   PB2 = LUT selector pot (ADC1)
//   PB3 = input A (digital, internal pull-up)
//   PB4 = input B (digital, internal pull-up)

#define F_CPU 1200000UL
#include <avr/io.h>

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

int main(void) {
    // PB0 + PB1 are outputs; PB3 + PB4 are inputs with pull-ups so a
    // floating wire reads high (open = logical 1, button to GND = 0).
    DDRB  |= _BV(PB0) | _BV(PB1);
    PORTB |= _BV(PB3) | _BV(PB4);

    // Fast PWM on OC0B (PB1) for the index indicator.
    TCCR0A = _BV(COM0B1) | _BV(WGM00) | _BV(WGM01);
    TCCR0B = _BV(CS01);

    ADCSRA = _BV(ADEN) | _BV(ADPS2);

    while (1) {
        uint8_t idx = (uint8_t)(adc_read(1) >> 6);   // 0..15

        uint8_t a = (PINB & _BV(PB3)) ? 1 : 0;
        uint8_t b = (PINB & _BV(PB4)) ? 1 : 0;
        uint8_t ab = (uint8_t)((a << 1) | b);

        if ((idx >> ab) & 1) PORTB |=  _BV(PB0);
        else                 PORTB &= ~_BV(PB0);

        OCR0B = (uint8_t)(idx << 4);
    }
}

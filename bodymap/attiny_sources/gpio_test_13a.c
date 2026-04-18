// gpio_test_13a — bring-up / wiring verification for a fresh ATtiny13a.
//
// Wire up the '13a with LEDs on PB0, PB1, PB3, PB4 (any LED + series
// resistor to ground works). Put a 10k pot between Vcc and GND with
// the wiper on PB2, and a momentary button between RESET (PB5) and
// GND with the usual 10k pull-up.
//
// What it does:
//   * On every boot, check MCUSR. If bit EXTRF is set (the button
//     pulled RESET low) the chip flashes all four LEDs together
//     three times as "hello, I saw your button press".
//   * Then it enters normal mode:
//       - PB1 / PB3 / PB4 run a slow chase so you can confirm each
//         pin is wired and each LED is alive.
//       - PB0 is the pot's mirror — turn the knob, LED fades.
//
// Pin map:
//   PB0 = OC0A PWM — pot-controlled brightness LED
//   PB1 = digital LED (chase step 1)
//   PB2 = pot wiper (ADC1)
//   PB3 = digital LED (chase step 2)
//   PB4 = digital LED (chase step 3)
//   PB5 = RESET / button (hardwired, not configurable without fuses)

#define F_CPU 1200000UL
#include <avr/io.h>
#include <util/delay.h>

#define CHASE_MASK  (_BV(PB1) | _BV(PB3) | _BV(PB4))
#define ALL_MASK    (_BV(PB0) | _BV(PB1) | _BV(PB3) | _BV(PB4))

static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (ADMUX & 0xF0) | (ch & 0x0F);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) { }
    return ADC;
}

static void greet_button(void) {
    // Three quick all-on blinks before normal mode starts.
    for (uint8_t i = 0; i < 3; i++) {
        PORTB |=  ALL_MASK;
        _delay_ms(120);
        PORTB &= ~ALL_MASK;
        _delay_ms(120);
    }
}

int main(void) {
    // Latch + clear MCUSR so the next boot sees a clean slate.
    uint8_t reset_flags = MCUSR;
    MCUSR = 0;

    DDRB |= ALL_MASK;    // PB0 PWM + PB1/PB3/PB4 digital outs
    PORTB &= ~ALL_MASK;

    // Fast PWM on OC0A (PB0). Prescaler /8 → ~586 Hz PWM at 1.2 MHz.
    TCCR0A = _BV(COM0A1) | _BV(WGM00) | _BV(WGM01);
    TCCR0B = _BV(CS01);

    ADCSRA = _BV(ADEN) | _BV(ADPS2);   // ADC on, /16 prescaler

    if (reset_flags & _BV(EXTRF)) {
        greet_button();
    }

    uint8_t step = 0;
    uint8_t ticks = 0;

    while (1) {
        // Brightness = pot reading, full 0..255 range.
        OCR0A = (uint8_t)(adc_read(1) >> 2);

        // Chase rotates every ~40 loop iterations (≈200 ms).
        if (++ticks >= 40) {
            ticks = 0;
            PORTB &= ~CHASE_MASK;
            switch (step) {
                case 0: PORTB |= _BV(PB1); break;
                case 1: PORTB |= _BV(PB3); break;
                case 2: PORTB |= _BV(PB4); break;
            }
            step = (step + 1) % 3;
        }

        _delay_ms(5);
    }
}

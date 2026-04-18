// peak_hold — max-value detector with pot-controlled decay.
//
// Pin map:
//   PB0 = PWM held-peak output
//   PB2 = decay rate pot (ADC1) — right = slower decay (longer hold)
//   PB3 = signal input   (ADC3)
//
// Tracks the highest reading seen in the recent past. Good for
// triggering from short events (taps, finger snaps, footfall) where
// the raw signal is over in a few ms but you want the downstream
// reader to see a sustained level. If decay is all the way right,
// the meter sticks forever (manual reset = power cycle or set decay
// left for a moment).

#define F_CPU 8000000UL
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
    ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1);

    uint16_t peak = 0;
    uint16_t tick = 0;

    while (1) {
        uint16_t signal = adc_read(3);
        uint16_t decay  = adc_read(1);

        if (signal > peak) peak = signal;

        // Decay: subtract 1 every N ticks, where N scales with the pot.
        // decay=0   → subtract every tick (very fast).
        // decay=1023→ subtract every ~1000 ticks (slow hold).
        uint16_t every = 1 + (decay >> 0);
        if (++tick >= every) {
            tick = 0;
            if (peak) peak--;
        }

        OCR0A = (uint8_t)(peak >> 2);
    }
}

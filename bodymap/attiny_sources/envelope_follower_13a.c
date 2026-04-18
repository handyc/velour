// envelope_follower_13a — simplified one-pole lowpass for the '13a.
//
// The '85 version uses Q16 math on 32-bit integers; the '13a's 64 B
// of RAM and 1 KB of flash push us toward Q8 on 16-bit ints. Gives
// you about 1% precision on the envelope — plenty for driving an
// LED or a slow motor, stingy if you want audio-grade smoothing.
//
// Pin map:
//   PB0 = PWM envelope out
//   PB2 = decay pot (ADC1)   — right = slower release
//   PB3 = signal in (ADC3)

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

    uint16_t env_q8 = 0;   // Q8 envelope in 0..65535

    while (1) {
        uint16_t sig = adc_read(3);
        uint16_t pot = adc_read(1);

        // Rectify around midrail and promote to Q8 (signal bits in high byte).
        int16_t rect = (int16_t)sig - 512;
        if (rect < 0) rect = -rect;
        uint16_t target = (uint16_t)(rect << 7);

        // k roughly 1/256 .. 1/2.  pot=0 → fast follow, pot=1023 → slow.
        uint8_t k = 1 + (uint8_t)(pot >> 3);          // 1..128
        uint8_t shift = (uint8_t)(8 - (k >> 4));      // 4..8

        if (target > env_q8) env_q8 += (target - env_q8) >> shift;
        else                 env_q8 -= (env_q8 - target) >> shift;

        OCR0A = (uint8_t)(env_q8 >> 8);
    }
}

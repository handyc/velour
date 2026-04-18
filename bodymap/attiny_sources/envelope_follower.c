// envelope_follower — one-pole exponential smoothing on an analog input.
//
// Pin map:
//   PB0 = PWM envelope output (0–255 → 0–Vcc)
//   PB2 = decay pot  (ADC1)   — harder right = slower release
//   PB3 = signal in  (ADC3)   — e.g. electret mic + amp, piezo, IR pair
//
// Typical use: audio/vibration amplitude envelope for a light or motor.
// The math is the classic "y += (x - y) * k" one-pole lowpass, with k
// derived from the pot so the user can feel slow vs snappy response.
// Fixed point (Q8) because the ATtiny has no FPU.

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

    uint32_t env_q16 = 0;            // 16.16 fixed-point envelope

    while (1) {
        uint32_t sig = adc_read(3);              // 0..1023
        uint16_t pot = adc_read(1);              // 0..1023
        // k in Q16 — small pot = fast follow (k≈0.5), large pot = slow (k≈1/256).
        uint16_t k_q16 = 64 + (pot << 5);        // 64..32800 out of 65536

        // Rectify (|signal - midrail|) and shift to Q16.
        int16_t rect = (int16_t)sig - 512;
        if (rect < 0) rect = -rect;
        uint32_t target_q16 = ((uint32_t)rect) << 17;  // 9-bit → 26-bit headroom

        // env += (target - env) * k
        if (target_q16 > env_q16) env_q16 += ((target_q16 - env_q16) >> 16) * k_q16;
        else                      env_q16 -= ((env_q16 - target_q16) >> 16) * k_q16;

        OCR0A = (uint8_t)((env_q16 >> 18) & 0xFF);
    }
}

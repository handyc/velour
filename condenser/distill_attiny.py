"""Tier 3→4: Distill to ATTiny13a C code.

Key insight: on a microcontroller, live pin readings replace what
would have been variables, database rows, or API calls in a larger
app. A pin reading IS a query. Setting a pin IS a write operation.
The GPIO bus IS the database.

The ATTiny13a has:
  - 1KB flash, 64B SRAM
  - 6 usable GPIO pins (PB0-PB5)
  - ADC on PB2-PB4 (10-bit, can distinguish 3-4 voltage levels)
  - Internal 9.6 MHz oscillator

Pin assignment strategy:
  - 2 ADC inputs: read neighbor edge "colors" as voltage levels
    (0V = color 0, 1.1V = color 1, 2.2V = color 2, 3.3V = color 3)
  - 2 PWM outputs: express this tile's edge colors as voltage levels
  - 1 status LED
  - 1 unused (future: cascade clock input)

Using ADC means 3-4 colors fit, not just 2. This is a significant
improvement over pure digital (which limits to 2 colors per pin).
"""


def distill(tileset_name='2-color checkerboard'):
    """Generate ATTiny13a C code for Wang tile matching via ADC."""

    # Load tileset from Django if available
    tiles = []
    colors = []
    try:
        from tiles.models import TileSet
        ts = TileSet.objects.filter(name__icontains=tileset_name).first()
        if not ts:
            ts = TileSet.objects.filter(tile_type='square').first()
        if ts:
            for t in ts.tiles.all():
                tiles.append([t.n_color, t.e_color, t.s_color, t.w_color])
            colors = ts.palette or []
    except Exception:
        pass

    if not tiles:
        colors = ['#58a6ff', '#f85149']
        for bits in range(16):
            tiles.append([
                colors[(bits >> 3) & 1], colors[(bits >> 2) & 1],
                colors[(bits >> 1) & 1], colors[bits & 1],
            ])

    if not colors:
        all_c = set()
        for t in tiles:
            all_c.update(t)
        colors = sorted(all_c)

    nc = len(colors)
    cmap = {c: i for i, c in enumerate(colors)}

    # Build lookup table: for each (N_in, W_in) combo, find first
    # matching tile and store (S_out, E_out)
    max_combos = nc * nc
    lut = []
    for n_in in range(nc):
        for w_in in range(nc):
            found = False
            for t in tiles:
                if cmap.get(t[0], 0) == n_in and cmap.get(t[3], 0) == w_in:
                    lut.append((cmap.get(t[2], 0), cmap.get(t[1], 0)))
                    found = True
                    break
            if not found:
                lut.append((0, 0))

    lut_bytes = ', '.join('0x%02X' % ((s << 4) | e) for s, e in lut)

    # ADC thresholds for distinguishing N colors
    # At 10-bit ADC (0-1023), with 3.3V ref:
    # 2 colors: threshold at 512
    # 3 colors: thresholds at 341, 682
    # 4 colors: thresholds at 256, 512, 768
    if nc <= 2:
        adc_decode = '''    // 2 colors: simple threshold at midpoint
    return (adc > 512) ? 1 : 0;'''
    elif nc == 3:
        adc_decode = '''    // 3 colors: two thresholds
    if (adc < 341) return 0;
    if (adc < 682) return 1;
    return 2;'''
    else:
        adc_decode = '''    // 4 colors: three thresholds
    if (adc < 256) return 0;
    if (adc < 512) return 1;
    if (adc < 768) return 2;
    return 3;'''

    # PWM output values for each color
    # Map color index to PWM duty cycle (0-255)
    pwm_values = []
    for i in range(nc):
        pwm_values.append(255 * i // max(nc - 1, 1))
    pwm_arr = ', '.join(str(v) for v in pwm_values)

    return '''// CONDENSER: Tier 4 — ATTiny13a Wang tile matcher
//
// GPIO pins ARE the database. Reading a pin IS a query.
// Setting a pin IS a write. The bus IS the data store.
//
// Colors: ''' + ', '.join('%s=%d' % (c, i) for i, c in enumerate(colors)) + '''
// Tiles: ''' + str(len(tiles)) + ''' in source set, ''' + str(len(lut)) + '''-entry LUT
//
// Pin assignment:
//   PB3 (ADC3, pin 2): N input — read neighbor's S edge as voltage
//   PB4 (ADC2, pin 3): W input — read neighbor's E edge as voltage
//   PB0 (OC0A, pin 5): S output — PWM voltage for our S edge
//   PB1 (OC0B, pin 6): E output — PWM voltage for our E edge
//   PB2 (pin 7):        status LED
//
// ADC reads voltage levels to distinguish ''' + str(nc) + ''' colors.
// PWM outputs produce corresponding voltages for downstream tiles.
// Multiple ATTiny13a chips can be wired in a grid — each one's
// outputs feed the next one's inputs, forming a physical Wang tiling.

#include <avr/io.h>
#include <util/delay.h>

// Lookup table: index = (N_color * ''' + str(nc) + ''') + W_color
// Value: high nibble = S_color, low nibble = E_color
static const uint8_t LUT[] PROGMEM = { ''' + lut_bytes + ''' };

// PWM values for each color (0-255 duty cycle)
static const uint8_t COLOR_PWM[] PROGMEM = { ''' + pwm_arr + ''' };

#define N_COLORS ''' + str(nc) + '''

// Read ADC channel and decode to color index
static uint8_t read_color(uint8_t channel) {
    ADMUX = channel;  // select ADC channel, Vcc ref
    ADCSRA |= (1 << ADSC);  // start conversion
    while (ADCSRA & (1 << ADSC));  // wait
    uint16_t adc = ADC;
''' + adc_decode + '''
}

int main(void) {
    // Pin directions: PB0,PB1 = output (PWM), PB2 = output (LED)
    DDRB = (1 << PB0) | (1 << PB1) | (1 << PB2);

    // Enable ADC: prescaler /64 for ~150kHz at 9.6MHz
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1);

    // Timer0 for PWM on PB0 (OC0A) and PB1 (OC0B)
    TCCR0A = (1 << COM0A1) | (1 << COM0B1) | (1 << WGM01) | (1 << WGM00);
    TCCR0B = (1 << CS01);  // prescaler /8

    while (1) {
        // READ: query the pin "database" for neighbor edges
        uint8_t n_color = read_color(3);  // ADC3 = PB3
        uint8_t w_color = read_color(2);  // ADC2 = PB4

        // MATCH: lookup the tile for these inputs
        uint8_t idx = n_color * N_COLORS + w_color;
        uint8_t result = pgm_read_byte(&LUT[idx]);
        uint8_t s_color = (result >> 4) & 0x0F;
        uint8_t e_color = result & 0x0F;

        // WRITE: set output pins to the matched edge colors
        OCR0A = pgm_read_byte(&COLOR_PWM[s_color]);  // PB0 = S edge
        OCR0B = pgm_read_byte(&COLOR_PWM[e_color]);  // PB1 = E edge

        // Status blink
        PORTB ^= (1 << PB2);

        _delay_ms(100);
    }
    return 0;
}
'''

"""Tier 3→4: Distill ESP8266 logic into ATTiny13a C code.

The ATTiny13a has:
  - 1KB flash (1024 bytes)
  - 64 bytes SRAM
  - 8 pins (6 usable as GPIO, 1 VCC, 1 GND)
  - No WiFi, no display, no serial (in practice)
  - 9.6 MHz internal oscillator

What survives: the CORE DECISION LOGIC of Wang tile matching.
Everything else is gone — no UI, no network, no storage.

The tile matching algorithm becomes:
  1. Read 4 input pins (neighbor edge colors, binary: HIGH/LOW = 2 colors)
  2. Look up the matching tile in a compact table in flash
  3. Set 4 output pins to the matched tile's opposite edges
  4. Delay, then repeat

For a 2-color square tileset (16 possible tiles), the lookup table
is 16 entries × 1 byte = 16 bytes. The entire program fits in ~200
bytes of flash, leaving 800 bytes for expansion.

What the automated distiller does:
  - Extract the 2-color matching logic
  - Generate a minimal avr-gcc C program
  - Compute the lookup table from the tileset
  - Target the ATTiny13a's pin assignments

What Claude would do differently:
  - Choose meaningful pin assignments based on physical layout
  - Add a clever encoding that packs more state into fewer pins
  - Design the timing to create visual patterns on LEDs
  - Consider power consumption and sleep modes
"""


def distill(tileset_name='2-color checkerboard'):
    """Generate ATTiny13a C code for a 2-color square tileset."""

    # Try to load the tileset from Django
    tiles = []
    try:
        from tiles.models import TileSet
        ts = TileSet.objects.filter(name__icontains=tileset_name).first()
        if ts:
            for t in ts.tiles.all():
                tiles.append({
                    'n': t.n_color, 'e': t.e_color,
                    's': t.s_color, 'w': t.w_color,
                })
    except Exception:
        pass

    if not tiles:
        # Fallback: generate a minimal 2-color set
        tiles = []
        for bits in range(16):
            tiles.append({
                'n': '#58a6ff' if (bits >> 3) & 1 else '#f85149',
                'e': '#58a6ff' if (bits >> 2) & 1 else '#f85149',
                's': '#58a6ff' if (bits >> 1) & 1 else '#f85149',
                'w': '#58a6ff' if bits & 1 else '#f85149',
            })

    # Build the color-to-bit mapping
    colors = sorted(set(t['n'] for t in tiles) | set(t['e'] for t in tiles) |
                     set(t['s'] for t in tiles) | set(t['w'] for t in tiles))
    if len(colors) > 2:
        colors = colors[:2]  # ATTiny can only handle 2 colors (binary pins)

    color_map = {c: i for i, c in enumerate(colors)}

    # Build lookup table: input = (n_in, w_in) as 2 bits → output = (s_out, e_out) as 2 bits
    # For a Wang tiling, we need to find a tile whose N matches the input N
    # and whose W matches the input W, then output its S and E.
    lookup = []
    for n_in in range(2):
        for w_in in range(2):
            # Find first tile matching these constraints
            found = False
            for t in tiles:
                tn = color_map.get(t['n'], 0)
                tw = color_map.get(t['w'], 0)
                if tn == n_in and tw == w_in:
                    te = color_map.get(t['e'], 0)
                    ts_val = color_map.get(t['s'], 0)
                    lookup.append((ts_val << 1) | te)
                    found = True
                    break
            if not found:
                lookup.append(0)

    lookup_str = ', '.join('0x%02X' % v for v in lookup)

    return f'''// ============================================================
// CONDENSER: Tier 4 — ATTiny13a distillation
//
// Wang tile edge-matching in 200 bytes of flash.
//
// Pin assignment:
//   PB0 (pin 5): N input  — north neighbor's south edge
//   PB1 (pin 6): W input  — west neighbor's east edge
//   PB2 (pin 7): S output — this tile's south edge
//   PB3 (pin 2): E output — this tile's east edge
//   PB4 (pin 3): status LED (blinks on each match cycle)
//
// Colors: {colors[0]} = LOW, {colors[1]} = HIGH
//
// The lookup table maps (N_in, W_in) → (S_out, E_out).
// 4 entries × 1 byte = 4 bytes. The rest is boilerplate.
//
// What survived from Tier 3:
//   - The tile matching algorithm (2 inputs → 2 outputs)
//   - The concept of edge-color constraints
//
// What was lost:
//   - All visual rendering (no display)
//   - All networking (no WiFi)
//   - All user interaction (no buttons, no browser)
//   - Hex tiles (only square, 2-color fits)
//   - Tileset selection (one set hardcoded)
//
// What a Claude distillation would do differently:
//   - Use the remaining 800 bytes for a state machine that
//     walks a virtual grid, outputting edges in sequence
//   - Add PWM on the LED to show "mood" (duty cycle = intensity)
//   - Use the ADC pin for analog input (3+ colors via voltage levels)
//   - Design the timing so multiple ATTiny13as can cascade
//     into a physical tiling network
//
// CONDENSER: At Tier 5 (555 timers), this becomes:
//   - Two 555s in astable mode: one for N/S, one for W/E
//   - LM393 comparators for edge matching
//   - RC time constants encode the "color" (HIGH time = color 0 or 1)
//   - The cascade output of one 555 feeds the input of the next
// ============================================================

#include <avr/io.h>
#include <util/delay.h>

// CONDENSER: The entire Wang tile logic in 4 bytes.
// Index = (N_input << 1) | W_input
// Value = (S_output << 1) | E_output
static const uint8_t TILE_LUT[4] PROGMEM = {{ {lookup_str} }};

// CONDENSER: Pin definitions.
// Two inputs (neighbor edges) and two outputs (our edges).
// This is the minimum viable representation of a Wang tile.
#define PIN_N_IN   PB0
#define PIN_W_IN   PB1
#define PIN_S_OUT  PB2
#define PIN_E_OUT  PB3
#define PIN_LED    PB4

#define TICK_MS    500

int main(void) {{
    // Set pin directions
    DDRB = (1 << PIN_S_OUT) | (1 << PIN_E_OUT) | (1 << PIN_LED);
    // Enable pull-ups on inputs
    PORTB = (1 << PIN_N_IN) | (1 << PIN_W_IN);

    // CONDENSER: The main loop — read, match, output.
    // This is the Wang tile algorithm reduced to its essence.
    // The entire loop fits in ~30 instructions.
    while (1) {{
        // Read neighbor edges
        uint8_t n_in = (PINB >> PIN_N_IN) & 1;
        uint8_t w_in = (PINB >> PIN_W_IN) & 1;

        // Look up matching tile
        uint8_t idx = (n_in << 1) | w_in;
        uint8_t result = pgm_read_byte(&TILE_LUT[idx]);
        uint8_t s_out = (result >> 1) & 1;
        uint8_t e_out = result & 1;

        // Set output edges
        if (s_out) PORTB |= (1 << PIN_S_OUT); else PORTB &= ~(1 << PIN_S_OUT);
        if (e_out) PORTB |= (1 << PIN_E_OUT); else PORTB &= ~(1 << PIN_E_OUT);

        // Blink status LED
        PORTB ^= (1 << PIN_LED);

        _delay_ms(TICK_MS);
    }}

    return 0;  // unreachable
}}
'''

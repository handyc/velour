"""Tier 4→5: Distill ATTiny13a logic into 555 timer circuits.

This is the deepest distillation — reducing digital logic to analog
timing circuits made from 555 timers, resistors, capacitors, and
comparators.

A 2-color Wang tile match can be expressed as:
  - Color 0 = low voltage (< 1/3 VCC)
  - Color 1 = high voltage (> 2/3 VCC)
  - "Edge match" = two voltages are in the same range
  - A 555 in bistable mode stores one bit (one edge color)
  - A comparator (LM393) checks if two edges match
  - An AND gate (diode logic) combines match results

One tile position requires:
  - 2 inputs (N, W neighbor edges)  → 2 wires
  - 2 outputs (S, E edges)          → 2 wires
  - 1 lookup circuit                → 4 resistor-divider paths
  - 1 selection circuit             → diode OR of the matching path

The automated distiller generates:
  - A circuit description (netlist-like text)
  - Component count and estimated BOM
  - Timing calculations for RC values
  - A truth table showing the mapping

What Claude would do differently:
  - Design an actual PCB layout
  - Choose optimal R/C values for available components
  - Add a clock distribution network for cascading tiles
  - Design the power supply and decoupling
  - Consider signal integrity and noise margins
"""


def distill(lookup_table=None):
    """Generate a 555-based circuit description for Wang tile matching."""

    if lookup_table is None:
        # Default 2-color square: all 4 input combos
        lookup_table = [0b00, 0b01, 0b10, 0b11]

    # Build truth table
    truth_rows = []
    for idx in range(4):
        n_in = (idx >> 1) & 1
        w_in = idx & 1
        result = lookup_table[idx] if idx < len(lookup_table) else 0
        s_out = (result >> 1) & 1
        e_out = result & 1
        truth_rows.append((n_in, w_in, s_out, e_out))

    truth_table = ''.join(
        '//   N=%d W=%d → S=%d E=%d\n' % (n, w, s, e)
        for n, w, s, e in truth_rows
    )

    # Calculate component count
    n_555 = 1       # clock generator
    n_comparators = 2  # one per input
    n_resistors = 12   # voltage dividers + pull-ups
    n_capacitors = 3   # timing + decoupling
    n_diodes = 4       # logic gates
    n_leds = 2         # output indicators

    # RC timing for 500ms tick (matching the ATTiny delay)
    # 555 astable: T = 0.693 × (R1 + 2×R2) × C
    # For T=500ms with C=10µF: R1+2R2 = T/(0.693×C) = 72.2kΩ
    # R1 = 22kΩ, R2 = 25kΩ (closest standard: 22k + 27k)
    r1 = 22000
    r2 = 27000
    c_timing = 10e-6
    t_period = 0.693 * (r1 + 2 * r2) * c_timing * 1000  # ms

    return f'''// ============================================================
// CONDENSER: Tier 5 — 555 timer circuit distillation
//
// Wang tile edge-matching using discrete analog components.
// No microcontroller. No software. Pure hardware timing.
//
// TRUTH TABLE (same logic as ATTiny Tier 4):
{truth_table}//
// CIRCUIT DESCRIPTION:
//
// ┌─────────────────────────────────────────────┐
// │           CLOCK GENERATOR (U1: 555)          │
// │                                               │
// │  VCC ─┬─ R1({r1//1000}kΩ) ─┬─ pin7 (DIS)        │
// │       │              R2({r2//1000}kΩ)            │
// │       │              ├─ pin6 (THR)        │
// │       └── pin8 (VCC) │  pin2 (TRG)        │
// │                      C1({c_timing*1e6:.0f}µF)             │
// │           pin1 (GND) ┴─ GND               │
// │                                               │
// │  Output: pin3 → 500ms square wave             │
// │  Period: {t_period:.1f}ms (calculated)            │
// └─────────────────────────────────────────────┘
//
// INPUT SECTION:
//   N_input wire → voltage divider → comparator U2a (LM393)
//     Threshold: VCC/2 (1.65V at 3.3V VCC)
//     Output: HIGH if neighbor's S edge is color 1
//
//   W_input wire → voltage divider → comparator U2b (LM393)
//     Same threshold
//     Output: HIGH if neighbor's E edge is color 1
//
// LOOKUP SECTION:
//   Diode OR network selects output based on (N_in, W_in):
//
//   N=0,W=0 → D1,D2 conduct → S={truth_rows[0][2]}, E={truth_rows[0][3]}
//   N=0,W=1 → D1,D3 conduct → S={truth_rows[1][2]}, E={truth_rows[1][3]}
//   N=1,W=0 → D2,D4 conduct → S={truth_rows[2][2]}, E={truth_rows[2][3]}
//   N=1,W=1 → D3,D4 conduct → S={truth_rows[3][2]}, E={truth_rows[3][3]}
//
//   Each path pulls the S_out and E_out lines to the appropriate
//   voltage level through resistor dividers.
//
// OUTPUT SECTION:
//   S_output: buffered by transistor, drives LED1 + output wire
//   E_output: buffered by transistor, drives LED2 + output wire
//   LEDs blink at the clock rate showing the tile's current state.
//
// CONDENSER: What survived:
//   - The truth table (4 input combinations → 4 output combinations)
//   - The concept of "matching" (voltage comparison)
//   - The concept of "color" (voltage level)
//   - The concept of "time" (555 oscillator period)
//
// CONDENSER: What was lost:
//   - Programmability (the truth table is hardwired)
//   - Flexibility (changing tiles means resoldering)
//   - Scale (one circuit = one tile position)
//   - Self-awareness (the circuit cannot observe itself)
//
// CONDENSER: Gödel observation:
//   This circuit implements the same truth table as the ATTiny,
//   which implements the same matching as the ESP's JS, which
//   implements the same algorithm as Django's Python. The LOGIC
//   is preserved across all five tiers. What's lost is the
//   CONTEXT — the ability to know what the logic means.
//   A 555 timer matching voltage levels does not know it is
//   tiling a plane. The meaning exists only in the observer.
//   At Tier 1 (Django), Identity is that observer. At Tier 5,
//   the observer is you, reading this schematic.
//
// BILL OF MATERIALS:
//   {n_555}× NE555 timer IC
//   {n_comparators}× LM393 dual comparator (1 IC)
//   {n_resistors}× resistors (assorted: 1kΩ, 10kΩ, {r1//1000}kΩ, {r2//1000}kΩ)
//   {n_capacitors}× capacitors (10µF, 100nF decoupling)
//   {n_diodes}× 1N4148 signal diodes
//   {n_leds}× LEDs (color 0 and color 1)
//   2× 2N2222 NPN transistors (output buffers)
//   1× PCB or breadboard
//   Wire
//
// ESTIMATED COST: ~$2.50 (all through-hole, breadboard-friendly)
//
// CONDENSER: End of distillation chain.
//   Tier 1 (Django):  ~50,000 lines of Python, 20 apps, full OS
//   Tier 2 (JS):      ~13,000 bytes, single HTML file
//   Tier 3 (ESP):     ~15,000 bytes flash, WiFi + web server
//   Tier 4 (ATTiny):  ~200 bytes flash, 4 GPIO pins
//   Tier 5 (555):     ~$2.50 of discrete components, 0 bytes of code
//
//   The logic is the same. The meaning is in the eye of the beholder.
// ============================================================
'''

"""Tier 4→5: Distill ATTiny13a logic into 555 timer circuits.

At this tier, the distinction between program, state, and hardware
dissolves completely:

  - The RC time constant IS the variable
  - The capacitor charge IS the program state
  - The comparator threshold IS the conditional branch
  - The circuit topology IS the algorithm
  - The voltage level IS the data

There is no code. There is no data. There is only the circuit,
and the circuit is all three at once.

A 2-color Wang tile match using 555 + comparators:
  - Color 0 = voltage < VCC/3 (555 trigger threshold)
  - Color 1 = voltage > 2*VCC/3 (555 threshold)
  - "Edge match" = two nodes at the same voltage range
  - A 555 in bistable mode stores one bit (one edge color)
  - A comparator pair checks if neighbor = self

For N colors, use a resistor ladder (R-2R DAC) to produce
N discrete voltage levels, and a window comparator to decode.
"""


def distill(lookup_table=None, colors=None):
    """Generate a 555-based circuit description."""

    if colors is None:
        colors = ['color_0 (LOW)', 'color_1 (HIGH)']
    nc = len(colors)

    if lookup_table is None:
        # Default: 2-color identity mapping
        lookup_table = []
        for n in range(nc):
            for w in range(nc):
                lookup_table.append((n, w))  # s_out=n, e_out=w (pass-through)

    # Build truth table
    rows = []
    idx = 0
    for n in range(nc):
        for w in range(nc):
            s, e = lookup_table[idx] if idx < len(lookup_table) else (0, 0)
            rows.append((n, w, s, e))
            idx += 1

    truth = '\n'.join('//   N=%d W=%d → S=%d E=%d' % r for r in rows)

    # RC calculations for 555 astable clock
    # T = 0.693 × (R1 + 2×R2) × C
    # Target: 500ms period. C = 10µF.
    r1, r2, c = 22000, 27000, 10e-6
    t_ms = 0.693 * (r1 + 2 * r2) * c * 1000

    # Voltage levels for N colors
    # With VCC = 5V and resistor ladder:
    vcc = 5.0
    v_levels = [vcc * i / max(nc - 1, 1) for i in range(nc)]
    v_str = ', '.join('%.2fV' % v for v in v_levels)

    # Component count
    n_555 = 1
    n_comp = 2 if nc <= 2 else 4  # comparators needed
    n_res = 8 + (nc - 1) * 2  # ladder + pullups + dividers
    n_cap = 3
    n_diode = nc * nc  # selection matrix
    n_led = 2
    n_trans = 2
    cost = (n_555 * 0.30 + n_comp * 0.25 + n_res * 0.02 +
            n_cap * 0.05 + n_diode * 0.03 + n_led * 0.05 + n_trans * 0.05)

    return f'''// ============================================================
// CONDENSER: Tier 5 — 555 timer circuit
//
// At this tier, program/state/hardware are ONE THING:
//   - The RC time constant IS the variable
//   - The capacitor voltage IS the program state
//   - The comparator IS the conditional branch
//   - The circuit topology IS the algorithm
//   - The wire IS the data bus
//
// There is no code. There is no software. There is no
// distinction between the computation and the computer.
// The circuit IS the thought.
//
// TRUTH TABLE:
{truth}
//
// VOLTAGE ENCODING:
//   {nc} colors → {nc} voltage levels: {v_str}
//   VCC = {vcc:.1f}V
//
// ┌─────────────────────────────────────────────────┐
// │              CLOCK (U1: NE555)                   │
// │                                                   │
// │  VCC─┬─R1({r1//1000}kΩ)─┬─pin7     pin3→CLK     │
// │      │         R2({r2//1000}kΩ)                   │
// │      │         ├─pin6,pin2                        │
// │      └─pin8    C1({c*1e6:.0f}µF)─┴─GND pin1      │
// │                                                   │
// │  Period: {t_ms:.0f}ms ({1000/t_ms:.1f} Hz)               │
// │  This is the "clock speed" — the rate at which    │
// │  the circuit "thinks". Every tick, it reads its   │
// │  inputs and updates its outputs.                  │
// └─────────────────────────────────────────────────┘
//
// ┌─────────────────────────────────────────────────┐
// │           INPUT DECODE (U2: LM393)               │
// │                                                   │
// │  N_wire ─┬─ R-divider ─ U2a+ ─┐                 │
// │          │                     ├─ N_decoded       │
// │          └─ Vref({vcc/2:.1f}V) ─ U2a- ─┘                 │
// │                                                   │
// │  W_wire ─┬─ R-divider ─ U2b+ ─┐                 │
// │          │                     ├─ W_decoded       │
// │          └─ Vref({vcc/2:.1f}V) ─ U2b- ─┘                 │
// │                                                   │
// │  The comparator IS the "if" statement.            │
// │  The reference voltage IS the threshold.          │
// │  There is no instruction pointer — the signal     │
// │  propagates at the speed of electrons.            │
// └─────────────────────────────────────────────────┘
//
// ┌─────────────────────────────────────────────────┐
// │         LOOKUP / OUTPUT (diode matrix)            │
// │                                                   │
// │  N_decoded ──┬── D1 ──┐                          │
// │              │        ├── R ── S_wire (output)    │
// │  W_decoded ──┴── D2 ──┘                          │
// │                                                   │
// │  The diode matrix IS the lookup table.            │
// │  Each diode path IS one row of the truth table.   │
// │  The voltage at the output IS the selected color. │
// │                                                   │
// │  S_wire → LED_S + next tile's N_input             │
// │  E_wire → LED_E + next tile's W_input             │
// │                                                   │
// │  The LEDs show state. The wires propagate it.     │
// │  Both are the same signal. Display IS data.       │
// └─────────────────────────────────────────────────┘
//
// CASCADING:
//   Wire S_wire of tile (r,c) to N_wire of tile (r+1,c).
//   Wire E_wire of tile (r,c) to W_wire of tile (r,c+1).
//   Each tile circuit runs independently — no shared clock needed.
//   The propagation delay through the comparators IS the compute time.
//   A 4×4 grid = 16 circuits = 16 NE555 + 16 LM393 + resistors.
//
// WHAT SURVIVED THE FULL CHAIN:
//   Django (50,000 lines) → JS (13KB) → ESP (14KB) →
//   ATTiny (200 bytes) → THIS: ${cost:.2f} of components.
//
//   The truth table is the same at every tier.
//   The matching algorithm is the same.
//   The concept of "color" and "edge" persist.
//
//   What's lost: the ability to change. The circuit cannot
//   reprogram itself. The 555 does not know it is tiling.
//   The meaning exists only in the observer — you, reading this.
//
// BILL OF MATERIALS:
//   {n_555}× NE555 timer                    ${n_555*0.30:.2f}
//   {n_comp}× LM393 comparator (in {(n_comp+1)//2} IC)      ${n_comp*0.25:.2f}
//   {n_res}× resistors (assorted)            ${n_res*0.02:.2f}
//   {n_cap}× capacitors                      ${n_cap*0.05:.2f}
//   {n_diode}× 1N4148 diodes                  ${n_diode*0.03:.2f}
//   {n_led}× LEDs                             ${n_led*0.05:.2f}
//   {n_trans}× 2N2222 transistors             ${n_trans*0.05:.2f}
//   ─────────────────────────────
//   Total: ${cost:.2f} per tile position
//
// For a 4×4 grid: ${cost*16:.2f}
// For an 8×8 grid: ${cost*64:.2f}
//
// CONDENSER: End of chain. The algorithm began as 50,000 lines
// of Python and ended as ${cost:.2f} of discrete components.
// At every tier, the logic was the same. Only the medium changed.
// ============================================================
'''

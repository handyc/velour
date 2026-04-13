"""Condenser: ATTiny13a multi-channel decision tree + picoUART + Gödel + bytebeat.

Generates C firmware for ATTiny13a that:
  1. Reads 1-4 analog channels via the 10-bit ADC
  2. Optionally median-of-3 filters each reading
  3. Walks a multi-variate binary decision tree (each branch picks a channel)
  4. Sends a framed packet via picoUART TX to a connected ESP
  5. On a trigger condition, transmits a self-description of its own
     decision logic — a Gödel self-reference that lets the ESP (and
     Velour) reconstruct the tree without the source code
  6. Optionally runs a bytebeat audio generator on PB1 (PWM), where the
     decision tree result selects which formula plays — the chip senses,
     decides, reports, and sings about it

The tree node layout (5 bytes each in PROGMEM):
  Branch: [channel, threshold_hi, threshold_lo, left_idx, right_idx]
  Leaf:   [0xFF,    value,        0,            0,        0        ]

Flash budget on ATTiny13a (1024 bytes):
  - Vectors + init:          ~50 bytes
  - picoUART TX:             ~40 bytes
  - ADC read (parameterized): ~35 bytes
  - Median-of-3 filter:      ~50 bytes
  - Multi-channel main loop:  ~80 bytes
  - Tree walker:              ~50 bytes
  - Framed TX (sync+XOR):    ~30 bytes
  - Tree data (15 nodes):     ~75 bytes
  - Gödel self-reference:    ~400 bytes (metadata + describe + CRC)
  - Bytebeat engine:         ~120 bytes (PWM init + 8 formulas + switcher)
  - TOTAL:                   ~930 bytes (tight but fits)

Pin assignment (3 channels, RESET intact):
  PB2 (ADC1, pin 7): analog input channel 1
  PB3 (ADC3, pin 2): analog input channel 2
  PB4 (ADC2, pin 3): analog input channel 3
  PB0 (pin 5):       picoUART TX to ESP RX
  PB1 (OC0B, pin 6): bytebeat PWM audio output (or status LED if no bytebeat)

With RSTDISBL fuse burned (4 channels, needs HV programmer to reflash):
  PB5 (ADC0, pin 1): analog input channel 4 (was RESET)

picoUART: https://github.com/nerdralph/picoUART
"""

import hashlib
import time


# Classic bytebeat formulas — each is a C expression using `t` (uint32_t counter).
# These are the canonical community-discovered formulas, all public domain.
# The result is cast to uint8_t and written to the PWM duty cycle register.
#
# Each formula produces a distinct character when output as 8-bit 8kHz audio:
#   0: silence (for when bytebeat is off for a given state)
#   1: Sierpinski harmonics   — the original bytebeat (Viznut 2011)
#   2: Crowd chant            — rhythmic alien choir
#   3: Acid bass              — TB-303-esque squelch
#   4: Cathedral bells        — slow harmonic shimmer
#   5: Bitcrushed drums       — percussive noise pattern
#   6: Underwater             — bubbly low-frequency warble
#   7: Alarm                  — urgent alternating tones

BYTEBEAT_FORMULAS = [
    ('silence',            '0'),
    ('sierpinski',         't*(t>>5|t>>8)'),
    ('crowd',              '(t*(t>>5&t))>>(t>>7)'),
    ('acid',               't*(((t>>12)|(t>>8))&(63&(t>>4)))'),
    ('bells',              '(t>>6|t|t>>(t>>16))*10+((t>>11)&7)'),
    ('drums',              '(t|(t>>9|t>>7))*t&(t>>11|t>>9)'),
    ('underwater',         '(t*(t>>8*(t>>15|t>>8)&(20|(t>>19)*5>>t|t>>3)))'),
    ('alarm',              '(t>>4)*(((t>>1)*(t>>3)*t>>4)|(t>>10))'),
]


def build_tree_nodes(rules):
    """Convert multi-channel rules into a balanced binary decision tree.

    Each rule: {'channel': int, 'threshold': int, 'label': str, 'value': int}
    Rules are sorted by (channel, threshold) and built into a BST.
    Branch nodes store which channel to read.

    Returns a list of node dicts.
    """
    if not rules:
        rules = _default_rules()

    rules = sorted(rules, key=lambda r: (r.get('channel', 0), r['threshold']))
    nodes = []

    def _build(lo, hi):
        if lo >= hi:
            r = rules[min(lo, len(rules) - 1)]
            idx = len(nodes)
            nodes.append({
                'type': 'leaf',
                'value': r['value'],
                'label': r.get('label', ''),
            })
            return idx

        mid = (lo + hi) // 2
        r = rules[mid]
        idx = len(nodes)
        nodes.append({
            'type': 'branch',
            'channel': r.get('channel', 0),
            'threshold': r['threshold'],
            'label': r.get('label', ''),
            'left': None,
            'right': None,
        })
        nodes[idx]['left'] = _build(lo, mid)
        nodes[idx]['right'] = _build(mid + 1, hi)
        return idx

    _build(0, len(rules) - 1)
    return nodes


def _default_rules():
    return [
        {'channel': 0, 'threshold': 200, 'label': 'COLD', 'value': ord('C')},
        {'channel': 0, 'threshold': 400, 'label': 'COOL', 'value': ord('O')},
        {'channel': 0, 'threshold': 600, 'label': 'WARM', 'value': ord('W')},
        {'channel': 0, 'threshold': 800, 'label': 'HOT', 'value': ord('H')},
    ]


# ADC channel → ATTiny13a ADMUX value and pin name
CHANNEL_MAP = {
    0: {'mux': 1, 'pin': 'PB2', 'adc': 'ADC1', 'phys': 'pin 7'},
    1: {'mux': 3, 'pin': 'PB3', 'adc': 'ADC3', 'phys': 'pin 2'},
    2: {'mux': 2, 'pin': 'PB4', 'adc': 'ADC2', 'phys': 'pin 3'},
    3: {'mux': 0, 'pin': 'PB5', 'adc': 'ADC0', 'phys': 'pin 1 (RESET)'},
}


def distill(rules=None, baud=9600, tx_pin='B,0',
            led=True, loop_delay_ms=500, name='sensor_decision',
            median_filter=True, framed=True, goedel=True,
            bytebeat=False, bytebeat_map=None):
    """Generate ATTiny13a C code: multi-channel decision tree + picoUART + Gödel + bytebeat.

    Parameters:
        rules: list of {'channel': int, 'threshold': int, 'label': str, 'value': int}
        baud: UART baud rate (default 9600)
        tx_pin: picoUART TX pin (default 'B,0' = PB0)
        led: include status LED on PB1 (ignored if bytebeat=True, PB1 becomes audio)
        loop_delay_ms: delay between readings
        name: firmware name (appears in metadata)
        median_filter: take median-of-3 readings per channel
        framed: send framed packets [0xAA, len, ...data..., XOR checksum]
        goedel: include Gödel self-reference (flash CRC + tree self-description)
        bytebeat: enable bytebeat audio output on PB1 (OC0B PWM)
        bytebeat_map: dict mapping decision value → formula index (0-7).
                      If None, auto-assigns formulas round-robin to leaf values.
    """
    if rules is None:
        rules = _default_rules()

    nodes = build_tree_nodes(rules)
    channels_used = sorted({r.get('channel', 0) for r in rules})
    n_channels = len(channels_used)
    n_nodes = len(nodes)
    uses_reset_pin = 3 in channels_used

    # Build Gödel metadata block
    goedel_sig = hashlib.md5(
        f'{name}:{n_nodes}:{n_channels}:{int(time.time())}'.encode()
    ).hexdigest()[:8]

    # Tree data for C
    tree_entries = []
    for n in nodes:
        if n['type'] == 'leaf':
            tree_entries.append(
                f'    {{0xFF, 0x{n["value"]:02X}, 0, 0, 0}},'
                f'  // leaf: {n["label"]} → 0x{n["value"]:02X}'
                f' ({chr(n["value"]) if 32 <= n["value"] < 127 else "?"})')
        else:
            mux = CHANNEL_MAP[n['channel']]['mux']
            tree_entries.append(
                f'    {{{mux}, '
                f'0x{(n["threshold"] >> 8) & 0xFF:02X}, '
                f'0x{n["threshold"] & 0xFF:02X}, '
                f'{n["left"]}, {n["right"]}}},'
                f'  // ch{n["channel"]} < {n["threshold"]} ? [{n["left"]}] : [{n["right"]}]'
                f' ({n["label"]})')

    tree_data = '\n'.join(tree_entries)

    # Rule summary
    rule_lines = []
    for r in sorted(rules, key=lambda r: (r.get('channel', 0), r['threshold'])):
        ch = r.get('channel', 0)
        ci = CHANNEL_MAP.get(ch, CHANNEL_MAP[0])
        val_char = chr(r['value']) if 32 <= r['value'] < 127 else '?'
        rule_lines.append(
            f'//   ch{ch} ({ci["adc"]}) < {r["threshold"]:4d}'
            f' → 0x{r["value"]:02X} ("{val_char}")  {r.get("label", "")}')
    rule_summary = '\n'.join(rule_lines)

    # When bytebeat is on, PB1 is OC0B (PWM audio), not a simple LED toggle
    if bytebeat:
        led = False  # PB1 is audio now

    # Pin assignment
    pin_lines = []
    for ch in channels_used:
        ci = CHANNEL_MAP[ch]
        pin_lines.append(f'//   {ci["pin"]} ({ci["adc"]}, {ci["phys"]}): '
                         f'analog input channel {ch}')
    pin_lines.append('//   PB0 (pin 5): picoUART TX → ESP RX')
    if bytebeat:
        pin_lines.append('//   PB1 (OC0B, pin 6): bytebeat PWM audio output')
    elif led:
        pin_lines.append('//   PB1 (pin 6): status LED')
    pin_summary = '\n'.join(pin_lines)

    # ADMUX values for used channels
    mux_values = [CHANNEL_MAP[ch]['mux'] for ch in channels_used]
    mux_arr = ', '.join(str(m) for m in mux_values)

    led_ddr = ' | (1 << PB1)' if (led or bytebeat) else ''
    led_toggle = '\n        PORTB ^= (1 << PB1);' if led else ''

    # Build bytebeat formula → leaf value mapping
    bb_map = {}
    if bytebeat:
        leaf_values = sorted({n['value'] for n in nodes if n['type'] == 'leaf'})
        if bytebeat_map:
            bb_map = {v: bytebeat_map.get(v, 0) for v in leaf_values}
        else:
            # Auto-assign: cycle through formulas 1-7 (skip 0=silence)
            for i, v in enumerate(leaf_values):
                bb_map[v] = (i % 7) + 1

    # Estimate flash
    base = 175
    tree_bytes = n_nodes * 5
    median_bytes = 50 if median_filter else 0
    frame_bytes = 30 if framed else 0
    goedel_bytes = 400 if goedel else 0
    bytebeat_bytes = 120 if bytebeat else 0
    est_total = (base + tree_bytes + median_bytes + frame_bytes
                 + goedel_bytes + bytebeat_bytes)
    est_pct = round(est_total / 1024 * 100)

    # Gödel metadata: packed description of self
    # Format: name (null-terminated), n_channels, n_nodes, channel_map,
    # then for each node: type|channel, threshold_hi, threshold_lo, left, right
    meta_name = name[:15]  # cap at 15 chars + null
    meta_bytes = []
    for c in meta_name:
        meta_bytes.append(f'0x{ord(c):02X}')
    meta_bytes.append('0x00')  # null terminator
    meta_bytes.append(f'0x{n_channels:02X}')
    meta_bytes.append(f'0x{n_nodes:02X}')
    for ch in channels_used:
        meta_bytes.append(f'0x{CHANNEL_MAP[ch]["mux"]:02X}')
    # Encode tree nodes into metadata
    for n in nodes:
        if n['type'] == 'leaf':
            meta_bytes.append('0xFF')
            meta_bytes.append(f'0x{n["value"]:02X}')
            meta_bytes.extend(['0x00', '0x00', '0x00'])
        else:
            mux = CHANNEL_MAP[n['channel']]['mux']
            meta_bytes.append(f'0x{mux:02X}')
            meta_bytes.append(f'0x{(n["threshold"] >> 8) & 0xFF:02X}')
            meta_bytes.append(f'0x{n["threshold"] & 0xFF:02X}')
            meta_bytes.append(f'0x{n["left"]:02X}')
            meta_bytes.append(f'0x{n["right"]:02X}')
    meta_len = len(meta_bytes)
    # Wrap at 12 bytes per line
    meta_lines = []
    for i in range(0, len(meta_bytes), 12):
        meta_lines.append('    ' + ', '.join(meta_bytes[i:i+12]) + ',')
    meta_block = '\n'.join(meta_lines)

    # ── Build C code ──────────────────────────────────────────────

    median_fn = '''
// Median-of-3: sort three readings, return middle value
static uint16_t median3(uint16_t a, uint16_t b, uint16_t c) {
    if (a > b) { uint16_t t = a; a = b; b = t; }
    if (b > c) { uint16_t t = b; b = c; c = t; }
    if (a > b) { uint16_t t = a; a = b; b = t; }
    return b;
}
''' if median_filter else ''

    read_call = '''    readings[i] = median3(read_adc(ch), read_adc(ch), read_adc(ch));''' \
        if median_filter else '''    readings[i] = read_adc(ch);'''

    if framed:
        tx_section = f'''
        // Framed packet: [0xAA, length, ch0_result, ..., XOR checksum]
        uint8_t pkt[{n_channels + 3}];
        pkt[0] = 0xAA;               // sync byte
        pkt[1] = {n_channels};       // payload length
        uint8_t xor = 0;
        for (uint8_t i = 0; i < {n_channels}; i++) {{
            pkt[2 + i] = results[i];
            xor ^= results[i];
        }}
        pkt[{n_channels + 2}] = xor; // checksum
        for (uint8_t i = 0; i < {n_channels + 3}; i++) putx(pkt[i]);'''
    else:
        tx_section = f'''
        // Transmit each channel's decision byte
        for (uint8_t i = 0; i < {n_channels}; i++) putx(results[i]);'''

    goedel_section = ''
    goedel_trigger = ''
    goedel_data = ''
    if goedel:
        goedel_data = f'''

// ── Gödel self-reference ──────────────────────────────────────
//
// The ATTiny carries a compressed description of its own decision
// logic in PROGMEM.  On a trigger condition (all ADC channels read
// below 10, i.e. all inputs grounded — the "who are you?" gesture),
// it transmits this self-description followed by a CRC-8 of its
// own flash contents.
//
// The ESP (or Velour) decodes the packet to reconstruct the tree
// without needing the source code.  The code IS its own documentation.
// This is not metaphorical self-reference — the chip reads its own
// program memory and describes what it finds.
//
// Metadata format:
//   name (null-terminated string)
//   n_channels (uint8_t)
//   n_nodes (uint8_t)
//   channel_mux_map (n_channels bytes)
//   node data (5 bytes each: type|mux, thr_hi, thr_lo, left, right)
//     leaf: 0xFF, value, 0, 0, 0
//     branch: mux, thr_hi, thr_lo, left_idx, right_idx

#define META_LEN {meta_len}
static const uint8_t GOEDEL_META[META_LEN] PROGMEM = {{
{meta_block}
}};

// CRC-8 of own flash — the ATTiny reads its entire program memory
// and computes a rolling hash.  This is genuine machine introspection:
// the code examines itself at the byte level.
static uint8_t flash_crc8(void) {{
    uint8_t crc = 0;
    for (uint16_t addr = 0; addr < FLASHEND + 1; addr++) {{
        uint8_t b = pgm_read_byte(addr);
        for (uint8_t bit = 0; bit < 8; bit++) {{
            uint8_t mix = (crc ^ b) & 0x01;
            crc >>= 1;
            if (mix) crc ^= 0x8C;  // CRC-8/MAXIM polynomial
            b >>= 1;
        }}
    }}
    return crc;
}}

// Transmit the Gödel self-description packet.
// Packet: [0xBB, META_LEN, ...metadata..., flash_crc, XOR_checksum]
static void describe_self(void) {{
    putx(0xBB);                       // Gödel packet sync (distinct from 0xAA data)
    putx(META_LEN);
    uint8_t xor = META_LEN;
    for (uint8_t i = 0; i < META_LEN; i++) {{
        uint8_t b = pgm_read_byte(&GOEDEL_META[i]);
        putx(b);
        xor ^= b;
    }}
    uint8_t crc = flash_crc8();
    putx(crc);                        // flash self-hash
    xor ^= crc;
    putx(xor);                        // checksum
}}'''

        goedel_trigger = f'''
        // Gödel trigger: all channels read below 10 (inputs grounded)
        // This is the "who are you?" gesture — ground all sensor inputs
        // and the ATTiny responds with its self-description.
        uint8_t all_low = 1;
        for (uint8_t i = 0; i < {n_channels}; i++) {{
            if (readings[i] >= 10) {{ all_low = 0; break; }}
        }}
        if (all_low) {{
            describe_self();
            _delay_ms(2000);  // debounce — don't re-trigger immediately
            continue;
        }}'''

    # ── Bytebeat code generation ─────────────────────────────────
    bytebeat_data = ''
    bytebeat_init = ''
    bytebeat_run = ''
    if bytebeat:
        # Generate the formula switch function
        cases = []
        formula_names = []
        for val, fidx in sorted(bb_map.items()):
            fname, fexpr = BYTEBEAT_FORMULAS[fidx]
            formula_names.append(f'0x{val:02X}→{fname}')
            cases.append(f'        case {val}: return (uint8_t)({fexpr});')
        cases_str = '\n'.join(cases)

        bytebeat_data = f'''

// ── Bytebeat audio engine ─────────────────────────────────────
//
// Bytebeat: evaluate t→f(t) at ~8kHz, output as PWM duty cycle on PB1.
// The decision tree result selects which formula plays — different
// sensor states produce different music.  The chip is singing about
// what it senses.
//
// Formula mapping:
//   {", ".join(formula_names)}
//
// PB1 is Timer0 OC0B output. The main loop interleaves bytebeat
// sample generation between decision cycles: run N samples of audio,
// then do one ADC read + tree walk + UART TX, repeat.  At 9.6MHz
// with a tight sample loop, we get roughly 8kHz sample rate.

static volatile uint32_t bb_t = 0;   // bytebeat time counter
static volatile uint8_t  bb_formula = 0;  // active formula (leaf value)

// Evaluate the active bytebeat formula for counter value t
static uint8_t bb_sample(uint32_t t) {{
    switch (bb_formula) {{
{cases_str}
        default: return 0;
    }}
}}'''

        bytebeat_init = '''
    // Timer0 fast PWM on OC0B (PB1) for bytebeat audio output
    // WGM = 0b011 (fast PWM), COM0B = 0b10 (non-inverting on OC0B)
    TCCR0A = (1 << COM0B1) | (1 << WGM01) | (1 << WGM00);
    TCCR0B = (1 << CS00);  // no prescaler — max PWM frequency
    OCR0B = 0;             // start silent
'''

        # Run N bytebeat samples between each decision cycle.
        # At ~12 cycles per sample at 9.6MHz, 256 samples ≈ 3.2ms.
        # loop_delay_ms / 3.2 ≈ number of sample batches per decision.
        n_samples = max(64, min(512, loop_delay_ms * 2))
        bytebeat_run = f'''
        // Bytebeat: generate {n_samples} audio samples between decision cycles.
        // Each sample: evaluate formula, write to PWM, increment t.
        bb_formula = results[0];  // first channel's decision drives the music
        for (uint16_t s = 0; s < {n_samples}; s++) {{
            OCR0B = bb_sample(bb_t);
            bb_t++;
        }}'''

    reset_warning = ''
    if uses_reset_pin:
        reset_warning = '''
// WARNING: Channel 3 uses PB5 (ADC0), which is the RESET pin.
// You MUST burn the RSTDISBL fuse to use it as ADC input:
//   avrdude -p t13 -c usbasp -U hfuse:w:0xFE:m
// After this, you need a high-voltage programmer (12V on RESET) to reflash.
'''

    bb_header = ''
    if bytebeat:
        bb_header = (
            f'// Bytebeat audio on PB1 (OC0B PWM) — the decision selects the song.\n'
            f'// Formula map: {", ".join(f"0x{v:02X}={BYTEBEAT_FORMULAS[i][0]}" for v, i in sorted(bb_map.items()))}\n'
        )

    return f'''// CONDENSER: ATTiny13a multi-channel decision tree + picoUART{" + Gödel" if goedel else ""}{" + bytebeat" if bytebeat else ""}
// Generated by Velour Condenser — {name}
// Gödel signature: {goedel_sig}
//
// {n_channels}-channel ADC, {n_nodes}-node decision tree, framed UART packets.
{"// The chip senses, decides, reports via UART, and sings about it." if bytebeat else "// The chip carries a description of its own logic and can transmit it"}
{"// Each sensor state triggers a different bytebeat formula on the PWM pin." if bytebeat else "// on request — genuine machine self-reference in under 1KB."}
{bb_header}//
//
// Decision rules:
{rule_summary}
//
// Est. flash: ~{est_total} bytes / 1024 ({est_pct}%)
// picoUART: https://github.com/nerdralph/picoUART
//
// Pin assignment:
{pin_summary}
//
// Build:
//   avr-gcc -mmcu=attiny13a -Os -DF_CPU=9600000UL \\
//     -DPU_TX={tx_pin} -DPU_BAUD_RATE={baud} \\
//     -I./picoUART -o {name}.elf {name}.c
//   avr-objcopy -O ihex {name}.elf {name}.hex
//   avrdude -p t13 -c usbasp -U flash:w:{name}.hex
{reset_warning}
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>
#include <picoUART.h>

// ── Decision tree ─────────────────────────────────────────────
// Node layout (5 bytes): channel/mux, threshold_hi, threshold_lo, left, right
// Leaf marker: channel == 0xFF, left field == result value

typedef struct {{
    uint8_t  channel;    // ADMUX value, or 0xFF for leaf
    uint8_t  thr_hi;     // threshold high byte (or result value for leaf)
    uint8_t  thr_lo;     // threshold low byte
    uint8_t  left;       // left child index
    uint8_t  right;      // right child index
}} Node;

static const Node TREE[{n_nodes}] PROGMEM = {{
{tree_data}
}};

// Walk the tree with per-channel ADC readings
static uint8_t decide(const uint16_t *readings, const uint8_t *mux_map, uint8_t n_ch) {{
    uint8_t idx = 0;
    for (;;) {{
        uint8_t ch = pgm_read_byte(&TREE[idx].channel);
        if (ch == 0xFF) {{
            return pgm_read_byte(&TREE[idx].thr_hi);  // leaf value
        }}
        uint16_t thr = ((uint16_t)pgm_read_byte(&TREE[idx].thr_hi) << 8)
                      | pgm_read_byte(&TREE[idx].thr_lo);
        // Find which readings[] index corresponds to this ADMUX channel
        uint16_t val = 0;
        for (uint8_t i = 0; i < n_ch; i++) {{
            if (mux_map[i] == ch) {{ val = readings[i]; break; }}
        }}
        uint8_t left  = pgm_read_byte(&TREE[idx].left);
        uint8_t right = pgm_read_byte(&TREE[idx].right);
        idx = (val < thr) ? left : right;
    }}
}}

// ── ADC ───────────────────────────────────────────────────────

static uint16_t read_adc(uint8_t mux) {{
    ADMUX = mux;
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC));
    return ADC;
}}
{median_fn}
// ── Channel map ───────────────────────────────────────────────

#define N_CHANNELS {n_channels}
static const uint8_t MUX_MAP[N_CHANNELS] PROGMEM = {{ {mux_arr} }};
{goedel_data}
{bytebeat_data}

// ── Main ──────────────────────────────────────────────────────

int main(void) {{
    DDRB = (1 << PB0){led_ddr};
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1);
{bytebeat_init}
    // Copy channel map to SRAM (tiny — {n_channels} bytes)
    uint8_t mux[N_CHANNELS];
    for (uint8_t i = 0; i < N_CHANNELS; i++)
        mux[i] = pgm_read_byte(&MUX_MAP[i]);
{"" if not goedel else '''
    // Boot self-announcement: transmit identity on first power-up
    describe_self();
'''}
    for (;;) {{
        // Read all channels
        uint16_t readings[N_CHANNELS];
        for (uint8_t i = 0; i < N_CHANNELS; i++) {{
            uint8_t ch = mux[i];
{read_call}
        }}
{goedel_trigger}
        // Run decision tree for each channel and collect results
        uint8_t results[N_CHANNELS];
        for (uint8_t i = 0; i < N_CHANNELS; i++) {{
            // For multi-channel trees the walker sees all readings;
            // for single-channel backward compat, it still works.
            results[i] = decide(readings, mux, N_CHANNELS);
        }}
{tx_section}
{bytebeat_run}
{led_toggle}

        {"" if bytebeat else f"_delay_ms({loop_delay_ms});"}
    }}
    return 0;
}}
'''

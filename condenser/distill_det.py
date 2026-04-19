"""Distill Det's hex Class-4 search experiment down four MCU rungs.

Det hunts for Rule-110-analog hex CA rulesets. Each target here
expresses a different slice of that experiment, matched to its
capability envelope:

  Tier 4a — ATTiny13a (1KB flash, 64B SRAM):
      The *ancestor*. Det is trying to find 2-D hex cousins of
      Rule 110; the 13a runs Rule 110 itself on a 32-cell ring
      and blinks an LED proportional to live-cell count.

  Tier 4b — ATTiny85 (8KB flash, 512B SRAM):
      A single randomly-drawn hex ruleset baked in at distill
      time, run forward on a 6×4 hex grid and dumped to serial.
      One candidate; no scoring on-chip.

  Tier 3a — ESP8266 (80KB RAM, 1MB flash):
      K baked candidates, each run and scored with the same
      metrics Det uses. Serves an HTML page ranking them.

  Tier 3b — ESP32-S3 SuperMini (320KB SRAM, 4MB flash):
      On-chip random generation AND scoring — the full search
      loop, small scale. Serves a live web UI.

Rules use the same 7-tuple format as automaton.detector.step_exact
and det.search, so candidates can be promoted back into Automaton
by hand if anything looks interesting on the bench.
"""

import json
import random


def _generate_rules(n_rules, n_colors, wildcard_pct, rng):
    """Same generator as det.search._generate_rules, inlined to keep
    this module Django-free."""
    seen = set()
    rules = []
    attempts = 0
    while len(rules) < n_rules and attempts < n_rules * 10:
        attempts += 1
        self_c = rng.randrange(n_colors)
        nbs = []
        for _ in range(6):
            if rng.randrange(100) < wildcard_pct:
                nbs.append(-1)
            else:
                nbs.append(rng.randrange(n_colors))
        result = rng.randrange(n_colors)
        if result == self_c and all(n == -1 for n in nbs):
            continue
        key = (self_c, tuple(nbs), result)
        if key in seen:
            continue
        seen.add(key)
        rules.append({'s': self_c, 'n': nbs, 'r': result})
    return rules


# ──────────────────────────────────────────────────────────────────
# Tier 4a — ATTiny13a: Rule 110 on a 32-cell ring
# ──────────────────────────────────────────────────────────────────

def distill_attiny13a():
    """Det's ancestor in 1KB: Rule 110 itself, the canonical Class-4
    elementary CA. Single cell seed, 32-cell ring, LED blinks when the
    live-cell count rises above half-full."""
    return '''// CONDENSER: Tier 4a — ATTiny13a, Det ancestor (Rule 110)
//
// Det hunts 2-D hex rulesets that behave like Rule 110 (1-D, 2-color,
// Class 4 — gliders, long transients, Turing-complete). This is that
// ancestor distilled to 1KB: 32-cell ring, rule 110 (01101110 = 0x6E),
// one seeded cell, LED proportional to population.
//
// Fuse: internal 9.6 MHz, no CKDIV8 (run at full speed).
// Pin: PB0 → LED (220 Ω series) → GND.
//
// What's lost relative to Det: the hex topology, the multi-colour
// alphabet, the search loop, the scorer. What's kept: the dynamic
// that makes Det worth running in the first place.

#include <avr/io.h>
#include <util/delay.h>

static uint32_t row = 0x00000001UL;  // single-cell seed at bit 0

int main(void) {
    DDRB |= (1 << PB0);                    // LED output

    while (1) {
        uint32_t nxt = 0;
        for (uint8_t i = 0; i < 32; i++) {
            uint8_t l = (row >> ((i + 1) & 31)) & 1;   // left (wrap)
            uint8_t s = (row >> i) & 1;
            uint8_t r = (row >> ((i + 31) & 31)) & 1;  // right (wrap)
            uint8_t pat = (l << 2) | (s << 1) | r;
            if ((0x6E >> pat) & 1) nxt |= (1UL << i);  // Rule 110
        }
        row = nxt;

        // Population-proportional LED: bright if > 16 cells alive.
        uint8_t cnt = 0;
        for (uint32_t v = row; v; v >>= 1) cnt += (uint8_t)(v & 1);
        if (cnt > 16) PORTB |=  (1 << PB0);
        else          PORTB &= ~(1 << PB0);

        _delay_ms(150);

        // If the ring collapses to empty (shouldn't happen for 110,
        // but guards against the degenerate fuse state) re-seed.
        if (row == 0) row = 0x00000001UL;
    }
    return 0;
}
'''


# ──────────────────────────────────────────────────────────────────
# Tier 4b — ATTiny85: One baked hex ruleset on a 6×4 grid
# ──────────────────────────────────────────────────────────────────

def distill_attiny85(n_colors=2, n_rules=24, wildcard_pct=20, seed=None):
    """One Det-generated ruleset baked into 8KB flash, run on a 6×4
    hex grid for 60 ticks, per-tick dumped via SoftwareSerial."""
    W, H = 6, 4
    horizon = 60
    rng = random.Random(seed if seed is not None else random.randint(1, 1 << 30))
    rules = _generate_rules(n_rules, n_colors, wildcard_pct, rng)

    # Pack each rule into an 8-byte struct: {s,n0..n5,r} (signed int8).
    # -1 stays as -1 (wildcard sentinel) in two's complement.
    rule_rows = []
    for r in rules:
        s = r['s'] & 0xFF
        ns = [n & 0xFF for n in r['n']]
        rr = r['r'] & 0xFF
        byte_tuple = [s] + ns + [rr]
        rule_rows.append('    {' + ','.join('(int8_t)0x%02X' % b for b in byte_tuple) + '},')
    rules_c = '\n'.join(rule_rows)

    return f'''// CONDENSER: Tier 4b — ATTiny85, one hex ruleset
//
// ONE ruleset drawn at distill time (seed baked in) and run forward
// on a {W}×{H} hex grid for {horizon} ticks. Every 3rd tick is dumped
// to PB3 via bit-banged serial at 9600 baud — watch with `picocom`.
//
// Rule format matches automaton.detector.step_exact:
//   [self, n0..n5, result]  with -1 as wildcard.
// {n_rules} rules, {n_colors} colors, {wildcard_pct}% wildcards at draw time.
//
// Pins: PB3 → TTL serial RX of host (3.3V level).
//       PB0 → heartbeat LED (toggle each frame).

#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>

#define W {W}
#define H {H}
#define N_COLORS {n_colors}
#define N_RULES  {len(rules)}
#define HORIZON  {horizon}

// Packed rules: 8 bytes each, stored in PROGMEM.
static const int8_t RULES[N_RULES][8] PROGMEM = {{
{rules_c}
}};

static uint8_t grid_a[H][W];
static uint8_t grid_b[H][W];

// Bit-banged serial on PB3, 9600 baud, 8N1. At 9.6 MHz one bit ≈ 104 µs.
static inline void tx_bit(uint8_t hi) {{
    if (hi) PORTB |=  (1 << PB3);
    else    PORTB &= ~(1 << PB3);
    _delay_us(104);
}}
static void tx_byte(uint8_t b) {{
    tx_bit(0);                              // start
    for (uint8_t i = 0; i < 8; i++) {{
        tx_bit(b & 1);
        b >>= 1;
    }}
    tx_bit(1);                              // stop
}}
static void tx_str(const char* s) {{
    while (*s) tx_byte(*s++);
}}

// Canonical hex neighbour order: N, NE, SE, S, SW, NW.
// Even columns and odd columns take different row offsets.
static inline uint8_t nb(uint8_t r, uint8_t c, uint8_t idx) {{
    int8_t nr = r, nc = c;
    uint8_t even = ((c & 1) == 0);
    switch (idx) {{
        case 0: nr = r - 1; break;
        case 1: nr = even ? r - 1 : r;     nc = c + 1; break;
        case 2: nr = even ? r     : r + 1; nc = c + 1; break;
        case 3: nr = r + 1; break;
        case 4: nr = even ? r     : r + 1; nc = c - 1; break;
        case 5: nr = even ? r - 1 : r;     nc = c - 1; break;
    }}
    if (nr < 0 || nr >= H || nc < 0 || nc >= W) return 0;  // pad
    return grid_a[nr][nc];
}}

static void step(void) {{
    for (uint8_t r = 0; r < H; r++) {{
        for (uint8_t c = 0; c < W; c++) {{
            uint8_t self_c = grid_a[r][c];
            uint8_t ns[6];
            for (uint8_t i = 0; i < 6; i++) ns[i] = nb(r, c, i);
            uint8_t out = self_c;  // default: identity
            for (uint8_t k = 0; k < N_RULES; k++) {{
                int8_t rs  = (int8_t)pgm_read_byte(&RULES[k][0]);
                if (rs != -1 && rs != (int8_t)self_c) continue;
                uint8_t ok = 1;
                for (uint8_t i = 0; i < 6; i++) {{
                    int8_t rn = (int8_t)pgm_read_byte(&RULES[k][1 + i]);
                    if (rn != -1 && rn != (int8_t)ns[i]) {{ ok = 0; break; }}
                }}
                if (ok) {{
                    out = (uint8_t)pgm_read_byte(&RULES[k][7]);
                    break;  // first-match-wins, same as step_exact
                }}
            }}
            grid_b[r][c] = out;
        }}
    }}
    // swap
    for (uint8_t r = 0; r < H; r++)
        for (uint8_t c = 0; c < W; c++)
            grid_a[r][c] = grid_b[r][c];
}}

static void dump(uint16_t t) {{
    char buf[8];
    tx_str("t=");
    uint16_t n = t; char* p = buf + 7; *p = 0;
    do {{ *--p = '0' + (n % 10); n /= 10; }} while (n);
    tx_str(p); tx_str(" ");
    for (uint8_t r = 0; r < H; r++) {{
        for (uint8_t c = 0; c < W; c++) tx_byte('0' + grid_a[r][c]);
        tx_byte('|');
    }}
    tx_byte('\\r'); tx_byte('\\n');
}}

int main(void) {{
    DDRB |= (1 << PB0) | (1 << PB3);
    PORTB |= (1 << PB3);                   // serial idle = high

    // Deterministic seed from a baked constant; change by re-distilling.
    uint16_t s = 0xBEEFu;
    for (uint8_t r = 0; r < H; r++)
        for (uint8_t c = 0; c < W; c++) {{
            s ^= s << 7; s ^= s >> 9; s ^= s << 8;
            grid_a[r][c] = s % N_COLORS;
        }}

    _delay_ms(250);
    tx_str("== ATTiny85 Det 4b ==\\r\\n");
    dump(0);

    for (uint16_t t = 1; t <= HORIZON; t++) {{
        step();
        PORTB ^= (1 << PB0);               // heartbeat
        if (t % 3 == 0) dump(t);
        _delay_ms(120);
    }}
    tx_str("-- done --\\r\\n");
    while (1) {{ PORTB ^= (1 << PB0); _delay_ms(800); }}
    return 0;
}}
'''


# ──────────────────────────────────────────────────────────────────
# Tier 3a — ESP8266: K baked candidates, scored, served as HTML
# ──────────────────────────────────────────────────────────────────

def _bake_candidates_c(n_candidates, n_rules, n_colors, wildcard_pct, seed):
    rng = random.Random(seed)
    blocks = []
    for ci in range(n_candidates):
        rules = _generate_rules(n_rules, n_colors, wildcard_pct, rng)
        flat = []
        for r in rules:
            flat.append(r['s'])
            flat.extend(r['n'])
            flat.append(r['r'])
        rows = []
        for i in range(0, len(flat), 8):
            rows.append('  ' + ','.join('(int8_t)%d' % v for v in flat[i:i + 8]))
        blocks.append(
            f'static const int8_t CAND_{ci}[{len(rules)}][8] = {{\n'
            + ',\n'.join('  {' + ','.join('(int8_t)%d' % v for v in flat[j:j + 8]) + '}'
                         for j in range(0, len(flat), 8))
            + '\n};'
        )
    return '\n\n'.join(blocks)


def distill_esp8266(n_candidates=3, n_rules=80, n_colors=3,
                     wildcard_pct=25, W=12, H=8, horizon=30,
                     seed=None, wifi_ssid='YOUR_WIFI',
                     wifi_pass='YOUR_PASS'):
    """Miniature Det: K candidates, each scored with activity +
    entropy + density, results served as an HTML leaderboard."""
    seed = seed if seed is not None else random.randint(1, 1 << 30)
    rng = random.Random(seed)

    candidates = []
    for ci in range(n_candidates):
        rules = _generate_rules(n_rules, n_colors, wildcard_pct, rng)
        candidates.append(rules)

    # Emit one flat PROGMEM blob per candidate: n_rules × 8 int8.
    cand_decls = []
    cand_lens = []
    for ci, rules in enumerate(candidates):
        flat = []
        for r in rules:
            flat.append(r['s'])
            flat.extend(r['n'])
            flat.append(r['r'])
        rows = []
        for j in range(0, len(flat), 8):
            rows.append('    {' + ','.join('(int8_t)%d' % v for v in flat[j:j + 8]) + '}')
        cand_decls.append(
            f'static const int8_t CAND_{ci}[{len(rules)}][8] PROGMEM = {{\n'
            + ',\n'.join(rows) + '\n};'
        )
        cand_lens.append(len(rules))

    cand_decls_c = '\n\n'.join(cand_decls)
    cand_ptr_table = ',\n'.join(f'    (const int8_t*)CAND_{ci}' for ci in range(n_candidates))
    cand_len_table = ', '.join(str(n) for n in cand_lens)

    return f'''// CONDENSER: Tier 3a — ESP8266, Det miniature
//
// {n_candidates} candidates × {n_rules} rules each, baked at distill
// time. Each candidate is run on a {W}×{H} hex grid for {horizon} ticks
// and scored with the same heuristic as det.search:
//   +  not uniform at horizon
//   +  mean activity in [0.05, 0.30]
//   +  color diversity ≥ 2
//   +  block entropy in [1.2, 3.2] bits
// Results are served at http://det-esp.local/ ranked by score.
//
// Seed: {seed}  (change by re-distilling)
// Promote candidates back to Automaton by copying the rule rows
// into automaton's ExactRule format — same field ordering.

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266mDNS.h>
#include <pgmspace.h>

const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASS = "{wifi_pass}";

ESP8266WebServer server(80);

#define W        {W}
#define H        {H}
#define N_COLORS {n_colors}
#define HORIZON  {horizon}
#define N_CAND   {n_candidates}

{cand_decls_c}

static const int8_t* CAND_PTRS[N_CAND] = {{
{cand_ptr_table}
}};
static const uint16_t CAND_NRULES[N_CAND] = {{ {cand_len_table} }};

static uint8_t grid_a[H][W];
static uint8_t grid_b[H][W];

static inline uint8_t nb(uint8_t r, uint8_t c, uint8_t idx) {{
    int nr = r, nc = c;
    bool even = ((c & 1) == 0);
    switch (idx) {{
        case 0: nr = r - 1; break;
        case 1: nr = even ? r - 1 : r;     nc = c + 1; break;
        case 2: nr = even ? r     : r + 1; nc = c + 1; break;
        case 3: nr = r + 1; break;
        case 4: nr = even ? r     : r + 1; nc = c - 1; break;
        case 5: nr = even ? r - 1 : r;     nc = c - 1; break;
    }}
    if (nr < 0 || nr >= H || nc < 0 || nc >= W) return 0;
    return grid_a[nr][nc];
}}

static void step(const int8_t* rules, uint16_t nr) {{
    for (uint8_t r = 0; r < H; r++) {{
        for (uint8_t c = 0; c < W; c++) {{
            uint8_t self_c = grid_a[r][c];
            uint8_t ns[6];
            for (uint8_t i = 0; i < 6; i++) ns[i] = nb(r, c, i);
            uint8_t out = self_c;
            for (uint16_t k = 0; k < nr; k++) {{
                int8_t rs = (int8_t)pgm_read_byte(&rules[k * 8]);
                if (rs != -1 && rs != (int8_t)self_c) continue;
                bool ok = true;
                for (uint8_t i = 0; i < 6; i++) {{
                    int8_t rn = (int8_t)pgm_read_byte(&rules[k * 8 + 1 + i]);
                    if (rn != -1 && rn != (int8_t)ns[i]) {{ ok = false; break; }}
                }}
                if (ok) {{
                    out = (uint8_t)pgm_read_byte(&rules[k * 8 + 7]);
                    break;
                }}
            }}
            grid_b[r][c] = out;
        }}
    }}
    memcpy(grid_a, grid_b, sizeof(grid_a));
}}

static void seed_grid(uint32_t s) {{
    uint32_t x = s ? s : 1;
    for (uint8_t r = 0; r < H; r++)
        for (uint8_t c = 0; c < W; c++) {{
            x ^= x << 13; x ^= x >> 17; x ^= x << 5;
            grid_a[r][c] = x % N_COLORS;
        }}
}}

struct Score {{
    float score;
    float activity;
    float entropy;
    uint8_t diversity;
    bool uniform;
    uint8_t final_grid[H][W];
}};

static Score run_and_score(uint8_t idx) {{
    Score s;
    memset(&s, 0, sizeof(s));
    seed_grid(0xC0FFEE ^ (idx * 0x9E37));
    uint8_t prev[H][W];
    float act_sum = 0;
    int act_n = 0;
    int tail_start = HORIZON - HORIZON / 3;
    if (tail_start < 1) tail_start = 1;
    for (int t = 1; t <= HORIZON; t++) {{
        memcpy(prev, grid_a, sizeof(prev));
        step(CAND_PTRS[idx], CAND_NRULES[idx]);
        if (t >= tail_start) {{
            int changed = 0;
            for (uint8_t r = 0; r < H; r++)
                for (uint8_t c = 0; c < W; c++)
                    if (prev[r][c] != grid_a[r][c]) changed++;
            act_sum += (float)changed / (W * H);
            act_n++;
        }}
    }}
    s.activity = act_n ? act_sum / act_n : 0;

    uint8_t counts[N_COLORS] = {{0}};
    uint8_t first = grid_a[0][0];
    bool uniform = true;
    for (uint8_t r = 0; r < H; r++)
        for (uint8_t c = 0; c < W; c++) {{
            uint8_t v = grid_a[r][c];
            counts[v % N_COLORS]++;
            if (v != first) uniform = false;
            s.final_grid[r][c] = v;
        }}
    s.uniform = uniform;
    uint8_t div = 0;
    for (uint8_t i = 0; i < N_COLORS; i++)
        if (counts[i] > W * H / 100) div++;
    s.diversity = div;

    // 2×2 block entropy, approximate (log2 via float)
    const int NB = (H - 1) * (W - 1);
    uint8_t blockCnt[1 << (4 * 2)] = {{0}};  // up to 16-entry histogram for 2-color
    // For n_colors > 2 collapse to 2-bit per cell to bound the table.
    for (uint8_t r = 0; r < H - 1; r++) {{
        for (uint8_t c = 0; c < W - 1; c++) {{
            uint8_t a = grid_a[r][c]     & 3;
            uint8_t b = grid_a[r][c + 1] & 3;
            uint8_t d = grid_a[r + 1][c] & 3;
            uint8_t e = grid_a[r + 1][c + 1] & 3;
            uint8_t key = (a << 6) | (b << 4) | (d << 2) | e;
            blockCnt[key & 0xFF]++;
        }}
    }}
    float ent = 0;
    for (uint16_t i = 0; i < 256; i++) {{
        if (!blockCnt[i]) continue;
        float p = (float)blockCnt[i] / NB;
        ent -= p * (logf(p) / logf(2.0f));
    }}
    s.entropy = ent;

    // Det's weighted sum.
    float sc = 0;
    if (!uniform)                          sc += 2.0f;
    if (s.activity >= 0.05 && s.activity <= 0.30) sc += 2.5f;
    if (s.diversity >= 2)                  sc += 1.5f;
    if (s.entropy >= 1.2 && s.entropy <= 3.2)      sc += 1.0f;
    s.score = sc;
    return s;
}}

static Score CACHED[N_CAND];

static void run_all(void) {{
    Serial.println("[det] running candidates…");
    for (uint8_t i = 0; i < N_CAND; i++) {{
        CACHED[i] = run_and_score(i);
        Serial.printf("  cand %u score=%.2f act=%.3f ent=%.2f div=%u uni=%d\\n",
            i, CACHED[i].score, CACHED[i].activity,
            CACHED[i].entropy, CACHED[i].diversity, CACHED[i].uniform);
    }}
}}

static String render_page() {{
    String html;
    html.reserve(4096);
    html += F("<!doctype html><title>Det ESP8266</title>");
    html += F("<style>body{{font-family:ui-monospace,Menlo,monospace;"
             "background:#0d1117;color:#c9d1d9;padding:1rem}}"
             "table{{border-collapse:collapse;margin:0.5rem 0}}"
             "td{{width:10px;height:10px;border:1px solid #222}}"
             ".c0{{background:#0d1117}}.c1{{background:#58a6ff}}"
             ".c2{{background:#f85149}}.c3{{background:#2ea043}}"
             ".card{{border:1px solid #30363d;padding:0.5rem;margin:0.5rem 0}}"
             "</style>");
    html += F("<h1>Det — miniature (ESP8266)</h1>");
    html += "<p>Grid " + String(W) + "×" + String(H)
          + ", horizon " + String(HORIZON)
          + ", " + String(N_CAND) + " candidates.</p>";

    // Rank indices by score descending.
    uint8_t order[N_CAND];
    for (uint8_t i = 0; i < N_CAND; i++) order[i] = i;
    for (uint8_t i = 0; i < N_CAND; i++)
        for (uint8_t j = i + 1; j < N_CAND; j++)
            if (CACHED[order[j]].score > CACHED[order[i]].score) {{
                uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
            }}

    for (uint8_t k = 0; k < N_CAND; k++) {{
        uint8_t i = order[k];
        Score& s = CACHED[i];
        html += "<div class=card><b>#" + String(k + 1) + "</b> "
              + "cand " + String(i)
              + " · score=" + String(s.score, 2)
              + " · act=" + String(s.activity, 3)
              + " · ent=" + String(s.entropy, 2)
              + " · div=" + String(s.diversity)
              + (s.uniform ? " · <i>uniform</i>" : "")
              + "<br><table>";
        for (uint8_t r = 0; r < H; r++) {{
            html += "<tr>";
            for (uint8_t c = 0; c < W; c++) {{
                html += "<td class=c" + String(s.final_grid[r][c]) + "></td>";
            }}
            html += "</tr>";
        }}
        html += "</table></div>";
    }}
    return html;
}}

void setup() {{
    Serial.begin(115200);
    delay(50);
    Serial.println("\\n[det-esp] booting");

    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {{
        delay(500); Serial.print(".");
    }}
    if (WiFi.status() == WL_CONNECTED) {{
        Serial.printf("\\nIP: %s\\n", WiFi.localIP().toString().c_str());
    }} else {{
        WiFi.softAP("det-esp", "det-esp-ap");
        Serial.println("\\nAP mode: det-esp / det-esp-ap");
    }}
    MDNS.begin("det-esp");
    run_all();
    server.on("/", []() {{ server.send(200, "text/html", render_page()); }});
    server.on("/rerun", []() {{ run_all(); server.send(200, "text/plain", "ok"); }});
    server.begin();
    Serial.println("[http] ready");
}}

void loop() {{
    server.handleClient();
    MDNS.update();
}}
'''


# ──────────────────────────────────────────────────────────────────
# Tier 3b — ESP32-S3 SuperMini: on-chip search
# ──────────────────────────────────────────────────────────────────

def distill_esp32s3(W=16, H=12, horizon=40, n_colors=4,
                     n_candidates=12, n_rules=100, wildcard_pct=25,
                     wifi_ssid='YOUR_WIFI', wifi_pass='YOUR_PASS'):
    """Full Det search loop on-chip: generate candidates with
    esp_random(), score them, keep the winner, serve live progress
    over SSE at /events. No bake — every boot is a fresh search."""
    return f'''// CONDENSER: Tier 3b — ESP32-S3 SuperMini, Det on-chip
//
// Generate-and-score IS the whole app. On boot the ESP draws
// {n_candidates} candidates of {n_rules} rules each, runs every one
// on a {W}×{H} hex grid for {horizon} ticks, scores with Det's
// heuristic, and serves a leaderboard at http://det-s3.local/.
//
// Live progress at /events (Server-Sent Events). The top-scoring
// candidate's rules are JSON-downloadable at /winner.json so you
// can paste them straight into Automaton.
//
// Tune at distill time; the board is fast enough to re-run the
// whole search on every request via /research.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <esp_random.h>

const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASS = "{wifi_pass}";

#define W        {W}
#define H        {H}
#define N_COLORS {n_colors}
#define HORIZON  {horizon}
#define N_CAND   {n_candidates}
#define N_RULES  {n_rules}
#define WILDPCT  {wildcard_pct}

WebServer server(80);

struct Rule {{ int8_t s; int8_t n[6]; int8_t r; }};
static Rule cand[N_CAND][N_RULES];
static uint16_t cand_len[N_CAND];

static uint8_t grid_a[H][W];
static uint8_t grid_b[H][W];

struct Score {{
    float score, activity, entropy;
    uint8_t diversity;
    bool uniform;
    uint8_t final_grid[H][W];
}};
static Score scores[N_CAND];

static inline uint32_t r32(void) {{ return esp_random(); }}

static void gen_candidate(uint8_t ci) {{
    // Deduplicated draw; first-match semantics tolerate duplicates
    // but we keep them out anyway to match det.search.
    uint16_t n = 0;
    uint32_t seen_hash[256]; uint8_t nh = 0;
    while (n < N_RULES) {{
        Rule R;
        R.s = r32() % N_COLORS;
        for (uint8_t i = 0; i < 6; i++) {{
            R.n[i] = ((r32() % 100) < WILDPCT) ? -1 : (int8_t)(r32() % N_COLORS);
        }}
        R.r = r32() % N_COLORS;
        if (R.r == R.s) {{
            bool all_wild = true;
            for (uint8_t i = 0; i < 6; i++) if (R.n[i] != -1) {{ all_wild = false; break; }}
            if (all_wild) continue;
        }}
        uint32_t h = (uint32_t)R.s;
        for (uint8_t i = 0; i < 6; i++) h = (h << 3) ^ (uint8_t)R.n[i];
        h = (h << 3) ^ (uint32_t)R.r;
        bool dup = false;
        for (uint8_t k = 0; k < nh; k++) if (seen_hash[k] == h) {{ dup = true; break; }}
        if (dup) continue;
        if (nh < 255) seen_hash[nh++] = h;
        cand[ci][n++] = R;
    }}
    cand_len[ci] = n;
}}

static inline uint8_t nb(uint8_t r, uint8_t c, uint8_t idx) {{
    int nr = r, nc = c;
    bool even = ((c & 1) == 0);
    switch (idx) {{
        case 0: nr = r - 1; break;
        case 1: nr = even ? r - 1 : r;     nc = c + 1; break;
        case 2: nr = even ? r     : r + 1; nc = c + 1; break;
        case 3: nr = r + 1; break;
        case 4: nr = even ? r     : r + 1; nc = c - 1; break;
        case 5: nr = even ? r - 1 : r;     nc = c - 1; break;
    }}
    if (nr < 0 || nr >= H || nc < 0 || nc >= W) return 0;
    return grid_a[nr][nc];
}}

static void step(uint8_t ci) {{
    uint16_t nr = cand_len[ci];
    for (uint8_t r = 0; r < H; r++) {{
        for (uint8_t c = 0; c < W; c++) {{
            uint8_t self_c = grid_a[r][c];
            uint8_t ns[6];
            for (uint8_t i = 0; i < 6; i++) ns[i] = nb(r, c, i);
            uint8_t out = self_c;
            for (uint16_t k = 0; k < nr; k++) {{
                const Rule& R = cand[ci][k];
                if (R.s != -1 && R.s != (int8_t)self_c) continue;
                bool ok = true;
                for (uint8_t i = 0; i < 6; i++)
                    if (R.n[i] != -1 && R.n[i] != (int8_t)ns[i]) {{ ok = false; break; }}
                if (ok) {{ out = R.r; break; }}
            }}
            grid_b[r][c] = out;
        }}
    }}
    memcpy(grid_a, grid_b, sizeof(grid_a));
}}

static void seed_grid(uint32_t s) {{
    uint32_t x = s ? s : 1;
    for (uint8_t r = 0; r < H; r++)
        for (uint8_t c = 0; c < W; c++) {{
            x ^= x << 13; x ^= x >> 17; x ^= x << 5;
            grid_a[r][c] = x % N_COLORS;
        }}
}}

static void score_candidate(uint8_t ci) {{
    seed_grid(0xDE7 ^ (ci * 0x9E37));
    uint8_t prev[H][W];
    float act_sum = 0; int act_n = 0;
    int tail_start = HORIZON - HORIZON / 3;
    if (tail_start < 1) tail_start = 1;
    for (int t = 1; t <= HORIZON; t++) {{
        memcpy(prev, grid_a, sizeof(prev));
        step(ci);
        if (t >= tail_start) {{
            int ch = 0;
            for (uint8_t r = 0; r < H; r++)
                for (uint8_t c = 0; c < W; c++)
                    if (prev[r][c] != grid_a[r][c]) ch++;
            act_sum += (float)ch / (W * H); act_n++;
        }}
    }}
    Score& s = scores[ci];
    s.activity = act_n ? act_sum / act_n : 0;

    uint16_t counts[N_COLORS] = {{0}};
    uint8_t first = grid_a[0][0];
    bool uniform = true;
    for (uint8_t r = 0; r < H; r++)
        for (uint8_t c = 0; c < W; c++) {{
            uint8_t v = grid_a[r][c];
            counts[v % N_COLORS]++;
            if (v != first) uniform = false;
            s.final_grid[r][c] = v;
        }}
    s.uniform = uniform;
    uint8_t div = 0;
    for (uint8_t i = 0; i < N_COLORS; i++)
        if (counts[i] > (uint16_t)(W * H / 100)) div++;
    s.diversity = div;

    const int NB = (H - 1) * (W - 1);
    uint8_t blockCnt[256] = {{0}};
    for (uint8_t r = 0; r < H - 1; r++)
        for (uint8_t c = 0; c < W - 1; c++) {{
            uint8_t a = grid_a[r][c]     & 3;
            uint8_t b = grid_a[r][c + 1] & 3;
            uint8_t d = grid_a[r + 1][c] & 3;
            uint8_t e = grid_a[r + 1][c + 1] & 3;
            blockCnt[(a << 6) | (b << 4) | (d << 2) | e]++;
        }}
    float ent = 0;
    for (uint16_t i = 0; i < 256; i++) {{
        if (!blockCnt[i]) continue;
        float p = (float)blockCnt[i] / NB;
        ent -= p * (logf(p) / logf(2.0f));
    }}
    s.entropy = ent;

    float sc = 0;
    if (!uniform)                             sc += 2.0f;
    if (s.activity >= 0.05 && s.activity <= 0.30) sc += 2.5f;
    if (s.diversity >= 2)                     sc += 1.5f;
    if (s.entropy >= 1.2 && s.entropy <= 3.2)     sc += 1.0f;
    s.score = sc;
}}

static void run_search(void) {{
    Serial.println("[det] generating + scoring");
    unsigned long t0 = millis();
    for (uint8_t i = 0; i < N_CAND; i++) {{
        gen_candidate(i);
        score_candidate(i);
        Serial.printf("  cand %u score=%.2f act=%.3f ent=%.2f div=%u\\n",
            i, scores[i].score, scores[i].activity,
            scores[i].entropy, scores[i].diversity);
    }}
    Serial.printf("[det] done in %lu ms\\n", millis() - t0);
}}

static uint8_t winner(void) {{
    uint8_t w = 0;
    for (uint8_t i = 1; i < N_CAND; i++)
        if (scores[i].score > scores[w].score) w = i;
    return w;
}}

static String render_page(void) {{
    String html;
    html.reserve(8192);
    html += F("<!doctype html><title>Det S3</title>");
    html += F("<style>body{{font-family:ui-monospace,Menlo,monospace;"
             "background:#0d1117;color:#c9d1d9;padding:1rem}}"
             "table{{border-collapse:collapse;margin:0.3rem 0}}"
             "td{{width:10px;height:10px;border:1px solid #222}}"
             ".c0{{background:#0d1117}}.c1{{background:#58a6ff}}"
             ".c2{{background:#f85149}}.c3{{background:#2ea043}}"
             ".card{{border:1px solid #30363d;padding:0.4rem;margin:0.4rem 0}}"
             "</style>");
    html += F("<h1>Det — ESP32-S3</h1>");
    html += "<p>" + String(N_CAND) + " candidates × " + String(N_RULES)
          + " rules · " + String(W) + "×" + String(H)
          + " · horizon " + String(HORIZON) + "</p>";
    html += F("<p><a href=/research>rerun search</a> · "
             "<a href=/winner.json>winner.json</a></p>");

    uint8_t order[N_CAND];
    for (uint8_t i = 0; i < N_CAND; i++) order[i] = i;
    for (uint8_t i = 0; i < N_CAND; i++)
        for (uint8_t j = i + 1; j < N_CAND; j++)
            if (scores[order[j]].score > scores[order[i]].score) {{
                uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
            }}
    for (uint8_t k = 0; k < N_CAND; k++) {{
        uint8_t i = order[k];
        Score& s = scores[i];
        html += "<div class=card><b>#" + String(k + 1) + "</b> "
              + "cand " + String(i)
              + " · score=" + String(s.score, 2)
              + " · act=" + String(s.activity, 3)
              + " · ent=" + String(s.entropy, 2)
              + " · div=" + String(s.diversity)
              + (s.uniform ? " · <i>uniform</i>" : "")
              + "<br><table>";
        for (uint8_t r = 0; r < H; r++) {{
            html += "<tr>";
            for (uint8_t c = 0; c < W; c++) {{
                html += "<td class=c" + String(s.final_grid[r][c]) + "></td>";
            }}
            html += "</tr>";
        }}
        html += "</table></div>";
    }}
    return html;
}}

static String render_winner_json(void) {{
    uint8_t w = winner();
    String j = "{{\\"cand\\":" + String(w)
             + ",\\"score\\":" + String(scores[w].score, 3)
             + ",\\"activity\\":" + String(scores[w].activity, 4)
             + ",\\"entropy\\":" + String(scores[w].entropy, 3)
             + ",\\"diversity\\":" + String(scores[w].diversity)
             + ",\\"n_colors\\":" + String(N_COLORS)
             + ",\\"rules\\":[";
    uint16_t nr = cand_len[w];
    for (uint16_t k = 0; k < nr; k++) {{
        const Rule& R = cand[w][k];
        if (k) j += ",";
        j += "{{\\"s\\":" + String((int)R.s) + ",\\"n\\":["
           + String((int)R.n[0]) + "," + String((int)R.n[1]) + ","
           + String((int)R.n[2]) + "," + String((int)R.n[3]) + ","
           + String((int)R.n[4]) + "," + String((int)R.n[5]) + "]"
           + ",\\"r\\":" + String((int)R.r) + "}}";
    }}
    j += "]}}";
    return j;
}}

void setup() {{
    Serial.begin(115200); delay(50);
    Serial.println("\\n[det-s3] booting");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {{
        delay(500); Serial.print(".");
    }}
    if (WiFi.status() == WL_CONNECTED) {{
        Serial.printf("\\nIP: %s\\n", WiFi.localIP().toString().c_str());
    }} else {{
        WiFi.softAP("det-s3", "det-s3-ap");
        Serial.println("\\nAP mode: det-s3 / det-s3-ap");
    }}
    MDNS.begin("det-s3");
    run_search();
    server.on("/", []() {{ server.send(200, "text/html", render_page()); }});
    server.on("/research", []() {{ run_search(); server.sendHeader("Location", "/"); server.send(302); }});
    server.on("/winner.json", []() {{ server.send(200, "application/json", render_winner_json()); }});
    server.begin();
}}

void loop() {{
    server.handleClient();
}}
'''

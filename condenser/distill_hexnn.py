"""HexNN → ESP32-S3 SuperMini: full pipeline as one self-contained sketch.

The browser bench at /hexnn/ does the whole thing in JS — make a random
16,384-prototype genome, run the nearest-prototype step, hunt and refine
with a small GA, render hexes, export JSON. This distillation collapses
all of that onto an ESP32-S3 SuperMini: on boot the chip generates a
random genome, optionally runs a Hunt + Refine chain to find an
edge-of-chaos rule, then keeps the live grid stepping and serves it on
http://hexnn-s3.local/.

Why not 16,384 prototypes? An S3 has ~512 KB SRAM but Wi-Fi + the
WebServer eat ~150 KB. At 8 bytes/prototype a single 16K-entry genome
is 128 KB — one fits, but a population of them does not. Dropping to
``n_log2=12`` (4,096 prototypes) makes each genome 32 KB and lets POP=6
or POP=8 sit comfortably in BSS while still capturing the family-
resemblance behaviour the NN format is interesting for. The browser-
side N_LOG2=14 reference is preserved as a comment so the algorithm
stays recognisable.

CONDENSER markers describe what was lost vs. the JS reference and what
the next tier (ESP8266, ATtiny) would have to shed.
"""

from __future__ import annotations


def distill_hexnn_esp32s3(K=4, n_log2=11, W=16, H=16, horizon=80,
                          burn_in=20, pop_size=8, generations=30,
                          mutation_rate=0.0008, run_hunt=True,
                          tick_ms=200,
                          wifi_ssid='YOUR_WIFI', wifi_pass='YOUR_PASS'):
    """Emit a single .ino-style C++ source for ESP32-S3 SuperMini.

    The same source covers the whole HexNN pipeline:
      * mulberry32 PRNG (matches the browser bit-for-bit at the same seed)
      * random-genome generation — N = ``2 ** n_log2`` prototypes
      * bin construction (group prototypes by self-colour for fast lookup)
      * nearest-prototype hex step with squared-Euclidean distance, early
        out at d=0
      * change-rate score after burn-in, fitness = 4·r·(1-r) with r the
        quantize-to-K=4 transition rate
      * GA loop with elite preserved + crossover + mutation (output
        reassign + key drift ±1)
      * one-shot Hunt-then-Refine on boot if ``run_hunt`` is true
      * live runner — steps the grid every ``tick_ms`` ms in loop()
      * web UI: SVG-rendered hex grid, score panel, /winner.json export,
        /research re-run, /step single-step button

    All large arrays live in BSS so the Arduino loop-task stack stays
    untouched. Buffer sizing is checked at distill time and ``static_assert``
    in the emitted C++ guarantees the population fits.
    """
    n_entries = 1 << n_log2
    bytes_per_genome = n_entries * 8
    pop_bytes = bytes_per_genome * pop_size
    # Shared bin arena: one genome-sized block (N×7 nb bytes + N out bytes)
    # plus K × 4 bytes for per-self offset+count.
    bins_arena = n_entries * 7 + n_entries
    bins_index = K * 4
    grid_bytes = W * H * 2
    # 2 spare genomes: elite + scratch (used by mutate/crossover).
    next_pop_bss = bytes_per_genome * pop_size  # next-gen swap buffer
    total_bss = (pop_bytes + 2 * bytes_per_genome + bins_arena
                 + bins_index + grid_bytes + next_pop_bss)
    # Hard ceiling — S3 SuperMini has 512 KB SRAM but Wi-Fi + WebServer
    # + IDF stacks reserve ~150 KB; we keep 360 KB for app data.
    BSS_BUDGET = 360 * 1024
    if total_bss > BSS_BUDGET:
        raise ValueError(
            f'Estimated BSS {total_bss:,} bytes exceeds {BSS_BUDGET:,} '
            f'budget — drop n_log2 ({n_log2} → {n_log2 - 1}) or pop_size '
            f'({pop_size} → {pop_size // 2}).'
        )

    return f'''// CONDENSER: HexNN — full pipeline on ESP32-S3 SuperMini
//
// One sketch covers the whole /hexnn/ browser app:
//   1. Generate a random {n_entries}-prototype genome at K={K}.
//   2. {('Hunt + Refine' if run_hunt else 'Skip GA;')} keep the elite as live state.
//   3. Run the live grid forever, one step every {tick_ms} ms.
//   4. Serve hexnn-s3.local over Wi-Fi: SVG render, /winner.json export.
//
// Estimated BSS use: ~{total_bss // 1024} KB. Browser uses N_LOG2=14
// ({1 << 14} prototypes) by default; this build uses N_LOG2={n_log2} so
// a population of {pop_size} fits in on-chip SRAM without PSRAM.
//
// Build with Arduino-ESP32 (board: ESP32S3 Dev Module) or PlatformIO.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <esp_random.h>

// ── Parameters baked at distillation time ────────────────────────────
#define K            {K}
#define N_LOG2       {n_log2}
#define N_ENTRIES    ({1 << n_log2})        // 1 << N_LOG2
#define W            {W}
#define H            {H}
#define HORIZON      {horizon}
#define BURN_IN      {burn_in}
#define POP_SIZE     {pop_size}
#define GENERATIONS  {generations}
#define MUT_PCT_E6   {int(mutation_rate * 1_000_000)}  // mutation rate × 1e6
#define RUN_HUNT     {1 if run_hunt else 0}
#define TICK_MS      {tick_ms}

const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASS = "{wifi_pass}";

WebServer server(80);

// ── PRNG — mulberry32, byte-for-byte identical to the JS reference ───
//
// The browser bench uses the same generator seeded from the URL "seed"
// field, so the same seed produces the same genome here as in the page.
// That makes /winner.json from the device round-trip into the JS bench
// for visual comparison.
static uint32_t prng_state = 1u;

static inline void prng_seed(uint32_t s) {{ prng_state = s ? s : 1u; }}

static inline uint32_t prng_u32(void) {{
    prng_state = (prng_state + 0x6D2B79F5u);
    uint32_t t = prng_state;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return (t ^ (t >> 14));
}}

static inline float prng_unit(void) {{
    return (float)prng_u32() / 4294967296.0f;
}}

static inline uint8_t prng_mod(uint8_t m) {{
    return (uint8_t)((prng_u32() % m) & 0xFFu);
}}

// ── Genome layout ────────────────────────────────────────────────────
//
// Mirrors the JS Uint8Array packing: keys[i*7..i*7+6] = (self, n0..n5),
// outs[i] = output colour. {n_entries} entries × 8 bytes = {bytes_per_genome:,}
// bytes per genome.
typedef uint8_t u8;

struct Genome {{
    u8 keys[N_ENTRIES * 7];
    u8 outs[N_ENTRIES];
}};

static Genome pop[POP_SIZE];          // population for the GA
static Genome elite;                  // best-so-far / live rule
static Genome scratch;                // working buffer for crossover
static_assert(sizeof(pop) + 2 * sizeof(Genome) < 320u * 1024u,
              "BSS exceeds the 320 KB budget — re-distill with a "
              "smaller n_log2 or pop_size.");

// Bins indexed by self-colour share one arena the size of one genome
// (N x 7 bytes), plus per-self offset+count. This is what makes the
// data fit on-chip — naive allocation of Bin[K] with worst-case N each
// would cost K x as much.
static u8 bin_nbs[N_ENTRIES * 6];
static u8 bin_outs[N_ENTRIES];
struct BinIdx {{ uint16_t off; uint16_t count; }};
static BinIdx bin_idx[K];

static u8 grid_a[W * H];
static u8 grid_b[W * H];

// Next-generation buffer for the GA, kept in BSS so the Arduino loop
// task's 8 KB stack never sees a population-sized allocation.
static Genome ga_next[POP_SIZE];

// ── Genome generation ─────────────────────────────────────────────────

static void make_genome(Genome* g, uint32_t seed) {{
    prng_seed(seed);
    for (uint32_t i = 0; i < N_ENTRIES; i++) {{
        for (uint8_t j = 0; j < 7; j++) g->keys[i * 7 + j] = prng_mod(K);
        g->outs[i] = prng_mod(K);
    }}
}}

static void copy_genome(Genome* dst, const Genome* src) {{
    memcpy(dst->keys, src->keys, sizeof(dst->keys));
    memcpy(dst->outs, src->outs, sizeof(dst->outs));
}}

// ── Bin build + nearest-prototype lookup ─────────────────────────────
//
// Two passes through the genome: first counts per-self, computes prefix-
// sum offsets; second writes neighbours+outs into the shared arena in
// the order the lookup wants them. After build, bin_idx[s] tells us
// where bin s sits inside bin_nbs / bin_outs.

static void build_bins(const Genome* g) {{
    for (uint8_t s = 0; s < K; s++) bin_idx[s].count = 0;
    for (uint32_t i = 0; i < N_ENTRIES; i++) bin_idx[g->keys[i * 7]].count++;
    uint16_t off = 0;
    for (uint8_t s = 0; s < K; s++) {{
        bin_idx[s].off = off;
        off = (uint16_t)(off + bin_idx[s].count);
        bin_idx[s].count = 0;            // reused as cursor below
    }}
    for (uint32_t i = 0; i < N_ENTRIES; i++) {{
        uint8_t s = g->keys[i * 7];
        uint16_t k = (uint16_t)(bin_idx[s].off + bin_idx[s].count);
        for (uint8_t j = 0; j < 6; j++) bin_nbs[k * 6 + j] = g->keys[i * 7 + 1 + j];
        bin_outs[k] = g->outs[i];
        bin_idx[s].count++;
    }}
}}

static inline uint8_t lookup(uint8_t self_c,
                             uint8_t n0, uint8_t n1, uint8_t n2,
                             uint8_t n3, uint8_t n4, uint8_t n5) {{
    BinIdx ix = bin_idx[self_c];
    if (!ix.count) return self_c;
    uint16_t best = ix.off;
    int bestD = 0x7FFFFFFF;
    for (uint16_t k = 0; k < ix.count; k++) {{
        uint16_t o = (uint16_t)((ix.off + k) * 6);
        int d0 = (int)bin_nbs[o]   - (int)n0;
        int d1 = (int)bin_nbs[o+1] - (int)n1;
        int d2 = (int)bin_nbs[o+2] - (int)n2;
        int d3 = (int)bin_nbs[o+3] - (int)n3;
        int d4 = (int)bin_nbs[o+4] - (int)n4;
        int d5 = (int)bin_nbs[o+5] - (int)n5;
        int d = d0*d0 + d1*d1 + d2*d2 + d3*d3 + d4*d4 + d5*d5;
        if (d < bestD) {{
            bestD = d;
            best = (uint16_t)(ix.off + k);
            if (d == 0) break;        // exact match, no further search
        }}
    }}
    return bin_outs[best];
}}

// ── Hex step (flat-top offset columns; matches s3lab + browser) ──────

static void step_grid(const u8* in, u8* out) {{
    for (int y = 0; y < H; y++) {{
        for (int x = 0; x < W; x++) {{
            uint8_t self_c = in[y * W + x];
            bool even = ((x & 1) == 0);
            int yN  = y - 1, yS = y + 1;
            int yNE = even ? y - 1 : y;
            int ySE = even ? y     : y + 1;
            int ySW = even ? y     : y + 1;
            int yNW = even ? y - 1 : y;
            uint8_t n0 = (yN  >= 0)             ? in[yN  * W + x]     : 0;
            uint8_t n1 = (yNE >= 0 && x+1 < W && yNE < H) ? in[yNE * W + x+1] : 0;
            uint8_t n2 = (ySE < H && x+1 < W && ySE >= 0) ? in[ySE * W + x+1] : 0;
            uint8_t n3 = (yS  < H)              ? in[yS  * W + x]     : 0;
            uint8_t n4 = (ySW < H && x-1 >= 0 && ySW >= 0) ? in[ySW * W + x-1] : 0;
            uint8_t n5 = (yNW >= 0 && x-1 >= 0 && yNW < H) ? in[yNW * W + x-1] : 0;
            out[y * W + x] = lookup(self_c, n0, n1, n2, n3, n4, n5);
        }}
    }}
}}

// ── Score: edge-of-chaos parabola on the K=4-quantized change rate ───

static inline uint8_t q4(uint8_t v) {{
    return (uint8_t)((uint16_t)v * 4u / K);   // 0..K-1 → 0..3
}}

static void seed_grid(u8* g, uint32_t s) {{
    uint32_t saved = prng_state;
    prng_seed(s);
    for (int i = 0; i < W * H; i++) g[i] = prng_mod(K);
    prng_state = saved;
}}

struct ScoreOut {{ float fitness; float r; }};

static ScoreOut score_genome(const Genome* g, uint32_t grid_seed) {{
    build_bins(g);
    seed_grid(grid_a, grid_seed);
    for (int s = 0; s < BURN_IN; s++) {{
        step_grid(grid_a, grid_b);
        memcpy(grid_a, grid_b, sizeof(grid_a));
    }}
    long total = 0;
    int counted = 0;
    for (int s = 0; s < HORIZON - BURN_IN; s++) {{
        step_grid(grid_a, grid_b);
        int ch = 0;
        for (int i = 0; i < W * H; i++)
            if (q4(grid_a[i]) != q4(grid_b[i])) ch++;
        total += ch;
        counted++;
        memcpy(grid_a, grid_b, sizeof(grid_a));
    }}
    float r = counted ? (float)total / ((float)counted * W * H) : 0.0f;
    return {{ 4.0f * r * (1.0f - r), r }};
}}

// ── Mutation + crossover ─────────────────────────────────────────────
//
// Output mutation: small fraction of prototypes get a fresh random
// output colour. Key drift: a separate slice of bytes nudge ±1 (clamped)
// — drift, not teleport, so prototypes migrate smoothly in colour-space.
// Same axes as the browser bench's mutateGenome.

static inline float mut_rate(void) {{ return (float)MUT_PCT_E6 * 1e-6f; }}

static void mutate(Genome* child, const Genome* src, float rate) {{
    if (child != src) copy_genome(child, src);
    for (uint32_t i = 0; i < N_ENTRIES; i++) {{
        if (prng_unit() < rate) child->outs[i] = prng_mod(K);
    }}
    uint32_t key_muts = (uint32_t)((float)N_ENTRIES * 7.0f * rate);
    if (key_muts < 1) key_muts = 1;
    for (uint32_t m = 0; m < key_muts; m++) {{
        uint32_t i = prng_u32() % N_ENTRIES;
        uint8_t  j = (uint8_t)(prng_u32() % 7u);
        uint32_t off = i * 7u + j;
        int v = (int)child->keys[off] + (prng_unit() < 0.5f ? -1 : 1);
        if (v < 0) v = 0;
        if (v >= K) v = K - 1;
        child->keys[off] = (uint8_t)v;
    }}
}}

static void crossover(Genome* dst, const Genome* a, const Genome* b) {{
    uint32_t cut = 1u + (prng_u32() % (N_ENTRIES - 1u));
    for (uint32_t i = 0; i < N_ENTRIES; i++) {{
        const Genome* src = i < cut ? a : b;
        for (uint8_t j = 0; j < 7; j++) dst->keys[i * 7 + j] = src->keys[i * 7 + j];
        dst->outs[i] = src->outs[i];
    }}
}}

// ── GA: hunt (broad) and refine (narrow). Returns fitness of elite. ──

static float run_ga(bool refine_mode) {{
    float rate = mut_rate();

    // Seed population.
    copy_genome(&pop[0], &elite);
    if (refine_mode) {{
        for (int i = 1; i < POP_SIZE; i++) mutate(&pop[i], &elite, rate);
    }} else {{
        for (int i = 1; i < POP_SIZE / 2; i++) mutate(&pop[i], &elite, rate * 4.0f);
        for (int i = POP_SIZE / 2; i < POP_SIZE; i++)
            make_genome(&pop[i], prng_u32());
    }}

    float best_fit = -1.0f, best_r = 0.0f;
    uint8_t best_idx = 0;
    float fit[POP_SIZE];

    for (int gen = 0; gen < GENERATIONS; gen++) {{
        for (int i = 0; i < POP_SIZE; i++) {{
            ScoreOut s = score_genome(&pop[i], 0xA5A5u + gen);
            fit[i] = s.fitness;
            if (s.fitness > best_fit) {{
                best_fit = s.fitness;
                best_r   = s.r;
                copy_genome(&elite, &pop[i]);
                best_idx = (uint8_t)i;
            }}
            if (gen == 0 || (gen + 1) == GENERATIONS) {{
                Serial.printf("[ga] gen %d ind %d fit %.4f r %.3f best %.4f\\n",
                    gen, i, s.fitness, s.r, best_fit);
            }}
        }}
        // Survivors: top quarter by fitness, elite at index 0.
        uint8_t order[POP_SIZE];
        for (int i = 0; i < POP_SIZE; i++) order[i] = (uint8_t)i;
        for (int i = 0; i < POP_SIZE; i++)
            for (int j = i + 1; j < POP_SIZE; j++)
                if (fit[order[j]] > fit[order[i]]) {{
                    uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
                }}
        int n_surv = POP_SIZE / 4; if (n_surv < 2) n_surv = 2;
        // Build next generation in ga_next[] (BSS-resident; see note
        // below), then bulk-copy back into pop[]. Elite at index 0.
        copy_genome(&ga_next[0], &pop[order[0]]);
        for (int i = 1; i < POP_SIZE; i++) {{
            uint8_t a = order[(uint8_t)(prng_u32() % n_surv)];
            uint8_t b = order[(uint8_t)(prng_u32() % n_surv)];
            crossover(&scratch, &pop[a], &pop[b]);
            mutate(&ga_next[i], &scratch, rate);
        }}
        for (int i = 0; i < POP_SIZE; i++) copy_genome(&pop[i], &ga_next[i]);
    }}
    (void)best_idx;
    Serial.printf("[ga] %s done · best fit %.4f r %.3f\\n",
                  refine_mode ? "refine" : "hunt", best_fit, best_r);
    return best_fit;
}}

// ga_next[] above is BSS-resident — the population is far too large to
// fit on the Arduino loop-task's 8 KB stack. At N_LOG2={n_log2} that's
// POP_SIZE × {bytes_per_genome:,} = {pop_bytes:,} bytes. Same constraint
// applies if you re-distill with a bigger n_log2 or pop_size: the
// distiller's BSS budget check is the line of defence.

// ── Grid runner state ────────────────────────────────────────────────

static volatile uint32_t live_tick = 0;
static unsigned long last_step_ms = 0;

static void reseed_live_grid(uint32_t s) {{
    seed_grid(grid_a, s);
    live_tick = 0;
}}

static void runner_step(void) {{
    step_grid(grid_a, grid_b);
    memcpy(grid_a, grid_b, sizeof(grid_a));
    live_tick++;
}}

// ── Web UI ───────────────────────────────────────────────────────────

static const char* PAL_HEX[] = {{
    "#e74c3c", "#3498db", "#2ecc71", "#f1c40f",
    "#9b59b6", "#1abc9c", "#e67e22", "#ecf0f1",
    "#34495e", "#fd79a8", "#a29bfe", "#ffeaa7",
    "#55efc4", "#fab1a0", "#dfe6e9", "#74b9ff"
}};
static inline const char* pal(uint8_t v) {{
    return PAL_HEX[v % (sizeof(PAL_HEX) / sizeof(PAL_HEX[0]))];
}}

static String render_page(void) {{
    // Flat-top SVG of the live grid. Centres match the browser bench.
    const float SZ = 12.0f, SQRT3 = 1.7320508f;
    float colDx = SZ * 1.5f, rowH = SQRT3 * SZ;
    float svgW = (W + 1) * colDx + 8;
    float svgH = H * rowH + rowH * 0.5f + 12;

    String html;
    html.reserve(8192);
    html += F("<!doctype html><meta charset=utf-8><title>HexNN S3</title>");
    html += F("<style>body{{font-family:ui-monospace,Menlo,monospace;"
             "background:#0d1117;color:#c9d1d9;padding:1rem;max-width:64ch}}"
             "a{{color:#79c0ff}}.b{{display:inline-block;padding:0.3rem 0.6rem;"
             "background:#21262d;border:1px solid #30363d;color:#c9d1d9;"
             "text-decoration:none;margin-right:0.4rem}}"
             ".st{{color:#8b949e;font-size:0.85rem}}</style>");
    html += F("<h1>HexNN — ESP32-S3</h1>");
    html += "<p class=st>K=" + String(K) + " · N=" + String(N_ENTRIES)
          + " prototypes · grid " + String(W) + "x" + String(H)
          + " · tick " + String(live_tick) + "</p>";
    html += F("<p><a class=b href=/step>Step</a>"
             "<a class=b href=/reseed>Reseed grid</a>"
             "<a class=b href=/research>Re-run hunt</a>"
             "<a class=b href=/winner.json>winner.json</a></p>");
    html += "<svg width=\\"" + String((int)svgW) + "\\" height=\\"" + String((int)svgH)
          + "\\" style=\\"background:#0d1117;border:1px solid #30363d\\">";
    for (int y = 0; y < H; y++) {{
        for (int x = 0; x < W; x++) {{
            uint8_t v = grid_a[y * W + x];
            float cx = 4 + x * colDx + SZ;
            float cy = 4 + y * rowH + ((x & 1) ? rowH / 2.0f : 0.0f) + SZ;
            String pts;
            for (int i = 0; i < 6; i++) {{
                float a = (float)i * (float)PI / 3.0f;
                float px = cx + SZ * cosf(a);
                float py = cy + SZ * sinf(a);
                if (i) pts += " ";
                pts += String((int)px) + "," + String((int)py);
            }}
            html += "<polygon points=\\"" + pts + "\\" fill=\\"" + pal(v) + "\\"/>";
        }}
    }}
    html += F("</svg>");
    html += F("<p class=st>Auto-step every ");
    html += String(TICK_MS);
    html += F(" ms. Refresh the page to see the grid advance.</p>");
    return html;
}}

static String render_winner_json(void) {{
    String j;
    j.reserve(2048 + N_ENTRIES * 24);
    j += "{{\\"format\\":\\"hexnn-genome-v1\\",\\"K\\":" + String(K)
       + ",\\"n_entries\\":" + String(N_ENTRIES)
       + ",\\"source\\":\\"esp32-s3-condenser\\""
       + ",\\"keys\\":[";
    for (uint32_t i = 0; i < N_ENTRIES; i++) {{
        if (i) j += ",";
        j += "[";
        for (int k = 0; k < 7; k++) {{
            if (k) j += ",";
            j += String((int)elite.keys[i * 7 + k]);
        }}
        j += "]";
    }}
    j += "],\\"outputs\\":[";
    for (uint32_t i = 0; i < N_ENTRIES; i++) {{
        if (i) j += ",";
        j += String((int)elite.outs[i]);
    }}
    j += "]}}";
    return j;
}}

// ── Boot orchestration: random genome → optional GA → live runner ────

void setup() {{
    Serial.begin(115200);
    delay(60);
    Serial.println("\\n[hexnn-s3] booting");

    uint32_t boot_seed = esp_random();
    Serial.printf("[hexnn-s3] boot seed 0x%08X\\n", boot_seed);
    prng_seed(boot_seed);

    make_genome(&elite, boot_seed);
    build_bins(&elite);
    seed_grid(grid_a, boot_seed ^ 0xC0DECAFEu);

#if RUN_HUNT
    Serial.println("[hexnn-s3] hunt phase");
    run_ga(false);
    Serial.println("[hexnn-s3] refine phase");
    run_ga(true);
    build_bins(&elite);                // re-bin the post-GA elite
    seed_grid(grid_a, boot_seed ^ 0xFEEDFACEu);
#else
    Serial.println("[hexnn-s3] GA disabled at distill time");
#endif

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {{
        delay(500); Serial.print(".");
    }}
    if (WiFi.status() == WL_CONNECTED) {{
        Serial.printf("\\n[hexnn-s3] IP %s\\n",
                      WiFi.localIP().toString().c_str());
        MDNS.begin("hexnn-s3");
    }} else {{
        WiFi.softAP("hexnn-s3", "hexnn-s3-ap");
        Serial.println("\\n[hexnn-s3] AP mode hexnn-s3 / hexnn-s3-ap");
    }}

    server.on("/", []() {{ server.send(200, "text/html", render_page()); }});
    server.on("/step", []() {{
        runner_step();
        server.sendHeader("Location", "/");
        server.send(302);
    }});
    server.on("/reseed", []() {{
        reseed_live_grid(esp_random());
        server.sendHeader("Location", "/");
        server.send(302);
    }});
    server.on("/research", []() {{
        run_ga(false);
        run_ga(true);
        build_bins(&elite);
        reseed_live_grid(esp_random());
        server.sendHeader("Location", "/");
        server.send(302);
    }});
    server.on("/winner.json", []() {{
        server.send(200, "application/json", render_winner_json());
    }});
    server.begin();
    Serial.println("[hexnn-s3] http ready");
    last_step_ms = millis();
}}

void loop() {{
    server.handleClient();
    unsigned long now = millis();
    if (now - last_step_ms >= (unsigned long)TICK_MS) {{
        runner_step();
        last_step_ms = now;
    }}
}}
'''

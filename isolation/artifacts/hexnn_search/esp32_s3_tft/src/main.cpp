// CONDENSER: HexNN — full pipeline on ESP32-S3 SuperMini + ST7735 128x128
//
// One sketch covers the whole /hexnn/ browser app:
//   1. Generate a random 2048-prototype genome at K=4.
//   2. Hunt + Refine keep the elite as live state.
//   3. Run the live grid forever, one step every 200 ms.
//   4. Serve hexnn-s3.local over Wi-Fi: SVG render, /winner.json export.
//   5. Render the live grid to a 128x128 ST7735 every tick.
//
// Estimated BSS use: ~304 KB. Browser uses N_LOG2=14
// (16384 prototypes) by default; this build uses N_LOG2=11 so
// a population of 8 fits in on-chip SRAM without PSRAM.
//
// Build with Arduino-ESP32 (board: ESP32S3 Dev Module) or PlatformIO.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <esp_random.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>

// Supermini ST7735 pin map; matches isolation/artifacts/
// hex_ca_class4/* and the s3lab/esp32_s3_xcc fork.
#define TFT_SCK   12
#define TFT_MOSI  11
#define TFT_DC     4
#define TFT_CS     5
#define TFT_RST    6
#define TFT_BL     7


// ── Parameters baked at distillation time ────────────────────────────
#define K            4
#define N_LOG2       11
#define N_ENTRIES    (2048)        // 1 << N_LOG2
#define W            16
#define H            16
#define HORIZON      80
#define BURN_IN      20
#define POP_SIZE     8
#define GENERATIONS  30
#define MUT_PCT_E6   800  // mutation rate × 1e6
#define RUN_HUNT     1
#define TICK_MS      200

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";

WebServer server(80);

// ── PRNG — mulberry32, byte-for-byte identical to the JS reference ───
//
// The browser bench uses the same generator seeded from the URL "seed"
// field, so the same seed produces the same genome here as in the page.
// That makes /winner.json from the device round-trip into the JS bench
// for visual comparison.
static uint32_t prng_state = 1u;

static inline void prng_seed(uint32_t s) { prng_state = s ? s : 1u; }

static inline uint32_t prng_u32(void) {
    prng_state = (prng_state + 0x6D2B79F5u);
    uint32_t t = prng_state;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return (t ^ (t >> 14));
}

static inline float prng_unit(void) {
    return (float)prng_u32() / 4294967296.0f;
}

static inline uint8_t prng_mod(uint8_t m) {
    return (uint8_t)((prng_u32() % m) & 0xFFu);
}

// ── Genome layout ────────────────────────────────────────────────────
//
// Mirrors the JS Uint8Array packing: keys[i*7..i*7+6] = (self, n0..n5),
// outs[i] = output colour. 2048 entries × 8 bytes = 16,384
// bytes per genome.
typedef uint8_t u8;

struct Genome {
    u8 keys[N_ENTRIES * 7];
    u8 outs[N_ENTRIES];
};

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
struct BinIdx { uint16_t off; uint16_t count; };
static BinIdx bin_idx[K];

static u8 grid_a[W * H];
static u8 grid_b[W * H];

// Next-generation buffer for the GA, kept in BSS so the Arduino loop
// task's 8 KB stack never sees a population-sized allocation.
static Genome ga_next[POP_SIZE];

// ── Genome generation ─────────────────────────────────────────────────

static void make_genome(Genome* g, uint32_t seed) {
    prng_seed(seed);
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        for (uint8_t j = 0; j < 7; j++) g->keys[i * 7 + j] = prng_mod(K);
        g->outs[i] = prng_mod(K);
    }
}

static void copy_genome(Genome* dst, const Genome* src) {
    memcpy(dst->keys, src->keys, sizeof(dst->keys));
    memcpy(dst->outs, src->outs, sizeof(dst->outs));
}

// ── Bin build + nearest-prototype lookup ─────────────────────────────
//
// Two passes through the genome: first counts per-self, computes prefix-
// sum offsets; second writes neighbours+outs into the shared arena in
// the order the lookup wants them. After build, bin_idx[s] tells us
// where bin s sits inside bin_nbs / bin_outs.

static void build_bins(const Genome* g) {
    for (uint8_t s = 0; s < K; s++) bin_idx[s].count = 0;
    for (uint32_t i = 0; i < N_ENTRIES; i++) bin_idx[g->keys[i * 7]].count++;
    uint16_t off = 0;
    for (uint8_t s = 0; s < K; s++) {
        bin_idx[s].off = off;
        off = (uint16_t)(off + bin_idx[s].count);
        bin_idx[s].count = 0;            // reused as cursor below
    }
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        uint8_t s = g->keys[i * 7];
        uint16_t k = (uint16_t)(bin_idx[s].off + bin_idx[s].count);
        for (uint8_t j = 0; j < 6; j++) bin_nbs[k * 6 + j] = g->keys[i * 7 + 1 + j];
        bin_outs[k] = g->outs[i];
        bin_idx[s].count++;
    }
}

static inline uint8_t lookup(uint8_t self_c,
                             uint8_t n0, uint8_t n1, uint8_t n2,
                             uint8_t n3, uint8_t n4, uint8_t n5) {
    BinIdx ix = bin_idx[self_c];
    if (!ix.count) return self_c;
    uint16_t best = ix.off;
    int bestD = 0x7FFFFFFF;
    for (uint16_t k = 0; k < ix.count; k++) {
        uint16_t o = (uint16_t)((ix.off + k) * 6);
        int d0 = (int)bin_nbs[o]   - (int)n0;
        int d1 = (int)bin_nbs[o+1] - (int)n1;
        int d2 = (int)bin_nbs[o+2] - (int)n2;
        int d3 = (int)bin_nbs[o+3] - (int)n3;
        int d4 = (int)bin_nbs[o+4] - (int)n4;
        int d5 = (int)bin_nbs[o+5] - (int)n5;
        int d = d0*d0 + d1*d1 + d2*d2 + d3*d3 + d4*d4 + d5*d5;
        if (d < bestD) {
            bestD = d;
            best = (uint16_t)(ix.off + k);
            if (d == 0) break;        // exact match, no further search
        }
    }
    return bin_outs[best];
}

// ── Hex step (flat-top offset columns; matches s3lab + browser) ──────

static void step_grid(const u8* in, u8* out) {
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
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
        }
    }
}

// ── Score: edge-of-chaos parabola on the K=4-quantized change rate ───

static inline uint8_t q4(uint8_t v) {
    return (uint8_t)((uint16_t)v * 4u / K);   // 0..K-1 → 0..3
}

static void seed_grid(u8* g, uint32_t s) {
    uint32_t saved = prng_state;
    prng_seed(s);
    for (int i = 0; i < W * H; i++) g[i] = prng_mod(K);
    prng_state = saved;
}

struct ScoreOut { float fitness; float r; };

static ScoreOut score_genome(const Genome* g, uint32_t grid_seed) {
    build_bins(g);
    seed_grid(grid_a, grid_seed);
    for (int s = 0; s < BURN_IN; s++) {
        step_grid(grid_a, grid_b);
        memcpy(grid_a, grid_b, sizeof(grid_a));
    }
    long total = 0;
    int counted = 0;
    for (int s = 0; s < HORIZON - BURN_IN; s++) {
        step_grid(grid_a, grid_b);
        int ch = 0;
        for (int i = 0; i < W * H; i++)
            if (q4(grid_a[i]) != q4(grid_b[i])) ch++;
        total += ch;
        counted++;
        memcpy(grid_a, grid_b, sizeof(grid_a));
    }
    float r = counted ? (float)total / ((float)counted * W * H) : 0.0f;
    return { 4.0f * r * (1.0f - r), r };
}

// ── Mutation + crossover ─────────────────────────────────────────────
//
// Output mutation: small fraction of prototypes get a fresh random
// output colour. Key drift: a separate slice of bytes nudge ±1 (clamped)
// — drift, not teleport, so prototypes migrate smoothly in colour-space.
// Same axes as the browser bench's mutateGenome.

static inline float mut_rate(void) { return (float)MUT_PCT_E6 * 1e-6f; }

static void mutate(Genome* child, const Genome* src, float rate) {
    if (child != src) copy_genome(child, src);
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        if (prng_unit() < rate) child->outs[i] = prng_mod(K);
    }
    uint32_t key_muts = (uint32_t)((float)N_ENTRIES * 7.0f * rate);
    if (key_muts < 1) key_muts = 1;
    for (uint32_t m = 0; m < key_muts; m++) {
        uint32_t i = prng_u32() % N_ENTRIES;
        uint8_t  j = (uint8_t)(prng_u32() % 7u);
        uint32_t off = i * 7u + j;
        int v = (int)child->keys[off] + (prng_unit() < 0.5f ? -1 : 1);
        if (v < 0) v = 0;
        if (v >= K) v = K - 1;
        child->keys[off] = (uint8_t)v;
    }
}

static void crossover(Genome* dst, const Genome* a, const Genome* b) {
    uint32_t cut = 1u + (prng_u32() % (N_ENTRIES - 1u));
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        const Genome* src = i < cut ? a : b;
        for (uint8_t j = 0; j < 7; j++) dst->keys[i * 7 + j] = src->keys[i * 7 + j];
        dst->outs[i] = src->outs[i];
    }
}

// ── GA: hunt (broad) and refine (narrow). Returns fitness of elite. ──

static float run_ga(bool refine_mode) {
    float rate = mut_rate();

    // Seed population.
    copy_genome(&pop[0], &elite);
    if (refine_mode) {
        for (int i = 1; i < POP_SIZE; i++) mutate(&pop[i], &elite, rate);
    } else {
        for (int i = 1; i < POP_SIZE / 2; i++) mutate(&pop[i], &elite, rate * 4.0f);
        for (int i = POP_SIZE / 2; i < POP_SIZE; i++)
            make_genome(&pop[i], prng_u32());
    }

    float best_fit = -1.0f, best_r = 0.0f;
    uint8_t best_idx = 0;
    float fit[POP_SIZE];

    for (int gen = 0; gen < GENERATIONS; gen++) {
        for (int i = 0; i < POP_SIZE; i++) {
            ScoreOut s = score_genome(&pop[i], 0xA5A5u + gen);
            fit[i] = s.fitness;
            if (s.fitness > best_fit) {
                best_fit = s.fitness;
                best_r   = s.r;
                copy_genome(&elite, &pop[i]);
                best_idx = (uint8_t)i;
            }
            if (gen == 0 || (gen + 1) == GENERATIONS) {
                Serial.printf("[ga] gen %d ind %d fit %.4f r %.3f best %.4f\n",
                    gen, i, s.fitness, s.r, best_fit);
            }
        }
        // Survivors: top quarter by fitness, elite at index 0.
        uint8_t order[POP_SIZE];
        for (int i = 0; i < POP_SIZE; i++) order[i] = (uint8_t)i;
        for (int i = 0; i < POP_SIZE; i++)
            for (int j = i + 1; j < POP_SIZE; j++)
                if (fit[order[j]] > fit[order[i]]) {
                    uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
                }
        int n_surv = POP_SIZE / 4; if (n_surv < 2) n_surv = 2;
        // Build next generation in ga_next[] (BSS-resident; see note
        // below), then bulk-copy back into pop[]. Elite at index 0.
        copy_genome(&ga_next[0], &pop[order[0]]);
        for (int i = 1; i < POP_SIZE; i++) {
            uint8_t a = order[(uint8_t)(prng_u32() % n_surv)];
            uint8_t b = order[(uint8_t)(prng_u32() % n_surv)];
            crossover(&scratch, &pop[a], &pop[b]);
            mutate(&ga_next[i], &scratch, rate);
        }
        for (int i = 0; i < POP_SIZE; i++) copy_genome(&pop[i], &ga_next[i]);
    }
    (void)best_idx;
    Serial.printf("[ga] %s done · best fit %.4f r %.3f\n",
                  refine_mode ? "refine" : "hunt", best_fit, best_r);
    return best_fit;
}

// ga_next[] above is BSS-resident — the population is far too large to
// fit on the Arduino loop-task's 8 KB stack. At N_LOG2=11 that's
// POP_SIZE × 16,384 = 131,072 bytes. Same constraint
// applies if you re-distill with a bigger n_log2 or pop_size: the
// distiller's BSS budget check is the line of defence.

// ── Grid runner state ────────────────────────────────────────────────

static volatile uint32_t live_tick = 0;
static unsigned long last_step_ms = 0;

static void reseed_live_grid(uint32_t s) {
    seed_grid(grid_a, s);
    live_tick = 0;
}

// ── TFT state ────────────────────────────────────────────────────
//
// Diff-render scaffolding: pal_rgb565[K] cached at boot, last_drawn[]
// remembers what was last on-screen per cell so we only repaint the
// cells whose value changed.

static Adafruit_ST7735 tft(TFT_CS, TFT_DC, TFT_MOSI, TFT_SCK, TFT_RST);
static uint16_t pal_rgb565[K];
static uint8_t  last_drawn[W * H];

// Convert one of the PAL_HEX[] CSS strings to RGB565. The strings are
// 7-byte "#rrggbb" — fail-soft to black on any malformed value.
static uint16_t css_hex_to_rgb565(const char *css) {
    if (!css || css[0] != '#') return 0;
    uint32_t v = 0;
    for (int i = 1; i <= 6; i++) {
        char c = css[i];
        uint32_t d = 0;
        if      (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else return 0;
        v = (v << 4) | d;
    }
    uint8_t r = (v >> 16) & 0xFF, g = (v >> 8) & 0xFF, b = v & 0xFF;
    return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

static void rebuild_pal_rgb565(void) {
    for (int i = 0; i < K; i++) pal_rgb565[i] = css_hex_to_rgb565(pal((uint8_t)i));
}

// ── TFT render (pointy-top hex tiles, diff-only) ─────────────────
//
// Cell pixel size + row stagger derived at distill time:
//   cell_px = panel_w / (W + 1)        (= 7)
//   row_step_y = cell_px * 866 / 1000  (≈ √3/2 · cell_px)
// Tiles are drawn as filled rects (close enough at this size); odd
// columns shifted +cell_px/2 on y to mirror the SVG bench.

#define TFT_CELL_PX     7
#define TFT_ROW_STEP_X1000  866
#define TFT_PANEL_W     128
#define TFT_PANEL_H     128

// Cell render: width is one px less than the column stride, height
// is one px less than the row stride, so both axes show a 1-px black
// gap between cells (matches the JS emulator at /hexnn/tft/).
#define TFT_ROW_STEP_PX  ((TFT_CELL_PX * TFT_ROW_STEP_X1000) / 1000)
#define TFT_CELL_W       (TFT_CELL_PX - 1)
#define TFT_CELL_H       ((TFT_ROW_STEP_PX > 1) ? (TFT_ROW_STEP_PX - 1) : 1)

static inline void tft_draw_one(int x, int y, uint8_t v) {
    int px = x * TFT_CELL_PX;
    int py = y * TFT_ROW_STEP_PX
           + ((x & 1) ? (TFT_CELL_PX / 2) : 0);
    if (px + TFT_CELL_W > TFT_PANEL_W || py + TFT_CELL_H > TFT_PANEL_H) return;
    tft.fillRect(px, py, TFT_CELL_W, TFT_CELL_H, pal_rgb565[v]);
}

static void render_tft_full(void) {
    tft.fillScreen(0);
    for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
        uint8_t v = grid_a[y * W + x] % K;
        tft_draw_one(x, y, v);
        last_drawn[y * W + x] = v;
    }
}

static void render_tft_diff(void) {
    for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
        int idx = y * W + x;
        uint8_t v = grid_a[idx] % K;
        if (last_drawn[idx] == v) continue;
        tft_draw_one(x, y, v);
        last_drawn[idx] = v;
    }
}

static void runner_step(void) {
    step_grid(grid_a, grid_b);
    memcpy(grid_a, grid_b, sizeof(grid_a));
    live_tick++;
    render_tft_diff();
}

// ── Web UI ───────────────────────────────────────────────────────────

static const char* PAL_HEX[] = {
    "#e74c3c", "#3498db", "#2ecc71", "#f1c40f",
    "#9b59b6", "#1abc9c", "#e67e22", "#ecf0f1",
    "#34495e", "#fd79a8", "#a29bfe", "#ffeaa7",
    "#55efc4", "#fab1a0", "#dfe6e9", "#74b9ff"
};
static inline const char* pal(uint8_t v) {
    return PAL_HEX[v % (sizeof(PAL_HEX) / sizeof(PAL_HEX[0]))];
}

static String render_page(void) {
    // Flat-top SVG of the live grid. Centres match the browser bench.
    const float SZ = 12.0f, SQRT3 = 1.7320508f;
    float colDx = SZ * 1.5f, rowH = SQRT3 * SZ;
    float svgW = (W + 1) * colDx + 8;
    float svgH = H * rowH + rowH * 0.5f + 12;

    String html;
    html.reserve(8192);
    html += F("<!doctype html><meta charset=utf-8><title>HexNN S3</title>");
    html += F("<style>body{font-family:ui-monospace,Menlo,monospace;"
             "background:#0d1117;color:#c9d1d9;padding:1rem;max-width:64ch}"
             "a{color:#79c0ff}.b{display:inline-block;padding:0.3rem 0.6rem;"
             "background:#21262d;border:1px solid #30363d;color:#c9d1d9;"
             "text-decoration:none;margin-right:0.4rem}"
             ".st{color:#8b949e;font-size:0.85rem}</style>");
    html += F("<h1>HexNN — ESP32-S3</h1>");
    html += "<p class=st>K=" + String(K) + " · N=" + String(N_ENTRIES)
          + " prototypes · grid " + String(W) + "x" + String(H)
          + " · tick " + String(live_tick) + "</p>";
    html += F("<p><a class=b href=/step>Step</a>"
             "<a class=b href=/reseed>Reseed grid</a>"
             "<a class=b href=/research>Re-run hunt</a>"
             "<a class=b href=/winner.json>winner.json</a></p>");
    html += "<svg width=\"" + String((int)svgW) + "\" height=\"" + String((int)svgH)
          + "\" style=\"background:#0d1117;border:1px solid #30363d\">";
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            uint8_t v = grid_a[y * W + x];
            float cx = 4 + x * colDx + SZ;
            float cy = 4 + y * rowH + ((x & 1) ? rowH / 2.0f : 0.0f) + SZ;
            String pts;
            for (int i = 0; i < 6; i++) {
                float a = (float)i * (float)PI / 3.0f;
                float px = cx + SZ * cosf(a);
                float py = cy + SZ * sinf(a);
                if (i) pts += " ";
                pts += String((int)px) + "," + String((int)py);
            }
            html += "<polygon points=\"" + pts + "\" fill=\"" + pal(v) + "\"/>";
        }
    }
    html += F("</svg>");
    html += F("<p class=st>Auto-step every ");
    html += String(TICK_MS);
    html += F(" ms. Refresh the page to see the grid advance.</p>");
    return html;
}

static String render_winner_json(void) {
    String j;
    j.reserve(2048 + N_ENTRIES * 24);
    j += "{\"format\":\"hexnn-genome-v1\",\"K\":" + String(K)
       + ",\"n_entries\":" + String(N_ENTRIES)
       + ",\"source\":\"esp32-s3-condenser\""
       + ",\"keys\":[";
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        if (i) j += ",";
        j += "[";
        for (int k = 0; k < 7; k++) {
            if (k) j += ",";
            j += String((int)elite.keys[i * 7 + k]);
        }
        j += "]";
    }
    j += "],\"outputs\":[";
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        if (i) j += ",";
        j += String((int)elite.outs[i]);
    }
    j += "]}";
    return j;
}

// ── Boot orchestration: random genome → optional GA → live runner ────

void setup() {
    Serial.begin(115200);
    delay(60);
    Serial.println("\n[hexnn-s3] booting");
    // ── ST7735 TFT init ─────────────────────────────────────
    pinMode(TFT_BL, OUTPUT); digitalWrite(TFT_BL, HIGH);
    tft.initR(INITR_144GREENTAB);
    tft.setSPISpeed(27000000UL);
    tft.setRotation(0);
    tft.fillScreen(0);
    rebuild_pal_rgb565();
    render_tft_full();

    uint32_t boot_seed = esp_random();
    Serial.printf("[hexnn-s3] boot seed 0x%08X\n", boot_seed);
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
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500); Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[hexnn-s3] IP %s\n",
                      WiFi.localIP().toString().c_str());
        MDNS.begin("hexnn-s3");
    } else {
        WiFi.softAP("hexnn-s3", "hexnn-s3-ap");
        Serial.println("\n[hexnn-s3] AP mode hexnn-s3 / hexnn-s3-ap");
    }

    server.on("/", []() { server.send(200, "text/html", render_page()); });
    server.on("/step", []() {
        runner_step();
        server.sendHeader("Location", "/");
        server.send(302);
    });
    server.on("/reseed", []() {
        reseed_live_grid(esp_random());
        server.sendHeader("Location", "/");
        server.send(302);
    });
    server.on("/research", []() {
        run_ga(false);
        run_ga(true);
        build_bins(&elite);
        reseed_live_grid(esp_random());
        server.sendHeader("Location", "/");
        server.send(302);
    });
    server.on("/winner.json", []() {
        server.send(200, "application/json", render_winner_json());
    });
    server.begin();
    Serial.println("[hexnn-s3] http ready");
    last_step_ms = millis();
}

void loop() {
    server.handleClient();
    unsigned long now = millis();
    if (now - last_step_ms >= (unsigned long)TICK_MS) {
        runner_step();
        last_step_ms = now;
    }
}

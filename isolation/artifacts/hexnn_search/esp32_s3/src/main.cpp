// HexNN class-4 hunter — ESP32-S3 SuperMini port.
//
// Direct port of ../pi4.py (the canonical reference) and of the
// in-browser bench at /hexnn/. Same algorithm, same constants, same
// scoring. The Pi engine writes a hexnn-genome-v1 JSON file; this
// device persists the same data to LittleFS as /elite.bin and prints
// it to USB CDC on demand.
//
// Pipeline (mirrors hexnn.engine + the browser GA):
//   1. Load /elite.bin if present, else generate a random genome
//      seeded from esp_random() and persist.
//   2. Population = elite + (POP_SIZE - 1) variants. Hunt seeds half
//      from a 4× rate mutation of elite + half random; Refine seeds
//      all from a 1× rate mutation of elite. Either round preserves
//      elite at index 0.
//   3. Score each genome on a fresh grid: burn-in, then mean K=4-
//      quantized change rate; fitness = 4·r·(1-r) (edge-of-chaos).
//   4. Sort, take top quarter, fill via crossover + mutate.
//   5. After N generations, re-bin the elite, persist back to
//      /elite.bin, print as hexnn-genome-v1 JSON, then step a live
//      grid every TICK_MS ms forever.
//
// Memory: 8 × (1<<11) × 8 = 128 KB population in BSS, plus a same-
// sized swap arena, plus elite/scratch/bins. ~305 KB total at the
// default config — fits easily in the S3 SuperMini's 512 KB SRAM.

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_system.h>
#include <esp_random.h>

// ── Compile-time configuration ───────────────────────────────────────
//
// Override any of these at build time:
//   build_flags = -DK=8 -DN_LOG2=12 -DPOP_SIZE=4
// to widen the colour palette, double the prototype count, etc.
#ifndef K
  #define K          4
#endif
#ifndef N_LOG2
  #define N_LOG2    11
#endif
#define N_ENTRIES   (1u << N_LOG2)
#ifndef GRID_W
  #define GRID_W    16
#endif
#ifndef GRID_H
  #define GRID_H    16
#endif
#ifndef HORIZON
  #define HORIZON   80
#endif
#ifndef BURN_IN
  #define BURN_IN   20
#endif
#ifndef POP_SIZE
  #define POP_SIZE   8
#endif
#ifndef GENERATIONS
  #define GENERATIONS 30
#endif
#ifndef MUT_PCT_E6
  #define MUT_PCT_E6  800   // mutation rate × 1e6 (= 0.0008)
#endif
#ifndef TICK_MS
  #define TICK_MS    200
#endif

#define ELITE_PATH   "/elite.bin"
#define MAGIC        "HXNN"
#define MAGIC_BYTES  4

typedef uint8_t u8;

// ── PRNG: mulberry32 (matches pi4.py + the browser bench) ────────────
static uint32_t prng_state = 1u;

static inline void prng_seed(uint32_t s) { prng_state = s ? s : 1u; }
static inline uint32_t prng_u32(void) {
    prng_state = (prng_state + 0x6D2B79F5u);
    uint32_t t = prng_state;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return (t ^ (t >> 14));
}
static inline float    prng_unit(void)        { return (float)prng_u32() / 4294967296.0f; }
static inline uint8_t  prng_modK(void)        { return (uint8_t)(prng_u32() % K); }
static inline uint32_t prng_modN(uint32_t n)  { return prng_u32() % n; }

// ── Genome ───────────────────────────────────────────────────────────
//
// keys[i*7 + 0..6] = (self, n0..n5); outs[i] = output colour. Same
// packing as the JS Uint8Arrays in /hexnn/.
struct Genome {
    u8 keys[N_ENTRIES * 7];
    u8 outs[N_ENTRIES];
};

static Genome pop[POP_SIZE];
static Genome ga_next[POP_SIZE];   // BSS, not stack — see notes/.
static Genome elite;
static Genome scratch;             // crossover work buffer

// Bin index: shared arena (size of one genome) + per-self {off, count}.
static u8       bin_nbs[N_ENTRIES * 6];
static u8       bin_outs[N_ENTRIES];
struct BinIdx { uint16_t off; uint16_t count; };
static BinIdx   bin_idx[K];

static u8 grid_a[GRID_W * GRID_H];
static u8 grid_b[GRID_W * GRID_H];

static unsigned long last_step_ms = 0;

// ── Genome helpers ───────────────────────────────────────────────────

static void make_genome(Genome* g) {
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        for (uint8_t j = 0; j < 7; j++) g->keys[i * 7 + j] = prng_modK();
        g->outs[i] = prng_modK();
    }
}

static inline void copy_genome(Genome* dst, const Genome* src) {
    memcpy(dst->keys, src->keys, sizeof(dst->keys));
    memcpy(dst->outs, src->outs, sizeof(dst->outs));
}

static void build_bins(const Genome* g) {
    for (uint8_t s = 0; s < K; s++) bin_idx[s].count = 0;
    for (uint32_t i = 0; i < N_ENTRIES; i++) bin_idx[g->keys[i * 7]].count++;
    uint16_t off = 0;
    for (uint8_t s = 0; s < K; s++) {
        bin_idx[s].off = off;
        off = (uint16_t)(off + bin_idx[s].count);
        bin_idx[s].count = 0;
    }
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        uint8_t s = g->keys[i * 7];
        uint16_t k = (uint16_t)(bin_idx[s].off + bin_idx[s].count);
        for (uint8_t j = 0; j < 6; j++) bin_nbs[k * 6 + j] = g->keys[i * 7 + 1 + j];
        bin_outs[k] = g->outs[i];
        bin_idx[s].count++;
    }
}

static inline uint8_t lookup(uint8_t self_c, uint8_t n0, uint8_t n1,
                             uint8_t n2, uint8_t n3, uint8_t n4, uint8_t n5) {
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
            if (d == 0) break;
        }
    }
    return bin_outs[best];
}

static void step_grid(const u8* in, u8* out) {
    for (int y = 0; y < GRID_H; y++) {
        for (int x = 0; x < GRID_W; x++) {
            uint8_t self_c = in[y * GRID_W + x];
            bool even = ((x & 1) == 0);
            int yN  = y - 1, yS = y + 1;
            int yNE = even ? y - 1 : y;
            int ySE = even ? y     : y + 1;
            int ySW = even ? y     : y + 1;
            int yNW = even ? y - 1 : y;
            uint8_t n0 = (yN  >= 0)              ? in[yN  * GRID_W + x]     : 0;
            uint8_t n1 = (yNE >= 0 && x+1 < GRID_W && yNE < GRID_H) ? in[yNE * GRID_W + x+1] : 0;
            uint8_t n2 = (ySE < GRID_H && x+1 < GRID_W && ySE >= 0) ? in[ySE * GRID_W + x+1] : 0;
            uint8_t n3 = (yS  < GRID_H)          ? in[yS  * GRID_W + x]     : 0;
            uint8_t n4 = (ySW < GRID_H && x-1 >= 0 && ySW >= 0) ? in[ySW * GRID_W + x-1] : 0;
            uint8_t n5 = (yNW >= 0 && x-1 >= 0 && yNW < GRID_H) ? in[yNW * GRID_W + x-1] : 0;
            out[y * GRID_W + x] = lookup(self_c, n0, n1, n2, n3, n4, n5);
        }
    }
}

// ── Score ────────────────────────────────────────────────────────────

static inline uint8_t q4(uint8_t v) { return (uint8_t)((uint16_t)v * 4u / K); }

static void seed_grid(u8* g, uint32_t s) {
    uint32_t saved = prng_state;
    prng_seed(s);
    for (int i = 0; i < GRID_W * GRID_H; i++) g[i] = prng_modK();
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
        for (int i = 0; i < GRID_W * GRID_H; i++)
            if (q4(grid_a[i]) != q4(grid_b[i])) ch++;
        total += ch;
        counted++;
        memcpy(grid_a, grid_b, sizeof(grid_a));
    }
    float r = counted ? (float)total / ((float)counted * GRID_W * GRID_H) : 0.0f;
    return { 4.0f * r * (1.0f - r), r };
}

// ── Mutation + crossover ─────────────────────────────────────────────

static inline float mut_rate(void) { return (float)MUT_PCT_E6 * 1e-6f; }

static void mutate(Genome* dst, const Genome* src, float rate) {
    if (dst != src) copy_genome(dst, src);
    for (uint32_t i = 0; i < N_ENTRIES; i++)
        if (prng_unit() < rate) dst->outs[i] = prng_modK();
    uint32_t key_muts = (uint32_t)((float)N_ENTRIES * 7.0f * rate);
    if (key_muts < 1) key_muts = 1;
    for (uint32_t m = 0; m < key_muts; m++) {
        uint32_t i = prng_modN(N_ENTRIES);
        uint8_t  j = (uint8_t)(prng_u32() % 7u);
        uint32_t off = i * 7u + j;
        int v = (int)dst->keys[off] + (prng_unit() < 0.5f ? -1 : 1);
        if (v < 0) v = 0;
        if (v >= K) v = K - 1;
        dst->keys[off] = (uint8_t)v;
    }
}

static void crossover(Genome* dst, const Genome* a, const Genome* b) {
    uint32_t cut = 1u + prng_modN(N_ENTRIES - 1u);
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        const Genome* src = i < cut ? a : b;
        for (uint8_t j = 0; j < 7; j++) dst->keys[i * 7 + j] = src->keys[i * 7 + j];
        dst->outs[i] = src->outs[i];
    }
}

// ── GA: hunt + refine ────────────────────────────────────────────────

static float run_ga(bool refine_mode) {
    float rate = mut_rate();
    copy_genome(&pop[0], &elite);
    if (refine_mode) {
        for (int i = 1; i < POP_SIZE; i++) mutate(&pop[i], &elite, rate);
    } else {
        for (int i = 1; i < POP_SIZE / 2; i++) mutate(&pop[i], &elite, rate * 4.0f);
        for (int i = POP_SIZE / 2; i < POP_SIZE; i++) {
            prng_seed(prng_u32() ^ 0xA5A5u);
            make_genome(&pop[i]);
        }
    }

    float best_fit = -1.0f, best_r = 0.0f;
    float fit[POP_SIZE];

    for (int gen = 0; gen < GENERATIONS; gen++) {
        for (int i = 0; i < POP_SIZE; i++) {
            ScoreOut s = score_genome(&pop[i], 0xA5A5u + (uint32_t)gen);
            fit[i] = s.fitness;
            if (s.fitness > best_fit) {
                best_fit = s.fitness;
                best_r   = s.r;
                copy_genome(&elite, &pop[i]);
            }
        }
        Serial.printf("[ga] %s gen %2d  best %.4f  r=%.3f\n",
                      refine_mode ? "refine" : "hunt  ",
                      gen + 1, best_fit, best_r);

        uint8_t order[POP_SIZE];
        for (int i = 0; i < POP_SIZE; i++) order[i] = (uint8_t)i;
        for (int i = 0; i < POP_SIZE; i++)
            for (int j = i + 1; j < POP_SIZE; j++)
                if (fit[order[j]] > fit[order[i]]) {
                    uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
                }
        int n_surv = POP_SIZE / 4; if (n_surv < 2) n_surv = 2;

        copy_genome(&ga_next[0], &pop[order[0]]);
        for (int i = 1; i < POP_SIZE; i++) {
            uint8_t a = order[(uint8_t)prng_modN(n_surv)];
            uint8_t b = order[(uint8_t)prng_modN(n_surv)];
            crossover(&scratch, &pop[a], &pop[b]);
            mutate(&ga_next[i], &scratch, rate);
        }
        for (int i = 0; i < POP_SIZE; i++) copy_genome(&pop[i], &ga_next[i]);
    }
    return best_fit;
}

// ── LittleFS persistence ─────────────────────────────────────────────
//
// File layout: 4-byte magic "HXNN" + K + n_log2 + 0 + 0 + N×7 keys + N outs.
// Same on-the-wire shape hexnn/genome.py uses — except we don't ship a
// palette here (the device produces no images; the Pi-side reference
// supplies its own palette when re-rendering).

static bool save_elite(void) {
    File f = LittleFS.open(ELITE_PATH, "w");
    if (!f) return false;
    u8 hdr[8] = { 'H','X','N','N', K, N_LOG2, 0, 0 };
    f.write(hdr, sizeof(hdr));
    f.write(elite.keys, sizeof(elite.keys));
    f.write(elite.outs, sizeof(elite.outs));
    f.close();
    return true;
}

static bool load_elite(void) {
    File f = LittleFS.open(ELITE_PATH, "r");
    if (!f) return false;
    u8 hdr[8];
    if (f.read(hdr, sizeof(hdr)) != sizeof(hdr)) { f.close(); return false; }
    if (memcmp(hdr, MAGIC, 4) || hdr[4] != K || hdr[5] != N_LOG2) {
        // Magic / shape mismatch — treat as fresh boot. Same effect as
        // deleting /elite.bin manually.
        Serial.println("[fs] /elite.bin shape mismatch, regenerating");
        f.close();
        return false;
    }
    bool ok = (f.read(elite.keys, sizeof(elite.keys)) == (int)sizeof(elite.keys))
           && (f.read(elite.outs, sizeof(elite.outs)) == (int)sizeof(elite.outs));
    f.close();
    return ok;
}

// ── Periodic JSON snapshot to USB CDC ────────────────────────────────
//
// Same shape the browser bench writes from "Download JSON". A reader
// can pipe USB CDC through `awk '/^---hexnn-begin---/,/^---hexnn-end---/'`
// to capture exactly one snapshot.

static void print_elite_json(void) {
    Serial.println("---hexnn-begin---");
    Serial.print("{\"format\":\"hexnn-genome-v1\",\"K\":");
    Serial.print(K);
    Serial.print(",\"n_entries\":"); Serial.print((long)N_ENTRIES);
    Serial.print(",\"source\":\"esp32-s3-isolation\",\"keys\":[");
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        if (i) Serial.print(',');
        Serial.print('[');
        for (int k = 0; k < 7; k++) {
            if (k) Serial.print(',');
            Serial.print((int)elite.keys[i * 7 + k]);
        }
        Serial.print(']');
    }
    Serial.print("],\"outputs\":[");
    for (uint32_t i = 0; i < N_ENTRIES; i++) {
        if (i) Serial.print(',');
        Serial.print((int)elite.outs[i]);
    }
    Serial.println("]}");
    Serial.println("---hexnn-end---");
}

// ── Boot orchestration ───────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n[hexnn-s3] booting");

    uint32_t boot_seed = esp_random();
    Serial.printf("[hexnn-s3] boot seed 0x%08X\n", boot_seed);
    prng_seed(boot_seed);

    if (!LittleFS.begin(true)) {
        Serial.println("[fs] LittleFS mount failed; halting");
        while (true) delay(1000);
    }

    if (!load_elite()) {
        Serial.println("[fs] no /elite.bin — generating fresh genome");
        make_genome(&elite);
        save_elite();
    } else {
        Serial.println("[fs] loaded /elite.bin");
    }
    build_bins(&elite);
    seed_grid(grid_a, boot_seed ^ 0xC0DECAFEu);

    Serial.println("[hexnn-s3] hunt phase");
    run_ga(false);
    Serial.println("[hexnn-s3] refine phase");
    run_ga(true);

    build_bins(&elite);
    save_elite();
    seed_grid(grid_a, boot_seed ^ 0xFEEDFACEu);
    print_elite_json();

    last_step_ms = millis();
    Serial.println("[hexnn-s3] live runner started");
}

void loop() {
    unsigned long now = millis();
    if (now - last_step_ms >= (unsigned long)TICK_MS) {
        step_grid(grid_a, grid_b);
        memcpy(grid_a, grid_b, sizeof(grid_a));
        last_step_ms = now;

        // Print a one-line activity summary every step so the host
        // can see motion. JSON snapshot every 50 steps.
        static uint32_t tick = 0;
        tick++;
        if (tick % 50 == 0) print_elite_json();
    }
    delay(2);
}

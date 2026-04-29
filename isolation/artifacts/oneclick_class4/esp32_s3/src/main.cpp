// One-click hex-CA class-4 hunter — ESP32-S3 SuperMini port.
//
// Direct port of isolation/artifacts/oneclick_class4/hunter.c (GA mode
// only; no display, no animated render). Same algorithm, same constants,
// same scoring. The Linux engine self-replicates by copying its own ELF
// bytes; on the S3 the engine lives in flash and we self-replicate by
// writing 4104-byte [magic][palette][genome] tails to LittleFS instead.
//
// Pipeline (matches det.pipeline.run_oneclick_pipeline):
//   1. Load /seed.bin (HXC4 magic + 4 palette + 4096 genome). Bootstrap
//      a random palette + identity genome on first boot.
//   2. Build the initial population: seed + (POP-1) mutants @ 5%.
//   3. Tournament-2 GA on a 14×14 hex grid for GENS generations.
//   4. Re-score; tournament top WINNERS across TSEEDS grid seeds.
//   5. Persist each winner as /winner_<N>.bin and emit hex on USB CDC.
//
// Memory: 30 × 4096 = 120 KB population in BSS. The S3 SuperMini has
// 512 KB SRAM, so we have ~390 KB free even before reaching for PSRAM.
//
// Build & flash:
//   pio run -t upload && pio device monitor

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_system.h>

#define K           4
#define NSIT        16384
#define GBYTES      4096
#define PAL_BYTES   4
#define MAGIC_BYTES 4
#define TAIL_MAGIC  "HXC4"
#define TAIL_BYTES  (MAGIC_BYTES + PAL_BYTES + GBYTES)
#define GRID_W      14
#define GRID_H      14
#define HORIZON     25
#define POP         30
#define GENS        40
#define TSEEDS      3
#define WINNERS     3

typedef uint8_t u8;

// ── BSS-resident arenas ───────────────────────────────────────────────
//
// All large buffers live in BSS so we don't blow the 8 KB Arduino loop
// task stack. tmp_genome / tmp_pal are the working buffers used by the
// insertion sort and the breeding step.

static u8     pool[POP][GBYTES];
static u8     pals[POP][PAL_BYTES];
static double fit[POP];

static u8 seed_genome[GBYTES];
static u8 seed_pal[PAL_BYTES];

static u8 grid_a[GRID_W * GRID_H];
static u8 grid_b[GRID_W * GRID_H];

static u8 tmp_genome[GBYTES];
static u8 tmp_pal[PAL_BYTES];

// Hex offset deltas — match hunter.c exactly.
static const int DY[6]  = { -1, -1,  0,  0,  1,  1 };
static const int DXE[6] = {  0,  1, -1,  1, -1,  0 };
static const int DXO[6] = { -1,  0, -1,  1,  0,  1 };

static double last_activity_tail = 0.0;

// ── PRNG ──────────────────────────────────────────────────────────────
//
// xorshift32 — seeded once from esp_random() at boot. ~3 ns per call,
// vs ~1 µs for esp_random's hardware TRNG. Mutation calls the PRNG
// per situation (16384 × per-genome-mutated × per-gen = many millions
// of calls), so the speed difference is the difference between a few
// seconds per hunt and tens of seconds.
static uint32_t prng_state = 0x9E3779B9u;
static inline uint32_t prng() {
    uint32_t x = prng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return prng_state = x;
}
static inline double prng_unit() {
    return (double)prng() / (double)UINT32_MAX;
}

// Park-Miller LCG for grid seeding — kept separate from the GA PRNG
// so a given (genome, grid_seed) pair always produces the same scoring
// trajectory regardless of where in the GA loop we are. Matches
// hunter.c exactly.
static uint32_t lcg_state;
static inline uint32_t lcg() {
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}

// ── Packed-genome accessors ───────────────────────────────────────────

static inline int g_get(const u8 *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
static inline void g_set(u8 *g, int idx, int v) {
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}
static inline int sit_idx(int s, const int *n) {
    int i = s;
    for (int k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}

// ── Hex stepping ──────────────────────────────────────────────────────

static void seed_grid(u8 *grid, uint32_t s) {
    lcg_state = s ? s : 1;
    for (int i = 0; i < GRID_W * GRID_H; i++)
        grid[i] = lcg() & 3;
}

static void step_grid(const u8 *g, const u8 *in, u8 *out) {
    for (int y = 0; y < GRID_H; y++) {
        const int *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < GRID_W; x++) {
            int self = in[y * GRID_W + x];
            int n[6];
            for (int k = 0; k < 6; k++) {
                int yy = y + DY[k];
                int xx = x + dx[k];
                n[k] = (yy >= 0 && yy < GRID_H
                     && xx >= 0 && xx < GRID_W) ? in[yy * GRID_W + xx] : 0;
            }
            out[y * GRID_W + x] = g_get(g, sit_idx(self, n));
        }
    }
}

// ── Class-4 fitness ───────────────────────────────────────────────────

static double fitness(const u8 *genome, uint32_t grid_seed) {
    seed_grid(grid_a, grid_seed);
    double act[HORIZON];
    int colour_counts_final[K] = {0};
    for (int t = 0; t < HORIZON; t++) {
        step_grid(genome, grid_a, grid_b);
        int changed = 0;
        for (int i = 0; i < GRID_W * GRID_H; i++)
            if (grid_a[i] != grid_b[i]) changed++;
        act[t] = (double)changed / (GRID_W * GRID_H);
        memcpy(grid_a, grid_b, GRID_W * GRID_H);
    }

    int uniform = 1;
    for (int i = 1; i < GRID_W * GRID_H; i++)
        if (grid_a[i] != grid_a[0]) { uniform = 0; break; }
    for (int i = 0; i < GRID_W * GRID_H; i++)
        colour_counts_final[grid_a[i]]++;
    int diversity = 0;
    for (int c = 0; c < K; c++)
        if (colour_counts_final[c] * 100 >= GRID_W * GRID_H) diversity++;

    int tail_n = HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;
    last_activity_tail = avg;

    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;
    double activity_reward;
    if (avg <= 0.12) activity_reward = avg / 0.12;
    else             activity_reward = (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    if (diversity >= 2) score += 0.25 * (diversity < K ? diversity : K);
    return score;
}

// ── Seed / palette bootstrap ──────────────────────────────────────────

static void identity_genome(u8 *g) {
    memset(g + 0 * 1024, 0x00, 1024);
    memset(g + 1 * 1024, 0x55, 1024);
    memset(g + 2 * 1024, 0xAA, 1024);
    memset(g + 3 * 1024, 0xFF, 1024);
}

static void invent_palette(u8 *pal) {
    for (int i = 0; i < K; ) {
        int c = ((prng() % 10) < 9)
              ? (16  + (int)(prng() % 216))
              : (232 + (int)(prng() % 24));
        int ok = 1;
        for (int j = 0; j < i; j++) if (pal[j] == c) { ok = 0; break; }
        if (ok) pal[i++] = (u8)c;
    }
}

// ── GA ops ────────────────────────────────────────────────────────────

static void mutate(u8 *dst, const u8 *src, double rate) {
    memcpy(dst, src, GBYTES);
    for (int i = 0; i < NSIT; i++) {
        if (prng_unit() < rate)
            g_set(dst, i, prng() & 3);
    }
}

static void cross(u8 *dst, const u8 *a, const u8 *b) {
    int cut = 1 + (int)(prng() % (GBYTES - 1));
    memcpy(dst, a, cut);
    memcpy(dst + cut, b + cut, GBYTES - cut);
}

static void palette_inherit(u8 *dst, const u8 *a, const u8 *b) {
    const u8 *src = (prng() & 1) ? a : b;
    memcpy(dst, src, PAL_BYTES);
    if ((prng() % 100) < 8) {
        int slot = prng() % K;
        int c = ((prng() % 10) < 9)
              ? (16  + (int)(prng() % 216))
              : (232 + (int)(prng() % 24));
        dst[slot] = (u8)c;
    }
}

// ── LittleFS persistence ──────────────────────────────────────────────

static int read_seed_from_fs(const char *path, u8 *pal, u8 *genome) {
    File f = LittleFS.open(path, "r");
    if (!f) return -1;
    if ((size_t)f.size() < TAIL_BYTES) { f.close(); return -1; }
    char magic[MAGIC_BYTES];
    int ok = (f.read((u8 *)magic, MAGIC_BYTES) == MAGIC_BYTES)
          && (memcmp(magic, TAIL_MAGIC, MAGIC_BYTES) == 0)
          && (f.read(pal, PAL_BYTES) == PAL_BYTES)
          && (f.read(genome, GBYTES) == GBYTES);
    f.close();
    return ok ? 0 : -1;
}

static int write_tail_to_fs(const char *path, const u8 *pal, const u8 *genome) {
    File f = LittleFS.open(path, "w");
    if (!f) return -1;
    f.write((const u8 *)TAIL_MAGIC, MAGIC_BYTES);
    f.write(pal, PAL_BYTES);
    f.write(genome, GBYTES);
    f.close();
    return 0;
}

static int next_winner_slot() {
    for (int i = 1; i < 1000; i++) {
        char path[32];
        snprintf(path, sizeof path, "/winner_%d.bin", i);
        if (!LittleFS.exists(path)) return i;
    }
    return -1;
}

// ── Insertion sort by fitness desc (palette follows genome) ──────────

static void sort_pop() {
    for (int i = 1; i < POP; i++) {
        double fv = fit[i];
        memcpy(tmp_genome, pool[i], GBYTES);
        memcpy(tmp_pal,    pals[i], PAL_BYTES);
        int j = i - 1;
        while (j >= 0 && fit[j] < fv) {
            fit[j + 1] = fit[j];
            memcpy(pool[j + 1], pool[j], GBYTES);
            memcpy(pals[j + 1], pals[j], PAL_BYTES);
            j--;
        }
        fit[j + 1] = fv;
        memcpy(pool[j + 1], tmp_genome, GBYTES);
        memcpy(pals[j + 1], tmp_pal,    PAL_BYTES);
    }
}

// ── Hex emission on USB CDC ───────────────────────────────────────────

static void emit_hex(const u8 *pal, const u8 *genome) {
    char buf[3];
    for (int i = 0; i < PAL_BYTES; i++) {
        snprintf(buf, sizeof buf, "%02x", pal[i]);
        Serial.print(buf);
    }
    for (int i = 0; i < GBYTES; i++) {
        snprintf(buf, sizeof buf, "%02x", genome[i]);
        Serial.print(buf);
    }
    Serial.println();
}

// ── setup / loop ──────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    // Wait briefly for USB CDC to come up so the user sees the banner.
    uint32_t t_start = millis();
    while (!Serial && (millis() - t_start) < 2000) delay(10);
    Serial.println();
    Serial.println("=== oneclick hex-CA class-4 hunter — ESP32-S3 ===");

    if (!LittleFS.begin(true)) {  // format on first mount failure
        Serial.println("LittleFS mount failed — winners will not persist");
    }

    // PRNG seed: hardware TRNG mixed with boot timing. Different every
    // reset, so pressing the reset button gets a fresh hunt.
    prng_state = esp_random() ^ (uint32_t)esp_timer_get_time();
    if (!prng_state) prng_state = 1;

    // Load /seed.bin or bootstrap.
    if (read_seed_from_fs("/seed.bin", seed_pal, seed_genome) != 0) {
        Serial.println("no /seed.bin — bootstrapping random palette + identity genome");
        invent_palette(seed_pal);
        identity_genome(seed_genome);
        write_tail_to_fs("/seed.bin", seed_pal, seed_genome);
    }
    Serial.printf("seed palette = [%d %d %d %d]\n",
                  seed_pal[0], seed_pal[1], seed_pal[2], seed_pal[3]);

    // The grid seed used during the GA is fixed for one hunt so the
    // sort is consistent across generations; per-winner tournament uses
    // grid_seed + 100 + s. Mirrors hunter.c.
    uint32_t grid_seed = prng();
    Serial.printf("grid seed = %u\n", (unsigned)grid_seed);

    // Initial population: seed + mutants @ 5%.
    memcpy(pool[0], seed_genome, GBYTES);
    memcpy(pals[0], seed_pal,    PAL_BYTES);
    for (int i = 1; i < POP; i++) {
        mutate(pool[i], seed_genome, 0.05);
        memcpy(pals[i], seed_pal, PAL_BYTES);
    }

    uint32_t t0 = millis();

    for (int gen = 0; gen < GENS; gen++) {
        for (int i = 0; i < POP; i++) fit[i] = fitness(pool[i], grid_seed);
        sort_pop();
        double sum = 0;
        for (int i = 0; i < POP; i++) sum += fit[i];
        fitness(pool[0], grid_seed);  // refresh last_activity_tail
        Serial.printf("gen %2d: best=%.2f mean=%.2f tail=%.3f pal=[%d %d %d %d]\n",
                      gen + 1, fit[0], sum / POP, last_activity_tail,
                      pals[0][0], pals[0][1], pals[0][2], pals[0][3]);

        // Breed bottom half from top half.
        for (int i = POP / 2; i < POP; i++) {
            int pa = (int)(prng() % (POP / 2));
            int pb = (int)(prng() % (POP / 2));
            cross(tmp_genome, pool[pa], pool[pb]);
            mutate(pool[i], tmp_genome, 0.005);
            palette_inherit(pals[i], pals[pa], pals[pb]);
        }
    }

    // Re-score + sort the final pop.
    for (int i = 0; i < POP; i++) fit[i] = fitness(pool[i], grid_seed);
    sort_pop();

    uint32_t elapsed = millis() - t0;
    Serial.printf("=== top %d winners (%.2f s GA) ===\n",
                  WINNERS, elapsed / 1000.0);

    int slot = next_winner_slot();
    for (int w = 0; w < WINNERS; w++) {
        double sum = 0;
        double per[TSEEDS];
        for (int s = 0; s < TSEEDS; s++) {
            per[s] = fitness(pool[w], grid_seed + 100 + s);
            sum += per[s];
        }
        double avg = sum / TSEEDS;

        char path[32] = "(no fs)";
        if (slot > 0) {
            snprintf(path, sizeof path, "/winner_%d.bin", slot);
            write_tail_to_fs(path, pals[w], pool[w]);
            slot++;
        }
        Serial.printf("#%d ga=%.2f avg=%.2f pal=[%d %d %d %d] per=[%.2f %.2f %.2f] -> %s\n  hex: ",
                      w + 1, fit[w], avg,
                      pals[w][0], pals[w][1], pals[w][2], pals[w][3],
                      per[0], per[1], per[2], path);
        emit_hex(pals[w], pool[w]);
    }
    Serial.println("done. press reset to run another hunt.");
}

void loop() {
    delay(5000);
}

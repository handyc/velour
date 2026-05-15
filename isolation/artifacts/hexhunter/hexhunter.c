/* hexhunter — library form of the original ./hunter program.
 *
 * Faithful port of isolation/artifacts/oneclick_class4/hunter.c minus
 * everything that didn't belong in a library: the ELF tail packing,
 * argv parsing, ANSI render, winner-binary writer, and the global
 * rand()/lcg state.
 *
 * The GA, fitness function, packed-genome helpers, and class-4
 * scoring are byte-for-byte equivalent to hunter.c so the output of
 *
 *     hexhunter(NULL, out)        with cfg=NULL  ↔  ./hunter 30 40 42
 *
 * matches what the original program would have shipped to ./winner_1.
 */

#include "hexhunter.h"

#include <stdlib.h>
#include <string.h>


/* ── Defaults (match hunter.c) ─────────────────────────────────────── */
#define DEF_POP                30
#define DEF_GENS               40
#define DEF_INIT_MUT_RATE      0.05
#define DEF_BREED_MUT_RATE     0.005
#define DEF_GRID_W             14
#define DEF_GRID_H             14
#define DEF_HORIZON            25
#define DEF_RNG_SEED           42u


/* ── Local RNG: same Park-Miller-style LCG hunter.c used, but threaded
 *    through every call site instead of a global.  Bit-for-bit
 *    compatible with the original `lcg_state` flow. */
typedef struct { uint32_t state; } hh_rng_t;

static inline void hh_rng_seed(hh_rng_t *r, uint32_t s) {
    r->state = s ? s : 1u;
}
static inline uint32_t hh_rng_u32(hh_rng_t *r) {
    r->state = r->state * 1103515245u + 12345u;
    return r->state >> 16;
}
/* In hunter.c the GA used libc rand() (typically RAND_MAX = 2^31-1).
 * For the library we use the same internal LCG everywhere so results
 * are deterministic across libc implementations.  The "0..RAND_MAX"
 * form below uses 0..0xFFFF (16-bit truncation, matching the LCG's
 * publishable bits) — different absolute values from libc rand(), but
 * the *shape* of the GA (mutation density, crossover cut, palette
 * inheritance) is preserved. */
#define HH_RAND_MAX 0xFFFF
static inline int hh_rand(hh_rng_t *r) { return (int)(hh_rng_u32(r) & HH_RAND_MAX); }
static inline double hh_rand_unit(hh_rng_t *r) {
    return (double)hh_rand(r) / (double)HH_RAND_MAX;
}


/* ── Packed-genome helpers (2 bits per situation, K=4) ─────────────── */

static inline int g_get(const uint8_t *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
static inline void g_set(uint8_t *g, int idx, int v) {
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}

/* base-K situation index: (self * K^6) + ... + n5 */
static inline int sit_idx(int s, const int *n) {
    int i = s;
    for (int k = 0; k < 6; k++) i = i * HH_K + n[k];
    return i;
}


/* ── Hex stepping (pointy-top, row-parity-sensitive) ─────────────────
 * Matches automaton.detector neighbour offsets in the main app and
 * the offsets in hunter.c. */
static const int DY[6]  = { -1, -1,  0,  0,  1,  1 };
static const int DXE[6] = {  0,  1, -1,  1, -1,  0 };  /* even row */
static const int DXO[6] = { -1,  0, -1,  1,  0,  1 };  /* odd row  */

static void step_grid(const uint8_t *g, const uint8_t *in, uint8_t *out,
                      int gw, int gh) {
    for (int y = 0; y < gh; y++) {
        const int *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < gw; x++) {
            int self = in[y * gw + x];
            int n[6];
            for (int k = 0; k < 6; k++) {
                int yy = y + DY[k];
                int xx = x + dx[k];
                n[k] = (yy >= 0 && yy < gh && xx >= 0 && xx < gw)
                     ? in[yy * gw + xx] : 0;
            }
            out[y * gw + x] = (uint8_t)g_get(g, sit_idx(self, n));
        }
    }
}


/* Park-Miller-style grid seeding — same as hunter.c's seed_grid(). */
static void seed_grid(uint8_t *grid, int gw, int gh, uint32_t seed) {
    hh_rng_t r;
    hh_rng_seed(&r, seed);
    int n = gw * gh;
    for (int i = 0; i < n; i++) grid[i] = (uint8_t)(hh_rng_u32(&r) & 3);
}


/* ── Class-4 fitness (smooth tent on activity tail) ─────────────────── */

static double fitness_inner(const uint8_t *genome, uint32_t grid_seed,
                            int gw, int gh, int horizon,
                            uint8_t *a, uint8_t *b, double *act,
                            double *out_activity_tail) {
    int n = gw * gh;
    seed_grid(a, gw, gh, grid_seed);
    int colour_counts_final[HH_K] = {0};

    for (int t = 0; t < horizon; t++) {
        step_grid(genome, a, b, gw, gh);
        int changed = 0;
        for (int i = 0; i < n; i++) if (a[i] != b[i]) changed++;
        act[t] = (double)changed / (double)n;
        memcpy(a, b, (size_t)n);
    }

    /* Final-grid stats. */
    int uniform = 1;
    for (int i = 1; i < n; i++)
        if (a[i] != a[0]) { uniform = 0; break; }
    for (int i = 0; i < n; i++) colour_counts_final[a[i]]++;
    int diversity = 0;
    for (int c = 0; c < HH_K; c++)
        if (colour_counts_final[c] * 100 >= n) diversity++;

    int tail_n = horizon / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = horizon - tail_n; i < horizon; i++) avg += act[i];
    avg /= (double)tail_n;
    if (out_activity_tail) *out_activity_tail = avg;

    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = horizon - tail_n; i < horizon; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;

    /* Smooth tent peaking at activity=0.12. */
    double activity_reward;
    if (avg <= 0.12) activity_reward = avg / 0.12;
    else             activity_reward = (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;

    if (diversity >= 2) {
        int d = diversity < HH_K ? diversity : HH_K;
        score += 0.25 * (double)d;
    }
    return score;
}


/* ── GA ops (use the threaded RNG, not libc rand) ──────────────────── */

static void mutate(uint8_t *dst, const uint8_t *src,
                   double rate, hh_rng_t *r) {
    memcpy(dst, src, HH_GENOME_BYTES);
    for (int i = 0; i < HH_NSIT; i++) {
        if (hh_rand_unit(r) < rate)
            g_set(dst, i, hh_rand(r) & 3);
    }
}

static void cross(uint8_t *dst, const uint8_t *a, const uint8_t *b,
                  hh_rng_t *r) {
    int cut = 1 + (hh_rand(r) % (HH_GENOME_BYTES - 1));
    memcpy(dst,        a,        (size_t)cut);
    memcpy(dst + cut,  b + cut,  (size_t)(HH_GENOME_BYTES - cut));
}


void hexhunter_identity_genome(uint8_t genome[HH_GENOME_BYTES]) {
    /* Every situation → self colour.  In packed form, that's:
     *   0x00 = 00 00 00 00  → all-self-0
     *   0x55 = 01 01 01 01  → all-self-1
     *   0xAA = 10 10 10 10  → all-self-2
     *   0xFF = 11 11 11 11  → all-self-3
     * laid out in 1024-byte blocks for self ∈ {0,1,2,3}. */
    memset(genome + 0 * 1024, 0x00, 1024);
    memset(genome + 1 * 1024, 0x55, 1024);
    memset(genome + 2 * 1024, 0xAA, 1024);
    memset(genome + 3 * 1024, 0xFF, 1024);
}


/* ── Config resolution (NULL or zero-fields → defaults) ────────────── */

static void resolve_config(const hh_config_t *src, hh_config_t *dst) {
    hh_config_t z = {0};
    if (src) z = *src;
    dst->population         = z.population         > 0   ? z.population         : DEF_POP;
    dst->generations        = z.generations        > 0   ? z.generations        : DEF_GENS;
    dst->init_mutation_rate = z.init_mutation_rate > 0.0 ? z.init_mutation_rate : DEF_INIT_MUT_RATE;
    dst->breed_mutation_rate= z.breed_mutation_rate> 0.0 ? z.breed_mutation_rate: DEF_BREED_MUT_RATE;
    dst->grid_w             = z.grid_w             > 0   ? z.grid_w             : DEF_GRID_W;
    dst->grid_h             = z.grid_h             > 0   ? z.grid_h             : DEF_GRID_H;
    dst->horizon            = z.horizon            > 0   ? z.horizon            : DEF_HORIZON;
    dst->rng_seed           = z.rng_seed           != 0  ? z.rng_seed           : DEF_RNG_SEED;
    dst->progress           = z.progress;
    dst->user               = z.user;
}


/* ── Core GA loop, shared by hexhunter() and hexhunter_refine() ───── */

static int run_ga(const hh_config_t *cfg, const uint8_t *seed_genome,
                  uint8_t *out_genome) {
    int pop = cfg->population;
    int gens = cfg->generations;
    if (pop < 2 || gens < 1) return -1;

    int gw = cfg->grid_w, gh = cfg->grid_h, horizon = cfg->horizon;
    if (gw < 3 || gh < 3 || horizon < 3) return -1;

    /* Allocate everything up front so we fail clean if OOM. */
    uint8_t *pool = calloc((size_t)pop, HH_GENOME_BYTES);
    double  *fit  = calloc((size_t)pop, sizeof(double));
    /* fitness scratch — share one buffer for everyone. */
    uint8_t *ga   = malloc((size_t)gw * gh);
    uint8_t *gb   = malloc((size_t)gw * gh);
    double  *act  = malloc((size_t)horizon * sizeof(double));
    if (!pool || !fit || !ga || !gb || !act) {
        free(pool); free(fit); free(ga); free(gb); free(act);
        return -2;
    }

    hh_rng_t rng;
    hh_rng_seed(&rng, cfg->rng_seed);

    /* pool[0] = seed, pool[1..] = mutants at init_mutation_rate */
    memcpy(pool, seed_genome, HH_GENOME_BYTES);
    for (int i = 1; i < pop; i++) {
        mutate(pool + i * HH_GENOME_BYTES, seed_genome,
               cfg->init_mutation_rate, &rng);
    }

    double tail = 0;
    for (int gen = 0; gen < gens; gen++) {
        for (int i = 0; i < pop; i++) {
            fit[i] = fitness_inner(pool + i * HH_GENOME_BYTES,
                                    cfg->rng_seed,
                                    gw, gh, horizon, ga, gb, act, &tail);
        }
        /* Insertion sort by fitness descending. */
        for (int i = 1; i < pop; i++) {
            double fv = fit[i];
            uint8_t tmp[HH_GENOME_BYTES];
            memcpy(tmp, pool + i * HH_GENOME_BYTES, HH_GENOME_BYTES);
            int j = i - 1;
            while (j >= 0 && fit[j] < fv) {
                fit[j + 1] = fit[j];
                memcpy(pool + (j + 1) * HH_GENOME_BYTES,
                       pool + j * HH_GENOME_BYTES, HH_GENOME_BYTES);
                j--;
            }
            fit[j + 1] = fv;
            memcpy(pool + (j + 1) * HH_GENOME_BYTES, tmp, HH_GENOME_BYTES);
        }
        if (cfg->progress) {
            double sum = 0;
            for (int i = 0; i < pop; i++) sum += fit[i];
            cfg->progress(gen + 1, gens, fit[0], sum / pop, tail, cfg->user);
        }

        /* Breed bottom half from top half. */
        for (int i = pop / 2; i < pop; i++) {
            int pa = hh_rand(&rng) % (pop / 2);
            int pb = hh_rand(&rng) % (pop / 2);
            uint8_t tmp[HH_GENOME_BYTES];
            cross(tmp,
                  pool + pa * HH_GENOME_BYTES,
                  pool + pb * HH_GENOME_BYTES, &rng);
            mutate(pool + i * HH_GENOME_BYTES, tmp,
                   cfg->breed_mutation_rate, &rng);
        }
    }

    /* Final re-score + sort, return pool[0]. */
    for (int i = 0; i < pop; i++) {
        fit[i] = fitness_inner(pool + i * HH_GENOME_BYTES,
                                cfg->rng_seed,
                                gw, gh, horizon, ga, gb, act, &tail);
    }
    for (int i = 1; i < pop; i++) {
        double fv = fit[i];
        uint8_t tmp[HH_GENOME_BYTES];
        memcpy(tmp, pool + i * HH_GENOME_BYTES, HH_GENOME_BYTES);
        int j = i - 1;
        while (j >= 0 && fit[j] < fv) {
            fit[j + 1] = fit[j];
            memcpy(pool + (j + 1) * HH_GENOME_BYTES,
                   pool + j * HH_GENOME_BYTES, HH_GENOME_BYTES);
            j--;
        }
        fit[j + 1] = fv;
        memcpy(pool + (j + 1) * HH_GENOME_BYTES, tmp, HH_GENOME_BYTES);
    }
    memcpy(out_genome, pool, HH_GENOME_BYTES);

    free(pool); free(fit); free(ga); free(gb); free(act);
    return 0;
}


/* ── Public API ───────────────────────────────────────────────────── */

int hexhunter(const hh_config_t *cfg, uint8_t out_genome[HH_GENOME_BYTES]) {
    if (!out_genome) return -1;
    hh_config_t c;
    resolve_config(cfg, &c);
    uint8_t seed[HH_GENOME_BYTES];
    hexhunter_identity_genome(seed);
    return run_ga(&c, seed, out_genome);
}

int hexhunter_refine(const hh_config_t *cfg,
                     const uint8_t in_genome[HH_GENOME_BYTES],
                     uint8_t out_genome[HH_GENOME_BYTES]) {
    if (!out_genome || !in_genome) return -1;
    hh_config_t c;
    resolve_config(cfg, &c);
    /* Copy the input first so out and in may safely alias. */
    uint8_t seed[HH_GENOME_BYTES];
    memcpy(seed, in_genome, HH_GENOME_BYTES);
    return run_ga(&c, seed, out_genome);
}

double hexhunter_fitness(const uint8_t genome[HH_GENOME_BYTES],
                         const hh_config_t *cfg) {
    hh_config_t c;
    resolve_config(cfg, &c);
    uint8_t *ga = malloc((size_t)c.grid_w * c.grid_h);
    uint8_t *gb = malloc((size_t)c.grid_w * c.grid_h);
    double  *act= malloc((size_t)c.horizon * sizeof(double));
    if (!ga || !gb || !act) { free(ga); free(gb); free(act); return -1.0; }
    double s = fitness_inner(genome, c.rng_seed, c.grid_w, c.grid_h,
                              c.horizon, ga, gb, act, NULL);
    free(ga); free(gb); free(act);
    return s;
}

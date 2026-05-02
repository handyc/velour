/* HexNN — OpenMP single-node driver for ALICE (20 cores × 4 hours).
 *
 * Lineage: descendant of `cli_linux.c` and the
 * `condenser/distill_hexnn.py:distill_hexnn_esp32s3(with_tft=True)`
 * firmware variant, but stripped of Arduino / WiFi / TFT and
 * specialised for a single-node OpenMP allocation. Same algorithm,
 * same fitness, same wire format for the winner JSON — round-trips
 * back into the /hexnn/ browser bench unchanged.
 *
 * Why driver-level GA? Each call to engine_score_bytes() races on
 * the engine's bin/grid scratch buffers, so engine_run_ga() can't
 * be parallelised in-place. Instead we keep one *master engine*
 * for genome bookkeeping (it owns the population storage) and one
 * *scoring engine per OpenMP thread* (~900 KB each). The hot loop:
 *
 *   #pragma omp parallel for
 *   for i in 0..POP:
 *       fits[i] = engine_score_bytes(scoring_engines[tid], pop[i], gseed)
 *
 *   serial: sort, save elite, breed children via crossover_bytes
 *           + driver-level mutation
 *
 * Time budget instead of a fixed generation count — the GA runs
 * until SECONDS elapse, with a checkpoint every CKPT generations
 * so a Slurm-killed wall-time job still leaves a recoverable
 * winner.json on disk.
 *
 * On ALICE, set --pop $SLURM_CPUS_PER_TASK (default 20) so each
 * core scores one genome per generation. POP can also be an
 * integer multiple to smooth scheduling.
 */

#include "engine.h"

#include <inttypes.h>
#include <omp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ── Defaults — overridable on the command line ─────────────────── */

#define DEFAULT_K           4
#define DEFAULT_N_LOG2      11
#define DEFAULT_W           16
#define DEFAULT_H           16
#define DEFAULT_HORIZON     80
#define DEFAULT_BURN_IN     20
#define DEFAULT_POP         20      /* matches one ALICE node's 20 cores */
#define DEFAULT_RATE_Q16    52      /* ≈ 0.0008 in Q16.16                */
#define DEFAULT_SECONDS     14000   /* 4h ALICE slot - 200 s margin      */
#define DEFAULT_CKPT_GENS   25
#define DEFAULT_OUTPUT      "winner.json"

typedef struct {
    uint32_t K, n_log2, W, H, horizon, burn_in, pop;
    uint32_t rate_q16;
    uint64_t seed;
    double   max_seconds;
    uint32_t ckpt_gens;
    const char *output_path;
    int      verbose;
} args_t;

static int parse_args(int argc, char **argv, args_t *a) {
    a->K = DEFAULT_K; a->n_log2 = DEFAULT_N_LOG2;
    a->W = DEFAULT_W; a->H = DEFAULT_H;
    a->horizon = DEFAULT_HORIZON; a->burn_in = DEFAULT_BURN_IN;
    a->pop = DEFAULT_POP;
    a->rate_q16 = DEFAULT_RATE_Q16;
    a->seed = 0;
    a->max_seconds = DEFAULT_SECONDS;
    a->ckpt_gens = DEFAULT_CKPT_GENS;
    a->output_path = DEFAULT_OUTPUT;
    a->verbose = 0;

    for (int i = 1; i < argc; i++) {
        const char *k = argv[i];
        const char *v = (i + 1 < argc) ? argv[i + 1] : NULL;
        #define EAT_INT(field) do { if (!v) return 1; a->field = (uint32_t)strtoul(v, NULL, 10); i++; } while (0)
        #define EAT_DBL(field) do { if (!v) return 1; a->field = strtod(v, NULL); i++; } while (0)
        if      (!strcmp(k, "--k"))         EAT_INT(K);
        else if (!strcmp(k, "--n-log2"))    EAT_INT(n_log2);
        else if (!strcmp(k, "--grid-w"))    EAT_INT(W);
        else if (!strcmp(k, "--grid-h"))    EAT_INT(H);
        else if (!strcmp(k, "--horizon"))   EAT_INT(horizon);
        else if (!strcmp(k, "--burn-in"))   EAT_INT(burn_in);
        else if (!strcmp(k, "--pop"))       EAT_INT(pop);
        else if (!strcmp(k, "--rate-q16")) EAT_INT(rate_q16);
        else if (!strcmp(k, "--seconds"))   EAT_DBL(max_seconds);
        else if (!strcmp(k, "--ckpt"))      EAT_INT(ckpt_gens);
        else if (!strcmp(k, "--seed"))    { if (!v) return 1; a->seed = strtoull(v, NULL, 0); i++; }
        else if (!strcmp(k, "--output"))  { if (!v) return 1; a->output_path = v; i++; }
        else if (!strcmp(k, "--verbose") || !strcmp(k, "-v")) a->verbose = 1;
        else if (!strcmp(k, "--help") || !strcmp(k, "-h")) {
            return 2;
        }
        else {
            fprintf(stderr, "unknown arg: %s\n", k);
            return 1;
        }
        #undef EAT_INT
        #undef EAT_DBL
    }
    return 0;
}

static void usage(const char *argv0) {
    fprintf(stderr,
        "usage: %s [options]\n"
        "  --k N            colours (default %d)\n"
        "  --n-log2 N       prototype count = 2^N (default %d, max 14)\n"
        "  --grid-w N       grid width (default %d)\n"
        "  --grid-h N       grid height (default %d)\n"
        "  --horizon N      total CA steps per scoring (default %d)\n"
        "  --burn-in N      first N steps don't count (default %d)\n"
        "  --pop N          GA population (default %d, set to # cores)\n"
        "  --rate-q16 N     mutation rate in Q16.16 (default %d ≈ 0.0008)\n"
        "  --seed S         master PRNG seed (default time(NULL))\n"
        "  --seconds T      wall-time budget in seconds (default %d)\n"
        "  --ckpt N         write checkpoint every N gens (default %d)\n"
        "  --output PATH    winner JSON path (default %s)\n"
        "  -v, --verbose    print per-generation stats to stderr\n",
        argv0,
        DEFAULT_K, DEFAULT_N_LOG2, DEFAULT_W, DEFAULT_H,
        DEFAULT_HORIZON, DEFAULT_BURN_IN, DEFAULT_POP,
        DEFAULT_RATE_Q16, DEFAULT_SECONDS, DEFAULT_CKPT_GENS,
        DEFAULT_OUTPUT);
}

/* ── small helpers ────────────────────────────────────────────────── */

static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

/* Deterministic mulberry32 — same generator the engine uses but kept
 * private so the driver-level RNG (mutation, breeding) doesn't
 * disturb the engine's prng state. */
typedef struct { uint32_t s; } drv_rng_t;
static void drv_seed(drv_rng_t *r, uint32_t s) { r->s = s ? s : 1u; }
static uint32_t drv_u32(drv_rng_t *r) {
    r->s = (r->s + 0x6D2B79F5u);
    uint32_t t = r->s;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return (t ^ (t >> 14));
}
static double drv_unit(drv_rng_t *r) {
    return (double)drv_u32(r) / 4294967296.0;
}
static uint32_t drv_mod(drv_rng_t *r, uint32_t n) {
    return (uint32_t)(((uint64_t)drv_u32(r) * (uint64_t)n) >> 32);
}

/* Driver-level mutation: per prototype, with prob `rate` either
 * reassign the output to a fresh random colour or drift one of the
 * 7 keys by ±1 with reflection at the K boundary. Mirrors the
 * engine's internal mutate but operating on raw bytes so we can
 * call it from any thread (the engine's mutate uses its own state).
 *
 * Note: this runs SERIALLY in the breed phase. Parallelising
 * mutation across genomes is a Phase 2 optimisation; at POP=20 and
 * N=2^14 it's already <1% of total wall time. */
static void drv_mutate(uint8_t *genome, uint32_t N, uint32_t K,
                       double rate, drv_rng_t *r) {
    uint8_t *keys = genome;            /* N×7                        */
    uint8_t *outs = genome + (size_t)N * 7u;
    for (uint32_t i = 0; i < N; i++) {
        if (drv_unit(r) >= rate) continue;
        if (drv_unit(r) < 0.5) {
            outs[i] = (uint8_t)drv_mod(r, K);
        } else {
            uint32_t which = drv_mod(r, 7);
            int v = (int)keys[i * 7 + which];
            v += (drv_unit(r) < 0.5) ? -1 : +1;
            if (v < 0)  v = 0;
            if (v >= (int)K) v = (int)K - 1;
            keys[i * 7 + which] = (uint8_t)v;
        }
    }
}

/* ── JSON output (same shape as /hexnn/ winner.json) ───────────────── */

static int write_winner_json(const char *path,
                             uint32_t K, uint32_t n_log2,
                             const uint8_t *keys, const uint8_t *outs,
                             uint32_t N,
                             q16_t fitness, q16_t r,
                             uint32_t generation,
                             double elapsed_s) {
    FILE *f = fopen(path, "w");
    if (!f) { perror(path); return 1; }
    fprintf(f, "{\"format\":\"hexnn-genome-v1\",\"K\":%u,"
               "\"n_entries\":%u,\"source\":\"alice-omp-cli\","
               "\"generation\":%u,\"elapsed_s\":%.2f,"
               "\"fitness_q16\":%u,\"r_q16\":%u,"
               "\"keys\":[",
            K, N, generation, elapsed_s,
            (unsigned)fitness, (unsigned)r);
    for (uint32_t i = 0; i < N; i++) {
        if (i) fputc(',', f);
        fputc('[', f);
        for (int k = 0; k < 7; k++) {
            if (k) fputc(',', f);
            fprintf(f, "%u", keys[i * 7 + k]);
        }
        fputc(']', f);
    }
    fputs("],\"outputs\":[", f);
    for (uint32_t i = 0; i < N; i++) {
        if (i) fputc(',', f);
        fprintf(f, "%u", outs[i]);
    }
    fputs("]}\n", f);
    fclose(f);
    return 0;
}

/* ── main ──────────────────────────────────────────────────────────── */

int main(int argc, char **argv) {
    args_t A;
    int err = parse_args(argc, argv, &A);
    if (err == 2) { usage(argv[0]); return 0; }
    if (err)      { usage(argv[0]); return 2; }
    if (A.seed == 0) A.seed = (uint64_t)time(NULL);
    if (A.pop < 4)   A.pop = 4;
    if (A.pop > 256) A.pop = 256;

    /* ── Build master engine config (used to size genome bytes). ── */
    engine_config_t cfg = {
        .K           = A.K,
        .n_log2      = A.n_log2,
        .grid_w      = A.W,
        .grid_h      = A.H,
        .pop_size    = A.pop,
        .horizon     = A.horizon,
        .burn_in     = A.burn_in,
        .mut_rate_q16 = A.rate_q16,
    };
    size_t need = engine_arena_size(&cfg);
    void *master_arena = malloc(need);
    if (!master_arena) { perror("malloc master"); return 3; }
    engine_t *master = NULL;
    int e = engine_init(&master, master_arena, need, &cfg);
    if (e) { fprintf(stderr, "engine_init master = %d\n", e); return 4; }
    engine_prng_seed(master, (uint32_t)A.seed);

    const uint32_t N = engine_n_entries(master);
    const size_t   gb = engine_genome_bytes(master);

    /* ── Allocate POP genomes side-by-side. The master engine owns
     * its own pop[] buffer too; we use that for crossover scratch but
     * keep our own pop_buf for the parallel-scoring rotation. ── */
    uint8_t *pop_buf = malloc((size_t)A.pop * gb);
    uint8_t *next_buf = malloc((size_t)A.pop * gb);
    q16_t   *fits     = malloc((size_t)A.pop * sizeof(q16_t));
    if (!pop_buf || !next_buf || !fits) {
        perror("malloc pop"); return 5;
    }

    /* Seed initial population: roll a random elite POP times. */
    for (uint32_t i = 0; i < A.pop; i++) {
        engine_make_elite(master);
        memcpy(pop_buf + (size_t)i * gb, engine_elite_bytes(master), gb);
    }

    /* ── Per-thread scoring engines — one per OpenMP thread. ───── */
    int n_threads = omp_get_max_threads();
    engine_config_t score_cfg = cfg;
    score_cfg.pop_size = 2;     /* engine validate_cfg requires ≥2  */
    size_t score_need = engine_arena_size(&score_cfg);
    void **score_arenas = calloc((size_t)n_threads, sizeof(void *));
    engine_t **score_engs = calloc((size_t)n_threads, sizeof(engine_t *));
    if (!score_arenas || !score_engs) { perror("calloc"); return 6; }
    for (int t = 0; t < n_threads; t++) {
        score_arenas[t] = malloc(score_need);
        if (!score_arenas[t]) { perror("score arena"); return 7; }
        e = engine_init(&score_engs[t], score_arenas[t], score_need, &score_cfg);
        if (e) { fprintf(stderr, "engine_init score[%d] = %d\n", t, e); return 8; }
    }

    fprintf(stderr,
        "[hexnn-omp] threads=%d pop=%u N=2^%u K=%u grid=%ux%u "
        "rate_q16=%u seconds=%.0f seed=%" PRIu64 "\n",
        n_threads, A.pop, A.n_log2, A.K, A.W, A.H,
        A.rate_q16, A.max_seconds, A.seed);
    fprintf(stderr,
        "[hexnn-omp] master arena %.1f MB, %d × score arena %.1f MB "
        "(total %.1f MB)\n",
        (double)need / 1048576.0, n_threads,
        (double)score_need / 1048576.0,
        (double)(need + (size_t)n_threads * score_need) / 1048576.0);

    /* ── GA loop with wall-time budget. ─────────────────────────── */
    drv_rng_t drv;
    drv_seed(&drv, (uint32_t)(A.seed ^ 0xDEADBEEFu));

    double t0 = now_seconds();
    uint32_t gen = 0;
    q16_t   best_fit = 0, best_r = 0;
    uint8_t *best_genome = malloc(gb);
    if (!best_genome) { perror("malloc best"); return 9; }
    memcpy(best_genome, pop_buf, gb);

    /* Mutation rate as a probability in [0,1). */
    double mut_rate = (double)A.rate_q16 / 65536.0;

    /* Permutation buffer for sorting; uint16 indices are fine since
     * pop is bounded at 256. */
    uint16_t order[256];

    for (;;) {
        if (now_seconds() - t0 >= A.max_seconds) {
            fprintf(stderr, "[hexnn-omp] wall budget reached at gen %u\n", gen);
            break;
        }

        uint32_t grid_seed = (uint32_t)A.seed + 0xA5A5u + gen;

        /* Parallel score across the population. Each thread uses its
         * own scoring engine — no shared state writes during this. */
        #pragma omp parallel for schedule(dynamic, 1)
        for (int i = 0; i < (int)A.pop; i++) {
            int tid = omp_get_thread_num();
            engine_score_t s = engine_score_bytes(
                score_engs[tid], pop_buf + (size_t)i * gb, grid_seed);
            fits[i] = s.fitness;
        }

        /* Track best across the population + remember its r. */
        uint32_t winner_i = 0;
        for (uint32_t i = 0; i < A.pop; i++) {
            if (fits[i] > best_fit) {
                best_fit = fits[i];
                /* Re-score serially to get r — cheap (one extra
                 * fitness call per improved generation). */
                engine_score_t s = engine_score_bytes(
                    score_engs[0], pop_buf + (size_t)i * gb, grid_seed);
                best_r = s.r;
                memcpy(best_genome, pop_buf + (size_t)i * gb, gb);
                winner_i = i;
            }
        }

        /* Sort indices by fitness desc — selection sort, POP small. */
        for (uint32_t i = 0; i < A.pop; i++) order[i] = (uint16_t)i;
        for (uint32_t i = 0; i < A.pop; i++) {
            for (uint32_t j = i + 1; j < A.pop; j++) {
                if (fits[order[j]] > fits[order[i]]) {
                    uint16_t t = order[i]; order[i] = order[j]; order[j] = t;
                }
            }
        }

        if (A.verbose || (gen % 5 == 0)) {
            double mean = 0;
            for (uint32_t i = 0; i < A.pop; i++) mean += (double)fits[i];
            mean /= (double)A.pop;
            fprintf(stderr,
                "[hexnn-omp] gen %5u  best=%5u  mean=%6.0f  best_so_far=%5u  "
                "winner=%u  elapsed=%.1fs\n",
                gen, (unsigned)fits[order[0]], mean,
                (unsigned)best_fit, winner_i, now_seconds() - t0);
        }

        /* Breed: top 25% survive, rest are crossover children mutated. */
        uint32_t n_surv = A.pop / 4;
        if (n_surv < 2) n_surv = 2;
        for (uint32_t i = 0; i < n_surv; i++) {
            memcpy(next_buf + (size_t)i * gb,
                   pop_buf + (size_t)order[i] * gb, gb);
        }
        for (uint32_t i = n_surv; i < A.pop; i++) {
            uint32_t pa = drv_mod(&drv, n_surv);
            uint32_t pb = drv_mod(&drv, n_surv);
            engine_crossover_bytes(master,
                next_buf + (size_t)i * gb,
                pop_buf  + (size_t)order[pa] * gb,
                pop_buf  + (size_t)order[pb] * gb);
            drv_mutate(next_buf + (size_t)i * gb, N, A.K, mut_rate, &drv);
        }
        memcpy(pop_buf, next_buf, (size_t)A.pop * gb);

        /* Periodic checkpoint so a wall-time kill leaves something. */
        if (gen > 0 && (gen % A.ckpt_gens == 0)) {
            const uint8_t *keys = best_genome;
            const uint8_t *outs = best_genome + (size_t)N * 7u;
            (void)write_winner_json(A.output_path,
                A.K, A.n_log2, keys, outs, N,
                best_fit, best_r, gen, now_seconds() - t0);
        }

        gen++;
    }

    /* Final write. */
    {
        const uint8_t *keys = best_genome;
        const uint8_t *outs = best_genome + (size_t)N * 7u;
        if (write_winner_json(A.output_path,
                A.K, A.n_log2, keys, outs, N,
                best_fit, best_r, gen, now_seconds() - t0) != 0) {
            return 10;
        }
    }
    fprintf(stderr,
        "[hexnn-omp] done — gen %u, best_fit=%u, elapsed=%.1fs, output=%s\n",
        gen, (unsigned)best_fit, now_seconds() - t0, A.output_path);

    /* Cleanup. */
    for (int t = 0; t < n_threads; t++) free(score_arenas[t]);
    free(score_arenas);
    free(score_engs);
    free(master_arena);
    free(pop_buf);
    free(next_buf);
    free(fits);
    free(best_genome);
    return 0;
}

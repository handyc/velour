/* HexNN portable engine — public API.
 *
 * One pure-C99 engine that drivers wrap for every target:
 *   - cli_linux.c       — argv → engine, prints fitness         (HPC seed)
 *   - mpi_islands.c     — MPI ranks = islands                   (planned)
 *   - arduino_s3.cpp    — Arduino-ESP32 wrapper                 (planned)
 *   - wasm_browser.c    — emscripten exports                    (planned)
 *   - selfhost_xcc.c    — xcc700 dialect, no structs/floats     (planned)
 *
 * No platform dependencies in this header or in engine.c — only
 * <stdint.h> and <stddef.h>. The caller provides the memory arena;
 * the engine never calls malloc. All sizing is config-driven so a
 * single binary can scope from K=4 / N=2^11 (S3-equivalent) up to
 * K=256 / N=2^14 (browser default) by passing different config.
 *
 * The algorithm and the wire format track hexnn/genome.py and the
 * /hexnn/ browser bench — same mulberry32 PRNG, same flat-top hex
 * neighbour math, same edge-of-chaos parabola fitness on the K=4-
 * quantized change rate. The Python pi4.py is the human-readable
 * reference; this header + engine.c is the production code.
 */
#ifndef HEXNN_ENGINE_H
#define HEXNN_ENGINE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── Q16.16 fixed-point fitness ────────────────────────────────────── */
/* Real value = q16 / 65536.0. Fitness peaks at 1<<16 (= 1.0). Using
 * fixed-point keeps the engine free of <math.h> and float ops, which
 * matters for xcc700 self-hosting and gives bit-exact reproducibility
 * across architectures with different float rounding modes. */
typedef uint32_t q16_t;
#define Q16_ONE   ((q16_t)0x10000u)

/* ── Engine configuration ──────────────────────────────────────────── */
typedef struct {
    uint32_t K;             /* colours, 2..256                          */
    uint32_t n_log2;        /* prototype count = 1u << n_log2; 8..14    */
    uint32_t grid_w;        /* CA grid width                            */
    uint32_t grid_h;        /* CA grid height                           */
    uint32_t pop_size;      /* GA population (>=4 for tournament)       */
    uint32_t horizon;       /* total CA steps per scoring run           */
    uint32_t burn_in;       /* first N steps don't count toward fitness */
    uint32_t mut_rate_q16;  /* mutation rate in Q16.16 (0..1<<16)       */
} engine_config_t;

/* ── Score outcome ─────────────────────────────────────────────────── */
typedef struct {
    q16_t fitness;          /* 4·r·(1-r) — peaks at r=0.5               */
    q16_t r;                /* mean K=4-quantized change rate           */
} engine_score_t;

/* ── GA mode ───────────────────────────────────────────────────────── */
typedef enum {
    ENGINE_GA_HUNT   = 0,   /* half mutated from elite, half random     */
    ENGINE_GA_REFINE = 1,   /* whole population mutated from elite      */
} engine_ga_mode_t;

/* ── Opaque handle ─────────────────────────────────────────────────── */
typedef struct engine engine_t;

/* ── Sizing ────────────────────────────────────────────────────────── */
/* Caller queries arena size for a config, then provides a buffer of
 * at least that many bytes to engine_init. Returns 0 if cfg is
 * invalid (K out of range, n_log2 out of range, pop_size < 2). */
size_t engine_arena_size(const engine_config_t* cfg);

/* ── Lifecycle ─────────────────────────────────────────────────────── */
/* engine_init lays the engine struct + all working buffers into
 * `arena`. The arena must outlive the engine. Returns 0 on success,
 * nonzero on bad config or undersized arena. */
int  engine_init(engine_t** out, void* arena, size_t arena_bytes,
                 const engine_config_t* cfg);

/* No engine_free — the arena owns the memory; freeing it is the
 * caller's responsibility. The engine has no destructors. */

/* ── PRNG ──────────────────────────────────────────────────────────── */
/* mulberry32, identical to the JS reference at /hexnn/. Seed once
 * before any genome generation; engine_score and engine_run_ga manage
 * their own internal PRNG state for reproducibility. */
void     engine_prng_seed(engine_t* eng, uint32_t seed);
uint32_t engine_prng_u32(engine_t* eng);
q16_t    engine_prng_q16(engine_t* eng);   /* uniform in [0, Q16_ONE)  */

/* ── Genome operations ─────────────────────────────────────────────── */
/* Generate a fresh random genome into the elite slot. Uses the
 * engine's PRNG state, which the caller seeds via engine_prng_seed. */
void engine_make_elite(engine_t* eng);

/* Score the elite on a fresh grid seeded from grid_seed (separate
 * PRNG, so scoring is deterministic given (genome, grid_seed)). */
engine_score_t engine_score_elite(engine_t* eng, uint32_t grid_seed);

/* Run a Hunt-or-Refine GA round. The elite is reused as the seed
 * for the new population; the best individual found becomes the new
 * elite. on_gen, if non-NULL, is called once per generation with
 * (gen_idx, best_fitness, best_r, ctx) — handy for live progress. */
typedef void (*engine_on_gen_t)(uint32_t gen, q16_t best,
                                q16_t r, void* ctx);
engine_score_t engine_run_ga(engine_t* eng,
                             engine_ga_mode_t mode,
                             uint32_t gens,
                             uint32_t hunt_seed,
                             engine_on_gen_t on_gen, void* on_gen_ctx);

/* ── Live runner / read-out ────────────────────────────────────────── */
/* Step the elite's grid one tick. Useful for a wall-clock runner. */
void engine_step_elite(engine_t* eng);

/* Direct pointers into the arena. Stable across all engine calls
 * that don't change config; do NOT free, do NOT memcpy past the
 * documented length. */
const uint8_t* engine_elite_keys(const engine_t* eng); /* len = N*7    */
const uint8_t* engine_elite_outs(const engine_t* eng); /* len = N      */
const uint8_t* engine_grid(const engine_t* eng);       /* grid_w*grid_h */

/* Re-seed the live grid (does not touch the elite). */
void engine_seed_live_grid(engine_t* eng, uint32_t grid_seed);

/* ── Introspection ─────────────────────────────────────────────────── */
const engine_config_t* engine_config(const engine_t* eng);
uint32_t engine_n_entries(const engine_t* eng);   /* 1u << n_log2       */

#ifdef __cplusplus
}
#endif
#endif /* HEXNN_ENGINE_H */

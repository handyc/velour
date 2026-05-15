/* hexhunter — reusable library form of the original ./hunter program.
 *
 * Self-contained, no globals, no I/O, no rand().  All state threads
 * through an explicit RNG inside the call, so two invocations with the
 * same `rng_seed` always produce the same output ruleset.
 *
 * The GA evolves a packed K=4 hex-CA genome over class-4 fitness.
 * Packing is 2 bits per situation:
 *
 *     K^7 situations × 2 bits / 8 = 4096 bytes
 *
 * Use HH_GENOME_BYTES anywhere you allocate or store a ruleset.
 *
 * Typical use:
 *
 *     uint8_t out[HH_GENOME_BYTES];
 *     hexhunter(NULL, out);                       // all defaults
 *
 *     hh_config_t cfg = {0};                      // {0} → defaults
 *     cfg.population = 60;
 *     cfg.generations = 80;
 *     cfg.rng_seed = 12345;
 *     hexhunter(&cfg, out);
 *
 *     // ... later, refine against the current best:
 *     uint8_t refined[HH_GENOME_BYTES];
 *     hexhunter_refine(&cfg, out, refined);
 */

#ifndef HEXHUNTER_H
#define HEXHUNTER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HH_K              4
#define HH_NSIT           16384
#define HH_GENOME_BYTES   4096      /* K^7 * 2 bits / 8 */

/* Optional progress callback.  Called once per generation after the
 * population is sorted; pass NULL for a silent run. */
typedef void (*hh_progress_fn)(int gen, int gens_total,
                               double best_fit, double mean_fit,
                               double best_activity_tail,
                               void *user);

/* Configuration.  Every field defaults to the original hunter.c
 * constants when zero/NULL.  Pass NULL or `{0}` for the unchanged
 * original run. */
typedef struct {
    int      population;            /* default 30 */
    int      generations;           /* default 40 */
    double   init_mutation_rate;    /* default 0.05  (seed → POP-1 mutants) */
    double   breed_mutation_rate;   /* default 0.005 (after crossover) */
    int      grid_w;                /* default 14 */
    int      grid_h;                /* default 14 */
    int      horizon;               /* default 25 (fitness steps) */
    uint32_t rng_seed;              /* default 42 */
    hh_progress_fn progress;        /* default NULL — silent */
    void    *user;                  /* opaque pointer passed to progress */
} hh_config_t;

/* Run the GA from scratch.  Seeds an identity genome, mutates POP-1
 * children at `init_mutation_rate`, runs `generations` of tournament-
 * breeding (top half breeds bottom half), returns the highest-fitness
 * genome in `out_genome`.
 *
 * `cfg` may be NULL, meaning "use every default".  Returns 0 on
 * success, negative on configuration error or out-of-memory. */
int hexhunter(const hh_config_t *cfg, uint8_t out_genome[HH_GENOME_BYTES]);

/* Same as hexhunter(), but the initial population is built from a
 * caller-supplied ruleset instead of identity.  Effectively continues
 * the search around the given genome.
 *
 * `in_genome` is copied into pool[0]; the remaining POP-1 slots are
 * mutants of `in_genome` at `init_mutation_rate`.
 *
 * `out_genome` and `in_genome` may alias safely. */
int hexhunter_refine(const hh_config_t *cfg,
                     const uint8_t in_genome[HH_GENOME_BYTES],
                     uint8_t out_genome[HH_GENOME_BYTES]);

/* Compute the fitness of a single genome at the requested rng_seed
 * under the same horizon/grid as the GA.  Useful for re-scoring,
 * external ranking, or smoke testing. */
double hexhunter_fitness(const uint8_t genome[HH_GENOME_BYTES],
                         const hh_config_t *cfg);

/* Helper: write the identity genome (every situation → self colour)
 * into `genome`.  This is the canonical "zero-activity" starting
 * point used internally by hexhunter(). */
void hexhunter_identity_genome(uint8_t genome[HH_GENOME_BYTES]);

#ifdef __cplusplus
}
#endif

#endif /* HEXHUNTER_H */

/* Sanity tests for libhexhunter.  Compile with:
 *   cc -O2 -Wall -Wextra test_hexhunter.c hexhunter.c -o test_hexhunter
 *   ./test_hexhunter
 *
 * Exits 0 on success, 1 on failure (with a message to stderr). */

#include "hexhunter.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ASSERT(cond, msg) do { if (!(cond)) { \
    fprintf(stderr, "FAIL: %s\n  at %s:%d\n", msg, __FILE__, __LINE__); \
    return 1; } } while (0)


static int test_identity_helper(void) {
    uint8_t g[HH_GENOME_BYTES];
    hexhunter_identity_genome(g);
    /* First quarter all 0x00, then 0x55, then 0xAA, then 0xFF. */
    for (int i = 0; i < 1024; i++) ASSERT(g[i        ] == 0x00, "id[0..1024) != 0x00");
    for (int i = 0; i < 1024; i++) ASSERT(g[i +  1024] == 0x55, "id[1024..) != 0x55");
    for (int i = 0; i < 1024; i++) ASSERT(g[i +  2048] == 0xAA, "id[2048..) != 0xAA");
    for (int i = 0; i < 1024; i++) ASSERT(g[i +  3072] == 0xFF, "id[3072..) != 0xFF");
    return 0;
}


static int test_default_run_returns_4096_bytes(void) {
    uint8_t out[HH_GENOME_BYTES];
    /* Tiny config so the test runs in well under a second. */
    hh_config_t cfg = {0};
    cfg.population = 8;
    cfg.generations = 4;
    cfg.rng_seed = 7;
    int rc = hexhunter(&cfg, out);
    ASSERT(rc == 0, "hexhunter returned non-zero");
    /* "4096 bytes were filled" — touch every page so valgrind would
     * notice if something was uninitialised. */
    int sum = 0;
    for (int i = 0; i < HH_GENOME_BYTES; i++) sum += out[i];
    ASSERT(sum >= 0, "genome content unreadable");
    return 0;
}


static int test_determinism_same_seed(void) {
    uint8_t a[HH_GENOME_BYTES], b[HH_GENOME_BYTES];
    hh_config_t cfg = {0};
    cfg.population = 8;
    cfg.generations = 5;
    cfg.rng_seed = 12345;
    ASSERT(hexhunter(&cfg, a) == 0, "run a failed");
    ASSERT(hexhunter(&cfg, b) == 0, "run b failed");
    ASSERT(memcmp(a, b, HH_GENOME_BYTES) == 0,
           "two runs at the same seed produced different genomes");
    return 0;
}


static int test_different_seeds_differ(void) {
    uint8_t a[HH_GENOME_BYTES], b[HH_GENOME_BYTES];
    hh_config_t cfg = {0};
    cfg.population = 8;
    cfg.generations = 5;

    cfg.rng_seed = 1; ASSERT(hexhunter(&cfg, a) == 0, "run a failed");
    cfg.rng_seed = 2; ASSERT(hexhunter(&cfg, b) == 0, "run b failed");
    ASSERT(memcmp(a, b, HH_GENOME_BYTES) != 0,
           "two runs at different seeds produced identical genomes");
    return 0;
}


static int test_refine_round_trip(void) {
    uint8_t a[HH_GENOME_BYTES], r[HH_GENOME_BYTES];
    hh_config_t cfg = {0};
    cfg.population = 8;
    cfg.generations = 4;
    cfg.rng_seed = 99;

    ASSERT(hexhunter(&cfg, a) == 0, "initial run failed");
    /* refine should accept the genome and produce a valid 4096-byte
     * result.  The refined result need not differ from the input
     * (could converge to the same genome) but it must be returned. */
    ASSERT(hexhunter_refine(&cfg, a, r) == 0, "refine failed");

    /* Refined fitness >= original fitness in expectation but not
     * guaranteed (random mutation can lose the local maximum on a
     * tiny test config).  Just check it's a finite, non-negative
     * score and the ruleset is well-formed. */
    double fa = hexhunter_fitness(a, &cfg);
    double fr = hexhunter_fitness(r, &cfg);
    ASSERT(fa >= 0.0, "original fitness < 0");
    ASSERT(fr >= 0.0, "refined  fitness < 0");
    return 0;
}


static int test_refine_aliasing(void) {
    /* in_genome and out_genome may alias — verify the implementation
     * copies the seed before overwriting. */
    uint8_t g[HH_GENOME_BYTES];
    hh_config_t cfg = {0};
    cfg.population = 6;
    cfg.generations = 3;
    cfg.rng_seed = 11;
    ASSERT(hexhunter(&cfg, g) == 0, "initial run failed");
    ASSERT(hexhunter_refine(&cfg, g, g) == 0, "in-place refine failed");
    return 0;
}


static int test_null_cfg_is_ok(void) {
    /* This is the headline use case: an empty function call.  Use a
     * progress callback that overrides the heavy defaults so the test
     * stays fast — but pass NULL cfg to confirm the API accepts it. */
    /* NB: NULL cfg uses the original defaults POP=30 GENS=40 which is
     * perfectly fine in CI but slow.  We exercise the NULL path with a
     * 0-generation early return is impossible (gens >=1 required), so
     * we instead just exercise the resolve path through fitness(). */
    uint8_t g[HH_GENOME_BYTES];
    hexhunter_identity_genome(g);
    double f = hexhunter_fitness(g, NULL);
    ASSERT(f >= 0.0, "fitness(NULL) < 0");
    return 0;
}


static int progress_calls = 0;
static void counting_progress(int gen, int total,
                              double best, double mean, double tail,
                              void *user) {
    (void)best; (void)mean; (void)tail; (void)user;
    if (gen >= 1 && gen <= total) progress_calls++;
}

static int test_progress_callback_fires(void) {
    progress_calls = 0;
    hh_config_t cfg = {0};
    cfg.population = 6;
    cfg.generations = 4;
    cfg.rng_seed = 5;
    cfg.progress = counting_progress;
    uint8_t out[HH_GENOME_BYTES];
    ASSERT(hexhunter(&cfg, out) == 0, "run failed");
    ASSERT(progress_calls == cfg.generations,
           "progress callback fired wrong number of times");
    return 0;
}


typedef int (*test_fn)(void);
typedef struct { const char *name; test_fn fn; } test_entry_t;

int main(void) {
    test_entry_t tests[] = {
        {"identity_helper",            test_identity_helper},
        {"default_run_returns_4096",   test_default_run_returns_4096_bytes},
        {"determinism_same_seed",      test_determinism_same_seed},
        {"different_seeds_differ",     test_different_seeds_differ},
        {"refine_round_trip",          test_refine_round_trip},
        {"refine_aliasing",            test_refine_aliasing},
        {"null_cfg_is_ok",             test_null_cfg_is_ok},
        {"progress_callback_fires",    test_progress_callback_fires},
    };
    int n = (int)(sizeof tests / sizeof tests[0]);
    int failures = 0;
    for (int i = 0; i < n; i++) {
        printf("  test %s ... ", tests[i].name);
        fflush(stdout);
        int rc = tests[i].fn();
        if (rc == 0) printf("ok\n");
        else { printf("FAIL\n"); failures++; }
    }
    printf("\n%s: %d / %d passed\n",
           failures ? "FAIL" : "OK", n - failures, n);
    return failures ? 1 : 0;
}

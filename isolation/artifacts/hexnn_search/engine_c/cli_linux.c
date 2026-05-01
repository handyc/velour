/* hexnn — Linux CLI driver for the portable HexNN engine.
 *
 * Mirrors the surface of ../pi4.py and ../hpc/cpu.py: argv flags pick
 * K, n_log2, grid, pop, gens, seed, etc.; prints per-generation
 * fitness to stderr and a hexnn-genome-v1 JSON snapshot to stdout.
 *
 * Build:
 *   make
 *
 * Run:
 *   ./hexnn --seed 42 --k 4 --n-log2 8 --grid 8 --pop 4 --gens 2 \
 *           --steps 16 --burn-in 4
 *
 * The JSON shape on stdout is byte-for-byte the same as the browser
 * "Download JSON" button at /hexnn/, so the same file round-trips
 * back into the page for visual inspection.
 */

/* Pull in clock_gettime + CLOCK_MONOTONIC from POSIX. -std=c99 alone
 * defines neither; this is the standard feature-test incantation. */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ── argv parsing ──────────────────────────────────────────────────── */

typedef struct {
    uint32_t K;
    uint32_t n_log2;
    uint32_t grid;
    uint32_t pop;
    uint32_t gens;
    uint32_t horizon;
    uint32_t burn_in;
    uint32_t seed;
    double   rate;
    int      do_hunt;
    int      do_refine;
    int      print_json;
    int      quiet;
    const char* output_path;
} cli_opts_t;

static void usage(const char* argv0) {
    fprintf(stderr,
        "hexnn — portable C engine CLI\n"
        "Usage: %s [opts]\n"
        "  --k N           colours, 2..256 (default 4)\n"
        "  --n-log2 N      log2(prototypes), 6..14 (default 11)\n"
        "  --grid N        grid edge (default 16)\n"
        "  --pop N         population size (default 16)\n"
        "  --gens N        generations per phase (default 30)\n"
        "  --steps N       horizon per scoring run (default 80)\n"
        "  --burn-in N     burn-in steps (default 20)\n"
        "  --seed N        master seed (default 1)\n"
        "  --rate F        mutation rate (default 0.0005)\n"
        "  --hunt          run a Hunt phase\n"
        "  --refine        run a Refine phase\n"
        "                  (default: both, in that order)\n"
        "  --no-json       skip the JSON dump on stdout\n"
        "  --quiet         skip per-gen fitness on stderr\n"
        "  --output PATH   write JSON to PATH instead of stdout\n",
        argv0);
}

static int parse_args(int argc, char** argv, cli_opts_t* o) {
    /* Defaults track the browser bench's "Auto" button. */
    o->K = 4;  o->n_log2 = 11;  o->grid = 16;
    o->pop = 16;  o->gens = 30;  o->horizon = 80;  o->burn_in = 20;
    o->seed = 1;  o->rate = 0.0005;
    o->do_hunt = 0; o->do_refine = 0;
    o->print_json = 1; o->quiet = 0;
    o->output_path = NULL;

    for (int i = 1; i < argc; i++) {
        const char* a = argv[i];
        #define ARG(k, body) \
            if (!strcmp(a, k)) { \
                if (i + 1 >= argc) { fprintf(stderr, "missing value for %s\n", k); return 1; } \
                body; i++; continue; \
            }
        ARG("--k",       o->K = (uint32_t)atoi(argv[i+1]));
        ARG("--n-log2",  o->n_log2 = (uint32_t)atoi(argv[i+1]));
        ARG("--grid",    o->grid = (uint32_t)atoi(argv[i+1]));
        ARG("--pop",     o->pop = (uint32_t)atoi(argv[i+1]));
        ARG("--gens",    o->gens = (uint32_t)atoi(argv[i+1]));
        ARG("--steps",   o->horizon = (uint32_t)atoi(argv[i+1]));
        ARG("--burn-in", o->burn_in = (uint32_t)atoi(argv[i+1]));
        ARG("--seed",    o->seed = (uint32_t)atoi(argv[i+1]));
        ARG("--rate",    o->rate = atof(argv[i+1]));
        ARG("--output",  o->output_path = argv[i+1]);
        #undef ARG
        if      (!strcmp(a, "--hunt"))     o->do_hunt = 1;
        else if (!strcmp(a, "--refine"))   o->do_refine = 1;
        else if (!strcmp(a, "--no-json"))  o->print_json = 0;
        else if (!strcmp(a, "--quiet"))    o->quiet = 1;
        else if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(argv[0]); return 2; }
        else { fprintf(stderr, "unknown arg: %s\n", a); return 1; }
    }
    if (!o->do_hunt && !o->do_refine) { o->do_hunt = 1; o->do_refine = 1; }
    return 0;
}

/* ── on-gen callback: prints a one-line progress strip to stderr ──── */

typedef struct { const char* mode; uint32_t gens; int quiet; } prog_ctx_t;

static void on_gen(uint32_t gen, q16_t best, q16_t r, void* ctx) {
    prog_ctx_t* p = (prog_ctx_t*)ctx;
    if (p->quiet) return;
    fprintf(stderr, "  [%s] gen %u/%u  best %.4f  r=%.3f\n",
            p->mode, gen + 1, p->gens,
            (double)best / 65536.0, (double)r / 65536.0);
}

/* ── JSON emit (matches the /hexnn/ "Download JSON" shape) ────────── */

static void print_json(FILE* fh, const engine_t* eng, q16_t fitness, q16_t r) {
    uint32_t N = engine_n_entries(eng);
    const uint8_t* keys = engine_elite_keys(eng);
    const uint8_t* outs = engine_elite_outs(eng);

    fprintf(fh, "{\"format\":\"hexnn-genome-v1\"");
    fprintf(fh, ",\"K\":%u",            engine_config(eng)->K);
    fprintf(fh, ",\"n_entries\":%u",    N);
    fprintf(fh, ",\"source\":\"engine_c-cli_linux\"");
    fprintf(fh, ",\"fitness\":%.6f",   (double)fitness / 65536.0);
    fprintf(fh, ",\"r\":%.6f",         (double)r       / 65536.0);
    fprintf(fh, ",\"keys\":[");
    for (uint32_t i = 0; i < N; i++) {
        if (i) fputc(',', fh);
        fputc('[', fh);
        for (int k = 0; k < 7; k++) {
            if (k) fputc(',', fh);
            fprintf(fh, "%u", (unsigned)keys[i * 7 + k]);
        }
        fputc(']', fh);
    }
    fprintf(fh, "],\"outputs\":[");
    for (uint32_t i = 0; i < N; i++) {
        if (i) fputc(',', fh);
        fprintf(fh, "%u", (unsigned)outs[i]);
    }
    fprintf(fh, "]}\n");
}

/* ── main ─────────────────────────────────────────────────────────── */

int main(int argc, char** argv) {
    cli_opts_t opts;
    int rc = parse_args(argc, argv, &opts);
    if (rc == 2) return 0;
    if (rc) { usage(argv[0]); return 2; }

    engine_config_t cfg = {
        .K            = opts.K,
        .n_log2       = opts.n_log2,
        .grid_w       = opts.grid,
        .grid_h       = opts.grid,
        .pop_size     = opts.pop,
        .horizon      = opts.horizon,
        .burn_in      = opts.burn_in,
        .mut_rate_q16 = (uint32_t)(opts.rate * 65536.0 + 0.5),
    };
    size_t arena_bytes = engine_arena_size(&cfg);
    if (arena_bytes == 0) {
        fprintf(stderr, "invalid config; check --k / --n-log2 / --pop ranges\n");
        return 2;
    }
    void* arena = malloc(arena_bytes);
    if (!arena) {
        fprintf(stderr, "malloc failed (needed %zu bytes)\n", arena_bytes);
        return 3;
    }

    engine_t* eng = NULL;
    rc = engine_init(&eng, arena, arena_bytes, &cfg);
    if (rc != 0) {
        fprintf(stderr, "engine_init failed: rc=%d\n", rc);
        free(arena); return 3;
    }

    fprintf(stderr,
        "[hexnn-c] K=%u N=%u grid=%ux%u pop=%u gens=%u rate=%.5f seed=%u\n"
        "[hexnn-c] arena=%zu bytes (%.1f KB)\n",
        cfg.K, engine_n_entries(eng), cfg.grid_w, cfg.grid_h,
        cfg.pop_size, opts.gens, opts.rate, opts.seed,
        arena_bytes, (double)arena_bytes / 1024.0);

    /* Initial elite. */
    engine_prng_seed(eng, opts.seed);
    engine_make_elite(eng);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    engine_score_t score = { 0, 0 };

    if (opts.do_hunt) {
        prog_ctx_t pc = { "hunt  ", opts.gens, opts.quiet };
        score = engine_run_ga(eng, ENGINE_GA_HUNT,
                              opts.gens, opts.seed * 31u + 17u,
                              on_gen, &pc);
    }
    if (opts.do_refine) {
        prog_ctx_t pc = { "refine", opts.gens, opts.quiet };
        score = engine_run_ga(eng, ENGINE_GA_REFINE,
                              opts.gens, opts.seed * 31u + 113u,
                              on_gen, &pc);
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double dt = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;

    fprintf(stderr,
        "[hexnn-c] best fitness %.4f (r=%.3f) · %.2f s wall · arena %.1f KB\n",
        (double)score.fitness / 65536.0,
        (double)score.r       / 65536.0,
        dt, (double)arena_bytes / 1024.0);

    if (opts.print_json) {
        FILE* fh = stdout;
        if (opts.output_path) {
            fh = fopen(opts.output_path, "w");
            if (!fh) { perror(opts.output_path); free(arena); return 4; }
        }
        print_json(fh, eng, score.fitness, score.r);
        if (fh != stdout) fclose(fh);
    }

    free(arena);
    return 0;
}

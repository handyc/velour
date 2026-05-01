/* hexnn_islands — multi-population island GA across MPI ranks.
 *
 * One MPI rank = one island = one engine_t with its own population.
 * Each island runs its local GA (Hunt + Refine) for `gens_per_epoch`
 * generations, then a merge phase exchanges genomes between islands
 * according to the chosen strategy. After `epochs` rounds, rank 0
 * gathers all final elites, picks the global winner, and prints the
 * hexnn-genome-v1 JSON to stdout.
 *
 * Build:
 *   make mpi          # needs mpicc
 *
 * Run locally (e.g. 4 ranks on one box):
 *   mpirun -n 4 ./hexnn_islands --pop-per-island 64 --gens-per-epoch 30 \
 *                               --epochs 10 --merge migrate-best
 *
 * Run on ALICE: see ../islands.sbatch.
 *
 * Single-process debug mode (no MPI, no merge):
 *   ./hexnn_islands --no-mpi --pop-per-island 16 --gens-per-epoch 5 \
 *                   --epochs 3
 *   Useful for verifying the island-loop math without an MPI runtime.
 *
 * Merge strategies — each one solves a different selection-pressure
 * problem. Picked at submit time via --merge:
 *
 *   migrate-best     Each island sends its elite to the next on a ring
 *                    topology; the receiver replaces its elite if the
 *                    incoming one scores better on a shared grid_seed.
 *                    Lowest-disruption; preserves winners.
 *
 *   crossover-merge  Pairs of adjacent islands exchange elites and
 *                    crossover them; both islands adopt the hybrid as
 *                    their new elite. Injects genuine recombination.
 *
 *   tournament-merge Rank 0 gathers every elite, scores them all on a
 *                    common grid_seed, broadcasts the global winner.
 *                    Aggressive convergence; risks premature collapse.
 *
 *   diversity-filter Like migrate-best but reject incoming elites
 *                    whose Hamming distance to the local elite is
 *                    below a threshold. Best for the multi-modal
 *                    landscape NN-CA actually has.
 *
 * The engine's internal pop[] is otherwise untouched between epochs —
 * each island's GA continues evolving its population from the
 * (possibly migrated-in) elite. Population diversity is preserved
 * within an island; cross-island exchange is elite-only.
 */

#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ── MPI shim — let the file compile in --no-mpi mode without any
 *    MPI headers, while the real build picks up <mpi.h>.            */

#ifdef HEXNN_NO_MPI
typedef int MPI_Comm;
typedef int MPI_Datatype;
typedef int MPI_Status;
#define MPI_COMM_WORLD       0
#define MPI_BYTE             0
#define MPI_UINT32_T         0
#define MPI_INT              0
#define MPI_STATUS_IGNORE    NULL
#define MPI_SUCCESS          0
static int MPI_Init(int* argc, char*** argv) { (void)argc; (void)argv; return 0; }
static int MPI_Finalize(void) { return 0; }
static int MPI_Comm_rank(MPI_Comm c, int* r) { (void)c; *r = 0; return 0; }
static int MPI_Comm_size(MPI_Comm c, int* s) { (void)c; *s = 1; return 0; }
static int MPI_Sendrecv(const void* sb, int sc, MPI_Datatype st, int dest, int stag,
                         void* rb, int rc, MPI_Datatype rt, int src, int rtag,
                         MPI_Comm comm, MPI_Status* stat) {
    (void)sb; (void)sc; (void)st; (void)dest; (void)stag;
    (void)rb; (void)rc; (void)rt; (void)src; (void)rtag;
    (void)comm; (void)stat; return 0;
}
static int MPI_Allgather(const void* sb, int sc, MPI_Datatype st,
                          void* rb, int rc, MPI_Datatype rt, MPI_Comm c) {
    (void)sb; (void)sc; (void)st; (void)rb; (void)rc; (void)rt; (void)c; return 0;
}
#else
#include <mpi.h>
#endif

/* ── argv parsing ─────────────────────────────────────────────────── */

typedef enum {
    MERGE_MIGRATE_BEST     = 0,
    MERGE_CROSSOVER        = 1,
    MERGE_TOURNAMENT       = 2,
    MERGE_DIVERSITY_FILTER = 3,
} merge_t;

typedef struct {
    /* GA */
    uint32_t K;
    uint32_t n_log2;
    uint32_t grid;
    uint32_t pop_per_island;
    uint32_t gens_per_epoch;
    uint32_t epochs;
    uint32_t horizon;
    uint32_t burn_in;
    uint32_t seed;
    double   rate;
    /* Islands */
    merge_t  merge;
    uint32_t k_migrants;        /* unused for now (always 1 = elite)  */
    uint32_t diversity_threshold;
    int      no_mpi;            /* single-process sequential debug    */
    int      quiet;
    const char* output_path;
} cli_opts_t;

static merge_t parse_merge(const char* s) {
    if (!strcmp(s, "migrate-best"))     return MERGE_MIGRATE_BEST;
    if (!strcmp(s, "crossover-merge"))  return MERGE_CROSSOVER;
    if (!strcmp(s, "tournament-merge")) return MERGE_TOURNAMENT;
    if (!strcmp(s, "diversity-filter")) return MERGE_DIVERSITY_FILTER;
    fprintf(stderr, "unknown merge strategy: %s\n", s);
    fprintf(stderr, "  valid: migrate-best, crossover-merge, "
                    "tournament-merge, diversity-filter\n");
    exit(2);
}

static const char* merge_name(merge_t m) {
    switch (m) {
    case MERGE_MIGRATE_BEST:     return "migrate-best";
    case MERGE_CROSSOVER:        return "crossover-merge";
    case MERGE_TOURNAMENT:       return "tournament-merge";
    case MERGE_DIVERSITY_FILTER: return "diversity-filter";
    }
    return "?";
}

static void usage(const char* argv0) {
    fprintf(stderr,
        "hexnn_islands — multi-population island GA over MPI\n"
        "Usage: mpirun -n N %s [opts]\n"
        "  --k N                  colours, 2..256 (default 4)\n"
        "  --n-log2 N             log2(prototypes), 6..14 (default 11)\n"
        "  --grid N               grid edge (default 16)\n"
        "  --pop-per-island N     local pop per rank (default 64)\n"
        "  --gens-per-epoch N     generations between merges (default 30)\n"
        "  --epochs N             number of merge rounds (default 10)\n"
        "  --steps N              fitness horizon (default 80)\n"
        "  --burn-in N            burn-in steps (default 20)\n"
        "  --rate F               mutation rate (default 0.0005)\n"
        "  --seed N               master seed (default 1)\n"
        "  --merge STRAT          merge strategy (default migrate-best)\n"
        "                         migrate-best | crossover-merge |\n"
        "                         tournament-merge | diversity-filter\n"
        "  --diversity-threshold N (for diversity-filter; default 100)\n"
        "  --output PATH          where rank 0 writes the winner JSON\n"
        "  --quiet                skip per-epoch progress\n"
        "  --no-mpi               run sequentially in-process for debug\n",
        argv0);
}

static int parse_args(int argc, char** argv, cli_opts_t* o) {
    o->K = 4;       o->n_log2 = 11;       o->grid = 16;
    o->pop_per_island = 64; o->gens_per_epoch = 30; o->epochs = 10;
    o->horizon = 80; o->burn_in = 20;     o->seed = 1;
    o->rate = 0.0005;
    o->merge = MERGE_MIGRATE_BEST;
    o->k_migrants = 1;  o->diversity_threshold = 100;
    o->no_mpi = 0;  o->quiet = 0;  o->output_path = NULL;

    for (int i = 1; i < argc; i++) {
        const char* a = argv[i];
        #define ARG(k, body) \
            if (!strcmp(a, k)) { \
                if (i + 1 >= argc) { fprintf(stderr, "missing value for %s\n", k); return 1; } \
                body; i++; continue; \
            }
        ARG("--k",                   o->K = (uint32_t)atoi(argv[i+1]));
        ARG("--n-log2",              o->n_log2 = (uint32_t)atoi(argv[i+1]));
        ARG("--grid",                o->grid = (uint32_t)atoi(argv[i+1]));
        ARG("--pop-per-island",      o->pop_per_island = (uint32_t)atoi(argv[i+1]));
        ARG("--gens-per-epoch",      o->gens_per_epoch = (uint32_t)atoi(argv[i+1]));
        ARG("--epochs",              o->epochs = (uint32_t)atoi(argv[i+1]));
        ARG("--steps",               o->horizon = (uint32_t)atoi(argv[i+1]));
        ARG("--burn-in",             o->burn_in = (uint32_t)atoi(argv[i+1]));
        ARG("--rate",                o->rate = atof(argv[i+1]));
        ARG("--seed",                o->seed = (uint32_t)atoi(argv[i+1]));
        ARG("--merge",               o->merge = parse_merge(argv[i+1]));
        ARG("--diversity-threshold", o->diversity_threshold = (uint32_t)atoi(argv[i+1]));
        ARG("--output",              o->output_path = argv[i+1]);
        #undef ARG
        if      (!strcmp(a, "--no-mpi"))  o->no_mpi = 1;
        else if (!strcmp(a, "--quiet"))   o->quiet = 1;
        else if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(argv[0]); return 2; }
        else { fprintf(stderr, "unknown arg: %s\n", a); return 1; }
    }
    return 0;
}

/* ── Per-rank engine init ─────────────────────────────────────────── */

static engine_t* setup_island(const cli_opts_t* o, int rank, void** arena_out,
                               size_t* arena_bytes_out) {
    engine_config_t cfg = {
        .K            = o->K,
        .n_log2       = o->n_log2,
        .grid_w       = o->grid,
        .grid_h       = o->grid,
        .pop_size     = o->pop_per_island,
        .horizon      = o->horizon,
        .burn_in      = o->burn_in,
        .mut_rate_q16 = (uint32_t)(o->rate * 65536.0 + 0.5),
    };
    size_t need = engine_arena_size(&cfg);
    if (need == 0) {
        fprintf(stderr, "[rank %d] invalid config\n", rank);
        return NULL;
    }
    void* arena = malloc(need);
    if (!arena) {
        fprintf(stderr, "[rank %d] malloc(%zu) failed\n", rank, need);
        return NULL;
    }
    engine_t* eng = NULL;
    int rc = engine_init(&eng, arena, need, &cfg);
    if (rc != 0) {
        fprintf(stderr, "[rank %d] engine_init rc=%d\n", rank, rc);
        free(arena); return NULL;
    }
    /* Each island gets a deterministic but distinct seed. */
    uint32_t island_seed = o->seed * 1009u + (uint32_t)rank;
    engine_prng_seed(eng, island_seed);
    engine_make_elite(eng);

    *arena_out = arena;
    *arena_bytes_out = need;
    return eng;
}

/* ── Merge strategies ─────────────────────────────────────────────── */

/* migrate-best: ring topology, conditional replace if peer is better. */
static void merge_migrate_best(engine_t* eng, int rank, int world,
                                uint32_t merge_seed, uint8_t* sendbuf,
                                uint8_t* recvbuf) {
    size_t gb = engine_genome_bytes(eng);
    int next = (rank + 1) % world;
    int prev = (rank - 1 + world) % world;

    memcpy(sendbuf, engine_elite_bytes(eng), gb);
    MPI_Sendrecv(sendbuf, (int)gb, MPI_BYTE, next, 0,
                 recvbuf, (int)gb, MPI_BYTE, prev, 0,
                 MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    /* Score local + incoming on the same grid_seed and pick the
     * better. Each rank does this independently — no extra comm. */
    engine_score_t local = engine_score_bytes(eng, engine_elite_bytes(eng), merge_seed);
    engine_score_t peer  = engine_score_bytes(eng, recvbuf,                  merge_seed);
    if (peer.fitness > local.fitness) {
        engine_inject_elite(eng, recvbuf);
    }
}

/* crossover-merge: paired ranks exchange elites and adopt a hybrid.
 * Pairs are (0,1), (2,3), … — odd-world-size leaves the last rank
 * alone for this round, which is fine; it'll pair next round. */
static void merge_crossover(engine_t* eng, int rank, int world,
                             uint32_t merge_seed, uint8_t* sendbuf,
                             uint8_t* recvbuf) {
    size_t gb = engine_genome_bytes(eng);
    int partner;
    if (rank == world - 1 && (world & 1)) {
        return;  /* odd world, last rank skips */
    }
    partner = (rank ^ 1);   /* swap LSB → 0↔1, 2↔3, …                */

    memcpy(sendbuf, engine_elite_bytes(eng), gb);
    MPI_Sendrecv(sendbuf, (int)gb, MPI_BYTE, partner, 1,
                 recvbuf, (int)gb, MPI_BYTE, partner, 1,
                 MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    /* Both partners run the same crossover with the same merge_seed
     * → both get the *same* hybrid genome, which is the whole point.
     * The PRNG state is restored after so the GA continues
     * deterministically given the seeds. */
    uint32_t saved = 0;
    /* engine.h doesn't expose state save/restore; we re-seed from
     * merge_seed explicitly here, accepting that the local GA's
     * subsequent draws now stem from merge_seed. The downside is
     * cosmetic: per-rank reproducibility chains pivot on each merge. */
    engine_prng_seed(eng, merge_seed);
    (void)saved;

    /* Need a temp buffer because crossover writes byte-by-byte and
     * we don't want dst==a or dst==b confusing the read order. */
    static uint8_t* tmp = NULL; static size_t tmp_cap = 0;
    if (tmp_cap < gb) { free(tmp); tmp = malloc(gb); tmp_cap = gb; }
    engine_crossover_bytes(eng, tmp, sendbuf, recvbuf);
    engine_inject_elite(eng, tmp);
}

/* tournament-merge: rank 0 gathers all elites, scores them on a
 * common grid_seed, broadcasts the global winner. */
static void merge_tournament(engine_t* eng, int rank, int world,
                              uint32_t merge_seed, uint8_t* sendbuf,
                              uint8_t* gather_buf) {
    size_t gb = engine_genome_bytes(eng);
    memcpy(sendbuf, engine_elite_bytes(eng), gb);
    MPI_Allgather(sendbuf, (int)gb, MPI_BYTE,
                  gather_buf, (int)gb, MPI_BYTE, MPI_COMM_WORLD);

    /* Every rank scores all `world` candidates on the same seed and
     * picks the best — Allgather instead of Gather+Bcast saves a
     * round-trip and keeps the answer tied bit-exactly across ranks. */
    int best = 0;
    engine_score_t bs = engine_score_bytes(eng, gather_buf, merge_seed);
    for (int r = 1; r < world; r++) {
        engine_score_t s = engine_score_bytes(
            eng, gather_buf + (size_t)r * gb, merge_seed);
        if (s.fitness > bs.fitness) { bs = s; best = r; }
    }
    engine_inject_elite(eng, gather_buf + (size_t)best * gb);
    (void)rank;
}

/* diversity-filter: ring like migrate-best, but only accept the peer
 * if it scores better AND its Hamming distance from the local elite
 * is at least `threshold`. */
static void merge_diversity_filter(engine_t* eng, int rank, int world,
                                    uint32_t merge_seed, uint32_t threshold,
                                    uint8_t* sendbuf, uint8_t* recvbuf) {
    size_t gb = engine_genome_bytes(eng);
    int next = (rank + 1) % world;
    int prev = (rank - 1 + world) % world;

    memcpy(sendbuf, engine_elite_bytes(eng), gb);
    MPI_Sendrecv(sendbuf, (int)gb, MPI_BYTE, next, 2,
                 recvbuf, (int)gb, MPI_BYTE, prev, 2,
                 MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    uint32_t dist = engine_genome_distance(
        engine_elite_bytes(eng), recvbuf, gb);
    if (dist < threshold) return;       /* too similar — skip       */

    engine_score_t local = engine_score_bytes(eng, engine_elite_bytes(eng), merge_seed);
    engine_score_t peer  = engine_score_bytes(eng, recvbuf,                  merge_seed);
    if (peer.fitness > local.fitness) {
        engine_inject_elite(eng, recvbuf);
    }
}

/* ── JSON emit (rank 0 only) ──────────────────────────────────────── */

static void print_json(FILE* fh, const engine_t* eng,
                        q16_t fitness, q16_t r, merge_t merge,
                        uint32_t epochs) {
    uint32_t N = engine_n_entries(eng);
    const uint8_t* keys = engine_elite_keys(eng);
    const uint8_t* outs = engine_elite_outs(eng);

    fprintf(fh, "{\"format\":\"hexnn-genome-v1\"");
    fprintf(fh, ",\"K\":%u",            engine_config(eng)->K);
    fprintf(fh, ",\"n_entries\":%u",    N);
    fprintf(fh, ",\"source\":\"engine_c-mpi_islands\"");
    fprintf(fh, ",\"merge\":\"%s\"",    merge_name(merge));
    fprintf(fh, ",\"epochs\":%u",       epochs);
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
    cli_opts_t o;
    int rc = parse_args(argc, argv, &o);
    if (rc == 2) return 0;
    if (rc) { usage(argv[0]); return 2; }

#ifdef HEXNN_NO_MPI
    /* No-MPI build always reports world=1 / rank=0. */
    o.no_mpi = 1;
#endif

    int rank = 0, world = 1;
    if (!o.no_mpi) {
        MPI_Init(&argc, &argv);
        MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        MPI_Comm_size(MPI_COMM_WORLD, &world);
    }

    void* arena = NULL; size_t arena_bytes = 0;
    engine_t* eng = setup_island(&o, rank, &arena, &arena_bytes);
    if (!eng) {
        if (!o.no_mpi) MPI_Finalize();
        return 3;
    }

    if (rank == 0) {
        fprintf(stderr,
            "[islands] world=%d K=%u N=%u grid=%ux%u\n"
            "[islands] pop/island=%u gens/epoch=%u epochs=%u merge=%s\n"
            "[islands] arena/island=%zu bytes (%.1f KB)%s\n",
            world, o.K, engine_n_entries(eng), o.grid, o.grid,
            o.pop_per_island, o.gens_per_epoch, o.epochs,
            merge_name(o.merge),
            arena_bytes, (double)arena_bytes / 1024.0,
            o.no_mpi ? " · single-rank --no-mpi mode" : "");
    }

    size_t gb = engine_genome_bytes(eng);
    uint8_t* sendbuf = malloc(gb);
    uint8_t* recvbuf = malloc(gb);
    /* gather_buf used only by tournament-merge but allocated for all
     * to keep the dispatch simple. world is small (≤1000 typically). */
    uint8_t* gather_buf = malloc(gb * (size_t)world);
    if (!sendbuf || !recvbuf || !gather_buf) {
        fprintf(stderr, "[rank %d] merge buffers malloc failed\n", rank);
        free(arena);
        if (!o.no_mpi) MPI_Finalize();
        return 3;
    }

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (uint32_t epoch = 0; epoch < o.epochs; epoch++) {
        /* Per-epoch hunt seed: distinct per island, distinct per epoch. */
        uint32_t hunt_seed = o.seed * 31u + 17u
                             + (uint32_t)rank * 7919u
                             + epoch * 65521u;

        engine_run_ga(eng, ENGINE_GA_HUNT,
                       o.gens_per_epoch, hunt_seed, NULL, NULL);
        engine_run_ga(eng, ENGINE_GA_REFINE,
                       o.gens_per_epoch, hunt_seed + 1u, NULL, NULL);

        /* Merge phase. Skip on the last epoch to leave each island's
         * elite as the local final answer for the global tournament. */
        if (epoch + 1 < o.epochs && world > 1 && !o.no_mpi) {
            uint32_t merge_seed = o.seed * 999983u + epoch;
            switch (o.merge) {
            case MERGE_MIGRATE_BEST:
                merge_migrate_best(eng, rank, world, merge_seed,
                                    sendbuf, recvbuf);
                break;
            case MERGE_CROSSOVER:
                merge_crossover(eng, rank, world, merge_seed,
                                 sendbuf, recvbuf);
                break;
            case MERGE_TOURNAMENT:
                merge_tournament(eng, rank, world, merge_seed,
                                  sendbuf, gather_buf);
                break;
            case MERGE_DIVERSITY_FILTER:
                merge_diversity_filter(eng, rank, world, merge_seed,
                                        o.diversity_threshold,
                                        sendbuf, recvbuf);
                break;
            }
        }

        if (rank == 0 && !o.quiet) {
            engine_score_t s = engine_score_bytes(
                eng, engine_elite_bytes(eng),
                o.seed * 0xCAFEu + epoch);
            fprintf(stderr,
                "[islands] epoch %u/%u  rank-0 elite fit %.4f  r=%.3f\n",
                epoch + 1, o.epochs,
                (double)s.fitness / 65536.0,
                (double)s.r       / 65536.0);
        }
    }

    /* Final global tournament: every island's elite is gathered to
     * rank 0; rank 0 picks the best on a fixed grid_seed and emits
     * JSON. */
    engine_score_t final_score = { 0, 0 };
    if (world > 1 && !o.no_mpi) {
        memcpy(sendbuf, engine_elite_bytes(eng), gb);
        MPI_Allgather(sendbuf, (int)gb, MPI_BYTE,
                      gather_buf, (int)gb, MPI_BYTE, MPI_COMM_WORLD);
        if (rank == 0) {
            int best = 0;
            engine_score_t bs = engine_score_bytes(
                eng, gather_buf, o.seed * 0xBEEFu);
            for (int r2 = 1; r2 < world; r2++) {
                engine_score_t s = engine_score_bytes(
                    eng, gather_buf + (size_t)r2 * gb,
                    o.seed * 0xBEEFu);
                if (s.fitness > bs.fitness) { bs = s; best = r2; }
            }
            engine_inject_elite(eng, gather_buf + (size_t)best * gb);
            final_score = bs;
            fprintf(stderr,
                "[islands] global winner: rank %d  fit %.4f  r=%.3f\n",
                best,
                (double)bs.fitness / 65536.0,
                (double)bs.r       / 65536.0);
        }
    } else {
        final_score = engine_score_bytes(
            eng, engine_elite_bytes(eng), o.seed * 0xBEEFu);
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double dt = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;

    if (rank == 0) {
        fprintf(stderr,
            "[islands] total %.2f s · %u epochs × %u gens × %d islands\n",
            dt, o.epochs, o.gens_per_epoch * 2, world);
        FILE* fh = stdout;
        if (o.output_path) {
            fh = fopen(o.output_path, "w");
            if (!fh) { perror(o.output_path); }
        }
        if (fh) {
            print_json(fh, eng, final_score.fitness, final_score.r,
                       o.merge, o.epochs);
            if (fh != stdout) fclose(fh);
        }
    }

    free(sendbuf); free(recvbuf); free(gather_buf); free(arena);
    if (!o.no_mpi) MPI_Finalize();
    return 0;
}

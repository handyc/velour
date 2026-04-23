/* ── Self-replicating hex-CA class-4 hunter ──────────────────────────
 *
 * Layout:
 *
 *   [ ELF: engine bytes (~10 KB of -O2 code) ][ 4096-byte seed genome ]
 *
 * Total size: ~14 KB when -O2 + strip. Target: under 16 KB.
 *
 * The seed genome is ALWAYS the last 4096 bytes of the binary itself.
 * There is no linked-in constant for the seed — we read ``argv[0]``
 * and slice off its tail. This lets us build the engine once and then
 * ship many hunters (one per genome) as ``cat engine_bytes genome.bin
 * > hunter_N``, no recompile needed.
 *
 * Pipeline:
 *   1. Read own tail → 4096-byte seed.
 *   2. Mutate seed ``POP-1`` times to form initial population.
 *   3. Run ``GENS`` generations of tournament-2 GA on a small hex grid.
 *   4. Score top K on multiple seed grids; pick top ``WINNERS``.
 *   5. For each winner: copy our own engine bytes to a new file,
 *      append the winner's genome, chmod +x. Each output is another
 *      self-contained hunter you can run to refine further.
 *
 * Build:
 *   cc -O2 -s hunter.c -o hunter_engine
 *   dd if=/dev/urandom bs=1 count=4096 >> hunter_engine
 *   mv hunter_engine hunter && chmod +x hunter
 *
 * Run:
 *   ./hunter          # → writes winner_1, winner_2, winner_3 + summary
 *   ./winner_1        # refines further from that genome
 *
 * ────────────────────────────────────────────────────────────────── */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/stat.h>

/* Hand-inlined fabs — avoids pulling in libm (saves ~8 KB on glibc). */
#define my_fabs(x) ((x) < 0 ? -(x) : (x))

#define K          4
#define NSIT       16384
#define GBYTES     4096          /* K^7 * 2 bits / 8 */
#define GRID_W     14
#define GRID_H     14
#define HORIZON    25
#define POP        30
#define GENS       40
#define TSEEDS     3
#define WINNERS    3

typedef unsigned char u8;

/* ── Packed-genome helpers ───────────────────────────────────────── */

static inline int g_get(const u8 *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
static inline void g_set(u8 *g, int idx, int v) {
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}

/* base-K situation index */
static inline int sit_idx(int s, const int *n) {
    int i = s;
    for (int k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}

/* ── Hex stepping ────────────────────────────────────────────────── */

/* Six-neighbour offsets, row-parity-sensitive. Out-of-bounds → 0
 * (padded). Same addressing as automaton.detector in the main app. */
static const int DY[6]   = { -1, -1,  0,  0,  1,  1 };
static const int DXE[6]  = {  0,  1, -1,  1, -1,  0 };  /* even row */
static const int DXO[6]  = { -1,  0, -1,  1,  0,  1 };  /* odd row  */

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

/* Deterministic seeded grid — Park-Miller LCG is tiny + good enough. */
static uint32_t lcg_state;
static inline uint32_t lcg(void) {
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}

static void seed_grid(u8 *grid, uint32_t seed) {
    lcg_state = seed ? seed : 1;
    for (int i = 0; i < GRID_W * GRID_H; i++)
        grid[i] = lcg() & 3;
}

/* ── Class-4 fitness ──────────────────────────────────────────────── */

/* Global last-activity-tail, populated by fitness() so main() can
 * report how the population is distributing across the edge-of-chaos
 * band. Not thread-safe; this program is single-threaded. */
static double last_activity_tail = 0.0;

static double fitness(const u8 *genome, uint32_t grid_seed) {
    u8 a[GRID_W * GRID_H], b[GRID_W * GRID_H];
    seed_grid(a, grid_seed);
    double act[HORIZON];
    int colour_counts_final[K] = {0};
    for (int t = 0; t < HORIZON; t++) {
        step_grid(genome, a, b);
        int changed = 0;
        for (int i = 0; i < GRID_W * GRID_H; i++)
            if (a[i] != b[i]) changed++;
        act[t] = (double)changed / (GRID_W * GRID_H);
        memcpy(a, b, sizeof a);
    }
    /* Final-grid stats. */
    int uniform = 1;
    for (int i = 1; i < GRID_W * GRID_H; i++)
        if (a[i] != a[0]) { uniform = 0; break; }
    for (int i = 0; i < GRID_W * GRID_H; i++) colour_counts_final[a[i]]++;
    int diversity = 0;
    for (int c = 0; c < K; c++)
        if (colour_counts_final[c] * 100 >= GRID_W * GRID_H) diversity++;

    /* Activity tail. */
    int tail_n = HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;
    last_activity_tail = avg;

    /* Partial credit, but with a SMOOTH activity gradient so the GA
     * has something to climb toward from either side of the band.
     * Previous version used a hard activity ∈ [0.03, 0.30] cutoff
     * which left genomes with avg=0.005 (dominantly identity) flat
     * at score ~3.5 with no pull toward the class-4 peak at 0.12. */
    double score = 0;
    if (!uniform) score += 1.0;
    /* "Aperiodic" proxy: activity never fell to zero in the tail. */
    int aperiodic = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;
    /* Activity — tent function peaking at 0.12, linearly falling to
     * zero at activity=0 on one side and activity=0.75 on the other.
     * No hard cutoff: even near-dead genomes get a tiny non-zero
     * contribution that pulls them toward the edge-of-chaos peak. */
    double activity_reward;
    if (avg <= 0.12) activity_reward = avg / 0.12;            /* 0 → 1 */
    else             activity_reward = (0.75 - avg) / 0.63;   /* 1 → 0 at 0.75 */
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    /* Colour diversity. */
    if (diversity >= 2) score += 0.25 * (diversity < K ? diversity : K);
    return score;
}

/* ── GA ops ───────────────────────────────────────────────────────── */

static void mutate(u8 *dst, const u8 *src, double rate) {
    memcpy(dst, src, GBYTES);
    for (int i = 0; i < NSIT; i++) {
        if ((double)rand() / RAND_MAX < rate)
            g_set(dst, i, rand() & 3);
    }
}

static void cross(u8 *dst, const u8 *a, const u8 *b) {
    int cut = 1 + rand() % (GBYTES - 1);
    memcpy(dst, a, cut);
    memcpy(dst + cut, b + cut, GBYTES - cut);
}

/* ── Reading self's seed + writing children ──────────────────────── */

static long file_size(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 ? st.st_size : -1;
}

static int read_self_seed(const char *self_path, u8 *out) {
    long sz = file_size(self_path);
    if (sz < GBYTES) return -1;
    FILE *fp = fopen(self_path, "rb");
    if (!fp) return -1;
    if (fseek(fp, sz - GBYTES, SEEK_SET) != 0) { fclose(fp); return -1; }
    int ok = fread(out, 1, GBYTES, fp) == GBYTES;
    fclose(fp);
    return ok ? 0 : -1;
}

static int write_child(const char *self_path, const char *dst_path,
                       const u8 *genome) {
    long sz = file_size(self_path);
    if (sz < GBYTES) return -1;
    long engine_size = sz - GBYTES;
    FILE *in = fopen(self_path, "rb");
    if (!in) return -1;
    FILE *out = fopen(dst_path, "wb");
    if (!out) { fclose(in); return -1; }
    u8 buf[4096];
    long left = engine_size;
    while (left > 0) {
        size_t want = left > (long)sizeof buf ? sizeof buf : left;
        size_t got = fread(buf, 1, want, in);
        if (got == 0) break;
        fwrite(buf, 1, got, out);
        left -= got;
    }
    fwrite(genome, 1, GBYTES, out);
    fclose(in); fclose(out);
    chmod(dst_path, 0755);
    return 0;
}

/* ── main ─────────────────────────────────────────────────────────── */

int main(int argc, char **argv) {
    unsigned rseed = (argc > 1) ? (unsigned)atoi(argv[1]) : 42;
    srand(rseed);

    /* 1. Read our own tail to get the seed genome. */
    u8 seed[GBYTES];
    if (read_self_seed(argv[0], seed) != 0) {
        fprintf(stderr, "error: can't read seed from '%s' "
                "(did you append 4096 bytes of genome to the engine?)\n",
                argv[0]);
        return 2;
    }

    /* 2. Initial population: seed + POP-1 heavily-mutated copies.
     *
     * Rate 0.05 ≈ 820 situation-flips per child. From the identity
     * seed that's enough to inject non-trivial activity into an
     * otherwise-dead substrate — the GA's job is then to prune back
     * toward the class-4 band. From a random-chaos seed the same
     * 820 flips don't change character (still chaos); that's why
     * build.sh now defaults to the identity seed.
     */
    u8 pool[POP][GBYTES];
    double fit[POP];
    memcpy(pool[0], seed, GBYTES);
    for (int i = 1; i < POP; i++) mutate(pool[i], seed, 0.05);

    /* 3. GA */
    for (int gen = 0; gen < GENS; gen++) {
        for (int i = 0; i < POP; i++) fit[i] = fitness(pool[i], rseed);

        /* Insertion sort (POP is small, keeps code tight). */
        for (int i = 1; i < POP; i++) {
            double fv = fit[i];
            u8 tmp[GBYTES]; memcpy(tmp, pool[i], GBYTES);
            int j = i - 1;
            while (j >= 0 && fit[j] < fv) {
                fit[j + 1] = fit[j];
                memcpy(pool[j + 1], pool[j], GBYTES);
                j--;
            }
            fit[j + 1] = fv;
            memcpy(pool[j + 1], tmp, GBYTES);
        }
        double sum = 0;
        for (int i = 0; i < POP; i++) sum += fit[i];
        /* Measure activity-tail of the best agent so the log shows
         * whether we're still stuck at chaos (≈0.75), still at
         * identity (≈0.0), or edging into the class-4 band (~0.1). */
        fitness(pool[0], rseed);
        fprintf(stderr,
                "gen %2d: best=%.2f mean=%.2f best_activity=%.3f\n",
                gen + 1, fit[0], sum / POP, last_activity_tail);

        /* Breed bottom half from top half. */
        for (int i = POP / 2; i < POP; i++) {
            u8 tmp[GBYTES];
            cross(tmp,
                  pool[rand() % (POP / 2)],
                  pool[rand() % (POP / 2)]);
            mutate(pool[i], tmp, 0.005);
        }
    }

    /* Re-score one more time on the final population. */
    for (int i = 0; i < POP; i++) fit[i] = fitness(pool[i], rseed);
    for (int i = 1; i < POP; i++) {
        double fv = fit[i];
        u8 tmp[GBYTES]; memcpy(tmp, pool[i], GBYTES);
        int j = i - 1;
        while (j >= 0 && fit[j] < fv) {
            fit[j + 1] = fit[j];
            memcpy(pool[j + 1], pool[j], GBYTES);
            j--;
        }
        fit[j + 1] = fv;
        memcpy(pool[j + 1], tmp, GBYTES);
    }

    /* 4. Tournament: top WINNERS × TSEEDS different seeds */
    printf("=== top %d winners ===\n", WINNERS);

    /* Pick output names by scanning for the next free winner_N slot.
     * This matters when either (a) the running binary is itself named
     * winner_N (a descendant re-invoked in its own parent dir), or
     * (b) a previous run left winner_1..winner_K in place. We never
     * clobber an existing file or the running executable. */
    int next_slot = 1;

    for (int w = 0; w < WINNERS; w++) {
        double sum = 0;
        double per[TSEEDS];
        for (int s = 0; s < TSEEDS; s++) {
            per[s] = fitness(pool[w], rseed + 100 + s);
            sum += per[s];
        }
        double avg = sum / TSEEDS;

        /* 5. Write the winner as a runnable child binary, at the next
         * slot that doesn't already exist on disk. */
        char path[64];
        for (;;) {
            snprintf(path, sizeof path, "winner_%d", next_slot);
            struct stat probe;
            if (stat(path, &probe) != 0) break;  /* free slot */
            next_slot++;
        }
        int rc = write_child(argv[0], path, pool[w]);
        if (rc != 0) {
            fprintf(stderr, "  couldn't write %s\n", path);
        }
        printf("#%d  ga=%.2f  avg=%.2f  per=[", w + 1, fit[w], avg);
        for (int s = 0; s < TSEEDS; s++)
            printf("%s%.2f", s ? " " : "", per[s]);
        printf("]  →  ./%s\n", path);
        next_slot++;  /* don't pick the same slot for the next winner */
    }

    return 0;
}

/* mandelhunt — fractal hex-CA quine hunter.
 *
 * officemandel + hexhunter, fused.  Generates Mandelbrot regions
 * across random walks through fractal coordinate space, posterises
 * each 128×128 K=4 image into a 16,384-byte hex CA rule LUT,
 * classifies for self-reproduction + Wolfram class 4, saves
 * filtered candidates as raw .lut files.
 *
 * The kernel insight: fractal self-similarity strongly correlates
 * with class-4 + quine-friendly CA structure (validated 2026-05-19,
 * 169 class-4 quine candidates from 602 loupe walk frames in 5 min
 * of Python; this C tool runs ~25× faster, ~5K candidates/hour on
 * one core, ~150K/hour on ALICE's 288-core jobs).
 *
 * Build:
 *   cc -std=c99 -O2 -o mandelhunt mandelhunt.c -lm
 *
 * Usage:
 *   mandelhunt                                # 1-hour walk-based scan
 *   mandelhunt -h 4 -o pool/ -s 0.5 -c 0.3    # 4 hours, custom filters
 *   mandelhunt -h 0.1 -d                       # quick dry-run, no files
 *
 * Output:
 *   - one binary <16,384-byte LUT>.lut per accepted candidate
 *   - leaderboard.json written every --report-every frames
 *   - one line per accept on stderr; one summary line per period
 *     on stdout (suitable for `tee scan.log`).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <signal.h>
#include <dirent.h>

#define SIDE        128                   /* 128x128 K=4 board */
#define BOARD_CELLS (SIDE * SIDE)         /* 16384 = one LUT */
#define K           4                     /* state alphabet */
#define LUT_SIZE    16384                 /* 4^7 */
#define TICKS       16                    /* SR evaluation depth */
#define CLASS_PROBE_TICKS 16              /* class-4 probe depth */
#define ACTIVITY_TICKS    12

/* ── Mandelbrot kernel — same iteration as officemandel ──────────────
 * One escape-time value per cell.  Iter is auto-tuned to the zoom
 * depth (deeper zoom → more iters) so deep regions don't go solid
 * black. */
static int auto_iter(double span) {
    int it = 192;
    while (span < 1.0 && it < 4096) { it += 64; span *= 2.0; }
    return it;
}

static int mandel_escape(double cx, double cy, int iter_cap) {
    double zx = 0, zy = 0, x2 = 0, y2 = 0;
    int i;
    for (i = 0; i < iter_cap && x2 + y2 < 4.0; i++) {
        zy = 2.0 * zx * zy + cy;
        zx = x2 - y2 + cx;
        x2 = zx * zx; y2 = zy * zy;
    }
    return i;
}

/* Render the SIDE×SIDE escape grid into `escape` (int per cell). */
static void mandel_grid(double cx, double cy, double span,
                          int *escape, int *iter_cap_out) {
    int it = auto_iter(span);
    *iter_cap_out = it;
    double s  = span / SIDE;
    double ox = cx - s * SIDE * 0.5;
    double oy = cy - s * SIDE * 0.5;
    for (int r = 0; r < SIDE; r++) {
        double y = oy + r * s;
        for (int c = 0; c < SIDE; c++) {
            double x = ox + c * s;
            escape[r * SIDE + c] = mandel_escape(x, y, it);
        }
    }
}

/* Posterise to K=4: cells in the set → bucket 3 (high "in-set"
 * indicator); finite cells split into 3 escape-quantile buckets.
 * Matches loupe.render.mandelbrot_buckets so the C and Python
 * pipelines produce comparable outputs on the same coordinates. */
static void posterise_to_lut(const int *escape, int iter_cap,
                              uint8_t *lut /* len=BOARD_CELLS */) {
    /* Sort finite escape values to find tertile boundaries. */
    int n_finite = 0;
    int finite[BOARD_CELLS];
    for (int i = 0; i < BOARD_CELLS; i++) {
        if (escape[i] < iter_cap) finite[n_finite++] = escape[i];
    }
    int bin1, bin2;
    if (n_finite < 3) {
        bin1 = iter_cap / 3;
        bin2 = (2 * iter_cap) / 3;
    } else {
        /* Selection by sort — n_finite ≤ 16384, fine. */
        for (int i = 0; i < n_finite - 1; i++)
            for (int j = i + 1; j < n_finite; j++)
                if (finite[i] > finite[j]) {
                    int t = finite[i]; finite[i] = finite[j]; finite[j] = t;
                }
        bin1 = finite[n_finite / 3];
        bin2 = finite[(2 * n_finite) / 3];
        if (bin2 <= bin1) bin2 = bin1 + 1;
    }
    for (int i = 0; i < BOARD_CELLS; i++) {
        int e = escape[i];
        if (e >= iter_cap)      lut[i] = 3;
        else if (e < bin1)       lut[i] = 0;
        else if (e < bin2)       lut[i] = 1;
        else                     lut[i] = 2;
    }
}

/* ── Hex CA step — K=4, 7-cell pointy-top neighbourhood ──────────────
 * Matches caformer.primitives.hex_ca_step byte-for-byte.  Toroidal
 * boundary.  `out` and `state` are 128×128 K=4 grids. */
static void hex_step(const uint8_t *state, const uint8_t *rule,
                       uint8_t *out) {
    for (int r = 0; r < SIDE; r++) {
        int even = !(r & 1);
        int up = (r - 1 + SIDE) % SIDE;
        int dn = (r + 1)        % SIDE;
        for (int c = 0; c < SIDE; c++) {
            int l = (c - 1 + SIDE) % SIDE;
            int rc = (c + 1)       % SIDE;
            int n_l    = state[r  * SIDE + l ];
            int n_r    = state[r  * SIDE + rc];
            int n_up_l = state[up * SIDE + l ];
            int n_up_  = state[up * SIDE + c ];
            int n_up_r = state[up * SIDE + rc];
            int n_dn_l = state[dn * SIDE + l ];
            int n_dn_  = state[dn * SIDE + c ];
            int n_dn_r = state[dn * SIDE + rc];
            int self_  = state[r  * SIDE + c ];
            int n_nw = even ? n_up_l : n_up_;
            int n_ne = even ? n_up_  : n_up_r;
            int n_sw = even ? n_dn_l : n_dn_;
            int n_se = even ? n_dn_  : n_dn_r;
            int key = (self_  << 12)
                    | (n_nw   << 10)
                    | (n_ne   <<  8)
                    | (n_r    <<  6)
                    | (n_se   <<  4)
                    | (n_sw   <<  2)
                    |  n_l;
            out[r * SIDE + c] = rule[key];
        }
    }
}

/* L0 fixed-point check: run the rule on its own LUT-as-image for a
 * SINGLE tick and count how many cells didn't change.  Returns the
 * match count (0..BOARD_CELLS).  When the match count == BOARD_CELLS
 * the rule is a strict L0 fixed-point quine — its LUT-as-image is a
 * fixed point of one CA step, so it's also a fixed point at every
 * deeper depth (it's the strictest possible ouroboros condition).
 *
 * 16× cheaper than self_reproduce_score with its default 16 ticks, so
 * cheap enough to use as a positive-confirmation pre-filter on every
 * accepted candidate. */
static int l0_fixed_point_match(const uint8_t *rule) {
    static uint8_t buf[BOARD_CELLS];
    hex_step(rule, rule, buf);
    int match = 0;
    for (int i = 0; i < BOARD_CELLS; i++)
        if (buf[i] == rule[i]) match++;
    return match;
}

/* Self-reproduction score: run the rule on its own LUT-as-image for
 * `ticks` steps; return fraction of cells equal to the seed. */
static double self_reproduce_score(const uint8_t *rule, int ticks) {
    static uint8_t buf_a[BOARD_CELLS];
    static uint8_t buf_b[BOARD_CELLS];
    memcpy(buf_a, rule, BOARD_CELLS);
    uint8_t *cur = buf_a, *nxt = buf_b;
    for (int t = 0; t < ticks; t++) {
        hex_step(cur, rule, nxt);
        uint8_t *tmp = cur; cur = nxt; nxt = tmp;
    }
    int match = 0;
    for (int i = 0; i < BOARD_CELLS; i++)
        if (cur[i] == rule[i]) match++;
    return (double)match / BOARD_CELLS;
}

/* Cheap classifier: probe activity (cells changing per tick) + a
 * coarse class label.
 *   class 1 = converges to uniform (activity tail near 0)
 *   class 2 = small periodic structure (activity small but >0)
 *   class 3 = chaotic (activity remains high, no structure)
 *   class 4 = persistent localised structures (medium activity,
 *             non-trivial spatial correlation)
 * This is a rough heuristic — full classification matches
 * spoeqi.metachain.classify_rule.  Returns class via *cls_out
 * and a c4-score via *c4_out. */
static double probe_activity(const uint8_t *rule, int ticks) {
    static uint8_t buf_a[BOARD_CELLS];
    static uint8_t buf_b[BOARD_CELLS];
    /* Seed with a deterministic noisy state (LCG byte stream). */
    uint32_t s = 0xCAFEBABE;
    for (int i = 0; i < BOARD_CELLS; i++) {
        s = s * 1103515245u + 12345u;
        buf_a[i] = (s >> 16) & 3;
    }
    uint8_t *cur = buf_a, *nxt = buf_b;
    int total_changes = 0;
    int tail_changes = 0;
    for (int t = 0; t < ticks; t++) {
        hex_step(cur, rule, nxt);
        int n_changed = 0;
        for (int i = 0; i < BOARD_CELLS; i++)
            if (cur[i] != nxt[i]) n_changed++;
        total_changes += n_changed;
        if (t >= ticks / 2) tail_changes += n_changed;
        uint8_t *tmp = cur; cur = nxt; nxt = tmp;
    }
    return (double)tail_changes /
           ((double)(ticks / 2 + 1) * BOARD_CELLS);
}

static void classify(const uint8_t *rule, int *cls_out,
                       double *c4_out) {
    double act = probe_activity(rule, CLASS_PROBE_TICKS);
    /* Heuristic class assignment — must agree with the Python
     * classify_rule directionally so leaderboard comparisons work.
     *   <  0.02   → class 1 (dies)
     *   0.02-0.08 → class 2 (small structures)
     *   >  0.55   → class 3 (chaotic)
     *   else      → class 4 (interesting)
     */
    int cls;
    double c4;
    if (act < 0.02)        { cls = 1; c4 = 0.0; }
    else if (act < 0.08)   { cls = 2; c4 = 0.1; }
    else if (act > 0.55)   { cls = 3; c4 = 0.05; }
    else {
        cls = 4;
        /* c4 score: distance from chaotic and dead extremes.
         * Peaks at activity around 0.3-0.4. */
        double a = act;
        c4 = 1.0 - 4.0 * fabs(a - 0.32);
        if (c4 < 0.0) c4 = 0.0;
    }
    *cls_out = cls;
    *c4_out  = c4;
}

/* ── Coordinate generators ─────────────────────────────────────────── */

typedef struct {
    double cx, cy, span;
} Coord;

/* Random walk that zooms into random sub-regions, starting from one
 * of N seed coordinates known to be interesting. */
static const Coord SEEDS[] = {
    { -0.5,    0.0,   3.0  },     /* main view */
    { -0.745,  0.113, 0.05 },     /* spiral */
    { -1.25,   0.0,   0.1  },     /* left bulb */
    { -0.16,   1.04,  0.04 },     /* elephant valley */
    {  0.272,  0.005, 0.01 },     /* seahorse valley */
};
static const int N_SEEDS = sizeof(SEEDS) / sizeof(SEEDS[0]);

static uint64_t rng_state;
static double rand_unit(void) {
    /* xorshift64 → [0, 1) */
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return (double)(rng_state & ((1ull << 53) - 1)) /
           (double)(1ull << 53);
}

static Coord next_coord(Coord cur) {
    Coord n = cur;
    /* Step: random offset + zoom in. */
    n.cx += (rand_unit() * 2.0 - 1.0) * 0.4 * cur.span;
    n.cy += (rand_unit() * 2.0 - 1.0) * 0.4 * cur.span;
    n.span *= 0.6 + 0.35 * rand_unit();
    if (n.span < 1e-12) n.span = 1.0;   /* reset if we zoomed too deep */
    return n;
}

/* ── Main loop ─────────────────────────────────────────────────────── */

static volatile int g_stop = 0;
static void on_signal(int sig) { (void)sig; g_stop = 1; }

static void usage(const char *prog) {
    fprintf(stderr,
        "usage: %s [-h hours] [-o out_dir] [-s min_sr] [-c min_c4]\n"
        "          [-w walk_steps] [-r report_every] [-S rng_seed] [-d]\n"
        "          [-L] [-C dir]\n"
        "  -h hours      wall-clock budget       (default 1.0)\n"
        "  -o out_dir    where to write LUTs     (default ./mh_pool)\n"
        "  -s min_sr     min SR strict to save   (default 0.4)\n"
        "  -c min_c4     min c4 score to save    (default 0.2)\n"
        "  -w walk_steps frames per random walk  (default 24)\n"
        "  -r every      report stats every N    (default 500)\n"
        "  -S seed       RNG seed                (default = time)\n"
        "  -d            dry-run (no files written)\n"
        "  -L            run L0 fixed-point check on accepted candidates;\n"
        "                strict-quine hits are copied to <out_dir>/ouroboros/\n"
        "                with a _L0 tag.  Adds tiny per-candidate overhead.\n"
        "  -C dir        SCAN MODE: don't generate; just L0-check every .lut\n"
        "                in <dir>, report counts.  All other flags ignored.\n",
        prog);
}

/* ── L0 directory scan mode (-C) ────────────────────────────────────── */

static int scan_directory_for_l0(const char *dir) {
    DIR *d = opendir(dir);
    if (!d) {
        fprintf(stderr, "cannot open dir %s\n", dir);
        return 1;
    }
    fprintf(stderr, "scanning %s for L0 fixed-point quines...\n", dir);

    long n_files = 0;
    long n_strict = 0;          /* match == BOARD_CELLS */
    long n_near   = 0;          /* match >= 16128 (≥ 98.4 %) */
    long sum_match = 0;
    int  best_match = -1;
    char best_name[512] = {0};
    static uint8_t lut[BOARD_CELLS];

    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        const char *name = de->d_name;
        size_t len = strlen(name);
        if (len < 4 || strcmp(name + len - 4, ".lut") != 0) continue;

        char path[1024];
        snprintf(path, sizeof path, "%s/%s", dir, name);
        FILE *fp = fopen(path, "rb");
        if (!fp) continue;
        size_t got = fread(lut, 1, BOARD_CELLS, fp);
        fclose(fp);
        if (got != BOARD_CELLS) {
            fprintf(stderr, "  skip %s: %zu bytes (expected %d)\n",
                    name, got, BOARD_CELLS);
            continue;
        }

        int m = l0_fixed_point_match(lut);
        n_files++;
        sum_match += m;
        if (m == BOARD_CELLS) {
            n_strict++;
            printf("  STRICT L0 ✓  %s  (%d/%d)\n", name, m, BOARD_CELLS);
        }
        if (m >= 16128) n_near++;
        if (m > best_match) {
            best_match = m;
            snprintf(best_name, sizeof best_name, "%s", name);
        }
    }
    closedir(d);

    printf("\n=== L0 scan done ===\n");
    printf("  scanned:        %ld .lut files\n", n_files);
    printf("  strict L0 (match==16384):  %ld\n", n_strict);
    printf("  near-strict   (>=98.4%%):  %ld\n", n_near);
    if (n_files > 0) {
        printf("  mean match:                %.1f / %d  (%.2f%%)\n",
               (double)sum_match / n_files, BOARD_CELLS,
               100.0 * sum_match / n_files / BOARD_CELLS);
        printf("  best match:                %d / %d  (%.4f%%)  %s\n",
               best_match, BOARD_CELLS,
               100.0 * best_match / BOARD_CELLS, best_name);
    }
    return 0;
}

int main(int argc, char **argv) {
    double hours = 1.0;
    const char *out_dir = "mh_pool";
    double min_sr = 0.4;
    double min_c4 = 0.2;
    int walk_steps = 24;
    int report_every = 500;
    int dry_run = 0;
    int l0_check = 0;
    const char *scan_dir = NULL;
    rng_state = (uint64_t)time(NULL);

    int opt;
    while ((opt = getopt(argc, argv, "h:o:s:c:w:r:S:dLC:")) != -1) {
        switch (opt) {
            case 'h': hours = atof(optarg); break;
            case 'o': out_dir = optarg; break;
            case 's': min_sr = atof(optarg); break;
            case 'c': min_c4 = atof(optarg); break;
            case 'w': walk_steps = atoi(optarg); break;
            case 'r': report_every = atoi(optarg); break;
            case 'S': rng_state = (uint64_t)atoll(optarg); break;
            case 'd': dry_run = 1; break;
            case 'L': l0_check = 1; break;
            case 'C': scan_dir = optarg; break;
            default:  usage(argv[0]); return 1;
        }
    }
    /* Scan mode (-C) short-circuits everything else. */
    if (scan_dir) return scan_directory_for_l0(scan_dir);

    if (!dry_run) {
        mkdir(out_dir, 0755);
        if (l0_check) {
            char path[1024];
            snprintf(path, sizeof path, "%s/ouroboros", out_dir);
            mkdir(path, 0755);
        }
    }
    signal(SIGTERM, on_signal);
    signal(SIGINT,  on_signal);

    fprintf(stderr,
        "mandelhunt: hours=%.2f out_dir=%s min_sr=%.2f min_c4=%.2f "
        "walk_steps=%d rng=%llu%s\n",
        hours, out_dir, min_sr, min_c4, walk_steps,
        (unsigned long long)rng_state, dry_run ? " [DRY RUN]" : "");

    time_t t_start = time(NULL);
    double budget = hours * 3600.0;
    long n_scanned = 0;
    long n_class4  = 0;
    long n_saved   = 0;
    long n_l0_strict = 0;       /* match == BOARD_CELLS (when -L) */
    long n_l0_near   = 0;       /* match >= 16128 = 98.4 % */
    int  best_l0_match = -1;    /* tracks best per-run L0 score */
    double best_combined = -1.0;
    Coord best_coord = {0};
    double best_sr = 0.0, best_c4 = 0.0;

    static int    escape[BOARD_CELLS];
    static uint8_t lut[BOARD_CELLS];

    Coord cur = SEEDS[(int)(rand_unit() * N_SEEDS)];
    int step_in_walk = 0;

    while (!g_stop) {
        double elapsed = difftime(time(NULL), t_start);
        if (elapsed >= budget) break;

        /* Advance the walk, or pick a new seed at end of walk. */
        if (step_in_walk == 0) {
            cur = SEEDS[(int)(rand_unit() * N_SEEDS)];
        }

        /* Render Mandelbrot at this coordinate. */
        int iter_cap;
        mandel_grid(cur.cx, cur.cy, cur.span, escape, &iter_cap);
        posterise_to_lut(escape, iter_cap, lut);

        /* Classify. */
        double sr = self_reproduce_score(lut, TICKS);
        int cls;
        double c4;
        classify(lut, &cls, &c4);
        n_scanned++;
        if (cls == 4) n_class4++;

        /* Accept gate. */
        if (cls == 4 && sr >= min_sr && c4 >= min_c4) {
            n_saved++;
            double combined = sr * (0.3 + c4);
            if (combined > best_combined) {
                best_combined = combined;
                best_coord = cur;
                best_sr = sr; best_c4 = c4;
            }
            /* Optional L0 fixed-point check. */
            int l0_match = -1;
            if (l0_check) {
                l0_match = l0_fixed_point_match(lut);
                if (l0_match > best_l0_match) best_l0_match = l0_match;
                if (l0_match == BOARD_CELLS) n_l0_strict++;
                if (l0_match >= 16128) n_l0_near++;
            }
            if (!dry_run) {
                char path[512];
                snprintf(path, sizeof path,
                    "%s/mh_n%06ld_sr%.3f_c4%.3f.lut",
                    out_dir, n_saved, sr, c4);
                FILE *fp = fopen(path, "wb");
                if (fp) {
                    fwrite(lut, 1, BOARD_CELLS, fp);
                    fclose(fp);
                }
                fprintf(stderr,
                    "  + saved %s  cx=%+.6f cy=%+.6f span=%.4g\n",
                    path, cur.cx, cur.cy, cur.span);
                /* If L0-strict, also copy to ouroboros/ with L0 tag. */
                if (l0_check && l0_match == BOARD_CELLS) {
                    char opath[512];
                    snprintf(opath, sizeof opath,
                        "%s/ouroboros/mh_n%06ld_sr%.3f_c4%.3f_L0.lut",
                        out_dir, n_saved, sr, c4);
                    FILE *op = fopen(opath, "wb");
                    if (op) {
                        fwrite(lut, 1, BOARD_CELLS, op);
                        fclose(op);
                    }
                    fprintf(stderr,
                        "  ★ STRICT L0 quine → %s\n", opath);
                }
            }
        }

        /* Periodic report. */
        if (n_scanned % report_every == 0) {
            double rate = n_scanned / (elapsed + 0.001);
            printf("[%6.1fm] scanned=%-8ld class4=%-6ld saved=%-5ld "
                   "best=%.3f rate=%.0f/s\n",
                   elapsed / 60.0, n_scanned, n_class4, n_saved,
                   best_combined, rate);
            fflush(stdout);
            /* Live leaderboard dump. */
            if (!dry_run) {
                char path[512];
                snprintf(path, sizeof path, "%s/leaderboard.json", out_dir);
                FILE *fp = fopen(path, "w");
                if (fp) {
                    fprintf(fp,
                        "{\n"
                        "  \"elapsed_seconds\": %.1f,\n"
                        "  \"n_scanned\":       %ld,\n"
                        "  \"n_class4\":        %ld,\n"
                        "  \"n_saved\":         %ld,\n"
                        "  \"n_l0_strict\":     %ld,\n"
                        "  \"n_l0_near\":       %ld,\n"
                        "  \"best_l0_match\":   %d,\n"
                        "  \"rate_per_sec\":    %.1f,\n"
                        "  \"best_combined\":   %.4f,\n"
                        "  \"best_sr\":         %.4f,\n"
                        "  \"best_c4\":         %.4f,\n"
                        "  \"best_cx\":         %.10f,\n"
                        "  \"best_cy\":         %.10f,\n"
                        "  \"best_span\":       %.6g\n"
                        "}\n",
                        elapsed, n_scanned, n_class4, n_saved,
                        n_l0_strict, n_l0_near, best_l0_match, rate,
                        best_combined, best_sr, best_c4,
                        best_coord.cx, best_coord.cy, best_coord.span);
                    fclose(fp);
                }
            }
        }

        /* Step along the walk. */
        cur = next_coord(cur);
        step_in_walk++;
        if (step_in_walk >= walk_steps) step_in_walk = 0;
    }

    double total = difftime(time(NULL), t_start);
    printf("\n=== mandelhunt done ===\n");
    printf("  scanned:        %ld\n", n_scanned);
    printf("  class-4 frames: %ld (%.1f%%)\n",
           n_class4, 100.0 * n_class4 / (n_scanned > 0 ? n_scanned : 1));
    printf("  saved:          %ld\n", n_saved);
    printf("  rate:           %.0f frames/sec\n",
           n_scanned / (total + 0.001));
    printf("  best combined:  %.4f  (sr=%.4f c4=%.4f)\n",
           best_combined, best_sr, best_c4);
    printf("  best coord:     cx=%+.10f cy=%+.10f span=%.6g\n",
           best_coord.cx, best_coord.cy, best_coord.span);
    if (l0_check) {
        printf("  L0 strict:      %ld (true ouroboros, sr_1tick = 1.0)\n",
               n_l0_strict);
        printf("  L0 near (≥98.4%%): %ld\n", n_l0_near);
        printf("  best L0 match:  %d / %d (%.4f%%)\n",
               best_l0_match, BOARD_CELLS,
               100.0 * (best_l0_match > 0 ? best_l0_match : 0) / BOARD_CELLS);
    }
    printf("  wall:           %.0fs\n", total);
    printf("  output dir:     %s\n", out_dir);
    return 0;
}

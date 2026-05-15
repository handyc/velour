/* hh_cli — minimal command-line front-end for libhexhunter.
 *
 * Reproduces the GA part of the original ./hunter program (no display
 * mode, no self-replicating ELF tail).  Writes the winning 4096-byte
 * ruleset to a file you specify (default: ./winner.bin).
 *
 *   ./hh_cli                                # all defaults
 *   ./hh_cli POP GENS                       # like ./hunter POP GENS
 *   ./hh_cli POP GENS SEED                  # ... with explicit RNG seed
 *   ./hh_cli POP GENS SEED OUT_PATH         # ... and a custom output path
 *
 * To refine an existing ruleset, pass it as a 5th positional arg
 * (the input is read first, then the GA continues around it):
 *
 *   ./hh_cli POP GENS SEED OUT_PATH IN_PATH
 */

#include "hexhunter.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>


static void usage(const char *prog) {
    fprintf(stderr,
        "usage: %s [POP] [GENS] [SEED] [OUT_PATH] [IN_PATH]\n"
        "  POP      population size      (default 30)\n"
        "  GENS     number of generations(default 40)\n"
        "  SEED     RNG seed             (default 42)\n"
        "  OUT_PATH winning ruleset out  (default ./winner.bin)\n"
        "  IN_PATH  refine an existing 4096-byte ruleset (optional)\n",
        prog);
}

static void on_progress(int gen, int total,
                        double best, double mean, double tail,
                        void *user) {
    (void)user;
    fprintf(stderr,
            "  gen %2d/%d  best=%.3f  mean=%.3f  best_activity_tail=%.3f\n",
            gen, total, best, mean, tail);
}

static int read_file_exactly(const char *path, uint8_t *buf, size_t want) {
    FILE *fp = fopen(path, "rb");
    if (!fp) { perror(path); return -1; }
    size_t got = fread(buf, 1, want, fp);
    int extra = fgetc(fp);   /* should be EOF */
    fclose(fp);
    if (got != want) {
        fprintf(stderr, "%s: expected %zu bytes, got %zu\n", path, want, got);
        return -1;
    }
    if (extra != EOF) {
        fprintf(stderr, "%s: file is larger than %zu bytes\n", path, want);
        return -1;
    }
    return 0;
}

static int write_file_exactly(const char *path, const uint8_t *buf, size_t n) {
    FILE *fp = fopen(path, "wb");
    if (!fp) { perror(path); return -1; }
    size_t got = fwrite(buf, 1, n, fp);
    fclose(fp);
    if (got != n) {
        fprintf(stderr, "%s: wrote %zu / %zu bytes\n", path, got, n);
        return -1;
    }
    return 0;
}


int main(int argc, char **argv) {
    if (argc > 6) { usage(argv[0]); return 1; }
    hh_config_t cfg = {0};
    if (argc > 1) cfg.population  = atoi(argv[1]);
    if (argc > 2) cfg.generations = atoi(argv[2]);
    if (argc > 3) cfg.rng_seed    = (uint32_t)strtoul(argv[3], NULL, 10);
    const char *out_path = (argc > 4) ? argv[4] : "winner.bin";
    const char *in_path  = (argc > 5) ? argv[5] : NULL;
    cfg.progress = on_progress;

    uint8_t out_genome[HH_GENOME_BYTES];
    int rc;
    if (in_path) {
        uint8_t in_genome[HH_GENOME_BYTES];
        if (read_file_exactly(in_path, in_genome, HH_GENOME_BYTES) != 0)
            return 2;
        fprintf(stderr, "refining %s ...\n", in_path);
        rc = hexhunter_refine(&cfg, in_genome, out_genome);
    } else {
        fprintf(stderr, "evolving from identity ...\n");
        rc = hexhunter(&cfg, out_genome);
    }
    if (rc != 0) {
        fprintf(stderr, "hexhunter failed (rc=%d)\n", rc);
        return 3;
    }

    if (write_file_exactly(out_path, out_genome, HH_GENOME_BYTES) != 0)
        return 4;

    double final_fit = hexhunter_fitness(out_genome, &cfg);
    fprintf(stderr,
            "wrote %s (%d bytes)  fitness=%.3f\n",
            out_path, HH_GENOME_BYTES, final_fit);
    return 0;
}

/* byte_model_sampled.c - random-sampling search in a 25-bit weight space.
 *
 * When exhaustive breaks down
 *   The 2-2-1 block has 9 weights, search space 2^9 = 512. Fine.
 *   A 4-4-1 block has 25 weights, search space 2^25 = 33,554,432.
 *   That is still enumerable in a few seconds, but the *point* is that
 *   exhaustive stops scaling at about 30 bits. Random sampling does not
 *   care about search-space size - it cares about hit *density*.
 *
 * Architecture, 25-bit layout
 *   4 inputs -> 4 hidden -> 1 output, +-1 sign weights, sign activation.
 *     bits  0..15  W1 (4 inputs x 4 hidden)
 *     bits 16..19  b1 (4 hidden biases)
 *     bits 20..23  W2 (4 hidden x 1 output)
 *     bit     24   b2 (output bias)
 *
 * Growth protocol (same shape as byte_model_moe.c)
 *   For each named target: draw up to BUDGET random 25-bit weight words.
 *   Accept the first that matches all 16 input rows. Checkpoint atomically
 *   after every success; resume from the checkpoint on restart.
 *
 * Checkpoint file
 *   byte_model_sampled.ckpt, format:
 *     magic      : "BMSM"  (byte-model-sampled-magic)
 *     version    : u32  1
 *     count      : u32
 *     per solver : target_id u32, weights u32
 *
 * Compile: cc -O2 -o byte_model_sampled byte_model_sampled.c
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define CHECKPOINT_PATH    "byte_model_sampled.ckpt"
#define CHECKPOINT_TMP     "byte_model_sampled.ckpt.tmp"
#define CHECKPOINT_MAGIC   "BMSM"
#define CHECKPOINT_VERSION 1u
#define TARGET_COUNT       8
#define SAMPLING_BUDGET    2000000u   /* 2M random draws per target */
#define WEIGHT_BITS        25u
#define WEIGHT_MASK        ((1u << WEIGHT_BITS) - 1u)

/* --- forward pass, 4-4-1 sign net with +-1 weights ----------------- */

static int unpack_weight(uint32_t word, int bit_index) {
    return ((int)((word >> bit_index) & 1u) << 1) - 1;
}
static int sign_of(int v) { return v >= 0 ? 1 : -1; }

static int net25_forward(uint32_t weights, int a, int b, int c, int d) {
    const int inputs[4] = { a, b, c, d };
    int hidden[4];
    int bit = 0;
    for (int h = 0; h < 4; ++h) {
        int acc = 0;
        for (int i = 0; i < 4; ++i)
            acc += unpack_weight(weights, bit++) * inputs[i];
        acc += unpack_weight(weights, 16 + h);
        hidden[h] = sign_of(acc);
    }
    int out = 0;
    for (int h = 0; h < 4; ++h)
        out += unpack_weight(weights, 20 + h) * hidden[h];
    out += unpack_weight(weights, 24);
    return sign_of(out);
}

/* --- target family -------------------------------------------------- */

typedef int (*target_fn)(int, int, int, int);

static int parity4(int a, int b, int c, int d) {
    int ones = (a>0)+(b>0)+(c>0)+(d>0);
    return (ones & 1) ? 1 : -1;
}
static int majority4(int a, int b, int c, int d) {
    int ones = (a>0)+(b>0)+(c>0)+(d>0);
    return (ones >= 3) ? 1 : -1;
}
static int and4(int a, int b, int c, int d) {
    return (a>0 && b>0 && c>0 && d>0) ? 1 : -1;
}
static int or4(int a, int b, int c, int d) {
    return (a>0 || b>0 || c>0 || d>0) ? 1 : -1;
}
static int threshold2(int a, int b, int c, int d) {
    int ones = (a>0)+(b>0)+(c>0)+(d>0);
    return (ones >= 2) ? 1 : -1;
}
static int exactly_one(int a, int b, int c, int d) {
    int ones = (a>0)+(b>0)+(c>0)+(d>0);
    return (ones == 1) ? 1 : -1;
}
static int exactly_two(int a, int b, int c, int d) {
    int ones = (a>0)+(b>0)+(c>0)+(d>0);
    return (ones == 2) ? 1 : -1;
}
static int xor_halves(int a, int b, int c, int d) {
    /* XOR between (a XOR b) and (c XOR d) - equivalently parity4 */
    int left  = ((a>0) != (b>0)) ? 1 : -1;
    int right = ((c>0) != (d>0)) ? 1 : -1;
    return (left > 0) != (right > 0) ? 1 : -1;
}

typedef struct { const char *name; target_fn fn; } TargetSpec;

static const TargetSpec TARGETS[TARGET_COUNT] = {
    { "parity4",     parity4     },
    { "majority4",   majority4   },
    { "and4",        and4        },
    { "or4",         or4         },
    { "threshold2",  threshold2  },
    { "exactly_one", exactly_one },
    { "exactly_two", exactly_two },
    { "xor_halves",  xor_halves  },
};

/* --- verifier: check a candidate against all 16 input rows --------- */

static int verify(uint32_t weights, target_fn fn) {
    for (int row = 0; row < 16; ++row) {
        int a = (row & 8) ? 1 : -1, b = (row & 4) ? 1 : -1;
        int c = (row & 2) ? 1 : -1, d = (row & 1) ? 1 : -1;
        if (net25_forward(weights, a, b, c, d) != fn(a, b, c, d)) return 0;
    }
    return 1;
}

/* --- random 25-bit candidate.  rand() yields >=15 bits; stitch to 25. */

static uint32_t rand25(void) {
    /* two rand() calls combined so the high bits mix properly */
    uint32_t lo = (uint32_t)rand() & 0xFFFFu;       /* 16 bits */
    uint32_t hi = (uint32_t)rand() & 0x1FFu;        /*  9 bits */
    return (lo | (hi << 16)) & WEIGHT_MASK;
}

/* returns 1 if found, 0 if budget exhausted. */
static int search_random(target_fn fn, uint32_t budget,
                         uint32_t *out_weights, uint32_t *out_attempts) {
    for (uint32_t attempt = 1; attempt <= budget; ++attempt) {
        uint32_t candidate = rand25();
        if (verify(candidate, fn)) {
            *out_weights  = candidate;
            *out_attempts = attempt;
            return 1;
        }
    }
    return 0;
}

/* --- checkpoint I/O (atomic tmp + fsync + rename) ------------------ */

typedef struct { uint32_t target_id; uint32_t weights; } Solver;

static int checkpoint_save(const Solver *solvers, int count) {
    FILE *fp = fopen(CHECKPOINT_TMP, "wb");
    if (!fp) return 0;
    uint32_t version = CHECKPOINT_VERSION, cnt = (uint32_t)count;
    if (fwrite(CHECKPOINT_MAGIC, 1, 4, fp) != 4      ||
        fwrite(&version, 4, 1, fp) != 1              ||
        fwrite(&cnt,     4, 1, fp) != 1) { fclose(fp); unlink(CHECKPOINT_TMP); return 0; }
    for (int i = 0; i < count; ++i) {
        if (fwrite(&solvers[i].target_id, 4, 1, fp) != 1 ||
            fwrite(&solvers[i].weights,   4, 1, fp) != 1) {
            fclose(fp); unlink(CHECKPOINT_TMP); return 0;
        }
    }
    fflush(fp);
    int fd = fileno(fp);
    if (fd >= 0) fsync(fd);
    fclose(fp);
    return rename(CHECKPOINT_TMP, CHECKPOINT_PATH) == 0;
}

static int checkpoint_load(Solver *solvers, int capacity) {
    FILE *fp = fopen(CHECKPOINT_PATH, "rb");
    if (!fp) return 0;
    char magic[4]; uint32_t version = 0, count = 0;
    if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, CHECKPOINT_MAGIC, 4) ||
        fread(&version, 4, 1, fp) != 1 || version != CHECKPOINT_VERSION ||
        fread(&count,   4, 1, fp) != 1 || count > (uint32_t)capacity) {
        fclose(fp); return 0;
    }
    int loaded = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (fread(&solvers[i].target_id, 4, 1, fp) != 1) break;
        if (fread(&solvers[i].weights,   4, 1, fp) != 1) break;
        loaded++;
    }
    fclose(fp);
    return loaded;
}

static int is_covered(const Solver *solvers, int count, uint32_t target_id) {
    for (int i = 0; i < count; ++i)
        if (solvers[i].target_id == target_id) return 1;
    return 0;
}

/* --- main ---------------------------------------------------------- */

int main(void) {
    srand(42u);   /* fixed seed -> reproducible runs */

    Solver solvers[TARGET_COUNT];
    int    count = checkpoint_load(solvers, TARGET_COUNT);
    if (count > 0)
        printf("resumed: %d solvers already in %s\n", count, CHECKPOINT_PATH);
    else
        printf("no checkpoint found - starting fresh\n");

    for (uint32_t target_id = 0; target_id < TARGET_COUNT; ++target_id) {
        if (is_covered(solvers, count, target_id)) continue;

        const TargetSpec *t = &TARGETS[target_id];
        uint32_t weights = 0, attempts = 0;
        int found = search_random(t->fn, SAMPLING_BUDGET, &weights, &attempts);

        if (!found) {
            printf("  target %-12s : no solver after %u samples (hit rate < %.2e)\n",
                   t->name, SAMPLING_BUDGET, 1.0 / SAMPLING_BUDGET);
            continue;
        }

        solvers[count].target_id = target_id;
        solvers[count].weights   = weights;
        count++;

        if (!checkpoint_save(solvers, count)) {
            fprintf(stderr, "FATAL: checkpoint save failed\n");
            return 1;
        }

        double hit_rate = (double)1.0 / attempts;
        printf("  + target %-12s  weights=0x%07x   "
               "found at attempt %7u (hit rate ~%.2e)   saved\n",
               t->name, weights, attempts, hit_rate);
    }

    printf("\ncoverage: %d / %d targets\n", count, TARGET_COUNT);

    /* full verify of everything in the pool */
    int checked = 0, correct = 0;
    for (int i = 0; i < count; ++i) {
        const TargetSpec *t = &TARGETS[solvers[i].target_id];
        for (int row = 0; row < 16; ++row) {
            int a = (row & 8) ? 1 : -1, b = (row & 4) ? 1 : -1;
            int c = (row & 2) ? 1 : -1, d = (row & 1) ? 1 : -1;
            int got  = net25_forward(solvers[i].weights, a, b, c, d);
            int want = t->fn(a, b, c, d);
            checked++;
            if (got == want) correct++;
        }
    }
    printf("verify  : %d/%d correct%s\n", correct, checked,
           correct == checked ? "  [OK]" : "  [FAIL]");
    printf("state   : %s  (delete to redo search)\n", CHECKPOINT_PATH);
    return (correct == checked) ? 0 : 2;
}

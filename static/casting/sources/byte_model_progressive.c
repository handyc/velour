/* byte_model_progressive.c — progressive architecture search.
 *
 * Architecture family: n → h → 1 MLP with ±1 weights, biases on every
 * unit, sign() activation. For h > 0 total bits = h*(n+2) + 1; the
 * h=0 baseline (linear classifier) is (n+1) bits.
 *
 * Search rule: for each target, grow h = 0, 1, 2, ... until exhaustive
 * search over all 2^W weight bitstrings finds a solver. Record the
 * smallest h that works, and the solver bits. Stop at W > 22 (~4M).
 *
 * This is the capability-per-parameter curve of tiny models. Linear
 * targets (OR/AND/MAJ) solve at h=0 or h=1. XOR needs h=2. Parity
 * over 4 bits may need more. The output is a pool you can serialize
 * and ship; the JS port dumps it as JSON.
 *
 * Compile: cc -O2 -o byte_model_progressive byte_model_progressive.c
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define MAX_H 4
#define MAX_N 4

static int sign_(int x) { return x >= 0 ? +1 : -1; }

/* Forward pass. Weight layout (LSB first):
 *   [input->hidden weights row-major for each hidden unit,
 *    each followed by that hidden unit's bias],
 *   then [output weights for each hidden unit, then output bias].
 * For h==0: just [n input weights, then output bias]. */
static int forward(uint32_t bits, int n, int h, const int *x) {
    int xi[MAX_N];
    for (int i = 0; i < n; ++i) xi[i] = x[i] ? 1 : -1;
    int idx = 0;
    if (h == 0) {
        int s = 0;
        for (int i = 0; i < n; ++i) {
            int w = ((bits >> idx++) & 1) ? 1 : -1;
            s += w * xi[i];
        }
        int b = ((bits >> idx++) & 1) ? 1 : -1;
        return sign_(s + b);
    }
    int hid[MAX_H];
    for (int j = 0; j < h; ++j) {
        int s = 0;
        for (int i = 0; i < n; ++i) {
            int w = ((bits >> idx++) & 1) ? 1 : -1;
            s += w * xi[i];
        }
        int b = ((bits >> idx++) & 1) ? 1 : -1;
        hid[j] = sign_(s + b);
    }
    int s = 0;
    for (int j = 0; j < h; ++j) {
        int w = ((bits >> idx++) & 1) ? 1 : -1;
        s += w * hid[j];
    }
    int b = ((bits >> idx++) & 1) ? 1 : -1;
    return sign_(s + b);
}

static int total_bits(int n, int h) {
    return (h == 0) ? (n + 1) : h * (n + 2) + 1;
}

typedef struct { const char *name; int n; unsigned long tt; } Target;
typedef struct { int solved; int h; int W; uint32_t bits; unsigned long examined; } Solver;

static Solver search_progressive(const Target *tgt, int max_W) {
    Solver s = { 0, 0, 0, 0, 0 };
    int x[MAX_N];
    int N = 1 << tgt->n;
    for (int h = 0; h <= MAX_H; ++h) {
        int W = total_bits(tgt->n, h);
        if (W > max_W) break;
        uint64_t space = 1ULL << W;
        for (uint64_t b = 0; b < space; ++b) {
            int ok = 1;
            for (int row = 0; row < N; ++row) {
                for (int i = 0; i < tgt->n; ++i)
                    x[i] = (row >> (tgt->n - 1 - i)) & 1;
                int y_pred = forward((uint32_t)b, tgt->n, h, x);
                int y_true = ((tgt->tt >> row) & 1) ? +1 : -1;
                if (y_pred != y_true) { ok = 0; break; }
            }
            s.examined++;
            if (ok) { s.solved = 1; s.h = h; s.W = W; s.bits = (uint32_t)b; return s; }
        }
    }
    return s;
}

static Target TARGETS[] = {
    {"2-AND",  2, 0x8},
    {"2-OR",   2, 0xe},
    {"2-XOR",  2, 0x6},
    {"3-AND",  3, 0x80},
    {"3-OR",   3, 0xfe},
    {"3-MAJ",  3, 0xe8},
    {"3-MUX",  3, 0xca},
    {"3-XOR",  3, 0x69},
    {"4-OR",   4, 0xfffe},
    {"4-AND",  4, 0x8000},
    {"4-MAJ",  4, 0xe880},
    {"4-thr2", 4, 0xfee8},
    {"4-XOR",  4, 0x6996},
};
#define N_TARGETS (sizeof(TARGETS)/sizeof(TARGETS[0]))

int main(void) {
    printf("progressive architecture search — tiny MLPs (±1 weights, sign activation)\n");
    printf("grow hidden width h until a solver is found; emit the whole pool.\n\n");
    printf("%-8s  %-3s  %-4s  %-10s  %s\n", "target", "h", "bits", "examined", "solver");
    printf("-----------------------------------------------------------------\n");
    int solved_count = 0;
    for (unsigned i = 0; i < N_TARGETS; ++i) {
        Solver r = search_progressive(&TARGETS[i], 22);
        if (r.solved) {
            printf("%-8s  %-3d  %-4d  %-10lu  0x%x\n",
                   TARGETS[i].name, r.h, r.W, r.examined, r.bits);
            solved_count++;
        } else {
            printf("%-8s  -    -     -           UNSOLVED (W > 22)\n",
                   TARGETS[i].name);
        }
    }
    printf("\npool: %d / %zu targets solved.\n", solved_count, N_TARGETS);
    printf("the JS version serializes this pool as JSON for drop-in use.\n");
    return 0;
}

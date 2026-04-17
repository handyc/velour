/* byte_model_runtime.c — tiny "inference engine" for a Casting pool.
 *
 * A Casting pool is a JSON array of solvers produced by progressive
 * architecture search. Each entry carries:
 *     { n: inputs, h: hidden units, weight_bits: W, bits: solver }
 *
 * The weight bitstring encodes (LSB first, for h > 0):
 *     for each hidden unit j in 0..h-1:
 *         n input weights, then 1 bias
 *     then h output weights, then 1 output bias.
 *
 * For h == 0 the bitstring is just n input weights plus 1 output bias
 * (a linear classifier).
 *
 * This file embeds a small demo pool so you can see the inference loop
 * without needing a JSON parser. The JS port at
 * static/casting/js/byte_model_runtime.js loads an arbitrary pool.json.
 *
 * Compile: cc -O2 -o byte_model_runtime byte_model_runtime.c
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    const char *name;
    int        n;
    uint32_t   bits;
    int        h;
    int        W;
} PoolEntry;

/* Seeded from a progressive-search run (11 / 13 targets solved). */
static PoolEntry POOL[] = {
    { "2-AND",  2, 0x3,     0,  3 },
    { "2-OR",   2, 0x7,     0,  3 },
    { "2-XOR",  2, 0x3,     2,  9 },
    { "3-AND",  3, 0x8,     1,  6 },
    { "3-OR",   3, 0xf,     0,  4 },
    { "3-MAJ",  3, 0x7,     0,  4 },
    { "3-MUX",  3, 0x10ba,  3, 16 },
    { "3-XOR",  3, 0x35,    3, 16 },
    { "4-OR",   4, 0x40022, 3, 19 },
    { "4-MAJ",  4, 0xf,     0,  5 },
    { "4-thr2", 4, 0x1f,    0,  5 },
};
#define N_POOL (sizeof(POOL)/sizeof(POOL[0]))

static int sign_(int x) { return x >= 0 ? +1 : -1; }

static int forward(uint32_t bits, int n, int h, const int *x) {
    int xi[4];
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
    int hid[4];
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

static const PoolEntry *find_entry(const char *name) {
    for (unsigned i = 0; i < N_POOL; ++i)
        if (strcmp(POOL[i].name, name) == 0) return &POOL[i];
    return NULL;
}

static void dump_truth(const PoolEntry *e) {
    printf("%-8s  (h=%d, W=%2d bits, solver=0x%x)\n",
           e->name, e->h, e->W, e->bits);
    int N = 1 << e->n;
    for (int row = 0; row < N; ++row) {
        int x[4];
        for (int i = 0; i < e->n; ++i) x[i] = (row >> (e->n - 1 - i)) & 1;
        int y = forward(e->bits, e->n, e->h, x);
        printf("  ");
        for (int i = 0; i < e->n; ++i) printf("%d", x[i]);
        printf(" -> %c%d\n", y > 0 ? '+' : '-', 1);
    }
}

int main(void) {
    printf("Casting Runtime — execute solvers out of a Casting pool.\n\n");
    printf("pool loaded: %zu entries\n\n", N_POOL);

    /* Spot-check the pool by running every entry on its full domain. */
    for (unsigned i = 0; i < N_POOL; ++i) {
        dump_truth(&POOL[i]);
        printf("\n");
    }

    /* A tiny "program": compute (a XOR b) AND (c OR d)
     * by chaining lookups from the pool. */
    printf("program: (a XOR b) AND (c OR d)\n");
    const PoolEntry *fxor = find_entry("2-XOR");
    const PoolEntry *f_or = find_entry("2-OR");
    const PoolEntry *fand = find_entry("2-AND");
    if (!fxor || !f_or || !fand) return 1;
    for (int row = 0; row < 16; ++row) {
        int a = (row >> 3) & 1, b = (row >> 2) & 1;
        int c = (row >> 1) & 1, d = (row >> 0) & 1;
        int ab[2] = { a, b };
        int cd[2] = { c, d };
        int u = (forward(fxor->bits, 2, fxor->h, ab) > 0) ? 1 : 0;
        int v = (forward(f_or->bits, 2, f_or->h, cd) > 0) ? 1 : 0;
        int uv[2] = { u, v };
        int y = (forward(fand->bits, 2, fand->h, uv) > 0) ? 1 : 0;
        printf("  a=%d b=%d c=%d d=%d -> %d\n", a, b, c, d, y);
    }
    return 0;
}

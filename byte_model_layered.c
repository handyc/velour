/* byte_model_layered.c - stack the MoE into a 3-position tree.
 *
 * What this adds to byte_model_moe.c
 *   The MoE there answers one 2-input boolean task at a time. This program
 *   loads the same checkpoint and arranges three experts into a layered
 *   tree, so the whole assembly is a 4-input -> 1-output function:
 *
 *       a  b       c  d
 *        \ /        \ /
 *       [f0]       [f1]       <- layer 0: two experts, 2 inputs each
 *          \      /
 *           \    /
 *           [ g ]              <- layer 1: one expert, combines the two
 *              |
 *           output
 *
 * What it measures
 *   Every (f0, f1, g) triple picks three experts from the 16-expert pool,
 *   so there are 16 * 16 * 16 = 4096 possible trees. Each tree realises
 *   some 4-input boolean function (fingerprint = its 16-bit truth table).
 *   The program counts how many of the 2^16 = 65536 possible 4-bit
 *   functions are *reachable* by some tree, and prints which assignments
 *   realise a few named targets.
 *
 * Dependency
 *   Requires byte_model_moe.ckpt to exist. Run ./byte_model_moe first.
 *
 * Compile: cc -O2 -o byte_model_layered byte_model_layered.c
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#define CHECKPOINT_PATH    "byte_model_moe.ckpt"
#define CHECKPOINT_MAGIC   "BMMM"
#define CHECKPOINT_VERSION 1u
#define POOL_CAPACITY      16

typedef struct {
    uint32_t task_id;
    uint32_t weights;
    int      lut[2][2];
} Expert;

/* --- same 2-2-1 block as byte_model_moe.c --------------------------- */

static int unpack_weight(uint32_t word, int bit_index) {
    return ((int)((word >> bit_index) & 1u) << 1) - 1;
}
static int sign_of(int value) { return value >= 0 ? 1 : -1; }

static int network_forward(uint32_t weights, int a, int b) {
    int h0 = sign_of( unpack_weight(weights,0)*a + unpack_weight(weights,1)*b
                    + unpack_weight(weights,2) );
    int h1 = sign_of( unpack_weight(weights,3)*a + unpack_weight(weights,4)*b
                    + unpack_weight(weights,5) );
    return   sign_of( unpack_weight(weights,6)*h0 + unpack_weight(weights,7)*h1
                    + unpack_weight(weights,8) );
}

static void compile_expert(Expert *expert) {
    for (int a_idx = 0; a_idx < 2; ++a_idx)
        for (int b_idx = 0; b_idx < 2; ++b_idx)
            expert->lut[a_idx][b_idx] =
                network_forward(expert->weights, a_idx?1:-1, b_idx?1:-1);
}

/* --- load the MoE pool checkpoint ----------------------------------- */

static int load_pool(Expert *pool) {
    FILE *fp = fopen(CHECKPOINT_PATH, "rb");
    if (!fp) return 0;
    char magic[4];
    uint32_t version = 0, count = 0;
    if (fread(magic, 1, 4, fp) != 4 ||
        memcmp(magic, CHECKPOINT_MAGIC, 4) != 0 ||
        fread(&version, 4, 1, fp) != 1 || version != CHECKPOINT_VERSION ||
        fread(&count,   4, 1, fp) != 1 || count > POOL_CAPACITY) {
        fclose(fp); return 0;
    }
    int loaded = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (fread(&pool[i].task_id, 4, 1, fp) != 1) break;
        if (fread(&pool[i].weights, 4, 1, fp) != 1) break;
        compile_expert(&pool[i]);
        loaded++;
    }
    fclose(fp);
    return loaded;
}

/* --- layered tree forward pass: 3 LUT reads per 4-bit input --------- */

static inline int expert_apply(const Expert *e, int a, int b) {
    return e->lut[a > 0][b > 0];
}

static inline int tree_forward(const Expert *f0, const Expert *f1,
                               const Expert *g, int a, int b, int c, int d) {
    return expert_apply(g,
                        expert_apply(f0, a, b),
                        expert_apply(f1, c, d));
}

/* fingerprint a tree by its 16-bit truth table over all 4-bit inputs */
static uint16_t tree_fingerprint(const Expert *f0, const Expert *f1,
                                 const Expert *g) {
    uint16_t fp = 0;
    for (int row = 0; row < 16; ++row) {
        int a = (row & 8) ? 1 : -1;
        int b = (row & 4) ? 1 : -1;
        int c = (row & 2) ? 1 : -1;
        int d = (row & 1) ? 1 : -1;
        if (tree_forward(f0, f1, g, a, b, c, d) > 0)
            fp |= (uint16_t)(1u << row);
    }
    return fp;
}

/* --- named 4-input boolean targets ---------------------------------- */

typedef int (*target_fn)(int, int, int, int);

static int parity4(int a, int b, int c, int d) {
    int ones = (a>0) + (b>0) + (c>0) + (d>0);
    return (ones & 1) ? 1 : -1;
}
static int majority4(int a, int b, int c, int d) {
    int ones = (a>0) + (b>0) + (c>0) + (d>0);
    return (ones >= 3) ? 1 : -1;
}
static int and4(int a, int b, int c, int d) {
    return (a>0 && b>0 && c>0 && d>0) ? 1 : -1;
}
static int or4(int a, int b, int c, int d) {
    return (a>0 || b>0 || c>0 || d>0) ? 1 : -1;
}
static int xor_a_and(int a, int b, int c, int d) {
    /* (a XOR b) AND (c AND d) - a non-trivial composed target */
    int left  = (a > 0) != (b > 0);        /* XOR */
    int right = (c > 0) && (d > 0);        /* AND */
    return (left && right) ? 1 : -1;
}

static uint16_t target_fingerprint(target_fn fn) {
    uint16_t fp = 0;
    for (int row = 0; row < 16; ++row) {
        int a = (row & 8) ? 1 : -1, b = (row & 4) ? 1 : -1;
        int c = (row & 2) ? 1 : -1, d = (row & 1) ? 1 : -1;
        if (fn(a, b, c, d) > 0) fp |= (uint16_t)(1u << row);
    }
    return fp;
}

/* --- bitset helpers on 2^16 = 65536 entries ------------------------- */

static uint8_t reachable_bits[8192];  /* 65536 bits */

static void reach_set(uint16_t fp)   { reachable_bits[fp >> 3] |= (uint8_t)(1u << (fp & 7)); }
static int  reach_has(uint16_t fp)   { return reachable_bits[fp >> 3] & (1u << (fp & 7)); }

/* remember the first (f0, f1, g) triple that realises each function */
static struct { int16_t f0, f1, g; } first_triple[65536];

/* --- main ----------------------------------------------------------- */

int main(void) {
    Expert pool[POOL_CAPACITY];
    int    pool_size = load_pool(pool);
    if (pool_size == 0) {
        fprintf(stderr,
                "no MoE checkpoint at %s\n"
                "run ./byte_model_moe first to grow the expert pool.\n",
                CHECKPOINT_PATH);
        return 1;
    }
    printf("loaded %d experts from %s\n", pool_size, CHECKPOINT_PATH);

    for (int i = 0; i < 65536; ++i) first_triple[i].f0 = -1;

    /* enumerate every (f0, f1, g) triple, record which 4-bit function it realises */
    for (int f0 = 0; f0 < pool_size; ++f0)
    for (int f1 = 0; f1 < pool_size; ++f1)
    for (int g  = 0; g  < pool_size; ++g) {
        uint16_t fp = tree_fingerprint(&pool[f0], &pool[f1], &pool[g]);
        if (!reach_has(fp)) {
            reach_set(fp);
            first_triple[fp].f0 = (int16_t)f0;
            first_triple[fp].f1 = (int16_t)f1;
            first_triple[fp].g  = (int16_t)g;
        }
    }

    int reached = 0;
    for (int i = 0; i < 65536; ++i) if (reach_has((uint16_t)i)) reached++;

    int total_triples = pool_size * pool_size * pool_size;
    printf("enumerated %d trees  ->  %d distinct 4-bit functions reachable"
           " (of 65536 possible; %.2f%%)\n",
           total_triples, reached, 100.0 * reached / 65536.0);

    /* --- check named targets --- */
    struct { const char *name; target_fn fn; } targets[] = {
        { "parity4",         parity4      },
        { "majority4",       majority4    },
        { "and4",            and4         },
        { "or4",             or4          },
        { "(aXORb)AND(cANDd)", xor_a_and  },
    };

    printf("\ntargets, and which pool tasks realise them:\n");
    for (unsigned i = 0; i < sizeof targets / sizeof targets[0]; ++i) {
        uint16_t fp = target_fingerprint(targets[i].fn);
        if (reach_has(fp)) {
            int f0 = first_triple[fp].f0,
                f1 = first_triple[fp].f1,
                g  = first_triple[fp].g;
            printf("  %-20s  YES  via ( layer0_left=task 0x%x[%s], "
                   "layer0_right=task 0x%x[%s], layer1=task 0x%x[%s] )\n",
                   targets[i].name,
                   pool[f0].task_id,
                   pool[f0].task_id == 0x6 ? "XOR" : "...",
                   pool[f1].task_id,
                   pool[f1].task_id == 0x6 ? "XOR" : "...",
                   pool[g].task_id,
                   pool[g].task_id == 0x6 ? "XOR" : "...");
        } else {
            printf("  %-20s  NO   (not realisable by any 3-position tree "
                   "over this pool)\n", targets[i].name);
        }
    }
    return 0;
}

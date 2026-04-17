/* byte_model_compound.c — growing complexity through composition.
 *
 * The vision
 *   Every tiny expert is still a 9-bit 2-2-1 sign net — it can only
 *   realise a 2-input boolean function. There are only 16 of those.
 *   But stack those 16 primitives into a short straight-line program
 *   (K ops, each op picks a primitive and two register inputs) and
 *   the reachable N-input boolean functions explode combinatorially.
 *
 *   The pool does not just accumulate more tasks — it gives every
 *   new target more building blocks to compose from. Growth of the
 *   pool ⇒ growth of reachable complexity. That's the whole point.
 *
 * What you get out
 *   • All 16 two-input boolean primitives found by enumeration.
 *   • Each named N-input target (3-AND, 3-MAJ, 3-XOR, 3-MUX,
 *     adder-carry, adder-sum, 4-XOR) searched by enumerating programs
 *     of length 1..K_MAX over the pool.
 *   • Minimum K needed per target, plus the program that solves it.
 *
 * Hot-path cost after search: K LUT lookups. No multiplies.
 *
 * Compile: cc -O2 -o byte_model_compound byte_model_compound.c
 * Run:     ./byte_model_compound
 */

#include <stdio.h>
#include <stdint.h>

#define PRIMITIVE_COUNT 16
#define K_MAX            3
#define MAX_INPUT_WIDTH  4
#define MAX_REGISTERS   (MAX_INPUT_WIDTH + K_MAX)

typedef struct {
    uint32_t task_id;
    uint32_t weights;
    int      lut[2][2];
} Primitive;

typedef struct { uint8_t prim_idx, a_reg, b_reg; } Op;
typedef struct { int n_ops; Op ops[K_MAX]; } Program;

/* --- 9-bit sign-network evaluator (same block as byte_model.c) -------- */

static int unpack_weight(uint32_t w, int i) {
    return ((int)((w >> i) & 1u) << 1) - 1;
}
static int sign_of(int v) { return v >= 0 ? 1 : -1; }

static int network_forward(uint32_t w, int a, int b) {
    int h0 = sign_of(unpack_weight(w,0)*a + unpack_weight(w,1)*b + unpack_weight(w,2));
    int h1 = sign_of(unpack_weight(w,3)*a + unpack_weight(w,4)*b + unpack_weight(w,5));
    return  sign_of(unpack_weight(w,6)*h0 + unpack_weight(w,7)*h1 + unpack_weight(w,8));
}

static int task_truth_2in(uint32_t task_id, int a, int b) {
    int idx = (((a>0)?1:0) << 1) | ((b>0)?1:0);
    return ((task_id >> idx) & 1u) ? 1 : -1;
}

/* --- grow primitive pool (search 512 candidates per 2-in task) -------- */

static int grow_primitive_pool(Primitive pool[PRIMITIVE_COUNT]) {
    int filled = 0;
    for (uint32_t tid = 0; tid < PRIMITIVE_COUNT; ++tid) {
        for (uint32_t c = 0; c < 512; ++c) {
            int ok = 1;
            for (int r = 0; r < 4 && ok; ++r) {
                int a = (r&2)?1:-1, b = (r&1)?1:-1;
                if (network_forward(c,a,b) != task_truth_2in(tid,a,b)) ok = 0;
            }
            if (ok) {
                pool[filled].task_id = tid;
                pool[filled].weights = c;
                for (int ai = 0; ai < 2; ++ai)
                    for (int bi = 0; bi < 2; ++bi)
                        pool[filled].lut[ai][bi] =
                            network_forward(c, ai?1:-1, bi?1:-1);
                filled++;
                break;
            }
        }
    }
    return filled;
}

/* --- straight-line program evaluation --------------------------------- */

static int program_run(const Primitive *pool, const Program *p,
                       const int *inputs, int n_inputs) {
    int regs[MAX_REGISTERS];
    for (int i = 0; i < n_inputs; ++i) regs[i] = inputs[i];
    int next = n_inputs;
    for (int k = 0; k < p->n_ops; ++k) {
        int a = regs[p->ops[k].a_reg];
        int b = regs[p->ops[k].b_reg];
        regs[next++] = pool[p->ops[k].prim_idx].lut[a>0][b>0];
    }
    return regs[next-1];
}

static int program_matches(const Primitive *pool, const Program *p,
                           uint64_t truth_table, int n_inputs) {
    int rows = 1 << n_inputs;
    for (int row = 0; row < rows; ++row) {
        int inputs[MAX_INPUT_WIDTH];
        for (int i = 0; i < n_inputs; ++i)
            inputs[i] = ((row >> (n_inputs-1-i)) & 1u) ? 1 : -1;
        int predicted = program_run(pool, p, inputs, n_inputs);
        int desired   = ((truth_table >> row) & 1u) ? 1 : -1;
        if (predicted != desired) return 0;
    }
    return 1;
}

/* --- odometer enumeration of programs of each length ------------------ */

static int search_program(const Primitive *pool, int pool_size,
                          uint64_t table, int n_inputs,
                          int k_max, Program *out) {
    Program p;
    for (int len = 1; len <= k_max; ++len) {
        p.n_ops = len;
        long total = 1;
        int regs_per_op[K_MAX];
        for (int k = 0; k < len; ++k) {
            regs_per_op[k] = n_inputs + k;
            total *= (long)pool_size * regs_per_op[k] * regs_per_op[k];
        }
        for (long idx = 0; idx < total; ++idx) {
            long rem = idx;
            for (int k = 0; k < len; ++k) {
                int r = regs_per_op[k];
                p.ops[k].prim_idx = (uint8_t)(rem % pool_size); rem /= pool_size;
                p.ops[k].a_reg    = (uint8_t)(rem % r);          rem /= r;
                p.ops[k].b_reg    = (uint8_t)(rem % r);          rem /= r;
            }
            if (program_matches(pool, &p, table, n_inputs)) {
                *out = p;
                return len;
            }
        }
    }
    return 0;
}

/* --- named compound targets ------------------------------------------- */

typedef struct { const char *name; int n_inputs; uint64_t table; } Target;

static const Target TARGETS[] = {
    /* 3-input */
    { "3-AND         ", 3, 0x80    },
    { "3-OR          ", 3, 0xfe    },
    { "3-XOR (parity)", 3, 0x96    },
    { "3-MAJ         ", 3, 0xe8    },
    { "3-MUX a?b:c   ", 3, 0xca    },
    { "adder-carry   ", 3, 0xe8    },
    { "adder-sum     ", 3, 0x96    },
    /* 4-input */
    { "4-XOR (parity)", 4, 0x6996  },
    { "4-MAJ (>=3/4) ", 4, 0xe880  },
};
#define N_TARGETS (int)(sizeof(TARGETS)/sizeof(TARGETS[0]))

static const char *prim_name(uint32_t tid) {
    static const char *n[16] = {
        "F","NOR","ANb","nb","nAb","na","XOR","NAND",
        "AND","XNOR","a","aOb","b","nAOb","OR","T"
    };
    return n[tid & 15];
}

/* --- main ------------------------------------------------------------- */

int main(void) {
    Primitive pool[PRIMITIVE_COUNT];
    int pool_size = grow_primitive_pool(pool);
    printf("primitive pool: %d / %d two-input boolean experts grown\n\n",
           pool_size, PRIMITIVE_COUNT);

    printf("%-16s   %-7s   %s\n", "target", "min K", "program");
    printf("%-16s   %-7s   %s\n", "----------------", "-----", "-------");
    int solved = 0;
    for (int t = 0; t < N_TARGETS; ++t) {
        Program p;
        int k = search_program(pool, pool_size, TARGETS[t].table,
                               TARGETS[t].n_inputs, K_MAX, &p);
        if (k == 0) {
            printf("%-16s   %-7s   unreachable within K=%d\n",
                   TARGETS[t].name, "—", K_MAX);
            continue;
        }
        solved++;
        printf("%-16s   K=%d     ", TARGETS[t].name, k);
        for (int i = 0; i < k; ++i) {
            int out_reg = TARGETS[t].n_inputs + i;
            printf("r%d=%s(r%d,r%d)%s",
                   out_reg,
                   prim_name(pool[p.ops[i].prim_idx].task_id),
                   p.ops[i].a_reg, p.ops[i].b_reg,
                   (i < k-1) ? "; " : "");
        }
        printf("\n");
    }
    printf("\nsolved %d / %d targets within K<=%d program length.\n",
           solved, N_TARGETS, K_MAX);
    printf("note: registers r0..r%d are inputs; each op appends one new register.\n",
           MAX_INPUT_WIDTH-1);
    return 0;
}

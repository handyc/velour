/* byte_model_parity.c — compose tiny solvers into bigger capability.
 *
 * Premise
 *   A single 2-input XOR solver is 9 bits of weights. It cannot
 *   compute 3-bit parity: it has only two input wires. But if we
 *   ROUTE the output of one XOR solver into a second solver, with
 *   the third bit going in on the other wire, the composition does
 *   compute 3-bit parity — and with four bits, the same block can
 *   be wired as a tree to compute 4-bit parity, and so on.
 *
 * What this shows
 *   1. Capability CAN grow by composing identical small models —
 *      provided the routing between them differs.
 *   2. After a small model is found, its entire behavior compiles
 *      to a 4-entry truth table (for a 2-input ±1 block). Runtime
 *      composition then reduces to nested array indexing, which is
 *      about as few machine instructions as you can spend per
 *      decision.
 *
 * Compile:  cc -O2 -o byte_model_parity byte_model_parity.c
 */
#include <stdio.h>
#include <stdint.h>

/* --- tiny 2-2-1 net with ±1 weights, 9 bits of state ---------------- */

/* unpack bit i of weight-word as ±1 with no branch: (bit<<1)-1 */
static inline int unpack_weight(uint32_t word, int bit_index) {
    return ((int)((word >> bit_index) & 1u) << 1) - 1;
}
static inline int sign_of(int v) { return v >= 0 ? 1 : -1; }

/* one forward pass through the 2→2→1 network with sign activation */
static int network_forward(uint32_t weights, int input_a, int input_b) {
    int hidden_0 = sign_of( unpack_weight(weights, 0) * input_a
                          + unpack_weight(weights, 1) * input_b
                          + unpack_weight(weights, 2) );
    int hidden_1 = sign_of( unpack_weight(weights, 3) * input_a
                          + unpack_weight(weights, 4) * input_b
                          + unpack_weight(weights, 5) );
    return           sign_of( unpack_weight(weights, 6) * hidden_0
                          + unpack_weight(weights, 7) * hidden_1
                          + unpack_weight(weights, 8) );
}

/* --- search: enumerate 9-bit worlds, keep the first that does XOR --- */

static uint32_t find_first_xor_solver(void) {
    const int truth_a[4]   = { -1, -1, +1, +1 };
    const int truth_b[4]   = { -1, +1, -1, +1 };
    const int xor_truth[4] = { -1, +1, +1, -1 };
    for (uint32_t candidate = 0; candidate < (1u << 9); ++candidate) {
        int matches = 1;
        for (int row = 0; row < 4 && matches; ++row)
            if (network_forward(candidate, truth_a[row], truth_b[row]) != xor_truth[row])
                matches = 0;
        if (matches) return candidate;
    }
    return (uint32_t)-1;  /* impossible — we know solutions exist */
}

/* --- compile: turn a found block into a 2x2 lookup table ------------ */
/* A 2-input ±1 block has only four distinct inputs. Once weights are
 * fixed, the whole block's behavior fits in 4 bits. This is the
 * "smallest useful form" of the model — storage AND execution.      */

typedef struct { int cell[2][2]; } Lut2x2;

static Lut2x2 compile_block(uint32_t weights) {
    Lut2x2 table;
    /* index 0 means the input was -1; index 1 means +1 */
    for (int a_idx = 0; a_idx < 2; ++a_idx)
        for (int b_idx = 0; b_idx < 2; ++b_idx)
            table.cell[a_idx][b_idx] =
                network_forward(weights, a_idx ? 1 : -1, b_idx ? 1 : -1);
    return table;
}

/* helper: read the LUT with ±1 inputs. Two comparisons, one index. */
static inline int lut_apply(const Lut2x2 *table, int input_a, int input_b) {
    return table->cell[input_a > 0][input_b > 0];
}

/* --- compositions: parity-N built from (N-1) copies of the block ---- */

/* parity3(a,b,c) = XOR(XOR(a,b), c). Two block invocations. */
static int parity_3(const Lut2x2 *block, int a, int b, int c) {
    return lut_apply(block, lut_apply(block, a, b), c);
}

/* parity4(a,b,c,d) = XOR(XOR(a,b), XOR(c,d)). Three invocations. */
static int parity_4(const Lut2x2 *block, int a, int b, int c, int d) {
    return lut_apply(block,
                     lut_apply(block, a, b),
                     lut_apply(block, c, d));
}

/* --- driver: verify against ground truth and report ---------------- */

int main(void) {
    uint32_t discovered_weights = find_first_xor_solver();
    Lut2x2   compiled_block     = compile_block(discovered_weights);

    printf("discovered 9-bit XOR solver: 0x%03x\n", discovered_weights);
    printf("compiled truth table:\n");
    printf("              b=-1  b=+1\n");
    printf("      a=-1 :  %+d    %+d\n", compiled_block.cell[0][0], compiled_block.cell[0][1]);
    printf("      a=+1 :  %+d    %+d\n", compiled_block.cell[1][0], compiled_block.cell[1][1]);
    printf("\n");

    /* --- parity3 over all 8 inputs ---------------------------- */
    int errors_3 = 0;
    for (int mask = 0; mask < 8; ++mask) {
        int a = (mask >> 0) & 1, b = (mask >> 1) & 1, c = (mask >> 2) & 1;
        int predicted = parity_3(&compiled_block, a ? 1 : -1, b ? 1 : -1, c ? 1 : -1);
        int truth     = ((a ^ b ^ c) ? +1 : -1);
        if (predicted != truth) errors_3++;
    }
    printf("parity3 (2 blocks, 18 bits, 2 lookups per decision): %d/8 correct\n",
           8 - errors_3);

    /* --- parity4 over all 16 inputs --------------------------- */
    int errors_4 = 0;
    for (int mask = 0; mask < 16; ++mask) {
        int a = (mask >> 0) & 1, b = (mask >> 1) & 1,
            c = (mask >> 2) & 1, d = (mask >> 3) & 1;
        int predicted = parity_4(&compiled_block,
                                 a ? 1 : -1, b ? 1 : -1,
                                 c ? 1 : -1, d ? 1 : -1);
        int truth     = ((a ^ b ^ c ^ d) ? +1 : -1);
        if (predicted != truth) errors_4++;
    }
    printf("parity4 (3 blocks, 27 bits, 3 lookups per decision): %d/16 correct\n",
           16 - errors_4);

    printf("\n");
    printf("same 9-bit block, wired differently, computes different functions.\n");
    printf("the capability comes from the routing, not the parameters.\n");
    return 0;
}

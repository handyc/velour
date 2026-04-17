/* byte_model_tiny_dt.c — the tiny decision tree, the humblest model.
 *
 * A decision tree here is a binary tree whose internal nodes test a
 * single input bit, and whose leaves emit ±1. At most a few nodes can
 * express any 2-to-3-input boolean function. DTs are cheap to evaluate
 * (one compare per level) and transparent (you can read off the rule).
 *
 * This experiment: hand-build three small DTs, evaluate them against
 * their targets' truth tables, and report accuracy. The DT substrate
 * (node struct + evaluator) is reused by later Casting experiments
 * (induction, forest, boosting, feedback-loop).
 *
 * No search, no training — just the data model and an accuracy pass.
 *
 * Compile: cc -O2 -o byte_model_tiny_dt byte_model_tiny_dt.c
 */

#include <stdio.h>
#include <stdint.h>

#define MAX_NODES 64

typedef struct {
    int is_leaf;
    int leaf_value;       /* ±1 when leaf */
    int split_feature;    /* 0..n-1 when internal */
    int zero_idx;         /* child when input bit = 0 */
    int one_idx;          /* child when input bit = 1 */
} DTNode;

static DTNode g_nodes[MAX_NODES];
static int    g_node_count = 0;

static int  dt_leaf(int v) {
    g_nodes[g_node_count] = (DTNode){1, v, -1, -1, -1};
    return g_node_count++;
}
static int dt_split(int feat, int z, int o) {
    g_nodes[g_node_count] = (DTNode){0, 0, feat, z, o};
    return g_node_count++;
}

static int dt_eval(int root, const int *inputs) {
    int idx = root;
    while (!g_nodes[idx].is_leaf) {
        int bit = inputs[g_nodes[idx].split_feature] > 0 ? 1 : 0;
        idx = bit ? g_nodes[idx].one_idx : g_nodes[idx].zero_idx;
    }
    return g_nodes[idx].leaf_value;
}

/* --- DT builders ------------------------------------------------------ */

static int dt_xor_2in(void) {
    /* XOR(a, b): split a; each branch splits b with opposite leaves. */
    int lp = dt_leaf(+1);
    int ln = dt_leaf(-1);
    int a0 = dt_split(1, ln, lp);     /* a=0 branch: b=0→-1, b=1→+1 */
    int a1 = dt_split(1, lp, ln);     /* a=1 branch: b=0→+1, b=1→-1 */
    return dt_split(0, a0, a1);
}

static int dt_majority_3in(void) {
    /* MAJ(a, b, c): +1 iff ≥ 2 of (a, b, c) are +1. */
    int lp = dt_leaf(+1);
    int ln = dt_leaf(-1);
    int a0_b1 = dt_split(2, ln, lp);     /* a=0,b=1: c decides */
    int a1_b0 = dt_split(2, ln, lp);     /* a=1,b=0: c decides */
    int a0    = dt_split(1, ln, a0_b1);  /* a=0: b=0 → -1, b=1 → c */
    int a1    = dt_split(1, a1_b0, lp);  /* a=1: b=0 → c, b=1 → +1 */
    return dt_split(0, a0, a1);
}

static int dt_mux_3in(void) {
    /* MUX(a, b, c) = if a then b else c. */
    int lp = dt_leaf(+1);
    int ln = dt_leaf(-1);
    int pick_c = dt_split(2, ln, lp);
    int pick_b = dt_split(1, ln, lp);
    return dt_split(0, pick_c, pick_b);
}

/* --- evaluation: run DT against a truth table ------------------------- */

static int target_bit(uint64_t table, int row) {
    return ((table >> row) & 1u) ? 1 : -1;
}

static int evaluate_dt(int root, int n_inputs, uint64_t target) {
    int rows = 1 << n_inputs;
    int correct = 0;
    for (int row = 0; row < rows; ++row) {
        int inputs[4];
        for (int i = 0; i < n_inputs; ++i)
            inputs[i] = ((row >> (n_inputs - 1 - i)) & 1) ? 1 : -1;
        int y = dt_eval(root, inputs);
        if (y == target_bit(target, row)) correct++;
    }
    return correct;
}

/* --- pretty-print tree ------------------------------------------------ */

static void print_tree(int idx, int depth, const char *axis) {
    for (int i = 0; i < depth; ++i) printf("  ");
    if (g_nodes[idx].is_leaf) {
        printf("%s leaf %+d\n", axis, g_nodes[idx].leaf_value);
        return;
    }
    printf("%s split on x%d\n", axis, g_nodes[idx].split_feature);
    print_tree(g_nodes[idx].zero_idx, depth + 1, "  0 →");
    print_tree(g_nodes[idx].one_idx,  depth + 1, "  1 →");
}

/* --- main ------------------------------------------------------------- */

typedef struct { const char *name; int n_inputs; uint64_t table;
                 int (*build)(void); } Case;

static const Case CASES[] = {
    { "XOR(a,b)     ", 2, 0x6,    dt_xor_2in      },
    { "MAJ(a,b,c)   ", 3, 0xe8,   dt_majority_3in },
    { "MUX(a?b:c)   ", 3, 0xca,   dt_mux_3in      },
};

int main(void) {
    printf("tiny decision trees: hand-crafted, evaluated row-by-row\n\n");
    for (int i = 0; i < (int)(sizeof(CASES)/sizeof(CASES[0])); ++i) {
        g_node_count = 0;
        int root = CASES[i].build();
        int rows = 1 << CASES[i].n_inputs;
        int correct = evaluate_dt(root, CASES[i].n_inputs, CASES[i].table);
        printf("target %s   accuracy %d / %d   nodes=%d\n",
               CASES[i].name, correct, rows, g_node_count);
        print_tree(root, 1, "root:");
        printf("\n");
    }
    printf("all three are exact — DTs are universal for small boolean targets.\n"
           "The substrate: a node is either a leaf ±1 or a split on x_i.\n"
           "Evaluation cost: one compare per level. This substrate is reused\n"
           "by tree-induction, tree-forest, tree-boosting, tree-feedback.\n");
    return 0;
}

/* byte_model_tree_induction.c — greedy ID3-style DT learner.
 *
 * Given labeled samples (x in {0,1}^N, y in {+1,-1}), recursively split
 * on the feature that maximises information gain. If a subset is pure,
 * emit a leaf. If no feature has positive gain but labels still mix,
 * split anyway on the first available feature — DT can still fit the
 * data once enough features are consumed, but the tree gets deep.
 *
 * The classical failure mode is N-bit parity: every single-feature
 * split has zero information gain at the root. The greedy heuristic
 * gives no hint; the tree still fits but uses every feature.
 *
 * Reports: induced tree size + training accuracy per target.
 *
 * Compile: cc -O2 -o byte_model_tree_induction byte_model_tree_induction.c -lm
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

#define N_FEATURES 4
#define N_SAMPLES  16
#define MAX_NODES  64

typedef struct {
    int features[N_FEATURES];
    int label;
} Sample;

typedef struct {
    int is_leaf;
    int leaf_value;
    int split_feature;
    int zero_idx, one_idx;
} DTNode;

static DTNode g_nodes[MAX_NODES];
static int    g_node_count = 0;

static double entropy(const Sample *s, const int *ix, int n) {
    int pos = 0;
    for (int i = 0; i < n; ++i) if (s[ix[i]].label > 0) pos++;
    int neg = n - pos;
    if (pos == 0 || neg == 0) return 0.0;
    double p = (double)pos / n, q = (double)neg / n;
    return -p * log(p) - q * log(q);
}

/* highest-gain feature among available; gain may be 0.0 */
static int best_feature(const Sample *s, const int *ix, int n,
                        const int *avail, double *out_gain) {
    double base = entropy(s, ix, n);
    int best = -1;
    double best_gain = -1.0;
    for (int f = 0; f < N_FEATURES; ++f) {
        if (!avail[f]) continue;
        int z[N_SAMPLES], o[N_SAMPLES]; int nz = 0, no = 0;
        for (int i = 0; i < n; ++i) {
            if (s[ix[i]].features[f]) o[no++] = ix[i];
            else                      z[nz++] = ix[i];
        }
        double after = 0.0;
        if (nz) after += (double)nz / n * entropy(s, z, nz);
        if (no) after += (double)no / n * entropy(s, o, no);
        double gain = base - after;
        if (gain > best_gain) { best_gain = gain; best = f; }
    }
    *out_gain = best_gain < 0 ? 0.0 : best_gain;
    return best;
}

static int emit_leaf(int value) {
    g_nodes[g_node_count] = (DTNode){1, value, -1, -1, -1};
    return g_node_count++;
}

static int majority_value(const Sample *s, const int *ix, int n) {
    int pos = 0;
    for (int i = 0; i < n; ++i) if (s[ix[i]].label > 0) pos++;
    return (pos >= n - pos) ? +1 : -1;
}

static int build_dt(const Sample *s, const int *ix, int n, const int *avail) {
    /* purity check */
    int pos = 0;
    for (int i = 0; i < n; ++i) if (s[ix[i]].label > 0) pos++;
    if (pos == 0) return emit_leaf(-1);
    if (pos == n) return emit_leaf(+1);
    /* any features available? */
    int any = 0;
    for (int f = 0; f < N_FEATURES; ++f) if (avail[f]) { any = 1; break; }
    if (!any) return emit_leaf(majority_value(s, ix, n));

    double gain;
    int f = best_feature(s, ix, n, avail, &gain);
    if (f < 0) return emit_leaf(majority_value(s, ix, n));

    /* split on f */
    int z[N_SAMPLES], o[N_SAMPLES]; int nz = 0, no = 0;
    for (int i = 0; i < n; ++i) {
        if (s[ix[i]].features[f]) o[no++] = ix[i];
        else                      z[nz++] = ix[i];
    }
    int new_avail[N_FEATURES];
    memcpy(new_avail, avail, sizeof(new_avail));
    new_avail[f] = 0;

    int slot = g_node_count++;
    int zc = build_dt(s, z, nz, new_avail);
    int oc = build_dt(s, o, no, new_avail);
    g_nodes[slot] = (DTNode){0, 0, f, zc, oc};
    return slot;
}

static int dt_eval(int root, const int *feats) {
    int idx = root;
    while (!g_nodes[idx].is_leaf)
        idx = feats[g_nodes[idx].split_feature] ? g_nodes[idx].one_idx : g_nodes[idx].zero_idx;
    return g_nodes[idx].leaf_value;
}

static void generate_samples(Sample *s, uint64_t table) {
    for (int row = 0; row < N_SAMPLES; ++row) {
        s[row].label = ((table >> row) & 1) ? +1 : -1;
        for (int f = 0; f < N_FEATURES; ++f)
            s[row].features[f] = (row >> (N_FEATURES - 1 - f)) & 1;
    }
}

static int accuracy(int root, const Sample *s, int n) {
    int correct = 0;
    for (int i = 0; i < n; ++i)
        if (dt_eval(root, s[i].features) == s[i].label) correct++;
    return correct;
}

static int count_leaves(int root) {
    if (g_nodes[root].is_leaf) return 1;
    return count_leaves(g_nodes[root].zero_idx) + count_leaves(g_nodes[root].one_idx);
}

static int tree_depth(int root) {
    if (g_nodes[root].is_leaf) return 0;
    int a = tree_depth(g_nodes[root].zero_idx);
    int b = tree_depth(g_nodes[root].one_idx);
    return 1 + (a > b ? a : b);
}

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

static void run_case(const char *name, uint64_t table) {
    Sample s[N_SAMPLES];
    int ix[N_SAMPLES];
    generate_samples(s, table);
    for (int i = 0; i < N_SAMPLES; ++i) ix[i] = i;
    int avail[N_FEATURES] = {1,1,1,1};
    g_node_count = 0;
    int root = build_dt(s, ix, N_SAMPLES, avail);
    int correct = accuracy(root, s, N_SAMPLES);
    int leaves = count_leaves(root);
    int depth  = tree_depth(root);
    printf("target %-15s   acc %2d / %d   nodes=%2d   leaves=%2d   depth=%d\n",
           name, correct, N_SAMPLES, g_node_count, leaves, depth);
    print_tree(root, 1, "root:");
    printf("\n");
}

int main(void) {
    printf("ID3 greedy induction over 4-input boolean targets (16 samples each)\n\n");
    run_case("4-MAJ (>=3)",      0xe880);
    run_case("4-threshold 2",    0xfee8);
    run_case("4-OR",             0xfffe);
    run_case("4-AND",            0x8000);
    run_case("4-XOR (parity)",   0x6996);
    printf("Observations:\n"
           "  - Threshold functions (MAJ, OR, AND) give large root-split gain;\n"
           "    induction produces small trees.\n"
           "  - Parity (XOR) gives zero gain at every feature; the induced\n"
           "    tree must consume every feature to separate all 16 rows.\n"
           "    DTs CAN fit it, they just can't exploit it.\n");
    return 0;
}

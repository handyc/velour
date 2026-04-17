/* byte_model_tree_forest.c — bagging: a forest of tiny decision trees.
 *
 * Training data: a 4-input boolean target (16 rows, true labels).
 * Corruption:    flip K random labels in training to simulate noise.
 * Single tree:   ID3 on the corrupted set; tests against the clean rows.
 * Forest:        F trees, each trained on a bootstrap sample (16 draws
 *                with replacement from the corrupted set). Predict by
 *                majority vote.
 *
 * The thesis: a single DT happily overfits the noise, so its test
 * accuracy drops below the noiseless ceiling. Trees trained on
 * different bootstrap samples overfit DIFFERENTLY, so majority voting
 * washes out idiosyncratic errors. Forest accuracy > single-tree
 * accuracy for any noisy dataset large enough to support diverse trees.
 *
 * Compile: cc -O2 -o byte_model_tree_forest byte_model_tree_forest.c -lm
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define N_FEATURES   4
#define N_SAMPLES    16
#define FOREST_SIZE  21
#define NOISE_FLIPS   3
#define MAX_NODES    64

typedef struct { int features[N_FEATURES]; int label; } Sample;
typedef struct { int is_leaf; int v; int f; int zc; int oc; } DTNode;

/* Per-tree node pool to avoid collisions between forest members. */
static DTNode g_pool[FOREST_SIZE + 1][MAX_NODES];
static int    g_count[FOREST_SIZE + 1];

static double entropy(const Sample *s, const int *ix, int n) {
    int pos = 0;
    for (int i = 0; i < n; ++i) if (s[ix[i]].label > 0) pos++;
    int neg = n - pos;
    if (pos == 0 || neg == 0) return 0.0;
    double p = (double)pos/n, q = (double)neg/n;
    return -p*log(p) - q*log(q);
}
static int best_feature(const Sample *s, const int *ix, int n,
                        const int *avail) {
    double base = entropy(s, ix, n);
    int best = -1; double best_gain = -1.0;
    for (int f = 0; f < N_FEATURES; ++f) {
        if (!avail[f]) continue;
        int z[N_SAMPLES], o[N_SAMPLES]; int nz = 0, no = 0;
        for (int i = 0; i < n; ++i) {
            if (s[ix[i]].features[f]) o[no++] = ix[i];
            else                      z[nz++] = ix[i];
        }
        double after = 0.0;
        if (nz) after += (double)nz/n * entropy(s, z, nz);
        if (no) after += (double)no/n * entropy(s, o, no);
        double gain = base - after;
        if (gain > best_gain) { best_gain = gain; best = f; }
    }
    return best;
}

/* Random-subspace variant: at each split, only let `max_features` of the
 * currently-available features compete. Key trick for diverse forests. */
static int best_feature_rand(const Sample *s, const int *ix, int n,
                             const int *avail, int max_features) {
    int cand[N_FEATURES]; int nc = 0;
    for (int f = 0; f < N_FEATURES; ++f) if (avail[f]) cand[nc++] = f;
    if (nc == 0) return -1;
    for (int i = nc - 1; i > 0; --i) {
        int j = rand() % (i + 1);
        int tmp = cand[i]; cand[i] = cand[j]; cand[j] = tmp;
    }
    int keep = nc < max_features ? nc : max_features;
    int subset[N_FEATURES] = {0};
    for (int i = 0; i < keep; ++i) subset[cand[i]] = 1;
    return best_feature(s, ix, n, subset);
}
static int emit_leaf(int tree, int v) {
    int idx = g_count[tree]++;
    g_pool[tree][idx] = (DTNode){1, v, -1, -1, -1};
    return idx;
}
static int majority(const Sample *s, const int *ix, int n) {
    int pos = 0;
    for (int i = 0; i < n; ++i) if (s[ix[i]].label > 0) pos++;
    return (pos >= n - pos) ? +1 : -1;
}
static int build(int tree, const Sample *s, const int *ix, int n,
                 const int *avail, int max_features) {
    int pos = 0;
    for (int i = 0; i < n; ++i) if (s[ix[i]].label > 0) pos++;
    if (pos == 0) return emit_leaf(tree, -1);
    if (pos == n) return emit_leaf(tree, +1);
    int any = 0;
    for (int f = 0; f < N_FEATURES; ++f) if (avail[f]) { any = 1; break; }
    if (!any) return emit_leaf(tree, majority(s, ix, n));
    int f = (max_features >= N_FEATURES)
        ? best_feature(s, ix, n, avail)
        : best_feature_rand(s, ix, n, avail, max_features);
    if (f < 0) return emit_leaf(tree, majority(s, ix, n));
    int z[N_SAMPLES], o[N_SAMPLES]; int nz = 0, no = 0;
    for (int i = 0; i < n; ++i) {
        if (s[ix[i]].features[f]) o[no++] = ix[i];
        else                      z[nz++] = ix[i];
    }
    int na[N_FEATURES]; memcpy(na, avail, sizeof(na)); na[f] = 0;
    int slot = g_count[tree]++;
    int zc = build(tree, s, z, nz, na, max_features);
    int oc = build(tree, s, o, no, na, max_features);
    g_pool[tree][slot] = (DTNode){0, 0, f, zc, oc};
    return slot;
}
static int eval_tree(int tree, int root, const int *feats) {
    int idx = root;
    while (!g_pool[tree][idx].is_leaf)
        idx = feats[g_pool[tree][idx].f] ? g_pool[tree][idx].oc : g_pool[tree][idx].zc;
    return g_pool[tree][idx].v;
}

/* --- data helpers ----------------------------------------------------- */

static void generate_clean(Sample *s, uint64_t table) {
    for (int row = 0; row < N_SAMPLES; ++row) {
        s[row].label = ((table >> row) & 1) ? +1 : -1;
        for (int f = 0; f < N_FEATURES; ++f)
            s[row].features[f] = (row >> (N_FEATURES - 1 - f)) & 1;
    }
}
static void flip_labels(Sample *s, int k) {
    int used[N_SAMPLES] = {0};
    for (int i = 0; i < k; ++i) {
        int r;
        do { r = rand() % N_SAMPLES; } while (used[r]);
        used[r] = 1;
        s[r].label = -s[r].label;
    }
}

/* --- runs ------------------------------------------------------------- */

static void run_case(const char *name, uint64_t table) {
    Sample clean[N_SAMPLES], train[N_SAMPLES];
    generate_clean(clean, table);
    memcpy(train, clean, sizeof train);
    flip_labels(train, NOISE_FLIPS);

    /* Which rows are corrupted? */
    int flipped_mask = 0;
    for (int i = 0; i < N_SAMPLES; ++i)
        if (train[i].label != clean[i].label) flipped_mask |= (1 << i);

    /* single tree: full feature set, no bootstrap */
    g_count[0] = 0;
    int ix[N_SAMPLES]; for (int i = 0; i < N_SAMPLES; ++i) ix[i] = i;
    int avail[N_FEATURES] = {1,1,1,1};
    int root_single = build(0, train, ix, N_SAMPLES, avail, N_FEATURES);
    int single_correct = 0;
    for (int i = 0; i < N_SAMPLES; ++i)
        if (eval_tree(0, root_single, clean[i].features) == clean[i].label)
            single_correct++;

    /* forest: F trees, each with bootstrap + random 2-of-4 feature subspace */
    int roots[FOREST_SIZE];
    for (int t = 0; t < FOREST_SIZE; ++t) {
        g_count[t + 1] = 0;
        int boot_ix[N_SAMPLES];
        for (int i = 0; i < N_SAMPLES; ++i) boot_ix[i] = rand() % N_SAMPLES;
        int aa[N_FEATURES] = {1,1,1,1};
        roots[t] = build(t + 1, train, boot_ix, N_SAMPLES, aa, 2);
    }
    int forest_correct = 0;
    for (int i = 0; i < N_SAMPLES; ++i) {
        int vote = 0;
        for (int t = 0; t < FOREST_SIZE; ++t)
            vote += eval_tree(t + 1, roots[t], clean[i].features);
        int y = vote >= 0 ? +1 : -1;
        if (y == clean[i].label) forest_correct++;
    }

    printf("target %-16s  flipped rows: 0x%04x (%d / %d)\n",
           name, flipped_mask, NOISE_FLIPS, N_SAMPLES);
    printf("  single tree          test acc: %2d / %d\n",
           single_correct, N_SAMPLES);
    printf("  forest  (F=%d vote)  test acc: %2d / %d\n\n",
           FOREST_SIZE, forest_correct, N_SAMPLES);
}

int main(void) {
    srand(42);
    printf("bagging: single tree vs %d-tree forest on noisy 4-input targets\n"
           "(training labels corrupted by %d random flips; test on clean truth)\n\n",
           FOREST_SIZE, NOISE_FLIPS);
    run_case("4-MAJ (>=3)",   0xe880);
    run_case("4-threshold 2", 0xfee8);
    run_case("4-OR",          0xfffe);
    run_case("4-AND",         0x8000);
    printf("Typical result: forest accuracy >= single-tree accuracy. Each\n"
           "bootstrap tree overfits a DIFFERENT subset of noise; majority\n"
           "vote washes out idiosyncratic errors. On low-noise targets the\n"
           "gap narrows — there is nothing for bagging to smooth over.\n");
    return 0;
}

/* byte_model_tree_feedback.c — recurrent decision trees.
 *
 * A decision tree has 4 inputs: 3 "sensors" (external bits) and 1
 * "memory" bit that is the tree's OWN previous output. Each tick we:
 *
 *   1. Read sensors (s0, s1, s2) from a driving signal.
 *   2. Evaluate the tree with inputs [s0, s1, s2, prev_out].
 *   3. The tree's output becomes the new memory bit for next tick.
 *
 * A tree + a driving-signal pattern define a dynamical system over a
 * 4-bit state. We walk it forward and look for a fixed point (same
 * state returns) or a limit cycle. Because the state space is only
 * 2^4 = 16, any trajectory must repeat within 16 steps.
 *
 * Why this might work:
 *   - Memory lets a tree model sequential dependencies that a single
 *     static DT cannot. Simple latches / toggles / counters become
 *     expressible.
 *
 * Why it often doesn't:
 *   - Random trees usually collapse to a constant or a trivial 2-cycle
 *     — the feedback bit gets ignored, or it just alternates.
 *   - The greedy inducer (used earlier in Casting) can't train this
 *     kind of tree — we would need a training signal over sequences,
 *     not i.i.d. rows. So the experiment here just ENUMERATES a handful
 *     of hand-built recurrent trees and watches their dynamics.
 *
 * Expected finding: mostly boring. Some trees latch, some toggle, a
 * few produce 3- or 4-cycles. True "interesting" behaviour (like a
 * deterministic mod-7 counter) would need more memory bits than the
 * one we give it. This experiment is a RED flag on its own, kept as
 * a substrate for future multi-bit-memory variants.
 *
 * Compile: cc -O2 -o byte_model_tree_feedback byte_model_tree_feedback.c
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#define N_FEATURES 4   /* s0, s1, s2, prev_out */
#define MAX_NODES  32
#define MAX_STEPS  40

typedef struct { int is_leaf; int v; int f; int zc; int oc; } DTNode;

typedef struct {
    const char *name;
    DTNode      nodes[MAX_NODES];
    int         n;
    int         root;
} RecTree;

static int eval_tree(const RecTree *t, const int *feats) {
    int idx = t->root;
    while (!t->nodes[idx].is_leaf)
        idx = feats[t->nodes[idx].f] ? t->nodes[idx].oc : t->nodes[idx].zc;
    return t->nodes[idx].v;
}

/* Drive pattern: a 3-bit sensor word that cycles through a short list. */
static int pat_const[][3]    = {{0,0,0}};
static int pat_toggle[][3]   = {{0,0,0},{1,1,1}};
static int pat_walk[][3]     = {{0,0,0},{1,0,0},{0,1,0},{0,0,1},
                                 {1,1,0},{1,0,1},{0,1,1},{1,1,1}};

typedef struct { const char *name; int (*data)[3]; int len; } Drive;

static const Drive DRIVES[] = {
    { "const-000",   pat_const,  1 },
    { "alt-000-111", pat_toggle, 2 },
    { "gray-walk",   pat_walk,   8 },
};
#define N_DRIVES 3

/* --- build helpers --- */
static int leaf(RecTree *t, int v) {
    int i = t->n++; t->nodes[i] = (DTNode){1, v, -1, -1, -1}; return i;
}
static int split(RecTree *t, int f, int zc, int oc) {
    int i = t->n++; t->nodes[i] = (DTNode){0, 0, f, zc, oc}; return i;
}

/* Hand-built recurrent trees. Feature index 3 is the prev-out memory. */

/* "latch": if s0 then set, if s1 then clear, else hold. */
static RecTree make_latch(void) {
    RecTree t = { "latch(s0/s1/mem)" };
    /* s0=1 -> +1; s0=0 and s1=1 -> -1; else mem */
    int p = leaf(&t, +1);
    int n = leaf(&t, -1);
    int hold_one  = leaf(&t, +1);
    int hold_neg  = leaf(&t, -1);
    int hold      = split(&t, 3, hold_neg, hold_one);
    int s1_true   = n;
    int s1_branch = split(&t, 1, hold, s1_true);
    t.root        = split(&t, 0, s1_branch, p);
    return t;
}

/* "toggle": flip on every tick regardless of sensors. */
static RecTree make_toggle(void) {
    RecTree t = { "toggle(¬mem)" };
    int p = leaf(&t, +1);
    int n = leaf(&t, -1);
    /* mem=0 -> +1, mem=1 -> -1 */
    t.root = split(&t, 3, p, n);
    return t;
}

/* "guarded toggle": flip only if s0 is 1, else hold. */
static RecTree make_guarded(void) {
    RecTree t = { "flip-if-s0 / hold" };
    int p1 = leaf(&t, +1), n1 = leaf(&t, -1);
    int hold = split(&t, 3, n1, p1);   /* mem=0->-1, mem=1->+1 (hold) */
    int p2 = leaf(&t, +1), n2 = leaf(&t, -1);
    int flip = split(&t, 3, p2, n2);   /* mem=0->+1, mem=1->-1 (flip) */
    t.root = split(&t, 0, hold, flip);
    return t;
}

/* "majority of sensors, feedback ignored": degenerates to feed-forward. */
static RecTree make_majority(void) {
    RecTree t = { "maj(s0,s1,s2) — no mem" };
    int p = leaf(&t, +1), n = leaf(&t, -1);
    /* count 1s among s0,s1,s2 — build as a cascade */
    /* s0 * s1 * s2: split on s0, then s1, then s2 */
    int l0a = leaf(&t, -1), l0b = leaf(&t, -1);  /* s0=0,s1=0 -> both 0 branches say -1 */
    int l0c = leaf(&t, -1), l0d = leaf(&t, +1);  /* s0=0,s1=1: s2=0 no (-1), s2=1 yes (+1) */
    int l1a = leaf(&t, -1), l1b = leaf(&t, +1);  /* s0=1,s1=0: s2=0 no, s2=1 yes */
    int l1c = leaf(&t, +1), l1d = leaf(&t, +1);  /* s0=1,s1=1: both +1 */
    (void)p; (void)n;
    int b00 = split(&t, 2, l0a, l0b); /* s0=0,s1=0 */
    int b01 = split(&t, 2, l0c, l0d); /* s0=0,s1=1 */
    int b10 = split(&t, 2, l1a, l1b); /* s0=1,s1=0 */
    int b11 = split(&t, 2, l1c, l1d); /* s0=1,s1=1 */
    int a0  = split(&t, 1, b00, b01);
    int a1  = split(&t, 1, b10, b11);
    t.root  = split(&t, 0, a0, a1);
    return t;
}

/* --- trajectory walker + cycle detection --- */
static void walk(const RecTree *t, const Drive *d, int init_mem) {
    int mem = init_mem;
    /* state for cycle detection = (step_mod_drive_len, mem) packed */
    int seen[32 * 2]; int seen_n = 0; /* 2 mem states * max 32 drive-positions */
    int history[MAX_STEPS][5];        /* step, s0, s1, s2, out */
    int steps = 0;
    int cycle_start = -1, cycle_len = -1;

    for (int step = 0; step < MAX_STEPS; ++step) {
        int pos = step % d->len;
        int s0 = d->data[pos][0], s1 = d->data[pos][1], s2 = d->data[pos][2];
        int feats[4] = { s0, s1, s2, mem };
        int out = eval_tree(t, feats);
        int out_bit = (out > 0) ? 1 : 0;

        history[steps][0] = step;
        history[steps][1] = s0;
        history[steps][2] = s1;
        history[steps][3] = s2;
        history[steps][4] = out_bit;
        steps++;

        int state_key = pos * 4 + mem * 2 + out_bit;
        int i;
        for (i = 0; i < seen_n; ++i) if (seen[i] == state_key) { cycle_start = i; break; }
        if (i != seen_n) { cycle_len = seen_n - cycle_start; break; }
        if (seen_n < (int)(sizeof(seen)/sizeof(seen[0]))) seen[seen_n++] = state_key;
        mem = out_bit;
    }

    printf("tree [%s]  drive [%s]  init mem=%d\n", t->name, d->name, init_mem);
    int show = steps < 12 ? steps : 12;
    for (int i = 0; i < show; ++i)
        printf("  t=%2d  s=%d%d%d  out=%d\n",
               history[i][0], history[i][1], history[i][2], history[i][3], history[i][4]);
    if (cycle_len > 0)
        printf("  cycle detected: length %d starting at step %d\n",
               cycle_len, cycle_start);
    else
        printf("  no cycle within %d steps (unreachable; state space is finite)\n", MAX_STEPS);
    printf("\n");
}

int main(void) {
    printf("recurrent decision trees — feedback loop over 1 memory bit\n\n");

    RecTree trees[] = { make_latch(), make_toggle(), make_guarded(), make_majority() };
    int    nt      = sizeof(trees) / sizeof(trees[0]);

    for (int i = 0; i < nt; ++i) {
        walk(&trees[i], &DRIVES[0], 0);
        walk(&trees[i], &DRIVES[1], 0);
        walk(&trees[i], &DRIVES[2], 0);
    }

    printf("Observations:\n"
           "  - toggle produces a clean 2-cycle whenever mem feedback is wired.\n"
           "  - latch tracks sensors and holds state, but the behaviour is\n"
           "    fully decidable from a finite state graph (no richer dynamics).\n"
           "  - majority ignores memory entirely — output is determined by\n"
           "    the drive pattern alone (as expected).\n"
           "  - with 1 memory bit the reachable dynamics are a subset of 4-bit\n"
           "    state graphs. To get richer behaviour (counters, latches that\n"
           "    remember multiple past inputs) we would need either multiple\n"
           "    memory bits or composition of several feedback trees.\n"
           "  - this entry is marked RED — it is a substrate for future work,\n"
           "    not a working ML demonstration on its own.\n");
    return 0;
}

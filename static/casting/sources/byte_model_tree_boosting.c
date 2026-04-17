/* byte_model_tree_boosting.c — AdaBoost on 1-split decision stumps.
 *
 * Weak learner: a stump is a 1-feature threshold classifier. It picks
 * a feature and a polarity (forward or inverted); prediction is ±1
 * based on that single input bit. Weighted error is minimized across
 * all 2*N_FEATURES candidate stumps each round.
 *
 * Boosting loop (classical AdaBoost / discrete version):
 *   Initialize  w_i = 1/N
 *   For t = 1..T:
 *     Fit stump h_t to minimize sum_i w_i * 1{h_t(x_i) != y_i}
 *     α_t = 0.5 * ln((1 - err) / err)
 *     w_i *= exp(-α_t * y_i * h_t(x_i));  normalize
 *   Predict:  sign(Σ α_t * h_t(x))
 *
 * Expected finding: threshold targets (MAJ, OR, AND) boost to 100%.
 * Parity targets (XOR) do NOT — the final classifier is a linear
 * combination of single-bit stumps, which cannot represent XOR. A
 * boosted-stumps learner is exactly as expressive as a linear model
 * over the bits. This is the educational punchline.
 *
 * Compile: cc -O2 -o byte_model_tree_boosting byte_model_tree_boosting.c -lm
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

#define N_FEATURES 4
#define N_SAMPLES  16
#define T_ROUNDS   60

typedef struct { int features[N_FEATURES]; int label; } Sample;
typedef struct { int feature; int polarity; /* 0 or 1 */ } Stump;

static int stump_predict(Stump s, const int *feats) {
    int bit = feats[s.feature] ? 1 : 0;
    return s.polarity ? (bit ? +1 : -1) : (bit ? -1 : +1);
}

static Stump best_stump(const Sample *s, const double *w, int n, double *out_err) {
    Stump best = {0, 0};
    double best_err = 1e9;
    for (int f = 0; f < N_FEATURES; ++f) {
        for (int pol = 0; pol < 2; ++pol) {
            Stump cand = {f, pol};
            double err = 0;
            for (int i = 0; i < n; ++i)
                if (stump_predict(cand, s[i].features) != s[i].label) err += w[i];
            if (err < best_err) { best_err = err; best = cand; }
        }
    }
    *out_err = best_err;
    return best;
}

static void normalize(double *w, int n) {
    double sum = 0;
    for (int i = 0; i < n; ++i) sum += w[i];
    if (sum <= 0) return;
    for (int i = 0; i < n; ++i) w[i] /= sum;
}

static void generate(Sample *s, uint64_t table) {
    for (int row = 0; row < N_SAMPLES; ++row) {
        s[row].label = ((table >> row) & 1) ? +1 : -1;
        for (int f = 0; f < N_FEATURES; ++f)
            s[row].features[f] = (row >> (N_FEATURES - 1 - f)) & 1;
    }
}

static void run_case(const char *name, uint64_t table) {
    Sample s[N_SAMPLES];
    generate(s, table);
    double w[N_SAMPLES];
    for (int i = 0; i < N_SAMPLES; ++i) w[i] = 1.0 / N_SAMPLES;

    Stump stumps[T_ROUNDS];
    double alphas[T_ROUNDS];
    int    rounds_used = 0;

    printf("target %-16s\n", name);
    for (int t = 0; t < T_ROUNDS; ++t) {
        double err;
        Stump h = best_stump(s, w, N_SAMPLES, &err);
        /* if err near 0 or 1, a single stump is already perfect (or inverted-perfect). */
        if (err < 1e-9)      { alphas[t] = 4.0;   stumps[t] = h; rounds_used = t + 1; break; }
        if (err >= 0.5)      break;
        double alpha = 0.5 * log((1.0 - err) / err);
        alphas[t] = alpha; stumps[t] = h;
        for (int i = 0; i < N_SAMPLES; ++i) {
            int pred = stump_predict(h, s[i].features);
            w[i] *= exp(-alpha * s[i].label * pred);
        }
        normalize(w, N_SAMPLES);
        rounds_used = t + 1;
    }

    int correct = 0;
    for (int i = 0; i < N_SAMPLES; ++i) {
        double score = 0;
        for (int t = 0; t < rounds_used; ++t)
            score += alphas[t] * stump_predict(stumps[t], s[i].features);
        int y = score >= 0 ? +1 : -1;
        if (y == s[i].label) correct++;
    }
    printf("  rounds used: %d   training acc: %d / %d\n", rounds_used, correct, N_SAMPLES);
    for (int t = 0; t < rounds_used && t < 6; ++t)
        printf("  round %d: x%d %s  α=%.3f\n",
               t + 1, stumps[t].feature,
               stumps[t].polarity ? "→" : "¬", alphas[t]);
    if (rounds_used > 6) printf("  (... %d more rounds omitted)\n", rounds_used - 6);
    printf("\n");
}

int main(void) {
    printf("AdaBoost on 1-feature decision stumps (T=%d rounds)\n\n", T_ROUNDS);
    run_case("4-MAJ (>=3)",     0xe880);
    run_case("4-threshold 2",   0xfee8);
    run_case("4-OR",            0xfffe);
    run_case("4-AND",           0x8000);
    run_case("4-XOR (parity)",  0x6996);
    printf("Observations:\n"
           "  - Threshold targets boost to perfect accuracy quickly. Sums of\n"
           "    single-bit stumps reproduce linear thresholds.\n"
           "  - Parity gets stuck at 50%% training accuracy. A boosted stump\n"
           "    is a linear combination over 1-bit features — the XOR is not\n"
           "    in the hypothesis class. Boosting with depth-2 trees WOULD\n"
           "    learn XOR; this program uses stumps on purpose to expose the\n"
           "    representational ceiling.\n");
    return 0;
}

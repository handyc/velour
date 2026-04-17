/* byte_model_evolution.c — genetic search over Casting LUT gene space.
 *
 * This is the "evolution-based" path to extending the Casting pool.
 * Instead of exhaustive enumeration (progressive search), we keep a
 * population of random n→h→1 MLPs with ±1 weights, score each against
 * the target truth table, and apply tournament selection + elitism +
 * mutation to breed the next generation. Smaller W is a tiebreaker so
 * the best solver is compact.
 *
 * Why evolution here: exhaustive search caps at W ≤ 22 (~4 M configs).
 * For W > 22, enumeration is impractical on a laptop in reasonable
 * time. A genetic algorithm doesn't guarantee optimality, but it can
 * find solvers in much larger spaces given enough generations. This
 * is the same algorithmic family the Velour Evolution Engine uses for
 * L-system breeding; the JS port calls directly into that engine with
 * gene_type = 'lut'.
 *
 * Gene layout: identical to byte_model_progressive.c (LSB-first, per
 * hidden unit [n input weights, 1 bias], then output layer).
 *
 * Compile: cc -O2 -o byte_model_evolution byte_model_evolution.c
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_H 4
#define MAX_N 4
#define POP   48
#define GENS  800
#define TRNK  3

static int sign_(int x) { return x >= 0 ? +1 : -1; }

static int total_bits(int n, int h) {
    return (h == 0) ? (n + 1) : h * (n + 2) + 1;
}

static int forward(uint32_t bits, int n, int h, int row) {
    int xi[MAX_N];
    for (int i = 0; i < n; ++i) xi[i] = ((row >> (n - 1 - i)) & 1) ? 1 : -1;
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

typedef struct { int n, h; uint32_t bits; double score; } Agent;
typedef struct { const char *name; int n; unsigned long tt; } Target;

static uint32_t random_bits(int W) {
    uint32_t b = 0;
    for (int i = 0; i < W; ++i) if ((rand() & 1)) b |= (1u << i);
    return b;
}

static double score(uint32_t bits, int n, int h, unsigned long tt) {
    int N = 1 << n, right = 0;
    for (int r = 0; r < N; ++r) {
        int y_pred = forward(bits, n, h, r);
        int y_true = ((tt >> r) & 1) ? +1 : -1;
        if (y_pred == y_true) right++;
    }
    double s = (double)right / (double)N;
    if (s >= 1.0 - 1e-9) s = 1.0 - 0.0001 * total_bits(n, h);
    return s;
}

static Agent mutate(Agent a, double rate) {
    int W = total_bits(a.n, a.h);
    for (int i = 0; i < W; ++i) {
        if ((double)rand()/RAND_MAX < rate) a.bits ^= (1u << i);
    }
    if ((double)rand()/RAND_MAX < rate * 0.15) {
        int dir = (rand() & 1) ? +1 : -1;
        int nh = a.h + dir;
        if (nh < 0) nh = 0;
        if (nh > MAX_H) nh = MAX_H;
        if (nh != a.h) {
            int nW = total_bits(a.n, nh);
            if (nW < W) a.bits &= (nW == 32 ? 0xffffffffu : ((1u << nW) - 1u));
            else {
                for (int i = W; i < nW; ++i) {
                    if ((rand() & 1)) a.bits |= (1u << i);
                }
            }
            a.h = nh;
        }
    }
    return a;
}

static Agent tournament(Agent *pop, int popN) {
    Agent best = pop[rand() % popN];
    for (int i = 1; i < TRNK; ++i) {
        Agent c = pop[rand() % popN];
        if (c.score > best.score) best = c;
    }
    return best;
}

static int evolve_target(const Target *t, Agent *out) {
    Agent pop[POP];
    for (int i = 0; i < POP; ++i) {
        pop[i].n = t->n;
        pop[i].h = rand() % (MAX_H + 1);
        pop[i].bits = random_bits(total_bits(t->n, pop[i].h));
        pop[i].score = score(pop[i].bits, pop[i].n, pop[i].h, t->tt);
    }
    for (int gen = 0; gen < GENS; ++gen) {
        /* find elite */
        int best_i = 0;
        for (int i = 1; i < POP; ++i) if (pop[i].score > pop[best_i].score) best_i = i;
        if (pop[best_i].score >= 1.0 - 0.0001 * total_bits(t->n, MAX_H)) {
            /* got a solver (any score >= 1.0 minus max size penalty) */
            if (score(pop[best_i].bits, pop[best_i].n, pop[best_i].h, t->tt) >= 1.0 - 1e-9) {
                *out = pop[best_i];
                return gen;
            }
        }
        Agent next[POP];
        next[0] = pop[best_i];
        for (int i = 1; i < POP; ++i) {
            Agent p = tournament(pop, POP);
            Agent c = mutate(p, 0.08);
            c.score = score(c.bits, c.n, c.h, t->tt);
            next[i] = c;
        }
        memcpy(pop, next, sizeof(pop));
    }
    /* no perfect solver found */
    int best_i = 0;
    for (int i = 1; i < POP; ++i) if (pop[i].score > pop[best_i].score) best_i = i;
    *out = pop[best_i];
    return -1;
}

static Target TARGETS[] = {
    {"2-AND",  2, 0x8},     {"2-OR",   2, 0xe},     {"2-XOR",  2, 0x6},
    {"3-AND",  3, 0x80},    {"3-OR",   3, 0xfe},    {"3-MAJ",  3, 0xe8},
    {"3-MUX",  3, 0xca},    {"3-XOR",  3, 0x69},    {"4-OR",   4, 0xfffe},
    {"4-AND",  4, 0x8000},  {"4-MAJ",  4, 0xe880},  {"4-thr2", 4, 0xfee8},
    {"4-XOR",  4, 0x6996},
};
#define N_TARGETS (sizeof(TARGETS)/sizeof(TARGETS[0]))

int main(void) {
    srand((unsigned)time(NULL));
    printf("evolutionary LUT search — genetic algorithm over ±1 MLP weights\n");
    printf("population %d, generations %d, tournament %d\n\n", POP, GENS, TRNK);
    printf("%-8s  %-3s  %-4s  %-10s  %s\n", "target", "h", "W", "gens", "solver (hex)");
    printf("-----------------------------------------------------------------\n");
    int solved = 0;
    for (unsigned i = 0; i < N_TARGETS; ++i) {
        Agent a;
        int g = evolve_target(&TARGETS[i], &a);
        if (g >= 0) {
            solved++;
            printf("%-8s  %-3d  %-4d  %-10d  0x%x\n",
                   TARGETS[i].name, a.h, total_bits(a.n, a.h), g, a.bits);
        } else {
            printf("%-8s  -    -     (%d gens)   no perfect solver; best %.3f\n",
                   TARGETS[i].name, GENS, a.score);
        }
    }
    printf("\n%d / %zu targets solved.\n", solved, N_TARGETS);
    return 0;
}

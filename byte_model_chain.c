/* byte_model_chain.c — find N working models, then chain them.
 *
 * Stage 1: enumerate 9-bit bitstrings, keep the first N that solve XOR.
 * Stage 2: combine them two ways and ask — is the chain "larger"?
 *
 *   ensemble  : majority vote across all N models
 *   deep chain: feed model_i's output into model_{i+1} as x1,
 *               carrying x2 through unchanged
 */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define DEFAULT_N 10

static int sgn(int v)           { return v >= 0 ? 1 : -1; }
static int w(uint32_t m, int i) { return ((m >> i) & 1) ? 1 : -1; }

static int forward(uint32_t m, int x1, int x2) {
    int h0 = sgn(w(m,0)*x1 + w(m,1)*x2 + w(m,2));
    int h1 = sgn(w(m,3)*x1 + w(m,4)*x2 + w(m,5));
    return   sgn(w(m,6)*h0 + w(m,7)*h1 + w(m,8));
}

/* --- dynamic list of working models --- */
typedef struct { uint32_t *data; int len, cap; } ModelList;

static void list_init(ModelList *L)          { L->data = NULL; L->len = L->cap = 0; }
static void list_free(ModelList *L)          { free(L->data); }
static void list_push(ModelList *L, uint32_t m) {
    if (L->len == L->cap) {
        L->cap = L->cap ? L->cap * 2 : 8;
        L->data = realloc(L->data, L->cap * sizeof *L->data);
    }
    L->data[L->len++] = m;
}

/* --- combiners --- */
static int ensemble(const ModelList *L, int x1, int x2) {
    int s = 0;
    for (int i = 0; i < L->len; i++) s += forward(L->data[i], x1, x2);
    return sgn(s);   /* majority of ±1 outputs */
}

static int deep_chain(const ModelList *L, int x1, int x2) {
    int y = x1;
    for (int i = 0; i < L->len; i++) y = forward(L->data[i], y, x2);
    return y;
}

/* --- evaluate a (name, fn) combiner on the XOR truth table --- */
typedef int (*combiner_fn)(const ModelList *L, int x1, int x2);
static void evaluate(const char *name, const ModelList *L, combiner_fn f) {
    int X[4][2] = {{-1,-1}, {-1,1}, {1,-1}, {1,1}};
    int Y[4]    = {   -1,       1,     1,     -1     };
    int ok = 0;
    printf("  %-11s : ", name);
    for (int i = 0; i < 4; i++) {
        int y = f(L, X[i][0], X[i][1]);
        printf("(%+d,%+d)→%+d  ", X[i][0], X[i][1], y);
        if (y == Y[i]) ok++;
    }
    printf("[%d/4%s]\n", ok, ok == 4 ? " ✓" : "");
}

int main(int argc, char **argv) {
    int N = (argc > 1) ? atoi(argv[1]) : DEFAULT_N;
    if (N <= 0) N = DEFAULT_N;

    ModelList L; list_init(&L);

    int X[4][2] = {{-1,-1}, {-1,1}, {1,-1}, {1,1}};
    int Y[4]    = {   -1,       1,     1,     -1     };

    for (uint32_t m = 0; m < (1u << 9) && L.len < N; m++) {
        int ok = 1;
        for (int i = 0; i < 4 && ok; i++)
            if (forward(m, X[i][0], X[i][1]) != Y[i]) ok = 0;
        if (ok) list_push(&L, m);
    }

    printf("collected %d working models (target N = %d):\n", L.len, N);
    for (int i = 0; i < L.len; i++) printf("  [%d] 0x%03x\n", i, L.data[i]);

    printf("\nchained behaviour on XOR truth table:\n");
    evaluate("ensemble",   &L, ensemble);
    evaluate("deep chain", &L, deep_chain);

    printf("\nsize accounting:\n");
    printf("  single model : %d bits\n", 9);
    printf("  chain total  : %d bits (%d× the parameter budget)\n",
           9 * L.len, L.len);

    list_free(&L);
    return 0;
}

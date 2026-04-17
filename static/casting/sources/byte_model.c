/* byte_model.c — a thought experiment made concrete.
 *
 * A "model" is just a bag of weights. If the weights are ternary
 * and the architecture is fixed, the model is literally a short
 * bitstring. Enumerate every bitstring, count how many happen
 * to solve XOR. Any of those is a "working model" you could have
 * stumbled onto by generating random bytes.
 *
 *   arch: 2 inputs → 2 hidden (sign activation) → 1 output
 *   weights ∈ {-1, +1}, 9 of them (4 W1 + 2 b1 + 2 W2 + 1 b2)
 *   total model size = 9 bits; search space = 512
 */
#include <stdio.h>
#include <stdint.h>

static int sgn(int v)        { return v >= 0 ? 1 : -1; }
static int w(uint32_t m, int i) { return ((m >> i) & 1) ? 1 : -1; }

static int forward(uint32_t m, int x1, int x2) {
    int h0 = sgn(w(m,0)*x1 + w(m,1)*x2 + w(m,2));
    int h1 = sgn(w(m,3)*x1 + w(m,4)*x2 + w(m,5));
    return   sgn(w(m,6)*h0 + w(m,7)*h1 + w(m,8));
}

int main(void) {
    int X[4][2]  = {{-1,-1}, {-1,1}, {1,-1}, {1,1}};
    int Y[4]     = {   -1,       1,     1,     -1     };   /* XOR, ±1 encoded */

    int hits = 0;
    uint32_t first = 0;
    for (uint32_t m = 0; m < (1u << 9); m++) {
        int ok = 1;
        for (int i = 0; i < 4 && ok; i++)
            if (forward(m, X[i][0], X[i][1]) != Y[i]) ok = 0;
        if (ok) { if (!hits) first = m; hits++; }
    }

    printf("search space : %u models (9-bit bitstrings)\n", 1u << 9);
    printf("working      : %d solve XOR\n", hits);
    printf("hit rate     : %.4f%%\n", 100.0 * hits / 512.0);
    printf("first found  : 0x%03x\n", first);
    return 0;
}

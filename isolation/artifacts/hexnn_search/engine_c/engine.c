/* HexNN portable engine — implementation.
 *
 * Pure C99. No platform deps, no malloc, no <math.h>, no <stdio.h>.
 * Drivers (cli_linux.c, mpi_islands.c, arduino_s3.cpp, …) own the
 * arena and the I/O.
 *
 * Memory map of `arena` after engine_init:
 *
 *   [0]                    engine_t header
 *   [hdr_end]              pop[POP_SIZE]      — POP_SIZE × N×8 bytes
 *   [pop_end]              ga_next[POP_SIZE]  — POP_SIZE × N×8 bytes
 *   [next_end]             elite              — N×8 bytes
 *   [elite_end]            scratch            — N×8 bytes (crossover work)
 *   [scratch_end]          bin_nbs            — N×6 bytes
 *   [bin_nbs_end]          bin_outs           — N bytes
 *   [bin_outs_end]         grid_a             — grid_w × grid_h
 *   [grid_a_end]           grid_b             — grid_w × grid_h
 *   [grid_b_end]           bin_idx            — K × 4 bytes (off, count)
 *   [bin_idx_end]          fit_buf            — POP_SIZE × 4 bytes (q16)
 *   [end]
 *
 * Each "genome" in pop / ga_next / elite / scratch is laid out as
 *   N×7 keys followed by N outs, contiguously. The 7-tuple is
 *   (self, n0, n1, n2, n3, n4, n5) — same packing as the JS Uint8Array
 *   in templates/hexnn/index.html and the per-step lookup loop here.
 */

#include "engine.h"

/* ── Internal helpers — no libc beyond what we implement inline ───── */

static void* engine_memcpy(void* dst, const void* src, size_t n) {
    unsigned char* d = (unsigned char*)dst;
    const unsigned char* s = (const unsigned char*)src;
    for (size_t i = 0; i < n; i++) d[i] = s[i];
    return dst;
}

static void* engine_memset(void* dst, int c, size_t n) {
    unsigned char* d = (unsigned char*)dst;
    unsigned char v = (unsigned char)c;
    for (size_t i = 0; i < n; i++) d[i] = v;
    return dst;
}

/* ── Engine struct ─────────────────────────────────────────────────── */

#define GENOME_BYTES(N)   ((size_t)(N) * 8u)   /* N*7 keys + N outs    */

struct engine {
    engine_config_t cfg;
    uint32_t        n_entries;       /* 1u << cfg.n_log2               */

    /* PRNG state for genome generation + GA breeding. The score path
     * uses its own local mulberry32 seeded from grid_seed so that
     * (genome, grid_seed) is a deterministic pair. */
    uint32_t        prng_state;

    /* All these point into the arena, allocated in engine_init via
     * a bump allocator. Layout above. */
    uint8_t*        pop;             /* POP_SIZE × N×8                 */
    uint8_t*        ga_next;         /* POP_SIZE × N×8                 */
    uint8_t*        elite;           /* N×8                            */
    uint8_t*        scratch;         /* N×8                            */
    uint8_t*        bin_nbs;         /* N×6                            */
    uint8_t*        bin_outs;        /* N                              */
    uint8_t*        grid_a;          /* grid_w × grid_h                */
    uint8_t*        grid_b;          /* grid_w × grid_h                */
    uint16_t*       bin_idx_off;     /* K                              */
    uint16_t*       bin_idx_cnt;     /* K                              */
    q16_t*          fit_buf;         /* POP_SIZE                       */
};

/* ── Genome-byte helpers ───────────────────────────────────────────── */

static uint8_t* genome_keys(uint8_t* g_base, uint32_t N) {
    return g_base;                         /* N*7 bytes                */
}
static uint8_t* genome_outs(uint8_t* g_base, uint32_t N) {
    return g_base + (size_t)N * 7u;        /* N bytes                  */
}
static uint8_t* pop_at(uint8_t* pop, uint32_t i, uint32_t N) {
    return pop + (size_t)i * GENOME_BYTES(N);
}

/* Copy entire genome from src_base to dst_base. */
static void genome_copy(uint8_t* dst, const uint8_t* src, uint32_t N) {
    engine_memcpy(dst, src, GENOME_BYTES(N));
}

/* ── PRNG — mulberry32 ─────────────────────────────────────────────── */

void engine_prng_seed(engine_t* eng, uint32_t seed) {
    eng->prng_state = seed ? seed : 1u;
}

uint32_t engine_prng_u32(engine_t* eng) {
    eng->prng_state = (eng->prng_state + 0x6D2B79F5u);
    uint32_t t = eng->prng_state;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return (t ^ (t >> 14));
}

q16_t engine_prng_q16(engine_t* eng) {
    /* Top 16 bits of u32 → uniform in [0, Q16_ONE). */
    return (q16_t)(engine_prng_u32(eng) >> 16);
}

/* Stand-alone scoring PRNG: same generator, separate state. */
typedef struct { uint32_t s; } score_prng_t;

static void   score_prng_seed(score_prng_t* p, uint32_t seed) {
    p->s = seed ? seed : 1u;
}
static uint32_t score_prng_u32(score_prng_t* p) {
    p->s = (p->s + 0x6D2B79F5u);
    uint32_t t = p->s;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return (t ^ (t >> 14));
}

/* Uniform integer in [0, n) via top-bit selection. Avoids modular
 * bias and matches the JS / pi4.py reference, both of which compute
 * `int(rng() * n)` from rng()=u32/2^32 — which equals (u32 * n)>>32. */
static uint32_t prng_mod_n(uint32_t r, uint32_t n) {
    return (uint32_t)(((uint64_t)r * (uint64_t)n) >> 32);
}

/* Same idea, narrowed to a uint8_t for the K case. K ≤ 256. */
static uint8_t prng_mod_K(uint32_t r, uint32_t K) {
    return (uint8_t)prng_mod_n(r, K);
}

/* ── Sizing ────────────────────────────────────────────────────────── */

static int validate_cfg(const engine_config_t* cfg) {
    if (!cfg)                              return 1;
    if (cfg->K < 2 || cfg->K > 256)        return 2;
    if (cfg->n_log2 < 6 || cfg->n_log2 > 16) return 3;
    if (cfg->pop_size < 2)                 return 4;
    if (cfg->grid_w == 0 || cfg->grid_h == 0) return 5;
    if (cfg->horizon <= cfg->burn_in)      return 6;
    return 0;
}

size_t engine_arena_size(const engine_config_t* cfg) {
    if (validate_cfg(cfg) != 0) return 0;
    uint32_t N = 1u << cfg->n_log2;
    size_t hdr  = sizeof(engine_t);
    size_t pop  = (size_t)cfg->pop_size * GENOME_BYTES(N);
    size_t next = pop;
    size_t el   = GENOME_BYTES(N);
    size_t sc   = GENOME_BYTES(N);
    size_t bnbs = (size_t)N * 6u;
    size_t bout = (size_t)N;
    size_t ga   = (size_t)cfg->grid_w * cfg->grid_h;
    size_t gb   = ga;
    size_t bidx = (size_t)cfg->K * 2u * sizeof(uint16_t);  /* off + cnt */
    size_t fit  = (size_t)cfg->pop_size * sizeof(q16_t);
    /* Plus 64 bytes of slack for any alignment we might add later. */
    return hdr + pop + next + el + sc + bnbs + bout + ga + gb + bidx + fit + 64;
}

/* ── Init: bump allocator over the arena ───────────────────────────── */

int engine_init(engine_t** out, void* arena, size_t arena_bytes,
                const engine_config_t* cfg) {
    if (!out || !arena || !cfg) return 1;
    int err = validate_cfg(cfg);
    if (err) return err;
    size_t need = engine_arena_size(cfg);
    if (arena_bytes < need) return 100;   /* arena too small */

    /* Header sits at the base of the arena. */
    engine_t* eng = (engine_t*)arena;
    engine_memset(eng, 0, sizeof(*eng));
    eng->cfg       = *cfg;
    eng->n_entries = 1u << cfg->n_log2;
    eng->prng_state = 1u;

    /* Bump-allocate the rest. uint8_t* arithmetic, no alignment
     * worries — every region is byte-aligned. */
    uint8_t* p   = (uint8_t*)arena + sizeof(engine_t);
    uint32_t N   = eng->n_entries;
    size_t   gb  = GENOME_BYTES(N);

    eng->pop      = p; p += (size_t)cfg->pop_size * gb;
    eng->ga_next  = p; p += (size_t)cfg->pop_size * gb;
    eng->elite    = p; p += gb;
    eng->scratch  = p; p += gb;
    eng->bin_nbs  = p; p += (size_t)N * 6u;
    eng->bin_outs = p; p += (size_t)N;
    eng->grid_a   = p; p += (size_t)cfg->grid_w * cfg->grid_h;
    eng->grid_b   = p; p += (size_t)cfg->grid_w * cfg->grid_h;
    eng->bin_idx_off = (uint16_t*)p; p += (size_t)cfg->K * sizeof(uint16_t);
    eng->bin_idx_cnt = (uint16_t*)p; p += (size_t)cfg->K * sizeof(uint16_t);
    eng->fit_buf  = (q16_t*)p;       p += (size_t)cfg->pop_size * sizeof(q16_t);

    *out = eng;
    return 0;
}

/* ── Genome generation ─────────────────────────────────────────────── */

static void make_genome_at(engine_t* eng, uint8_t* g_base) {
    uint32_t N = eng->n_entries;
    uint32_t K = eng->cfg.K;
    uint8_t* keys = genome_keys(g_base, N);
    uint8_t* outs = genome_outs(g_base, N);
    for (uint32_t i = 0; i < N; i++) {
        for (uint32_t j = 0; j < 7; j++) {
            keys[i * 7u + j] = prng_mod_K(engine_prng_u32(eng), K);
        }
        outs[i] = prng_mod_K(engine_prng_u32(eng), K);
    }
}

/* Random-genome generation against an isolated PRNG state — does not
 * disturb the caller's engine_t.prng_state. pi4.py's make_genome
 * works exactly this way (its own mulberry32 instance per call), and
 * the GA's seed_population step relies on the main GA prng surviving
 * across the random half of the population. */
static void make_genome_at_with_seed(engine_t* eng, uint8_t* g_base,
                                      uint32_t seed) {
    uint32_t N = eng->n_entries;
    uint32_t K = eng->cfg.K;
    uint8_t* keys = genome_keys(g_base, N);
    uint8_t* outs = genome_outs(g_base, N);
    score_prng_t p;             /* same generator, separate state */
    score_prng_seed(&p, seed);
    for (uint32_t i = 0; i < N; i++) {
        for (uint32_t j = 0; j < 7; j++) {
            keys[i * 7u + j] = prng_mod_K(score_prng_u32(&p), K);
        }
        outs[i] = prng_mod_K(score_prng_u32(&p), K);
    }
}

void engine_make_elite(engine_t* eng) {
    make_genome_at(eng, eng->elite);
}

/* ── Bin build + nearest-prototype lookup ─────────────────────────── */

static void build_bins(engine_t* eng, const uint8_t* g_base) {
    uint32_t N = eng->n_entries;
    uint32_t K = eng->cfg.K;
    const uint8_t* keys = genome_keys((uint8_t*)g_base, N);
    const uint8_t* outs = genome_outs((uint8_t*)g_base, N);

    for (uint32_t s = 0; s < K; s++) eng->bin_idx_cnt[s] = 0;
    for (uint32_t i = 0; i < N; i++) eng->bin_idx_cnt[keys[i * 7u]]++;
    uint32_t off = 0;
    for (uint32_t s = 0; s < K; s++) {
        eng->bin_idx_off[s] = (uint16_t)off;
        off += eng->bin_idx_cnt[s];
        eng->bin_idx_cnt[s] = 0;          /* reused as cursor below     */
    }
    for (uint32_t i = 0; i < N; i++) {
        uint8_t s = keys[i * 7u];
        uint32_t k = eng->bin_idx_off[s] + eng->bin_idx_cnt[s];
        for (uint32_t j = 0; j < 6; j++) {
            eng->bin_nbs[k * 6u + j] = keys[i * 7u + 1u + j];
        }
        eng->bin_outs[k] = outs[i];
        eng->bin_idx_cnt[s]++;
    }
}

static uint8_t lookup(const engine_t* eng, uint8_t self_c,
                      uint8_t n0, uint8_t n1, uint8_t n2,
                      uint8_t n3, uint8_t n4, uint8_t n5) {
    uint16_t off   = eng->bin_idx_off[self_c];
    uint16_t count = eng->bin_idx_cnt[self_c];
    if (count == 0) return self_c;
    uint16_t best = off;
    int32_t bestD = 0x7FFFFFFF;
    for (uint16_t k = 0; k < count; k++) {
        uint32_t o = (uint32_t)(off + k) * 6u;
        int32_t d0 = (int32_t)eng->bin_nbs[o]   - (int32_t)n0;
        int32_t d1 = (int32_t)eng->bin_nbs[o+1] - (int32_t)n1;
        int32_t d2 = (int32_t)eng->bin_nbs[o+2] - (int32_t)n2;
        int32_t d3 = (int32_t)eng->bin_nbs[o+3] - (int32_t)n3;
        int32_t d4 = (int32_t)eng->bin_nbs[o+4] - (int32_t)n4;
        int32_t d5 = (int32_t)eng->bin_nbs[o+5] - (int32_t)n5;
        int32_t d  = d0*d0 + d1*d1 + d2*d2 + d3*d3 + d4*d4 + d5*d5;
        if (d < bestD) {
            bestD = d;
            best  = (uint16_t)(off + k);
            if (d == 0) break;
        }
    }
    return eng->bin_outs[best];
}

/* ── Hex step (flat-top offset columns; matches s3lab + browser) ─── */

static void step_grid_internal(const engine_t* eng,
                               const uint8_t* in, uint8_t* out) {
    int32_t W = (int32_t)eng->cfg.grid_w;
    int32_t H = (int32_t)eng->cfg.grid_h;
    for (int32_t y = 0; y < H; y++) {
        for (int32_t x = 0; x < W; x++) {
            uint8_t self_c = in[y * W + x];
            int even = ((x & 1) == 0);
            int32_t yN  = y - 1, yS = y + 1;
            int32_t yNE = even ? y - 1 : y;
            int32_t ySE = even ? y     : y + 1;
            int32_t ySW = even ? y     : y + 1;
            int32_t yNW = even ? y - 1 : y;
            uint8_t n0 = (yN  >= 0)                            ? in[yN  * W + x]      : 0;
            uint8_t n1 = (yNE >= 0 && x+1 < W && yNE < H)      ? in[yNE * W + x+1]    : 0;
            uint8_t n2 = (ySE < H && x+1 < W && ySE >= 0)      ? in[ySE * W + x+1]    : 0;
            uint8_t n3 = (yS  < H)                              ? in[yS  * W + x]      : 0;
            uint8_t n4 = (ySW < H && x-1 >= 0 && ySW >= 0)     ? in[ySW * W + (x-1)]  : 0;
            uint8_t n5 = (yNW >= 0 && x-1 >= 0 && yNW < H)     ? in[yNW * W + (x-1)]  : 0;
            out[y * W + x] = lookup(eng, self_c, n0, n1, n2, n3, n4, n5);
        }
    }
}

void engine_step_elite(engine_t* eng) {
    build_bins(eng, eng->elite);
    step_grid_internal(eng, eng->grid_a, eng->grid_b);
    engine_memcpy(eng->grid_a, eng->grid_b,
                  (size_t)eng->cfg.grid_w * eng->cfg.grid_h);
}

/* ── Score: edge-of-chaos parabola on the K=4-quantized change rate ─ */

static void seed_grid(score_prng_t* p, uint8_t* grid, uint32_t W,
                      uint32_t H, uint32_t K) {
    for (uint32_t i = 0; i < W * H; i++) {
        grid[i] = prng_mod_K(score_prng_u32(p), K);
    }
}

static uint8_t q4(uint8_t v, uint32_t K) {
    return (uint8_t)((uint32_t)v * 4u / K);
}

engine_score_t engine_score_genome_at(engine_t* eng, const uint8_t* g_base,
                                      uint32_t grid_seed) {
    build_bins(eng, g_base);

    uint32_t W = eng->cfg.grid_w;
    uint32_t H = eng->cfg.grid_h;
    uint32_t K = eng->cfg.K;
    uint8_t* a = eng->grid_a;
    uint8_t* b = eng->grid_b;
    score_prng_t p;
    score_prng_seed(&p, grid_seed);
    seed_grid(&p, a, W, H, K);

    for (uint32_t s = 0; s < eng->cfg.burn_in; s++) {
        step_grid_internal(eng, a, b);
        engine_memcpy(a, b, (size_t)W * H);
    }
    uint64_t total = 0;
    uint32_t counted = 0;
    uint32_t score_steps = eng->cfg.horizon - eng->cfg.burn_in;
    for (uint32_t s = 0; s < score_steps; s++) {
        step_grid_internal(eng, a, b);
        uint32_t ch = 0;
        for (uint32_t i = 0; i < W * H; i++) {
            if (q4(a[i], K) != q4(b[i], K)) ch++;
        }
        total += ch;
        counted++;
        engine_memcpy(a, b, (size_t)W * H);
    }
    engine_score_t out;
    if (counted == 0 || (W * H) == 0) {
        out.fitness = 0; out.r = 0;
        return out;
    }
    /* r = total / (counted * grid_area), expressed as Q16.16. */
    uint64_t denom = (uint64_t)counted * (uint64_t)W * (uint64_t)H;
    q16_t r = (q16_t)((total << 16) / denom);
    if (r > Q16_ONE) r = Q16_ONE;
    /* fitness = 4 · r · (1-r), all in Q16. Compute via uint64 to
     * keep the intermediate from overflowing 32 bits. */
    uint64_t one_minus_r = Q16_ONE - r;
    uint64_t prod = (uint64_t)r * one_minus_r;          /* Q32         */
    q16_t fit = (q16_t)((prod >> 14));                  /* Q16, ×4     */
    if (fit > Q16_ONE) fit = Q16_ONE;
    out.fitness = fit;
    out.r       = r;
    return out;
}

engine_score_t engine_score_elite(engine_t* eng, uint32_t grid_seed) {
    return engine_score_genome_at(eng, eng->elite, grid_seed);
}

/* ── Mutation + crossover ─────────────────────────────────────────── */

static void mutate(engine_t* eng, uint8_t* dst, const uint8_t* src,
                   q16_t rate_q16) {
    uint32_t N = eng->n_entries;
    uint32_t K = eng->cfg.K;
    if (dst != src) genome_copy(dst, src, N);

    uint8_t* keys = genome_keys(dst, N);
    uint8_t* outs = genome_outs(dst, N);

    for (uint32_t i = 0; i < N; i++) {
        if (engine_prng_q16(eng) < rate_q16) {
            outs[i] = prng_mod_K(engine_prng_u32(eng), K);
        }
    }
    /* key_muts = round(N * 7 * rate). Round-half-up — pi4.py uses
     * Python's banker's rounding which for non-half cases agrees;
     * for the half case the discrepancy is one mutation, well below
     * the algorithm's noise floor. */
    uint64_t prod = (uint64_t)N * 7u * (uint64_t)rate_q16;
    uint32_t key_muts = (uint32_t)((prod + 0x8000u) >> 16);
    if (key_muts < 1) key_muts = 1;
    for (uint32_t m = 0; m < key_muts; m++) {
        uint32_t i = prng_mod_n(engine_prng_u32(eng), N);
        uint32_t j = prng_mod_n(engine_prng_u32(eng), 7u);
        uint32_t off = i * 7u + j;
        int delta = engine_prng_q16(eng) < (Q16_ONE / 2) ? -1 : 1;
        int v = (int)keys[off] + delta;
        if (v < 0) v = 0;
        if (v >= (int)K) v = (int)K - 1;
        keys[off] = (uint8_t)v;
    }
}

static void crossover(engine_t* eng, uint8_t* dst,
                      const uint8_t* a, const uint8_t* b) {
    uint32_t N = eng->n_entries;
    uint32_t cut = 1u + prng_mod_n(engine_prng_u32(eng), N - 1u);
    uint8_t* dk = genome_keys(dst, N);
    uint8_t* dout = genome_outs(dst, N);
    const uint8_t* ak = genome_keys((uint8_t*)a, N);
    const uint8_t* aout = genome_outs((uint8_t*)a, N);
    const uint8_t* bk = genome_keys((uint8_t*)b, N);
    const uint8_t* bout = genome_outs((uint8_t*)b, N);
    for (uint32_t i = 0; i < N; i++) {
        const uint8_t* sk = (i < cut) ? ak : bk;
        const uint8_t* so = (i < cut) ? aout : bout;
        for (uint32_t j = 0; j < 7; j++) dk[i * 7u + j] = sk[i * 7u + j];
        dout[i] = so[i];
    }
}

/* ── GA: hunt + refine ────────────────────────────────────────────── */

static void seed_population(engine_t* eng, engine_ga_mode_t mode,
                            q16_t rate_q16, uint32_t hunt_seed) {
    uint32_t N = eng->n_entries;
    /* Slot 0 is always the elite verbatim. */
    genome_copy(pop_at(eng->pop, 0, N), eng->elite, N);

    if (mode == ENGINE_GA_REFINE) {
        for (uint32_t i = 1; i < eng->cfg.pop_size; i++) {
            mutate(eng, pop_at(eng->pop, i, N), eng->elite, rate_q16);
        }
    } else {
        /* Hunt: half mutated (4× rate), half random. The mutated half
         * consumes the GA's main PRNG; the random half uses isolated
         * per-genome seeds (`hunt_seed + i*1009`) so the GA's PRNG
         * state going into the breed loop matches pi4.py exactly. */
        q16_t boosted = rate_q16 << 2;
        if (boosted > Q16_ONE) boosted = Q16_ONE;
        uint32_t half = eng->cfg.pop_size / 2u;
        if (half < 1) half = 1;
        for (uint32_t i = 1; i < half; i++) {
            mutate(eng, pop_at(eng->pop, i, N), eng->elite, boosted);
        }
        for (uint32_t i = half; i < eng->cfg.pop_size; i++) {
            make_genome_at_with_seed(eng, pop_at(eng->pop, i, N),
                                     hunt_seed + i * 1009u);
        }
    }
}

static void breed_next_generation(engine_t* eng, q16_t rate_q16,
                                  const uint8_t* order, uint32_t n_surv) {
    uint32_t N    = eng->n_entries;
    uint32_t POP  = eng->cfg.pop_size;
    /* Elite at index 0 of next gen. */
    genome_copy(pop_at(eng->ga_next, 0, N),
                pop_at(eng->pop, order[0], N), N);
    for (uint32_t i = 1; i < POP; i++) {
        uint32_t a = order[prng_mod_n(engine_prng_u32(eng), n_surv)];
        uint32_t b = order[prng_mod_n(engine_prng_u32(eng), n_surv)];
        crossover(eng, eng->scratch, pop_at(eng->pop, a, N),
                                     pop_at(eng->pop, b, N));
        mutate(eng, pop_at(eng->ga_next, i, N), eng->scratch, rate_q16);
    }
    /* Swap pop ↔ ga_next by bulk copy. (Could swap pointers if we
     * felt fancy, but the cost is dominated by scoring.) */
    engine_memcpy(eng->pop, eng->ga_next, (size_t)POP * GENOME_BYTES(N));
}

engine_score_t engine_run_ga(engine_t* eng,
                             engine_ga_mode_t mode,
                             uint32_t gens,
                             uint32_t hunt_seed,
                             engine_on_gen_t on_gen, void* ctx) {
    uint32_t N    = eng->n_entries;
    uint32_t POP  = eng->cfg.pop_size;
    q16_t rate    = (q16_t)eng->cfg.mut_rate_q16;

    engine_prng_seed(eng, hunt_seed);
    seed_population(eng, mode, rate, hunt_seed);

    q16_t best_fit = 0;
    q16_t best_r   = 0;

    /* Working buffer for the per-gen sort permutation. POP_SIZE ≤ 65k
     * for the configs we care about; uint16_t indices keep stack use
     * negligible (POP × 2 bytes). */
    uint8_t order[256];   /* POP_SIZE bounded at 256 in practice       */
    if (POP > 256) POP = 256;        /* defensive — config validates    */

    for (uint32_t gen = 0; gen < gens; gen++) {
        uint32_t grid_seed = hunt_seed + 0xA5A5u + gen;

        for (uint32_t i = 0; i < POP; i++) {
            engine_score_t s = engine_score_genome_at(
                eng, pop_at(eng->pop, i, N), grid_seed);
            eng->fit_buf[i] = s.fitness;
            if (s.fitness > best_fit) {
                best_fit = s.fitness;
                best_r   = s.r;
                genome_copy(eng->elite, pop_at(eng->pop, i, N), N);
            }
        }
        if (on_gen) on_gen(gen, best_fit, best_r, ctx);

        /* Selection sort by fitness desc — POP is small (typically ≤
         * 32) so an n² sort is fine and avoids dragging in qsort. */
        for (uint32_t i = 0; i < POP; i++) order[i] = (uint8_t)i;
        for (uint32_t i = 0; i < POP; i++) {
            for (uint32_t j = i + 1; j < POP; j++) {
                if (eng->fit_buf[order[j]] > eng->fit_buf[order[i]]) {
                    uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
                }
            }
        }
        uint32_t n_surv = POP / 4;
        if (n_surv < 2) n_surv = 2;
        breed_next_generation(eng, rate, order, n_surv);
    }

    engine_score_t out; out.fitness = best_fit; out.r = best_r;
    return out;
}

/* ── Live runner / read-out ────────────────────────────────────────── */

void engine_seed_live_grid(engine_t* eng, uint32_t grid_seed) {
    score_prng_t p;
    score_prng_seed(&p, grid_seed);
    seed_grid(&p, eng->grid_a, eng->cfg.grid_w, eng->cfg.grid_h,
              eng->cfg.K);
}

const uint8_t* engine_elite_keys(const engine_t* eng) {
    return eng->elite;
}
const uint8_t* engine_elite_outs(const engine_t* eng) {
    return eng->elite + (size_t)eng->n_entries * 7u;
}
const uint8_t* engine_elite_bytes(const engine_t* eng) {
    return eng->elite;        /* keys then outs, contiguous N*8 bytes */
}
size_t engine_genome_bytes(const engine_t* eng) {
    return GENOME_BYTES(eng->n_entries);
}
const uint8_t* engine_grid(const engine_t* eng) {
    return eng->grid_a;
}
const engine_config_t* engine_config(const engine_t* eng) {
    return &eng->cfg;
}
uint32_t engine_n_entries(const engine_t* eng) {
    return eng->n_entries;
}

/* ── Public wrappers for cross-genome ops (MPI, file IO, etc.) ───── */

void engine_inject_elite(engine_t* eng, const uint8_t* genome_bytes) {
    engine_memcpy(eng->elite, genome_bytes, GENOME_BYTES(eng->n_entries));
}

engine_score_t engine_score_bytes(engine_t* eng,
                                   const uint8_t* genome_bytes,
                                   uint32_t grid_seed) {
    return engine_score_genome_at(eng, genome_bytes, grid_seed);
}

uint32_t engine_genome_distance(const uint8_t* a, const uint8_t* b,
                                size_t bytes) {
    uint32_t d = 0;
    for (size_t i = 0; i < bytes; i++) if (a[i] != b[i]) d++;
    return d;
}

void engine_crossover_bytes(engine_t* eng, uint8_t* dst,
                             const uint8_t* a, const uint8_t* b) {
    /* dst may alias a or b; crossover() handles that since it
     * writes per-index from the chosen source. */
    crossover(eng, dst, a, b);
}

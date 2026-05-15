/* hexhunter — JavaScript port of libhexhunter.
 *
 * Pure JS, no dependencies.  Runs in browsers and Node.  Byte-for-byte
 * compatible with the C library (`hexhunter.c`) and Python port
 * (`hexhunter.py`) for the same (population, generations, rng_seed)
 * configuration.
 *
 * Designed to live on a page or in a Web Worker — the GA loop yields
 * to the event loop after every generation so the UI stays responsive.
 *
 * Public API:
 *
 *     // synchronous (returns Uint8Array of length 4096)
 *     const out = hexhunter({population: 30, generations: 40, rng_seed: 42});
 *     const out = hexhunter();                  // all defaults
 *     const r   = hexhunter_refine(out, {generations: 20});
 *     const f   = hexhunter_fitness(r);
 *
 *     // async (yields after each generation; takes onProgress callback)
 *     const out = await hexhunter_async({population: 30, generations: 40,
 *                                          progress: (g, total, best, mean, tail) => ... });
 */

(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.hexhunter_lib = factory();
}(typeof self !== 'undefined' ? self : this, function () {
'use strict';

const K              = 4;
const NSIT           = 16384;
const GENOME_BYTES   = 4096;

const DEF_POP                = 30;
const DEF_GENS               = 40;
const DEF_INIT_MUT_RATE      = 0.05;
const DEF_BREED_MUT_RATE     = 0.005;
const DEF_GRID_W             = 14;
const DEF_GRID_H             = 14;
const DEF_HORIZON            = 25;
const DEF_RNG_SEED           = 42;

const DY  = [-1, -1,  0,  0,  1,  1];
const DXE = [ 0,  1, -1,  1, -1,  0];
const DXO = [-1,  0, -1,  1,  0,  1];

/* ── Park-Miller LCG, 32-bit unsigned ─────────────────────────────── */
/* Math.imul + >>>0 give us deterministic wrap-around matching the C
 * `state * 1103515245u + 12345u` semantics.  Verified bit-for-bit
 * against hexhunter.c's hh_rng. */

function rng_make(seed) {
    return { state: ((seed | 0) === 0 ? 1 : (seed >>> 0)) };
}
function rng_u32(r) {
    r.state = (Math.imul(r.state, 1103515245) + 12345) >>> 0;
    return r.state >>> 16;
}
function rng_rand(r) {        // 0..0xFFFF, matches HH_RAND_MAX
    return rng_u32(r) & 0xFFFF;
}
function rng_unit(r) {
    return rng_rand(r) / 0xFFFF;
}

/* ── Packed-genome helpers (2 bits per situation) ─────────────────── */

function g_get(g, idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
function g_set(g, idx, v) {
    const b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}
function sit_idx(self_, n) {
    let i = self_;
    for (let k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}

/* ── Hex stepping (pointy-top, row-parity-sensitive) ─────────────── */

function step_grid(g, src, dst, gw, gh) {
    const n = [0, 0, 0, 0, 0, 0];
    for (let y = 0; y < gh; y++) {
        const dx = (y & 1) ? DXO : DXE;
        for (let x = 0; x < gw; x++) {
            const self_ = src[y * gw + x];
            for (let k = 0; k < 6; k++) {
                const yy = y + DY[k];
                const xx = x + dx[k];
                n[k] = (yy >= 0 && yy < gh && xx >= 0 && xx < gw)
                     ? src[yy * gw + xx] : 0;
            }
            dst[y * gw + x] = g_get(g, sit_idx(self_, n));
        }
    }
}

function seed_grid(grid, gw, gh, seed) {
    const r = rng_make(seed);
    const n = gw * gh;
    for (let i = 0; i < n; i++) grid[i] = rng_u32(r) & 3;
}

/* ── Class-4 fitness (smooth tent peaking at activity=0.12) ──────── */

function fitness_inner(genome, gridSeed, gw, gh, horizon) {
    const n = gw * gh;
    const a = new Uint8Array(n);
    const b = new Uint8Array(n);
    seed_grid(a, gw, gh, gridSeed);
    const act = new Float64Array(horizon);

    for (let t = 0; t < horizon; t++) {
        step_grid(genome, a, b, gw, gh);
        let changed = 0;
        for (let i = 0; i < n; i++) if (a[i] !== b[i]) changed++;
        act[t] = changed / n;
        a.set(b);
    }

    let uniform = true;
    for (let i = 1; i < n; i++) if (a[i] !== a[0]) { uniform = false; break; }
    const counts = [0, 0, 0, 0];
    for (let i = 0; i < n; i++) counts[a[i]]++;
    let diversity = 0;
    for (let c = 0; c < K; c++) if (counts[c] * 100 >= n) diversity++;

    let tailN = (horizon / 3) | 0;
    if (tailN < 1) tailN = 1;
    let avg = 0;
    for (let i = horizon - tailN; i < horizon; i++) avg += act[i];
    avg /= tailN;

    let score = 0;
    if (!uniform) score += 1.0;
    let aperiodic = false;
    for (let i = horizon - tailN; i < horizon; i++) {
        if (act[i] > 0.001) { aperiodic = true; break; }
    }
    if (aperiodic) score += 1.5;

    let activityReward;
    if (avg <= 0.12) activityReward = avg / 0.12;
    else             activityReward = (0.75 - avg) / 0.63;
    if (activityReward < 0) activityReward = 0;
    score += 2.0 * activityReward;

    if (diversity >= 2) {
        score += 0.25 * Math.min(diversity, K);
    }
    return { score: score, activity_tail: avg };
}

/* ── GA ops (use the threaded RNG, not Math.random) ──────────────── */

function mutate(dst, src, rate, r) {
    dst.set(src);
    for (let i = 0; i < NSIT; i++) {
        if (rng_unit(r) < rate) g_set(dst, i, rng_rand(r) & 3);
    }
}
function cross(dst, a, b, r) {
    const cut = 1 + (rng_rand(r) % (GENOME_BYTES - 1));
    dst.set(a.subarray(0, cut));
    dst.set(b.subarray(cut), cut);
}

function identity_genome() {
    const g = new Uint8Array(GENOME_BYTES);
    g.fill(0x00, 0,    1024);
    g.fill(0x55, 1024, 2048);
    g.fill(0xAA, 2048, 3072);
    g.fill(0xFF, 3072, 4096);
    return g;
}

/* ── Config resolution (unset/zero → default) ────────────────────── */

function resolve(cfg) {
    cfg = cfg || {};
    const c = {};
    c.population          = cfg.population          > 0    ? cfg.population          : DEF_POP;
    c.generations         = cfg.generations         > 0    ? cfg.generations         : DEF_GENS;
    c.init_mutation_rate  = cfg.init_mutation_rate  > 0    ? cfg.init_mutation_rate  : DEF_INIT_MUT_RATE;
    c.breed_mutation_rate = cfg.breed_mutation_rate > 0    ? cfg.breed_mutation_rate : DEF_BREED_MUT_RATE;
    c.grid_w              = cfg.grid_w              > 0    ? cfg.grid_w              : DEF_GRID_W;
    c.grid_h              = cfg.grid_h              > 0    ? cfg.grid_h              : DEF_GRID_H;
    c.horizon             = cfg.horizon             > 0    ? cfg.horizon             : DEF_HORIZON;
    c.rng_seed            = cfg.rng_seed            != null ? (cfg.rng_seed >>> 0)   : DEF_RNG_SEED;
    c.progress            = cfg.progress || null;
    return c;
}

/* ── Core GA ─────────────────────────────────────────────────────── */

function score_and_sort(pool, fits, cfg) {
    for (let i = 0; i < pool.length; i++) {
        fits[i] = fitness_inner(pool[i], cfg.rng_seed,
                                 cfg.grid_w, cfg.grid_h, cfg.horizon).score;
    }
    /* Insertion sort by fitness descending. */
    for (let i = 1; i < pool.length; i++) {
        const fv = fits[i];
        const tmp = new Uint8Array(pool[i]);   // copy
        let j = i - 1;
        while (j >= 0 && fits[j] < fv) {
            fits[j + 1] = fits[j];
            pool[j + 1] = new Uint8Array(pool[j]);
            j--;
        }
        fits[j + 1] = fv;
        pool[j + 1] = tmp;
    }
}

function do_breed(pool, cfg, rng) {
    const half = pool.length >> 1;
    for (let i = half; i < pool.length; i++) {
        const pa = rng_rand(rng) % half;
        const pb = rng_rand(rng) % half;
        const tmp = new Uint8Array(GENOME_BYTES);
        cross(tmp, pool[pa], pool[pb], rng);
        const child = new Uint8Array(GENOME_BYTES);
        mutate(child, tmp, cfg.breed_mutation_rate, rng);
        pool[i] = child;
    }
}

function init_pool(seedGenome, cfg, rng) {
    const pop = cfg.population;
    const pool = new Array(pop);
    pool[0] = new Uint8Array(seedGenome);
    for (let i = 1; i < pop; i++) {
        const child = new Uint8Array(GENOME_BYTES);
        mutate(child, pool[0], cfg.init_mutation_rate, rng);
        pool[i] = child;
    }
    return pool;
}

function call_progress(cfg, gen, pool, fits) {
    if (!cfg.progress) return;
    let sum = 0;
    for (let i = 0; i < fits.length; i++) sum += fits[i];
    const tail = fitness_inner(pool[0], cfg.rng_seed,
                                 cfg.grid_w, cfg.grid_h, cfg.horizon).activity_tail;
    cfg.progress(gen, cfg.generations, fits[0], sum / fits.length, tail);
}

function run_sync(cfg, seedGenome) {
    const rng = rng_make(cfg.rng_seed);
    const pool = init_pool(seedGenome, cfg, rng);
    const fits = new Float64Array(cfg.population);

    for (let gen = 0; gen < cfg.generations; gen++) {
        score_and_sort(pool, fits, cfg);
        call_progress(cfg, gen + 1, pool, fits);
        do_breed(pool, cfg, rng);
    }
    score_and_sort(pool, fits, cfg);
    return new Uint8Array(pool[0]);
}

async function run_async(cfg, seedGenome) {
    const rng = rng_make(cfg.rng_seed);
    const pool = init_pool(seedGenome, cfg, rng);
    const fits = new Float64Array(cfg.population);

    for (let gen = 0; gen < cfg.generations; gen++) {
        score_and_sort(pool, fits, cfg);
        call_progress(cfg, gen + 1, pool, fits);
        do_breed(pool, cfg, rng);
        /* Yield once per generation so the host event loop runs (UI
         * stays responsive in the browser). */
        await new Promise(r => setTimeout(r, 0));
    }
    score_and_sort(pool, fits, cfg);
    return new Uint8Array(pool[0]);
}

/* ── Public API ──────────────────────────────────────────────────── */

function hexhunter(cfg) {
    return run_sync(resolve(cfg), identity_genome());
}
function hexhunter_refine(inGenome, cfg) {
    if (!(inGenome && inGenome.length === GENOME_BYTES))
        throw new Error('in_genome must be ' + GENOME_BYTES + ' bytes');
    return run_sync(resolve(cfg), new Uint8Array(inGenome));
}
function hexhunter_async(cfg) {
    return run_async(resolve(cfg), identity_genome());
}
function hexhunter_refine_async(inGenome, cfg) {
    if (!(inGenome && inGenome.length === GENOME_BYTES))
        throw new Error('in_genome must be ' + GENOME_BYTES + ' bytes');
    return run_async(resolve(cfg), new Uint8Array(inGenome));
}
function hexhunter_fitness(genome, cfg) {
    if (!(genome && genome.length === GENOME_BYTES))
        throw new Error('genome must be ' + GENOME_BYTES + ' bytes');
    const c = resolve(cfg);
    return fitness_inner(genome, c.rng_seed, c.grid_w, c.grid_h, c.horizon).score;
}

return {
    K: K, NSIT: NSIT, GENOME_BYTES: GENOME_BYTES,
    DEF_POP: DEF_POP, DEF_GENS: DEF_GENS,
    DEF_INIT_MUT_RATE: DEF_INIT_MUT_RATE,
    DEF_BREED_MUT_RATE: DEF_BREED_MUT_RATE,
    DEF_GRID_W: DEF_GRID_W, DEF_GRID_H: DEF_GRID_H,
    DEF_HORIZON: DEF_HORIZON, DEF_RNG_SEED: DEF_RNG_SEED,
    identity_genome: identity_genome,
    hexhunter: hexhunter,
    hexhunter_refine: hexhunter_refine,
    hexhunter_async: hexhunter_async,
    hexhunter_refine_async: hexhunter_refine_async,
    hexhunter_fitness: hexhunter_fitness,
};
}));

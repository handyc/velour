// engine.mjs — algorithmic port of
// isolation/artifacts/hex_ca_class4/esp32_s3_full/src/main.cpp.
//
// Same constants, same scoring, same step semantics. Anything you
// see here should map line-for-line to the C side; that's the whole
// point — the lab page is for design iteration, not firmware-level
// emulation. After you're happy with a /gpio_map.txt and /genome.bin
// in the browser, the on-device sketch will produce identical
// dynamics.

export const K           = 4;
export const NSIT        = 16384;          // K^7
export const GBYTES      = 4096;           // NSIT * 2 bits / 8
export const PAL_BYTES   = 4;
export const MAGIC_BYTES = 4;
export const TAIL_MAGIC  = 'HXC4';
export const TAIL_BYTES  = MAGIC_BYTES + PAL_BYTES + GBYTES;  // 4104

export const GRID_W      = 14;
export const GRID_H      = 14;
export const HORIZON     = 25;

export const POP         = 30;
export const GENS        = 40;
export const TSEEDS      = 3;
export const WINNERS     = 3;

// Hex offset deltas — match hunter.c.
const DY  = [-1, -1,  0,  0,  1,  1];
const DXE = [ 0,  1, -1,  1, -1,  0];
const DXO = [-1,  0, -1,  1,  0,  1];

// ── PRNG: xorshift32 (matches the C side, same algorithm) ─────────────

let prng_state = 0x9E3779B9 >>> 0;

export function seed_prng(s) {
    prng_state = (s >>> 0) || 1;
}

export function prng() {
    let x = prng_state;
    x ^= x << 13; x >>>= 0;
    x ^= x >>> 17;
    x ^= x << 5;  x >>>= 0;
    prng_state = x;
    return x;
}

export function prng_unit() {
    return prng() / 4294967296;
}

// Park-Miller LCG for grid seeding (deterministic across runs given a
// fixed grid_seed). Same generator as the C `lcg`.
let lcg_state = 0;

function lcg_seed(s) { lcg_state = (s >>> 0) || 1; }
function lcg() {
    lcg_state = (Math.imul(lcg_state, 1103515245) + 12345) >>> 0;
    return lcg_state >>> 16;
}

// ── Packed-genome accessors ───────────────────────────────────────────

export function g_get(g, idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}

export function g_set(g, idx, v) {
    const b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}

function sit_idx(self, n) {
    let i = self;
    for (let k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}

// ── Grid stepping ─────────────────────────────────────────────────────

export function seed_grid(grid, s) {
    lcg_seed(s);
    for (let i = 0; i < GRID_W * GRID_H; i++)
        grid[i] = lcg() & 3;
}

export function step_grid(genome, inGrid, outGrid) {
    const n = [0, 0, 0, 0, 0, 0];
    for (let y = 0; y < GRID_H; y++) {
        const dx = (y & 1) ? DXO : DXE;
        for (let x = 0; x < GRID_W; x++) {
            const self = inGrid[y * GRID_W + x];
            for (let k = 0; k < 6; k++) {
                const yy = y + DY[k];
                const xx = x + dx[k];
                n[k] = (yy >= 0 && yy < GRID_H && xx >= 0 && xx < GRID_W)
                     ? inGrid[yy * GRID_W + xx] : 0;
            }
            outGrid[y * GRID_W + x] = g_get(genome, sit_idx(self, n));
        }
    }
}

// ── Class-4 fitness (matches main.cpp::fitness exactly) ──────────────

const FIT_GRID_A = new Uint8Array(GRID_W * GRID_H);
const FIT_GRID_B = new Uint8Array(GRID_W * GRID_H);

export function fitness(genome, gridSeed) {
    seed_grid(FIT_GRID_A, gridSeed);
    const act = new Float64Array(HORIZON);
    const colourCounts = [0, 0, 0, 0];

    let a = FIT_GRID_A, b = FIT_GRID_B;
    for (let t = 0; t < HORIZON; t++) {
        step_grid(genome, a, b);
        let changed = 0;
        for (let i = 0; i < GRID_W * GRID_H; i++)
            if (a[i] !== b[i]) changed++;
        act[t] = changed / (GRID_W * GRID_H);
        a.set(b);   // mirror the memcpy(a, b)
    }

    let uniform = 1;
    for (let i = 1; i < GRID_W * GRID_H; i++)
        if (a[i] !== a[0]) { uniform = 0; break; }
    for (let i = 0; i < GRID_W * GRID_H; i++) colourCounts[a[i]]++;
    let diversity = 0;
    for (let c = 0; c < K; c++)
        if (colourCounts[c] * 100 >= GRID_W * GRID_H) diversity++;

    let tail_n = (HORIZON / 3) | 0;
    if (tail_n < 1) tail_n = 1;
    let avg = 0;
    for (let i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;

    let score = 0;
    if (!uniform) score += 1.0;
    let aperiodic = 0;
    for (let i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;

    let activityReward;
    if (avg <= 0.12) activityReward = avg / 0.12;
    else             activityReward = (0.75 - avg) / 0.63;
    if (activityReward < 0) activityReward = 0;
    score += 2.0 * activityReward;

    if (diversity >= 2) score += 0.25 * Math.min(diversity, K);

    return { score, tail: avg, diversity, uniform: !!uniform };
}

// ── Bootstrap genome / palette ───────────────────────────────────────

export function identity_genome() {
    const g = new Uint8Array(GBYTES);
    g.fill(0x00, 0,         1024);
    g.fill(0x55, 1024,      2048);
    g.fill(0xAA, 2048,      3072);
    g.fill(0xFF, 3072,      4096);
    return g;
}

export function invent_palette() {
    const pal = new Uint8Array(PAL_BYTES);
    for (let i = 0; i < K; ) {
        const c = ((prng() % 10) < 9)
                ? (16  + (prng() % 216))
                : (232 + (prng() % 24));
        let dup = false;
        for (let j = 0; j < i; j++) if (pal[j] === c) { dup = true; break; }
        if (!dup) pal[i++] = c;
    }
    return pal;
}

// ── GA ops ────────────────────────────────────────────────────────────

export function mutate(dst, src, rate) {
    dst.set(src);
    for (let i = 0; i < NSIT; i++) {
        if (prng_unit() < rate) g_set(dst, i, prng() & 3);
    }
}

export function cross(dst, a, b) {
    const cut = 1 + (prng() % (GBYTES - 1));
    dst.set(a.subarray(0, cut), 0);
    dst.set(b.subarray(cut),    cut);
}

export function palette_inherit(dst, a, b) {
    const src = (prng() & 1) ? a : b;
    dst.set(src);
    if ((prng() % 100) < 8) {
        const slot = prng() % K;
        const c = ((prng() % 10) < 9)
                ? (16  + (prng() % 216))
                : (232 + (prng() % 24));
        dst[slot] = c;
    }
}

// ── ANSI 256 → CSS rgb() ─────────────────────────────────────────────
//
// The ESP32 sketch emits RGB565; here we just go straight to CSS to
// keep the canvas code simple. Same value table.

const ANSI_STD = [
    [0,0,0],[128,0,0],[0,128,0],[128,128,0],
    [0,0,128],[128,0,128],[0,128,128],[192,192,192],
    [128,128,128],[255,0,0],[0,255,0],[255,255,0],
    [0,0,255],[255,0,255],[0,255,255],[255,255,255],
];
const ANSI_LVL = [0, 95, 135, 175, 215, 255];

export function ansi256_to_rgb(idx) {
    if (idx < 16) {
        return ANSI_STD[idx];
    } else if (idx < 232) {
        const i = idx - 16;
        const r = (i / 36) | 0, g = ((i % 36) / 6) | 0, b = i % 6;
        return [ANSI_LVL[r], ANSI_LVL[g], ANSI_LVL[b]];
    } else {
        let v = 8 + (idx - 232) * 10;
        if (v > 255) v = 255;
        return [v, v, v];
    }
}

export function ansi256_to_css(idx) {
    const [r, g, b] = ansi256_to_rgb(idx);
    return `rgb(${r},${g},${b})`;
}

// ── Tail (genome.bin) encode/decode ──────────────────────────────────
//
// Format: [HXC4][4-byte palette][4096-byte packed genome] = 4104 bytes.
// Byte-identical to the C sketch's /winner.bin and hunter's
// winner_<N>.bin so files round-trip with zero conversion.

export function encode_tail(palette, genome) {
    const out = new Uint8Array(TAIL_BYTES);
    for (let i = 0; i < MAGIC_BYTES; i++) out[i] = TAIL_MAGIC.charCodeAt(i);
    out.set(palette, MAGIC_BYTES);
    out.set(genome,  MAGIC_BYTES + PAL_BYTES);
    return out;
}

export function decode_tail(bytes) {
    if (bytes.length < TAIL_BYTES) {
        throw new Error(`tail too short: ${bytes.length} < ${TAIL_BYTES}`);
    }
    for (let i = 0; i < MAGIC_BYTES; i++) {
        if (bytes[i] !== TAIL_MAGIC.charCodeAt(i)) {
            throw new Error(`bad magic at byte ${i}`);
        }
    }
    const palette = bytes.slice(MAGIC_BYTES, MAGIC_BYTES + PAL_BYTES);
    const genome  = bytes.slice(MAGIC_BYTES + PAL_BYTES,
                                MAGIC_BYTES + PAL_BYTES + GBYTES);
    return { palette, genome };
}

// ── Random fallback genome (no hunt) ─────────────────────────────────

export function random_genome() {
    const g = new Uint8Array(GBYTES);
    for (let i = 0; i < GBYTES; i++) g[i] = prng() & 0xFF;
    return g;
}

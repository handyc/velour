// hexnn_engine.mjs — K-dialable nearest-neighbour hex CA engine.
//
// Extracted verbatim from templates/hexnn/index.html (the in-browser
// HexNN bench) so other sublabs can reuse it. Bit-for-bit the same
// algorithm: mulberry32 PRNG, 16,384 prototypes per genome (configurable
// via N_LOG2 below), squared-Euclidean nearest-prototype lookup,
// edge-of-chaos parabola fitness on the K=4-quantized change rate.
//
// Independent of engine.mjs (which is K=4 packed-positional, a
// completely different format). HexNN supports K dialable from 4 up
// to 256 — the engine doesn't care, just the genome generator and
// scoring metric do.
//
// The render side (hex-tiles, palette mapping, etc.) lives in the
// caller; this module is pure compute over Uint8Array buffers.

export const N_LOG2    = 14;
export const N_ENTRIES = 1 << N_LOG2;        // 16,384 prototypes per genome


// ── ANSI-256 → RGB lookup (shared with engine.mjs's table) ─────────

const ANSI_STD = [
    [0,0,0],[128,0,0],[0,128,0],[128,128,0],[0,0,128],[128,0,128],[0,128,128],[192,192,192],
    [128,128,128],[255,0,0],[0,255,0],[255,255,0],[0,0,255],[255,0,255],[0,255,255],[255,255,255],
];
const ANSI_LVL = [0, 95, 135, 175, 215, 255];

export function ansi256_rgb(idx) {
    idx &= 0xFF;
    if (idx < 16) return ANSI_STD[idx];
    if (idx < 232) {
        const i = idx - 16;
        return [ANSI_LVL[(i / 36) | 0], ANSI_LVL[((i % 36) / 6) | 0], ANSI_LVL[i % 6]];
    }
    let v = 8 + (idx - 232) * 10;
    if (v > 255) v = 255;
    return [v, v, v];
}


// ── PRNG ──────────────────────────────────────────────────────────

export function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}


// ── Genome generation ─────────────────────────────────────────────
//
// Each genome is N_ENTRIES prototypes. Each prototype is a 7-tuple
// (self, n0..n5) plus an output colour. Stored as two parallel
// Uint8Arrays for tight memory + fast access:
//   keys: Uint8Array(N_ENTRIES * 7)   — keys[i*7..i*7+6]
//   outs: Uint8Array(N_ENTRIES)       — outs[i]
//
// Plus a per-genome integer K (the colour-cardinality of THIS rule),
// dialable 4..256.

export function makeGenome(K, seed) {
    const rng = mulberry32(seed);
    const keys = new Uint8Array(N_ENTRIES * 7);
    const outs = new Uint8Array(N_ENTRIES);
    for (let i = 0; i < N_ENTRIES; i++) {
        for (let j = 0; j < 7; j++) keys[i * 7 + j] = (rng() * K) | 0;
        outs[i] = (rng() * K) | 0;
    }
    return { K, keys, outs };
}


// ── Bins ──────────────────────────────────────────────────────────
//
// Group prototypes by self-colour for fast lookup at step time. Cost
// of buildBins is O(N_ENTRIES); cost of lookup is O(N_ENTRIES / K) on
// average. At K=64 the per-cell cost drops dramatically vs a flat scan.

export function buildBins(g) {
    const K = g.K;
    const counts = new Array(K).fill(0);
    for (let i = 0; i < N_ENTRIES; i++) counts[g.keys[i * 7]]++;
    const bins = new Array(K);
    const cursor = new Array(K).fill(0);
    for (let s = 0; s < K; s++) {
        bins[s] = {
            nbs:  new Uint8Array(counts[s] * 6),
            outs: new Uint8Array(counts[s]),
            count: counts[s],
        };
    }
    for (let i = 0; i < N_ENTRIES; i++) {
        const s = g.keys[i * 7];
        const k = cursor[s]++;
        for (let j = 0; j < 6; j++) bins[s].nbs[k * 6 + j] = g.keys[i * 7 + 1 + j];
        bins[s].outs[k] = g.outs[i];
    }
    return bins;
}


// ── Lookup: nearest-prototype with squared Euclidean ─────────────

export function lookup(bins, self_c, n0, n1, n2, n3, n4, n5) {
    const bin = bins[self_c];
    if (!bin || bin.count === 0) return self_c;
    const nbs = bin.nbs;
    let best = 0, bestD = Infinity;
    for (let k = 0; k < bin.count; k++) {
        const o = k * 6;
        const d0 = nbs[o]   - n0,
              d1 = nbs[o+1] - n1,
              d2 = nbs[o+2] - n2,
              d3 = nbs[o+3] - n3,
              d4 = nbs[o+4] - n4,
              d5 = nbs[o+5] - n5;
        const d = d0*d0 + d1*d1 + d2*d2 + d3*d3 + d4*d4 + d5*d5;
        if (d < bestD) {
            bestD = d; best = k;
            if (d === 0) break;
        }
    }
    return bin.outs[best];
}


// ── Step: flat-top offset-column hex (matches s3lab + browser bench) ─

export function stepWithGenomeBins(grid, W, H, bins) {
    const nxt = new Uint8Array(W * H);
    for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
            const self_c = grid[y * W + x];
            const even = (x & 1) === 0;
            const yN  = y - 1, yS = y + 1;
            const yNE = even ? y - 1 : y, ySE = even ? y     : y + 1;
            const ySW = even ? y     : y + 1, yNW = even ? y - 1 : y;
            const n0 = (yN  >= 0)                            ? grid[yN  * W + x]     : 0;
            const n1 = (yNE >= 0 && x+1 < W && yNE < H)      ? grid[yNE * W + x+1]   : 0;
            const n2 = (ySE < H && x+1 < W && ySE >= 0)      ? grid[ySE * W + x+1]   : 0;
            const n3 = (yS  < H)                             ? grid[yS  * W + x]     : 0;
            const n4 = (ySW < H && x-1 >= 0 && ySW >= 0)     ? grid[ySW * W + x-1]   : 0;
            const n5 = (yNW >= 0 && x-1 >= 0 && yNW < H)     ? grid[yNW * W + x-1]   : 0;
            nxt[y * W + x] = lookup(bins, self_c, n0, n1, n2, n3, n4, n5);
        }
    }
    return nxt;
}


// ── Score: edge-of-chaos parabola on K=4-quantized change rate ──

export function quantize4(v, K) {
    return Math.floor(v * 4 / K);
}

export function changeRateK4(prev, cur, K) {
    let changes = 0;
    for (let i = 0; i < cur.length; i++) {
        if (quantize4(prev[i], K) !== quantize4(cur[i], K)) changes++;
    }
    return changes / cur.length;
}

export function freshGrid(W, H, K, rng) {
    const g = new Uint8Array(W * H);
    for (let i = 0; i < g.length; i++) g[i] = (rng() * K) | 0;
    return g;
}

export function score(g, W, steps, rng, burnIn) {
    const bins = buildBins(g);
    let cur = freshGrid(W, W, g.K, rng);
    for (let s = 0; s < burnIn; s++) {
        cur = stepWithGenomeBins(cur, W, W, bins);
    }
    let total = 0;
    let counted = 0;
    for (let s = 0; s < steps - burnIn; s++) {
        const nxt = stepWithGenomeBins(cur, W, W, bins);
        total += changeRateK4(cur, nxt, g.K);
        counted++;
        cur = nxt;
    }
    const r = counted > 0 ? total / counted : 0;
    return { f: 4 * r * (1 - r), r };
}


// ── GA ops: mutate + crossover ────────────────────────────────────

export function mutateGenome(g, rate, rng) {
    const K = g.K;
    const n = g.outs.length;
    const child = {
        K,
        keys: new Uint8Array(g.keys),
        outs: new Uint8Array(g.outs),
    };
    for (let i = 0; i < n; i++) {
        if (rng() < rate) child.outs[i] = (rng() * K) | 0;
    }
    const keyMutations = Math.max(1, Math.round(n * 7 * rate));
    for (let m = 0; m < keyMutations; m++) {
        const i = (rng() * n) | 0;
        const j = (rng() * 7) | 0;
        const off = i * 7 + j;
        const cur = child.keys[off];
        const delta = rng() < 0.5 ? -1 : 1;
        let v = cur + delta;
        if (v < 0) v = 0;
        if (v >= K) v = K - 1;
        child.keys[off] = v;
    }
    return child;
}

export function crossover(a, b, rng) {
    const n = a.outs.length;
    const cut = 1 + ((rng() * (n - 1)) | 0);
    const child = {
        K: a.K,
        keys: new Uint8Array(n * 7),
        outs: new Uint8Array(n),
    };
    for (let i = 0; i < n; i++) {
        const src = i < cut ? a : b;
        for (let j = 0; j < 7; j++) child.keys[i * 7 + j] = src.keys[i * 7 + j];
        child.outs[i] = src.outs[i];
    }
    return child;
}


// ── Palette helpers ───────────────────────────────────────────────
//
// Random K-element palette of ANSI-256 indices. Used for inventing a
// new palette per library entry, and for inheriting from a winner
// during tournament replacement.

export function inventPalette(K, rng) {
    const pal = new Uint8Array(K);
    for (let i = 0; i < K; i++) {
        const c = ((rng() * 10) | 0) < 9
                ? (16  + ((rng() * 216) | 0))
                : (232 + ((rng() * 24)  | 0));
        pal[i] = c;
    }
    return pal;
}


// ── Palette modes (matches /hexnn/ bench's set) ───────────────────
//
// Returns a Uint32Array of K packed RGBA values (little-endian:
// 0xAA BB GG RR). Pre-packing eliminates the per-frame ANSI lookup
// in the render loop and enables direct typed-array writes.
//
// Modes:
//   random-ansi  — each cell a random ANSI-256 index (skewed toward
//                  the 6×6×6 cube, like /hexnn/ default)
//   viridis      — perceptually-uniform purple→teal→yellow gradient
//   plasma       — purple→magenta→orange→yellow gradient
//   grayscale    — black to white
//   rainbow      — full HSL hue sweep at fixed S/L
//
// For deterministic modes (anything but random-ansi), `rng` is used
// to pick a cyclic phase shift so multiple library entries built in
// the same mode look distinct from each other while staying in-mode.

export const PALETTE_MODES = ['random-ansi', 'viridis', 'plasma', 'grayscale', 'rainbow'];

function packRGBA(r, g, b) {
    return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
}

function lerpStops(stops, t) {
    const f = t * (stops.length - 1);
    const lo = Math.floor(f);
    const hi = Math.min(stops.length - 1, lo + 1);
    const u = f - lo;
    const a = stops[lo], b = stops[hi];
    return [
        Math.round(a[0] + (b[0] - a[0]) * u),
        Math.round(a[1] + (b[1] - a[1]) * u),
        Math.round(a[2] + (b[2] - a[2]) * u),
    ];
}

const VIRIDIS_STOPS = [[68,1,84],[59,82,139],[33,144,141],[93,201,99],[253,231,37]];
const PLASMA_STOPS  = [[13,8,135],[126,3,168],[204,71,120],[248,149,64],[240,249,33]];

export function makePaletteRGBA(K, mode, rng) {
    const out = new Uint32Array(K);

    if (mode === 'viridis' || mode === 'plasma') {
        const stops = (mode === 'viridis') ? VIRIDIS_STOPS : PLASMA_STOPS;
        const phase = (rng() * K) | 0;       // cyclic shift for variety
        for (let i = 0; i < K; i++) {
            const idx = (i + phase) % K;
            const [r, g, b] = lerpStops(stops, idx / Math.max(1, K - 1));
            out[i] = packRGBA(r, g, b);
        }
        return out;
    }

    if (mode === 'grayscale') {
        const phase = (rng() * K) | 0;
        for (let i = 0; i < K; i++) {
            const idx = (i + phase) % K;
            const v = Math.round(idx / Math.max(1, K - 1) * 255);
            out[i] = packRGBA(v, v, v);
        }
        return out;
    }

    if (mode === 'rainbow') {
        const hueOff = rng() * 360;
        for (let i = 0; i < K; i++) {
            // HSL → RGB at S=L=0.5; same maths /hexnn/ uses.
            const h = ((i / Math.max(1, K)) * 360 + hueOff) % 360;
            const c = (1 - Math.abs(2 * 0.5 - 1)) * 1;
            const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
            let r = 0, g = 0, bl = 0;
            if      (h < 60)  { r = c; g = x; }
            else if (h < 120) { r = x; g = c; }
            else if (h < 180) { g = c; bl = x; }
            else if (h < 240) { g = x; bl = c; }
            else if (h < 300) { r = x; bl = c; }
            else              { r = c; bl = x; }
            const m = 0.5 - c / 2;
            out[i] = packRGBA(
                Math.round((r  + m) * 255),
                Math.round((g  + m) * 255),
                Math.round((bl + m) * 255),
            );
        }
        return out;
    }

    // random-ansi (default fallback): each cell a random ANSI-256 idx
    // skewed toward the 6×6×6 cube — same skew /hexnn/ uses.
    for (let i = 0; i < K; i++) {
        const ai = ((rng() * 10) | 0) < 9
                 ? (16  + ((rng() * 216) | 0))
                 : (232 + ((rng() * 24)  | 0));
        const [r, g, b] = ansi256_rgb(ai);
        out[i] = packRGBA(r, g, b);
    }
    return out;
}

// Convert a packed-RGBA palette back to CSS hex strings — used when
// downloading a genome as hexnn-genome-v1 JSON.
export function paletteRGBAToCssHex(palRGBA) {
    const out = new Array(palRGBA.length);
    const to8 = v => v.toString(16).padStart(2, '0');
    for (let i = 0; i < palRGBA.length; i++) {
        const v = palRGBA[i];
        const r =  v        & 0xFF;
        const g = (v >>> 8) & 0xFF;
        const b = (v >>> 16) & 0xFF;
        out[i] = '#' + to8(r) + to8(g) + to8(b);
    }
    return out;
}

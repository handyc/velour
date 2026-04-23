// Det × Evolution Engine — packed-ruleset hex CA gene handler.
//
// Dense flat-genome representation mirroring the Python
// ``automaton.packed.PackedRuleset``. A complete K-colour ruleset is
// a Uint8Array of K^7 × bits_per_cell / 8 bytes — 4096 bytes at K=4.
//
// Addressing: the 7-slot situation (self + 6 neighbours) is a 7-digit
// base-K number. Lookup is a byte fetch + 2-bit shift/mask.
//
// Compared to the sparse `hexcaHandler` in hexca_gene.mjs:
//   * Every situation has an explicit output (no identity fallback).
//   * Mutation flips one situation's output — always meaningful.
//   * Crossover is a contiguous byte-slice — no dedup/length-balancing
//     needed.
//   * Simulation is one memory fetch per cell per tick, no hash.
// The sparse and dense representations are losslessly convertible —
// the Python side uses ``PackedRuleset.from_explicit`` /
// ``.to_explicit``; this module exposes `fromExplicit` / `toExplicit`.

const K_MIN = 2;
const K_MAX = 16;

function bitsPerCell(nColors) {
    if (nColors <= 2) return 1;
    if (nColors <= 4) return 2;
    if (nColors <= 16) return 4;
    throw new Error(`n_colors=${nColors} unsupported (max ${K_MAX})`);
}

export class PackedRuleset {
    constructor(nColors = 4, data = null) {
        if (nColors < K_MIN || nColors > K_MAX) {
            throw new Error(`n_colors must be ${K_MIN}..${K_MAX}`);
        }
        this.nColors = nColors;
        this.bitsPerCell = bitsPerCell(nColors);
        this.nSituations = Math.pow(nColors, 7);
        const totalBits = this.nSituations * this.bitsPerCell;
        this.totalBytes = (totalBits + 7) >> 3;
        if (data) {
            if (data.length !== this.totalBytes) {
                throw new Error(
                    `data is ${data.length} bytes, expected ${this.totalBytes}`);
            }
            this.data = (data instanceof Uint8Array) ? data.slice()
                                                     : new Uint8Array(data);
        } else {
            this.data = new Uint8Array(this.totalBytes);
        }
        // Precompute K^6..K^0 for addressing
        this._w = [1, 1, 1, 1, 1, 1, 1];
        let w = 1;
        for (let i = 6; i >= 0; i--) {
            this._w[i] = w;
            w *= nColors;
        }
    }

    indexOf(selfC, nbs) {
        // nbs is length-6 array [n0..n5]
        return selfC * this._w[0]
             + nbs[0] * this._w[1]
             + nbs[1] * this._w[2]
             + nbs[2] * this._w[3]
             + nbs[3] * this._w[4]
             + nbs[4] * this._w[5]
             + nbs[5] * this._w[6];
    }

    situationAt(index) {
        const parts = new Array(7);
        let rem = index;
        for (let i = 0; i < 7; i++) {
            parts[i] = Math.floor(rem / this._w[i]);
            rem = rem % this._w[i];
        }
        return [parts[0], parts.slice(1)];
    }

    getByIndex(idx) {
        const totalBit = idx * this.bitsPerCell;
        const byteI = totalBit >> 3;
        const bitI = totalBit & 7;
        const mask = (1 << this.bitsPerCell) - 1;
        return (this.data[byteI] >> bitI) & mask;
    }

    setByIndex(idx, output) {
        const totalBit = idx * this.bitsPerCell;
        const byteI = totalBit >> 3;
        const bitI = totalBit & 7;
        const mask = (1 << this.bitsPerCell) - 1;
        this.data[byteI] = ((this.data[byteI] & ~(mask << bitI)) & 0xFF)
                         | ((output & mask) << bitI);
    }

    get(selfC, nbs) { return this.getByIndex(this.indexOf(selfC, nbs)); }
    set(selfC, nbs, output) { this.setByIndex(this.indexOf(selfC, nbs), output); }

    // ── Population initialisers ───────────────────────────────────────

    static random(nColors, rng) {
        const r = new PackedRuleset(nColors);
        for (let i = 0; i < r.nSituations; i++) {
            r.setByIndex(i, Math.floor(rng() * nColors));
        }
        return r;
    }

    static identity(nColors) {
        const r = new PackedRuleset(nColors);
        for (let s = 0; s < nColors; s++) {
            const base = s * Math.pow(nColors, 6);
            for (let j = 0; j < Math.pow(nColors, 6); j++) {
                r.setByIndex(base + j, s);
            }
        }
        return r;
    }

    // ── Evolutionary operators ────────────────────────────────────────

    mutate(rate, rng) {
        const child = new PackedRuleset(this.nColors, this.data);
        const expected = this.nSituations * rate;
        // If rate × nSituations is tiny, do independent per-situation
        // coin flips. If it's large, just iterate — same thing.
        for (let i = 0; i < this.nSituations; i++) {
            if (rng() < rate) {
                child.setByIndex(i, Math.floor(rng() * this.nColors));
            }
        }
        return child;
    }

    crossover(other, rng) {
        if (this.nColors !== other.nColors) {
            throw new Error('crossover between different K is nonsensical');
        }
        // Single-point byte-slice: prefix from this, suffix from other.
        const cut = 1 + Math.floor(rng() * (this.totalBytes - 1));
        const out = new Uint8Array(this.totalBytes);
        for (let i = 0; i < cut; i++) out[i] = this.data[i];
        for (let i = cut; i < this.totalBytes; i++) out[i] = other.data[i];
        return new PackedRuleset(this.nColors, out);
    }

    hamming(other) {
        if (this.nColors !== other.nColors) {
            throw new Error('hamming between different K is nonsensical');
        }
        let diff = 0;
        for (let i = 0; i < this.nSituations; i++) {
            if (this.getByIndex(i) !== other.getByIndex(i)) diff++;
        }
        return diff;
    }

    // ── Sparse-rule interop (round-trip with hexca_gene.mjs) ──────────

    static fromExplicit(rules, nColors) {
        const r = PackedRuleset.identity(nColors);
        const exactMap = new Map();
        const wildcards = [];
        for (const er of rules) {
            if (er.s === -1 || er.n.some(x => x === -1)) wildcards.push(er);
            else {
                const key = er.s * Math.pow(nColors, 6)
                    + er.n.reduce((acc, v, i) =>
                        acc + v * Math.pow(nColors, 5 - i), 0);
                exactMap.set(key, er.r);
            }
        }
        for (let idx = 0; idx < r.nSituations; idx++) {
            if (exactMap.has(idx)) { r.setByIndex(idx, exactMap.get(idx)); continue; }
            const [selfC, nbs] = r.situationAt(idx);
            for (const er of wildcards) {
                if (er.s >= 0 && er.s !== selfC) continue;
                let ok = true;
                for (let j = 0; j < 6; j++) {
                    if (er.n[j] >= 0 && er.n[j] !== nbs[j]) { ok = false; break; }
                }
                if (ok) { r.setByIndex(idx, er.r); break; }
            }
            // Else leaves identity default (self colour)
        }
        return r;
    }

    toExplicit(skipIdentity = true) {
        const out = [];
        for (let idx = 0; idx < this.nSituations; idx++) {
            const [selfC, nbs] = this.situationAt(idx);
            const r = this.getByIndex(idx);
            if (skipIdentity && r === selfC) continue;
            out.push({ s: selfC, n: nbs, r });
        }
        return out;
    }

    // ── Serialisation ─────────────────────────────────────────────────

    toHex() {
        let s = '';
        for (const b of this.data) s += b.toString(16).padStart(2, '0');
        return s;
    }

    static fromHex(hex, nColors) {
        const n = hex.length / 2;
        const bytes = new Uint8Array(n);
        for (let i = 0; i < n; i++) {
            bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
        }
        return new PackedRuleset(nColors, bytes);
    }
}

// ── Simulator ─────────────────────────────────────────────────────────

export function stepPacked(grid, W, H, packed) {
    const K = packed.nColors;
    const w0 = Math.pow(K, 6), w1 = Math.pow(K, 5), w2 = Math.pow(K, 4);
    const w3 = Math.pow(K, 3), w4 = Math.pow(K, 2), w5 = K;
    const bits = packed.bitsPerCell;
    const mask = (1 << bits) - 1;
    const data = packed.data;
    const out = new Uint8Array(W * H);
    for (let r = 0; r < H; r++) {
        for (let c = 0; c < W; c++) {
            const selfC = grid[r * W + c];
            const even = (c % 2) === 0;
            // Positional neighbours — must match the Python side exactly.
            const nR = [r - 1, even ? r - 1 : r, even ? r : r + 1,
                        r + 1, even ? r : r + 1, even ? r - 1 : r];
            const nC = [c, c + 1, c + 1, c, c - 1, c - 1];
            const nb = new Array(6);
            for (let k = 0; k < 6; k++) {
                const rr = nR[k], cc = nC[k];
                nb[k] = (rr >= 0 && rr < H && cc >= 0 && cc < W)
                    ? grid[rr * W + cc] : 0;
            }
            const idx = selfC * w0
                      + nb[0] * w1 + nb[1] * w2 + nb[2] * w3
                      + nb[3] * w4 + nb[4] * w5 + nb[5];
            const totalBit = idx * bits;
            out[r * W + c] = (data[totalBit >> 3] >> (totalBit & 7)) & mask;
        }
    }
    return out;
}

// ── Evolution Engine handler ──────────────────────────────────────────
//
// Gene shape: { packed_hex, n_colors }. Stored as hex so it serialises
// through the engine's JSON checkpoint cleanly. The handler unpacks
// once at work time, runs the sim, and measures identically to the
// sparse hexca handler — same grid seed, same W/H, same horizon,
// same class-4 score.

import {
    simulateAndAnalyze as simulateSparse,
    rawScore as sparseRawScore,
} from './hexca_gene.mjs';

const DEFAULT_SCORE_NORM = 7.0;

function seededGrid(W, H, nColors, seedStr, rngFactory) {
    // Mirror hexca_gene.mjs's seededGrid exactly so the two handlers
    // score against identical substrates.
    const rng = rngFactory(seedStr);
    const g = new Uint8Array(W * H);
    for (let i = 0; i < W * H; i++) g[i] = Math.floor(rng() * nColors);
    return g;
}

function mulberry32(seed) {
    let s = seed >>> 0;
    return function () {
        s |= 0; s = (s + 0x6D2B79F5) | 0;
        let t = Math.imul(s ^ (s >>> 15), 1 | s);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function hashString(str) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < str.length; i++) {
        h ^= str.charCodeAt(i);
        h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
}

function seededRng(seedStr) {
    return mulberry32(hashString(String(seedStr || 'det')));
}

function clampInt(v, lo, hi) {
    const n = v | 0;
    return n < lo ? lo : (n > hi ? hi : n);
}

export const packedHexcaHandler = {
    random(rng, ctx) {
        const t = (ctx && ctx.hexca_target) || {};
        const nColors = clampInt(t.n_colors || 4, 2, 4);
        const packed = PackedRuleset.random(nColors, rng);
        return { packed_hex: packed.toHex(), n_colors: nColors };
    },

    mutate(gene, rng, rate, ctx) {
        const nColors = gene.n_colors
                     || ((ctx && ctx.hexca_target && ctx.hexca_target.n_colors) || 4);
        const parent = PackedRuleset.fromHex(gene.packed_hex, nColors);
        const child = parent.mutate(rate, rng);
        return { packed_hex: child.toHex(), n_colors: nColors };
    },

    crossover(geneA, geneB, rng, ctx) {
        const nColors = geneA.n_colors || geneB.n_colors
                     || ((ctx && ctx.hexca_target && ctx.hexca_target.n_colors) || 4);
        const a = PackedRuleset.fromHex(geneA.packed_hex, nColors);
        const b = PackedRuleset.fromHex(geneB.packed_hex, nColors);
        const child = a.crossover(b, rng);
        return { packed_hex: child.toHex(), n_colors: nColors };
    },

    async work(agent, ctx) {
        const target = (ctx && ctx.hexca_target) || {};
        const W = clampInt(target.screen_width || 18, 4, 40);
        const H = clampInt(target.screen_height || 18, 4, 40);
        const nColors = clampInt(target.n_colors || 4, 2, 4);
        const horizon = clampInt(target.horizon || 30, 6, 120);
        const gridSeed = target.grid_seed || 'det-evo';

        const gene = agent.gene || {};
        const packed = PackedRuleset.fromHex(
            gene.packed_hex, gene.n_colors || nColors);

        // Measure: run horizon ticks and compute the same class-4
        // analysis the sparse handler does.
        let grid = seededGrid(W, H, nColors, gridSeed, seededRng);
        const history = new Map();
        history.set(gridKey(grid), 0);
        const activity = [];
        let period = null, enteredAt = null;
        let prev = grid;
        for (let t = 1; t <= horizon; t++) {
            const nxt = stepPacked(grid, W, H, packed);
            activity.push(activityRate(grid, nxt));
            const key = gridKey(nxt);
            const hit = history.get(key);
            if (hit !== undefined) {
                period = t - hit; enteredAt = hit;
                prev = grid; grid = nxt; break;
            }
            history.set(key, t);
            prev = grid; grid = nxt;
        }

        const uniform = grid.every((v, _, g) => v === g[0]);
        const be = blockEntropy(grid, W, H, 2);
        const dens = densityProfile(grid, nColors);
        const colorDiversity = dens.reduce((n, d) => n + (d > 0.01 ? 1 : 0), 0);
        const tailN = Math.max(1, Math.floor(activity.length / 3));
        const tail = activity.slice(-tailN);
        const activityTail = tail.length
            ? tail.reduce((s, x) => s + x, 0) / tail.length : 0;

        const analysis = {
            uniform, period, entered_at: enteredAt,
            activity_tail: +activityTail.toFixed(4),
            block_entropy: +be.toFixed(4),
            density_profile: dens.map(d => +d.toFixed(4)),
            color_diversity: colorDiversity,
            n_ticks: activity.length,
        };
        const raw = sparseRawScore(analysis, nColors);
        agent.output = `packed p=${analysis.period} a=${analysis.activity_tail} ` +
                       `be=${analysis.block_entropy} cd=${analysis.color_diversity} | ` +
                       `raw=${raw.toFixed(2)}`;
        return Math.max(0, Math.min(1, raw / DEFAULT_SCORE_NORM));
    },
};

// ── Local helpers (copies of the minimal subset from hexca_gene.mjs) ──
// Kept inline so packed_gene.mjs can be used without pulling the
// sparse handler's entire simulator into play.

function activityRate(a, b) {
    let changed = 0;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) changed++;
    return a.length ? changed / a.length : 0;
}

function blockEntropy(grid, W, H, k) {
    if (H < k || W < k) return 0;
    const counts = new Map();
    let total = 0;
    for (let r = 0; r <= H - k; r++) {
        for (let c = 0; c <= W - k; c++) {
            let key = '';
            for (let dr = 0; dr < k; dr++) {
                for (let dc = 0; dc < k; dc++) {
                    key += grid[(r + dr) * W + (c + dc)] + ',';
                }
            }
            counts.set(key, (counts.get(key) || 0) + 1);
            total++;
        }
    }
    let ent = 0;
    for (const v of counts.values()) {
        const p = v / total;
        ent -= p * Math.log2(p);
    }
    return ent;
}

function densityProfile(grid, nColors) {
    const counts = new Array(nColors).fill(0);
    for (let i = 0; i < grid.length; i++) {
        if (grid[i] >= 0 && grid[i] < nColors) counts[grid[i]]++;
    }
    if (grid.length === 0) return counts.map(() => 0);
    return counts.map(c => c / grid.length);
}

function gridKey(grid) {
    let s = '';
    for (let i = 0; i < grid.length; i++) s += String.fromCharCode(grid[i]);
    return s;
}

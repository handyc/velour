// Det × Evolution Engine — hex CA gene handler.
//
// A gene here is a list of exact-match hex rules (same shape as
// automaton.detector.step_exact + det.search._generate_rules):
//   [{ s: selfColor, n: [n0..n5], r: resultColor }]
// with -1 as the wildcard sentinel.
//
// The scoring ctx is a `hexca_target` blob carrying the fixed
// screening substrate (grid size, n_colors, horizon, grid_seed) so
// every agent in the population plays the same game. The mutate
// operator only perturbs the rule set; it does not change the target.
//
// Fitness here returns a [0, 1] normalized version of the Python-side
// _score so it plugs straight into the engine's elitist/tournament
// loop. The raw Class-4 score comes back as `agent.output` for UI.
//
// Changes to det/search.py's _generate_rules/_score should be mirrored
// here so a promote → evolve → import round trip doesn't drift in
// meaning between JS screening and Python re-scoring.

const MAX_RULES_CAP = 400;
const BE_CAP = { 2: 4.0, 3: 6.3, 4: 8.0 };
// Matches det.search._score's observed peak: sums of every positive
// contribution add up to ~6.25 in practice, so normalize by a slightly
// wider ceiling to keep the [0,1] range honest.
const SCORE_NORM = 7.0;

// ── Ruleset generator ──────────────────────────────────────────────
// Mirrors det.search._generate_rules exactly.
function generateRules(rng, nRules, nColors, wildcardPct) {
    const seen = new Set();
    const rules = [];
    let attempts = 0;
    const maxAttempts = nRules * 10;
    while (rules.length < nRules && attempts < maxAttempts) {
        attempts++;
        const s = Math.floor(rng() * nColors);
        const n = new Array(6);
        for (let i = 0; i < 6; i++) {
            if (Math.floor(rng() * 100) < wildcardPct) n[i] = -1;
            else n[i] = Math.floor(rng() * nColors);
        }
        const r = Math.floor(rng() * nColors);
        if (r === s && n.every(x => x === -1)) continue;
        const key = `${s}|${n.join(',')}|${r}`;
        if (seen.has(key)) continue;
        seen.add(key);
        rules.push({ s, n, r });
    }
    return rules;
}

// ── Step_exact (port of automaton.detector.step_exact) ─────────────
// Flattened grid is a Uint8Array of length W*H, row-major. The Python
// side uses list-of-lists; we pick flat arrays in JS for allocation
// hygiene (screening runs 40+ ticks × 400+ cells × population).
function stepExact(grid, W, H, exactMap, wildcards) {
    const next = new Uint8Array(W * H);
    for (let r = 0; r < H; r++) {
        for (let c = 0; c < W; c++) {
            const self = grid[r * W + c];
            const even = (c % 2) === 0;
            const nR = [
                r - 1,
                even ? r - 1 : r,
                even ? r : r + 1,
                r + 1,
                even ? r : r + 1,
                even ? r - 1 : r,
            ];
            const nC = [c, c + 1, c + 1, c, c - 1, c - 1];
            const nb = [0, 0, 0, 0, 0, 0];
            for (let k = 0; k < 6; k++) {
                const rr = nR[k], cc = nC[k];
                if (rr >= 0 && rr < H && cc >= 0 && cc < W) {
                    nb[k] = grid[rr * W + cc];
                } else {
                    nb[k] = 0;
                }
            }
            const key = `${self}|${nb[0]},${nb[1]},${nb[2]},${nb[3]},${nb[4]},${nb[5]}`;
            const exact = exactMap.get(key);
            if (exact !== undefined) {
                next[r * W + c] = exact;
                continue;
            }
            let result = self;
            for (const er of wildcards) {
                if (er.s >= 0 && er.s !== self) continue;
                let matched = true;
                for (let j = 0; j < 6; j++) {
                    if (er.n[j] >= 0 && er.n[j] !== nb[j]) {
                        matched = false;
                        break;
                    }
                }
                if (matched) { result = er.r; break; }
            }
            next[r * W + c] = result;
        }
    }
    return next;
}

function prepareRules(rules) {
    const exactMap = new Map();
    const wildcards = [];
    for (const er of rules) {
        if (er.s === -1 || er.n.some(x => x === -1)) {
            wildcards.push(er);
        } else {
            const key = `${er.s}|${er.n[0]},${er.n[1]},${er.n[2]},${er.n[3]},${er.n[4]},${er.n[5]}`;
            exactMap.set(key, er.r);
        }
    }
    return { exactMap, wildcards };
}

// ── Seeded grid + analysis ─────────────────────────────────────────
// mulberry32 isn't identical to Python's random.Random, so grids
// re-screened in Python will differ; the scorer is still meaningful
// because it measures the dynamics the JS engine saw. The Python
// importer re-scores against a fresh Python-seeded grid — the scores
// are expected to be close but not identical, and that is fine.
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

function seededGrid(W, H, nColors, seedStr) {
    const rng = mulberry32(hashString(String(seedStr || 'det')));
    const g = new Uint8Array(W * H);
    for (let i = 0; i < W * H; i++) g[i] = Math.floor(rng() * nColors);
    return g;
}

function isUniform(grid) {
    if (grid.length === 0) return true;
    const first = grid[0];
    for (let i = 1; i < grid.length; i++) if (grid[i] !== first) return false;
    return true;
}

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
    // grid is small (≤ ~400 cells at 4 colors); base64 of the bytes is
    // plenty unique without needing a full crypto hash.
    let s = '';
    for (let i = 0; i < grid.length; i++) s += String.fromCharCode(grid[i]);
    return s;
}

// Run the ruleset and measure the resulting analysis dict. Mirrors
// det.search._step_and_measure but keeps the final grid + prev around
// so the UI could render a preview later if we want.
export function simulateAndAnalyze(rules, W, H, nColors, horizon, gridSeed) {
    const { exactMap, wildcards } = prepareRules(rules);
    let grid = seededGrid(W, H, nColors, gridSeed);
    const history = new Map();
    history.set(gridKey(grid), 0);
    const activity = [];
    let period = null, enteredAt = null;
    let prev = grid;
    for (let t = 1; t <= horizon; t++) {
        const nxt = stepExact(grid, W, H, exactMap, wildcards);
        activity.push(activityRate(grid, nxt));
        const key = gridKey(nxt);
        const hit = history.get(key);
        if (hit !== undefined) {
            period = t - hit;
            enteredAt = hit;
            prev = grid;
            grid = nxt;
            break;
        }
        history.set(key, t);
        prev = grid;
        grid = nxt;
    }
    const uniform = isUniform(grid);
    const be = blockEntropy(grid, W, H, 2);
    const dens = densityProfile(grid, nColors);
    const colorDiversity = dens.reduce((n, d) => n + (d > 0.01 ? 1 : 0), 0);
    const tailN = Math.max(1, Math.floor(activity.length / 3));
    const tail = activity.slice(-tailN);
    const activityTail = tail.length
        ? tail.reduce((s, x) => s + x, 0) / tail.length
        : 0;
    return {
        uniform, period, entered_at: enteredAt,
        activity_tail: +activityTail.toFixed(4),
        block_entropy: +be.toFixed(4),
        density_profile: dens.map(d => +d.toFixed(4)),
        color_diversity: colorDiversity,
        n_ticks: activity.length,
        finalGrid: grid, prevGrid: prev,
    };
}

// Port of det.search._score with (non-uniform, aperiodic/long_period,
// activity_band, entropy_band, color_diversity) weights identical to
// the Python side.
export function rawScore(analysis, nColors) {
    let score = 0;
    if (!analysis.uniform) score += 1.0;
    const p = analysis.period;
    if (p === null || p === undefined) score += 1.5;
    else if (p > 8) score += 0.75;
    const a = analysis.activity_tail;
    if (a >= 0.03 && a <= 0.30) {
        const peak = 0.12;
        const distance = Math.abs(a - peak) / 0.18;
        score += 2.0 * Math.max(0, 1 - distance);
    }
    const be = analysis.block_entropy;
    const cap = BE_CAP[nColors] || 8.0;
    const low = cap * 0.35, high = cap * 0.75;
    if (be >= low && be <= high) {
        const mid = (low + high) / 2;
        score += 1.5 * (1.0 - Math.abs(be - mid) / ((high - low) / 2));
    }
    if (analysis.color_diversity >= 2) {
        score += 0.25 * Math.min(analysis.color_diversity, nColors);
    }
    return score;
}

// ── Engine adapter ─────────────────────────────────────────────────
export const hexcaHandler = {
    random(rng, ctx) {
        const t = (ctx && ctx.hexca_target) || {};
        const nRules = clampInt(t.n_rules_per_candidate || 80, 1, MAX_RULES_CAP);
        const nColors = clampInt(t.n_colors || 4, 2, 4);
        const wc = clampInt(t.wildcard_pct || 25, 0, 95);
        return { rules: generateRules(rng, nRules, nColors, wc) };
    },
    mutate(gene, rng, rate) {
        const next = { rules: (gene.rules || []).map(r => ({
            s: r.s, n: r.n.slice(), r: r.r,
        })) };
        if (next.rules.length === 0) return next;
        // Figure out the color space from the largest index in the gene
        // (we can't reach ctx here, so we guess conservatively from 2..4).
        let nColors = 2;
        for (const er of next.rules) {
            if (er.s + 1 > nColors) nColors = er.s + 1;
            if (er.r + 1 > nColors) nColors = er.r + 1;
            for (const x of er.n) if (x + 1 > nColors) nColors = x + 1;
        }
        nColors = Math.max(2, Math.min(4, nColors));
        for (let i = 0; i < next.rules.length; i++) {
            if (rng() < rate) {
                const op = Math.floor(rng() * 3);
                const er = next.rules[i];
                if (op === 0) {
                    // flip result
                    er.r = Math.floor(rng() * nColors);
                } else if (op === 1) {
                    // flip one neighbor slot (possibly toggle wildcard)
                    const j = Math.floor(rng() * 6);
                    if (rng() < 0.3) er.n[j] = -1;
                    else er.n[j] = Math.floor(rng() * nColors);
                } else {
                    // flip self-color
                    er.s = Math.floor(rng() * nColors);
                }
            }
        }
        // Low-rate structural mutation: drop or add a rule.
        if (rng() < rate * 0.1 && next.rules.length > 4) {
            next.rules.splice(Math.floor(rng() * next.rules.length), 1);
        } else if (rng() < rate * 0.1 && next.rules.length < MAX_RULES_CAP) {
            const s = Math.floor(rng() * nColors);
            const n = new Array(6);
            for (let i = 0; i < 6; i++) {
                n[i] = (rng() < 0.25) ? -1 : Math.floor(rng() * nColors);
            }
            const r = Math.floor(rng() * nColors);
            if (!(r === s && n.every(x => x === -1))) {
                next.rules.push({ s, n, r });
            }
        }
        return next;
    },
    crossover(geneA, geneB, rng) {
        // Single-point-by-fraction: child = A[0..fA] ++ B[fB..]. Using
        // a shared fraction across parents preserves length (roughly)
        // even when parents differ in rule count. Dedup on key so a
        // rule that exists in both parents doesn't take two slots.
        const ra = (geneA && geneA.rules) || [];
        const rb = (geneB && geneB.rules) || [];
        if (ra.length === 0) return { rules: rb.map(cloneRule) };
        if (rb.length === 0) return { rules: ra.map(cloneRule) };
        const f = 0.3 + rng() * 0.4; // 0.30..0.70
        const splitA = Math.max(1, Math.floor(ra.length * f));
        const splitB = Math.min(rb.length - 1,
                                Math.max(0, Math.floor(rb.length * f)));
        const child = [];
        const seen = new Set();
        for (let i = 0; i < splitA; i++) pushUnique(child, seen, ra[i]);
        for (let i = splitB; i < rb.length; i++) pushUnique(child, seen, rb[i]);
        // Guard: crossover that drops below 4 rules is rarely
        // interesting on the hex substrate — pad from the richer parent
        // so the child has something to step with.
        const richer = (ra.length >= rb.length) ? ra : rb;
        let idx = 0;
        while (child.length < 4 && idx < richer.length) {
            pushUnique(child, seen, richer[idx++]);
        }
        return { rules: child };
    },
    async work(agent, ctx) {
        const target = (ctx && ctx.hexca_target) || {};
        const W = clampInt(target.screen_width || 18, 4, 40);
        const H = clampInt(target.screen_height || 18, 4, 40);
        const nColors = clampInt(target.n_colors || 4, 2, 4);
        const horizon = clampInt(target.horizon || 30, 6, 120);
        const rules = (agent.gene && agent.gene.rules) || [];
        // Use the agent id as part of the grid seed so siblings all see
        // the *same* substrate — fair comparison.
        const gridSeed = target.grid_seed || 'det-evo';
        const analysis = simulateAndAnalyze(
            rules, W, H, nColors, horizon, gridSeed);
        const raw = rawScore(analysis, nColors);
        agent.output = `p=${analysis.period} a=${analysis.activity_tail} ` +
                       `be=${analysis.block_entropy} ` +
                       `cd=${analysis.color_diversity} | raw=${raw.toFixed(2)}`;
        // Normalize to [0, 1] so it slots into the engine's elitist loop
        // alongside lsystem/lut scores.
        const norm = Math.max(0, Math.min(1, raw / SCORE_NORM));
        return norm;
    },
};

function clampInt(v, lo, hi) {
    const n = v | 0;
    return n < lo ? lo : (n > hi ? hi : n);
}

function cloneRule(r) {
    return { s: r.s, n: r.n.slice(), r: r.r };
}

function ruleKey(r) {
    return `${r.s}|${r.n[0]},${r.n[1]},${r.n[2]},${r.n[3]},${r.n[4]},${r.n[5]}|${r.r}`;
}

function pushUnique(list, seen, rule) {
    const k = ruleKey(rule);
    if (seen.has(k)) return;
    seen.add(k);
    list.push(cloneRule(rule));
}

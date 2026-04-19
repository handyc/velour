// Evolution Engine — runs entirely in the browser.
//
// Three roles, one Agent class, distinguished by `level`:
//   L0 worker     — gene = {axiom, rules:{char→str}, iterations}
//                   work() expands the L-system, returns its output string
//   L1 meta       — gene = inner-pop params; work() runs an inner L0 pop
//                   and returns the best inner score as its "output score"
//   L2 meta-meta  — gene = inner L1-pop params; work() runs inner L1 pop
//
// The engine is event-driven: tick() runs one generation. The UI calls
// start()/pause() and reads `engine.history` for charts.

const LSYS_ALPHABET = 'F+-[]X';
const SCORE_CAP_LEN = 256;       // truncate strings before edit-distance
const MAX_OUTPUT_LEN = 4000;     // L-system expansion safety cap

// ── L-system expansion ──────────────────────────────────────────────
export class LSystem {
    static expand(axiom, rules, iterations, maxLen = MAX_OUTPUT_LEN) {
        let s = axiom || '';
        const iters = Math.max(0, Math.min(8, iterations | 0));
        for (let i = 0; i < iters; i++) {
            let out = '';
            for (const ch of s) {
                out += (rules && rules[ch] != null) ? rules[ch] : ch;
                if (out.length > maxLen) {
                    return out.slice(0, maxLen);
                }
            }
            s = out;
        }
        return s;
    }
}

// ── Levenshtein with row buffer, O(n) memory ────────────────────────
export function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    const n = a.length, m = b.length;
    let prev = new Array(m + 1);
    let curr = new Array(m + 1);
    for (let j = 0; j <= m; j++) prev[j] = j;
    for (let i = 1; i <= n; i++) {
        curr[0] = i;
        const ai = a.charCodeAt(i - 1);
        for (let j = 1; j <= m; j++) {
            const cost = ai === b.charCodeAt(j - 1) ? 0 : 1;
            const del = prev[j] + 1;
            const ins = curr[j - 1] + 1;
            const sub = prev[j - 1] + cost;
            curr[j] = del < ins ? (del < sub ? del : sub) : (ins < sub ? ins : sub);
        }
        [prev, curr] = [curr, prev];
    }
    return prev[m];
}

export function scoreString(output, goal) {
    const a = (output || '').slice(0, SCORE_CAP_LEN);
    const b = (goal   || '').slice(0, SCORE_CAP_LEN);
    if (!a.length && !b.length) return 1;
    const d = levenshtein(a, b);
    const denom = Math.max(a.length, b.length, 1);
    return Math.max(0, 1 - d / denom);
}

// ── Random helpers ──────────────────────────────────────────────────
const rnd = (rng) => rng();
const ri  = (rng, n) => Math.floor(rnd(rng) * n);
const pick = (rng, arr) => arr[ri(rng, arr.length)];

// Mulberry32 — deterministic when seeded, default rng if not.
export function makeRng(seed) {
    if (seed == null) return Math.random;
    let s = seed >>> 0;
    return function () {
        s |= 0; s = (s + 0x6D2B79F5) | 0;
        let t = Math.imul(s ^ (s >>> 15), 1 | s);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// ── Gene helpers (L0) ───────────────────────────────────────────────
function randomL0Gene(rng) {
    const alphabet = LSYS_ALPHABET;
    const rules = {};
    // 1–3 starting rules
    const ruleCount = 1 + ri(rng, 3);
    for (let i = 0; i < ruleCount; i++) {
        const k = pick(rng, ['F', 'X']);
        rules[k] = randomRuleBody(rng, alphabet);
    }
    return {
        axiom: pick(rng, ['F', 'X', 'F+F', 'FX']),
        rules,
        iterations: 2 + ri(rng, 3),  // 2..4
    };
}

function randomRuleBody(rng, alphabet) {
    const len = 3 + ri(rng, 8); // 3..10
    let s = '';
    for (let i = 0; i < len; i++) s += pick(rng, alphabet);
    // try to keep brackets balanced — strip orphans
    return balanceBrackets(s);
}

function balanceBrackets(s) {
    let depth = 0, out = '';
    for (const ch of s) {
        if (ch === '[') { depth++; out += ch; }
        else if (ch === ']') { if (depth > 0) { depth--; out += ch; } }
        else out += ch;
    }
    while (depth-- > 0) out += ']';
    return out;
}

function mutateL0(gene, rng, rate) {
    const next = {
        axiom: gene.axiom,
        rules: { ...gene.rules },
        iterations: gene.iterations,
    };
    // mutate each rule with prob `rate`
    for (const k of Object.keys(next.rules)) {
        if (rnd(rng) < rate) {
            next.rules[k] = mutateRuleBody(next.rules[k], rng);
        }
    }
    // small chance: add a new rule for a fresh char
    if (rnd(rng) < rate * 0.5) {
        const k = pick(rng, ['F', 'X']);
        if (!next.rules[k]) next.rules[k] = randomRuleBody(rng, LSYS_ALPHABET);
    }
    // small chance: nudge iterations ±1
    if (rnd(rng) < rate * 0.4) {
        next.iterations = Math.max(1, Math.min(6,
            next.iterations + (rnd(rng) < 0.5 ? -1 : 1)));
    }
    // very small chance: mutate axiom
    if (rnd(rng) < rate * 0.2) {
        next.axiom = mutateRuleBody(next.axiom || 'F', rng);
    }
    return next;
}

function mutateRuleBody(s, rng) {
    if (!s) return pick(rng, LSYS_ALPHABET);
    const op = ri(rng, 3);
    if (op === 0 && s.length < 24) {
        // insert
        const i = ri(rng, s.length + 1);
        return balanceBrackets(s.slice(0, i) + pick(rng, LSYS_ALPHABET) + s.slice(i));
    } else if (op === 1 && s.length > 1) {
        // delete
        const i = ri(rng, s.length);
        return balanceBrackets(s.slice(0, i) + s.slice(i + 1));
    } else {
        // swap one char
        const i = ri(rng, s.length);
        return balanceBrackets(s.slice(0, i) + pick(rng, LSYS_ALPHABET) + s.slice(i + 1));
    }
}

// ── Gene helpers (L1, L2 — inner-pop params) ────────────────────────
function randomMetaGene(rng) {
    return {
        inner_size: 8 + ri(rng, 9),         // 8..16
        inner_generations: 4 + ri(rng, 9),  // 4..12
        mutation_rate: 0.10 + rnd(rng) * 0.30, // 0.10..0.40
        tournament_k: 2 + ri(rng, 3),       // 2..4
    };
}

function mutateMeta(gene, rng, rate) {
    const next = { ...gene };
    if (rnd(rng) < rate) {
        next.inner_size = Math.max(4, Math.min(32,
            next.inner_size + (rnd(rng) < 0.5 ? -1 : 1) * (1 + ri(rng, 2))));
    }
    if (rnd(rng) < rate) {
        next.inner_generations = Math.max(2, Math.min(20,
            next.inner_generations + (rnd(rng) < 0.5 ? -1 : 1)));
    }
    if (rnd(rng) < rate) {
        const delta = (rnd(rng) - 0.5) * 0.1;
        next.mutation_rate = Math.max(0.02, Math.min(0.6, next.mutation_rate + delta));
    }
    if (rnd(rng) < rate) {
        next.tournament_k = Math.max(2, Math.min(6,
            next.tournament_k + (rnd(rng) < 0.5 ? -1 : 1)));
    }
    return next;
}

// ── LUT gene handler (Casting) ──────────────────────────────────────
// A LUT agent's gene encodes a tiny n→h→1 MLP with ±1 weights and sign
// activation — exactly the architecture family the Casting progressive
// search uses. Weight bit layout matches byte_model_progressive.c:
// per hidden unit [n input weights, 1 bias], then output [h weights, 1
// bias]. For h=0 the gene is just [n input weights, 1 bias]. Input
// bits are read MSB-first from `row` so truth-table encodings are
// compatible with the exhaustive-search pool.
const LUT_MAX_H = 4;

function lutTotalBits(n, h) {
    return h > 0 ? h * (n + 2) + 1 : (n + 1);
}

function lutForward(bits, n, h, row) {
    const xi = new Array(n);
    for (let i = 0; i < n; i++) xi[i] = ((row >> (n - 1 - i)) & 1) ? 1 : -1;
    let idx = 0;
    const wb = (k) => (((bits >> k) & 1) ? 1 : -1);
    if (h === 0) {
        let s = 0;
        for (let i = 0; i < n; i++) s += wb(idx++) * xi[i];
        const b = wb(idx++);
        return (s + b) >= 0 ? 1 : -1;
    }
    const hid = new Array(h);
    for (let j = 0; j < h; j++) {
        let s = 0;
        for (let i = 0; i < n; i++) s += wb(idx++) * xi[i];
        const b = wb(idx++);
        hid[j] = (s + b) >= 0 ? 1 : -1;
    }
    let s = 0;
    for (let j = 0; j < h; j++) s += wb(idx++) * hid[j];
    const b = wb(idx++);
    return (s + b) >= 0 ? 1 : -1;
}

export function lutTruthTable(gene) {
    const n = gene.n | 0, h = gene.h | 0, bits = gene.bits >>> 0;
    const N = 1 << n;
    let tt = 0;
    for (let row = 0; row < N; row++) {
        if (lutForward(bits, n, h, row) > 0) tt |= (1 << row);
    }
    return tt >>> 0;
}

function popcount(x) {
    x = x | 0;
    x = x - ((x >>> 1) & 0x55555555);
    x = (x & 0x33333333) + ((x >>> 2) & 0x33333333);
    return (((x + (x >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}

function lutRandom(rng, n) {
    const h = ri(rng, LUT_MAX_H + 1);
    const W = lutTotalBits(n, h);
    let bits = 0;
    for (let i = 0; i < W; i++) if (rnd(rng) < 0.5) bits |= (1 << i);
    return { n, h, bits: bits >>> 0 };
}

function lutMutate(gene, rng, rate) {
    const next = { n: gene.n, h: gene.h, bits: gene.bits >>> 0 };
    let W = lutTotalBits(next.n, next.h);
    for (let i = 0; i < W; i++) {
        if (rnd(rng) < rate) next.bits ^= (1 << i);
    }
    next.bits >>>= 0;
    if (rnd(rng) < rate * 0.15) {
        const dir = (rnd(rng) < 0.5) ? -1 : 1;
        const newH = Math.max(0, Math.min(LUT_MAX_H, next.h + dir));
        if (newH !== next.h) {
            const newW = lutTotalBits(next.n, newH);
            if (newW < W) {
                next.bits = next.bits & ((1 << newW) - 1);
            } else {
                for (let i = W; i < newW; i++) {
                    if (rnd(rng) < 0.5) next.bits |= (1 << i);
                }
                next.bits >>>= 0;
            }
            next.h = newH;
        }
    }
    return next;
}

async function lutWork(agent, ctx) {
    const g = agent.gene || {};
    const target = ctx.lut_target || null;
    if (!target || target.n !== g.n) {
        agent.output = 'no target or arch mismatch';
        return 0;
    }
    const tt = lutTruthTable(g);
    const N = 1 << target.n;
    const mask = (N >= 32) ? 0xffffffff : ((1 << N) - 1);
    const diff = (tt ^ (target.truth_table >>> 0)) & mask;
    const wrong = popcount(diff);
    const right = N - wrong;
    const W = lutTotalBits(g.n, g.h);
    agent.output = `n=${g.n} h=${g.h} W=${W} tt=0x${tt.toString(16)} ` +
                   `target=0x${(target.truth_table >>> 0).toString(16)} ${right}/${N}`;
    // Bonus: prefer smaller architectures when fitness ties. 1% knock per
    // extra bit. Keeps the best solver compact.
    let s = right / N;
    if (s >= 1 - 1e-9) {
        s = 1.0 - 0.0001 * W;
    }
    return s;
}

// ── Gene-type registry ──────────────────────────────────────────────
// The L-system path above is the default. New types just register here.
// Each handler provides random/mutate/work; the engine dispatches on
// Agent.gene_type. Backward compat: gene_type omitted == 'lsystem'.
export const GENE_TYPES = {
    lsystem: {
        random: (rng, ctx) => randomL0Gene(rng),
        mutate: mutateL0,
        work: async (agent, ctx) => {
            const g = agent.gene || {};
            const axiomFromSeed = (agent.seed_string && agent.seed_string.length)
                ? agent.seed_string : (g.axiom || 'F');
            agent.output = LSystem.expand(axiomFromSeed, g.rules || {},
                                          g.iterations | 0);
            return scoreString(agent.output, ctx.goal);
        },
    },
    lut: {
        random: (rng, ctx) => lutRandom(rng, (ctx && ctx.lut_target && ctx.lut_target.n) || 2),
        mutate: lutMutate,
        work: lutWork,
    },
};

// ── Agent ───────────────────────────────────────────────────────────
let _agentSeq = 0;

export class Agent {
    constructor({ level = 0, gene = null, seed_string = '', script = '',
                  parent = null, name = '', gene_type = 'lsystem' } = {}) {
        this.id = ++_agentSeq;
        this.level = level;
        this.gene = gene;
        this.gene_type = gene_type;
        this.seed_string = seed_string;
        this.script = script || '';
        this.parent_id = parent ? parent.id : null;
        this.parent_name = parent ? parent.name : null;
        this.name = name || `a${this.id}`;
        this.score = 0;
        this.output = '';
    }

    clone() {
        const child = new Agent({
            level: this.level,
            gene: deepClone(this.gene),
            gene_type: this.gene_type,
            seed_string: this.seed_string,
            script: this.script,
            parent: this,
        });
        return child;
    }

    mutate(rng, rate) {
        if (this.level === 0) {
            const handler = GENE_TYPES[this.gene_type] || GENE_TYPES.lsystem;
            this.gene = handler.mutate(this.gene, rng, rate);
        } else {
            this.gene = mutateMeta(this.gene, rng, rate);
        }
        return this;
    }

    // L0: invoke the gene-type's work(). Default is L-system against
    //     ctx.goal (edit distance). LUT gene type scores against
    //     ctx.lut_target truth table. Script hook adds a bonus.
    // L1/L2: run an inner population, return its best score as the output.
    async work(ctx) {
        if (this.level === 0) {
            const handler = GENE_TYPES[this.gene_type] || GENE_TYPES.lsystem;
            let s = await handler.work(this, ctx);
            if (this.script && this.script.trim()) {
                try {
                    const fn = new Function('agent', 'ctx', this.script);
                    const bonus = fn(this, ctx);
                    if (typeof bonus === 'number' && isFinite(bonus)) {
                        s = Math.max(0, Math.min(1, 0.5 * s + 0.5 * bonus));
                    }
                } catch (_) { /* user script errors are silent */ }
            }
            this.score = s;
            return s;
        }
        // L1/L2: spin an inner population at level-1
        const innerLevel = this.level - 1;
        const g = this.gene || randomMetaGene(ctx.rng);
        const inner = new EvolutionEngine({
            level: innerLevel,
            goal: ctx.goal,
            population_size: g.inner_size,
            generations_target: g.inner_generations,
            target_score: 1.0,
            params: { mutation_rate: g.mutation_rate, tournament_k: g.tournament_k },
            seedAgent: ctx.innerSeed || null,
            rng: ctx.rng,
            gene_type: ctx.gene_type || 'lsystem',
            lut_target: ctx.lut_target || null,
            hexca_target: ctx.hexca_target || null,
        });
        inner.init();
        await inner.runUntilDone();
        this.score = inner.bestScore;
        this.output = inner.best ? (inner.best.output || '').slice(0, 240) : '';
        return this.score;
    }

    snapshot() {
        return {
            level: this.level,
            gene: deepClone(this.gene),
            seed_string: this.seed_string,
            script: this.script,
            score: this.score,
            output: (this.output || '').slice(0, 1000),
            parent_name: this.parent_name,
            name: this.name,
        };
    }
}

function deepClone(x) {
    if (x == null || typeof x !== 'object') return x;
    return JSON.parse(JSON.stringify(x));
}

// ── Engine ──────────────────────────────────────────────────────────
export class EvolutionEngine {
    constructor({
        run = null, level = 0, goal = '',
        population_size = 24, generations_target = 200,
        target_score = 0.95,
        params = {}, seedAgent = null, rng = null,
        gene_type = 'lsystem', lut_target = null, hexca_target = null,
    } = {}) {
        this.run = run;
        this.level = level;
        this.goal = goal || '';
        this.geneType = gene_type;
        this.lutTarget = lut_target;
        this.hexcaTarget = hexca_target;
        this.populationSize = Math.max(2, population_size | 0);
        this.generationsTarget = Math.max(1, generations_target | 0);
        this.targetScore = target_score;
        this.params = params || {};
        this.seedAgent = seedAgent;
        this.rng = rng || makeRng(params.seed);
        this.mutationRate = (typeof params.mutation_rate === 'number')
            ? params.mutation_rate : 0.25;
        this.tournamentK = (typeof params.tournament_k === 'number')
            ? params.tournament_k : 3;
        this.crossoverRate = (typeof params.crossover_rate === 'number')
            ? params.crossover_rate : 0;
        this.script = params.script || '';
        this.seedString = params.seed_string || '';

        this.population = [];
        this.generation = 0;
        this.bestScore = 0;
        this.best = null;
        this.history = []; // {gen, best, mean}
        this.status = 'idle';

        this.onGeneration = null;
        this.onLog = null;
    }

    init() {
        this.population = [];
        for (let i = 0; i < this.populationSize; i++) {
            this.population.push(this._makeFounder(i));
        }
        this.generation = 0;
        this.bestScore = 0;
        this.best = null;
        this.history = [];
    }

    _makeFounder(i) {
        const ctx = { lut_target: this.lutTarget, hexca_target: this.hexcaTarget };
        let gene;
        if (this.seedAgent && i === 0) {
            gene = deepClone(this.seedAgent.gene);
        } else if (this.seedAgent && this.rng() < 0.3) {
            gene = deepClone(this.seedAgent.gene);
        } else if (this.level === 0) {
            const handler = GENE_TYPES[this.geneType] || GENE_TYPES.lsystem;
            gene = handler.random(this.rng, ctx);
        } else {
            gene = randomMetaGene(this.rng);
        }
        const a = new Agent({
            level: this.level,
            gene,
            gene_type: this.geneType,
            seed_string: this.seedString,
            script: this.script,
        });
        // immediate diversity: mutate non-elite founders
        if (i > 0) a.mutate(this.rng, this.mutationRate);
        return a;
    }

    // One generation: evaluate → select → reproduce.
    async tick() {
        const ctx = {
            goal: this.goal, rng: this.rng,
            gene_type: this.geneType,
            lut_target: this.lutTarget,
            hexca_target: this.hexcaTarget,
        };
        for (const a of this.population) {
            await a.work(ctx);
        }
        this.population.sort((a, b) => b.score - a.score);
        const elite = this.population[0];
        const mean = this.population.reduce((s, a) => s + a.score, 0)
                     / this.population.length;
        if (elite.score > this.bestScore) {
            this.bestScore = elite.score;
            this.best = elite;
        }
        this.generation++;
        this.history.push({ gen: this.generation, best: elite.score, mean });
        if (this.onGeneration) this.onGeneration(this);
        if (this.onLog) this.onLog({
            gen: this.generation, best: elite.score, mean,
            elite_name: elite.name,
        });
        // breed next generation
        const handler = GENE_TYPES[this.geneType] || GENE_TYPES.lsystem;
        const canCross = this.level === 0
                         && typeof handler.crossover === 'function'
                         && this.crossoverRate > 0
                         && this.populationSize >= 3;
        const next = [elite];           // elitist carry-forward
        while (next.length < this.populationSize) {
            if (canCross && rnd(this.rng) < this.crossoverRate) {
                const p1 = this._tournament();
                let p2 = this._tournament();
                // Bias toward distinct parents so crossover does real work
                if (p2 === p1 && this.population.length > 1) {
                    for (let tries = 0; tries < 3 && p2 === p1; tries++) {
                        p2 = this._tournament();
                    }
                }
                const childGene = handler.crossover(p1.gene, p2.gene, this.rng);
                const child = new Agent({
                    level: this.level,
                    gene: childGene,
                    gene_type: this.geneType,
                    seed_string: this.seedString,
                    script: this.script,
                    parent: p1,
                });
                child.mutate(this.rng, this.mutationRate);
                next.push(child);
            } else {
                const parent = this._tournament();
                next.push(parent.clone().mutate(this.rng, this.mutationRate));
            }
        }
        this.population = next;
        return { gen: this.generation, best: elite.score, mean };
    }

    _tournament() {
        let winner = null;
        const k = Math.max(2, Math.min(this.populationSize, this.tournamentK | 0));
        for (let i = 0; i < k; i++) {
            const cand = this.population[ri(this.rng, this.population.length)];
            if (!winner || cand.score > winner.score) winner = cand;
        }
        return winner;
    }

    isDone() {
        return this.generation >= this.generationsTarget
            || this.bestScore >= this.targetScore;
    }

    async runUntilDone(maxMs = 4000) {
        const t0 = performance.now();
        while (!this.isDone()) {
            await this.tick();
            if (performance.now() - t0 > maxMs) break;
        }
    }
}

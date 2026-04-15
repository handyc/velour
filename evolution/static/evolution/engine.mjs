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

// ── Agent ───────────────────────────────────────────────────────────
let _agentSeq = 0;

export class Agent {
    constructor({ level = 0, gene = null, seed_string = '', script = '',
                  parent = null, name = '' } = {}) {
        this.id = ++_agentSeq;
        this.level = level;
        this.gene = gene;
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
            seed_string: this.seed_string,
            script: this.script,
            parent: this,
        });
        return child;
    }

    mutate(rng, rate) {
        if (this.level === 0) {
            this.gene = mutateL0(this.gene, rng, rate);
        } else {
            this.gene = mutateMeta(this.gene, rng, rate);
        }
        return this;
    }

    // L0: expand L-system from seed_string, append optional user-script
    //     contribution, score against goal.
    // L1/L2: run an inner population, return its best score as the output.
    async work(ctx) {
        if (this.level === 0) {
            const g = this.gene || {};
            const axiomFromSeed = (this.seed_string && this.seed_string.length)
                ? this.seed_string : (g.axiom || 'F');
            this.output = LSystem.expand(axiomFromSeed, g.rules || {},
                                         g.iterations | 0);
            let s = scoreString(this.output, ctx.goal);
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
    } = {}) {
        this.run = run;
        this.level = level;
        this.goal = goal || '';
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
        let gene;
        if (this.seedAgent && i === 0) {
            gene = deepClone(this.seedAgent.gene);
        } else if (this.seedAgent && this.rng() < 0.3) {
            gene = deepClone(this.seedAgent.gene);
        } else {
            gene = (this.level === 0)
                ? randomL0Gene(this.rng)
                : randomMetaGene(this.rng);
        }
        const a = new Agent({
            level: this.level,
            gene,
            seed_string: this.seedString,
            script: this.script,
        });
        // immediate diversity: mutate non-elite founders
        if (i > 0) a.mutate(this.rng, this.mutationRate);
        return a;
    }

    // One generation: evaluate → select → reproduce.
    async tick() {
        const ctx = { goal: this.goal, rng: this.rng };
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
        const next = [elite];           // elitist carry-forward
        while (next.length < this.populationSize) {
            const parent = this._tournament();
            next.push(parent.clone().mutate(this.rng, this.mutationRate));
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

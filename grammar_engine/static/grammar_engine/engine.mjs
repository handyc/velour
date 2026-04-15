// Grammar Engine — shared synthesis + vocabulary stack.
//
// Each GrammarEngine instance is an independent language: its own
// phonic particles, subwords, words, L-system grammars, and
// utterance log. Pass in an AudioContext + master GainNode to enable
// playback; pass in a `spec` blob to load a persisted language, or
// a `seed` to generate one deterministically. Call startChurn() to
// enable the evolve/invent/word-birth timers; leave them off for
// static languages attached to Planets/Worlds.
//
// Public API (the bits callers should touch):
//   new GrammarEngine({ ctx, master, spec, seed, name })
//   engine.attachAudio(ctx, master)
//   engine.setPinkMode('buffer' | 'live')
//   engine.generatePhrase(kind?)           → string (L-system path)
//   engine.expandGrammarMeta(kind?)        → { symbols, kind, variant }
//   engine.generateVocabPhrase()           → string
//   engine.generateVocabPhraseMeta()       → { symbols, units, words, ... }
//   engine.speakPhrase(symbols, distance)  // render grammar-tier phrase
//   engine.speakUnits(units, distance)     // render vocab-tier phrase
//   engine.evolve()                        // run one evolution cycle
//   engine.invent()                        // synthesise a new preset
//   engine.stats()                         // numeric summary
//   engine.serialize()                     // plain JSON blob
//   engine.startChurn() / stopChurn()
//
// Everything in this module is self-contained — no globals, no
// direct DOM access, no hardcoded UI. Inspector code lives separately
// in inspector.mjs.


// ── Deterministic PRNG ─────────────────────────────────────
// Used only during initial generation from a seed, so that two calls
// with the same seed produce identical particles/subwords/words.
// Runtime evolution and speech selection still use Math.random().
function mulberry32(seed) {
    let a = (seed >>> 0) || 1;
    return function() {
        a |= 0; a = (a + 0x6D2B79F5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function makeRng(randFn) {
    return (lo, hi) => lo + randFn() * (hi - lo);
}

function makePick(randFn) {
    return (xs) => xs[Math.floor(randFn() * xs.length)];
}


// ── L-system expander ──────────────────────────────────────
// Same as Legolith's / bridge's original. Rules apply `iterations`
// times to the axiom.
export class LSystem {
    constructor(axiom, rules, iterations) {
        this.axiom = axiom;
        this.rules = rules;
        this.iterations = iterations || 2;
    }
    expand() {
        let s = this.axiom;
        for (let k = 0; k < this.iterations; k++) {
            let out = '';
            for (const c of s) {
                out += (c in this.rules) ? this.rules[c] : c;
            }
            s = out;
        }
        return s;
    }
}


// ── Acoustic constants ─────────────────────────────────────
const VOWEL_FORMANTS = [
    [ 300,  870],  // /u/
    [ 390, 2300],  // /i/
    [ 730, 1100],  // /ɑ/
    [ 570, 1700],  // /e/
    [ 440, 1020],  // /ʌ/
    [ 500, 1500],  // neutral
];

const SYMBOL_MEAN_DUR = {
    V: 0.18, v: 0.09, n: 0.09, l: 0.09, C: 0.055,
    s: 0.045, p: 0.03, '.': 0.09, ',': 0.33,
};

const PARTICLE_DUR = {
    V: [0.055, 0.090], v: [0.028, 0.055],
    C: [0.020, 0.038], s: [0.015, 0.032],
    n: [0.028, 0.055], l: [0.025, 0.050],
    p: [0.010, 0.022],
};

const PARTICLE_TYPE_BAG = 'VVVVVvvvnnllCCsp';

const SYMS = 'VvCsnlp';

// Defaults — overridable via engine constructor options.
const DEFAULTS = {
    SUBWORD_MIN: 100,
    SUBWORD_CAP: 1000,
    SUBWORD_SEED: 300,
    WORD_COUNT: 10000,
    PARTICLE_SEED: 140,
    PARTICLE_CAP: 400,
    PARTICLE_MIN: 90,
    UTTERANCE_LOG_CAP: 400,
};


// ── Default preset grammars ─────────────────────────────────
// These are the "stock" L-system grammars the old bridge shipped.
// A Language spec can override SPEECH_GRAMMARS entirely — e.g. a
// planet's language might ship with just its own custom grammars.
const DEFAULT_SPEECH_GRAMMARS = {
    greeting: {
        note: 'Short two-word exchange. Soft onsets, trailing breath.',
        axiom: 'S', iterations: 4,
        variants: {
            cheerful: { S: 'W.W,', W: 'XX', X: 'ON',
                        O: ['C', 'n', 'l', ''], N: 'V' },
            tired:    { S: 'W,W,', W: 'X',  X: 'ON',
                        O: ['n', 'l', ''], N: 'v' },
            formal:   { S: 'W.W.W,', W: 'XX', X: 'OND',
                        O: ['Cl', 'Cn', 'C'], N: 'V', D: ['n', 's', ''] },
        },
    },
    command: {
        note: 'Short, clipped, plosive-heavy; one or two words.',
        axiom: 'S', iterations: 4,
        variants: {
            short:         { S: 'W',          W: 'XX', X: 'pVs' },
            double:        { S: 'W.W',        W: 'XX', X: ['pVC', 'CVp', 'pVp'] },
            barked:        { S: 'W',          W: 'X',  X: 'pVp' },
            hailed:        { S: 'W.W',        W: 'X',  X: ['pV', 'nV'] },
            shouted:       { S: 'W.W.W',      W: 'X',  X: 'pV' },
            terse:         { S: 'W',          W: 'X',  X: 'Cv' },
            affirmed:      { S: 'W',          W: 'XX', X: ['pVs', 'Vs'] },
            dismissive:    { S: 'W',          W: 'XX', X: ['Vp', 'Vs'] },
            snapped:       { S: 'W',          W: 'X',  X: 'spV' },
            declarative:   { S: 'W.W',        W: 'XX', X: ['CVC', 'pVC', 'pVp'] },
            tense:         { S: 'W,W',        W: 'X',  X: 'psV' },
            rhythmic:      { S: 'W.W.W',      W: 'XX', X: 'pVs' },
            countdown:     { S: 'W.W.W.W.W,', W: 'X',  X: 'CV' },
            warning:       { S: 'W.W,',       W: 'XX', X: ['pV', 'sV'] },
            quiet_urgent:  { S: 'W,W',        W: 'X',  X: ['sVn', 'nVs'] },
            confirmation:  { S: 'W',          W: 'XX', X: ['pV', 'Vp'] },
            refusal:       { S: 'W',          W: 'X',  X: ['nVC', 'nV'] },
            ordered:       { S: 'W.W.W',      W: 'XX', X: 'pVp' },
            relayed:       { S: 'W,W.W',      W: 'X',  X: ['CV', 'pV'] },
            staccato:      { S: 'WWW,',       W: 'X.', X: 'pV' },
        },
    },
    technical: {
        note: 'Dense consonant clusters, dictation-style.',
        axiom: 'S', iterations: 4,
        variants: {
            readout:        { S: 'W.W.W.W,',    W: 'X',   X: 'CvC' },
            jargon:         { S: 'W.W,',        W: 'XXX', X: ['CsV', 'sCV', 'pCV', 'CVs'] },
            chatter:        { S: 'WWWW,',       W: 'X.',  X: 'CvC' },
            spec:           { S: 'W.W.W.W,',    W: 'X',   X: 'CsV' },
            coordinates:    { S: 'W.W.W,',      W: 'X',   X: 'CvCv' },
            checklist:      { S: 'WWWW,',       W: 'X.',  X: 'CV' },
            status:         { S: 'W.W,',        W: 'XX',  X: 'sVC' },
            report:         { S: 'W.W.W.W.W,',  W: 'X',   X: 'nVs' },
            alert:          { S: 'W,W,W,',      W: 'X',   X: 'pVs' },
            diagnostic:     { S: 'W.W.W,',      W: 'XX',  X: 'CsC' },
            telemetry:      { S: 'WWWWW,',      W: 'X',   X: 'Cv' },
            measurement:    { S: 'W.W.W,',      W: 'X',   X: 'VsC' },
            sequence:       { S: 'W.W.W.W,',    W: 'X',   X: 'CVC' },
            query_tech:     { S: 'W.W,',        W: 'XX',  X: 'sV' },
            verify:         { S: 'W.W,',        W: 'XX',  X: 'CVn' },
            acknowledged:   { S: 'W.W,',        W: 'X',   X: 'nVC' },
            update:         { S: 'W.W.W,',     W: 'XX',  X: 'pvC' },
            schematic:      { S: 'W.W.W,',      W: 'X',   X: 'spV' },
            survey:         { S: 'W.W.W.W,',    W: 'X',   X: 'sVs' },
            handoff:        { S: 'W,W,W,',      W: 'XX',  X: ['CV', 'pV'] },
            checksum:       { S: 'W.W.W,',      W: 'X',   X: 'Cvs' },
            manifest:       { S: 'WW.WW.WW,',   W: 'X',   X: 'CV' },
            triangulation:  { S: 'W.W.W.W.W,',  W: 'XX',  X: 'CVs' },
            calibration:    { S: 'W.W.W.W,',    W: 'X',   X: 'sCv' },
            parameter:      { S: 'W.W.W,',      W: 'XX',  X: ['CV', 'CvC'] },
            routing:        { S: 'W.W,',        W: 'XXX', X: 'CV' },
            timing:         { S: 'W.W,',        W: 'X',   X: 'pvp' },
            transmission:   { S: 'WW,WW,WW,',   W: 'X',   X: 'sCv' },
        },
    },
    casual: {
        note: 'Open, vowelly, conversational.',
        axiom: 'S', iterations: 4,
        variants: {
            relaxed: { S: 'W.W.W,', W: 'XX',  X: ['CV', 'VC', 'CVC', 'nV', 'Vn', 'lV', 'V'] },
            musing:  { S: 'W,W,',   W: 'XXX', X: ['Vv', 'nVv', 'VnV', 'VlV'] },
        },
    },
    question: {
        note: 'Pitch contour rises to the final "?". The "?" is kept as the '
            + 'last character so speakPhrase detects the question; speakSymbol '
            + 'ignores it so it doesn\'t generate a sound.',
        axiom: 'S', iterations: 4,
        variants: {
            plain:       { S: 'W.Wv?',     W: 'XX',  X: ['CV', 'nV', 'Vn', 'CVC', 'lV'] },
            curious:     { S: 'W.W.Wv?',   W: 'XX',  X: ['lV', 'nV', 'VnV'] },
            incredulous: { S: 'W.Wv?',     W: 'XX',  X: ['pV', 'CV', 'CVC'] },
            polite:      { S: 'W,W.Wv?',   W: 'XX',  X: ['lV', 'CV', 'nV'] },
            brief:       { S: 'Wv?',       W: 'XXX', X: ['CV', 'nV'] },
            rhetorical:  { S: 'W.W,Wv?',   W: 'XX',  X: ['VnV', 'VlV', 'V'] },
            probing:     { S: 'W.W.W.Wv?', W: 'X',   X: ['CV', 'nV', 'lV'] },
            echo:        { S: 'W?',        W: 'XX',  X: ['CV', 'nV'] },
            challenge:   { S: 'W.Wv?',     W: 'XX',  X: ['pV', 'CVp', 'pVC'] },
        },
    },
};

const INVENT_SYLL = ['ka','ne','so','ri','mu','lo','te','pa','zi','vo',
                     'ki','na','ju','be','fe','xo','qu','dy','gra','ush'];
const INVENT_S_PATTERNS = ['W','W.W','W.W.W','W,W','W.W,','W.W.W,',
                           'WW,','W.W.W.W,','WWW,','W,W.W,'];
const INVENT_W_PATTERNS = ['X','XX','XXX','X.','XXXX','X,'];
const INVENT_X_POOL = ['CV','VC','CVC','nV','Vn','lV','Vl','pV','sV',
                       'Vp','Vs','CsV','CVs','sCv','pCv','nVC','VlV',
                       'VnV','Cv','vC','pVp','nVl','lVn'];


// ── GrammarEngine class ────────────────────────────────────
export class GrammarEngine {
    constructor(options = {}) {
        const opts = options || {};
        this.name = opts.name || 'unnamed';
        this.seed = (opts.seed == null) ? (Date.now() & 0x7fffffff) : (opts.seed | 0);

        this.ctx = opts.ctx || null;
        this.master = opts.master || null;
        this.pink = null;
        this.pinkMode = opts.pinkMode || 'buffer';

        // Parameters (overridable per engine for different language scales)
        this.limits = Object.assign({}, DEFAULTS, opts.limits || {});

        // Runtime data tiers.
        this.PARTICLES = [];
        this.SUBWORDS = [];
        this.WORDS = [];
        this.SPEECH_GRAMMARS = {};

        this.utteranceLog = [];
        this.utteranceLogCap = this.limits.UTTERANCE_LOG_CAP;
        this.onLog = opts.onLog || null;

        this._churnTimers = [];

        // Populate from spec if provided; otherwise seed-generate.
        if (opts.spec && Object.keys(opts.spec).length) {
            this.loadSpec(opts.spec);
        } else {
            this.generateFresh(this.seed);
        }
    }

    // ── Audio attach / pink noise buffer ────────────────────
    attachAudio(ctx, master) {
        this.ctx = ctx;
        this.master = master || ctx.destination;
        this.pink = null;
    }

    setPinkMode(mode) {
        if (mode === 'buffer' || mode === 'live') this.pinkMode = mode;
    }

    _getPinkBuffer() {
        if (!this.ctx) return null;
        if (this.pink) return this.pink;
        const ctx = this.ctx;
        const secs = 8;
        const buf = ctx.createBuffer(1, ctx.sampleRate * secs, ctx.sampleRate);
        const d = buf.getChannelData(0);
        let b0=0, b1=0, b2=0, b3=0, b4=0, b5=0, b6=0;
        for (let i = 0; i < d.length; i++) {
            const w = Math.random() * 2 - 1;
            b0 = 0.99886 * b0 + w * 0.0555179;
            b1 = 0.99332 * b1 + w * 0.0750759;
            b2 = 0.96900 * b2 + w * 0.1538520;
            b3 = 0.86650 * b3 + w * 0.3104856;
            b4 = 0.55000 * b4 + w * 0.5329522;
            b5 = -0.7616 * b5 - w * 0.0168980;
            d[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
            b6 = w * 0.115926;
        }
        this.pink = buf;
        return buf;
    }

    // ── Deterministic generation ────────────────────────────
    generateFresh(seed) {
        const prng = mulberry32((seed | 0) || 1);
        const R  = prng;                    // raw number
        const rng = (lo, hi) => lo + R() * (hi - lo);
        const pick = (xs) => xs[Math.floor(R() * xs.length)];

        this.PARTICLES.length = 0;
        this.SUBWORDS.length = 0;
        this.WORDS.length = 0;
        this.SPEECH_GRAMMARS = JSON.parse(JSON.stringify(DEFAULT_SPEECH_GRAMMARS));

        const seedParticle = (type) => {
            const [dLo, dHi] = PARTICLE_DUR[type];
            const pp = {
                id: this.PARTICLES.length, type,
                dur: rng(dLo, dHi),
                offsetFrac: R() * 0.9 + 0.02,
                useCount: 0, born: Date.now(),
            };
            if (type === 'V' || type === 'v') {
                const [f1, f2] = VOWEL_FORMANTS[
                    Math.floor(R() * VOWEL_FORMANTS.length)];
                pp.bp1Freq = f1; pp.bp1Q = 10;
                pp.bp2Freq = f2; pp.bp2Q = 12;
                if (type === 'V' && R() < 0.28) {
                    const [g1, g2] = VOWEL_FORMANTS[
                        Math.floor(R() * VOWEL_FORMANTS.length)];
                    pp.bp1End = g1; pp.bp2End = g2;
                } else {
                    pp.bp1End = pp.bp1Freq * rng(0.95, 1.08);
                    pp.bp2End = pp.bp2Freq * rng(0.92, 1.10);
                }
                pp.gain = 0.9; pp.shape = 'vowel'; pp.voiced = true;
            } else if (type === 'n') {
                pp.bp1Freq = 260; pp.bp1End = pp.bp1Freq * rng(0.96, 1.04); pp.bp1Q = 12;
                pp.bp2Freq = 2100; pp.bp2End = pp.bp2Freq * rng(0.94, 1.08); pp.bp2Q = 8;
                pp.gain = 0.55; pp.shape = 'nasal'; pp.voiced = true;
            } else if (type === 'l') {
                pp.bp1Freq = 360; pp.bp1End = 330; pp.bp1Q = 9;
                pp.bp2Freq = 1100; pp.bp2End = 1400; pp.bp2Q = 8;
                pp.gain = 0.6; pp.shape = 'liquid'; pp.voiced = true;
            } else if (type === 'C') {
                pp.bp1Freq = rng(1200, 2400); pp.bp1Q = 3;
                pp.bp2Freq = rng(2800, 4500); pp.bp2Q = 3;
                pp.gain = 0.55; pp.shape = 'consonant'; pp.voiced = false;
            } else if (type === 's') {
                pp.bp1Freq = rng(3800, 6500); pp.bp1Q = 2;
                pp.bp2Freq = rng(5000, 8000); pp.bp2Q = 2;
                pp.gain = 0.5; pp.shape = 'sibilant'; pp.voiced = false;
            } else if (type === 'p') {
                pp.bp1Freq = rng(400, 800); pp.bp1Q = 1.5;
                pp.bp2Freq = rng(1200, 2000); pp.bp2Q = 1.5;
                pp.gain = 0.7; pp.shape = 'plosive'; pp.voiced = false;
            }
            this.PARTICLES.push(pp);
            return pp;
        };

        while (this.PARTICLES.length < this.limits.PARTICLE_SEED) {
            const t = PARTICLE_TYPE_BAG[Math.floor(R() * PARTICLE_TYPE_BAG.length)];
            seedParticle(t);
        }
        const seedPop = () => {
            const r = R();
            if (r < 0.70) return 2 + Math.floor(R() * 4);
            if (r < 0.95) return 6 + Math.floor(R() * 8);
            return 15 + Math.floor(R() * 20);
        };
        for (const pp of this.PARTICLES) pp.useCount = seedPop();

        const subTemplates = [
            'CV','VC','CVC','nV','Vn','lV','Vl','pV','Vp','sV','Vs',
            'CVn','nVC','lVn','nVl','VnV','VlV','CVl','lVC',
            'Cv','vC','vCv','nv','vn','lv','vl',
            'pVC','CVs','sVn','nVs',
        ];
        const genSubPattern = () => {
            if (R() < 0.7) return pick(subTemplates);
            const len = 2 + Math.floor(R() * 3);
            let p = '';
            for (let i = 0; i < len; i++) p += SYMS[Math.floor(R() * SYMS.length)];
            return p;
        };
        const pickPopPPOfType = (type) => {
            const pool = this.PARTICLES.filter(p => p.type === type);
            if (pool.length === 0) return seedParticle(type);
            let best = null, bestScore = -1;
            for (let i = 0; i < 5; i++) {
                const pp = pool[Math.floor(R() * pool.length)];
                const score = pp.useCount + R() * 0.8;
                if (score > bestScore) { bestScore = score; best = pp; }
            }
            return best;
        };
        const seedSub = () => {
            const pattern = genSubPattern();
            const particleIds = [];
            for (const ch of pattern) {
                if (!PARTICLE_DUR[ch]) continue;
                particleIds.push(pickPopPPOfType(ch).id);
            }
            if (particleIds.length === 0) return null;
            const pat = particleIds
                .map(i => (this.PARTICLES[i] || {type:'?'}).type).join('');
            const s = {
                id: this.SUBWORDS.length,
                particleIds, pattern: pat,
                useCount: seedPop(), born: Date.now(),
            };
            this.SUBWORDS.push(s);
            return s;
        };
        while (this.SUBWORDS.length < this.limits.SUBWORD_SEED) seedSub();

        const pickPopSub = () => {
            let best = null, bestScore = -1;
            for (let i = 0; i < 5; i++) {
                const s = this.SUBWORDS[Math.floor(R() * this.SUBWORDS.length)];
                const score = s.useCount + R() * 0.8;
                if (score > bestScore) { bestScore = score; best = s; }
            }
            return best;
        };
        while (this.WORDS.length < this.limits.WORD_COUNT) {
            const n = R() < 0.85
                ? 1 + Math.floor(R() * 5)
                : 6 + Math.floor(R() * 5);
            const subIds = [];
            for (let i = 0; i < n; i++) {
                const sub = pickPopSub();
                subIds.push(sub ? sub.id : Math.floor(R() * this.SUBWORDS.length));
            }
            this.WORDS.push({
                id: this.WORDS.length,
                subIds,
                useCount: seedPop(),
                born: Date.now(),
            });
        }
    }

    loadSpec(spec) {
        this.PARTICLES = (spec.particles || []).map(p => ({ ...p }));
        this.SUBWORDS = (spec.subwords || []).map(s => ({
            ...s, particleIds: (s.particleIds || []).slice(),
        }));
        this.WORDS = (spec.words || []).map(w => ({
            ...w, subIds: (w.subIds || []).slice(),
        }));
        this.SPEECH_GRAMMARS = JSON.parse(JSON.stringify(
            spec.grammars || DEFAULT_SPEECH_GRAMMARS));
        if (spec.seed != null) this.seed = spec.seed | 0;
        if (spec.name) this.name = spec.name;
    }

    serialize() {
        return {
            name: this.name,
            seed: this.seed,
            particles: this.PARTICLES.map(p => ({ ...p })),
            subwords:  this.SUBWORDS.map(s => ({
                ...s, particleIds: s.particleIds.slice(),
            })),
            words:     this.WORDS.map(w => ({
                ...w, subIds: w.subIds.slice(),
            })),
            grammars: JSON.parse(JSON.stringify(this.SPEECH_GRAMMARS)),
        };
    }

    // ── Runtime helpers ─────────────────────────────────────
    _rng(lo, hi) { return lo + Math.random() * (hi - lo); }
    _pick(xs) { return xs[Math.floor(Math.random() * xs.length)]; }

    _pickParticleOfType(type) {
        const pool = [];
        for (const pp of this.PARTICLES) if (pp.type === type) pool.push(pp);
        if (pool.length === 0) return this._newParticle(type);
        return pool[Math.floor(Math.random() * pool.length)];
    }

    _pickPopularParticleOfType(type, k) {
        k = k || 5;
        const pool = this.PARTICLES.filter(p => p.type === type);
        if (pool.length === 0) return this._newParticle(type);
        let best = null, bestScore = -1;
        for (let i = 0; i < k; i++) {
            const pp = pool[Math.floor(Math.random() * pool.length)];
            const score = pp.useCount + Math.random() * 0.8;
            if (score > bestScore) { bestScore = score; best = pp; }
        }
        return best;
    }

    _pickPopularSubword(k) {
        k = k || 5;
        if (this.SUBWORDS.length === 0) return null;
        let best = null, bestScore = -1;
        for (let i = 0; i < k; i++) {
            const s = this.SUBWORDS[Math.floor(Math.random() * this.SUBWORDS.length)];
            const score = s.useCount + Math.random() * 0.8;
            if (score > bestScore) { bestScore = score; best = s; }
        }
        return best;
    }

    _pickWordByPopularity(k) {
        k = k || 5;
        if (this.WORDS.length === 0) return null;
        let best = null, bestScore = -1;
        for (let i = 0; i < k; i++) {
            const w = this.WORDS[Math.floor(Math.random() * this.WORDS.length)];
            const score = w.useCount + Math.random() * 0.8;
            if (score > bestScore) { bestScore = score; best = w; }
        }
        return best;
    }

    _newParticle(type) {
        const [dLo, dHi] = PARTICLE_DUR[type];
        const pp = {
            id: this.PARTICLES.length, type,
            dur: this._rng(dLo, dHi),
            offsetFrac: Math.random() * 0.9 + 0.02,
            useCount: 0, born: Date.now(),
        };
        if (type === 'V' || type === 'v') {
            const [f1, f2] = VOWEL_FORMANTS[
                Math.floor(Math.random() * VOWEL_FORMANTS.length)];
            pp.bp1Freq = f1; pp.bp1Q = 10;
            pp.bp2Freq = f2; pp.bp2Q = 12;
            if (type === 'V' && Math.random() < 0.28) {
                const [g1, g2] = VOWEL_FORMANTS[
                    Math.floor(Math.random() * VOWEL_FORMANTS.length)];
                pp.bp1End = g1; pp.bp2End = g2;
            } else {
                pp.bp1End = pp.bp1Freq * this._rng(0.95, 1.08);
                pp.bp2End = pp.bp2Freq * this._rng(0.92, 1.10);
            }
            pp.gain = 0.9; pp.shape = 'vowel'; pp.voiced = true;
        } else if (type === 'n') {
            pp.bp1Freq = 260; pp.bp1End = pp.bp1Freq * this._rng(0.96, 1.04); pp.bp1Q = 12;
            pp.bp2Freq = 2100; pp.bp2End = pp.bp2Freq * this._rng(0.94, 1.08); pp.bp2Q = 8;
            pp.gain = 0.55; pp.shape = 'nasal'; pp.voiced = true;
        } else if (type === 'l') {
            pp.bp1Freq = 360; pp.bp1End = 330; pp.bp1Q = 9;
            pp.bp2Freq = 1100; pp.bp2End = 1400; pp.bp2Q = 8;
            pp.gain = 0.6; pp.shape = 'liquid'; pp.voiced = true;
        } else if (type === 'C') {
            pp.bp1Freq = this._rng(1200, 2400); pp.bp1Q = 3;
            pp.bp2Freq = this._rng(2800, 4500); pp.bp2Q = 3;
            pp.gain = 0.55; pp.shape = 'consonant'; pp.voiced = false;
        } else if (type === 's') {
            pp.bp1Freq = this._rng(3800, 6500); pp.bp1Q = 2;
            pp.bp2Freq = this._rng(5000, 8000); pp.bp2Q = 2;
            pp.gain = 0.5; pp.shape = 'sibilant'; pp.voiced = false;
        } else if (type === 'p') {
            pp.bp1Freq = this._rng(400, 800); pp.bp1Q = 1.5;
            pp.bp2Freq = this._rng(1200, 2000); pp.bp2Q = 1.5;
            pp.gain = 0.7; pp.shape = 'plosive'; pp.voiced = false;
        }
        this.PARTICLES.push(pp);
        return pp;
    }

    _randParticleType() {
        return PARTICLE_TYPE_BAG[
            Math.floor(Math.random() * PARTICLE_TYPE_BAG.length)];
    }

    addParticle(type) { return this._newParticle(type); }

    addSubword(input) {
        let particleIds;
        if (Array.isArray(input)) {
            particleIds = input.slice();
        } else {
            particleIds = [];
            for (const ch of String(input)) {
                if (!PARTICLE_DUR[ch]) continue;
                particleIds.push(this._pickPopularParticleOfType(ch).id);
            }
        }
        if (particleIds.length === 0) return null;
        const pattern = particleIds
            .map(i => (this.PARTICLES[i] || {type:'?'}).type).join('');
        const s = {
            id: this.SUBWORDS.length,
            particleIds, pattern,
            useCount: 0, born: Date.now(),
        };
        this.SUBWORDS.push(s);
        return s;
    }

    addRandomWord() {
        const n = Math.random() < 0.85
            ? 1 + Math.floor(Math.random() * 5)
            : 6 + Math.floor(Math.random() * 5);
        const subIds = [];
        for (let i = 0; i < n; i++) {
            const sub = this._pickPopularSubword();
            subIds.push(sub ? sub.id
                : Math.floor(Math.random() * this.SUBWORDS.length));
        }
        const w = { id: this.WORDS.length, subIds, useCount: 0, born: Date.now() };
        this.WORDS.push(w);
        return w;
    }

    // ── Phrase generation ──────────────────────────────────
    expandGrammarMeta(kind) {
        const keys = Object.keys(this.SPEECH_GRAMMARS);
        if (keys.length === 0) {
            return { symbols: '', kind: null, variant: null, words: null };
        }
        const chosenKind = kind || keys[Math.floor(Math.random() * keys.length)];
        const g = this.SPEECH_GRAMMARS[chosenKind];
        if (!g) return { symbols: '', kind: chosenKind, variant: null, words: null };
        const variantNames = Object.keys(g.variants);
        const variantName = variantNames[Math.floor(Math.random() * variantNames.length)];
        const variant = g.variants[variantName];
        const rules = {};
        for (const [key, val] of Object.entries(variant)) {
            rules[key] = Array.isArray(val)
                ? val[Math.floor(Math.random() * val.length)] : val;
        }
        const symbols = new LSystem(g.axiom || 'S', rules, g.iterations || 4).expand();
        return { symbols, kind: chosenKind, variant: variantName, words: null };
    }
    expandGrammar(kind) { return this.expandGrammarMeta(kind).symbols; }
    generatePhrase(kind) { return this.expandGrammar(kind); }

    generateVocabPhraseMeta() {
        const wordCount = 2 + Math.floor(Math.random() * 4);
        const wordsPicked = [];
        const units = [];
        const parts = [];
        for (let i = 0; i < wordCount; i++) {
            const w = this._pickWordByPopularity();
            if (!w) continue;
            wordsPicked.push(w);
            let syms = '';
            for (const sid of w.subIds) {
                const sub = this.SUBWORDS[sid];
                if (!sub) continue;
                sub.useCount++;
                syms += sub.pattern;
                for (const pid of sub.particleIds) {
                    if (this.PARTICLES[pid]) units.push({ kind: 'pp', id: pid });
                }
            }
            w.useCount++;
            parts.push(syms);
            if (i < wordCount - 1) units.push({ kind: 'punct', char: '.' });
        }
        const ending = Math.random() < 0.15 ? '?'
                     : Math.random() < 0.08 ? '!' : ',';
        units.push({ kind: 'punct', char: ending });
        return {
            symbols: parts.join('.') + ending,
            units, words: wordsPicked,
            kind: 'vocab', variant: null,
        };
    }
    generateVocabPhrase() { return this.generateVocabPhraseMeta().symbols; }

    // ── Speech renderers ───────────────────────────────────
    _makeSpeaker() {
        const lower = Math.random() < 0.5;
        return {
            pitch:        lower ? this._rng(88, 138)  : this._rng(170, 245),
            formantShift: lower ? this._rng(0.92, 1.02) : this._rng(1.05, 1.20),
            rate:         this._rng(0.9, 1.15),
            breathiness:  this._rng(0.08, 0.22),
            vibrato:      this._rng(3.5, 5.5),
            vibratoDepth: this._rng(0.006, 0.020),
        };
    }

    _makePitchContour(phraseStart, phraseDur, ending) {
        const dur = Math.max(phraseDur, 0.05);
        return (t) => {
            const x = Math.max(0, Math.min(1, (t - phraseStart) / dur));
            if (ending === '?')   return 0.92 + 0.40 * Math.pow(x, 1.6);
            if (ending === '!')   return 1.15 - 0.30 * x;
            return 1.06 - 0.24 * x;
        };
    }

    _estimatePhraseDur(symbols, speaker) {
        let total = 0;
        for (const c of symbols) total += (SYMBOL_MEAN_DUR[c] || 0) * speaker.rate;
        return total + 0.02 * symbols.length;
    }

    _speakSymbol(sym, t, distance, pan, speaker, pitchAt) {
        const ctx = this.ctx;
        if (!ctx) return 0;
        const fs = speaker.formantShift;
        const rate = speaker.rate;
        const buf = this._getPinkBuffer();
        if (!buf) return 0;

        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.loop = true;
        const offset = Math.random() * (buf.duration - 1);

        let dur, bp1Freq, bp1Q, bp2Freq, bp2Q, gain, shape;
        let bp1End, bp2End, voiced = false;
        if (sym === 'V' || sym === 'v') {
            const [f1, f2] = VOWEL_FORMANTS[
                Math.floor(Math.random() * VOWEL_FORMANTS.length)];
            bp1Freq = f1 * fs; bp1Q = 10;
            bp2Freq = f2 * fs; bp2Q = 12;
            if (sym === 'V' && Math.random() < 0.28) {
                const [g1, g2] = VOWEL_FORMANTS[
                    Math.floor(Math.random() * VOWEL_FORMANTS.length)];
                bp1End = g1 * fs; bp2End = g2 * fs;
            } else {
                bp1End = bp1Freq * this._rng(0.95, 1.08);
                bp2End = bp2Freq * this._rng(0.92, 1.10);
            }
            dur = (sym === 'V' ? this._rng(0.14, 0.22) : this._rng(0.07, 0.11)) * rate;
            gain = 0.9; shape = 'vowel'; voiced = true;
        } else if (sym === 'n') {
            bp1Freq = 260 * fs; bp1End = bp1Freq * this._rng(0.96, 1.04); bp1Q = 12;
            bp2Freq = 2100 * fs; bp2End = bp2Freq * this._rng(0.94, 1.08); bp2Q = 8;
            dur = this._rng(0.07, 0.11) * rate;
            gain = 0.55; shape = 'nasal'; voiced = true;
        } else if (sym === 'l') {
            bp1Freq = 360 * fs; bp1End = 330 * fs; bp1Q = 9;
            bp2Freq = 1100 * fs; bp2End = 1400 * fs; bp2Q = 8;
            dur = this._rng(0.06, 0.10) * rate;
            gain = 0.6; shape = 'liquid'; voiced = true;
        } else if (sym === 'C') {
            bp1Freq = this._rng(1200, 2400) * fs; bp1Q = 3;
            bp2Freq = this._rng(2800, 4500) * fs; bp2Q = 3;
            dur = this._rng(0.045, 0.07) * rate;
            gain = 0.55; shape = 'consonant';
        } else if (sym === 's') {
            bp1Freq = this._rng(3800, 6500); bp1Q = 2;
            bp2Freq = this._rng(5000, 8000); bp2Q = 2;
            dur = this._rng(0.035, 0.06) * rate;
            gain = 0.5; shape = 'sibilant';
        } else if (sym === 'p') {
            bp1Freq = this._rng(400, 800); bp1Q = 1.5;
            bp2Freq = this._rng(1200, 2000); bp2Q = 1.5;
            dur = this._rng(0.02, 0.035) * rate;
            gain = 0.7; shape = 'plosive';
        } else {
            return 0;
        }

        const bp1 = ctx.createBiquadFilter();
        bp1.type = 'bandpass';
        bp1.frequency.value = bp1Freq; bp1.Q.value = bp1Q;
        const bp2 = ctx.createBiquadFilter();
        bp2.type = 'bandpass';
        bp2.frequency.value = bp2Freq; bp2.Q.value = bp2Q;
        const mix = ctx.createGain();
        mix.gain.value = 0.45;

        const env = ctx.createGain();
        env.gain.value = 0.0001;
        if (shape === 'vowel' || shape === 'nasal' || shape === 'liquid') {
            env.gain.exponentialRampToValueAtTime(gain, t + 0.015);
            env.gain.setValueAtTime(gain, t + Math.max(0.01, dur - 0.03));
            env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
            bp1.frequency.setValueAtTime(bp1Freq, t);
            bp1.frequency.linearRampToValueAtTime(bp1End, t + dur);
            bp2.frequency.setValueAtTime(bp2Freq, t);
            bp2.frequency.linearRampToValueAtTime(bp2End, t + dur);
        } else if (shape === 'plosive') {
            env.gain.linearRampToValueAtTime(gain, t + 0.004);
            env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        } else {
            env.gain.exponentialRampToValueAtTime(gain, t + 0.008);
            env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        }

        const panN = ctx.createStereoPanner();
        panN.pan.value = pan;
        const distG = ctx.createGain();
        distG.gain.value = 0.35 + distance * 0.5;

        const breath = ctx.createGain();
        breath.gain.value = voiced ? speaker.breathiness : 1.0;
        src.connect(breath);
        breath.connect(bp1); breath.connect(bp2);
        bp1.connect(mix); bp2.connect(mix);

        if (voiced) {
            const osc = ctx.createOscillator();
            osc.type = 'sawtooth';
            const f0a = speaker.pitch * pitchAt(t);
            const f0b = speaker.pitch * pitchAt(t + dur);
            osc.frequency.setValueAtTime(f0a, t);
            osc.frequency.linearRampToValueAtTime(f0b, t + dur);
            const lfo = ctx.createOscillator();
            lfo.frequency.value = speaker.vibrato;
            const lfoGain = ctx.createGain();
            lfoGain.gain.value = f0a * speaker.vibratoDepth;
            lfo.connect(lfoGain).connect(osc.frequency);
            const voiceGain = ctx.createGain();
            voiceGain.gain.value = shape === 'nasal' ? 0.55
                                 : shape === 'liquid' ? 0.75 : 0.9;
            osc.connect(voiceGain);
            voiceGain.connect(bp1); voiceGain.connect(bp2);
            osc.start(t); osc.stop(t + dur + 0.03);
            lfo.start(t); lfo.stop(t + dur + 0.03);
        }

        mix.connect(env).connect(panN).connect(distG).connect(this.master);
        src.start(t, offset);
        src.stop(t + dur + 0.02);
        return dur;
    }

    _speakParticle(pp, t, distance, pan, speaker, pitchAt) {
        const ctx = this.ctx;
        if (!ctx) return 0;
        const fs = speaker.formantShift;
        const rate = speaker.rate;
        const buf = this._getPinkBuffer();
        if (!buf) return 0;
        const dur = pp.dur * rate;

        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.loop = false;
        const span = buf.duration - 0.3;
        const offset = this.pinkMode === 'live'
            ? ((ctx.currentTime + pp.offsetFrac * span) % span)
            : pp.offsetFrac * span;

        const bp1 = ctx.createBiquadFilter();
        bp1.type = 'bandpass';
        bp1.frequency.value = pp.bp1Freq * fs; bp1.Q.value = pp.bp1Q;
        const bp2 = ctx.createBiquadFilter();
        bp2.type = 'bandpass';
        bp2.frequency.value = pp.bp2Freq * fs; bp2.Q.value = pp.bp2Q;
        const mix = ctx.createGain();
        mix.gain.value = 0.45;

        const env = ctx.createGain();
        env.gain.value = 0.0001;
        const shape = pp.shape;
        const gain = pp.gain;
        if (shape === 'vowel' || shape === 'nasal' || shape === 'liquid') {
            env.gain.exponentialRampToValueAtTime(gain, t + 0.015);
            env.gain.setValueAtTime(gain, t + Math.max(0.01, dur - 0.03));
            env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
            bp1.frequency.setValueAtTime(pp.bp1Freq * fs, t);
            bp1.frequency.linearRampToValueAtTime((pp.bp1End || pp.bp1Freq) * fs, t + dur);
            bp2.frequency.setValueAtTime(pp.bp2Freq * fs, t);
            bp2.frequency.linearRampToValueAtTime((pp.bp2End || pp.bp2Freq) * fs, t + dur);
        } else if (shape === 'plosive') {
            env.gain.linearRampToValueAtTime(gain, t + 0.004);
            env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        } else {
            env.gain.exponentialRampToValueAtTime(gain, t + 0.008);
            env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        }

        const panN = ctx.createStereoPanner();
        panN.pan.value = pan;
        const distG = ctx.createGain();
        distG.gain.value = 0.35 + distance * 0.5;

        const breath = ctx.createGain();
        breath.gain.value = pp.voiced ? speaker.breathiness : 1.0;
        src.connect(breath);
        breath.connect(bp1); breath.connect(bp2);
        bp1.connect(mix); bp2.connect(mix);

        if (pp.voiced) {
            const osc = ctx.createOscillator();
            osc.type = 'sawtooth';
            const f0a = speaker.pitch * pitchAt(t);
            const f0b = speaker.pitch * pitchAt(t + dur);
            osc.frequency.setValueAtTime(f0a, t);
            osc.frequency.linearRampToValueAtTime(f0b, t + dur);
            const lfo = ctx.createOscillator();
            lfo.frequency.value = speaker.vibrato;
            const lfoGain = ctx.createGain();
            lfoGain.gain.value = f0a * speaker.vibratoDepth;
            lfo.connect(lfoGain).connect(osc.frequency);
            const voiceGain = ctx.createGain();
            voiceGain.gain.value = shape === 'nasal' ? 0.55
                                 : shape === 'liquid' ? 0.75 : 0.9;
            osc.connect(voiceGain);
            voiceGain.connect(bp1); voiceGain.connect(bp2);
            osc.start(t); osc.stop(t + dur + 0.03);
            lfo.start(t); lfo.stop(t + dur + 0.03);
        }

        mix.connect(env).connect(panN).connect(distG).connect(this.master);
        src.start(t, offset);
        src.stop(t + dur + 0.02);
        pp.useCount++;
        return dur;
    }

    speakPhrase(symbols, distance) {
        if (!this.ctx) return;
        const pan = this._rng(-0.85, 0.85);
        const speaker = this._makeSpeaker();
        let ending = '.';
        for (let i = symbols.length - 1; i >= 0; i--) {
            const c = symbols[i];
            if (c === '?' || c === '!' || c === '.' || c === ',') {
                ending = c; break;
            }
        }
        const phraseStart = this.ctx.currentTime + 0.02;
        const phraseDur = this._estimatePhraseDur(symbols, speaker);
        const pitchAt = this._makePitchContour(phraseStart, phraseDur, ending);
        let t = phraseStart;
        for (const sym of symbols) {
            if (sym === '.') {
                t += this._rng(0.06, 0.13);
            } else if (sym === ',') {
                t += this._rng(0.22, 0.45);
            } else {
                const dur = this._speakSymbol(sym, t, distance, pan, speaker, pitchAt);
                t += dur + this._rng(0.01, 0.04);
            }
        }
    }

    speakUnits(units, distance) {
        if (!this.ctx) return;
        const pan = this._rng(-0.85, 0.85);
        const speaker = this._makeSpeaker();

        let ending = '.';
        for (let i = units.length - 1; i >= 0; i--) {
            const u = units[i];
            if (u.kind === 'punct') { ending = u.char; break; }
        }
        const phraseStart = this.ctx.currentTime + 0.02;
        let est = 0;
        for (const u of units) {
            if (u.kind === 'pp' && this.PARTICLES[u.id]) {
                est += this.PARTICLES[u.id].dur * speaker.rate + 0.02;
            } else if (u.kind === 'punct') {
                est += u.char === ',' ? 0.33 : 0.09;
            }
        }
        const pitchAt = this._makePitchContour(phraseStart, est, ending);
        let t = phraseStart;
        for (const u of units) {
            if (u.kind === 'pp') {
                const pp = this.PARTICLES[u.id];
                if (!pp) continue;
                const dur = this._speakParticle(pp, t, distance, pan, speaker, pitchAt);
                t += dur + this._rng(0.01, 0.04);
            } else if (u.kind === 'punct') {
                if (u.char === '.') t += this._rng(0.06, 0.13);
                else if (u.char === ',') t += this._rng(0.22, 0.45);
            }
        }
    }

    // ── Evolution + invention ───────────────────────────────
    mutateSubword(particleIds) {
        const arr = particleIds.slice();
        const op = Math.random();
        if (op < 0.3 && arr.length > 2) {
            arr.splice(Math.floor(Math.random() * arr.length), 1);
        } else if (op < 0.55 && arr.length < 5) {
            const i = Math.floor(Math.random() * (arr.length + 1));
            const t = this._randParticleType();
            arr.splice(i, 0, this._pickPopularParticleOfType(t).id);
        } else if (op < 0.8 && arr.length) {
            const i = Math.floor(Math.random() * arr.length);
            const oldPP = this.PARTICLES[arr[i]];
            const t = (oldPP && Math.random() < 0.7)
                ? oldPP.type : this._randParticleType();
            arr[i] = this._pickPopularParticleOfType(t).id;
        } else if (arr.length) {
            const i = Math.floor(Math.random() * arr.length);
            arr.splice(i + 1, 0, arr[i]);
        }
        return arr;
    }

    evolve() {
        const { PARTICLE_CAP, PARTICLE_MIN, SUBWORD_CAP } = this.limits;

        const sortedP = [...this.PARTICLES].sort((a, b) => b.useCount - a.useCount);
        const topPN = Math.max(2, Math.floor(this.PARTICLES.length * 0.03));
        for (let i = 0; i < topPN; i++) {
            if (this.PARTICLES.length >= PARTICLE_CAP) break;
            const parent = sortedP[i];
            if (!parent) break;
            this._newParticle(parent.type);
        }
        const pAgeT = Date.now() - 120000;
        const freshP = this.PARTICLES.filter(p => !(p.useCount === 0 && p.born < pAgeT));
        const staleP = this.PARTICLES.filter(p =>   p.useCount === 0 && p.born < pAgeT);
        const neededP = Math.max(0, PARTICLE_MIN - freshP.length);
        const keepP = freshP.concat(staleP.slice(0, neededP));
        if (keepP.length !== this.PARTICLES.length) {
            const idMap = new Map();
            keepP.forEach((p, i) => { idMap.set(p.id, i); });
            const typeSurvivors = {};
            keepP.forEach((p, i) => {
                if (!typeSurvivors[p.type]) typeSurvivors[p.type] = [];
                typeSurvivors[p.type].push(i);
            });
            for (const s of this.SUBWORDS) {
                s.particleIds = s.particleIds.map(oldId => {
                    if (idMap.has(oldId)) return idMap.get(oldId);
                    const t = (this.PARTICLES[oldId] || {type: 'V'}).type;
                    const pool = typeSurvivors[t];
                    if (pool && pool.length) {
                        return pool[Math.floor(Math.random() * pool.length)];
                    }
                    return Math.floor(Math.random() * keepP.length);
                });
            }
            keepP.forEach((p, i) => { p.id = i; });
            this.PARTICLES.length = 0;
            this.PARTICLES.push(...keepP);
            for (const s of this.SUBWORDS) {
                s.pattern = s.particleIds
                    .map(i => (this.PARTICLES[i] || {type:'?'}).type).join('');
            }
        }

        const sorted = [...this.SUBWORDS].sort((a, b) => b.useCount - a.useCount);
        const topN = Math.max(2, Math.floor(this.SUBWORDS.length * 0.02));
        for (let i = 0; i < topN; i++) {
            if (this.SUBWORDS.length >= SUBWORD_CAP) break;
            const parent = sorted[i];
            if (!parent) break;
            this.addSubword(this.mutateSubword(parent.particleIds));
        }

        const ageThreshold = Date.now() - 120000;
        const fresh = this.SUBWORDS.filter(
            s => !(s.useCount === 0 && s.born < ageThreshold));
        const stale = this.SUBWORDS.filter(
            s =>   s.useCount === 0 && s.born < ageThreshold);
        const needed = Math.max(0, this.limits.SUBWORD_MIN - fresh.length);
        const keep = fresh.concat(stale.slice(0, needed));
        if (keep.length !== this.SUBWORDS.length) {
            const idMap = new Map();
            keep.forEach((s, i) => { idMap.set(s.id, i); });
            keep.forEach((s, i) => { s.id = i; });
            for (const w of this.WORDS) {
                w.subIds = w.subIds.map(id =>
                    idMap.has(id) ? idMap.get(id)
                                  : Math.floor(Math.random() * keep.length));
            }
            this.SUBWORDS.length = 0;
            this.SUBWORDS.push(...keep);
        }
    }

    invent() {
        let name = '';
        const pk = (xs) => xs[Math.floor(Math.random() * xs.length)];
        for (let i = 0; i < 3; i++) name += pk(INVENT_SYLL);
        while (this.SPEECH_GRAMMARS[name]) name += pk(INVENT_SYLL);
        const nVariants = 1 + Math.floor(Math.random() * 3);
        const variants = {};
        for (let v = 0; v < nVariants; v++) {
            const choices = [];
            const nChoices = 1 + Math.floor(Math.random() * 4);
            for (let j = 0; j < nChoices; j++) choices.push(pk(INVENT_X_POOL));
            variants['v' + (v + 1)] = {
                S: pk(INVENT_S_PATTERNS),
                W: pk(INVENT_W_PATTERNS),
                X: choices.length === 1 ? choices[0] : choices,
            };
        }
        this.SPEECH_GRAMMARS[name] = {
            note: 'auto-invented at ' + new Date().toLocaleTimeString(),
            axiom: 'S', iterations: 4, variants,
            born: Date.now(), invented: true,
        };
        return name;
    }

    pruneUnusedWords(n) {
        n = n || 3;
        const grace = Date.now() - 120000;
        const candidates = this.WORDS
            .filter(w => w.useCount === 0 && w.born < grace)
            .sort((a, b) => a.born - b.born);
        const victims = new Set(candidates.slice(0, n));
        if (victims.size === 0) return 0;
        const kept = this.WORDS.filter(w => !victims.has(w));
        kept.forEach((w, i) => { w.id = i; });
        this.WORDS.length = 0;
        this.WORDS.push(...kept);
        return victims.size;
    }

    // ── Churn timers — caller opts in ───────────────────────
    startChurn(options) {
        this.stopChurn();
        const opts = options || {};
        const evolveMs  = opts.evolveMs  || 45000;
        const inventMs  = opts.inventMs  || 30000;
        const wordAddMs = opts.wordAddMs || 60000;
        const prunedMs  = opts.prunedMs  || 120000;
        const gate = opts.gate || (() => true);
        this._churnTimers.push(
            setInterval(() => { if (gate()) this.evolve(); }, evolveMs),
            setInterval(() => { if (gate()) this.invent(); }, inventMs),
            setInterval(() => { if (gate()) this.addRandomWord(); }, wordAddMs),
            setInterval(() => { if (gate()) this.pruneUnusedWords(); }, prunedMs),
        );
    }

    stopChurn() {
        for (const t of this._churnTimers) clearInterval(t);
        this._churnTimers = [];
    }

    // ── Logging + stats ────────────────────────────────────
    logUtterance(entry) {
        this.utteranceLog.push(entry);
        if (this.utteranceLog.length > this.utteranceLogCap) {
            this.utteranceLog.splice(
                0, this.utteranceLog.length - this.utteranceLogCap);
        }
        if (this.onLog) this.onLog(entry);
    }

    stats() {
        return {
            particles: this.PARTICLES.length,
            subwords:  this.SUBWORDS.length,
            words:     this.WORDS.length,
            grammars:  Object.keys(this.SPEECH_GRAMMARS).length,
            usedParticles: this.PARTICLES.filter(p => p.useCount > 0).length,
            usedSubwords:  this.SUBWORDS.filter(s => s.useCount > 0).length,
            usedWords:     this.WORDS.filter(w => w.useCount > 0).length,
            totalSpeakEvents: this.WORDS.reduce((s, w) => s + w.useCount, 0),
        };
    }
}

// Also export static data the Inspector renders against.
GrammarEngine.PARTICLE_DUR = PARTICLE_DUR;
GrammarEngine.VOWEL_FORMANTS = VOWEL_FORMANTS;
GrammarEngine.SYMS = SYMS;

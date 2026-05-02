// stratum.mjs — sublab: two-layer hex CA where the outer layer is
// driven by the elite of the inner layer's evolving population.
//
// LIBRARY: 64 K=64 HexNN rules ("colours" in the meta-CA's palette).
// Each library entry holds a unique genome + unique palette + own
// running grid + cached bins + last-known fitness.
//
// META-CA: a 16x16 hex grid whose cell states are integers 0..63 —
// each state names a library entry. The meta-CA steps using the
// elite library entry's HexNN ruleset; as evolution shifts who's at
// the top of the library, the meta-CA's stepping rule changes with it.
//
// RENDER: each of the 256 meta-cells displays the live grid of the
// library entry it currently indexes, painted with that entry's own
// palette. Multiple meta-cells with the same state render identical
// patterns — which makes "regions" of the meta-CA's state visible at
// a glance.
//
// EVOLUTION: tournament rounds between random library entries on a
// separate clock (~5s default). Loser is replaced by a mutated copy
// of winner; palette inherits from winner. Elite index updates
// whenever a re-score exceeds the current best.
//
// Substrate is hexagonal at three scales (cells in CA → tiles in
// library / meta → if you tile this sublab side-by-side with itself).

import {
    N_LOG2, N_ENTRIES, mulberry32,
    makeGenome, buildBins, lookup, stepWithGenomeBins,
    score, mutateGenome, crossover, freshGrid,
    PALETTE_MODES, makePaletteRGBA, paletteRGBAToCssHex,
    ansi256_rgb,
} from '../hexnn_engine.mjs';


// ── Layout ─────────────────────────────────────────────────────────

const LIB_K       = 64;          // K value for every library entry's CA
const LIB_SIZE    = 64;          // population size — also the meta-CA's
                                 // K (since each state names a library
                                 // entry). 64 = nice 8x8 thumbnail strip.
const LIB_ROWS    = 8;
const LIB_COLS    = 8;
const META_ROWS   = 16;
const META_COLS   = 16;

const INNER_W     = 16;          // each library CA's inner grid (hex)
const INNER_H     = 16;

const LIB_TILE_PX = 32;          // size of one library thumbnail
const LIB_TILE_GAP = 3;
const META_TILE_PX = 24;         // size of one meta-cell display
const META_TILE_GAP = 3;

// Inner hex render — pointy-top with odd rows shifted +CELL_PX/2.
// Cell sizes are float (TILE / (W + 0.5)); pixel coords floor.
const LIB_CELL_PX  = LIB_TILE_PX  / (INNER_W + 0.5);
const META_CELL_PX = META_TILE_PX / (INNER_W + 0.5);

// Canvas dimensions (pre-sized via JS in init() too — JS is the
// source of truth, the HTML attrs are just initial layout hints).
const LIB_CANVAS_W  = LIB_COLS * (LIB_TILE_PX + LIB_TILE_GAP) - LIB_TILE_GAP + LIB_TILE_PX / 2;
const LIB_CANVAS_H  = LIB_ROWS * (LIB_TILE_PX + LIB_TILE_GAP) - LIB_TILE_GAP;
const META_CANVAS_W = META_COLS * (META_TILE_PX + META_TILE_GAP) - META_TILE_GAP + META_TILE_PX / 2;
const META_CANVAS_H = META_ROWS * (META_TILE_PX + META_TILE_GAP) - META_TILE_GAP;


// ── Algorithm tunables ─────────────────────────────────────────────

const DEFAULT_INNER_TICK_MS  = 200;     // step every library CA
const DEFAULT_META_TICK_MS   = 2000;    // step the meta-CA grid
const DEFAULT_TOURN_MS       = 5000;    // tournament round between library entries
const DEFAULT_MUT_RATE       = 0.0008;  // mutation rate when copying winner→loser

// Score parameters — keep modest to keep tournament rounds responsive.
const SCORE_STEPS  = 25;
const SCORE_BURNIN = 6;


// ── State ──────────────────────────────────────────────────────────

function makeLibraryEntry(seed, paletteMode) {
    const genome      = makeGenome(LIB_K, seed);
    const paletteRGBA = makePaletteRGBA(LIB_K, paletteMode,
                                          mulberry32(seed ^ 0xA5A5A5A5));
    const gridA       = freshGrid(INNER_W, INNER_H, LIB_K,
                                   mulberry32(seed ^ 0xCAFE_BABE));
    const bins        = buildBins(genome);
    return { genome, paletteRGBA, gridA, bins, fitness: 0, r: 0 };
}

const state = {
    library:    [],                   // length LIB_SIZE
    eliteIdx:   0,
    eliteBins:  null,                 // alias of library[eliteIdx].bins (for meta step)

    metaA: new Uint8Array(META_ROWS * META_COLS),
    metaB: new Uint8Array(META_ROWS * META_COLS),

    running:    true,

    innerTickMs: DEFAULT_INNER_TICK_MS,
    metaTickMs:  DEFAULT_META_TICK_MS,
    tournMs:     DEFAULT_TOURN_MS,
    mutRate:     DEFAULT_MUT_RATE,

    innerHandle: null,
    metaHandle:  null,
    tournHandle: null,

    metaTicks: 0,
    rounds: 0,

    hunting: false,                   // true while a GA hunt is in flight;
                                      // tournament rounds skip while set
    huntKind: '',                     // 'hunt' | 'refine' for status text

    paletteMode: 'random-ansi',       // current palette generator; user-
                                      // tunable via the select in the UI.
                                      // Applies to every newly-minted CA
                                      // (bootstrap, hunt-insert, tournament
                                      // replacement); changing the mode
                                      // also rebuilds every existing CA's
                                      // palette in place.
};


// ── Hunt parameters ────────────────────────────────────────────────
//
// Hunt and Refine run separate compact GAs with different defaults:
//
//   Hunt   — pop=8, gens=20. Half mutated from elite (4× rate), half
//            random. Quick broad search; ~3-4 s.
//   Refine — pop=8, gens=64. All mutated from elite at the standard
//            rate. Iterative sharpening; ~10-13 s. The 3× longer
//            schedule reflects refine's role: when you're warm-starting
//            from an already-good rule, more gens of grinding is what
//            actually moves the needle.
//
// gen counts are user-tunable via the input next to each button so
// you can crank refine higher if 64 isn't enough on a particular rule.

const HUNT_POP_SIZE         = 8;
const HUNT_GENS_DEFAULT     = 20;
const REFINE_GENS_DEFAULT   = 64;
const HUNT_MUT_RATE         = 0.001;   // 4× this for fresh-Hunt's random half
const HUNT_INSERT           = 3;       // number of top winners pushed into
                                       // the library after the hunt

function refineGens() {
    const el = document.getElementById('stratum-refine-gens');
    const v = el ? parseInt(el.value, 10) : REFINE_GENS_DEFAULT;
    if (Number.isFinite(v) && v >= 5 && v <= 500) return v;
    return REFINE_GENS_DEFAULT;
}


function bootstrap() {
    state.library = [];
    for (let i = 0; i < LIB_SIZE; i++) {
        const seed = ((Math.random() * 0xFFFFFFFF) >>> 0) ^ (i * 2654435761);
        const e = makeLibraryEntry(seed, state.paletteMode);
        // Score immediately so we have a fitness ranking.
        const sc = score(e.genome, INNER_W, SCORE_STEPS, mulberry32(seed ^ 0x1234),
                          SCORE_BURNIN);
        e.fitness = sc.f;
        e.r       = sc.r;
        state.library.push(e);
    }
    // Initial elite = highest fitness.
    let best = 0, bestF = -1;
    for (let i = 0; i < LIB_SIZE; i++) {
        if (state.library[i].fitness > bestF) {
            bestF = state.library[i].fitness;
            best  = i;
        }
    }
    state.eliteIdx  = best;
    state.eliteBins = state.library[best].bins;

    // Meta-state: random initialisation in 0..63.
    for (let i = 0; i < state.metaA.length; i++) {
        state.metaA[i] = (Math.random() * LIB_SIZE) | 0;
    }
    state.metaTicks = 0;
    state.rounds = 0;
}


// ── Inner tick: step every library CA's grid one step ────────────

function tickInner() {
    if (!state.running) return;
    for (let i = 0; i < LIB_SIZE; i++) {
        const e = state.library[i];
        e.gridA = stepWithGenomeBins(e.gridA, INNER_W, INNER_H, e.bins);
    }
    paintAll();
}


// ── Meta tick: step the meta-CA using the elite's ruleset ────────

function tickMeta() {
    if (!state.running) return;
    const next = stepWithGenomeBins(state.metaA, META_COLS, META_ROWS, state.eliteBins);
    state.metaA = next;
    state.metaTicks++;
    document.getElementById('stratum-meta-ticks').textContent = state.metaTicks;
    paintAll();
}


// ── Tournament round: pick two library entries, score, replace loser ─

function tickTournament() {
    if (!state.running) return;
    // Don't trample on a hunt-in-progress; the hunt is going to
    // bulk-replace several library slots and we don't want a stray
    // tournament edit between gens.
    if (state.hunting) return;

    let i = (Math.random() * LIB_SIZE) | 0;
    let j = (Math.random() * LIB_SIZE) | 0;
    if (i === j) j = (j + 1) % LIB_SIZE;

    // Score both on the same fresh seed for a fair comparison.
    const sharedSeed = (Math.random() * 0xFFFFFFFF) >>> 0;
    const sc_i = score(state.library[i].genome, INNER_W, SCORE_STEPS,
                        mulberry32(sharedSeed), SCORE_BURNIN);
    const sc_j = score(state.library[j].genome, INNER_W, SCORE_STEPS,
                        mulberry32(sharedSeed), SCORE_BURNIN);
    state.library[i].fitness = sc_i.f; state.library[i].r = sc_i.r;
    state.library[j].fitness = sc_j.f; state.library[j].r = sc_j.r;

    // Tournament: higher fitness wins. Loser inherits a mutated copy
    // of the winner's genome and the winner's palette outright (so
    // dominant rules visibly share colour schemes).
    const winnerIdx = sc_i.f >= sc_j.f ? i : j;
    const loserIdx  = winnerIdx === i ? j : i;
    const W = state.library[winnerIdx];
    const L = state.library[loserIdx];

    const child = mutateGenome(W.genome, state.mutRate, mulberry32(sharedSeed ^ 0xD00D));
    L.genome   = child;
    L.bins     = buildBins(child);
    L.paletteRGBA = new Uint32Array(W.paletteRGBA);
    L.gridA    = freshGrid(INNER_W, INNER_H, LIB_K,
                            mulberry32((Math.random() * 0xFFFFFFFF) >>> 0));
    L.fitness  = W.fitness;     // upper bound; will be re-scored next time
    L.r        = W.r;

    // Update elite if we discovered a better one.
    if (state.library[winnerIdx].fitness > state.library[state.eliteIdx].fitness) {
        state.eliteIdx  = winnerIdx;
        state.eliteBins = state.library[winnerIdx].bins;
    } else if (loserIdx === state.eliteIdx) {
        // Edge case: elite was just overwritten — pick a new one.
        let best = 0, bestF = -Infinity;
        for (let k = 0; k < LIB_SIZE; k++) {
            if (state.library[k].fitness > bestF) {
                bestF = state.library[k].fitness; best = k;
            }
        }
        state.eliteIdx  = best;
        state.eliteBins = state.library[best].bins;
    }
    state.rounds++;
    updateStatus();
    paintAll();
}


// ── Hunt + Refine: compact GA on a single click ────────────────────
//
// Runs a small GA, then inserts the top HUNT_INSERT winners into the
// library by replacing the bottom-fitness slots. The auto-tournament
// loop pauses while hunting (state.hunting flag). Per-gen yields keep
// the UI thread alive — without them the page would freeze for ~4s.

async function runHunt(warmStart) {
    if (state.hunting) return;
    state.hunting = true;
    state.huntKind = warmStart ? 'refine' : 'hunt';
    const gens = warmStart ? refineGens() : HUNT_GENS_DEFAULT;
    const status = document.getElementById('stratum-hunt-status');
    const huntBtn = document.getElementById('stratum-hunt-btn');
    const refineBtn = document.getElementById('stratum-refine-btn');
    if (huntBtn)   huntBtn.disabled   = true;
    if (refineBtn) refineBtn.disabled = true;

    const t0 = performance.now();
    const elite = state.library[state.eliteIdx];

    // Build initial population. Each individual = {genome, paletteRGBA}.
    const pop = [];
    pop.push({
        genome:      elite.genome,                   // elite passes through
        paletteRGBA: new Uint32Array(elite.paletteRGBA),
    });
    if (warmStart) {
        // Refine: rest are mutations of the elite at HUNT_MUT_RATE.
        for (let k = 1; k < HUNT_POP_SIZE; k++) {
            const mutSeed = (Math.random() * 0xFFFFFFFF) >>> 0;
            pop.push({
                genome:      mutateGenome(elite.genome, HUNT_MUT_RATE, mulberry32(mutSeed)),
                paletteRGBA: new Uint32Array(elite.paletteRGBA),
            });
        }
    } else {
        // Hunt: half mutated (4× rate), half random with fresh palettes
        // in the current mode.
        const half = HUNT_POP_SIZE / 2;
        for (let k = 1; k < half; k++) {
            const mutSeed = (Math.random() * 0xFFFFFFFF) >>> 0;
            pop.push({
                genome:      mutateGenome(elite.genome, HUNT_MUT_RATE * 4, mulberry32(mutSeed)),
                paletteRGBA: new Uint32Array(elite.paletteRGBA),
            });
        }
        for (let k = half; k < HUNT_POP_SIZE; k++) {
            const seed = (Math.random() * 0xFFFFFFFF) >>> 0;
            pop.push({
                genome:      makeGenome(LIB_K, seed),
                paletteRGBA: makePaletteRGBA(LIB_K, state.paletteMode,
                                              mulberry32(seed ^ 0xA5A5A5A5)),
            });
        }
    }
    for (const ind of pop) { ind.fitness = 0; ind.r = 0; }

    // Run gens.
    let bestEver = null;
    for (let gen = 0; gen < gens; gen++) {
        const seed = (Math.random() * 0xFFFFFFFF) >>> 0;
        for (const ind of pop) {
            const sc = score(ind.genome, INNER_W, SCORE_STEPS,
                              mulberry32(seed), SCORE_BURNIN);
            ind.fitness = sc.f; ind.r = sc.r;
        }
        pop.sort((a, b) => b.fitness - a.fitness);

        if (!bestEver || pop[0].fitness > bestEver.fitness) {
            bestEver = {
                genome:  new Uint8Array(pop[0].genome.keys
                    ? pop[0].genome.keys : []),  // shouldn't happen
                ...pop[0],
            };
        }
        if (status) {
            status.textContent =
                `${state.huntKind} gen ${gen + 1}/${gens} ` +
                `best ${pop[0].fitness.toFixed(4)} (r=${pop[0].r.toFixed(3)})`;
        }

        // Reproduce: top half keeps elite, bottom half = crossover-mutate.
        const half = HUNT_POP_SIZE / 2;
        const next = [pop[0]];        // elite passes through
        while (next.length < HUNT_POP_SIZE) {
            const a = pop[(Math.random() * half) | 0];
            const b = pop[(Math.random() * half) | 0];
            const cxRng = mulberry32((Math.random() * 0xFFFFFFFF) >>> 0);
            const child = mutateGenome(
                crossover(a.genome, b.genome, cxRng),
                HUNT_MUT_RATE, cxRng,
            );
            // Palette inherit: 50/50 per slot from the two parents.
            const pal = new Uint32Array(LIB_K);
            for (let k = 0; k < LIB_K; k++) {
                pal[k] = (Math.random() < 0.5) ? a.paletteRGBA[k] : b.paletteRGBA[k];
            }
            next.push({ genome: child, paletteRGBA: pal, fitness: 0, r: 0 });
        }
        pop.length = 0; for (const x of next) pop.push(x);

        // Yield to UI thread so per-gen progress can paint.
        // eslint-disable-next-line no-await-in-loop
        await new Promise(r => setTimeout(r, 0));
    }

    // Insert the top HUNT_INSERT into the library, replacing the
    // bottom-fitness slots (so we keep diversity in the middle band
    // and don't immediately overwrite a recently-discovered winner).
    const ranked = state.library
        .map((e, i) => ({ e, i }))
        .sort((a, b) => a.e.fitness - b.e.fitness);
    const N_INS = Math.min(HUNT_INSERT, HUNT_POP_SIZE);
    for (let k = 0; k < N_INS; k++) {
        const slot = ranked[k].i;
        const winner = pop[k];
        state.library[slot].genome   = winner.genome;
        state.library[slot].bins     = buildBins(winner.genome);
        state.library[slot].paletteRGBA = winner.paletteRGBA;
        state.library[slot].fitness  = winner.fitness;
        state.library[slot].r        = winner.r;
        state.library[slot].gridA    = freshGrid(
            INNER_W, INNER_H, LIB_K,
            mulberry32((Math.random() * 0xFFFFFFFF) >>> 0));
    }

    // Refresh elite — likely changed.
    let bestIdx = 0, bestF = -Infinity;
    for (let k = 0; k < LIB_SIZE; k++) {
        if (state.library[k].fitness > bestF) {
            bestF = state.library[k].fitness;
            bestIdx = k;
        }
    }
    state.eliteIdx  = bestIdx;
    state.eliteBins = state.library[bestIdx].bins;

    state.hunting = false;
    if (huntBtn)   huntBtn.disabled   = false;
    if (refineBtn) refineBtn.disabled = false;
    const dt = ((performance.now() - t0) / 1000).toFixed(1);
    if (status) {
        status.textContent =
            `${state.huntKind} done in ${dt}s · ` +
            `top score ${pop[0].fitness.toFixed(4)} (r=${pop[0].r.toFixed(3)}) · ` +
            `inserted ${N_INS} winners`;
    }
    paintAll();
    updateStatus();
}


// ── Render ─────────────────────────────────────────────────────────
//
// Two canvases — library strip and meta-CA — both painted with a
// single canvas-sized ImageData buffer + Uint32Array alias. Same trick
// as cellular.mjs.

function packRGBA(r, g, b) {
    return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
}
const BG_RGBA = packRGBA(0x0d, 0x11, 0x17);

let libImage = null,  libBuf32 = null;
let metaImage = null, metaBuf32 = null;

function ensureBuffers() {
    const libCv = document.getElementById('stratum-library');
    const metaCv = document.getElementById('stratum-meta');
    if (!libCv || !metaCv) return false;
    if (!libImage || libImage.width !== libCv.width) {
        const ctx = libCv.getContext('2d');
        libImage = ctx.createImageData(libCv.width, libCv.height);
        libBuf32 = new Uint32Array(libImage.data.buffer);
    }
    if (!metaImage || metaImage.width !== metaCv.width) {
        const ctx = metaCv.getContext('2d');
        metaImage = ctx.createImageData(metaCv.width, metaCv.height);
        metaBuf32 = new Uint32Array(metaImage.data.buffer);
    }
    return true;
}

// Shared workhorse: blit one library entry's grid into `buf` at
// (tileX, tileY) using its pre-packed RGBA palette.
function blitGridIntoBuffer(buf, bufW, entry, tileX, tileY, tilePx, cellPx) {
    const K = LIB_K;
    const pal = entry.paletteRGBA;        // already Uint32Array of RGBA
    const grid = entry.gridA;
    for (let cy = 0; cy < INNER_H; cy++) {
        const py0 = tileY + ((cy * cellPx) | 0);
        const py1 = tileY + (((cy + 1) * cellPx) | 0);
        const cellXOff = (cy & 1) ? cellPx * 0.5 : 0;
        for (let cx = 0; cx < INNER_W; cx++) {
            const v = grid[cy * INNER_W + cx];
            const rgba = pal[v % K];
            const px0 = tileX + ((cx * cellPx + cellXOff) | 0);
            const px1 = tileX + (((cx + 1) * cellPx + cellXOff) | 0);
            for (let py = py0; py < py1; py++) {
                const rowStart = py * bufW;
                for (let px = px0; px < px1; px++) {
                    buf[rowStart + px] = rgba;
                }
            }
        }
    }
}

function paintLibrary() {
    const cv = document.getElementById('stratum-library');
    if (!cv) return;
    const ctx = cv.getContext('2d');
    libBuf32.fill(BG_RGBA);

    for (let i = 0; i < LIB_SIZE; i++) {
        const r = (i / LIB_COLS) | 0;
        const c = i - r * LIB_COLS;
        const xOff = (r & 1) ? LIB_TILE_PX / 2 : 0;
        const x = (c * (LIB_TILE_PX + LIB_TILE_GAP) + xOff) | 0;
        const y = (r * (LIB_TILE_PX + LIB_TILE_GAP)) | 0;
        blitGridIntoBuffer(libBuf32, cv.width, state.library[i],
                            x, y, LIB_TILE_PX, LIB_CELL_PX);
    }
    ctx.putImageData(libImage, 0, 0);

    // Borders: gold for elite, dim for the rest. Cheap (64 strokes).
    for (let i = 0; i < LIB_SIZE; i++) {
        const r = (i / LIB_COLS) | 0;
        const c = i - r * LIB_COLS;
        const xOff = (r & 1) ? LIB_TILE_PX / 2 : 0;
        const x = c * (LIB_TILE_PX + LIB_TILE_GAP) + xOff;
        const y = r * (LIB_TILE_PX + LIB_TILE_GAP);
        if (i === state.eliteIdx) {
            ctx.strokeStyle = '#d4a72c';
            ctx.lineWidth   = 2;
        } else {
            ctx.strokeStyle = '#21262d';
            ctx.lineWidth   = 1;
        }
        ctx.strokeRect(x + 0.5, y + 0.5, LIB_TILE_PX - 1, LIB_TILE_PX - 1);
    }
}

function paintMeta() {
    const cv = document.getElementById('stratum-meta');
    if (!cv) return;
    const ctx = cv.getContext('2d');
    metaBuf32.fill(BG_RGBA);

    for (let i = 0; i < META_ROWS * META_COLS; i++) {
        const r = (i / META_COLS) | 0;
        const c = i - r * META_COLS;
        const xOff = (r & 1) ? META_TILE_PX / 2 : 0;
        const x = (c * (META_TILE_PX + META_TILE_GAP) + xOff) | 0;
        const y = (r * (META_TILE_PX + META_TILE_GAP)) | 0;
        const v = state.metaA[i] % LIB_SIZE;
        blitGridIntoBuffer(metaBuf32, cv.width, state.library[v],
                            x, y, META_TILE_PX, META_CELL_PX);
    }
    ctx.putImageData(metaImage, 0, 0);

    // Border highlight if a meta-cell shows the elite library entry.
    for (let i = 0; i < META_ROWS * META_COLS; i++) {
        const v = state.metaA[i] % LIB_SIZE;
        if (v !== state.eliteIdx) continue;
        const r = (i / META_COLS) | 0;
        const c = i - r * META_COLS;
        const xOff = (r & 1) ? META_TILE_PX / 2 : 0;
        const x = c * (META_TILE_PX + META_TILE_GAP) + xOff;
        const y = r * (META_TILE_PX + META_TILE_GAP);
        ctx.strokeStyle = 'rgba(212, 167, 44, 0.7)';
        ctx.lineWidth   = 1;
        ctx.strokeRect(x + 0.5, y + 0.5, META_TILE_PX - 1, META_TILE_PX - 1);
    }
}

function paintAll() {
    if (!ensureBuffers()) return;
    paintLibrary();
    paintMeta();
}


// ── Status line ────────────────────────────────────────────────────

function updateStatus() {
    const e = state.library[state.eliteIdx];
    document.getElementById('stratum-elite-idx').textContent  = state.eliteIdx;
    document.getElementById('stratum-elite-fit').textContent  = e.fitness.toFixed(4);
    document.getElementById('stratum-elite-r').textContent    = e.r.toFixed(3);
    document.getElementById('stratum-rounds').textContent     = state.rounds;
    document.getElementById('stratum-meta-ticks').textContent = state.metaTicks;
}


// ── Click-to-download (genome → hexnn-genome-v1 JSON) ──────────────
//
// Hit-testing on the hex tile grids: the meta canvas inverse-maps a
// click to (r, c) accounting for the odd-row offset. Library is the
// same shape with smaller tiles. The JSON emitted is byte-shape-
// identical to the /hexnn/ bench's "Download JSON" button so the
// same file round-trips into that page.

function fnv1a32Hex(keys, outs) {
    let h = 0x811c9dc5 >>> 0;
    for (let i = 0; i < keys.length; i++) {
        h = ((h ^ keys[i]) >>> 0);
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    for (let i = 0; i < outs.length; i++) {
        h = ((h ^ outs[i]) >>> 0);
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h.toString(16).padStart(8, '0');
}

// (paletteRGBAToCssHex now lives in hexnn_engine.mjs and is imported
// at the top of this module.)

async function downloadLibraryEntryAsJSON(idx, source, compress) {
    const e = state.library[idx];
    // The genome is stored as {K, keys: Uint8Array(N*7), outs: Uint8Array(N)}.
    const g = e.genome;
    const keys = [];
    for (let i = 0; i < g.outs.length; i++) {
        const off = i * 7;
        keys.push([
            g.keys[off], g.keys[off+1], g.keys[off+2], g.keys[off+3],
            g.keys[off+4], g.keys[off+5], g.keys[off+6],
        ]);
    }
    const outputs = Array.from(g.outs);
    const fp = fnv1a32Hex(g.keys, g.outs);
    const payload = {
        format:         'hexnn-genome-v1',
        K:              g.K,
        n_entries:      g.outs.length,
        palette:        paletteRGBAToCssHex(e.paletteRGBA),
        palette_name:   `stratum-${state.paletteMode}-${source}-${idx}`,
        fingerprint:    fp,
        exported_at:    new Date().toISOString(),
        source:         source,        // 'library' or 'meta:rIcJ'
        library_index:  idx,
        fitness:        e.fitness,
        r:              e.r,
        keys:           keys,
        outputs:        outputs,
    };
    const json = JSON.stringify(payload);

    let blob, ext, mime;
    if (compress && typeof CompressionStream !== 'undefined') {
        // Stream-compress through gzip. ~10× smaller than raw JSON for
        // a hexnn-genome-v1 payload (keys are mostly small ints, lots
        // of repetition). Falls back to raw JSON if the browser is
        // really old.
        const cs = new CompressionStream('gzip');
        const writer = cs.writable.getWriter();
        const enc = new TextEncoder();
        writer.write(enc.encode(json));
        writer.close();
        const compressed = await new Response(cs.readable).arrayBuffer();
        blob = new Blob([compressed], {type: 'application/gzip'});
        ext  = 'json.gz';
        mime = 'application/gzip';
    } else {
        blob = new Blob([json], {type: 'application/json'});
        ext  = 'json';
        mime = 'application/json';
    }
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `hexnn-K${g.K}-${fp}.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Inverse of the layout math in paintLibrary / paintMeta. Returns
// the {row, col} of the tile under (mx, my), or null if the click
// landed in a gap or outside the grid.
function tileFromMouse(mx, my, cols, rows, tilePx, tileGap) {
    // Try odd row first if y suggests it; we just brute-force check
    // both candidate rows (offset / non-offset) since they overlap on
    // x. Whichever lands the click inside its tile box wins.
    const stride = tilePx + tileGap;
    const r = Math.floor(my / stride);
    if (r < 0 || r >= rows) return null;
    if ((my - r * stride) >= tilePx) return null;       // in vertical gap
    const xOff = (r & 1) ? tilePx / 2 : 0;
    const localX = mx - xOff;
    const c = Math.floor(localX / stride);
    if (c < 0 || c >= cols) return null;
    if ((localX - c * stride) >= tilePx) return null;   // in horizontal gap
    return { row: r, col: c };
}

function shouldCompress() {
    const cb = document.getElementById('stratum-gzip-cb');
    return cb ? cb.checked : true;        // default on
}

function onLibraryClick(ev) {
    const cv = ev.currentTarget;
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const hit = tileFromMouse(mx, my, LIB_COLS, LIB_ROWS, LIB_TILE_PX, LIB_TILE_GAP);
    if (!hit) return;
    const idx = hit.row * LIB_COLS + hit.col;
    if (idx < 0 || idx >= LIB_SIZE) return;
    downloadLibraryEntryAsJSON(idx, 'library', shouldCompress());
}

function onMetaClick(ev) {
    const cv = ev.currentTarget;
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const hit = tileFromMouse(mx, my, META_COLS, META_ROWS, META_TILE_PX, META_TILE_GAP);
    if (!hit) return;
    const cellIdx = hit.row * META_COLS + hit.col;
    const libIdx  = state.metaA[cellIdx] % LIB_SIZE;
    downloadLibraryEntryAsJSON(libIdx, `meta:r${hit.row}c${hit.col}`, shouldCompress());
}


// ── Image → palettes ───────────────────────────────────────────────
//
// Sample an image (or several) into the 64 library entries' palettes.
// Each entry gets K=64 colours from a position-mapped 8×8 region of
// its chosen source image, quantized to nearest ANSI-256 — so the
// global palette stays bounded at 256 distinct colours regardless of
// how rich the source images are. Single-image mode lays out all 64
// entries against the same picture (the library mosaic mirrors it).
// Multi-image mode picks a random source image per entry, so the
// library becomes a collage of references.

const ANSI_PALETTE_RGB = (() => {
    const out = new Array(256);
    for (let i = 0; i < 256; i++) out[i] = ansi256_rgb(i);
    return out;
})();

function nearestAnsi256(r, g, b) {
    let best = 0, bestD = Infinity;
    for (let i = 0; i < 256; i++) {
        const [ar, ag, ab] = ANSI_PALETTE_RGB[i];
        const dr = ar - r, dg = ag - g, db = ab - b;
        const d = dr*dr + dg*dg + db*db;
        if (d < bestD) { bestD = d; best = i; if (d === 0) break; }
    }
    return best;
}

function packRGBA_(r, g, b) {
    return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
}

function loadImageFile(file) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload  = () => { URL.revokeObjectURL(url); resolve(img); };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('decode failed')); };
        img.src = url;
    });
}

function rasterizeToPalettePlane(img, PX, PY) {
    const w = img.naturalWidth, h = img.naturalHeight;
    const side = Math.min(w, h);
    const cx = ((w - side) / 2) | 0, cy = ((h - side) / 2) | 0;
    const off = document.createElement('canvas');
    off.width = PX; off.height = PY;
    const octx = off.getContext('2d');
    octx.imageSmoothingEnabled = true;
    octx.drawImage(img, cx, cy, side, side, 0, 0, PX, PY);
    return octx.getImageData(0, 0, PX, PY).data;
}

// Serialize a Uint8Array of small ints into a JSON array body without
// the per-element overhead of Array.from + JSON.stringify (which is
// painfully slow at the 16,384-entry scale of HexNN genomes).
function u8ToJsonInts(u8) { return '[' + u8.join(',') + ']'; }

function buildStratumPopulationJson(sources) {
    const parts = [];
    parts.push('{"format":"stratum-population-v1"');
    parts.push(',"sublab":"stratum"');
    parts.push(',"K":' + LIB_K);
    parts.push(',"lib_size":' + LIB_SIZE);
    parts.push(',"lib_rows":' + LIB_ROWS + ',"lib_cols":' + LIB_COLS);
    parts.push(',"meta_rows":' + META_ROWS + ',"meta_cols":' + META_COLS);
    parts.push(',"inner_w":' + INNER_W + ',"inner_h":' + INNER_H);
    parts.push(',"n_entries":' + N_ENTRIES);
    parts.push(',"elite_idx":' + state.eliteIdx);
    parts.push(',"exported_at":' + JSON.stringify(new Date().toISOString()));
    parts.push(',"sources":' + JSON.stringify(sources || []));
    parts.push(',"library":[');
    for (let i = 0; i < state.library.length; i++) {
        const e = state.library[i];
        if (i > 0) parts.push(',');
        parts.push('{"keys":'    + u8ToJsonInts(e.genome.keys));
        parts.push(',"outputs":' + u8ToJsonInts(e.genome.outs));
        parts.push(',"palette":' + JSON.stringify(paletteRGBAToCssHex(e.paletteRGBA)));
        parts.push(',"grid":'    + u8ToJsonInts(e.gridA));
        parts.push(',"fitness":' + (Number.isFinite(e.fitness) ? e.fitness : 0).toFixed(6));
        parts.push(',"r":'       + (Number.isFinite(e.r)       ? e.r       : 0).toFixed(6));
        parts.push('}');
    }
    parts.push('],"meta_grid":' + u8ToJsonInts(state.metaA));
    parts.push('}');
    return parts.join('');
}

function cssHexPaletteToRGBA(palHex) {
    const out = new Uint32Array(palHex.length);
    for (let i = 0; i < palHex.length; i++) {
        const h = String(palHex[i] || '#000000');
        const r = parseInt(h.slice(1, 3), 16) || 0;
        const g = parseInt(h.slice(3, 5), 16) || 0;
        const b = parseInt(h.slice(5, 7), 16) || 0;
        out[i] = ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
    }
    return out;
}

async function loadStratumPopulationFromFile(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    let json;
    const looksGz = buf.length >= 2 && buf[0] === 0x1F && buf[1] === 0x8B;
    if (looksGz) {
        if (typeof DecompressionStream === 'undefined') {
            throw new Error('this browser cannot decompress gzip');
        }
        const ds = new DecompressionStream('gzip');
        const w = ds.writable.getWriter();
        w.write(buf);
        w.close();
        const out = await new Response(ds.readable).arrayBuffer();
        json = new TextDecoder().decode(out);
    } else {
        json = new TextDecoder().decode(buf);
    }
    const data = JSON.parse(json);
    if (data.format !== 'stratum-population-v1') {
        throw new Error('not a stratum-population-v1 file');
    }
    if (data.K !== LIB_K) {
        throw new Error(`K mismatch: file has K=${data.K}, build expects K=${LIB_K}`);
    }
    if (data.lib_size !== LIB_SIZE) {
        throw new Error(`lib_size mismatch: file=${data.lib_size}, build=${LIB_SIZE}`);
    }
    if (!Array.isArray(data.library) || data.library.length !== LIB_SIZE) {
        throw new Error('library array length mismatch');
    }
    state.library = [];
    for (let i = 0; i < data.library.length; i++) {
        const lib = data.library[i];
        const genome = {
            K: data.K,
            keys: new Uint8Array(lib.keys),
            outs: new Uint8Array(lib.outputs),
        };
        if (genome.keys.length !== N_ENTRIES * 7 || genome.outs.length !== N_ENTRIES) {
            throw new Error(`entry ${i}: N_ENTRIES mismatch`);
        }
        const bins = buildBins(genome);
        const palRGBA = cssHexPaletteToRGBA(lib.palette);
        const gridA   = new Uint8Array(lib.grid);
        if (gridA.length !== INNER_W * INNER_H) {
            throw new Error(`entry ${i}: grid size mismatch`);
        }
        state.library.push({
            genome, paletteRGBA: palRGBA, gridA, bins,
            fitness: Number(lib.fitness) || 0,
            r:       Number(lib.r)       || 0,
        });
    }
    if (Array.isArray(data.meta_grid) && data.meta_grid.length === META_ROWS * META_COLS) {
        state.metaA = new Uint8Array(data.meta_grid);
        state.metaB = new Uint8Array(data.meta_grid.length);
    }
    state.eliteIdx = (data.elite_idx >= 0 && data.elite_idx < LIB_SIZE) ? data.elite_idx : 0;
    state.eliteBins = state.library[state.eliteIdx].bins;
    state.metaTicks = 0;
    state.rounds    = 0;
}

async function downloadGzipped(filename, jsonString) {
    let blob;
    if (typeof CompressionStream !== 'undefined') {
        const cs = new CompressionStream('gzip');
        const w = cs.writable.getWriter();
        w.write(new TextEncoder().encode(jsonString));
        w.close();
        const buf = await new Response(cs.readable).arrayBuffer();
        blob = new Blob([buf], {type: 'application/gzip'});
    } else {
        blob = new Blob([jsonString], {type: 'application/json'});
        if (!filename.endsWith('.json')) filename = filename.replace(/\.gz$/, '');
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return blob.size;
}

function applyImagePalettesToLibrary(imgs) {
    if (!imgs || imgs.length === 0) return;
    // K=64 → 8×8 sample grid per entry. 8 cols × 8 rows of entries
    // → 64×64 sample plane per source image.
    const SK = 8;
    const PX = LIB_COLS * SK;
    const PY = LIB_ROWS * SK;
    const sources = imgs.map(img => rasterizeToPalettePlane(img, PX, PY));

    for (let er = 0; er < LIB_ROWS; er++) {
        for (let ec = 0; ec < LIB_COLS; ec++) {
            const entry = state.library[er * LIB_COLS + ec];
            if (!entry) continue;
            const src = sources.length === 1
                ? sources[0]
                : sources[(Math.random() * sources.length) | 0];
            const x0 = ec * SK, y0 = er * SK;
            for (let k = 0; k < LIB_K; k++) {
                const kx = k % SK, ky = (k / SK) | 0;
                const px = x0 + kx, py = y0 + ky;
                const idx = (py * PX + px) * 4;
                const ansi = nearestAnsi256(src[idx], src[idx+1], src[idx+2]);
                const [qr, qg, qb] = ANSI_PALETTE_RGB[ansi];
                entry.paletteRGBA[k] = packRGBA_(qr, qg, qb);
            }
        }
    }
}


// ── Wire-up ────────────────────────────────────────────────────────

function startTimers() {
    stopTimers();
    if (!state.running) return;
    state.innerHandle = setInterval(tickInner, state.innerTickMs);
    state.metaHandle  = setInterval(tickMeta,  state.metaTickMs);
    state.tournHandle = setInterval(tickTournament, state.tournMs);
}
function stopTimers() {
    if (state.innerHandle) { clearInterval(state.innerHandle); state.innerHandle = null; }
    if (state.metaHandle)  { clearInterval(state.metaHandle);  state.metaHandle  = null; }
    if (state.tournHandle) { clearInterval(state.tournHandle); state.tournHandle = null; }
}

function init() {
    // Pin canvases to JS-computed dimensions.
    const libCv  = document.getElementById('stratum-library');
    const metaCv = document.getElementById('stratum-meta');
    if (libCv)  { libCv.width  = LIB_CANVAS_W;  libCv.height  = LIB_CANVAS_H; }
    if (metaCv) { metaCv.width = META_CANVAS_W; metaCv.height = META_CANVAS_H; }

    bootstrap();
    paintAll();
    updateStatus();

    document.getElementById('pause-btn').onclick = () => {
        state.running = !state.running;
        document.getElementById('pause-btn').textContent =
            state.running ? 'Pause' : 'Run';
        if (state.running) startTimers(); else stopTimers();
    };
    document.getElementById('reset-lib-btn').onclick = () => {
        bootstrap();
        paintAll();
        updateStatus();
    };
    document.getElementById('reseed-meta-btn').onclick = () => {
        for (let i = 0; i < state.metaA.length; i++) {
            state.metaA[i] = (Math.random() * LIB_SIZE) | 0;
        }
        state.metaTicks = 0;
        updateStatus();
        paintAll();
    };

    document.getElementById('inner-tick').oninput = (e) => {
        state.innerTickMs = parseInt(e.target.value, 10);
        document.getElementById('inner-tick-out').textContent = state.innerTickMs + ' ms';
        if (state.running) startTimers();
    };
    document.getElementById('meta-tick').oninput = (e) => {
        state.metaTickMs = parseInt(e.target.value, 10);
        document.getElementById('meta-tick-out').textContent = state.metaTickMs + ' ms';
        if (state.running) startTimers();
    };
    document.getElementById('tourn-tick').oninput = (e) => {
        state.tournMs = parseInt(e.target.value, 10);
        document.getElementById('tourn-tick-out').textContent = state.tournMs + ' ms';
        if (state.running) startTimers();
    };
    document.getElementById('mut-rate').oninput = (e) => {
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v) && v >= 0) state.mutRate = v;
    };

    // Hunt + Refine buttons run a compact GA on the current elite.
    const huntBtn = document.getElementById('stratum-hunt-btn');
    const refineBtn = document.getElementById('stratum-refine-btn');
    if (huntBtn)   huntBtn.onclick   = () => runHunt(false);
    if (refineBtn) refineBtn.onclick = () => runHunt(true);

    // Palette mode selector — flip every existing library entry's
    // palette to the new mode in place, then repaint. New library
    // entries (bootstrap, hunt-insert, tournament replacement) pick
    // up the same mode automatically via state.paletteMode.
    const paletteSel = document.getElementById('stratum-palette-mode');
    if (paletteSel) {
        paletteSel.value = state.paletteMode;
        paletteSel.onchange = (e) => {
            state.paletteMode = e.target.value;
            for (let i = 0; i < state.library.length; i++) {
                const seed = ((Math.random() * 0xFFFFFFFF) >>> 0) ^ (i * 2654435761);
                state.library[i].paletteRGBA = makePaletteRGBA(
                    LIB_K, state.paletteMode, mulberry32(seed));
            }
            paintAll();
        };
    }

    // Click-to-download genome JSON. Wire on both canvases — clicks
    // on the meta-CA download whichever library entry is currently
    // displayed in that meta-cell. (libCv / metaCv already declared
    // at the top of init() for the size pinning; reuse them here.)
    if (libCv) {
        libCv.style.cursor = 'pointer';
        libCv.addEventListener('click', onLibraryClick);
    }
    if (metaCv) {
        metaCv.style.cursor = 'pointer';
        metaCv.addEventListener('click', onMetaClick);
    }

    // Image(s) → palettes. One file = the library mosaic mirrors that
    // image's spatial colour layout. Multiple files = each library
    // entry randomly picks a source image, so the library becomes a
    // collage of multiple references. All colours quantized to
    // nearest-ANSI-256 so the global palette ceiling stays bounded.
    // Auto-export: the image-derived population is effectively a
    // compressed encoding of the image, so we save it to disk
    // immediately after applying — restorable via "📂 Load population".
    const imgInput = document.getElementById('stratum-image-input');
    if (imgInput) {
        imgInput.addEventListener('change', async (e) => {
            const files = [...(e.target.files || [])]
                .filter(f => f.type && f.type.startsWith('image/'));
            if (files.length === 0) return;
            const status = document.getElementById('stratum-hunt-status');
            if (status) {
                status.style.color = '#8b949e';
                status.textContent = `loading ${files.length} image${files.length > 1 ? 's' : ''}…`;
            }
            try {
                const imgs = await Promise.all(files.map(loadImageFile));
                applyImagePalettesToLibrary(imgs);
                paintAll();
                const sources = files.map(f => ({ name: f.name, size: f.size }));
                if (status) {
                    status.style.color = '#3fb950';
                    status.textContent = files.length === 1
                        ? 'palettes loaded from 1 image · saving population…'
                        : `palettes loaded — ${files.length} sources · saving population…`;
                }
                // Auto-export the resulting population.
                const json = buildStratumPopulationJson(sources);
                const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const sz = await downloadGzipped(`stratum-population-K${LIB_K}-${stamp}.json.gz`, json);
                if (status) {
                    const kb = (sz / 1024).toFixed(1);
                    status.textContent = files.length === 1
                        ? `palettes loaded · population saved (${kb} KB)`
                        : `palettes loaded — ${files.length} sources · population saved (${kb} KB)`;
                }
            } catch (err) {
                if (status) {
                    status.style.color = '#cf222e';
                    status.textContent = 'image load failed';
                }
                console.error(err);
            }
            imgInput.value = '';
        });
    }

    // Manual population save — same gzipped JSON format as the auto-export
    // after image-import; useful for snapshotting any state regardless of
    // how it was reached.
    const saveBtn = document.getElementById('stratum-save-population-btn');
    if (saveBtn) {
        saveBtn.onclick = async () => {
            const status = document.getElementById('stratum-hunt-status');
            if (status) {
                status.style.color = '#8b949e';
                status.textContent = 'saving population…';
            }
            try {
                const json = buildStratumPopulationJson([]);
                const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const sz = await downloadGzipped(`stratum-population-K${LIB_K}-${stamp}.json.gz`, json);
                if (status) {
                    status.style.color = '#3fb950';
                    status.textContent = `population saved (${(sz / 1024).toFixed(1)} KB)`;
                }
            } catch (err) {
                if (status) {
                    status.style.color = '#cf222e';
                    status.textContent = 'save failed';
                }
                console.error(err);
            }
        };
    }

    // Manual population load — read a stratum-population-v1[.gz] file and
    // replace the in-memory library + meta-CA grid.
    const loadInput = document.getElementById('stratum-load-population-input');
    if (loadInput) {
        loadInput.addEventListener('change', async (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file) return;
            const status = document.getElementById('stratum-hunt-status');
            if (status) {
                status.style.color = '#8b949e';
                status.textContent = `loading ${file.name}…`;
            }
            try {
                await loadStratumPopulationFromFile(file);
                paintAll();
                updateStatus();
                if (status) {
                    status.style.color = '#3fb950';
                    status.textContent = `population restored from ${file.name}`;
                }
            } catch (err) {
                if (status) {
                    status.style.color = '#cf222e';
                    status.textContent = 'load failed: ' + (err.message || err);
                }
                console.error(err);
            }
            loadInput.value = '';
        });
    }

    startTimers();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

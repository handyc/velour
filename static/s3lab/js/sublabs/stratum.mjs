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
    N_LOG2, N_ENTRIES, ansi256_rgb, mulberry32,
    makeGenome, buildBins, lookup, stepWithGenomeBins,
    score, mutateGenome, crossover, freshGrid, inventPalette,
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

function makeLibraryEntry(seed) {
    const genome  = makeGenome(LIB_K, seed);
    const palette = inventPalette(LIB_K, mulberry32(seed ^ 0xA5A5A5A5));
    const gridA   = freshGrid(INNER_W, INNER_H, LIB_K, mulberry32(seed ^ 0xCAFE_BABE));
    const bins    = buildBins(genome);
    return { genome, palette, gridA, bins, fitness: 0, r: 0 };
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
};


// ── Hunt parameters ────────────────────────────────────────────────
//
// A single Hunt or Refine click runs a compact GA: pop=8, gens=20.
// The whole thing finishes in ~3-5 s with per-gen yields, so the UI
// stays responsive (tile rendering keeps painting in between gens).
// Smaller and faster than /hexnn/'s default 16×60 because we want
// these buttons to feel like a quick experiment, not a long wait.

const HUNT_POP_SIZE  = 8;
const HUNT_GENS      = 20;
const HUNT_MUT_RATE  = 0.001;     // 4× this for fresh-Hunt's random half
const HUNT_INSERT    = 3;         // number of top winners pushed into
                                  // the library after the hunt


function bootstrap() {
    state.library = [];
    for (let i = 0; i < LIB_SIZE; i++) {
        const seed = ((Math.random() * 0xFFFFFFFF) >>> 0) ^ (i * 2654435761);
        const e = makeLibraryEntry(seed);
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
    L.palette  = new Uint8Array(W.palette);
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
    const status = document.getElementById('stratum-hunt-status');
    const huntBtn = document.getElementById('stratum-hunt-btn');
    const refineBtn = document.getElementById('stratum-refine-btn');
    if (huntBtn)   huntBtn.disabled   = true;
    if (refineBtn) refineBtn.disabled = true;

    const t0 = performance.now();
    const elite = state.library[state.eliteIdx];

    // Build initial population. Each individual = {genome, palette}.
    const pop = [];
    pop.push({
        genome:  elite.genome,                   // elite passes through unchanged
        palette: new Uint8Array(elite.palette),
    });
    if (warmStart) {
        // Refine: rest are mutations of the elite at HUNT_MUT_RATE.
        for (let k = 1; k < HUNT_POP_SIZE; k++) {
            const mutSeed = (Math.random() * 0xFFFFFFFF) >>> 0;
            pop.push({
                genome:  mutateGenome(elite.genome, HUNT_MUT_RATE, mulberry32(mutSeed)),
                palette: new Uint8Array(elite.palette),
            });
        }
    } else {
        // Hunt: half mutated (4× rate), half random with random palettes.
        const half = HUNT_POP_SIZE / 2;
        for (let k = 1; k < half; k++) {
            const mutSeed = (Math.random() * 0xFFFFFFFF) >>> 0;
            pop.push({
                genome:  mutateGenome(elite.genome, HUNT_MUT_RATE * 4, mulberry32(mutSeed)),
                palette: new Uint8Array(elite.palette),
            });
        }
        for (let k = half; k < HUNT_POP_SIZE; k++) {
            const seed = (Math.random() * 0xFFFFFFFF) >>> 0;
            pop.push({
                genome:  makeGenome(LIB_K, seed),
                palette: inventPalette(LIB_K, mulberry32(seed ^ 0xA5A5A5A5)),
            });
        }
    }
    for (const ind of pop) { ind.fitness = 0; ind.r = 0; }

    // Run gens.
    let bestEver = null;
    for (let gen = 0; gen < HUNT_GENS; gen++) {
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
                `${state.huntKind} gen ${gen + 1}/${HUNT_GENS} ` +
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
            const pal = new Uint8Array(LIB_K);
            for (let k = 0; k < LIB_K; k++) {
                pal[k] = (Math.random() < 0.5) ? a.palette[k] : b.palette[k];
            }
            next.push({ genome: child, palette: pal, fitness: 0, r: 0 });
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
        state.library[slot].palette  = winner.palette;
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
// (tileX, tileY) using palette[0..K-1] → packed RGBA.
function blitGridIntoBuffer(buf, bufW, entry, tileX, tileY, tilePx, cellPx) {
    const K = LIB_K;
    // Pack the entire palette to RGBA32 once per blit.
    const pal = new Uint32Array(K);
    for (let p = 0; p < K; p++) {
        const rgb = ansi256_rgb(entry.palette[p]);
        pal[p] = packRGBA(rgb[0], rgb[1], rgb[2]);
    }
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

function paletteToCssHex(pal) {
    const out = new Array(pal.length);
    for (let i = 0; i < pal.length; i++) {
        const [r, g, b] = ansi256_rgb(pal[i]);
        const to8 = v => v.toString(16).padStart(2, '0');
        out[i] = '#' + to8(r) + to8(g) + to8(b);
    }
    return out;
}

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
        palette:        paletteToCssHex(e.palette),
        palette_name:   `stratum-${source}-${idx}`,
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

    startTimers();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

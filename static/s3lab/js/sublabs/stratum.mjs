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
};


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

    startTimers();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

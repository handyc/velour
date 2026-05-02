// strateta.mjs — sublab: K=256 image-CA library.
//
// Sister of stratum at K=256 with a 16×16 library (256 entries instead
// of 64). Image upload fills the 256 palettes from a 256×256-pixel
// mosaic of the source — each entry gets a 16×16 region, 256 colours
// per palette, sampled directly from the corresponding spot of the
// picture. The library reads as a high-fidelity preview of the image.
//
// EVOLUTION: tournament-driven GA, same as stratum, but with two
// fitness modes the user toggles between:
//
//   'edge-of-chaos'   — same K=4-quantized changeRate parabola as
//                       stratum/classic. Drives toward 110-like
//                       dynamics regardless of what the palette
//                       happens to be.
//
//   'pixel-faithful'  — score = how closely the entry's CA output
//                       (after a few steps) matches its corresponding
//                       region of the source image, measured as
//                       1 - mean RGB squared distance. Refines toward
//                       a CA whose attractor *is* the image.
//
// SOURCE RAIL: source image thumbnails are rendered below the library
// canvas so the user can compare at a glance.
//
// Engine: identical hexnn_engine.mjs, K dialled to 256. No meta-CA
// layer (kept simple — the library IS the visual product here).

import {
    N_LOG2, N_ENTRIES, mulberry32,
    makeGenome, buildBins, lookup, stepWithGenomeBins,
    score, scoreKAware, mutateGenome, crossover, freshGrid,
    PALETTE_MODES, makePaletteRGBA, paletteRGBAToCssHex,
    ansi256_rgb,
} from '../hexnn_engine.mjs';


// ── Layout ─────────────────────────────────────────────────────────

const LIB_K       = 256;         // K of every library entry's CA
const LIB_SIZE    = 256;         // 16×16 = 256 entries
const LIB_ROWS    = 16;
const LIB_COLS    = 16;

const INNER_W     = 16;          // each library CA's inner grid (hex)
const INNER_H     = 16;

// Tile is non-square: width = LIB_TILE_W (drives inner cell size via
// LIB_CELL_PX = TILE_W / (INNER_W + 0.5) for the pointy-top stagger);
// height = INNER_H rows × cellPx × 0.866 (the hex y-stride). Gap = 0
// so neighbouring CAs touch — outer rows alternate +TILE_W/2 on x to
// tessellate at the population scale.
const LIB_TILE_W   = 24;
const LIB_TILE_GAP = 0;
const LIB_CELL_PX  = LIB_TILE_W / (INNER_W + 0.5);
const LIB_TILE_H   = Math.max(1, Math.round(INNER_H * LIB_CELL_PX * 0.866));

const LIB_CANVAS_W = LIB_COLS * LIB_TILE_W + (LIB_TILE_W / 2 | 0);
const LIB_CANVAS_H = LIB_ROWS * LIB_TILE_H;


// ── Algorithm tunables ─────────────────────────────────────────────

const DEFAULT_INNER_TICK_MS  = 400;     // step every library CA
const DEFAULT_TOURN_MS       = 6000;    // tournament round
const DEFAULT_MUT_RATE       = 0.0008;

const SCORE_STEPS  = 14;
const SCORE_BURNIN = 4;
// Pixel-faithful: how many steps to run before comparing to source.
const PIX_STEPS    = 10;


// ── State ──────────────────────────────────────────────────────────

function makeLibraryEntry(seed, paletteMode) {
    const genome      = makeGenome(LIB_K, seed);
    const paletteRGBA = makePaletteRGBA(LIB_K, paletteMode,
                                          mulberry32(seed ^ 0xA5A5A5A5));
    const gridA       = freshGrid(INNER_W, INNER_H, LIB_K,
                                   mulberry32(seed ^ 0xCAFEBABE));
    const bins        = buildBins(genome);
    return { genome, paletteRGBA, gridA, bins, fitness: 0, r: 0, pixFit: 0 };
}

const state = {
    library:    [],                   // length LIB_SIZE
    eliteIdx:   0,

    running:    true,

    innerTickMs: DEFAULT_INNER_TICK_MS,
    tournMs:     DEFAULT_TOURN_MS,
    mutRate:     DEFAULT_MUT_RATE,

    innerHandle: null,
    tournHandle: null,

    rounds: 0,
    hunting: false,
    huntKind: '',
    autoActive: false,

    paletteMode: 'random-ansi',
    refineMode:  'edge-of-chaos',     // 'edge-of-chaos' | 'pixel-faithful'

    // Source-image bookkeeping. Per library entry, a 16×16 RGB region
    // (768 bytes) used by pixel-faithful fitness. Index N is a tag
    // identifying which uploaded image each entry was sampled from.
    sourceRegions: null,              // Uint8ClampedArray | null
    sourceImages:  [],                // Array<{ name, dataURL, w, h }>
    sourceTagPerEntry: null,          // Uint8Array(LIB_SIZE) — image idx
};


// ── Hunt parameters ────────────────────────────────────────────────

const HUNT_POP_SIZE       = 8;
const HUNT_GENS_DEFAULT   = 16;
const REFINE_GENS_DEFAULT = 48;
const HUNT_MUT_RATE       = 0.0008;
const HUNT_INSERT         = 4;

function refineGens() {
    const el = document.getElementById('strateta-refine-gens');
    const v = el ? parseInt(el.value, 10) : REFINE_GENS_DEFAULT;
    if (Number.isFinite(v) && v >= 5 && v <= 500) return v;
    return REFINE_GENS_DEFAULT;
}


function bootstrap() {
    state.library = [];
    for (let i = 0; i < LIB_SIZE; i++) {
        const seed = ((Math.random() * 0xFFFFFFFF) >>> 0) ^ (i * 2654435761);
        const e = makeLibraryEntry(seed, state.paletteMode);
        scoreEntry(e, i);
        state.library.push(e);
    }
    state.eliteIdx = pickElite();
    state.rounds = 0;
}


// ── Fitness ────────────────────────────────────────────────────────
//
// Two scoring functions, picked by state.refineMode. Both write to
// entry.fitness so downstream selection (tournament, hunt) is uniform.

function edgeOfChaosScore(entry) {
    // K-aware change rate (scoreKAware) instead of K=4-quantized score
    // — at K=256 the legacy score collapses 256 outputs into 4 quartile
    // buckets, biasing the GA toward rules that use only a few values.
    // Strateta wants the full colour range exercised, so any cell
    // change counts. Same edge-of-chaos parabola on top.
    const seed = (Math.random() * 0xFFFFFFFF) >>> 0;
    const sc = scoreKAware(entry.genome, INNER_W, SCORE_STEPS,
                            mulberry32(seed | 1), SCORE_BURNIN);
    return { f: sc.f, r: sc.r };
}

// Run the entry's CA from a fresh random grid for PIX_STEPS, render
// the resulting grid via the entry's palette, then compare to the
// entry's source-image region. Score = 1 - (meanSquaredRGBDist /
// maxSquaredRGBDist), in [0, 1]. Higher = better match.
function pixelFaithfulScore(entry, entryIdx) {
    if (!state.sourceRegions) return { f: 0, r: 0 };
    const off = entryIdx * INNER_W * INNER_H * 3;
    const seed = (Math.random() * 0xFFFFFFFF) >>> 0;
    let grid = freshGrid(INNER_W, INNER_H, LIB_K, mulberry32(seed | 1));
    for (let s = 0; s < PIX_STEPS; s++) {
        grid = stepWithGenomeBins(grid, INNER_W, INNER_H, entry.bins);
    }
    const pal = entry.paletteRGBA;
    let totalSq = 0;
    const N = INNER_W * INNER_H;
    for (let i = 0; i < N; i++) {
        const v   = grid[i];
        const pv  = pal[v];
        const ar  =  pv         & 0xFF;
        const ag  = (pv >>>  8) & 0xFF;
        const ab  = (pv >>> 16) & 0xFF;
        const sr  = state.sourceRegions[off + i*3];
        const sg  = state.sourceRegions[off + i*3 + 1];
        const sb  = state.sourceRegions[off + i*3 + 2];
        const dr  = ar - sr, dg = ag - sg, db = ab - sb;
        totalSq  += dr*dr + dg*dg + db*db;
    }
    const meanSq = totalSq / N;
    // Maximum possible per-pixel squared distance: 3 × 255² = 195075.
    const f = 1 - (meanSq / (3 * 255 * 255));
    // Adopt the post-step grid so the GUI sees the matched state.
    entry.gridA = grid;
    return { f: Math.max(0, Math.min(1, f)), r: 0 };
}

function scoreEntry(entry, idx) {
    const sc = (state.refineMode === 'pixel-faithful' && state.sourceRegions)
        ? pixelFaithfulScore(entry, idx)
        : edgeOfChaosScore(entry);
    entry.fitness = sc.f;
    entry.r       = sc.r;
    return sc;
}

function pickElite() {
    let best = 0, bestF = -Infinity;
    for (let i = 0; i < state.library.length; i++) {
        if (state.library[i].fitness > bestF) {
            bestF = state.library[i].fitness;
            best  = i;
        }
    }
    return best;
}


// ── Inner tick: step every library CA's grid one step ─────────────

function tickInner() {
    if (!state.running) return;
    for (let i = 0; i < LIB_SIZE; i++) {
        const e = state.library[i];
        e.gridA = stepWithGenomeBins(e.gridA, INNER_W, INNER_H, e.bins);
    }
    paintLibrary();
}


// ── Tournament ─────────────────────────────────────────────────────

function tickTournament() {
    if (!state.running) return;
    if (state.hunting) return;

    let i = (Math.random() * LIB_SIZE) | 0;
    let j = (Math.random() * LIB_SIZE) | 0;
    if (i === j) j = (j + 1) % LIB_SIZE;

    const ei = state.library[i], ej = state.library[j];
    const sc_i = scoreEntry(ei, i);
    const sc_j = scoreEntry(ej, j);

    const winnerIdx = sc_i.f >= sc_j.f ? i : j;
    const loserIdx  = winnerIdx === i ? j : i;
    const W = state.library[winnerIdx];
    const L = state.library[loserIdx];

    const child = mutateGenome(W.genome, state.mutRate,
                                mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1));
    L.genome    = child;
    L.bins      = buildBins(child);
    // Pixel-faithful keeps the loser's image-derived palette so the
    // comparison stays meaningful; edge-of-chaos copies winner palette
    // (so dominant rules visibly share colour schemes, like stratum).
    if (state.refineMode !== 'pixel-faithful') {
        L.paletteRGBA = new Uint32Array(W.paletteRGBA);
    }
    L.gridA   = freshGrid(INNER_W, INNER_H, LIB_K,
                           mulberry32((Math.random() * 0xFFFFFFFF) >>> 0));
    scoreEntry(L, loserIdx);

    if (state.library[winnerIdx].fitness > state.library[state.eliteIdx].fitness) {
        state.eliteIdx = winnerIdx;
    }

    state.rounds++;
    updateStatus();
    paintLibrary();
}


// ── Hunt + Refine ──────────────────────────────────────────────────

async function runHunt(refineMode) {
    if (state.hunting) return;
    state.hunting = true;
    state.huntKind = refineMode ? 'refine' : 'hunt';
    setHuntStatus('starting…');

    const elite = state.library[state.eliteIdx];
    const popSize = HUNT_POP_SIZE;
    const gens = refineMode ? refineGens() : HUNT_GENS_DEFAULT;

    // Seed population: half mutated from elite (or all if refining),
    // half fresh-random (only on Hunt).
    const pop = [];
    for (let i = 0; i < popSize; i++) {
        let g;
        if (refineMode) {
            g = mutateGenome(elite.genome, HUNT_MUT_RATE,
                              mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1));
        } else if (i < (popSize >> 1)) {
            g = mutateGenome(elite.genome, HUNT_MUT_RATE * 4,
                              mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1));
        } else {
            g = makeGenome(LIB_K, ((Math.random() * 0xFFFFFFFF) >>> 0) | 1);
        }
        pop.push({ genome: g, bins: buildBins(g),
                   paletteRGBA: new Uint32Array(elite.paletteRGBA),
                   gridA: freshGrid(INNER_W, INNER_H, LIB_K,
                                    mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1)),
                   fitness: 0, r: 0 });
    }

    for (let gen = 0; gen < gens; gen++) {
        // Score every individual (against the elite's source region for
        // pixel-faithful — borrowed since hunt mints don't yet have
        // their own region; this evaluates "could this rule paint the
        // target the elite is anchored to").
        for (let p = 0; p < pop.length; p++) {
            const ent = pop[p];
            scoreEntry(ent, state.eliteIdx);
        }
        pop.sort((a, b) => b.fitness - a.fitness);
        // Refresh bottom half from top half via mutation + crossover.
        const half = pop.length >> 1;
        for (let p = half; p < pop.length; p++) {
            const a = pop[(Math.random() * half) | 0];
            const b = pop[(Math.random() * half) | 0];
            const ch = crossover(a.genome, b.genome,
                                  mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1));
            const mu = mutateGenome(ch, state.mutRate,
                                     mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1));
            pop[p].genome = mu;
            pop[p].bins   = buildBins(mu);
            pop[p].gridA  = freshGrid(INNER_W, INNER_H, LIB_K,
                                       mulberry32(((Math.random() * 0xFFFFFFFF) >>> 0) | 1));
        }
        if ((gen & 3) === 3) {
            setHuntStatus(`${state.huntKind}: gen ${gen + 1}/${gens} · top ${pop[0].fitness.toFixed(3)}`);
            await new Promise(r => setTimeout(r, 0));
        }
    }

    pop.sort((a, b) => b.fitness - a.fitness);

    // Insert top winners into the worst-fitness library slots.
    const orderByFit = state.library
        .map((e, i) => [e.fitness, i])
        .sort((a, b) => a[0] - b[0]);
    for (let k = 0; k < HUNT_INSERT && k < pop.length; k++) {
        const slot = orderByFit[k][1];
        const w = pop[k];
        state.library[slot].genome      = w.genome;
        state.library[slot].bins        = w.bins;
        state.library[slot].gridA       = w.gridA;
        state.library[slot].fitness     = w.fitness;
        state.library[slot].r           = w.r;
        // Pixel-faithful: keep the slot's own palette (image-derived)
        // so the freshly-inserted rule renders into the right region.
        if (state.refineMode !== 'pixel-faithful') {
            state.library[slot].paletteRGBA = new Uint32Array(w.paletteRGBA);
        }
    }
    state.eliteIdx = pickElite();
    state.hunting = false;
    state.huntKind = '';
    setHuntStatus(`${refineMode ? 'refine' : 'hunt'} done · top ${pop[0].fitness.toFixed(3)} placed in 4 slots`);
    paintLibrary();
    updateStatus();
}

function setHuntStatus(msg) {
    const el = document.getElementById('strateta-hunt-status');
    if (el) el.textContent = msg;
}


// ── Render ─────────────────────────────────────────────────────────

function packRGBA(r, g, b) {
    return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
}

let libBuf = null, libBufW = 0, libBufH = 0;
function ensureBuffers() {
    if (libBuf && libBufW === LIB_CANVAS_W && libBufH === LIB_CANVAS_H) return;
    libBufW = LIB_CANVAS_W;
    libBufH = LIB_CANVAS_H;
    libBuf  = new Uint32Array(libBufW * libBufH);
}

function blitGridIntoBuffer(buf, bufW, entry, tileX, tileY, tilePx, cellPx) {
    const grid = entry.gridA;
    const pal  = entry.paletteRGBA;
    const tileXEnd = tileX + tilePx;
    for (let y = 0; y < INNER_H; y++) {
        const rowShift = (y & 1) ? cellPx / 2 : 0;
        const py0 = (tileY + y * cellPx * 0.866) | 0;
        const py1 = (tileY + (y + 1) * cellPx * 0.866) | 0;
        const cellH = Math.max(1, py1 - py0);
        for (let x = 0; x < INNER_W; x++) {
            // Compute each cell's pixel span from the *neighbour's*
            // floor position (NOT from x*cellPx without rowShift) so the
            // half-cell stagger doesn't leave a 1-px gap at the tile's
            // right edge on unshifted rows. The last cell of each row
            // extends to tileXEnd so unshifted rows fill the full tile.
            const px0 = (tileX + x * cellPx + rowShift) | 0;
            const naturalPx1 = (tileX + (x + 1) * cellPx + rowShift) | 0;
            const px1 = (x === INNER_W - 1)
                ? Math.max(naturalPx1, tileXEnd)
                : naturalPx1;
            const cellW = Math.max(1, px1 - px0);
            const v = grid[y * INNER_W + x];
            const c = pal[v];
            for (let dy = 0; dy < cellH; dy++) {
                const py = py0 + dy;
                if (py < 0 || py >= libBufH) continue;
                for (let dx = 0; dx < cellW; dx++) {
                    const px = px0 + dx;
                    if (px < 0 || px >= bufW) continue;
                    buf[py * bufW + px] = c;
                }
            }
        }
    }
}

function paintLibrary() {
    ensureBuffers();
    libBuf.fill(0xFF0D1117);
    for (let r = 0; r < LIB_ROWS; r++) {
        for (let c = 0; c < LIB_COLS; c++) {
            const xShift = (r & 1) ? (LIB_TILE_W / 2 | 0) : 0;
            const tx = c * LIB_TILE_W + xShift;
            const ty = r * LIB_TILE_H;
            const idx = r * LIB_COLS + c;
            blitGridIntoBuffer(libBuf, LIB_CANVAS_W,
                                state.library[idx], tx, ty, LIB_TILE_W, LIB_CELL_PX);
            if (idx === state.eliteIdx) {
                drawBorder(libBuf, LIB_CANVAS_W, LIB_CANVAS_H,
                            tx, ty, LIB_TILE_W, LIB_TILE_H, 0xFFD4A72C);
            }
        }
    }
    const cv = document.getElementById('strateta-library');
    if (cv) {
        const ctx = cv.getContext('2d');
        const im = new ImageData(new Uint8ClampedArray(libBuf.buffer), LIB_CANVAS_W, LIB_CANVAS_H);
        ctx.putImageData(im, 0, 0);
    }
}

function drawBorder(buf, bufW, bufH, x, y, w, h, c) {
    for (let i = 0; i < w; i++) {
        if (y >= 0 && y < bufH) buf[y * bufW + (x + i)] = c;
        if (y + h - 1 < bufH) buf[(y + h - 1) * bufW + (x + i)] = c;
    }
    for (let i = 0; i < h; i++) {
        if (x >= 0 && x < bufW) buf[(y + i) * bufW + x] = c;
        if (x + w - 1 < bufW) buf[(y + i) * bufW + (x + w - 1)] = c;
    }
}

function updateStatus() {
    const el = document.getElementById('strateta-elite-idx');
    if (el) el.textContent = state.eliteIdx;
    const fitEl = document.getElementById('strateta-elite-fit');
    if (fitEl) fitEl.textContent =
        (state.library[state.eliteIdx]?.fitness ?? 0).toFixed(3);
    const rd = document.getElementById('strateta-rounds');
    if (rd) rd.textContent = state.rounds;
    const md = document.getElementById('strateta-refine-mode-status');
    if (md) md.textContent = state.refineMode;
}


// ── Source thumbnail rail ──────────────────────────────────────────
//
// Renders below the library so the user can compare the (image-derived)
// palettes against their source images at a glance. Scrolls horizontally
// when many images are loaded.

function paintSourceRail() {
    const rail = document.getElementById('strateta-source-rail');
    if (!rail) return;
    rail.innerHTML = '';
    if (!state.sourceImages.length) {
        rail.style.display = 'none';
        return;
    }
    rail.style.display = '';
    for (let i = 0; i < state.sourceImages.length; i++) {
        const im = state.sourceImages[i];
        const wrap = document.createElement('div');
        wrap.style.display = 'inline-block';
        wrap.style.marginRight = '0.4rem';
        wrap.style.verticalAlign = 'top';
        wrap.style.textAlign = 'center';
        wrap.style.fontSize = '0.7rem';
        wrap.style.color = '#8b949e';
        const img = document.createElement('img');
        img.src = im.dataURL;
        img.style.width = '64px';
        img.style.height = '64px';
        img.style.objectFit = 'cover';
        img.style.border = '1px solid #30363d';
        img.style.borderRadius = '3px';
        img.style.imageRendering = 'pixelated';
        img.title = im.name;
        wrap.appendChild(img);
        const cap = document.createElement('div');
        cap.textContent = im.name.length > 14 ? im.name.slice(0, 13) + '…' : im.name;
        cap.style.maxWidth = '64px';
        cap.style.overflow = 'hidden';
        cap.style.whiteSpace = 'nowrap';
        cap.style.textOverflow = 'ellipsis';
        wrap.appendChild(cap);
        rail.appendChild(wrap);
    }
}


// ── Image → palettes ───────────────────────────────────────────────

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

function makeImageThumbnail(img) {
    const TH = 64;
    const w = img.naturalWidth, h = img.naturalHeight;
    const side = Math.min(w, h);
    const cx = ((w - side) / 2) | 0, cy = ((h - side) / 2) | 0;
    const off = document.createElement('canvas');
    off.width = TH; off.height = TH;
    const ctx = off.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(img, cx, cy, side, side, 0, 0, TH, TH);
    return off.toDataURL('image/png');
}

// Image(s) → palettes: each library entry gets a 16×16 region of its
// chosen source image as its 256-colour palette (and as its
// pixel-faithful target). The library mosaic mirrors a 256×256-pixel
// preview of the picture (or a collage when multiple images uploaded).
function applyImagePalettesToLibrary(imgs, fileMeta) {
    if (!imgs || imgs.length === 0) return;
    const SK = INNER_W;                       // 16 — sqrt of K=256
    const PX = LIB_COLS * SK;                 // 256
    const PY = LIB_ROWS * SK;                 // 256
    const planes = imgs.map(img => rasterizeToPalettePlane(img, PX, PY));

    state.sourceImages = imgs.map((img, i) => ({
        name: (fileMeta && fileMeta[i] && fileMeta[i].name) || `image-${i+1}`,
        dataURL: makeImageThumbnail(img),
        w: img.naturalWidth, h: img.naturalHeight,
    }));
    state.sourceRegions = new Uint8ClampedArray(LIB_SIZE * INNER_W * INNER_H * 3);
    state.sourceTagPerEntry = new Uint8Array(LIB_SIZE);

    for (let er = 0; er < LIB_ROWS; er++) {
        for (let ec = 0; ec < LIB_COLS; ec++) {
            const entryIdx = er * LIB_COLS + ec;
            const entry = state.library[entryIdx];
            const tag = (planes.length === 1) ? 0
                                              : ((Math.random() * planes.length) | 0);
            const src = planes[tag];
            state.sourceTagPerEntry[entryIdx] = tag;
            const x0 = ec * SK, y0 = er * SK;
            const regOff = entryIdx * INNER_W * INNER_H * 3;
            for (let k = 0; k < LIB_K; k++) {
                const kx = k % SK, ky = (k / SK) | 0;
                const px = x0 + kx, py = y0 + ky;
                const idx = (py * PX + px) * 4;
                const r = src[idx], g = src[idx+1], b = src[idx+2];
                // Palette: nearest-ANSI quantize so the global palette
                // ceiling stays bounded at 256 distinct colours.
                const ansi = nearestAnsi256(r, g, b);
                const [qr, qg, qb] = ANSI_PALETTE_RGB[ansi];
                entry.paletteRGBA[k] = packRGBA(qr, qg, qb);
                // Source-region: keep the actual image RGB (pre-quantize)
                // so pixel-faithful fitness has the highest-resolution
                // target available.
                state.sourceRegions[regOff + k*3]     = r;
                state.sourceRegions[regOff + k*3 + 1] = g;
                state.sourceRegions[regOff + k*3 + 2] = b;
            }
        }
    }
}


// ── Population save / load ─────────────────────────────────────────

function u8ToJsonInts(u8) { return '[' + u8.join(',') + ']'; }

function buildStratetaPopulationJson(sources) {
    const parts = [];
    parts.push('{"format":"strateta-population-v1"');
    parts.push(',"sublab":"strateta"');
    parts.push(',"K":' + LIB_K);
    parts.push(',"lib_size":' + LIB_SIZE);
    parts.push(',"lib_rows":' + LIB_ROWS + ',"lib_cols":' + LIB_COLS);
    parts.push(',"inner_w":' + INNER_W + ',"inner_h":' + INNER_H);
    parts.push(',"n_entries":' + N_ENTRIES);
    parts.push(',"elite_idx":' + state.eliteIdx);
    parts.push(',"refine_mode":' + JSON.stringify(state.refineMode));
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
        parts.push('}');
    }
    parts.push(']');
    if (state.sourceRegions) {
        parts.push(',"source_regions":' + u8ToJsonInts(state.sourceRegions));
    }
    if (state.sourceImages.length) {
        parts.push(',"source_images":' + JSON.stringify(state.sourceImages));
    }
    parts.push('}');
    return parts.join('');
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
        if (filename.endsWith('.gz')) filename = filename.slice(0, -3);
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return blob.size;
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

async function loadStratetaPopulationFromFile(file) {
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
    if (data.format !== 'strateta-population-v1') {
        throw new Error('not a strateta-population-v1 file');
    }
    if (data.K !== LIB_K)         throw new Error(`K mismatch: file=${data.K}, build=${LIB_K}`);
    if (data.lib_size !== LIB_SIZE) throw new Error('lib_size mismatch');
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
        state.library.push({
            genome, paletteRGBA: palRGBA, gridA, bins,
            fitness: Number(lib.fitness) || 0,
            r: 0, pixFit: 0,
        });
    }
    state.eliteIdx = (data.elite_idx >= 0 && data.elite_idx < LIB_SIZE) ? data.elite_idx : 0;
    if (data.refine_mode === 'pixel-faithful' || data.refine_mode === 'edge-of-chaos') {
        state.refineMode = data.refine_mode;
    }
    if (Array.isArray(data.source_regions)) {
        state.sourceRegions = new Uint8ClampedArray(data.source_regions);
    } else {
        state.sourceRegions = null;
    }
    if (Array.isArray(data.source_images)) {
        state.sourceImages = data.source_images;
    } else {
        state.sourceImages = [];
    }
    state.rounds = 0;
}


// ── Click-to-download (genome → hexnn-genome-v1 JSON) ──────────────

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

async function downloadEntryAsJSON(idx, compress) {
    const e = state.library[idx];
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
        format:        'hexnn-genome-v1',
        K:             g.K,
        n_entries:     g.outs.length,
        palette:       paletteRGBAToCssHex(e.paletteRGBA),
        palette_name:  `strateta-${state.refineMode}-${idx}`,
        fingerprint:   fp,
        exported_at:   new Date().toISOString(),
        source:        'strateta',
        library_index: idx,
        fitness:       e.fitness,
        keys, outputs,
    };
    const json = JSON.stringify(payload);
    let blob, ext;
    if (compress && typeof CompressionStream !== 'undefined') {
        const cs = new CompressionStream('gzip');
        const w = cs.writable.getWriter();
        w.write(new TextEncoder().encode(json));
        w.close();
        const out = await new Response(cs.readable).arrayBuffer();
        blob = new Blob([out], {type: 'application/gzip'});
        ext = 'json.gz';
    } else {
        blob = new Blob([json], {type: 'application/json'});
        ext = 'json';
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

function tileFromMouse(mx, my, cols, rows, tileW, tileH) {
    const r = Math.floor(my / tileH);
    if (r < 0 || r >= rows) return null;
    const xOff = (r & 1) ? (tileW / 2 | 0) : 0;
    const localX = mx - xOff;
    const c = Math.floor(localX / tileW);
    if (c < 0 || c >= cols) return null;
    return { row: r, col: c };
}

function shouldCompress() {
    const cb = document.getElementById('strateta-gzip-cb');
    return cb ? cb.checked : true;
}

function onLibraryClick(ev) {
    const cv = ev.currentTarget;
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const hit = tileFromMouse(mx, my, LIB_COLS, LIB_ROWS, LIB_TILE_W, LIB_TILE_H);
    if (!hit) return;
    const idx = hit.row * LIB_COLS + hit.col;
    if (idx < 0 || idx >= LIB_SIZE) return;
    downloadEntryAsJSON(idx, shouldCompress());
}


// ── Wire-up ────────────────────────────────────────────────────────

function startTimers() {
    stopTimers();
    if (!state.running) return;
    state.innerHandle = setInterval(tickInner, state.innerTickMs);
    state.tournHandle = setInterval(tickTournament, state.tournMs);
}
function stopTimers() {
    if (state.innerHandle) { clearInterval(state.innerHandle); state.innerHandle = null; }
    if (state.tournHandle) { clearInterval(state.tournHandle); state.tournHandle = null; }
}

function init() {
    const libCv = document.getElementById('strateta-library');
    if (libCv) { libCv.width = LIB_CANVAS_W; libCv.height = LIB_CANVAS_H; }

    bootstrap();
    paintLibrary();
    paintSourceRail();
    updateStatus();

    document.getElementById('pause-btn').onclick = () => {
        state.running = !state.running;
        document.getElementById('pause-btn').textContent =
            state.running ? 'Pause' : 'Run';
        if (state.running) startTimers(); else stopTimers();
    };
    document.getElementById('reset-lib-btn').onclick = () => {
        bootstrap();
        paintLibrary();
        updateStatus();
    };

    document.getElementById('inner-tick').oninput = (e) => {
        state.innerTickMs = parseInt(e.target.value, 10);
        document.getElementById('inner-tick-out').textContent = state.innerTickMs + ' ms';
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

    const huntBtn   = document.getElementById('strateta-hunt-btn');
    const refineBtn = document.getElementById('strateta-refine-btn');
    if (huntBtn)   huntBtn.onclick   = () => runHunt(false);
    if (refineBtn) refineBtn.onclick = () => runHunt(true);

    // Full auto: Hunt once, then loop Refine on a configurable cadence.
    // Tournament keeps running in the gap, so the population evolves
    // naturally between refines. Click again to stop — the in-flight
    // Refine completes before the loop exits.
    const autoBtn     = document.getElementById('strateta-auto-btn');
    const autoDelayEl = document.getElementById('strateta-auto-delay');
    if (autoBtn) {
        autoBtn.onclick = () => {
            if (state.autoActive) {
                state.autoActive = false;
                setAutoButtonLabel(false);
            } else {
                startStratetaAuto();
            }
        };
    }
    function setAutoButtonLabel(active) {
        if (!autoBtn) return;
        autoBtn.textContent  = active ? '⏹ Stop auto' : '🔁 Full auto';
        autoBtn.style.background = active ? '#cf222e' : '#a371f7';
    }
    async function startStratetaAuto() {
        if (state.hunting || state.autoActive) return;
        state.autoActive = true;
        setAutoButtonLabel(true);
        await runHunt(false);
        while (state.autoActive) {
            let delaySec = parseFloat(autoDelayEl ? autoDelayEl.value : '6');
            if (!Number.isFinite(delaySec) || delaySec < 1) delaySec = 6;
            if (delaySec > 120) delaySec = 120;
            let remainingMs = delaySec * 1000;
            while (state.autoActive && remainingMs > 0) {
                setHuntStatus(`🔁 auto: next refine in ${(remainingMs / 1000).toFixed(1)}s · mode ${state.refineMode}`);
                await new Promise(r => setTimeout(r, 100));
                remainingMs -= 100;
            }
            if (!state.autoActive) break;
            await runHunt(true);
        }
        setAutoButtonLabel(false);
        const cur = (document.getElementById('strateta-hunt-status')?.textContent) || '';
        if (cur.startsWith('🔁')) setHuntStatus('auto stopped.');
    }

    const paletteSel = document.getElementById('strateta-palette-mode');
    if (paletteSel) {
        paletteSel.value = state.paletteMode;
        paletteSel.onchange = (e) => {
            state.paletteMode = e.target.value;
            for (let i = 0; i < state.library.length; i++) {
                const seed = ((Math.random() * 0xFFFFFFFF) >>> 0) ^ (i * 2654435761);
                state.library[i].paletteRGBA = makePaletteRGBA(
                    LIB_K, state.paletteMode, mulberry32(seed));
            }
            paintLibrary();
        };
    }

    const refineModeSel = document.getElementById('strateta-refine-mode');
    if (refineModeSel) {
        refineModeSel.value = state.refineMode;
        refineModeSel.onchange = (e) => {
            state.refineMode = e.target.value;
            updateStatus();
            // Re-score the library under the new fitness so the elite
            // and rankings reflect the active mode.
            for (let i = 0; i < state.library.length; i++) {
                scoreEntry(state.library[i], i);
            }
            state.eliteIdx = pickElite();
            updateStatus();
            paintLibrary();
        };
    }

    if (libCv) {
        libCv.style.cursor = 'pointer';
        libCv.addEventListener('click', onLibraryClick);
    }

    // Image(s) → palettes + source rail + auto-export.
    const imgInput = document.getElementById('strateta-image-input');
    if (imgInput) {
        imgInput.addEventListener('change', async (e) => {
            const files = [...(e.target.files || [])]
                .filter(f => f.type && f.type.startsWith('image/'));
            if (files.length === 0) return;
            const status = document.getElementById('strateta-hunt-status');
            if (status) {
                status.style.color = '#8b949e';
                status.textContent = `loading ${files.length} image${files.length > 1 ? 's' : ''}…`;
            }
            try {
                const imgs = await Promise.all(files.map(loadImageFile));
                const meta = files.map(f => ({ name: f.name, size: f.size }));
                applyImagePalettesToLibrary(imgs, meta);
                paintSourceRail();
                paintLibrary();
                if (status) {
                    status.style.color = '#3fb950';
                    status.textContent = files.length === 1
                        ? 'palettes loaded · saving population…'
                        : `palettes loaded — ${files.length} sources · saving population…`;
                }
                const json = buildStratetaPopulationJson(meta);
                const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const sz = await downloadGzipped(`strateta-population-K${LIB_K}-${stamp}.json.gz`, json);
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

    const saveBtn = document.getElementById('strateta-save-population-btn');
    if (saveBtn) {
        saveBtn.onclick = async () => {
            const status = document.getElementById('strateta-hunt-status');
            if (status) {
                status.style.color = '#8b949e';
                status.textContent = 'saving population…';
            }
            try {
                const json = buildStratetaPopulationJson([]);
                const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const sz = await downloadGzipped(`strateta-population-K${LIB_K}-${stamp}.json.gz`, json);
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

    const loadInput = document.getElementById('strateta-load-population-input');
    if (loadInput) {
        loadInput.addEventListener('change', async (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file) return;
            const status = document.getElementById('strateta-hunt-status');
            if (status) {
                status.style.color = '#8b949e';
                status.textContent = `loading ${file.name}…`;
            }
            try {
                await loadStratetaPopulationFromFile(file);
                paintSourceRail();
                paintLibrary();
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

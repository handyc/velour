// cellular.mjs — sublab: 8x8 toroidal cellular GA where the grid IS
// the population.
//
// The substrate is hexagonal at TWO scales: each tile is a hex CA
// (the engine.mjs default), and the 8x8 *grid of tiles* is itself
// a pointy-top hex tiling — odd rows shifted +TILE_PX/2 on x. This
// makes population-level selection flow through the same 6-neighbour
// topology that the rules themselves operate on inside each tile.
// Beautifully self-similar: rules that win at the substrate scale
// spread through a substrate-shaped population.
//
// 64 cells, each holding one genome + palette + live CA grid + last-
// known fitness. Every cell steps its CA continuously like Filmstrip;
// the GA happens on a separate, slower clock as a "round":
//
//   1. Pick a random cell C and one of its 6 hex-neighbours N (toroidal
//      — left edge wraps to right, top to bottom — so selection
//      pressure is uniform across the grid).
//   2. Score both genomes on a shared grid_seed (so the comparison
//      is fair).
//   3. The loser is replaced by a mutated copy of the winner.
//      Palette inherits from the winner. Loser's grid restarts.
//
// Watch a few rounds: regional palettes converge, then drift, as
// good rules sweep neighbourhoods and mutate at the edges. The grid
// becomes a literal evolutionary landscape.
//
// Why not Web Workers per cell: a round is ~50 microseconds (two 25-
// tick fitness evals at 16x16, K=4, packed lookup). At 2 rounds/sec
// that's 100 us/sec — orders of magnitude under any need for off-
// thread work. Inline keeps the code simple and the visuals tight.

import {
    K, GBYTES, PAL_BYTES, GRID_W, GRID_H,
    seed_prng, prng,
    seed_grid, step_grid,
    fitness, mutate, palette_inherit,
    ansi256_to_css,
    random_genome, invent_palette, identity_genome,
} from '../engine.mjs';

// ── Layout ─────────────────────────────────────────────────────────

const GRID_COLS    = 16;
const GRID_ROWS    = 16;
const N_CELLS      = GRID_COLS * GRID_ROWS;
const TILE_PX      = 24;        // half of Filmstrip — needed to fit
                                // 16×16 = 256 tiles in a viewport.
                                // At 24 px tile, each internal CA cell
                                // is ~1.45 px so individual hex cells
                                // smear together; what dominates here
                                // is the palette field per tile and
                                // aggregate motion.
const TILE_GAP     = 3;
const CELL_PX      = TILE_PX / (GRID_W + 0.5);   // pointy-top hex (cells)
// Pointy-top hex layout for the tile grid itself: odd rows are
// shifted +TILE_PX/2 on x, mirroring the cell-level offset inside
// each tile. Canvas width must accommodate the offset row's right
// edge, hence the extra +TILE_PX/2 below.
const CANVAS_W     = GRID_COLS * (TILE_PX + TILE_GAP) - TILE_GAP + TILE_PX / 2;
const CANVAS_H     = GRID_ROWS * (TILE_PX + TILE_GAP) - TILE_GAP;

// ── Algorithm tunables ─────────────────────────────────────────────

// Rounds per second. Default 2 → noticeable spatial dynamics emerge
// in 1–2 minutes without burning CPU. User-adjustable in the UI.
const DEFAULT_ROUND_MS  = 500;

// Mutation rate when copying winner→loser. Lower than a fresh GA
// run because we're already starting from a winner — too high and
// the population drifts to noise; too low and the grid converges
// to a single rule and stops evolving. 0.5% is a reasonable middle.
const DEFAULT_MUT_RATE  = 0.005;

// Recency border: how long after a refine the green border lingers
// before fading to neutral grey. Long enough to see waves spread.
const RECENCY_FADE_MS   = 5000;

// Score evaluation horizon. 25 ticks matches engine.fitness() default
// and the existing hunt — keeps scores comparable between sublabs.
const SCORE_STEPS       = 25;

// ── State ──────────────────────────────────────────────────────────

function makeCell(seed) {
    seed_prng(seed);
    return {
        genome:  random_genome(),
        palette: invent_palette(),
        gridA:   new Uint8Array(GRID_W * GRID_H),
        gridB:   new Uint8Array(GRID_W * GRID_H),
        score:   0,
        refinedAt: 0,    // wall-clock ms of last replacement; 0 if pristine
    };
}

const state = {
    cells: [],                      // length N_CELLS, row-major
    running: true,                  // CA step + rounds both enabled
    tickMs: 200,                    // CA step interval
    roundMs: DEFAULT_ROUND_MS,
    mutRate: DEFAULT_MUT_RATE,
    showArrows: false,              // overlay arrows of the most recent round
    lastRound: null,                // {winner, loser, ts} for arrow overlay
    tickHandle: null,
    roundHandle: null,
    rounds: 0,
    selectionMechanic: 'tournament',  // future: 'crossover' | 'tide'
};

// ── Boot ───────────────────────────────────────────────────────────

function bootstrap() {
    state.cells = [];
    for (let i = 0; i < N_CELLS; i++) {
        const seed = ((Math.random() * 0xFFFFFFFF) >>> 0) ^ (i * 2654435761);
        const c = makeCell(seed);
        seed_grid(c.gridA, ((Math.random() * 0xFFFFFFFF) >>> 0));
        state.cells.push(c);
    }
    state.rounds = 0;
}

// ── Topology: toroidal pointy-top 6-neighbour hex ──────────────────
//
// Pointy-top means cells point up/down (vs flat-top which points
// left/right). For pointy-top with odd rows shifted +0.5 on x, the
// six neighbour positions depend on whether the row is even or odd —
// hence the two delta tables below. Same offset-row convention used
// by software hex-grid libraries (Red Blob Games' "odd-r offset").
//
// Order: W, E, NW, NE, SW, SE — six directions, no straight N/S
// because pointy-top hex has horizontal sides, not vertical.

const NB_DC_EVEN = [-1, +1, -1,  0, -1,  0];   // even rows
const NB_DC_ODD  = [-1, +1,  0, +1,  0, +1];   // odd rows
const NB_DR      = [ 0,  0, -1, -1, +1, +1];

function neighbourIdx(i, dir) {
    const r = (i / GRID_COLS) | 0;
    const c = i - r * GRID_COLS;
    const dc = (r & 1) ? NB_DC_ODD[dir] : NB_DC_EVEN[dir];
    const dr = NB_DR[dir];
    const nr = (r + dr + GRID_ROWS) % GRID_ROWS;
    const nc = (c + dc + GRID_COLS) % GRID_COLS;
    return nr * GRID_COLS + nc;
}

// ── Tick: step every cell's CA grid ────────────────────────────────

function tickAll() {
    if (!state.running) return;
    for (let i = 0; i < state.cells.length; i++) {
        const c = state.cells[i];
        step_grid(c.genome, c.gridA, c.gridB);
        // swap A↔B without re-allocating
        const tmp = c.gridA; c.gridA = c.gridB; c.gridB = tmp;
    }
    paintGrid();
}

// ── Round: tournament between random cell + random neighbour ───────

function runRound() {
    if (!state.running) return;

    const ci = (Math.random() * N_CELLS) | 0;
    const dir = (Math.random() * 6) | 0;        // 6 hex directions
    const ni = neighbourIdx(ci, dir);
    if (ci === ni) return;          // safety; shouldn't happen with N=8

    // Score both on the same fresh seed for a fair comparison.
    const sharedSeed = (Math.random() * 0xFFFFFFFF) >>> 0;
    const fc = fitness(state.cells[ci].genome, sharedSeed).score;
    const fn = fitness(state.cells[ni].genome, sharedSeed).score;

    state.cells[ci].score = fc;
    state.cells[ni].score = fn;

    // Tournament: higher fitness wins. Ties favour the cell already
    // there (minor bias toward stability, prevents free drift).
    const winnerIdx = fc >= fn ? ci : ni;
    const loserIdx  = winnerIdx === ci ? ni : ci;

    const W = state.cells[winnerIdx];
    const L = state.cells[loserIdx];

    // Loser inherits a *mutated* copy of the winner. Mutating in
    // place avoids allocating; we use the loser's existing buffers.
    mutate(L.genome, W.genome, state.mutRate);
    palette_inherit(L.palette, W.palette, W.palette);
    L.score     = W.score;     // best estimate available without re-scoring
    L.refinedAt = Date.now();
    // Reset the loser's grid so the new genome's CA isn't running on
    // the previous genome's spacetime — would conflate identity and
    // history visually.
    seed_grid(L.gridA, (Math.random() * 0xFFFFFFFF) >>> 0);

    state.lastRound = { winner: winnerIdx, loser: loserIdx, ts: Date.now() };
    state.rounds++;
    document.getElementById('cellular-rounds').textContent = state.rounds;

    paintGrid();
}

// ── Render ─────────────────────────────────────────────────────────

const canvas = () => document.getElementById('cellular');

function paintGrid() {
    const cv = canvas();
    if (!cv) return;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, cv.width, cv.height);

    const now = Date.now();
    for (let i = 0; i < N_CELLS; i++) {
        const r = (i / GRID_COLS) | 0;
        const c = i - r * GRID_COLS;
        // Pointy-top tile-grid: odd rows shifted +TILE_PX/2 on x, the
        // same offset trick applied at the cell level inside each tile.
        const xOff = (r & 1) ? TILE_PX / 2 : 0;
        const x = c * (TILE_PX + TILE_GAP) + xOff;
        const y = r * (TILE_PX + TILE_GAP);
        paintTile(ctx, state.cells[i], x, y, now);
    }

    if (state.showArrows && state.lastRound &&
        now - state.lastRound.ts < 1500) {
        paintArrow(ctx, state.lastRound.winner, state.lastRound.loser, now);
    }
}

function paintTile(ctx, cell, x, y, now) {
    const css = [
        ansi256_to_css(cell.palette[0]),
        ansi256_to_css(cell.palette[1]),
        ansi256_to_css(cell.palette[2]),
        ansi256_to_css(cell.palette[3]),
    ];
    for (let cy = 0; cy < GRID_H; cy++) {
        const xOff = (cy & 1) ? CELL_PX * 0.5 : 0;
        for (let cx = 0; cx < GRID_W; cx++) {
            const v = cell.gridA[cy * GRID_W + cx];
            ctx.fillStyle = css[v & 3];
            ctx.fillRect(x + cx * CELL_PX + xOff, y + cy * CELL_PX,
                         CELL_PX, CELL_PX);
        }
    }
    // Recency border: bright green just after a replacement, fading
    // over RECENCY_FADE_MS to neutral grey. Lets you watch good rules
    // spread literally as a visual wave.
    const ageMs = cell.refinedAt ? (now - cell.refinedAt) : Infinity;
    const t = Math.min(1, ageMs / RECENCY_FADE_MS);
    if (t < 1) {
        const a = (1 - t).toFixed(3);
        ctx.strokeStyle = `rgba(63, 185, 80, ${a})`;
        ctx.lineWidth   = 2;
        ctx.strokeRect(x + 0.5, y + 0.5, TILE_PX - 1, TILE_PX - 1);
    } else {
        ctx.strokeStyle = '#21262d';
        ctx.lineWidth   = 1;
        ctx.strokeRect(x + 0.5, y + 0.5, TILE_PX - 1, TILE_PX - 1);
    }
}

function tileCenter(idx) {
    const r = (idx / GRID_COLS) | 0;
    const c = idx - r * GRID_COLS;
    const xOff = (r & 1) ? TILE_PX / 2 : 0;
    return [
        c * (TILE_PX + TILE_GAP) + xOff + TILE_PX / 2,
        r * (TILE_PX + TILE_GAP)        + TILE_PX / 2,
    ];
}

function paintArrow(ctx, fromIdx, toIdx, now) {
    const age = now - state.lastRound.ts;
    const a = (1 - age / 1500).toFixed(3);
    const [x1, y1] = tileCenter(fromIdx);
    const [x2, y2] = tileCenter(toIdx);
    ctx.strokeStyle = `rgba(255, 255, 255, ${a})`;
    ctx.lineWidth   = 2;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    // Arrowhead — small triangle at the loser cell.
    const ah = 6;
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    const px = -uy, py = ux;
    ctx.fillStyle = `rgba(255, 255, 255, ${a})`;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - ux * ah + px * ah * 0.6, y2 - uy * ah + py * ah * 0.6);
    ctx.lineTo(x2 - ux * ah - px * ah * 0.6, y2 - uy * ah - py * ah * 0.6);
    ctx.closePath();
    ctx.fill();
}

// ── Wire-up ─────────────────────────────────────────────────────────

function startTimers() {
    stopTimers();
    if (state.running) {
        state.tickHandle  = setInterval(tickAll, state.tickMs);
        state.roundHandle = setInterval(runRound, state.roundMs);
    }
}
function stopTimers() {
    if (state.tickHandle)  { clearInterval(state.tickHandle);  state.tickHandle  = null; }
    if (state.roundHandle) { clearInterval(state.roundHandle); state.roundHandle = null; }
}

function init() {
    bootstrap();
    const cv = canvas();
    if (cv) {
        cv.width  = CANVAS_W;
        cv.height = CANVAS_H;
    }
    paintGrid();

    document.getElementById('round-ms').oninput = (e) => {
        const v = parseInt(e.target.value, 10);
        if (Number.isFinite(v) && v > 50) {
            state.roundMs = v;
            document.getElementById('round-ms-out').textContent = v + ' ms';
            if (state.running) startTimers();
        }
    };
    document.getElementById('tick-ms').oninput = (e) => {
        const v = parseInt(e.target.value, 10);
        if (Number.isFinite(v) && v >= 20) {
            state.tickMs = v;
            document.getElementById('tick-ms-out').textContent = v + ' ms';
            if (state.running) startTimers();
        }
    };
    document.getElementById('mut-rate').oninput = (e) => {
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v) && v >= 0) {
            state.mutRate = v;
        }
    };
    document.getElementById('arrows-cb').onchange = (e) => {
        state.showArrows = e.target.checked;
    };
    document.getElementById('pause-btn').onclick = () => {
        state.running = !state.running;
        document.getElementById('pause-btn').textContent =
            state.running ? 'Pause' : 'Run';
        if (state.running) startTimers(); else stopTimers();
    };
    document.getElementById('reset-btn').onclick = () => {
        bootstrap();
        document.getElementById('cellular-rounds').textContent = 0;
        paintGrid();
    };
    document.getElementById('seed-btn').onclick = () => {
        // Reseed the grids of every cell — keeps genomes, restarts
        // their CAs from a fresh random initial condition. Useful
        // when many cells have settled into their attractors.
        for (let i = 0; i < state.cells.length; i++) {
            seed_grid(state.cells[i].gridA,
                     (Math.random() * 0xFFFFFFFF) >>> 0);
        }
        paintGrid();
    };

    startTimers();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

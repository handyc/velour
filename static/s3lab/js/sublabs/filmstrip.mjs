// filmstrip.mjs — sublab: scrolling strip of past CA refinements.
//
// Same engine + Web-Worker hunt as Classic; different rendering. The
// strip holds the last N=8 refinements as freezable frames. The live
// tile (rightmost) is always running. Each Refine completes →
//   1. snapshot the live state (genome, palette, grid, fitness),
//   2. shift the strip left by one (oldest frame falls off the left),
//   3. push the snapshot as the just-superseded penultimate slot,
//   4. install the new winner as live.
//
// Frozen frames cost zero CPU after their initial draw. The "run
// history" toggle steps every frame each tick (Nx CPU at 16x16 is
// fine; the limit is bin lookups, not cells).

import {
    K, GBYTES, PAL_BYTES, GRID_W, GRID_H,
    seed_prng, prng,
    seed_grid, step_grid,
    ansi256_to_css,
    random_genome, invent_palette,
} from '../engine.mjs';

// ── Tunables ──────────────────────────────────────────────────────────

const N_FRAMES        = 8;        // total strip slots (including live)
const TILE_PX         = 96;       // pixel side of one CA tile
const TILE_GAP        = 8;        // gap between tiles
const CAPTION_PX      = 24;       // strip below the tile for badges
// Pointy-top hex rendering: odd rows are shifted +CELL_PX/2 on x, so
// the rightmost cell of an odd row would overshoot a TILE_PX/GRID_W
// cell width. Divide by GRID_W + 0.5 instead so the offset row's
// right edge lands exactly at TILE_PX. Same trick s3lab's TFT
// renderer uses (drawCell in classic.mjs).
const CELL_PX         = TILE_PX / (GRID_W + 0.5);

// Stall-detection thresholds — same as Classic.
const ACT_FLOOR_RUN        = 0.05;
const STATIC_DWELL_LIMIT   = 15;
const PERIODIC_DWELL_LIMIT = 8;

// ── State ─────────────────────────────────────────────────────────────
//
// frames[] is the strip from oldest (index 0) to newest. The LIVE tile
// always lives at frames[N_FRAMES - 1]. Older frames are "frozen": their
// `gridA` is the pinned snapshot. When `runHistory` is on, we step each
// frame's grid every tick.

function makeFrame({ genome, palette, fitness, label } = {}) {
    return {
        genome:    genome  || random_genome(),
        palette:   palette || new Uint8Array([21, 196, 226, 46]),
        gridA:     new Uint8Array(GRID_W * GRID_H),
        gridB:     new Uint8Array(GRID_W * GRID_H),
        fitness:   fitness != null ? fitness : null,
        label:     label || 'random',
        born:      Date.now(),
        pinned:    false,         // future hook — never auto-evict
    };
}

const state = {
    frames: [],                   // length up to N_FRAMES, last = live
    tickMs: 200,
    running: true,
    tick: 0,
    runHistory: false,
    autoRefine: true,             // stall-triggered refine
    hunting: false,
    huntKind: '',                 // 'fresh' | 'refine'

    // Periodic-refine timer — independent of stall detection. When
    // enabled, fires a refine every `timerRefineSec` seconds (skipped
    // if a hunt is already running so we don't queue refines on
    // refines).
    timerRefine:    false,
    timerRefineSec: 1,
    timerHandle:    null,

    // live-only activity tracking (mirrors Classic)
    activityHistory: [],
    activityHistoryN: 60,
    staticDwellTicks: 0,
    lastTickActivity: 0,
    gridHashes: [],
    gridHashN: 16,
    periodicDwell: 0,
};

function liveFrame() { return state.frames[state.frames.length - 1]; }

// ── Init: empty strip with one fresh live tile ────────────────────────

function bootstrap() {
    seed_prng((Math.random() * 0xFFFFFFFF) >>> 0);
    const f = makeFrame({
        genome: random_genome(),
        palette: invent_palette(),
        label: 'random',
    });
    seed_grid(f.gridA, prng());
    state.frames = [f];
}

// ── Tick: step live, optionally step history ─────────────────────────

function tickAll() {
    if (!state.running || state.frames.length === 0) return;

    // Live tile.
    const live = liveFrame();
    step_grid(live.genome, live.gridA, live.gridB);
    [live.gridA, live.gridB] = [live.gridB, live.gridA];
    state.lastTickActivity = countActivity(live.gridA, live.gridB);
    pushActivity(state.lastTickActivity);

    // History (frozen by default).
    if (state.runHistory) {
        for (let i = 0; i < state.frames.length - 1; i++) {
            const f = state.frames[i];
            step_grid(f.genome, f.gridA, f.gridB);
            [f.gridA, f.gridB] = [f.gridB, f.gridA];
        }
    }

    state.tick++;
    document.getElementById('tick-count').textContent = state.tick;

    paintStrip();
    updateActivityDisplay();
    checkAutoRefine();
}

function countActivity(prev, cur) {
    let changed = 0;
    for (let i = 0; i < prev.length; i++) if (prev[i] !== cur[i]) changed++;
    return changed / prev.length;
}

function pushActivity(v) {
    state.activityHistory.push(v);
    if (state.activityHistory.length > state.activityHistoryN) {
        state.activityHistory.shift();
    }
}

function activityMA() {
    const a = state.activityHistory;
    if (!a.length) return 0;
    let s = 0; for (let i = 0; i < a.length; i++) s += a[i];
    return s / a.length;
}

function gridHash(g) {
    let h = 0;
    for (let i = 0; i < g.length; i++) h = ((h * 33) ^ g[i]) >>> 0;
    return h;
}

function checkPeriodicity() {
    const live = liveFrame();
    const h = gridHash(live.gridA);
    state.gridHashes.push(h);
    if (state.gridHashes.length > state.gridHashN) state.gridHashes.shift();
    // Are we revisiting a recent state?
    for (let i = 0; i < state.gridHashes.length - 1; i++) {
        if (state.gridHashes[i] === h) return true;
    }
    return false;
}

// ── Render the whole strip (one canvas, N tile boxes) ───────────────

const canvas = () => document.getElementById('filmstrip');
const captionsEl = () => document.getElementById('filmstrip-captions');

function paintStrip() {
    const cv = canvas();
    if (!cv) return;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, cv.width, cv.height);

    // Right-align the strip so the live tile (newest) sits at the
    // right edge. Older frames extend leftward.
    const total = state.frames.length;
    const stripW = total * TILE_PX + (total - 1) * TILE_GAP;
    const x0 = cv.width - stripW;

    for (let i = 0; i < total; i++) {
        const f = state.frames[i];
        const x = x0 + i * (TILE_PX + TILE_GAP);
        paintTile(ctx, f, x, 0);
    }

    paintCaptions();
}

function paintTile(ctx, f, x, y) {
    // Cell colours from the genome's palette via ANSI lookup.
    const css = [
        ansi256_to_css(f.palette[0]),
        ansi256_to_css(f.palette[1]),
        ansi256_to_css(f.palette[2]),
        ansi256_to_css(f.palette[3]),
    ];
    // Pointy-top hex layout: odd rows shifted +CELL_PX/2 on x. The
    // resulting tile has the jagged left/right edge that makes the
    // hexagonal cell relationships visible. Engine math is hex on
    // both axes; without the offset, the visualisation hides it.
    for (let cy = 0; cy < GRID_H; cy++) {
        const xOff = (cy & 1) ? CELL_PX * 0.5 : 0;
        for (let cx = 0; cx < GRID_W; cx++) {
            const v = f.gridA[cy * GRID_W + cx];
            ctx.fillStyle = css[v & 3];
            ctx.fillRect(x + cx * CELL_PX + xOff, y + cy * CELL_PX,
                         CELL_PX, CELL_PX);
        }
    }
    // Frame: green for live, dim grey for history.
    const isLive = (f === liveFrame());
    ctx.strokeStyle = isLive ? '#3fb950' : '#30363d';
    ctx.lineWidth   = isLive ? 2 : 1;
    ctx.strokeRect(x + 0.5, y + 0.5, TILE_PX - 1, TILE_PX - 1);
}

function paintCaptions() {
    const el = captionsEl();
    if (!el) return;
    const total = state.frames.length;
    const items = state.frames.map((f, i) => {
        const isLive = i === total - 1;
        const fitTxt = f.fitness != null ? f.fitness.toFixed(2) : '—';
        const ageMs  = Date.now() - f.born;
        const ageTxt = ageMs < 60000 ? `${(ageMs / 1000) | 0}s`
                                     : `${(ageMs / 60000) | 0}m`;
        const mark   = isLive ? '<span class="frame-live">● live</span>'
                              : `<span class="frame-age">${ageTxt}</span>`;
        return `<div class="frame-caption">
                  <span class="frame-label">${escapeHtml(f.label)}</span>
                  <span class="frame-fit">fit ${fitTxt}</span>
                  ${mark}
                </div>`;
    });
    el.innerHTML = items.join('');
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
}

function updateActivityDisplay() {
    const now = state.lastTickActivity;
    const ma  = activityMA();
    document.getElementById('act-now').textContent = (now * 100).toFixed(1) + '%';
    document.getElementById('act-ma').textContent  = (ma  * 100).toFixed(1) + '%';
    paintActivitySpark();
}

const SPARK_W = 200, SPARK_H = 28;
function paintActivitySpark() {
    const sp = document.getElementById('act-spark');
    if (!sp) return;
    const ctx = sp.getContext('2d');
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, SPARK_W, SPARK_H);
    // Floor line at 5%.
    ctx.strokeStyle = '#30363d';
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    const yFloor = SPARK_H - ACT_FLOOR_RUN * SPARK_H * 4;
    ctx.moveTo(0, yFloor); ctx.lineTo(SPARK_W, yFloor);
    ctx.stroke();
    ctx.setLineDash([]);

    const a = state.activityHistory;
    if (!a.length) return;
    ctx.strokeStyle = '#58a6ff';
    ctx.beginPath();
    for (let i = 0; i < a.length; i++) {
        const x = (i / (state.activityHistoryN - 1)) * SPARK_W;
        const y = SPARK_H - Math.min(1, a[i] * 4) * SPARK_H;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
}

function checkAutoRefine() {
    if (!state.autoRefine || state.hunting) return;
    const ma = activityMA();
    if (ma < ACT_FLOOR_RUN) {
        state.staticDwellTicks++;
    } else {
        state.staticDwellTicks = 0;
    }
    const periodic = checkPeriodicity();
    if (periodic) {
        state.periodicDwell++;
    } else {
        state.periodicDwell = 0;
    }
    document.getElementById('act-dwell').textContent =
        state.staticDwellTicks > 0 || state.periodicDwell > 0
            ? `dwell ${state.staticDwellTicks}/${STATIC_DWELL_LIMIT} `
              + `· per ${state.periodicDwell}/${PERIODIC_DWELL_LIMIT}`
            : '';
    if (state.staticDwellTicks >= STATIC_DWELL_LIMIT
        || state.periodicDwell >= PERIODIC_DWELL_LIMIT) {
        startHunt({ warmStart: true,
                     reason: state.periodicDwell >= PERIODIC_DWELL_LIMIT
                              ? 'cycle' : 'low activity' });
    }
}

// ── Hunt control — same Worker contract as Classic ───────────────────

let huntWorker = null;
let huntStartedAt = 0;
let currentAttempt = 0;
let totalAttempts  = 0;

function startHunt({ warmStart = false, reason = '' } = {}) {
    if (state.hunting) return;
    state.hunting  = true;
    state.huntKind = warmStart ? 'refine' : 'fresh';
    huntStartedAt  = performance.now();
    document.getElementById('hunt-btn').disabled    = true;
    document.getElementById('refine-btn').disabled  = true;
    const labelPrefix = warmStart ? 'refining' : 'hunting';
    const status = document.getElementById('hunt-status');
    status.textContent = reason
        ? `${labelPrefix} (${reason}) — starting…`
        : `${labelPrefix} — starting…`;

    huntWorker = new Worker(
        new URL('../worker.mjs', import.meta.url),
        { type: 'module' }
    );
    const live = liveFrame();
    huntWorker.onmessage = (e) => {
        const m = e.data;
        if (m.type === 'attempt') {
            currentAttempt = m.n;
            totalAttempts  = m.total;
        } else if (m.type === 'progress') {
            status.textContent =
                `${state.huntKind} [${currentAttempt}/${totalAttempts}] ` +
                `gen ${m.gen}/${m.total}  best ${m.best.toFixed(2)}  ` +
                `mean ${m.mean.toFixed(2)}  tail ${m.tail.toFixed(3)}`;
            document.getElementById('hunt-progress').value = m.gen / m.total;
        } else if (m.type === 'verify') {
            const pct = (m.activity_ma * 100).toFixed(1);
            status.textContent = m.accepted
                ? `[${currentAttempt}/${totalAttempts}] accepted — ${pct}%`
                : `[${currentAttempt}/${totalAttempts}] rejected — ${m.reason} (${pct}%)`;
        } else if (m.type === 'done') {
            // On success: snapshot the just-running live tile and push
            // a brand-new live with the winning genome.
            const oldLive = liveFrame();
            // Stamp the soon-to-be-history frame with its score so the
            // caption can show it.
            oldLive.fitness = m.fitness;
            oldLive.label   = state.huntKind === 'refine' ? 'refined' : 'hunted';

            const newLive = makeFrame({
                genome:  new Uint8Array(m.genome),
                palette: new Uint8Array(m.palette),
                fitness: null,           // unscored at install time
                label:   'live',
            });
            seed_grid(newLive.gridA, prng());
            // Shift left if we're at capacity, else just append.
            if (state.frames.length >= N_FRAMES) {
                state.frames.shift();
            }
            state.frames.push(newLive);

            state.hunting = false;
            document.getElementById('hunt-btn').disabled    = false;
            document.getElementById('refine-btn').disabled  = false;
            const elapsed = (performance.now() - huntStartedAt) / 1000;
            const pct = (m.activity_ma * 100).toFixed(1);
            const verdict = m.accepted ? 'accepted' : 'forced';
            status.textContent =
                `done — fitness ${m.fitness.toFixed(2)}  ` +
                `${pct}%  attempts ${m.attempts}  ` +
                `${elapsed.toFixed(1)}s · ${verdict}`;
            document.getElementById('hunt-progress').value = 1.0;

            // Reset activity tracking on the new live tile.
            state.activityHistory = [];
            state.gridHashes = [];
            state.staticDwellTicks = 0;
            state.periodicDwell = 0;
            state.lastTickActivity = 0;
            paintStrip();
            updateActivityDisplay();
            huntWorker.terminate();
            huntWorker = null;
        }
    };

    // Send the live tile as the warm-start seed for refine mode.
    // User-tunable knobs from the Hunt control row are read at
    // launch time, so changes apply to the next hunt without a
    // page reload. We don't double-bump the warm-start mutation rate
    // the way Classic does — the user already controls this directly.
    const hp = readHuntParams();
    huntWorker.postMessage({
        type:      'run_hunt',
        prng_seed: (Math.random() * 0xffffffff) >>> 0,
        grid_seed: (Math.random() * 0xffffffff) >>> 0,
        seedGenome:          warmStart ? live.genome.buffer.slice(0)  : null,
        seedPalette:         warmStart ? live.palette.buffer.slice(0) : null,
        initialMutationRate: hp.mut,
        popSize:             hp.pop,
        gens:                hp.gens,
        maxAttempts:         hp.attempts,
        activityFloor:       0.05,
        activityCeil:        0.50,
    });
}

// Read the four hunt-tuning inputs and clamp to safe ranges. Called
// at hunt-launch time so changes take effect on the very next run.
function readHuntParams() {
    const num = (id, dflt, min, max) => {
        const el = document.getElementById(id);
        const v = el ? parseFloat(el.value) : dflt;
        if (!Number.isFinite(v)) return dflt;
        return Math.min(max, Math.max(min, v));
    };
    return {
        pop:      num('hunt-pop',      30,   4, 128) | 0,
        gens:     num('hunt-gens',     40,   5, 300) | 0,
        mut:      num('hunt-mut',      0.05, 0, 0.5),
        attempts: num('hunt-attempts', 4,    1, 10)  | 0,
    };
}

function paintHuntCost() {
    const el = document.getElementById('hunt-cost');
    if (!el) return;
    const p = readHuntParams();
    // pop * gens * attempts is the rough fitness-evaluation budget;
    // each eval is ~1.2ms at 16x16/4 colour, so total is ~ms × that.
    el.textContent = (p.pop * p.gens * p.attempts).toLocaleString();
}

// ── Wire-up ──────────────────────────────────────────────────────────

let tickHandle = null;
function startTimer() {
    stopTimer();
    if (state.running) {
        tickHandle = setInterval(tickAll, state.tickMs);
    }
}
function stopTimer() {
    if (tickHandle) { clearInterval(tickHandle); tickHandle = null; }
}

// Periodic refine timer — independent of the live runner's tick.
// Fires a refine every `state.timerRefineSec` seconds when enabled.
// Skips fires while a hunt is already running so we don't queue
// refines on top of refines.
function startTimerRefine() {
    stopTimerRefine();
    if (!state.timerRefine) return;
    const ms = Math.max(100, state.timerRefineSec * 1000);
    state.timerHandle = setInterval(() => {
        if (state.hunting) return;
        startHunt({ warmStart: true, reason: 'timer' });
    }, ms);
}
function stopTimerRefine() {
    if (state.timerHandle) {
        clearInterval(state.timerHandle);
        state.timerHandle = null;
    }
}

function init() {
    bootstrap();
    paintStrip();

    document.getElementById('hunt-btn').onclick =
        () => startHunt({ warmStart: false });
    document.getElementById('refine-btn').onclick =
        () => startHunt({ warmStart: true });
    document.getElementById('auto-refine-cb').onchange = (e) => {
        state.autoRefine = e.target.checked;
    };
    document.getElementById('run-history-cb').onchange = (e) => {
        state.runHistory = e.target.checked;
    };
    const timerCb  = document.getElementById('timer-refine-cb');
    const timerVal = document.getElementById('timer-refine-sec');
    if (timerCb) {
        timerCb.onchange = (e) => {
            state.timerRefine = e.target.checked;
            if (state.timerRefine) startTimerRefine(); else stopTimerRefine();
        };
    }
    if (timerVal) {
        timerVal.oninput = (e) => {
            const v = parseFloat(e.target.value);
            if (Number.isFinite(v) && v > 0) {
                state.timerRefineSec = v;
                if (state.timerRefine) startTimerRefine();
            }
        };
    }
    // Hunt-tuning inputs — repaint the live cost estimate as the
    // user adjusts. No need to actually save state; readHuntParams
    // re-reads the DOM at launch time.
    ['hunt-pop', 'hunt-gens', 'hunt-mut', 'hunt-attempts'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', paintHuntCost);
    });
    paintHuntCost();
    document.getElementById('seed-btn').onclick = () => {
        const live = liveFrame();
        seed_grid(live.gridA, (Math.random() * 0xffffffff) >>> 0);
        state.tick = 0;
        document.getElementById('tick-count').textContent = '0';
        state.activityHistory = [];
        state.gridHashes = [];
        state.staticDwellTicks = 0;
        state.periodicDwell = 0;
        paintStrip();
    };
    document.getElementById('palette-btn').onclick = () => {
        // Reseed the engine PRNG before invent_palette so successive
        // clicks actually pick different colours.
        seed_prng((Math.random() * 0xffffffff) >>> 0);
        liveFrame().palette = invent_palette();
        paintStrip();
    };
    document.getElementById('pause-btn').onclick = () => {
        state.running = !state.running;
        document.getElementById('pause-btn').textContent =
            state.running ? 'Pause' : 'Run';
        if (state.running) startTimer(); else stopTimer();
    };
    document.getElementById('step-btn').onclick = () => {
        if (state.running) state.running = false;
        document.getElementById('pause-btn').textContent = 'Run';
        stopTimer();
        tickAll();
    };
    document.getElementById('clear-history-btn').onclick = () => {
        const live = liveFrame();
        state.frames = [live];
        paintStrip();
    };
    const slider = document.getElementById('tick-slider');
    const label  = document.getElementById('tick-label');
    slider.oninput = () => {
        state.tickMs = parseInt(slider.value, 10);
        label.textContent = `${state.tickMs} ms`;
        if (state.running) startTimer();
    };

    startTimer();
    updateActivityDisplay();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

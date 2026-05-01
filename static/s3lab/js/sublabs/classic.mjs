// main.mjs — UI bootstrap, render loop, GPIO panel, binding editor.
//
// All compute is in engine.mjs / hunt.mjs / worker.mjs. This file is
// just the wiring.

import {
    K, GBYTES, PAL_BYTES, GRID_W, GRID_H, TAIL_MAGIC, TAIL_BYTES,
    seed_prng, prng,
    seed_grid, step_grid, g_get,
    ansi256_to_css, ansi256_to_rgb,
    encode_tail, decode_tail,
    random_genome, identity_genome, invent_palette,
} from '../engine.mjs';

// ── State ─────────────────────────────────────────────────────────────

const state = {
    genome:    random_genome(),
    palette:   new Uint8Array([21, 196, 226, 46]),  // arbitrary defaults
    gridA:     new Uint8Array(GRID_W * GRID_H),
    gridB:     new Uint8Array(GRID_W * GRID_H),
    cur:       null,    // alias of gridA or gridB
    nxt:       null,
    bindings:  [],      // outputs: {cell_x, cell_y, gpio_pin, state_mask}
    inputs:    [],      // inputs:  {gpio_pin, cell_x, cell_y, low_state, high_state, level}
    tickMs:    300,
    running:   true,
    tick:      0,
    history:   {},      // gpio_pin -> Array<0|1> (last N levels)
    historyN:  120,
    hunting:   false,
    huntKind:  '',      // 'fresh' or 'refine' (warm-start)

    // Activity tracking
    activityHistory: [],     // last N tick activity ratios (0..1)
    activityHistoryN: 60,
    staticDwellTicks: 0,     // consecutive ticks with MA below floor
    autoRefine: true,
    lastTickActivity: 0,
    // Periodicity detection — if the grid revisits a recent state, the
    // CA is stuck in a short cycle even if activity > 0.
    gridHashes: [],          // last N grid hashes
    gridHashN: 16,
    periodicDwell: 0,        // consecutive ticks "inside a short cycle"
};

// Auto-refine thresholds.
//   ACT_FLOOR_RUN: any MA below this counts as stalled. Raised to 5%
//     so we don't tolerate "barely-alive" steady-states that visually
//     look frozen — class-4 should hover near 10-15% on a healthy run.
//   STATIC_DWELL_LIMIT: consecutive stalled ticks before refine fires.
//     ~4.5 s at 300 ms, fast enough to feel responsive.
//   PERIODIC_DWELL_LIMIT: consecutive ticks the grid has been in a
//     ≤16-period cycle before refine fires. A short cycle is by
//     definition visually frozen; trigger faster than the activity
//     path.
const ACT_FLOOR_RUN         = 0.05;
const STATIC_DWELL_LIMIT    = 15;
const PERIODIC_DWELL_LIMIT  = 8;

// Default bindings: edges of the grid as outputs, interior as inputs.
// The mental model is "inputs re-seed the centre, outputs read the
// long-term effect at the edges".
//
// Pin budget on a SuperMini: TFT eats 4–7 + 11–12, USB takes 19/20,
// BOOT is 0 — leaving exactly 9 free pins (1, 2, 3, 8, 9, 10, 13, 14,
// 21). The lab default fills that budget exactly so anything you
// design here is physically buildable: 5 outputs sample both vertical
// edges, 4 inputs form a 2×2 grid in the interior.
//
// state_mask = 0x8 ⇒ output HIGH when cell == state 3, so each edge
// pin fires only when a state-3 wave reaches it. Inputs use
// low=0 / high=3 so a click on HIGH injects a strong stimulus the
// outputs can detect propagating outward.
state.bindings = [
    // Left edge (x=0), three sample rows
    { cell_x: 0, cell_y:  0, gpio_pin:  1, state_mask: 0x8 },
    { cell_x: 0, cell_y:  6, gpio_pin:  2, state_mask: 0x8 },
    { cell_x: 0, cell_y: 12, gpio_pin:  3, state_mask: 0x8 },
    // Right edge (x=13), two sample rows
    { cell_x: 13, cell_y:  3, gpio_pin:  8, state_mask: 0x8 },
    { cell_x: 13, cell_y:  9, gpio_pin:  9, state_mask: 0x8 },
];
state.inputs = [
    // 2×2 grid in the interior, evenly placed away from the edges
    { gpio_pin: 10, cell_x:  3, cell_y:  3, low_state: 0, high_state: 3, level: 1 },
    { gpio_pin: 13, cell_x: 10, cell_y:  3, low_state: 0, high_state: 3, level: 1 },
    { gpio_pin: 14, cell_x:  3, cell_y: 10, low_state: 0, high_state: 3, level: 1 },
    { gpio_pin: 21, cell_x: 10, cell_y: 10, low_state: 0, high_state: 3, level: 1 },
];

state.cur = state.gridA;
state.nxt = state.gridB;

seed_prng(Date.now() & 0xffffffff);
seed_grid(state.cur, prng());

// ── DOM refs ──────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const tftCanvas    = $('tft');
const tftCtx       = tftCanvas.getContext('2d');
const wfCanvas     = $('waveform');
const wfCtx        = wfCanvas.getContext('2d');
const actSparkCv   = $('act-spark');
const actSparkCtx  = actSparkCv.getContext('2d');
const actNowEl     = $('act-now');
const actMaEl      = $('act-ma');
const actDwellEl   = $('act-dwell');
const huntStatus   = $('hunt-status');
const huntProgress = $('hunt-progress');
const huntBtn      = $('hunt-btn');
const refineBtn    = $('refine-btn');
const autoRefineCb = $('auto-refine-cb');
const tickSlider   = $('tick-slider');
const tickLabel    = $('tick-label');
const pauseBtn     = $('pause-btn');
const stepBtn      = $('step-btn');
const seedBtn      = $('seed-btn');
const downloadGen  = $('download-genome');
const uploadGen    = $('upload-genome');
const downloadMap  = $('download-gpio-map');
const sendAutoBtn  = $('send-to-automaton');
const sendStatus   = $('send-status');
const outputList   = $('output-bindings');
const inputList    = $('input-bindings');
const addOutBtn    = $('add-output');
const addInBtn     = $('add-input');
const tftGenome    = $('tft-genome-info');

// ── TFT render ────────────────────────────────────────────────────────
//
// Faked ST7735S 80×160 landscape, scaled 4x for visibility (640×320).
// 16×16 grid at 4px cell = 64×64 logical (was 14×14 at 5px = 70×70).
// Rest of the canvas is "off-display" framing: bezel for the LCD.

const TFT_W   = 160;       // logical
const TFT_H   = 80;        // logical
const TFT_PX  = 4;         // px per logical pixel
const CELL    = 4;         // logical cell width (4px × 16 cells = 64 logical)
const XPAD    = 46;        // logical — centres the 64+stagger grid in 160 wide
const YPAD    = 7;         // logical — centres the 64-tall grid in 80 tall

function logicalToCanvas(lx, ly) {
    return [lx * TFT_PX, ly * TFT_PX];
}

function rgbCss(idx) {
    return ansi256_to_css(idx);
}

function drawTftBackground() {
    // Black bezel (LCD off pixels).
    tftCtx.fillStyle = '#000';
    tftCtx.fillRect(0, 0, TFT_W * TFT_PX, TFT_H * TFT_PX);
}

function drawCell(x, y, c) {
    const px = XPAD + x * CELL + ((y & 1) ? ((CELL / 2) | 0) : 0);
    const py = YPAD + y * CELL;
    const [cx, cy] = logicalToCanvas(px, py);
    tftCtx.fillStyle = rgbCss(state.palette[c]);
    tftCtx.fillRect(cx, cy, CELL * TFT_PX, CELL * TFT_PX);
}

function renderFull(grid) {
    drawTftBackground();
    for (let y = 0; y < GRID_H; y++)
        for (let x = 0; x < GRID_W; x++)
            drawCell(x, y, grid[y * GRID_W + x]);
}

function renderDiff(prev, cur) {
    for (let y = 0; y < GRID_H; y++)
        for (let x = 0; x < GRID_W; x++)
            if (prev[y * GRID_W + x] !== cur[y * GRID_W + x])
                drawCell(x, y, cur[y * GRID_W + x]);
}

function drawHuntBanner(gen, total, best, mean) {
    // Black header strip
    tftCtx.fillStyle = '#000';
    tftCtx.fillRect(0, 0, TFT_W * TFT_PX, 26 * TFT_PX);
    tftCtx.fillStyle = '#fff';
    tftCtx.font = `${10 * TFT_PX / 2}px ui-monospace, Menlo, monospace`;
    tftCtx.textBaseline = 'top';
    tftCtx.fillText('HUNTING',           2 * TFT_PX,  2 * TFT_PX);
    tftCtx.fillText(`gen ${gen}/${total}`, 2 * TFT_PX, 14 * TFT_PX);
    tftCtx.fillText(`best ${best.toFixed(2)}`, 80 * TFT_PX, 2 * TFT_PX);
    tftCtx.fillText(`mean ${mean.toFixed(2)}`, 80 * TFT_PX, 14 * TFT_PX);

    // Bottom progress bar
    const barY = 70 * TFT_PX, barH = 6 * TFT_PX;
    const w = (TFT_W * TFT_PX * gen) / total;
    tftCtx.fillStyle = '#000';
    tftCtx.fillRect(0, barY, TFT_W * TFT_PX, barH);
    tftCtx.fillStyle = best > 4.0 ? '#3fb950'
                     : best > 3.0 ? '#d29922'
                     :              '#f85149';
    tftCtx.fillRect(0, barY, w, barH);
}

// ── GPIO logic ────────────────────────────────────────────────────────

function levelFor(b, cellValue) {
    return (b.state_mask >> cellValue) & 1;
}

function applyOutputBindings(grid) {
    for (let i = 0; i < state.bindings.length; i++) {
        const b = state.bindings[i];
        const v = grid[b.cell_y * GRID_W + b.cell_x];
        const level = levelFor(b, v);
        recordHistory(b.gpio_pin, level);
        const led = document.getElementById(`led-out-${i}`);
        if (led) led.className = `bled ${level ? 'high' : 'low'}`;
    }
}

function applyInputBindings(grid) {
    for (const b of state.inputs) {
        // b.level is 0 or 1, set by the user click.
        grid[b.cell_y * GRID_W + b.cell_x] =
            b.level ? b.high_state : b.low_state;
        recordHistory(b.gpio_pin, b.level);
    }
}

function recordHistory(pin, level) {
    if (!state.history[pin]) state.history[pin] = [];
    const h = state.history[pin];
    h.push(level);
    if (h.length > state.historyN) h.shift();
}

// ── Waveform render ─────────────────────────────────────────────────

function resizeWaveformCanvas() {
    const allPins = new Set([
        ...state.bindings.map(b => b.gpio_pin),
        ...state.inputs.map(b => b.gpio_pin),
    ]);
    const rowH    = 22;
    const minH    = 80;
    const targetH = Math.max(minH, allPins.size * rowH);
    if (wfCanvas.height !== targetH) {
        wfCanvas.height = targetH;
        wfCanvas.style.height = `${targetH}px`;
    }
}

function drawWaveform() {
    const W = wfCanvas.width;
    const H = wfCanvas.height;
    wfCtx.fillStyle = '#0d1117';
    wfCtx.fillRect(0, 0, W, H);

    const allPins = [...new Set([
        ...state.bindings.map(b => b.gpio_pin),
        ...state.inputs.map(b => b.gpio_pin),
    ])].sort((a, b) => a - b);

    if (allPins.length === 0) return;

    const rowH = Math.max(14, (H / allPins.length) | 0);
    const labelW = 56;
    const plotW = W - labelW - 10;

    wfCtx.font = '10px ui-monospace, Menlo, monospace';
    wfCtx.textBaseline = 'middle';

    for (let i = 0; i < allPins.length; i++) {
        const pin = allPins[i];
        const y0 = i * rowH;
        const mid = y0 + rowH / 2;

        const isInput = state.inputs.some(b => b.gpio_pin === pin);
        wfCtx.fillStyle = isInput ? '#58a6ff' : '#3fb950';
        wfCtx.fillText(`${isInput ? 'in ' : 'out'} ${pin}`, 4, mid);

        // Trace
        wfCtx.strokeStyle = isInput ? '#58a6ff' : '#3fb950';
        wfCtx.lineWidth = 1.4;
        wfCtx.beginPath();
        const h = state.history[pin] || [];
        const dx = plotW / state.historyN;
        const yHi = y0 + 3;
        const yLo = y0 + rowH - 4;
        for (let k = 0; k < h.length; k++) {
            const x = labelW + k * dx;
            const y = h[k] ? yHi : yLo;
            if (k === 0) wfCtx.moveTo(x, y);
            else {
                // Vertical edge if level changed
                const yPrev = h[k - 1] ? yHi : yLo;
                if (yPrev !== y) wfCtx.lineTo(x, yPrev);
                wfCtx.lineTo(x, y);
            }
        }
        wfCtx.stroke();

        // Baseline
        wfCtx.strokeStyle = '#21262d';
        wfCtx.beginPath();
        wfCtx.moveTo(labelW, yLo);
        wfCtx.lineTo(labelW + plotW, yLo);
        wfCtx.stroke();
    }
}

// ── Activity tracking ─────────────────────────────────────────────────

function recordActivity(ratio) {
    state.lastTickActivity = ratio;
    const h = state.activityHistory;
    h.push(ratio);
    if (h.length > state.activityHistoryN) h.shift();
}

function activityMA() {
    const h = state.activityHistory;
    if (h.length === 0) return 0;
    let s = 0;
    for (let i = 0; i < h.length; i++) s += h[i];
    return s / h.length;
}

// FNV-1a 32-bit hash over the grid bytes. ~1 µs per call on the S3
// grid (196 cells); cheap enough to call every tick.
function gridHash(g) {
    let h = 0x811c9dc5 >>> 0;
    for (let i = 0; i < g.length; i++) {
        h ^= g[i];
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h;
}

// Returns the cycle length if the grid is currently stuck in a cycle
// of period ≤ gridHashN, otherwise 0. Records the new hash.
function checkPeriodicity(g) {
    const h = gridHash(g);
    const buf = state.gridHashes;
    let period = 0;
    for (let i = 0; i < buf.length; i++) {
        if (buf[i] === h) {
            period = buf.length - i;   // distance from now
            break;
        }
    }
    buf.push(h);
    if (buf.length > state.gridHashN) buf.shift();
    return period;
}

function drawActivitySparkline() {
    const W = actSparkCv.width;
    const H = actSparkCv.height;
    actSparkCtx.fillStyle = '#0d1117';
    actSparkCtx.fillRect(0, 0, W, H);

    // 12% reference line — peak of the fitness tent.
    const peakY = H - (0.12 / 0.6) * H;
    actSparkCtx.strokeStyle = '#21262d';
    actSparkCtx.beginPath();
    actSparkCtx.moveTo(0, peakY);
    actSparkCtx.lineTo(W, peakY);
    actSparkCtx.stroke();

    // Floor reference line — auto-refine triggers below this.
    const floorY = H - (ACT_FLOOR_RUN / 0.6) * H;
    actSparkCtx.strokeStyle = '#3a1f1f';
    actSparkCtx.beginPath();
    actSparkCtx.moveTo(0, floorY);
    actSparkCtx.lineTo(W, floorY);
    actSparkCtx.stroke();

    // Activity trace
    const h = state.activityHistory;
    if (h.length < 2) return;
    actSparkCtx.strokeStyle = '#3fb950';
    actSparkCtx.lineWidth = 1.4;
    actSparkCtx.beginPath();
    const dx = W / state.activityHistoryN;
    for (let i = 0; i < h.length; i++) {
        const x = i * dx;
        // 0..0.6 range maps to full height (clip above 0.6).
        const y = H - Math.min(h[i], 0.6) / 0.6 * H;
        if (i === 0) actSparkCtx.moveTo(x, y);
        else         actSparkCtx.lineTo(x, y);
    }
    actSparkCtx.stroke();
}

function updateActivityDisplay() {
    actNowEl.textContent = `${(state.lastTickActivity * 100).toFixed(1)}%`;
    actMaEl.textContent  = `${(activityMA() * 100).toFixed(1)}%`;

    if (state.autoRefine && !state.hunting) {
        if (state.periodicDwell > 0) {
            const remaining = PERIODIC_DWELL_LIMIT - state.periodicDwell;
            actDwellEl.textContent = remaining > 0
                ? `· cycle ≤${state.gridHashN} ticks for ${state.periodicDwell} → refine in ${remaining}`
                : '· refining (periodic)…';
            actDwellEl.classList.add('warning');
        } else if (state.staticDwellTicks > 0) {
            const remaining = STATIC_DWELL_LIMIT - state.staticDwellTicks;
            actDwellEl.textContent = remaining > 0
                ? `· static for ${state.staticDwellTicks} ticks → refine in ${remaining}`
                : '· refining (stalled)…';
            actDwellEl.classList.add('warning');
        } else {
            actDwellEl.textContent = '';
            actDwellEl.classList.remove('warning');
        }
    } else {
        actDwellEl.textContent = '';
        actDwellEl.classList.remove('warning');
    }
    drawActivitySparkline();
}

function checkAutoRefine(periodFound) {
    if (!state.autoRefine) return;
    if (state.hunting) return;
    if (state.activityHistory.length < state.activityHistoryN) return;

    // Periodicity path — fires faster than the activity path because a
    // short cycle is, by definition, visually frozen even at non-zero
    // activity.
    if (periodFound > 0) {
        state.periodicDwell++;
        if (state.periodicDwell > PERIODIC_DWELL_LIMIT) {
            state.periodicDwell = 0;
            state.staticDwellTicks = 0;
            startHunt({ warmStart: true,
                        reason: `auto-refine: stuck in ${periodFound}-tick cycle` });
            return;
        }
    } else {
        state.periodicDwell = 0;
    }

    const ma = activityMA();
    if (ma < ACT_FLOOR_RUN) {
        state.staticDwellTicks++;
        if (state.staticDwellTicks > STATIC_DWELL_LIMIT) {
            state.staticDwellTicks = 0;
            startHunt({ warmStart: true,
                        reason: `auto-refine: stalled (${(ma * 100).toFixed(1)}%)` });
        }
    } else {
        state.staticDwellTicks = 0;
    }
}

// ── Tick loop ─────────────────────────────────────────────────────────

let lastTickAt = 0;

function rafLoop(now) {
    requestAnimationFrame(rafLoop);
    if (state.hunting) return;
    if (!state.running) return;
    if (now - lastTickAt < state.tickMs) return;
    lastTickAt = now;
    doTick();
}

function doTick() {
    applyInputBindings(state.cur);
    step_grid(state.genome, state.cur, state.nxt);

    let changed = 0;
    for (let i = 0; i < GRID_W * GRID_H; i++)
        if (state.cur[i] !== state.nxt[i]) changed++;
    recordActivity(changed / (GRID_W * GRID_H));

    renderDiff(state.cur, state.nxt);
    applyOutputBindings(state.nxt);
    drawWaveform();
    [state.cur, state.nxt] = [state.nxt, state.cur];

    // Periodicity check on the *new* current state (post-swap).
    const period = checkPeriodicity(state.cur);

    state.tick++;
    $('tick-count').textContent = state.tick;

    updateActivityDisplay();
    checkAutoRefine(period);
}

// ── Hunt control ─────────────────────────────────────────────────────

let huntWorker = null;
let huntStartedAt = 0;
let currentAttempt = 0;
let totalAttempts = 0;

function startHunt({ warmStart = false, reason = '' } = {}) {
    if (state.hunting) return;
    state.hunting = true;
    state.huntKind = warmStart ? 'refine' : 'fresh';
    huntStartedAt = performance.now();
    huntBtn.disabled    = true;
    refineBtn.disabled  = true;
    const labelPrefix = warmStart ? 'refining' : 'hunting';
    huntStatus.textContent =
        reason ? `${labelPrefix} (${reason}) — starting…`
               : `${labelPrefix} — starting…`;

    huntWorker = new Worker(
        new URL('../worker.mjs', import.meta.url),
        { type: 'module' }
    );
    huntWorker.onmessage = (e) => {
        const m = e.data;
        if (m.type === 'attempt') {
            currentAttempt = m.n;
            totalAttempts  = m.total;
        } else if (m.type === 'progress') {
            huntStatus.textContent =
                `${state.huntKind === 'refine' ? 'refining' : 'hunting'} ` +
                `[${currentAttempt}/${totalAttempts}]  ` +
                `gen ${m.gen}/${m.total}  best ${m.best.toFixed(2)}  ` +
                `mean ${m.mean.toFixed(2)}  tail ${m.tail.toFixed(3)}`;
            huntProgress.value = m.gen / m.total;
            // Live palette feedback so the on-canvas hunt banner shows
            // the colour the genome will eventually inherit.
            state.palette = new Uint8Array(m.palette);
            drawHuntBanner(m.gen, m.total, m.best, m.mean);
        } else if (m.type === 'verify') {
            const pct = (m.activity_ma * 100).toFixed(1);
            if (!m.accepted) {
                huntStatus.textContent =
                    `[${currentAttempt}/${totalAttempts}] rejected — ${m.reason} ` +
                    `(${pct}%); retrying…`;
            } else {
                huntStatus.textContent =
                    `[${currentAttempt}/${totalAttempts}] accepted — ${pct}% activity`;
            }
        } else if (m.type === 'done') {
            state.genome  = new Uint8Array(m.genome);
            state.palette = new Uint8Array(m.palette);
            state.hunting = false;
            huntBtn.disabled    = false;
            refineBtn.disabled  = false;

            const elapsed = (performance.now() - huntStartedAt) / 1000;
            const pct = (m.activity_ma * 100).toFixed(1);
            const verdict = m.accepted ? 'accepted' : `forced (no candidate passed)`;
            huntStatus.textContent =
                `done — fitness ${m.fitness.toFixed(2)}  ` +
                `activity ${pct}%  attempts ${m.attempts}  ` +
                `${elapsed.toFixed(1)} s  · ${verdict}`;
            huntProgress.value = 1.0;

            // Reset run-time state so post-hunt live display is fresh.
            seed_grid(state.cur, prng());
            renderFull(state.cur);
            applyOutputBindings(state.cur);
            state.activityHistory  = [];
            state.gridHashes       = [];
            state.staticDwellTicks = 0;
            state.periodicDwell    = 0;
            state.lastTickActivity = 0;
            updateGenomeInfo();
            updateActivityDisplay();
            huntWorker.terminate();
            huntWorker = null;
        }
    };

    huntWorker.postMessage({
        type:      'run_hunt',
        prng_seed: (Math.random() * 0xffffffff) >>> 0,
        grid_seed: (Math.random() * 0xffffffff) >>> 0,
        // Warm-start: hand the worker the current genome+palette + bump
        // the initial mutation rate so the GA explores neighbours
        // rather than re-finding the same local optimum.
        seedGenome:          warmStart ? state.genome.buffer.slice(0)  : null,
        seedPalette:         warmStart ? state.palette.buffer.slice(0) : null,
        initialMutationRate: warmStart ? 0.10 : 0.05,
        maxAttempts:         4,
        // Verification floor 5% to match the run-time stall floor —
        // a winner that barely clears 3% on the verify run will
        // almost certainly trigger the run-time stall path within
        // seconds. Ceiling 50% rejects pure-chaos rulesets.
        activityFloor:       0.05,
        activityCeil:        0.50,
    });
}

// ── File I/O ─────────────────────────────────────────────────────────

function downloadBytes(filename, bytes, mime = 'application/octet-stream') {
    const blob = new Blob([bytes], { type: mime });
    const url  = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

function downloadGenome() {
    const bytes = encode_tail(state.palette, state.genome);
    downloadBytes('genome.bin', bytes);
}

// Read Django's csrftoken cookie — set when the page was rendered. The
// import endpoint is POST + login_required, so CSRF must be present.
function getCsrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : '';
}

async function sendToAutomaton() {
    const bytes = encode_tail(state.palette, state.genome);
    sendAutoBtn.disabled = true;
    sendStatus.textContent = 'sending…';
    try {
        const resp = await fetch('/automaton/import-from-s3lab/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/octet-stream',
                'X-CSRFToken':  getCsrfToken(),
            },
            body: bytes,
        });
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(`HTTP ${resp.status}: ${txt}`);
        }
        const j = await resp.json();
        const tag = j.duplicate ? '(already imported)' : 'imported';
        sendStatus.innerHTML = `${tag} → <a href="${j.url}" target="_blank" style="color:#7ee787;">${j.name}</a> · ${j.n_explicit.toLocaleString()} rules`;
    } catch (e) {
        sendStatus.textContent = 'error: ' + e.message;
    } finally {
        sendAutoBtn.disabled = false;
    }
}

function downloadGpioMap() {
    const lines = [
        '# CA cell <-> GPIO bindings.',
        '# Generated by /s3lab/.',
        '#',
        '# Output: cell_x,cell_y,gpio_pin,state_mask',
        '# Input : input,gpio_pin,cell_x,cell_y,low_state,high_state',
        '',
    ];
    for (const b of state.bindings) {
        lines.push(`${b.cell_x},${b.cell_y},${b.gpio_pin},0x${b.state_mask.toString(16).toUpperCase()}`);
    }
    if (state.inputs.length) {
        lines.push('');
        for (const b of state.inputs) {
            lines.push(`input,${b.gpio_pin},${b.cell_x},${b.cell_y},${b.low_state},${b.high_state}`);
        }
    }
    const text = lines.join('\n') + '\n';
    downloadBytes('gpio_map.txt', new TextEncoder().encode(text), 'text/plain');
}

function applyGenomeBytes(bytes, label) {
    // Shared apply path for any genome.bin source — file upload, query
    // param fetch, paste, etc. Keeps the post-decode side-effects in
    // one place so future loaders all behave the same.
    const { palette, genome } = decode_tail(bytes);
    state.palette = palette;
    state.genome  = genome;
    seed_grid(state.cur, prng());
    renderFull(state.cur);
    updateGenomeInfo();
    huntStatus.textContent = `loaded ${label} (${bytes.length} B)`;
}

async function uploadGenome(file) {
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    try {
        applyGenomeBytes(bytes, file.name);
    } catch (err) {
        huntStatus.textContent = `upload failed: ${err.message}`;
    }
}

// On page load, honour ?from=<automaton-sim-slug> by fetching that
// simulation's genome.bin and applying it. Lets Automaton's "→ s3lab"
// button drop you into the lab with the chosen ruleset preloaded.
async function loadGenomeFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const fromSlug = params.get('from');
    if (!fromSlug) return;
    const url = `/automaton/${encodeURIComponent(fromSlug)}/genome.bin`;
    huntStatus.textContent = `fetching ${fromSlug}…`;
    try {
        const resp = await fetch(url, { credentials: 'same-origin' });
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(`HTTP ${resp.status}: ${txt}`);
        }
        const buf = await resp.arrayBuffer();
        applyGenomeBytes(new Uint8Array(buf), `automaton:${fromSlug}`);
    } catch (err) {
        huntStatus.textContent = `import failed: ${err.message}`;
    }
}

function updateGenomeInfo() {
    let nz = 0;
    for (let i = 0; i < GBYTES; i++) if (state.genome[i] !== 0) nz++;
    const palText = Array.from(state.palette).join(' ');
    tftGenome.textContent =
        `genome: ${GBYTES} B (${((nz / GBYTES) * 100).toFixed(0)}% nonzero) · pal=[${palText}]`;
}

// ── Binding editor ──────────────────────────────────────────────────

function renderBindingLists() {
    resizeWaveformCanvas();
    outputList.innerHTML = '';
    for (let i = 0; i < state.bindings.length; i++) {
        const b = state.bindings[i];
        const li = document.createElement('li');
        li.className = 'binding-row';
        li.innerHTML = `
          <span class="bcell">cell (${b.cell_x},${b.cell_y})</span>
          <span class="barrow">→</span>
          <span class="bpin">GPIO ${b.gpio_pin}</span>
          <span class="bled low" id="led-out-${i}"></span>
          <span class="bmask">mask 0x${b.state_mask.toString(16).toUpperCase()}</span>
          <button data-i="${i}" data-kind="out" class="brm">×</button>
        `;
        outputList.appendChild(li);
    }

    inputList.innerHTML = '';
    for (let i = 0; i < state.inputs.length; i++) {
        const b = state.inputs[i];
        const isHigh = b.level === 1;
        const li = document.createElement('li');
        li.className = 'binding-row';
        li.innerHTML = `
          <button class="bbtn ${isHigh ? 'high' : 'low'}"
                  data-i="${i}" data-kind="toggle">${isHigh ? 'HIGH' : 'LOW'}</button>
          <span class="bpin">GPIO ${b.gpio_pin}</span>
          <span class="barrow">→</span>
          <span class="bcell">cell (${b.cell_x},${b.cell_y})</span>
          <span class="bmask">low=${b.low_state} high=${b.high_state}</span>
          <button data-i="${i}" data-kind="in" class="brm">×</button>
        `;
        inputList.appendChild(li);
    }
}

function bindBindingListClicks() {
    outputList.addEventListener('click', (e) => {
        const btn = e.target.closest('button.brm');
        if (!btn) return;
        const i = parseInt(btn.dataset.i, 10);
        state.bindings.splice(i, 1);
        renderBindingLists();
    });
    inputList.addEventListener('click', (e) => {
        const t = e.target.closest('button');
        if (!t) return;
        const i = parseInt(t.dataset.i, 10);
        if (t.dataset.kind === 'in') {
            state.inputs.splice(i, 1);
        } else if (t.dataset.kind === 'toggle') {
            state.inputs[i].level = state.inputs[i].level ? 0 : 1;
        }
        renderBindingLists();
    });
}

function showAddDialog(kind) {
    if (kind === 'out') {
        const x = parseInt(prompt('cell_x (0–13)?', '0'),  10);
        const y = parseInt(prompt('cell_y (0–13)?', '0'),  10);
        const p = parseInt(prompt('gpio_pin?',      '1'),  10);
        const m = parseInt(prompt('state_mask (0x0–0xF)?', '0x8'), 16) || 0;
        if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(p)) {
            state.bindings.push({ cell_x: x, cell_y: y, gpio_pin: p, state_mask: m & 0xF });
            renderBindingLists();
        }
    } else {
        const p  = parseInt(prompt('gpio_pin?',  '9'), 10);
        const x  = parseInt(prompt('cell_x?',    '0'), 10);
        const y  = parseInt(prompt('cell_y?',    '0'), 10);
        const lo = parseInt(prompt('low_state (0–3)?',  '0'), 10);
        const hi = parseInt(prompt('high_state (0–3)?', '3'), 10);
        if ([p, x, y, lo, hi].every(Number.isFinite)) {
            state.inputs.push({
                gpio_pin: p, cell_x: x, cell_y: y,
                low_state: lo & 3, high_state: hi & 3, level: 1,
            });
            renderBindingLists();
        }
    }
}

// ── Wire up ──────────────────────────────────────────────────────────

huntBtn.addEventListener('click',   () => startHunt());
refineBtn.addEventListener('click', () => startHunt({ warmStart: true,
                                                      reason: 'manual refine' }));

autoRefineCb.addEventListener('change', () => {
    state.autoRefine = autoRefineCb.checked;
    state.staticDwellTicks = 0;
    updateActivityDisplay();
});

pauseBtn.addEventListener('click', () => {
    state.running = !state.running;
    pauseBtn.textContent = state.running ? 'Pause' : 'Resume';
});

stepBtn.addEventListener('click', () => {
    state.running = false;
    pauseBtn.textContent = 'Resume';
    doTick();
});

seedBtn.addEventListener('click', () => {
    seed_grid(state.cur, prng());
    state.tick = 0;
    renderFull(state.cur);
    drawWaveform();
});

tickSlider.addEventListener('input', () => {
    state.tickMs = parseInt(tickSlider.value, 10);
    tickLabel.textContent = `${state.tickMs} ms`;
});

downloadGen.addEventListener('click', downloadGenome);
downloadMap.addEventListener('click', downloadGpioMap);
sendAutoBtn.addEventListener('click', sendToAutomaton);

uploadGen.addEventListener('change', () => {
    if (uploadGen.files && uploadGen.files[0]) uploadGenome(uploadGen.files[0]);
});

addOutBtn.addEventListener('click', () => showAddDialog('out'));
addInBtn .addEventListener('click', () => showAddDialog('in'));

bindBindingListClicks();
renderBindingLists();
renderFull(state.cur);
applyOutputBindings(state.cur);
drawWaveform();
updateGenomeInfo();
updateActivityDisplay();
tickLabel.textContent = `${state.tickMs} ms`;
autoRefineCb.checked = state.autoRefine;
loadGenomeFromQuery();
requestAnimationFrame(rafLoop);

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
} from './engine.mjs';

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
};

// Default bindings — match the C sketch's default /gpio_map.txt.
state.bindings = [
    { cell_x: 3, cell_y: 5, gpio_pin: 1, state_mask: 0x8 },
    { cell_x: 4, cell_y: 5, gpio_pin: 2, state_mask: 0x8 },
    { cell_x: 5, cell_y: 5, gpio_pin: 3, state_mask: 0x8 },
    { cell_x: 6, cell_y: 5, gpio_pin: 8, state_mask: 0x8 },
];
state.inputs = [
    { gpio_pin: 9,  cell_x: 0,  cell_y: 0,  low_state: 0, high_state: 3, level: 1 },
    { gpio_pin: 10, cell_x: 13, cell_y: 13, low_state: 0, high_state: 3, level: 1 },
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
const huntStatus   = $('hunt-status');
const huntProgress = $('hunt-progress');
const huntBtn      = $('hunt-btn');
const tickSlider   = $('tick-slider');
const tickLabel    = $('tick-label');
const pauseBtn     = $('pause-btn');
const stepBtn      = $('step-btn');
const seedBtn      = $('seed-btn');
const downloadGen  = $('download-genome');
const uploadGen    = $('upload-genome');
const downloadMap  = $('download-gpio-map');
const outputList   = $('output-bindings');
const inputList    = $('input-bindings');
const addOutBtn    = $('add-output');
const addInBtn     = $('add-input');
const tftGenome    = $('tft-genome-info');

// ── TFT render ────────────────────────────────────────────────────────
//
// Faked ST7735S 80×160 landscape, scaled 4x for visibility (640×320).
// 14×14 grid at 5px cell = 70×70 logical, scaled = 280×280. Rest of
// the canvas is "off-display" framing: gives the LCD a believable bezel.

const TFT_W   = 160;       // logical
const TFT_H   = 80;        // logical
const TFT_PX  = 4;         // px per logical pixel
const CELL    = 5;         // logical cell width
const XPAD    = 44;        // logical
const YPAD    = 5;         // logical

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
    for (const b of state.bindings) {
        const v = grid[b.cell_y * GRID_W + b.cell_x];
        const level = levelFor(b, v);
        recordHistory(b.gpio_pin, level);
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

    const rowH = Math.min(28, (H / allPins.length) | 0);
    const labelW = 50;
    const plotW = W - labelW - 10;

    wfCtx.font = '11px ui-monospace, Menlo, monospace';
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
        wfCtx.lineWidth = 1.5;
        wfCtx.beginPath();
        const h = state.history[pin] || [];
        const dx = plotW / state.historyN;
        const yHi = y0 + 4;
        const yLo = y0 + rowH - 6;
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
    renderDiff(state.cur, state.nxt);
    applyOutputBindings(state.nxt);
    drawWaveform();
    [state.cur, state.nxt] = [state.nxt, state.cur];
    state.tick++;
    $('tick-count').textContent = state.tick;
}

// ── Hunt control ─────────────────────────────────────────────────────

let huntWorker = null;

function startHunt() {
    if (state.hunting) return;
    state.hunting = true;
    huntBtn.disabled = true;
    huntStatus.textContent = 'starting…';

    huntWorker = new Worker(
        new URL('./worker.mjs', import.meta.url),
        { type: 'module' }
    );
    huntWorker.onmessage = (e) => {
        const m = e.data;
        if (m.type === 'progress') {
            huntStatus.textContent =
                `gen ${m.gen}/${m.total}  best ${m.best.toFixed(2)}  ` +
                `mean ${m.mean.toFixed(2)}  tail ${m.tail.toFixed(3)}`;
            huntProgress.value = m.gen / m.total;
            // Live palette feedback on the TFT banner
            state.palette = new Uint8Array(m.palette);
            drawHuntBanner(m.gen, m.total, m.best, m.mean);
        } else if (m.type === 'done') {
            state.genome  = new Uint8Array(m.genome);
            state.palette = new Uint8Array(m.palette);
            state.hunting = false;
            huntBtn.disabled = false;
            huntStatus.textContent =
                `done — fitness ${m.fitness.toFixed(2)}  ` +
                `elapsed ${(m.elapsed_ms / 1000).toFixed(2)} s`;
            huntProgress.value = 1.0;
            seed_grid(state.cur, prng());
            renderFull(state.cur);
            updateGenomeInfo();
            huntWorker.terminate();
            huntWorker = null;
        }
    };

    huntWorker.postMessage({
        type:      'run_hunt',
        prng_seed: (Math.random() * 0xffffffff) >>> 0,
        grid_seed: (Math.random() * 0xffffffff) >>> 0,
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

async function uploadGenome(file) {
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    try {
        const { palette, genome } = decode_tail(bytes);
        state.palette = palette;
        state.genome  = genome;
        seed_grid(state.cur, prng());
        renderFull(state.cur);
        updateGenomeInfo();
        huntStatus.textContent = `loaded ${file.name} (${bytes.length} B)`;
    } catch (err) {
        huntStatus.textContent = `upload failed: ${err.message}`;
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
    outputList.innerHTML = '';
    for (let i = 0; i < state.bindings.length; i++) {
        const b = state.bindings[i];
        const li = document.createElement('li');
        li.className = 'binding-row';
        li.innerHTML = `
          <span class="bcell">cell (${b.cell_x},${b.cell_y})</span>
          <span class="barrow">→</span>
          <span class="bpin">GPIO ${b.gpio_pin}</span>
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

huntBtn.addEventListener('click', startHunt);

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
tickLabel.textContent = `${state.tickMs} ms`;
requestAnimationFrame(rafLoop);

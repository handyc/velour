"""Emit a self-contained HTML LUT viewer for .lut files.

Single .html with no dependencies.  Load any 16,384-byte K=4 hex CA
rule LUT (mandelhunt output, mondrian_climb output, Taxon DB export,
etc.) via drag-drop or file picker and:

  - Render the LUT-as-image (128×128 with the 4-colour palette)
  - Compute the L0 fixed-point match count (1-tick self-mapping)
  - Step the CA forward on the LUT-as-image (Ouroboros view)
  - Play continuously, see the rule's dynamics on its own substrate

Same hex CA step (K=4, 7→1, pointy-top, row-parity, toroidal) as the
Python and C runtimes — and as the standalone CA-LLM HTML.

  manage.py caformer_emit_lutview --out lutview.html

The output file is small (~12 KB) and runs locally with no network.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

from django.core.management.base import BaseCommand


def _default_mandelbrot_lut() -> bytes:
    """The iconic main Mandelbrot view at (cx=-0.5, cy=0, span=3.0),
    posterised to K=4, returned as 16,384 raw bytes (128×128 cells).

    Used as the default "Hello!" rule loaded into the viewer when
    nobody has dropped a .lut file yet."""
    from loupe.render import mandelbrot_buckets
    arr = mandelbrot_buckets(-0.5, 0.0, 3.0, 128, 128, iter_cap=None)
    import numpy as np
    return bytes(arr.astype(np.uint8).ravel())


def build_lutview_html(default_lut_bytes: bytes = None) -> str:
    """Build the standalone LUT viewer HTML.  If `default_lut_bytes`
    is provided (must be 16,384 bytes), it gets embedded as base64
    and JS loads it automatically on page open so the viewer never
    sits empty."""
    if default_lut_bytes is None:
        b64 = ''
    else:
        if len(default_lut_bytes) != 16384:
            raise ValueError(
                f'default_lut_bytes must be 16,384 B; got {len(default_lut_bytes)}')
        b64 = base64.b64encode(default_lut_bytes).decode('ascii')
    return HTML.replace('__DEFAULT_LUT_B64__', b64)


HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>caformer LUT viewer</title>
<style>
body { background:#0a0e0a; color:#cfe5cf;
       font-family:ui-sans-serif,system-ui,sans-serif;
       margin:0; padding:0; line-height:1.5; }
.wrap { max-width:880px; margin:1rem auto; padding:0 1rem; }
h1 { color:#aaffaa; font-size:1.3rem;
     border-bottom:1px solid #2a6a2a; padding-bottom:4px; }
.lede { color:#88aa88; font-size:0.88rem; }
.drop { border:2px dashed #2a6a2a; background:#050a05;
        padding:18px; margin:16px 0; text-align:center;
        color:#79c0ff; cursor:pointer; transition:background 0.15s; }
.drop.hover { background:#0a2a0a; color:#aaffaa; }
.drop input[type=file] { display:none; }
.row { display:flex; gap:16px; align-items:flex-start;
       margin-top:14px; flex-wrap:wrap; }
.canvases { display:flex; flex-direction:column; gap:8px; }
canvas { background:#000; border:1px solid #2a6a2a;
         image-rendering:pixelated; image-rendering:crisp-edges; }
.controls { background:#050a05; border:1px solid #1a4a1a;
            padding:12px 14px; min-width:240px; }
.controls h3 { color:#aaffaa; font-size:0.95rem; margin:0 0 8px 0; }
button { background:#0a2a0a; color:#aaffaa;
         border:1px solid #2a6a2a; padding:5px 12px;
         font-family:inherit; cursor:pointer; margin:2px 4px 2px 0; }
button:hover { background:#1a4a1a; }
button:disabled { color:#5a8a5a; cursor:default; background:#050a05; }
.stat { font-family:ui-monospace,monospace; font-size:0.85rem;
        color:#cfe5cf; margin:4px 0; }
.stat b { color:#aaffaa; }
.tag { display:inline-block; padding:1px 6px; border-radius:2px;
       font-size:0.72rem; margin-left:6px;
       background:#1a3a1a; color:#aaffaa; }
.tag.warn { background:#3a1a1a; color:#ffaaaa; }
.tag.win  { background:#1a3a5a; color:#79c0ff; }
.palette { display:flex; gap:4px; margin:8px 0; }
.swatch  { width:18px; height:18px; border:1px solid #444; }
.swatch span { display:block; text-align:center; color:#aaa;
               font-size:0.65rem; line-height:18px;
               text-shadow:0 0 2px #000; }
details { margin-top:1rem; }
summary { color:#79c0ff; cursor:pointer; font-size:0.85rem; }
pre { color:#cfe5cf; background:#050a05; padding:10px;
      border:1px solid #1a3a1a; font-size:0.78rem; overflow-x:auto; }
</style>
</head>
<body>
<div class="wrap">
<h1>caformer · LUT viewer</h1>
<p class="lede">Drop a 16,384-byte K=4 hex CA rule LUT (mandelhunt output,
mondrian_climb best.lut, anything 7→1) and watch it run on its own
LUT-as-image — the Ouroboros view.  Strict L0 = every cell stable
after one tick.  Strict ouroboros = sr_strict 1.0 at every depth.</p>

<label class="drop" id="drop">
  click to pick a .lut file, or drop it here
  <input id="file" type="file" accept=".lut,application/octet-stream" />
</label>

<div class="row">
  <div class="canvases">
    <div class="stat">initial (LUT-as-image):</div>
    <canvas id="canvasInit" width="516" height="512"></canvas>
    <div class="stat">current tick:</div>
    <canvas id="canvasCur"  width="516" height="512"></canvas>
  </div>
  <div class="controls">
    <h3>controls</h3>
    <div>
      <button id="btnStep" disabled>step 1 tick</button>
      <button id="btnStep10" disabled>+10</button>
      <button id="btnPlay" disabled>▶ play</button>
      <button id="btnReset" disabled>reset</button>
    </div>
    <div style="margin-top:6px;">
      <button id="btnPalette">🎨 random palette</button>
      <button id="btnPaletteReset">default palette</button>
    </div>
    <div style="margin-top:10px; border-top:1px solid #1a3a1a; padding-top:8px;">
      <div class="stat" style="margin-bottom:4px;">hunt mode:
        <select id="huntMode" style="background:#0a1a2a; color:#79c0ff;
                border:1px solid #1a4a6a; padding:1px 4px; font:inherit;">
          <option value="mandelbrot">Mandelbrot (18% c4)</option>
          <option value="julia">Julia (73% c4)</option>
          <option value="burning_ship">Burning Ship (37% c4)</option>
          <option value="tricorn">Tricorn (47% c4)</option>
        </select>
      </div>
      <button id="btnHunt">▶ fractal search</button>
      <button id="btnHuntOnce">+1 candidate</button>
      <div class="stat" id="statHunt">live search: idle</div>
    </div>
    <div class="stat" id="statFile">no file loaded</div>
    <div class="stat" id="statTick">tick: —</div>
    <div class="stat" id="statL0">L0 match: —</div>
    <div class="stat" id="statSr">SR vs initial: —</div>
    <div class="stat" id="statClass">class hint: —</div>
    <h3 style="margin-top:14px;">palette (K=4)</h3>
    <div class="palette" id="palette"></div>
  </div>
</div>

<details>
  <summary>what the stats mean</summary>
  <pre>L0 match     count of cells that stayed put after ONE tick.
             16384 = strict L0 fixed-point (a true ouroboros).
             &lt;16384 means SOME cells changed.

SR vs init   fraction of cells matching the initial state at the
             current tick.  A strict ouroboros at depth N keeps this
             at 1.0 forever.  A class-4 partial quine oscillates
             near 0.5-0.85.

class hint   rough heuristic from cells-changed-per-tick over the
             last ticks.  Same buckets as caformer/spoeqi:
               1 = dies/stabilises    2 = small structure
               3 = chaotic             4 = persistent localised
</pre>
</details>
</div>

<script>
const SIDE = 128;
const CELLS = SIDE * SIDE;
const DEFAULT_PALETTE = [
    [0,   0,   0],
    [60,  150, 220],
    [240, 180, 60],
    [250, 245, 240],
];
let PALETTE = DEFAULT_PALETTE.map(c => c.slice());

// Build palette swatches.
const palDiv = document.getElementById("palette");
function renderPaletteSwatches() {
    palDiv.innerHTML = "";
    for (let k = 0; k < 4; k++) {
        const [r,g,b] = PALETTE[k];
        const s = document.createElement("div");
        s.className = "swatch";
        s.style.background = `rgb(${r},${g},${b})`;
        const t = document.createElement("span"); t.textContent = k;
        s.appendChild(t); palDiv.appendChild(s);
    }
}
renderPaletteSwatches();

// ── Hex CA step (matches caformer/primitives.py:hex_ca_step) ───────
function hexStep(state, rule, side) {
    const out = new Uint8Array(side * side);
    for (let r = 0; r < side; r++) {
        const even = (r & 1) === 0;
        const up = (r - 1 + side) % side;
        const dn = (r + 1) % side;
        for (let c = 0; c < side; c++) {
            const l = (c - 1 + side) % side;
            const rc = (c + 1) % side;
            const self_ = state[r  * side + c ];
            const nL    = state[r  * side + l ];
            const nR    = state[r  * side + rc];
            const nUpL  = state[up * side + l ];
            const nUp_  = state[up * side + c ];
            const nUpR  = state[up * side + rc];
            const nDnL  = state[dn * side + l ];
            const nDn_  = state[dn * side + c ];
            const nDnR  = state[dn * side + rc];
            const nNW = even ? nUpL : nUp_;
            const nNE = even ? nUp_ : nUpR;
            const nSW = even ? nDnL : nDn_;
            const nSE = even ? nDn_ : nDnR;
            const key = (self_ << 12) | (nNW << 10) | (nNE << 8)
                      | (nR    <<  6) | (nSE <<  4) | (nSW << 2)
                      |  nL;
            out[r * side + c] = rule[key];
        }
    }
    return out;
}

// ── Render a (side, side) K=4 grid into a canvas with hex offset ───
//
// Pointy-top hex: every other ROW is shifted right by half a cell so
// the visual matches the actual CA neighbourhood topology (where odd
// rows' NW/NE/SW/SE neighbours come from a different column than
// even rows').  We use canvas.height to derive the cell size so the
// shift never distorts the vertical proportions; the canvas width
// is chosen wide enough (side * cellPx + cellPx/2) to hold the
// rightmost shifted cell.
function renderGrid(canvas, grid, side) {
    const cellPx = canvas.height / side;
    const shift  = cellPx / 2;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // Batch by colour to minimise fillStyle changes.
    for (let color = 0; color < 4; color++) {
        const [r, g, b] = PALETTE[color];
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        for (let row = 0; row < side; row++) {
            const yo = row * cellPx;
            const xo = (row & 1) ? shift : 0;
            for (let col = 0; col < side; col++) {
                if ((grid[row * side + col] & 3) === color) {
                    ctx.fillRect(xo + col * cellPx, yo, cellPx, cellPx);
                }
            }
        }
    }
}

// ── State ──────────────────────────────────────────────────────────
let rule = null;          // Uint8Array(16384), the LUT bytes
let init = null;          // Uint8Array(16384), the LUT-as-image initial
let cur  = null;          // Uint8Array(16384), current tick state
let tick = 0;
let playTimer = null;
const recentChanges = [];   // rolling window for class hint

const canvasInit = document.getElementById("canvasInit");
const canvasCur  = document.getElementById("canvasCur");
const btnStep    = document.getElementById("btnStep");
const btnStep10  = document.getElementById("btnStep10");
const btnPlay    = document.getElementById("btnPlay");
const btnReset   = document.getElementById("btnReset");

function setEnabled(on) {
    btnStep.disabled = !on; btnStep10.disabled = !on;
    btnPlay.disabled = !on; btnReset.disabled = !on;
}

function loadLUT(bytes) {
    if (bytes.length !== CELLS) {
        alert("expected 16384 bytes, got " + bytes.length);
        return;
    }
    rule = new Uint8Array(CELLS);
    for (let i = 0; i < CELLS; i++) rule[i] = bytes[i] & 3;
    init = new Uint8Array(rule);
    cur  = new Uint8Array(rule);
    tick = 0;
    recentChanges.length = 0;
    renderGrid(canvasInit, init, SIDE);
    renderGrid(canvasCur,  cur,  SIDE);
    updateStats();
    setEnabled(true);
}

function updateStats() {
    document.getElementById("statTick").innerHTML =
        "tick: <b>" + tick + "</b>";
    // L0 = match count after one tick from current cur (without modifying).
    let l0 = 0;
    if (rule) {
        const stepped = hexStep(cur, rule, SIDE);
        for (let i = 0; i < CELLS; i++) if (stepped[i] === cur[i]) l0++;
    }
    const l0pct = (100 * l0 / CELLS).toFixed(3);
    const l0tag = l0 === CELLS ? '<span class="tag win">STRICT</span>'
                : l0 >= 16128  ? '<span class="tag">near</span>'
                : '';
    document.getElementById("statL0").innerHTML =
        "L0 match: <b>" + l0 + "</b>/16384 (" + l0pct + "%)" + l0tag;
    // SR vs initial.
    let sr = 0;
    for (let i = 0; i < CELLS; i++) if (cur[i] === init[i]) sr++;
    const srpct = (100 * sr / CELLS).toFixed(2);
    document.getElementById("statSr").innerHTML =
        "SR vs initial: <b>" + sr + "</b>/16384 (" + srpct + "%)";
    // Class hint from recent activity (cells changing per tick over
    // the rolling window).
    if (recentChanges.length > 0) {
        const mean = recentChanges.reduce((a,b)=>a+b, 0) / recentChanges.length;
        const act = mean / CELLS;
        let cls;
        if (act < 0.02)        cls = "1 (dies/stable)";
        else if (act < 0.08)   cls = "2 (small structure)";
        else if (act > 0.55)   cls = "3 (chaotic)";
        else                   cls = "4 (persistent)";
        document.getElementById("statClass").innerHTML =
            "class hint: <b>" + cls + "</b>" +
            " <span style=color:#5a8a5a>(act " + (act*100).toFixed(2) +
            "%, window " + recentChanges.length + ")</span>";
    }
}

function stepOnce() {
    if (!rule) return;
    const stepped = hexStep(cur, rule, SIDE);
    let n_changed = 0;
    for (let i = 0; i < CELLS; i++) if (stepped[i] !== cur[i]) n_changed++;
    cur = stepped;
    tick++;
    recentChanges.push(n_changed);
    if (recentChanges.length > 16) recentChanges.shift();
    renderGrid(canvasCur, cur, SIDE);
    updateStats();
}

btnStep.addEventListener("click", stepOnce);
btnStep10.addEventListener("click", () => { for (let i = 0; i < 10; i++) stepOnce(); });
btnPlay.addEventListener("click", () => {
    if (playTimer) {
        clearInterval(playTimer); playTimer = null;
        btnPlay.textContent = "▶ play";
    } else {
        btnPlay.textContent = "❚❚ pause";
        playTimer = setInterval(stepOnce, 120);
    }
});
btnReset.addEventListener("click", () => {
    cur = new Uint8Array(init); tick = 0;
    recentChanges.length = 0;
    renderGrid(canvasCur, cur, SIDE);
    updateStats();
});

// ── File loading (picker + drag/drop) ───────────────────────────────
const drop  = document.getElementById("drop");
const fileI = document.getElementById("file");
const statFile = document.getElementById("statFile");

function handleFile(f) {
    statFile.textContent = "loading " + f.name + " (" + f.size + " B)";
    const fr = new FileReader();
    fr.onload = () => {
        const bytes = new Uint8Array(fr.result);
        loadLUT(bytes);
        statFile.innerHTML = "<b>" + f.name + "</b> (" + bytes.length + " B)";
    };
    fr.onerror = () => { statFile.textContent = "read error"; };
    fr.readAsArrayBuffer(f);
}

drop.addEventListener("click", () => fileI.click());
fileI.addEventListener("change", e => {
    if (e.target.files.length) handleFile(e.target.files[0]);
});
drop.addEventListener("dragover", e => {
    e.preventDefault(); drop.classList.add("hover");
});
drop.addEventListener("dragleave", () => drop.classList.remove("hover"));
drop.addEventListener("drop", e => {
    e.preventDefault(); drop.classList.remove("hover");
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});

// ── Palette controls ───────────────────────────────────────────────
function rerenderBoth() {
    if (init) renderGrid(canvasInit, init, SIDE);
    if (cur)  renderGrid(canvasCur,  cur,  SIDE);
}
function randomColour() {
    // Bias toward saturated, distinguishable colours — avoid all-grey.
    const h = Math.random() * 360;
    const s = 60 + Math.random() * 40;       // 60..100% saturation
    const l = 25 + Math.random() * 60;       // 25..85% lightness
    // HSL → RGB
    const c = (1 - Math.abs(2*l/100 - 1)) * s / 100;
    const x = c * (1 - Math.abs(((h/60) % 2) - 1));
    const m = l/100 - c/2;
    let r=0,g=0,b=0;
    if      (h < 60)  { r=c; g=x; }
    else if (h < 120) { r=x; g=c; }
    else if (h < 180) { g=c; b=x; }
    else if (h < 240) { g=x; b=c; }
    else if (h < 300) { r=x; b=c; }
    else              { r=c; b=x; }
    return [Math.round((r+m)*255), Math.round((g+m)*255), Math.round((b+m)*255)];
}
document.getElementById("btnPalette").addEventListener("click", () => {
    PALETTE = [randomColour(), randomColour(), randomColour(), randomColour()];
    renderPaletteSwatches();
    rerenderBoth();
});
document.getElementById("btnPaletteReset").addEventListener("click", () => {
    PALETTE = DEFAULT_PALETTE.map(c => c.slice());
    renderPaletteSwatches();
    rerenderBoth();
});

// ── Embedded mandelhunt: live fractal-quine search in the browser ──
//
// Generates Mandelbrot regions at random walking coordinates, posterises
// to K=4 (16,384 bytes = LUT-as-board), scores each for self-reproduction
// + class-4 + L0 fixed-point match.  When a candidate passes the gate,
// it gets loaded as the live LUT and the viewer auto-plays it for
// `huntDisplayMs` ms before searching for the next one.

const huntDisplayMs = 10000;       // display each find for 10 s
const huntMinSr     = 0.55;         // accept threshold
const huntMaxIters  = 800;          // iter cap per pixel
const MANDEL_SEEDS = [
    [-0.5,    0.0,   3.0],          // main view
    [-0.745,  0.113, 0.05],         // spiral
    [-1.25,   0.0,   0.1],          // left bulb
    [-0.16,   1.04,  0.04],         // elephant valley
    [ 0.272,  0.005, 0.01],         // seahorse valley
];
const JULIA_CS = [
    [-0.4,    0.6],       // rabbit
    [ 0.285,  0.01],      // near tip of cardioid
    [-0.835, -0.2321],    // spiral
    [ 0.45,   0.1428],    // douady rabbit-ish
    [-0.70176,-0.3842],   // dragon
    [ 0.0,    1.0],       // dendrite
    [-1.476,  0.0],       // period-3 along real axis
    [-0.12,   0.74],      // Newton-like spirals
    [-0.75,   0.11],      // near main bulb
];
const BSHIP_CENTER = [-1.75, -0.03];
let huntState = { running: false, walkCx: -0.5, walkCy: 0.0,
                    walkSpan: 3.0, stepsInWalk: 0,
                    nScanned: 0, nAccepted: 0, bestSr: 0,
                    holdUntil: 0, timer: null, mode: 'mandelbrot' };

// Generic per-pixel escape iteration.  mode picks the recurrence.
function escapeAt(zx0, zy0, cx, cy, iterCap, mode) {
    let zx = zx0, zy = zy0, i;
    for (i = 0; i < iterCap; i++) {
        if (zx*zx + zy*zy > 4.0) return i;
        let nx, ny;
        if (mode === 'mandelbrot' || mode === 'julia') {
            nx = zx*zx - zy*zy + cx;
            ny = 2*zx*zy + cy;
        } else if (mode === 'burning_ship') {
            const ax = Math.abs(zx), ay = Math.abs(zy);
            nx = ax*ax - ay*ay + cx;
            ny = 2*ax*ay + cy;
        } else if (mode === 'tricorn') {
            nx = zx*zx - zy*zy + cx;
            ny = -2*zx*zy + cy;
        } else { return iterCap; }
        zx = nx; zy = ny;
    }
    return iterCap;
}
function fractalGrid(params, side, mode) {
    // params: for mandelbrot/burning_ship/tricorn → {cx,cy,span} (c is pixel coord)
    //         for julia → {juliaCx, juliaCy, center_x, center_y, zoom}
    let it = 192, s = params.span || params.zoom || 1.0;
    while (s < 1.0 && it < huntMaxIters) { it += 64; s *= 2; }
    const escape = new Int32Array(side * side);
    if (mode === 'julia') {
        const half = params.zoom / 2;
        const px = params.zoom / side;
        const ox = params.center_x - half;
        const oy = params.center_y - half;
        for (let r = 0; r < side; r++) {
            const y = oy + r * px;
            for (let c = 0; c < side; c++) {
                escape[r * side + c] = escapeAt(
                    ox + c * px, y, params.juliaCx, params.juliaCy, it, mode);
            }
        }
    } else {
        const half = params.span / 2;
        const px = params.span / side;
        const ox = params.cx - half;
        const oy = params.cy - half;
        for (let r = 0; r < side; r++) {
            const y = oy + r * px;
            for (let c = 0; c < side; c++) {
                escape[r * side + c] = escapeAt(0, 0, ox + c * px, y, it, mode);
            }
        }
    }
    return { escape, iterCap: it };
}
function posterise(escape, iterCap) {
    // K=4: in-set → 3, finite split into tertile buckets 0/1/2.
    const finite = [];
    for (let i = 0; i < escape.length; i++) {
        if (escape[i] < iterCap) finite.push(escape[i]);
    }
    let bin1, bin2;
    if (finite.length < 3) { bin1 = iterCap/3; bin2 = 2*iterCap/3; }
    else {
        finite.sort((a,b) => a-b);
        bin1 = finite[finite.length / 3 | 0];
        bin2 = finite[(2*finite.length / 3) | 0];
        if (bin2 <= bin1) bin2 = bin1 + 1;
    }
    const out = new Uint8Array(escape.length);
    for (let i = 0; i < escape.length; i++) {
        const e = escape[i];
        if      (e >= iterCap) out[i] = 3;
        else if (e <  bin1)    out[i] = 0;
        else if (e <  bin2)    out[i] = 1;
        else                   out[i] = 2;
    }
    return out;
}
function srStrict(lut, ticks) {
    let cur = new Uint8Array(lut);
    for (let t = 0; t < ticks; t++) cur = hexStep(cur, lut, SIDE);
    let match = 0;
    for (let i = 0; i < CELLS; i++) if (cur[i] === lut[i]) match++;
    return match / CELLS;
}

function nextHuntCoord() {
    // For julia, "coords" means a c value (constant per pixel) and a
    // viewport zoom; the walk perturbs both.
    if (huntState.mode === 'julia') {
        if (huntState.stepsInWalk >= 12) {
            const c = JULIA_CS[Math.floor(Math.random() * JULIA_CS.length)];
            huntState.juliaCx = c[0] + (Math.random() - 0.5) * 0.05;
            huntState.juliaCy = c[1] + (Math.random() - 0.5) * 0.05;
            huntState.center_x = 0; huntState.center_y = 0;
            huntState.zoom = 1.5 + Math.random() * 3.0;
            huntState.stepsInWalk = 0;
            return;
        }
        huntState.juliaCx += (Math.random() - 0.5) * 0.04;
        huntState.juliaCy += (Math.random() - 0.5) * 0.04;
        huntState.zoom *= 0.7 + Math.random() * 0.5;
        huntState.stepsInWalk++;
        return;
    }
    // Mandelbrot / burning_ship / tricorn — escape-time over c-space.
    if (huntState.stepsInWalk >= 24 || huntState.walkSpan < 1e-9) {
        let seed;
        if (huntState.mode === 'burning_ship') {
            seed = [BSHIP_CENTER[0] + (Math.random()-0.5)*0.3,
                    BSHIP_CENTER[1] + (Math.random()-0.5)*0.3,
                    Math.pow(10, -2 + Math.random()*2.3)];
        } else if (huntState.mode === 'tricorn') {
            seed = [(Math.random()-0.5)*2.0, (Math.random()-0.5)*2.0,
                    Math.pow(10, -1.5 + Math.random()*2)];
        } else {
            seed = MANDEL_SEEDS[Math.floor(Math.random()*MANDEL_SEEDS.length)];
        }
        huntState.walkCx = seed[0]; huntState.walkCy = seed[1]; huntState.walkSpan = seed[2];
        huntState.stepsInWalk = 0;
        return;
    }
    huntState.walkCx += (Math.random()*2 - 1) * 0.4 * huntState.walkSpan;
    huntState.walkCy += (Math.random()*2 - 1) * 0.4 * huntState.walkSpan;
    huntState.walkSpan *= 0.6 + Math.random() * 0.35;
    huntState.stepsInWalk++;
}

function huntOnce() {
    nextHuntCoord();
    let params, label;
    if (huntState.mode === 'julia') {
        params = { juliaCx: huntState.juliaCx, juliaCy: huntState.juliaCy,
                   center_x: huntState.center_x, center_y: huntState.center_y,
                   zoom: huntState.zoom };
        label = `julia · c=(${params.juliaCx.toFixed(4)},${params.juliaCy.toFixed(4)}) ` +
                `zoom=${params.zoom.toExponential(2)}`;
    } else {
        params = { cx: huntState.walkCx, cy: huntState.walkCy,
                   span: huntState.walkSpan };
        label = `${huntState.mode} · cx=${params.cx.toFixed(4)} ` +
                `cy=${params.cy.toFixed(4)} span=${params.span.toExponential(2)}`;
    }
    const { escape, iterCap } = fractalGrid(params, SIDE, huntState.mode);
    const lut = posterise(escape, iterCap);
    const sr  = srStrict(lut, 4);
    huntState.nScanned++;
    if (sr > huntState.bestSr) huntState.bestSr = sr;
    updateHuntStat();
    return { lut, sr, label };
}

function updateHuntStat() {
    const status = document.getElementById("statHunt");
    if (!huntState.running) {
        status.innerHTML = `live search: idle · scanned=${huntState.nScanned}` +
                           ` accepted=${huntState.nAccepted}` +
                           ` best_sr=${huntState.bestSr.toFixed(3)}`;
    } else {
        const left = Math.max(0, (huntState.holdUntil - Date.now()) / 1000);
        status.innerHTML = `<b>SEARCHING</b> · scanned=${huntState.nScanned}` +
                           ` accepted=${huntState.nAccepted}` +
                           ` best_sr=${huntState.bestSr.toFixed(3)}` +
                           (left > 0 ? ` · displaying for ${left.toFixed(1)}s` : '');
    }
}

function huntTick() {
    if (!huntState.running) return;
    // While holding a find, just keep stepping the CA forward.
    if (Date.now() < huntState.holdUntil) {
        stepOnce();
        updateHuntStat();
        huntState.timer = setTimeout(huntTick, 80);
        return;
    }
    // Display time over — search for the next candidate.
    const found = huntOnce();
    if (found.sr >= huntMinSr) {
        huntState.nAccepted++;
        loadLUT(found.lut);
        document.getElementById("statFile").innerHTML =
            `<b>hunt ${huntState.nAccepted}</b> · ${found.label} ` +
            `· sr=${found.sr.toFixed(3)}`;
        huntState.holdUntil = Date.now() + huntDisplayMs;
    }
    updateHuntStat();
    // Quick re-tick to keep searching.
    huntState.timer = setTimeout(huntTick, 5);
}

document.getElementById("huntMode").addEventListener("change", (e) => {
    huntState.mode = e.target.value;
    // Force a fresh seed pick on the next coord step so the walk
    // restarts inside the new fractal.
    huntState.stepsInWalk = 999;
    huntState.walkSpan = 3.0;
    updateHuntStat();
});
document.getElementById("btnHunt").addEventListener("click", () => {
    huntState.running = !huntState.running;
    document.getElementById("btnHunt").textContent =
        huntState.running ? "❚❚ stop search" : "▶ fractal search";
    if (huntState.running) {
        // Reset walk to a seed.
        huntState.stepsInWalk = 999;
        huntState.holdUntil = 0;
        huntTick();
    } else if (huntState.timer) {
        clearTimeout(huntState.timer); huntState.timer = null;
    }
    updateHuntStat();
});
document.getElementById("btnHuntOnce").addEventListener("click", () => {
    const found = huntOnce();
    loadLUT(found.lut);
    document.getElementById("statFile").innerHTML =
        `<b>one-shot</b> · ${found.label} · sr=${found.sr.toFixed(3)}`;
});

// ── Default-LUT auto-load on first open ────────────────────────────
const DEFAULT_LUT_B64 = "__DEFAULT_LUT_B64__";
if (DEFAULT_LUT_B64 && DEFAULT_LUT_B64.length > 0) {
    const bin = atob(DEFAULT_LUT_B64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    loadLUT(bytes);
    document.getElementById("statFile").innerHTML =
        "<b>(default)</b> Mandelbrot main view, posterised K=4";
}
</script>
</body>
</html>
'''


class Command(BaseCommand):
    help = ('Emit a single self-contained HTML LUT viewer for any 16,384-'
            'byte K=4 hex CA rule .lut file.')

    def add_arguments(self, parser):
        parser.add_argument('--out', type=str, default='lutview.html')

    def add_arguments_extra(self, parser):  # noqa: keep next to add_arguments
        pass

    def handle(self, *, out, **opts):
        # Bake a Mandelbrot-main-view default LUT into the HTML so the
        # viewer opens with something rendered (instead of empty canvases).
        try:
            default = _default_mandelbrot_lut()
        except Exception as e:
            sys.stdout.write(f'note: skipping default LUT ({e})\n')
            default = None
        html = build_lutview_html(default)
        out_p = Path(out)
        out_p.write_text(html, encoding='utf-8')
        sys.stdout.write(f'wrote {out_p} '
                            f'({out_p.stat().st_size} B'
                            f'{", default LUT embedded" if default else ""})\n')

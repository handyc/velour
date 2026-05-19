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

import sys
from pathlib import Path

from django.core.management.base import BaseCommand


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
    <canvas id="canvasInit" width="512" height="512"></canvas>
    <div class="stat">current tick:</div>
    <canvas id="canvasCur"  width="512" height="512"></canvas>
  </div>
  <div class="controls">
    <h3>controls</h3>
    <div>
      <button id="btnStep" disabled>step 1 tick</button>
      <button id="btnStep10" disabled>+10</button>
      <button id="btnPlay" disabled>▶ play</button>
      <button id="btnReset" disabled>reset</button>
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
const PALETTE = [
    [0,   0,   0],
    [60,  150, 220],
    [240, 180, 60],
    [250, 245, 240],
];

// Build palette swatches.
const palDiv = document.getElementById("palette");
for (let k = 0; k < 4; k++) {
    const [r,g,b] = PALETTE[k];
    const s = document.createElement("div");
    s.className = "swatch";
    s.style.background = `rgb(${r},${g},${b})`;
    const t = document.createElement("span"); t.textContent = k;
    s.appendChild(t); palDiv.appendChild(s);
}

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

// ── Render a (side, side) K=4 grid into a canvas ────────────────────
function renderGrid(canvas, grid, side) {
    const cellPx = canvas.width / side;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(side, side);
    for (let i = 0; i < side * side; i++) {
        const [r, g, b] = PALETTE[grid[i] & 3];
        img.data[i * 4 + 0] = r;
        img.data[i * 4 + 1] = g;
        img.data[i * 4 + 2] = b;
        img.data[i * 4 + 3] = 255;
    }
    // Tiny offscreen canvas at native size, then scale up.
    const tmp = document.createElement("canvas");
    tmp.width = side; tmp.height = side;
    tmp.getContext("2d").putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(tmp, 0, 0, canvas.width, canvas.height);
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
</script>
</body>
</html>
'''


class Command(BaseCommand):
    help = ('Emit a single self-contained HTML LUT viewer for any 16,384-'
            'byte K=4 hex CA rule .lut file.')

    def add_arguments(self, parser):
        parser.add_argument('--out', type=str, default='lutview.html')

    def handle(self, *, out, **opts):
        out_p = Path(out)
        out_p.write_text(HTML, encoding='utf-8')
        sys.stdout.write(f'wrote {out_p} '
                            f'({out_p.stat().st_size} B)\n')

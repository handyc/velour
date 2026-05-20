"""Emit a standalone HTML/JS '1970s TV' that plays CA channels.

Single .html file, no dependencies.  Renders a wood-paneled 1970s
television; the screen area shows a 128×128 K=4 hex CA running at
30 fps; the chassis has channel ◀ / ▶, VCR-style transport
(rewind / pause / play / fast-forward), and an auto-search toggle
that advances channels every 1 s.

Each "channel" is a different fractal-derived rule generated in
the browser using the same generators that lutview ships with
(Mandelbrot, Julia, Burning Ship, Tricorn, Multibrot, Newton,
Phoenix).  The first channel is the bundled main-Mandelbrot LUT
(byte-identical to lutview's default).

  manage.py caformer_emit_tv --out tv.html
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

from django.core.management.base import BaseCommand


def _default_mandelbrot_lut() -> bytes:
    from loupe.render import mandelbrot_buckets
    import numpy as np
    arr = mandelbrot_buckets(-0.5, 0.0, 3.0, 128, 128, iter_cap=None)
    return bytes(arr.astype(np.uint8).ravel())


HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CA-TV · channel surfing the edge of chaos</title>
<style>
  html, body { margin:0; padding:0; height:100%;
               background: radial-gradient(circle at 50% 30%, #1a1611, #050403);
               font-family: ui-monospace, "SF Mono", monospace;
               color:#cfc4a8; overflow:hidden; }

  /* The whole TV cabinet. 90% of viewport height; aspect ratio
     keeps it shaped like a chunky 70s receiver. */
  #cabinet {
    position:absolute; left:50%; top:50%;
    transform: translate(-50%, -50%);
    height:90vh; aspect-ratio: 1.18 / 1;
    background:
      linear-gradient(180deg,
        #5c3a1d 0%, #6e4a28 8%, #7a5430 30%,
        #6c4724 70%, #4d3018 100%);
    border-radius: 22px;
    box-shadow:
      inset 0 0 0 4px #2a1a0d,
      inset 0 8px 24px rgba(0,0,0,0.55),
      0 30px 60px rgba(0,0,0,0.7),
      0 0 1px #000;
    display:grid;
    grid-template-rows: 1fr auto;
    padding:3.5%;
    box-sizing:border-box;
  }
  /* Faux wood-grain via repeating horizontal lines. */
  #cabinet::before {
    content:''; position:absolute; inset:0; border-radius:22px;
    background: repeating-linear-gradient(
      0deg,
      rgba(0,0,0,0.06) 0px, rgba(0,0,0,0.06) 1px,
      transparent 1px,    transparent 3px);
    pointer-events:none;
  }

  /* The bezel: black plastic frame around the screen. */
  #bezel {
    background:#0a0907;
    border-radius: 6% / 9%;
    padding: 3.2% 3.6%;
    box-shadow: inset 0 0 0 2px #2a2520, inset 0 0 25px #000;
    display:flex; align-items:center; justify-content:center;
    position:relative;
  }
  /* The screen itself — the CRT glass.  border-radius percentages
     give that pillow-shaped 1970s look; inner radial gradient adds
     a subtle phosphor glow. */
  #screen {
    width:100%; height:100%;
    border-radius: 7% / 10%;
    background:#000;
    box-shadow:
      inset 0 0 60px rgba(0, 30, 0, 0.7),
      inset 0 0 6px rgba(120, 255, 120, 0.15);
    position:relative; overflow:hidden;
  }
  /* The canvas fills the screen.  Pixelated so the CA cells stay
     crisp at any zoom. */
  #ca-canvas {
    position:absolute; inset:0; width:100%; height:100%;
    image-rendering: pixelated; image-rendering: crisp-edges;
  }
  /* Curved CRT scan-line overlay + subtle vignette. */
  #screen::after {
    content:''; position:absolute; inset:0; pointer-events:none;
    background:
      repeating-linear-gradient(
        0deg, rgba(0,0,0,0.18) 0px, rgba(0,0,0,0.18) 1px,
              transparent      1px, transparent      3px),
      radial-gradient(ellipse at center,
                       transparent 55%, rgba(0,0,0,0.45) 100%);
  }

  /* Bottom strip = controls + speaker grille. */
  #controls {
    display:grid;
    grid-template-columns: 1fr auto 1.4fr;
    gap: 2%;
    align-items: stretch;
    margin-top: 3%;
    min-height: 14%;
  }
  /* Speaker grille — vertical slats. */
  #grille {
    background: #1a1108;
    border:1px solid #2a1a0d;
    border-radius: 4px;
    background-image:
      repeating-linear-gradient(
        90deg, #1a1108 0px, #1a1108 4px,
               #3a2a18 4px, #3a2a18 6px);
    box-shadow: inset 0 0 6px #000;
  }
  /* Channel panel: chunky knob + display + buttons. */
  .panel {
    background: linear-gradient(180deg, #c9b88e, #8a774d);
    border-radius: 6px;
    border: 1px solid #2a1a0d;
    padding: 8px 12px;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.4),
      inset 0 -2px 4px rgba(0,0,0,0.3),
      0 2px 4px rgba(0,0,0,0.5);
    display:flex; flex-direction:column; gap:6px;
    color:#1a0f06; font-weight:bold;
  }
  .panel .label {
    font-size: clamp(8px, 1.2vh, 12px);
    text-transform: uppercase;
    letter-spacing: 0.1em; opacity:0.75;
  }
  .panel .row { display:flex; gap:8px; align-items:center; }

  /* "Bakelite" push buttons. */
  button {
    background:
      linear-gradient(180deg, #2a2118 0%, #1a130c 100%);
    color:#cfc4a8;
    border:1px solid #050403;
    border-radius: 4px;
    padding: 6px 10px;
    font: inherit; font-weight:bold;
    cursor:pointer;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.08),
      inset 0 -2px 3px rgba(0,0,0,0.6),
      0 1px 1px rgba(0,0,0,0.5);
    transition: transform 0.05s, box-shadow 0.05s;
    font-size: clamp(9px, 1.3vh, 13px);
  }
  button:hover { background: linear-gradient(180deg, #3a2e20, #221810); }
  button:active {
    transform: translateY(1px);
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.8);
  }
  button.on {
    background: linear-gradient(180deg, #c2912a, #8a5e10);
    color:#1a0f06;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.3),
      inset 0 -2px 3px rgba(0,0,0,0.4),
      0 0 6px rgba(255,180,40,0.5);
  }

  /* Channel readout — orange-glow Nixie-ish. */
  #ch-display {
    background:#180a02;
    color:#ff8a18;
    text-shadow: 0 0 6px #ff8a18, 0 0 14px rgba(255,138,24,0.6);
    border:1px solid #050403;
    border-radius:3px;
    padding: 4px 12px;
    font-family: "Courier New", monospace;
    font-weight:bold;
    font-size: clamp(14px, 2.5vh, 22px);
    letter-spacing: 0.15em;
    min-width: 4ch; text-align:center;
    box-shadow: inset 0 0 8px #000;
  }

  /* Status line beneath the screen / inside cabinet. */
  #status {
    grid-column: 1 / 4;
    text-align:center;
    font-size: clamp(8px, 1.1vh, 11px);
    color: #a09075; opacity:0.85;
    padding: 4px 0 0 0;
    letter-spacing: 0.08em;
  }
</style>
</head>
<body>
<div id="cabinet">
  <div id="bezel">
    <div id="screen">
      <canvas id="ca-canvas"></canvas>
    </div>
  </div>
  <div id="controls">
    <!-- Channel panel -->
    <div class="panel">
      <div class="label">CHANNEL</div>
      <div class="row">
        <button id="ch-prev" title="Previous channel">◀</button>
        <div id="ch-display">CH 01</div>
        <button id="ch-next" title="Next channel">▶</button>
      </div>
      <div class="row">
        <button id="ch-autosearch" title="Advance one channel per second">AUTO ▶▶</button>
      </div>
    </div>
    <!-- Speaker grille -->
    <div id="grille"></div>
    <!-- VCR transport -->
    <div class="panel">
      <div class="label">TRANSPORT</div>
      <div class="row">
        <button id="btn-rew" title="Reset to channel start">⏮ REW</button>
        <button id="btn-pause" title="Pause">❚❚ PAUSE</button>
        <button id="btn-play" class="on" title="Play">▶ PLAY</button>
        <button id="btn-ff" title="Fast forward (4× speed)">⏭ FF</button>
      </div>
      <div class="row" id="speedrow">
        <span class="label">SPEED:</span>
        <span id="speed-readout">1×</span>
        <span class="label">TICK:</span>
        <span id="tick-readout">0</span>
      </div>
      <div class="row">
        <button id="btn-music" title="8-voice CA-derived music (samples the current state every beat)">🔇 MUSIC</button>
      </div>
    </div>
    <div id="status">CA-TV · channel-surfing the edge of chaos</div>
  </div>
</div>

<script>
// ── CA primitives (same as lutview) ────────────────────────────────
const SIDE = 128;
const CELLS = SIDE * SIDE;
// PALETTE = the 4 colours mapped to K=4 cell values 0..3.  Mutated
// on every channel change for variety — see randomisePalette().
let PALETTE = [[0,0,0], [60,150,220], [240,180,60], [250,245,240]];

// Pick a vibrant random RGB via HSL with bounded saturation + lightness.
function _randColour() {
  const h = Math.random() * 360;
  const s = 55 + Math.random() * 40;        // 55..95% saturation
  const l = 22 + Math.random() * 60;        // 22..82% lightness
  const c = (1 - Math.abs(2 * l/100 - 1)) * s / 100;
  const x = c * (1 - Math.abs(((h/60) % 2) - 1));
  const m = l/100 - c/2;
  let r = 0, g = 0, b = 0;
  if      (h <  60) { r = c; g = x; }
  else if (h < 120) { r = x; g = c; }
  else if (h < 180) {         g = c; b = x; }
  else if (h < 240) {         g = x; b = c; }
  else if (h < 300) { r = x;         b = c; }
  else              { r = c;         b = x; }
  return [Math.round((r + m) * 255),
          Math.round((g + m) * 255),
          Math.round((b + m) * 255)];
}
// ── Music: 8-voice scheduled audio derived from the CA state ───────
//
// Adapted from officerpghiresev86's wavetable+meta-CA conductor:
// every beat, sample 8 cells from a fixed row of the current CA
// state; map cell value to a semitone offset; schedule note events
// via AudioContext look-ahead.  Voice fundamental rises by
// `MUSIC_VOICE_OCTAVE_SPREAD` semitones per voice so the 8 voices
// span ~3 octaves.  Each channel change brings a new rule + new
// initial state, so the music shifts noticeably across channels.

const MUSIC_BEAT_DUR_S       = 0.18;
const MUSIC_LOOK_AHEAD_S     = 1.5;
const MUSIC_SCHED_MS         = 80;
const MUSIC_VOICES           = 8;
const MUSIC_BASE_FREQ        = 196.00;     // G3
const MUSIC_VOICE_OCTAVE_SPREAD = 5;        // semitones between voices
const MUSIC_CELL_TO_SEMI     = [null, 0, 5, 7]; // null = rest, else root/4th/5th
const MUSIC_VOICE_ROW        = 96;          // row to sample (mid-low on 128)

let audioCtx       = null;
let musicMaster    = null;
let musicOn        = false;
let musicNextBeatT = 0;
let musicSchedTimer = null;

function musicEnsureCtx() {
  if (audioCtx) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  musicMaster = audioCtx.createGain();
  musicMaster.gain.value = 0.18;            // headroom for 8 voices
  musicMaster.connect(audioCtx.destination);
}

function musicScheduleBeat(t) {
  if (!state) return;
  const row = MUSIC_VOICE_ROW % SIDE;
  for (let v = 0; v < MUSIC_VOICES; v++) {
    const col = (v * SIDE / MUSIC_VOICES) | 0;
    const cellVal = state[row * SIDE + col] & 3;
    const semi = MUSIC_CELL_TO_SEMI[cellVal];
    if (semi === null) continue;
    const totalSemi = semi + v * MUSIC_VOICE_OCTAVE_SPREAD;
    const freq = MUSIC_BASE_FREQ * Math.pow(2, totalSemi / 12);
    // Per-voice oscillator with quick envelope.
    const osc = audioCtx.createOscillator();
    const g   = audioCtx.createGain();
    // Triangle for low voices, sine for high → less harshness.
    osc.type = v < 3 ? 'triangle' : 'sine';
    osc.frequency.setValueAtTime(freq, t);
    const peak = 0.16;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(peak, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.001, t + MUSIC_BEAT_DUR_S * 0.9);
    osc.connect(g).connect(musicMaster);
    osc.start(t);
    osc.stop(t + MUSIC_BEAT_DUR_S);
  }
}

function musicSchedulerTick() {
  if (!musicOn || !audioCtx) return;
  while (musicNextBeatT < audioCtx.currentTime + MUSIC_LOOK_AHEAD_S) {
    musicScheduleBeat(musicNextBeatT);
    musicNextBeatT += MUSIC_BEAT_DUR_S;
  }
}

function musicStart() {
  if (musicOn) return;
  musicEnsureCtx();
  if (audioCtx.state === 'suspended') audioCtx.resume();
  musicOn = true;
  musicNextBeatT = audioCtx.currentTime + 0.05;
  musicSchedTimer = setInterval(musicSchedulerTick, MUSIC_SCHED_MS);
}

function musicStop() {
  musicOn = false;
  if (musicSchedTimer) { clearInterval(musicSchedTimer); musicSchedTimer = null; }
}

function randomisePalette() {
  // Cell 0 stays dark so the response region's zeros read as
  // background; cells 1/2/3 get fresh hues.
  PALETTE = [[0, 0, 0], _randColour(), _randColour(), _randColour()];
}

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
                | (nR    <<  6) | (nSE <<  4) | (nSW << 2) |  nL;
      out[r * side + c] = rule[key];
    }
  }
  return out;
}

// ── Channel generators (a subset of the lutview fractal hunter) ───
const MANDEL_SEEDS = [
  [-0.5,    0.0,   3.0],
  [-0.745,  0.113, 0.05],
  [-1.25,   0.0,   0.1],
  [-0.16,   1.04,  0.04],
  [ 0.272,  0.005, 0.01],
  [-0.7269, 0.1889, 0.005],
];
const JULIA_CS = [
  [-0.4, 0.6], [0.285, 0.01], [-0.835, -0.2321],
  [0.45, 0.1428], [-0.70176, -0.3842], [0, 1],
  [-1.476, 0], [-0.12, 0.74], [-0.75, 0.11],
];
const BSHIP_CENTER = [-1.75, -0.03];

function escapeAt(zx0, zy0, cx, cy, iterCap, mode, d) {
  let zx = zx0, zy = zy0, i;
  for (i = 0; i < iterCap; i++) {
    if (zx*zx + zy*zy > 4.0) return i;
    let nx, ny;
    if (mode === 'mandelbrot' || mode === 'julia') {
      nx = zx*zx - zy*zy + cx;  ny = 2*zx*zy + cy;
    } else if (mode === 'burning_ship') {
      const ax = Math.abs(zx), ay = Math.abs(zy);
      nx = ax*ax - ay*ay + cx;  ny = 2*ax*ay + cy;
    } else if (mode === 'tricorn') {
      nx = zx*zx - zy*zy + cx;  ny = -2*zx*zy + cy;
    } else if (mode === 'multibrot') {
      const r = Math.sqrt(zx*zx + zy*zy);
      const th = Math.atan2(zy, zx);
      const rd = Math.pow(r, d);
      nx = rd * Math.cos(d * th) + cx;
      ny = rd * Math.sin(d * th) + cy;
    } else { return iterCap; }
    zx = nx; zy = ny;
  }
  return iterCap;
}
const NEWTON_ROOTS = [[1,0],[-0.5,0.8660254],[-0.5,-0.8660254]];
function newtonGrid(params, side) {
  const px = params.span / side;
  const half = params.span / 2;
  const ox = params.cx - half, oy = params.cy - half;
  const iters = 32;
  const out = new Uint8Array(side * side);
  for (let r = 0; r < side; r++) {
    const y0 = oy + r * px;
    for (let c = 0; c < side; c++) {
      let zx = ox + c * px, zy = y0;
      for (let it = 0; it < iters; it++) {
        const z2x = zx*zx - zy*zy, z2y = 2*zx*zy;
        const denom = 3*(z2x*z2x + z2y*z2y) + 1e-20;
        zx = (2/3)*zx +  z2x/denom;
        zy = (2/3)*zy - z2y/denom;
      }
      let best=3, bd=0.01;
      for (let k=0;k<3;k++) {
        const dx=zx-NEWTON_ROOTS[k][0], dy=zy-NEWTON_ROOTS[k][1];
        const d2=dx*dx+dy*dy;
        if (d2<bd){bd=d2; best=k;}
      }
      out[r*side+c]=best;
    }
  }
  return out;
}
function phoenixGrid(params, side, iterCap) {
  const px = params.span / side;
  const half = params.span / 2;
  const ox = params.cx - half, oy = params.cy - half;
  const escape = new Int32Array(side*side);
  for (let r=0; r<side; r++) {
    const y0=oy+r*px;
    for (let c=0; c<side; c++) {
      let zx=ox+c*px, zy=y0, pzx=0, pzy=0, hit=iterCap;
      for (let i=0; i<iterCap; i++) {
        if (zx*zx+zy*zy>4){hit=i; break;}
        const nx=zx*zx-zy*zy+params.p_re+params.p_im*pzx;
        const ny=2*zx*zy+params.p_im*pzy;
        pzx=zx; pzy=zy; zx=nx; zy=ny;
      }
      escape[r*side+c]=hit;
    }
  }
  return escape;
}
function fractalGrid(params, side, mode) {
  let it = 192;
  let s = params.span || 1.0;
  while (s < 1.0 && it < 800) { it += 64; s *= 2; }
  if (mode === 'newton') return { directLut: newtonGrid(params, side) };
  if (mode === 'phoenix') return { escape: phoenixGrid(params, side, it), iterCap: it };
  const escape = new Int32Array(side*side);
  const half = params.span / 2;
  const px = params.span / side;
  const ox = params.cx - half, oy = params.cy - half;
  const d = params.d || 3;
  if (mode === 'julia') {
    for (let r=0; r<side; r++) {
      const y=oy+r*px;
      for (let c=0; c<side; c++) {
        escape[r*side+c]=escapeAt(ox+c*px, y, params.juliaCx, params.juliaCy, it, mode);
      }
    }
  } else {
    for (let r=0; r<side; r++) {
      const y=oy+r*px;
      for (let c=0; c<side; c++) {
        escape[r*side+c]=escapeAt(0, 0, ox+c*px, y, it, mode, d);
      }
    }
  }
  return { escape, iterCap: it };
}
function posterise(escape, iterCap) {
  const finite=[];
  for (let i=0; i<escape.length; i++)
    if (escape[i]<iterCap) finite.push(escape[i]);
  let bin1, bin2;
  if (finite.length<3) { bin1=iterCap/3; bin2=2*iterCap/3; }
  else {
    finite.sort((a,b)=>a-b);
    bin1=finite[finite.length/3|0];
    bin2=finite[(2*finite.length/3)|0];
    if (bin2<=bin1) bin2=bin1+1;
  }
  const out=new Uint8Array(escape.length);
  for (let i=0; i<escape.length; i++) {
    const e=escape[i];
    if (e>=iterCap) out[i]=3;
    else if (e<bin1) out[i]=0;
    else if (e<bin2) out[i]=1;
    else out[i]=2;
  }
  return out;
}

// Mulberry32 PRNG for deterministic channels.
function mulberry32(seed) {
  return function() {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Each channel = deterministic (mode, params) from channel-id seed.
function buildChannel(chId) {
  // Channels 0..CORPUS_CHANNELS.length-1 = real trained per-position
  // LUTs from the corpus (FTV mode). After those, channel
  // CORPUS_CHANNELS.length = Mandelbrot main view; then fractals.
  if (chId < CORPUS_CHANNELS.length) {
    const c = CORPUS_CHANNELS[chId];
    return { mode: 'corpus',
             label: `CH ${String(chId+1).padStart(2,'0')}  ${c.label}`,
             lut: c.lut };
  }
  // Adjusted ID for the fractal channel space.
  const fId = chId - CORPUS_CHANNELS.length;
  if (fId === 0) {
    return { mode: 'mandelbrot',
             label: `CH ${String(chId+1).padStart(2,'0')}  MANDEL · main view`,
             lut: defaultLut };
  }
  const rnd = mulberry32(0xC1A55E + chId * 7919);
  const modes = ['mandelbrot','julia','burning_ship','tricorn',
                 'multibrot','newton','phoenix'];
  const mode = modes[Math.floor(rnd() * modes.length)];
  let params, label;
  if (mode === 'julia') {
    const c = JULIA_CS[Math.floor(rnd() * JULIA_CS.length)];
    params = { juliaCx: c[0] + (rnd()-0.5)*0.05,
               juliaCy: c[1] + (rnd()-0.5)*0.05,
               span: 1.5 + rnd()*2.5 };
    // Julia uses 'span' as zoom centered at (0,0); our fractalGrid
    // path needs cx/cy too, so set them to 0 here.
    params.cx = 0; params.cy = 0;
    label = `julia c=(${params.juliaCx.toFixed(3)},${params.juliaCy.toFixed(3)})`;
  } else if (mode === 'burning_ship') {
    params = { cx: BSHIP_CENTER[0] + (rnd()-0.5)*0.3,
               cy: BSHIP_CENTER[1] + (rnd()-0.5)*0.3,
               span: Math.pow(10, -2 + rnd()*2.3) };
    label = `b.ship cx=${params.cx.toFixed(2)} span=${params.span.toExponential(1)}`;
  } else if (mode === 'tricorn' || mode === 'multibrot') {
    params = { cx: (rnd()-0.5)*2.0, cy: (rnd()-0.5)*2.0,
               span: Math.pow(10, -1.5 + rnd()*2) };
    if (mode === 'multibrot') params.d = 3 + Math.floor(rnd()*5);
    label = `${mode}${params.d ? ' d='+params.d : ''} cx=${params.cx.toFixed(2)} span=${params.span.toExponential(1)}`;
  } else if (mode === 'newton') {
    params = { cx: (rnd()-0.5)*0.5, cy: (rnd()-0.5)*0.5,
               span: Math.pow(10, -1.5 + rnd()*2.1) };
    label = `newton z³−1 span=${params.span.toExponential(1)}`;
  } else if (mode === 'phoenix') {
    params = { cx: (rnd()-0.5)*1.0, cy: (rnd()-0.5)*1.0,
               span: Math.pow(10, -1.5 + rnd()*1.5),
               p_re: 0.5667 + (rnd()-0.5)*0.4,
               p_im: -0.5   + (rnd()-0.5)*0.4 };
    label = `phoenix p=(${params.p_re.toFixed(2)},${params.p_im.toFixed(2)})`;
  } else {
    const seed = MANDEL_SEEDS[Math.floor(rnd()*MANDEL_SEEDS.length)];
    params = { cx: seed[0] + (rnd()-0.5)*seed[2]*0.4,
               cy: seed[1] + (rnd()-0.5)*seed[2]*0.4,
               span: seed[2] * (0.4 + rnd()*0.8) };
    label = `mandel cx=${params.cx.toFixed(3)} span=${params.span.toExponential(1)}`;
  }
  const g = fractalGrid(params, SIDE, mode);
  const lut = g.directLut ? g.directLut : posterise(g.escape, g.iterCap);
  return { mode, params, label: `CH ${String(chId+1).padStart(2,'0')}  ${label}`, lut };
}

// ── Baked corpus channels (FTV mode) ───────────────────────────────
// Each entry is { label: string, lut: Uint8Array }.  These channels
// fire first (CH 01, CH 02 …) before the fractal-generated ones.
// Each one is a real trained per-position rule from the corpus —
// when channel-surfed, you see THAT rule's CA dynamics on its own
// LUT-as-image.
const CORPUS_CHANNELS_RAW = __CORPUS_CHANNELS_JSON__;
const CORPUS_CHANNELS = CORPUS_CHANNELS_RAW.map(c => {
  const bin = atob(c.lut_b64);
  const lut = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) lut[i] = bin.charCodeAt(i) & 3;
  return { label: c.label, lut };
});

// ── Default LUT (Mandelbrot main view), baked at build time ─────────
const DEFAULT_LUT_B64 = "__DEFAULT_LUT_B64__";
let defaultLut;
if (DEFAULT_LUT_B64 && DEFAULT_LUT_B64.length > 0) {
  const bin = atob(DEFAULT_LUT_B64);
  defaultLut = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) defaultLut[i] = bin.charCodeAt(i) & 3;
} else {
  defaultLut = new Uint8Array(CELLS);   // all zeros fallback
}

// ── Animation state ────────────────────────────────────────────────
const canvas = document.getElementById('ca-canvas');
const ctx = canvas.getContext('2d', { alpha: false });
let currentChannel = 0;
let state = null;
let rule  = null;
let label = '';
let tick  = 0;
let speed = 1;           // ticks per frame (1 = 30 ticks/sec at 30 fps)
let playing = true;
let autosearch = false;
let lastFrameTime = 0;
const TARGET_FPS = 30;
const FRAME_MS = 1000 / TARGET_FPS;

// Sized for raw 128×128 image; CSS scales to fill the screen.
canvas.width = SIDE;
canvas.height = SIDE;
const imageData = ctx.createImageData(SIDE, SIDE);

function loadChannel(chId, opts={}) {
  const ch = buildChannel(chId);
  currentChannel = chId;
  rule = ch.lut;
  // Initial state = the LUT itself (ouroboros), unless reset.
  state = new Uint8Array(rule);
  label = ch.label;
  tick = 0;
  // Fresh palette per channel — sells the "different rule = different
  // signal" vibe more than reusing the same 4 colours.  rewindCurrent()
  // passes {keepPalette: true} so the rewind button doesn't reroll.
  if (!opts.keepPalette) randomisePalette();
  document.getElementById('ch-display').textContent =
    'CH ' + String(chId+1).padStart(2,'0');
  document.getElementById('status').textContent = label;
  redraw();
}

function rewindCurrent() { loadChannel(currentChannel, {keepPalette: true}); }

function redraw() {
  const data = imageData.data;
  for (let i = 0; i < CELLS; i++) {
    const c = state[i] & 3;
    const p = PALETTE[c];
    const off = i << 2;
    data[off]     = p[0];
    data[off + 1] = p[1];
    data[off + 2] = p[2];
    data[off + 3] = 255;
  }
  ctx.putImageData(imageData, 0, 0);
}

function tickOnce() {
  state = hexStep(state, rule, SIDE);
  tick++;
}

function frame(now) {
  if (now - lastFrameTime >= FRAME_MS) {
    lastFrameTime = now;
    if (playing) {
      for (let i = 0; i < speed; i++) tickOnce();
      redraw();
      document.getElementById('tick-readout').textContent = String(tick);
    }
  }
  requestAnimationFrame(frame);
}

// ── Controls ───────────────────────────────────────────────────────
function setPlaying(on) {
  playing = on;
  document.getElementById('btn-play').classList.toggle('on', on);
  document.getElementById('btn-pause').classList.toggle('on', !on);
}
function setSpeed(s) {
  speed = s;
  document.getElementById('speed-readout').textContent = s + '×';
  document.getElementById('btn-ff').classList.toggle('on', s > 1);
}
function setAutosearch(on) {
  autosearch = on;
  document.getElementById('ch-autosearch').classList.toggle('on', on);
  if (autosearch) {
    if (window._autoTimer) clearInterval(window._autoTimer);
    window._autoTimer = setInterval(() => {
      loadChannel(currentChannel + 1);
    }, 1000);
  } else if (window._autoTimer) {
    clearInterval(window._autoTimer); window._autoTimer = null;
  }
}

document.getElementById('ch-prev').addEventListener('click',
  () => loadChannel(currentChannel === 0 ? 99 : currentChannel - 1));
document.getElementById('ch-next').addEventListener('click',
  () => loadChannel(currentChannel + 1));
document.getElementById('ch-autosearch').addEventListener('click',
  () => setAutosearch(!autosearch));

document.getElementById('btn-rew').addEventListener('click', rewindCurrent);
document.getElementById('btn-pause').addEventListener('click', () => setPlaying(false));
document.getElementById('btn-play').addEventListener('click', () => setPlaying(true));
document.getElementById('btn-ff').addEventListener('click',
  () => setSpeed(speed === 1 ? 4 : (speed === 4 ? 8 : 1)));
document.getElementById('btn-music').addEventListener('click', () => {
  if (musicOn) {
    musicStop();
    const b = document.getElementById('btn-music');
    b.textContent = '🔇 MUSIC';
    b.classList.remove('on');
  } else {
    musicStart();
    const b = document.getElementById('btn-music');
    b.textContent = '🔊 MUSIC';
    b.classList.add('on');
  }
});

// Keyboard shortcuts.
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft')  document.getElementById('ch-prev').click();
  else if (e.key === 'ArrowRight') document.getElementById('ch-next').click();
  else if (e.key === ' ') { e.preventDefault(); setPlaying(!playing); }
  else if (e.key === 'r')  rewindCurrent();
  else if (e.key === 'f')  document.getElementById('btn-ff').click();
  else if (e.key === 'a')  setAutosearch(!autosearch);
});

// Boot.
loadChannel(0);
requestAnimationFrame(frame);
</script>
</body>
</html>
'''


class Command(BaseCommand):
    help = ('Emit a standalone 1970s TV that channel-surfs CA rules at '
            '30 fps.  --bake-corpus N adds N real trained per-position '
            'LUTs from board128_exact pairs as the first N channels '
            '(FTV = "fractal television" plus corpus).')

    def add_arguments(self, parser):
        parser.add_argument('--out', type=str, default='tv.html')
        parser.add_argument('--bake-corpus', type=int, default=0,
                              help='how many real corpus channels to bake '
                                     'as the first channels (default 0 = '
                                     'fractal-only TV)')
        parser.add_argument('--corpus-per-pair', type=int, default=1,
                              help='channels per pair (default 1 = position '
                                     '0 only).  Use 0 for all positions.')

    def handle(self, *, out, bake_corpus, corpus_per_pair, **opts):
        import json
        # Default Mandelbrot LUT.
        try:
            default = _default_mandelbrot_lut()
            b64 = base64.b64encode(default).decode('ascii')
        except Exception as e:
            sys.stdout.write(f'note: skipping default LUT ({e})\n')
            b64 = ''

        # Corpus channels: collect N real trained per-position rules.
        corpus_channels = []
        if bake_corpus > 0:
            from caformer.models import QRPair
            pairs = list(QRPair.objects.filter(board128_exact=True)
                                .order_by('pk'))
            for p in pairs:
                if len(corpus_channels) >= bake_corpus: break
                blob = bytes(p.board128_rules_blob or b'')
                n_pos = len(blob) // 16384
                max_take = n_pos if corpus_per_pair == 0 \
                                  else min(corpus_per_pair, n_pos)
                for pos in range(max_take):
                    if len(corpus_channels) >= bake_corpus: break
                    rule_bytes = blob[pos*16384:(pos+1)*16384]
                    target_char = (p.expected[pos] if pos < len(p.expected)
                                       else '?')
                    label = (f'pk{p.pk} {p.prompt!r}→{p.expected!r}'
                             f' pos{pos}={target_char!r}')[:60]
                    corpus_channels.append({
                        'label':   label,
                        'lut_b64': base64.b64encode(rule_bytes).decode('ascii'),
                    })
            sys.stdout.write(
                f'baked {len(corpus_channels)} corpus channels '
                f'(from {len(pairs)} board128_exact pairs)\n')

        html = (HTML
                .replace('__DEFAULT_LUT_B64__', b64)
                .replace('__CORPUS_CHANNELS_JSON__',
                            json.dumps(corpus_channels)))
        out_p = Path(out)
        out_p.write_text(html, encoding='utf-8')
        sys.stdout.write(
            f'wrote {out_p} ({out_p.stat().st_size:,} B; '
            f'{len(corpus_channels)} corpus channels + fractal channels'
            f'{", default Mandelbrot baked" if b64 else ""})\n')

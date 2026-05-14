/* loupe.js — Mandelbrot renderer + epsilon-greedy agent walks.
 *
 * Public surface:
 *
 *   const eng = new LoupeEngine(canvas, {iter, palette});
 *   eng.setView(cx, cy, span);
 *   eng.render();                                 // sync; uses iter from ctor
 *   eng.fitness(view, sampleW, sampleH);          // Shannon entropy
 *   eng.thumbnail(view, w, h)  → data URI PNG     // for saving
 *
 *   const agent = new LoupeAgent(eng, {
 *     start: {cx, cy, span}, n_steps, k_candidates, epsilon,
 *     scale_dz, scale_xy, on_step, sample_w, sample_h,
 *   });
 *   const walk = agent.run();   // returns the gene array
 *
 * The gene is JSON-serialisable; each step records the viewport and
 * the fitness at that step.
 */
'use strict';

(function (global) {

// ─── colour palette (16 stops, looped) ───────────────────────────────
// Picked to give recognisable bands without going garish.  Index 0 is
// reserved for "in-set" pixels (rendered as black by the engine).
const DEFAULT_PALETTE = [
  [  0,   0,   0],   // unused — in-set is forced to (0,0,0)
  [ 25,   7,  26], [ 30,  20,  90], [ 50,  50, 130], [ 90,  90, 180],
  [120, 150, 220], [180, 200, 240], [240, 220, 180], [240, 180,  80],
  [220, 120,  30], [180,  70,  20], [120,  40,  20], [ 70,  20,  30],
  [ 60,  60,  60], [120, 120, 120], [200, 200, 200],
];

// ─── core mandelbrot iteration ───────────────────────────────────────
// Plain JS double precision.  For the 1024×768 viewer at ~256 iter
// this is ~30 ms on a laptop.  Web Worker upgrade is a Phase-2 item.
function _escape(cx, cy, iter) {
  let zx = 0, zy = 0;
  let x2 = 0, y2 = 0;
  for (let i = 0; i < iter; i++) {
    zy = 2 * zx * zy + cy;
    zx = x2 - y2 + cx;
    x2 = zx * zx; y2 = zy * zy;
    if (x2 + y2 > 4.0) return i;
  }
  return iter;
}

class LoupeEngine {
  constructor (canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.W = canvas.width;
    this.H = canvas.height;
    this.iter = opts.iter || 256;
    this.palette = opts.palette || DEFAULT_PALETTE;
    this.cx = -0.5; this.cy = 0.0; this.span = 3.0;
    this._buf = new Uint8ClampedArray(this.W * this.H * 4);
    this._image = new ImageData(this._buf, this.W, this.H);
  }

  // Auto-tune iter cap so deep zooms keep boundary detail.  Mirrors
  // officemandel's retune(): +64 per halving below span=1, capped 4096.
  retune () {
    let n = 192;
    let s = this.span;
    while (s < 1.0 && n < 4096) { n += 64; s *= 2.0; }
    this.iter = n;
  }

  setView (cx, cy, span) {
    this.cx = cx; this.cy = cy; this.span = span;
    this.retune();
    return this;
  }

  /* Pan the view by (px, py) in pixels — used by mouse drag. */
  pan (px, py) {
    const s = this.span / this.W;
    this.cx -= px * s;
    this.cy -= py * s;
    return this;
  }

  /* Zoom by factor f about screen point (px, py).  f<1 = zoom in. */
  zoomAt (px, py, f) {
    // The point (px, py) should map to the same complex coord before
    // and after the zoom: c = c_old(px,py) = c_new(px,py).
    const s_old = this.span / this.W;
    const x_old = this.cx - s_old * (this.W * 0.5) + s_old * px;
    const y_old = this.cy - s_old * (this.H * 0.5) + s_old * py;
    this.span *= f;
    const s_new = this.span / this.W;
    this.cx = x_old - s_new * (px - this.W * 0.5);
    this.cy = y_old - s_new * (py - this.H * 0.5);
    this.retune();
    return this;
  }

  /* Render the current view to the canvas. */
  render () {
    const W = this.W, H = this.H, iter = this.iter, pal = this.palette;
    const s = this.span / W;
    const ox = this.cx - s * (W * 0.5);
    const oy = this.cy - s * (H * 0.5);
    const buf = this._buf;
    let i = 0;
    for (let r = 0; r < H; r++) {
      const y = oy + r * s;
      for (let c = 0; c < W; c++) {
        const e = _escape(ox + c * s, y, iter);
        let R, G, B;
        if (e === iter) { R = 0; G = 0; B = 0; }
        else {
          const p = pal[1 + (e % (pal.length - 1))];
          R = p[0]; G = p[1]; B = p[2];
        }
        buf[i++] = R; buf[i++] = G; buf[i++] = B; buf[i++] = 255;
      }
    }
    this.ctx.putImageData(this._image, 0, 0);
  }

  /* Sample escape times in a w×h grid spanning the given view.  Used
   * by the fitness function and agent candidate evaluation; cheaper
   * than a full render and palette-independent.
   *
   * Returns Uint16Array of length w*h. */
  sampleEscapes (view, w, h) {
    const iter = view.iter || this.iter;
    const span = view.span;
    const cx = view.cx, cy = view.cy;
    const s = span / w;
    // Match the renderer's coordinate math: pixel (c, r) → complex
    //   (cx + s*(c - w/2 + 0.5),  cy_local + s*(r - h/2 + 0.5))
    // We don't enforce square aspect here; the agent's fitness window
    // can have any aspect, but we keep it square in practice.
    const ox = cx - s * (w * 0.5);
    const oy = cy - s * (h * 0.5);
    const out = new Uint16Array(w * h);
    let i = 0;
    for (let r = 0; r < h; r++) {
      const y = oy + r * s;
      for (let c = 0; c < w; c++) {
        out[i++] = _escape(ox + c * s, y, iter);
      }
    }
    return out;
  }

  /* Shannon entropy of the escape-time histogram for ``view``.
   * High when the window covers boundary regions with varied escape
   * speeds; low for deep-in-set (all = iter) or far-out (all small).
   *
   * Auto-tunes iter from the view's span so the resulting histogram
   * isn't dominated by the cap. */
  fitness (view, sampleW = 64, sampleH = 64, bins = 32) {
    // Estimate a sensible iter cap for the *current* span so the
    // histogram has resolution at deep zooms.
    let est_iter = 192;
    let s = view.span;
    while (s < 1.0 && est_iter < 4096) { est_iter += 64; s *= 2.0; }
    const v = {cx: view.cx, cy: view.cy, span: view.span, iter: est_iter};
    const escapes = this.sampleEscapes(v, sampleW, sampleH);
    // Histogram bins: 0..est_iter mapped to [0, bins-1]; the very
    // last bin is reserved for "in-set" so deep regions count
    // distinctly from finite escape times.
    const hist = new Float64Array(bins);
    const n = escapes.length;
    const scale = (bins - 1) / Math.max(1, est_iter);
    for (let i = 0; i < n; i++) {
      const e = escapes[i];
      const b = e >= est_iter ? bins - 1 : Math.min(bins - 2, Math.floor(e * scale));
      hist[b]++;
    }
    let H = 0;
    for (let b = 0; b < bins; b++) {
      const p = hist[b] / n;
      if (p > 0) H -= p * Math.log2(p);
    }
    return H;
  }

  /* Render the current view at the given size and return a data URI. */
  thumbnail (w = 128, h = 128) {
    const off = document.createElement('canvas');
    off.width = w; off.height = h;
    const octx = off.getContext('2d');
    const img = octx.createImageData(w, h);
    const buf = img.data;
    const iter = this.iter, pal = this.palette;
    const s = this.span / w;
    const ox = this.cx - s * (w * 0.5);
    const oy = this.cy - s * (h * 0.5);
    let i = 0;
    for (let r = 0; r < h; r++) {
      const y = oy + r * s;
      for (let c = 0; c < w; c++) {
        const e = _escape(ox + c * s, y, iter);
        let R, G, B;
        if (e === iter) { R = 0; G = 0; B = 0; }
        else {
          const p = pal[1 + (e % (pal.length - 1))];
          R = p[0]; G = p[1]; B = p[2];
        }
        buf[i++] = R; buf[i++] = G; buf[i++] = B; buf[i++] = 255;
      }
    }
    octx.putImageData(img, 0, 0);
    return off.toDataURL('image/png');
  }
}


// ─── agent ──────────────────────────────────────────────────────────
//
// Each step the agent considers ``k`` candidate moves drawn from a
// small Gaussian-ish jitter, scores each by fitness() at a tiny
// sample resolution, and picks the highest-fitness candidate with
// probability (1 - epsilon).  Otherwise it picks one at random
// (exploration).  The resulting trajectory often heads toward
// boundary cusps and seahorse-valley type regions.

function _randn () {
  // Box-Muller cheap normal random.
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

class LoupeAgent {
  constructor (engine, opts = {}) {
    this.eng = engine;
    this.start = opts.start || {
      cx: engine.cx, cy: engine.cy, span: engine.span,
    };
    this.n_steps      = opts.n_steps      || 24;
    this.k_candidates = opts.k_candidates || 6;
    this.epsilon      = opts.epsilon      || 0.15;
    this.scale_xy     = opts.scale_xy     || 0.35;  // fraction of span
    this.scale_dz     = opts.scale_dz     || 0.15;  // log-scale zoom jitter
    this.sample_w     = opts.sample_w     || 48;
    this.sample_h     = opts.sample_h     || 48;
    this.on_step      = opts.on_step      || null;
    this.zoom_bias    = opts.zoom_bias    || -0.10; // log-zoom drift in (zoom in over time)
  }

  /* Generate a candidate viewport offset from ``view``.  dx/dy in
   * span-fractions, dz multiplicative (e.g. 0.8 = zoom in 20%). */
  _candidate (view) {
    const dx = _randn() * this.scale_xy;
    const dy = _randn() * this.scale_xy;
    // Log-scale zoom: bias is in log space so each step shrinks span
    // on average without runaway.
    const log_dz = this.zoom_bias + _randn() * this.scale_dz;
    const dz = Math.exp(log_dz);
    return {dx, dy, dz};
  }

  _apply (view, cand) {
    return {
      cx:   view.cx + cand.dx * view.span,
      cy:   view.cy + cand.dy * view.span,
      span: Math.max(1e-12, Math.min(8.0, view.span * cand.dz)),
    };
  }

  /* Run the walk.  Returns the gene (list of viewport+fitness dicts
   * including the start state).  Synchronous; intended to be called
   * inside setTimeout chains so the UI stays responsive between
   * walks rather than during them. */
  run () {
    let view = {cx: this.start.cx, cy: this.start.cy, span: this.start.span};
    const gene = [];
    gene.push({
      cx: view.cx, cy: view.cy, span: view.span,
      fitness: this.eng.fitness(view, this.sample_w, this.sample_h),
    });
    for (let step = 0; step < this.n_steps; step++) {
      // K candidates → pick the best with (1 - eps) probability.
      const cands = [];
      let best_i = 0, best_f = -Infinity;
      for (let k = 0; k < this.k_candidates; k++) {
        const cand = this._candidate(view);
        const next_view = this._apply(view, cand);
        const f = this.eng.fitness(next_view, this.sample_w, this.sample_h);
        cands.push({cand, view: next_view, f});
        if (f > best_f) { best_f = f; best_i = k; }
      }
      const pick = (Math.random() < this.epsilon)
        ? cands[Math.floor(Math.random() * cands.length)]
        : cands[best_i];
      view = pick.view;
      const entry = {
        cx: view.cx, cy: view.cy, span: view.span, fitness: pick.f,
        dx: pick.cand.dx, dy: pick.cand.dy, dz: pick.cand.dz,
      };
      gene.push(entry);
      if (this.on_step) this.on_step(step, entry, gene);
    }
    return gene;
  }
}

global.LoupeEngine = LoupeEngine;
global.LoupeAgent  = LoupeAgent;
global.LOUPE_DEFAULT_PALETTE = DEFAULT_PALETTE;

})(window);

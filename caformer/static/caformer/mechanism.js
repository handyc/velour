/* caformer/mechanism.js — render a 16×16 hex CA on a canvas and step
 * it forward by a packed K=4 rule table.  Mirrors hex_ca_step exactly
 * so live diagrams use the same neighbour order and 14-bit key as the
 * Python / C implementations.
 *
 * Usage:
 *   const cell = new HexCA(canvas, {side: 16, palette: PALETTE_CFA});
 *   cell.setGridFromSeed(seedInt);
 *   cell.stepWithPackedRule(packedBytes, ticks);
 *   cell.paint();
 *
 * Rule tables are 2-bit-packed (4096 bytes = 16,384 entries).
 */

(function () {
  'use strict';

  const PALETTE_CFA = ['#0a0a0a', '#48a', '#aa6', '#cfa'];
  const PALETTE_HEAT = ['#0a0a0a', '#322', '#852', '#fc6'];

  function unpackLUT(packed) {
    // packed: Uint8Array of length 4096; result: Uint8Array of length 16384.
    const out = new Uint8Array(16384);
    for (let i = 0; i < 4096; i++) {
      const b = packed[i];
      out[i * 4 + 0] = (b >> 6) & 3;
      out[i * 4 + 1] = (b >> 4) & 3;
      out[i * 4 + 2] = (b >> 2) & 3;
      out[i * 4 + 3] = (b     ) & 3;
    }
    return out;
  }

  function base64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // Match hex_ca_step in caformer/primitives.py: parity-dependent
  // neighbours for a pointy-top hex lattice on a torus.  Key bits
  // (big-end first): self, nw, ne, e, se, sw, w  (2 bits each → 14 bits).
  function hexStep(grid, side, lut) {
    const out = new Uint8Array(side * side);
    for (let y = 0; y < side; y++) {
      const even = (y & 1) === 0;
      const yu = (y - 1 + side) % side;
      const yd = (y + 1) % side;
      for (let x = 0; x < side; x++) {
        const xl = (x - 1 + side) % side;
        const xr = (x + 1) % side;
        const s  = grid[y * side + x];
        const nw = even ? grid[yu * side + xl] : grid[yu * side + x ];
        const ne = even ? grid[yu * side + x ] : grid[yu * side + xr];
        const sw = even ? grid[yd * side + xl] : grid[yd * side + x ];
        const se = even ? grid[yd * side + x ] : grid[yd * side + xr];
        const nl = grid[y  * side + xl];
        const nr = grid[y  * side + xr];
        const key = (s  << 12) | (nw << 10) | (ne << 8)
                  | (nr << 6 ) | (se <<  4) | (sw << 2)
                  |  nl;
        out[y * side + x] = lut[key];
      }
    }
    return out;
  }

  // Pointy-top hex render: a column step of TILE pixels wide,
  // odd rows shifted +TILE/2 (matches feedback_pointytop_hex_render).
  function paintHex(ctx, grid, side, palette, cellPx) {
    const w = cellPx;
    const h = cellPx * 0.95;
    ctx.save();
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    for (let y = 0; y < side; y++) {
      const ox = (y & 1) ? w * 0.5 : 0;
      for (let x = 0; x < side; x++) {
        const c = grid[y * side + x] & 3;
        ctx.fillStyle = palette[c];
        // Hex outline:
        const cx = x * w + ox + w * 0.5;
        const cy = y * h + h * 0.5;
        const r  = w * 0.58;
        ctx.beginPath();
        for (let k = 0; k < 6; k++) {
          const a = Math.PI / 6 + k * Math.PI / 3;
          const px = cx + r * Math.cos(a);
          const py = cy + r * Math.sin(a);
          if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
      }
    }
    ctx.restore();
  }

  // Seed a 16×16 grid from an integer seed via xorshift32, picking
  // 2-bit values just like the C embed_token() does (LCG-equivalent).
  function seedGrid(side, seed) {
    let s = (seed >>> 0) || 0xCA5E1D;
    const n = side * side;
    const out = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      // xorshift32
      s ^= s << 13; s >>>= 0;
      s ^= s >>> 17;
      s ^= s << 5;  s >>>= 0;
      out[i] = (s >>> 16) & 3;
    }
    return out;
  }

  // ── HexCA: stateful renderer around a single canvas ──────────
  class HexCA {
    constructor(canvas, opts) {
      this.canvas  = canvas;
      this.ctx     = canvas.getContext('2d');
      this.side    = (opts && opts.side)    || 16;
      this.palette = (opts && opts.palette) || PALETTE_CFA;
      this.cellPx  = (opts && opts.cellPx)  || null;
      // Auto-size cellPx if not specified: fit the side to canvas width.
      if (!this.cellPx) {
        // Each row uses `side` columns + half-column shift, so width
        // budget is (side + 0.5) cells wide.
        this.cellPx = Math.floor(canvas.width / (this.side + 0.5));
      }
      this.grid = new Uint8Array(this.side * this.side);
    }
    setGrid(arr) {
      this.grid = new Uint8Array(arr);
      return this;
    }
    setGridFromSeed(seed) {
      this.grid = seedGrid(this.side, seed);
      return this;
    }
    stepWithLUT(lut, ticks) {
      ticks = ticks || 1;
      for (let t = 0; t < ticks; t++) {
        this.grid = hexStep(this.grid, this.side, lut);
      }
      return this;
    }
    stepWithPackedRule(packed, ticks) {
      return this.stepWithLUT(unpackLUT(packed), ticks);
    }
    paint() {
      paintHex(this.ctx, this.grid, this.side, this.palette, this.cellPx);
      return this;
    }
    // For diagrams: which 14-bit key would the cell at (x,y) read?
    keyAt(x, y) {
      const side = this.side;
      const grid = this.grid;
      const even = (y & 1) === 0;
      const yu = (y - 1 + side) % side;
      const yd = (y + 1) % side;
      const xl = (x - 1 + side) % side;
      const xr = (x + 1) % side;
      const s  = grid[y  * side + x ];
      const nw = even ? grid[yu * side + xl] : grid[yu * side + x ];
      const ne = even ? grid[yu * side + x ] : grid[yu * side + xr];
      const sw = even ? grid[yd * side + xl] : grid[yd * side + x ];
      const se = even ? grid[yd * side + x ] : grid[yd * side + xr];
      const nl = grid[y  * side + xl];
      const nr = grid[y  * side + xr];
      return {
        cells: {self: s, nw, ne, e: nr, se, sw, w: nl},
        key:  (s  << 12) | (nw << 10) | (ne << 8)
             | (nr << 6 ) | (se <<  4) | (sw << 2)
             |  nl,
      };
    }
  }

  // ── Rule-table stripe: paint a packed LUT as a thin colour band ─
  function paintLUTStripe(canvas, packed, palette, highlight) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
    const lut = unpackLUT(packed);
    // Each pixel column covers 16384 / w entries; paint mean colour.
    const per = 16384 / w;
    const counts = [0, 0, 0, 0];
    for (let px = 0; px < w; px++) {
      counts[0] = counts[1] = counts[2] = counts[3] = 0;
      const lo = Math.floor(px * per);
      const hi = Math.floor((px + 1) * per);
      for (let i = lo; i < hi; i++) counts[lut[i]]++;
      // Majority colour:
      let best = 0;
      for (let c = 1; c < 4; c++) if (counts[c] > counts[best]) best = c;
      ctx.fillStyle = palette[best];
      ctx.fillRect(px, 0, 1, h);
    }
    if (highlight !== undefined && highlight !== null) {
      const x = Math.floor(highlight / per);
      ctx.fillStyle = '#fff';
      ctx.fillRect(x, 0, 1, h);
      ctx.fillStyle = 'rgba(255,255,255,0.18)';
      ctx.fillRect(Math.max(0, x - 1), 0, 3, h);
    }
  }

  // ── Load a TrainedModel's rules via JSON endpoint ─────────────
  async function loadRules(slug) {
    const r = await fetch(`/caformer/rules/${encodeURIComponent(slug)}.json`,
                         {credentials: 'same-origin'});
    if (!r.ok) throw new Error(`rules fetch failed: ${r.status}`);
    const j = await r.json();
    const out = {meta: j.meta, rules: {}};
    for (const k of Object.keys(j.rules)) {
      out.rules[k] = base64ToBytes(j.rules[k]);
    }
    return out;
  }

  window.CAformerMechanism = {
    HexCA, hexStep, seedGrid, unpackLUT, base64ToBytes,
    paintLUTStripe, paintHex, loadRules,
    PALETTE_CFA, PALETTE_HEAT,
  };
})();

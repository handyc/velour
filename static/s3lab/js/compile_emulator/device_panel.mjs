// device_panel.mjs — UI for the embedded ESP32-S3 SuperMini emulator
// on /s3lab/compile/. Renders a 128×128 TFT canvas at 4× zoom, a row
// of 16 GPIO LEDs underneath, plus a status line. Slot-aware:
//
//   step()    — interpreter ticks the user's step kernel. The 16×16
//               grid is shown on the TFT (one cell per 8×8 block).
//   render()  — interpreter calls user's render() each tick; the
//               resulting RGB565 buffer is blitted to the TFT.
//   gpio()    — interpreter calls user's gpio() each tick; the 16
//               LEDs reflect the levels[0..15].
//   fitness() — interpreter calls user's fitness() once per ▶ Run;
//               score shown in the status line.
//
// The panel never spins on its own — all motion is driven by the
// caller via tick() / runN(N). State is owned by this module so the
// CA can persist across ticks.

import {
    parseProgram, runFunction, asCharPtr, InterpError,
} from './xcc_interp.mjs';


export const PANEL_W = 128;
export const PANEL_H = 128;
export const GRID_W  = 16;
export const GRID_H  = 16;

// Default genome — a slot's first arg. We don't pretend this is a
// real HXC4 layout; it's just 4096 bytes the kernel can read.
function defaultGenome(seed = 0xC0FFEE) {
    const g = new Uint8Array(4096);
    let s = seed >>> 0 || 1;
    for (let i = 0; i < g.length; i++) {
        s = (Math.imul(s, 1103515245) + 12345) >>> 0;
        g[i] = (s >>> 16) & 0xFF;
    }
    return g;
}

function defaultGrid(seed = 42) {
    const g = new Uint8Array(GRID_W * GRID_H);
    let s = seed >>> 0 || 1;
    for (let i = 0; i < g.length; i++) {
        s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
        g[i] = (s >>> 24) & 3;
    }
    return g;
}


// Default cell colours when a step kernel runs without a render()
// pair — the four K=4 ANSI palette indices that s3lab/automaton use.
const DEFAULT_PALETTE_RGB = [
    [0,   0,   0],     // 0: black
    [205, 0,   0],     // 1: red (ANSI 9)
    [205, 205, 0],     // 2: yellow (ANSI 11)
    [205, 0,   205],   // 3: magenta (ANSI 13)
];


export class DevicePanel {
    constructor(rootEl, opts = {}) {
        this.root = rootEl;
        this.zoom = opts.zoom ?? 4;
        this.canvas = null;
        this.ctx = null;
        this.gpioRow = null;
        this.statusEl = null;
        this.scoreEl = null;
        this.tickEl = null;

        // Slot kernels currently loaded.
        this.prog = null;
        this.parseError = null;
        this.activeSlot = null;          // 'step' | 'render' | 'gpio' | 'fitness'

        // Simulation state (4 KiB genome, two grids, RGB565 buf, GPIO levels).
        this.genome  = defaultGenome();
        this.gridA   = defaultGrid();
        this.gridB   = new Uint8Array(GRID_W * GRID_H);
        this.rgb565  = new Uint8Array(GRID_W * GRID_H * 2);
        this.levels  = new Uint8Array(64);

        // For render-slot use, keep a previous-grid copy.
        this.gridPrev = new Uint8Array(GRID_W * GRID_H);

        this.tickCount = 0;
        this.lastError = null;
        this.lastScore = null;
        this._mountUI();
    }

    _mountUI() {
        const cssZoom = this.zoom;
        const W = PANEL_W * cssZoom;
        const H = PANEL_H * cssZoom;
        this.root.innerHTML = `
          <div style="display:flex; flex-direction:column; gap:0.5rem; align-items:flex-start;">
            <div style="background:#0d1117; border:1px solid #30363d; padding:0.6rem;
                        border-radius:5px; display:inline-block;">
              <div style="font-family:ui-monospace,monospace; font-size:0.65rem;
                          color:#6e7681; letter-spacing:0.05em; margin-bottom:0.3rem;">
                ESP32-S3 SUPERMINI · ST7735 1.44″ 128×128 (emulated)
              </div>
              <canvas class="emu-tft" width="${PANEL_W}" height="${PANEL_H}"
                      style="width:${W}px; height:${H}px;
                             image-rendering:pixelated; image-rendering:crisp-edges;
                             background:#000; border:1px solid #21262d;
                             display:block;"></canvas>
              <div class="emu-gpio-row" style="display:flex; gap:3px;
                          margin-top:0.5rem; align-items:center;
                          font-family:ui-monospace,monospace; font-size:0.6rem;
                          color:#6e7681;">
                <span style="margin-right:0.4rem;">GPIO:</span>
              </div>
            </div>
            <div class="emu-status" style="font-family:ui-monospace,monospace;
                        font-size:0.78rem; color:#8b949e;
                        min-height:1.1rem;">idle</div>
            <div class="emu-controls" style="display:flex; gap:0.4rem; align-items:center;
                        flex-wrap:wrap;">
              <button class="emu-tick" style="background:#1f6feb; color:#fff;
                      border:0; padding:0.3rem 0.7rem; border-radius:3px;
                      cursor:pointer; font-family:inherit; font-size:0.85rem;"
                      title="Run the active slot once. For step kernels: advance one CA tick. For render/gpio: re-invoke. For fitness: re-score.">▶ Tick</button>
              <button class="emu-runn" style="background:#238636; color:#fff;
                      border:0; padding:0.3rem 0.7rem; border-radius:3px;
                      cursor:pointer; font-family:inherit; font-size:0.85rem;"
                      title="Run N ticks back-to-back (default 30 — fast enough to see motion).">▶ Run 30</button>
              <button class="emu-reset" style="background:#21262d; color:#c9d1d9;
                      border:1px solid #30363d; padding:0.3rem 0.7rem; border-radius:3px;
                      cursor:pointer; font-family:inherit; font-size:0.85rem;"
                      title="Re-seed genome + grid + clear GPIO state.">Reset</button>
              <span style="color:#6e7681; font-size:0.75rem; margin-left:0.5rem;">tick</span>
              <span class="emu-tickcount" style="color:#7ee787; font-family:ui-monospace,monospace;">0</span>
              <span class="emu-score" style="color:#79c0ff; font-family:ui-monospace,monospace; margin-left:0.5rem;"></span>
            </div>
          </div>
        `;
        this.canvas = this.root.querySelector('.emu-tft');
        this.ctx = this.canvas.getContext('2d');
        this.gpioRow = this.root.querySelector('.emu-gpio-row');
        this.statusEl = this.root.querySelector('.emu-status');
        this.scoreEl = this.root.querySelector('.emu-score');
        this.tickEl = this.root.querySelector('.emu-tickcount');

        // 16 LED pips
        for (let i = 0; i < 16; i++) {
            const led = document.createElement('span');
            led.className = 'emu-led';
            led.dataset.idx = String(i);
            led.style.cssText = `display:inline-block; width:0.7rem; height:0.7rem;
                background:#161b22; border:1px solid #30363d; border-radius:50%;
                transition:background 80ms;`;
            led.title = `gpio[${i}]`;
            this.gpioRow.appendChild(led);
        }

        this.root.querySelector('.emu-tick').addEventListener('click', () => this.tick());
        this.root.querySelector('.emu-runn').addEventListener('click', () => this.runN(30));
        this.root.querySelector('.emu-reset').addEventListener('click', () => this.reset());

        this.repaint();
    }

    setSlot(name) { this.activeSlot = name; this.setStatus(`active slot: ${name || '?'}`); }

    loadSource(src) {
        this.parseError = null;
        try {
            this.prog = parseProgram(src);
        } catch (e) {
            this.prog = null;
            this.parseError = e.message;
            this.setStatus(`parse error · ${e.message}`, 'err');
            return false;
        }
        // Pick a slot automatically if the user hasn't said otherwise.
        if (!this.activeSlot) {
            for (const s of ['step', 'render', 'gpio', 'fitness']) {
                if (this.prog.functions.has(s)) { this.activeSlot = s; break; }
            }
        }
        this.setStatus(
            `parsed · functions: ${[...this.prog.functions.keys()].join(', ')}`,
            'ok'
        );
        return true;
    }

    reset() {
        this.genome  = defaultGenome();
        this.gridA   = defaultGrid();
        this.gridB.fill(0);
        this.gridPrev.fill(0);
        this.rgb565.fill(0);
        this.levels.fill(0);
        this.tickCount = 0;
        this.lastScore = null;
        this.repaint();
    }

    tick() {
        if (!this.prog) {
            if (this.parseError) {
                this.setStatus(`can't tick: ${this.parseError}`, 'err');
            } else {
                this.setStatus('no program loaded', 'err');
            }
            return;
        }
        const slot = this.activeSlot;
        if (!slot || !this.prog.functions.has(slot)) {
            this.setStatus(`slot '${slot}' not in source`, 'err');
            return;
        }
        try {
            if (slot === 'step') {
                this.gridPrev.set(this.gridA);
                runFunction(this.prog, 'step',
                    [asCharPtr(this.genome), asCharPtr(this.gridA), asCharPtr(this.gridB)]);
                const tmp = this.gridA; this.gridA = this.gridB; this.gridB = tmp;
            } else if (slot === 'render') {
                this.rgb565.fill(0xFF);  // pre-fill SKIP so render can no-op cells
                runFunction(this.prog, 'render',
                    [asCharPtr(this.gridPrev), asCharPtr(this.gridA), asCharPtr(this.rgb565)]);
            } else if (slot === 'gpio') {
                this.levels.fill(0);
                runFunction(this.prog, 'gpio',
                    [asCharPtr(this.gridA), asCharPtr(this.levels)]);
            } else if (slot === 'fitness') {
                const score = runFunction(this.prog, 'fitness',
                    [asCharPtr(this.genome), 42 | 0]);
                this.lastScore = score | 0;
            }
            this.tickCount++;
            this.lastError = null;
            this.setStatus(`ok · slot=${slot} tick=${this.tickCount}`, 'ok');
        } catch (e) {
            const msg = e instanceof InterpError ? e.message : `${e.name || 'Error'}: ${e.message}`;
            this.lastError = msg;
            this.setStatus(`runtime · ${msg}`, 'err');
        }
        this.repaint();
    }

    runN(n) {
        for (let k = 0; k < n; k++) {
            if (this.lastError) break;
            this.tick();
        }
    }

    setStatus(msg, kind) {
        if (!this.statusEl) return;
        this.statusEl.textContent = msg;
        this.statusEl.style.color =
            kind === 'err' ? '#f85149' :
            kind === 'ok'  ? '#3fb950' :
                             '#8b949e';
    }

    repaint() {
        this._paintTft();
        this._paintGpio();
        if (this.tickEl) this.tickEl.textContent = this.tickCount;
        if (this.scoreEl) {
            this.scoreEl.textContent = (this.lastScore !== null)
                ? `score=${this.lastScore} (=${(this.lastScore / 10000).toFixed(3)})`
                : '';
        }
    }

    _paintTft() {
        // For render slot, blit rgb565 directly. Otherwise, render the
        // gridA via the default palette.
        const im = this.ctx.createImageData(PANEL_W, PANEL_H);
        const buf = new Uint32Array(im.data.buffer);
        if (this.activeSlot === 'render') {
            // 16×16 cells, each rgb565 colour → fill 8×8 block.
            for (let cy = 0; cy < GRID_H; cy++) {
                for (let cx = 0; cx < GRID_W; cx++) {
                    const idx = (cy * GRID_W + cx) * 2;
                    const lo = this.rgb565[idx];
                    const hi = this.rgb565[idx + 1];
                    if (lo === 0xFF && hi === 0xFF) continue;  // SKIP
                    const px565 = (hi << 8) | lo;
                    const r = ((px565 >> 11) & 0x1F) << 3;
                    const g = ((px565 >> 5) & 0x3F) << 2;
                    const b = (px565 & 0x1F) << 3;
                    const c = (0xFF << 24) | (b << 16) | (g << 8) | r;
                    fillBlock(buf, PANEL_W, cx * 8, cy * 8, 8, 8, c);
                }
            }
        } else {
            for (let cy = 0; cy < GRID_H; cy++) {
                for (let cx = 0; cx < GRID_W; cx++) {
                    const v = this.gridA[cy * GRID_W + cx] & 3;
                    const [r, g, b] = DEFAULT_PALETTE_RGB[v];
                    const c = (0xFF << 24) | (b << 16) | (g << 8) | r;
                    fillBlock(buf, PANEL_W, cx * 8, cy * 8, 8, 8, c);
                }
            }
        }
        this.ctx.putImageData(im, 0, 0);
    }

    _paintGpio() {
        const leds = this.gpioRow.querySelectorAll('.emu-led');
        for (let i = 0; i < leds.length; i++) {
            const on = this.levels[i] !== 0;
            leds[i].style.background = on ? '#3fb950' : '#161b22';
            leds[i].style.boxShadow = on ? '0 0 6px #3fb950' : 'none';
        }
    }
}


function fillBlock(buf, bufW, x, y, w, h, c) {
    for (let dy = 0; dy < h; dy++) {
        const row = (y + dy) * bufW;
        for (let dx = 0; dx < w; dx++) {
            buf[row + x + dx] = c;
        }
    }
}

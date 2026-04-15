// Evolution UI — wires the engine to a live page.
//
// Renders: a control bar (run/pause/step/speed/save-best),
//          a sparkline of best/mean per generation,
//          a grid of agent cards with click-to-save.

export class EvolutionUI {
    constructor({ root, engine, csrfToken, runId, onSaved }) {
        this.root = root;
        this.engine = engine;
        this.csrfToken = csrfToken;
        this.runId = runId;
        this.onSaved = onSaved || null;

        this.running = false;
        this.tickDelayMs = 0;
        this._raf = null;

        this._build();
        this._wire();
        this._paintAll();
    }

    _build() {
        this.root.innerHTML = `
          <div class="ev-bar">
            <button class="ev-btn primary" data-act="run">▶ Run</button>
            <button class="ev-btn" data-act="step">Step</button>
            <button class="ev-btn" data-act="reset">Reset</button>
            <label class="ev-lbl">speed
              <select data-ctl="speed">
                <option value="0">max</option>
                <option value="50">fast</option>
                <option value="200" selected>medium</option>
                <option value="600">slow</option>
              </select>
            </label>
            <button class="ev-btn primary" data-act="save-best">Save best</button>
            <span class="ev-stats">
              gen <b data-stat="gen">0</b> · best
              <b data-stat="best">0.000</b> · mean
              <b data-stat="mean">0.000</b>
            </span>
          </div>
          <canvas class="ev-spark" width="900" height="80"></canvas>
          <div class="ev-grid"></div>
          <div class="ev-log"></div>
        `;
        this.gridEl  = this.root.querySelector('.ev-grid');
        this.logEl   = this.root.querySelector('.ev-log');
        this.sparkEl = this.root.querySelector('.ev-spark');
        this.statGen  = this.root.querySelector('[data-stat=gen]');
        this.statBest = this.root.querySelector('[data-stat=best]');
        this.statMean = this.root.querySelector('[data-stat=mean]');
    }

    _wire() {
        this.root.querySelector('[data-act=run]').addEventListener('click',
            () => this.toggleRun());
        this.root.querySelector('[data-act=step]').addEventListener('click',
            () => this._step());
        this.root.querySelector('[data-act=reset]').addEventListener('click',
            () => { this.engine.init(); this._paintAll(); });
        this.root.querySelector('[data-act=save-best]').addEventListener('click',
            () => this.saveAgent(this.engine.best));
        this.root.querySelector('[data-ctl=speed]').addEventListener('change',
            (e) => { this.tickDelayMs = +e.target.value; });

        this.engine.onGeneration = () => this._paintLive();
        this.engine.onLog = (entry) => this._appendLog(entry);
    }

    toggleRun() {
        this.running = !this.running;
        const btn = this.root.querySelector('[data-act=run]');
        btn.textContent = this.running ? '⏸ Pause' : '▶ Run';
        if (this.running) this._loop();
    }

    async _step() {
        await this.engine.tick();
        this._reportRun();
    }

    async _loop() {
        while (this.running && !this.engine.isDone()) {
            await this.engine.tick();
            this._reportRun();
            if (this.tickDelayMs > 0) {
                await new Promise(r => setTimeout(r, this.tickDelayMs));
            } else {
                await new Promise(r => setTimeout(r, 0));
            }
        }
        if (this.engine.isDone() && this.running) {
            this.running = false;
            this.root.querySelector('[data-act=run]').textContent = '▶ Run';
            this._reportRun('finished');
        }
    }

    _paintAll() {
        this._paintLive();
        this._paintSpark();
    }

    _paintLive() {
        this.statGen.textContent = this.engine.generation;
        this.statBest.textContent = this.engine.bestScore.toFixed(3);
        const last = this.engine.history.length
            ? this.engine.history[this.engine.history.length - 1]
            : null;
        this.statMean.textContent = last ? last.mean.toFixed(3) : '0.000';
        this._paintGrid();
        this._paintSpark();
    }

    _paintGrid() {
        const cards = this.engine.population.map((a, i) => {
            const score = (a.score || 0).toFixed(3);
            const previewSrc = (a.output || '');
            const preview = escapeHtml(previewSrc.slice(0, 80))
                + (previewSrc.length > 80 ? '…' : '');
            const elite = i === 0 ? ' ev-elite' : '';
            return `
              <div class="ev-card${elite}" data-idx="${i}">
                <div class="ev-card-head">
                  <span class="ev-name">${escapeHtml(a.name)}</span>
                  <span class="ev-score">${score}</span>
                </div>
                <div class="ev-out"><code>${preview || '—'}</code></div>
                <div class="ev-actions">
                  <button class="ev-btn small" data-save="${i}">save</button>
                </div>
              </div>`;
        }).join('');
        this.gridEl.innerHTML = cards;
        this.gridEl.querySelectorAll('[data-save]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = +e.target.getAttribute('data-save');
                this.saveAgent(this.engine.population[idx]);
            });
        });
    }

    _paintSpark() {
        const c = this.sparkEl;
        const ctx = c.getContext('2d');
        const W = c.width, H = c.height;
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#0b1018'; ctx.fillRect(0, 0, W, H);
        const h = this.engine.history;
        if (!h.length) return;
        const xs = h.length;
        const dx = W / Math.max(1, xs - 1 || 1);
        const draw = (key, color) => {
            ctx.strokeStyle = color; ctx.lineWidth = 1.5;
            ctx.beginPath();
            for (let i = 0; i < h.length; i++) {
                const v = h[i][key];
                const x = i * dx;
                const y = H - v * (H - 6) - 3;
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
        };
        draw('mean', '#6c8aa6');
        draw('best', '#58a6ff');
        // target line
        ctx.strokeStyle = '#445'; ctx.setLineDash([3, 4]);
        const ty = H - this.engine.targetScore * (H - 6) - 3;
        ctx.beginPath(); ctx.moveTo(0, ty); ctx.lineTo(W, ty); ctx.stroke();
        ctx.setLineDash([]);
    }

    _appendLog(entry) {
        const row = document.createElement('div');
        row.className = 'ev-log-row';
        row.innerHTML =
            `<span class="g">gen ${entry.gen}</span> ` +
            `<span class="b">best ${entry.best.toFixed(3)}</span> ` +
            `<span class="m">mean ${entry.mean.toFixed(3)}</span> ` +
            `<span class="n">↑ ${escapeHtml(entry.elite_name || '')}</span>`;
        this.logEl.prepend(row);
        // keep log bounded
        while (this.logEl.children.length > 60) {
            this.logEl.removeChild(this.logEl.lastChild);
        }
    }

    _reportRun(forceStatus) {
        if (!this.runId) return;
        const status = forceStatus
            || (this.running ? 'running' : (this.engine.isDone() ? 'finished' : 'paused'));
        // throttle: only every ~10 generations or status change
        if (!forceStatus && this.engine.generation % 10 !== 0) return;
        fetch(`/evolution/runs/${this.runId}/update/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken,
            },
            body: JSON.stringify({
                generation: this.engine.generation,
                best_score: this.engine.bestScore,
                status,
            }),
        }).catch(() => {});
    }

    async saveAgent(agent) {
        if (!agent) return;
        const snap = agent.snapshot();
        const body = {
            name: `${this.engine.run?.name || 'run'}-g${this.engine.generation}-${snap.name}`,
            level: snap.level,
            gene: snap.gene,
            seed_string: snap.seed_string,
            script: snap.script,
            score: snap.score,
            run_slug: this.runId,
        };
        try {
            const r = await fetch('/evolution/agents/save/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify(body),
            });
            if (!r.ok) {
                this._toast(`save failed (${r.status})`, 'err');
                return;
            }
            const j = await r.json();
            if (j.ok) {
                this._appendLog({
                    gen: this.engine.generation, best: snap.score, mean: 0,
                    elite_name: `saved: ${j.name}`,
                });
                this._toast(j.name, 'ok', j.url);
                if (this.onSaved) this.onSaved(j);
            } else {
                this._toast(`save failed: ${j.error || 'unknown'}`, 'err');
            }
        } catch (e) {
            this._toast(`save failed: ${e.message || e}`, 'err');
        }
    }

    _toast(msg, kind = 'ok', href = null) {
        let host = this.root.querySelector('.ev-toasts');
        if (!host) {
            host = document.createElement('div');
            host.className = 'ev-toasts';
            this.root.appendChild(host);
        }
        const el = document.createElement('div');
        el.className = `ev-toast ev-toast-${kind}`;
        if (href) {
            el.innerHTML = `saved → <a href="${href}" target="_blank">${escapeHtml(msg)}</a>`;
        } else {
            el.textContent = msg;
        }
        host.appendChild(el);
        setTimeout(() => { el.classList.add('ev-toast-fade'); }, 3000);
        setTimeout(() => { el.remove(); }, 4200);
    }
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
}

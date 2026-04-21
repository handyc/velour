/* Grammar Engine — Language Inspector.
 *
 * Mounts on a `.gi-backdrop` modal (see _inspector.html), reads and writes
 * a GrammarEngine instance you pass in. Tabs:
 *   - L-System Rules: edit per-kind grammar JSON
 *   - Phonic Particles: add / delete / nudge particle timing
 *   - Subwords: add / re-translate / delete
 *   - Words: search / edit chain / delete / add random
 *   - Live Stats: counts, top-N, and a scrolling utterance log
 *
 * Usage (module):
 *   import { Inspector } from '/static/grammar_engine/inspector.mjs';
 *   import { GrammarEngine, LSystem } from '/static/grammar_engine/engine.mjs';
 *   const engine = new GrammarEngine({ seed: 12345 });
 *   const insp = new Inspector({
 *       root: document.getElementById('gi-backdrop'),
 *       engine, LSystem,
 *   });
 *   insp.wireOpener(document.getElementById('grammar-toggle'));
 */

export class Inspector {
    constructor(options) {
        const o = options || {};
        this.root = o.root;
        if (!this.root) throw new Error('Inspector: options.root is required');
        this.engine = o.engine || null;
        // The LSystem class is passed in so "Sample" can show a live expansion
        // without the Inspector knowing how to import from engine.mjs.
        this.LSystem = o.LSystem || null;

        this.activeTab = 'grammar';
        this.statsTimer = null;
        this._chainedOnLog = null;

        // Per-tab continuous-evolve state. Persists across pane
        // re-renders so the checkboxes stay consistent.
        this.evolveState = {
            particles: { continuous: false, intervalSec: 10, timer: null,
                         method: 'evolveParticles', render: '_renderParticles' },
            subwords:  { continuous: false, intervalSec: 10, timer: null,
                         method: 'evolveSubwords',  render: '_renderSubwords' },
            words:     { continuous: false, intervalSec: 10, timer: null,
                         method: 'evolveWords',     render: '_renderWords' },
            grammar:   { continuous: false, intervalSec: 30, timer: null,
                         method: 'evolveGrammars',  render: '_renderGrammar' },
        };

        this._panes = {
            grammar:   this.root.querySelector('#gi-pane-grammar'),
            particles: this.root.querySelector('#gi-pane-particles'),
            subwords:  this.root.querySelector('#gi-pane-subwords'),
            words:     this.root.querySelector('#gi-pane-words'),
            stats:     this.root.querySelector('#gi-pane-stats'),
        };
        this._tabs = this.root.querySelectorAll('.gi-tab');
        this._closeBtn = this.root.querySelector('#gi-close');

        this._wireChrome();
        if (this.engine) this._hookEngineLog();
    }

    // ── Engine binding ──────────────────────────────────────────
    setEngine(engine) {
        this._unhookEngineLog();
        this.engine = engine;
        if (this.engine) this._hookEngineLog();
        if (this.root.classList.contains('open')) this.render(this.activeTab);
    }
    _hookEngineLog() {
        // Chain onto any existing onLog handler rather than clobbering it.
        this._chainedOnLog = this.engine.onLog || null;
        this.engine.onLog = (entry) => {
            if (this._chainedOnLog) this._chainedOnLog(entry);
            this._onLogEntry(entry);
        };
    }
    _unhookEngineLog() {
        if (!this.engine) return;
        this.engine.onLog = this._chainedOnLog;
        this._chainedOnLog = null;
    }

    // ── Open / close / tabs ─────────────────────────────────────
    _wireChrome() {
        this._closeBtn.addEventListener('click', () => this.close());
        this.root.addEventListener('click', (e) => {
            if (e.target === this.root) this.close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.root.classList.contains('open')) this.close();
        });
        this._tabs.forEach(t => t.addEventListener('click', () => {
            this._tabs.forEach(x => x.classList.remove('active'));
            t.classList.add('active');
            Object.values(this._panes).forEach(p => p.classList.remove('active'));
            this.activeTab = t.dataset.tab;
            this._panes[this.activeTab].classList.add('active');
            this.render(this.activeTab);
            if (this.activeTab === 'stats') this._startStatsTimer();
            else this._stopStatsTimer();
        }));
    }
    wireOpener(btn) {
        if (!btn) return;
        btn.addEventListener('click', () => this.open());
    }
    open() {
        this.root.classList.add('open');
        this.render(this.activeTab);
        if (this.activeTab === 'stats') this._startStatsTimer();
        for (const tab of Object.keys(this.evolveState)) {
            if (this.evolveState[tab].continuous) this._startEvolveTimer(tab);
        }
    }
    close() {
        this.root.classList.remove('open');
        this._stopStatsTimer();
        for (const tab of Object.keys(this.evolveState)) this._stopEvolveTimer(tab);
    }
    _startStatsTimer() {
        this._stopStatsTimer();
        this.statsTimer = setInterval(() => this.render('stats'), 1000);
    }
    _stopStatsTimer() {
        if (this.statsTimer) { clearInterval(this.statsTimer); this.statsTimer = null; }
    }
    _startEvolveTimer(tab) {
        const st = this.evolveState[tab];
        if (!st) return;
        this._stopEvolveTimer(tab);
        const ms = Math.max(1, st.intervalSec) * 1000;
        st.timer = setInterval(() => {
            if (!this.engine) return;
            this.engine[st.method]();
            if (this.activeTab === tab && this.root.classList.contains('open')) {
                this[st.render]();
            }
        }, ms);
    }
    _stopEvolveTimer(tab) {
        const st = this.evolveState[tab];
        if (st && st.timer) { clearInterval(st.timer); st.timer = null; }
    }

    // Render the "Run evolve cycle now · continuous · every N s" strip
    // that every evolvable tab shares. Call with the tab key and the
    // toolbar element the controls should be appended to.
    _wireEvolveControls(tab, toolbar) {
        const st = this.evolveState[tab];
        if (!st) return;
        const wrap = document.createElement('span');
        wrap.style.cssText = 'display:inline-flex;gap:0.4rem;align-items:center;';
        wrap.innerHTML = `
            <button class="gi-btn gi-ev-run">Run evolve cycle now</button>
            <label style="display:inline-flex;gap:0.3rem;align-items:center;
                    color:#8b95a0;font-size:0.78rem;">
                <input type="checkbox" class="gi-ev-cont">
                continuous · every
                <input type="number" class="gi-ev-sec" min="1" max="3600"
                       style="width:4rem;padding:0.15rem 0.3rem;">
                s
                <span class="gi-ev-status" style="color:#6e7681;"></span>
            </label>
        `;
        toolbar.appendChild(wrap);
        const btn = wrap.querySelector('.gi-ev-run');
        const cb = wrap.querySelector('.gi-ev-cont');
        const sec = wrap.querySelector('.gi-ev-sec');
        const status = wrap.querySelector('.gi-ev-status');
        cb.checked = st.continuous;
        sec.value = st.intervalSec;
        const refresh = () => { status.textContent = st.continuous ? '· running' : ''; };
        refresh();
        btn.onclick = () => {
            if (!this.engine) return;
            this.engine[st.method]();
            this[st.render]();
        };
        cb.addEventListener('change', () => {
            st.continuous = cb.checked;
            if (st.continuous) this._startEvolveTimer(tab);
            else this._stopEvolveTimer(tab);
            refresh();
        });
        sec.addEventListener('change', () => {
            const v = parseInt(sec.value, 10);
            if (!Number.isFinite(v) || v < 1) { sec.value = st.intervalSec; return; }
            st.intervalSec = Math.min(3600, v);
            sec.value = st.intervalSec;
            if (st.continuous) this._startEvolveTimer(tab);
        });
    }

    render(tab) {
        if (!this.engine) {
            Object.values(this._panes).forEach(p => {
                p.innerHTML = '<div style="color:#8b95a0;padding:1rem;">' +
                              'No engine attached.</div>';
            });
            return;
        }
        if (tab === 'grammar')        this._renderGrammar();
        else if (tab === 'particles') this._renderParticles();
        else if (tab === 'subwords')  this._renderSubwords();
        else if (tab === 'words')     this._renderWords();
        else if (tab === 'stats')     this._renderStats();
    }

    // ── Grammar tab ────────────────────────────────────────────
    _renderGrammar() {
        const engine = this.engine;
        const pane = this._panes.grammar;
        pane.innerHTML = '';
        const header = document.createElement('div');
        header.style.marginBottom = '0.8rem';
        header.style.fontSize = '0.72rem';
        header.style.color = '#8b95a0';
        header.innerHTML = 'Rules are applied for <b>iterations</b> passes over '
            + 'the <b>axiom</b>. A value that is a <b>string</b> expands to that '
            + 'string; a value that is an <b>array</b> picks one entry at '
            + 'expansion time. Edit the JSON and click <b>Apply</b>. '
            + 'Evolve cycle spawns a mutated child variant under each grammar, '
            + 'seeded from its most-used variant(s).';
        pane.appendChild(header);
        const evBar = document.createElement('div');
        evBar.className = 'gi-toolbar gi-ev-bar';
        evBar.style.marginBottom = '0.8rem';
        pane.appendChild(evBar);
        this._wireEvolveControls('grammar', evBar);

        const LSystem = this.LSystem;
        const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];

        for (const [kind, grammar] of Object.entries(engine.SPEECH_GRAMMARS)) {
            const box = document.createElement('div');
            box.className = 'gi-grammar';
            box.innerHTML = `
                <div class="gi-grammar-head">
                    <span class="gname">${kind}</span>
                    <span style="color:#566270;font-size:0.7rem;">
                        axiom=<b>${grammar.axiom}</b>
                        · iter=<b>${grammar.iterations}</b>
                    </span>
                    <div class="gnote">${grammar.note || ''}</div>
                </div>
            `;
            for (const [vname, rules] of Object.entries(grammar.variants)) {
                const v = document.createElement('div');
                v.className = 'gi-variant';
                const json = JSON.stringify(rules, null, 2);
                v.innerHTML = `
                    <div class="gi-variant-name">${vname}</div>
                    <textarea class="gi-rules-editor" rows="${json.split('\n').length}"></textarea>
                    <div class="gi-actions">
                        <button class="gi-btn primary" data-action="apply">Apply</button>
                        <button class="gi-btn" data-action="sample">Sample</button>
                        <button class="gi-btn" data-action="reset">Revert</button>
                        <span class="gi-msg"></span>
                    </div>
                `;
                const ta = v.querySelector('textarea');
                ta.value = json;
                const msg = v.querySelector('.gi-msg');
                const original = json;
                v.querySelector('[data-action=apply]').onclick = () => {
                    try {
                        const parsed = JSON.parse(ta.value);
                        grammar.variants[vname] = parsed;
                        ta.classList.remove('bad');
                        msg.textContent = 'Applied.';
                        msg.className = 'gi-msg ok';
                    } catch (e) {
                        ta.classList.add('bad');
                        msg.textContent = 'Bad JSON: ' + e.message;
                        msg.className = 'gi-msg bad';
                    }
                };
                v.querySelector('[data-action=sample]').onclick = () => {
                    try {
                        const parsed = JSON.parse(ta.value);
                        const resolved = {};
                        for (const [k, val] of Object.entries(parsed)) {
                            resolved[k] = Array.isArray(val) ? pick(val) : val;
                        }
                        if (!LSystem) {
                            msg.textContent = 'Sampler unavailable (no LSystem passed).';
                            msg.className = 'gi-msg bad';
                            return;
                        }
                        const out = new LSystem(
                            grammar.axiom || 'S', resolved,
                            grammar.iterations || 4).expand();
                        msg.textContent = 'Sample: ' + out;
                        msg.className = 'gi-msg ok';
                    } catch (e) {
                        msg.textContent = 'Bad JSON: ' + e.message;
                        msg.className = 'gi-msg bad';
                    }
                };
                v.querySelector('[data-action=reset]').onclick = () => {
                    ta.value = original;
                    ta.classList.remove('bad');
                    msg.textContent = 'Reverted (textarea only — click Apply to commit).';
                    msg.className = 'gi-msg';
                };
                box.appendChild(v);
            }
            pane.appendChild(box);
        }
    }

    // ── Particles tab ──────────────────────────────────────────
    _renderParticles() {
        const engine = this.engine;
        const PARTICLES = engine.PARTICLES;
        const SUBWORDS = engine.SUBWORDS;
        const PARTICLE_CAP = engine.limits.PARTICLE_CAP;
        const PARTICLE_MIN = engine.limits.PARTICLE_MIN;
        const pane = this._panes.particles;
        pane.innerHTML = `
            <div class="gi-toolbar">
                <select class="gi-pp-type">
                    <option value="V">V (long vowel)</option>
                    <option value="v">v (short vowel)</option>
                    <option value="n">n (nasal)</option>
                    <option value="l">l (liquid)</option>
                    <option value="C">C (consonant)</option>
                    <option value="s">s (sibilant)</option>
                    <option value="p">p (plosive)</option>
                </select>
                <button class="gi-btn primary gi-pp-add">Add particle</button>
                <span class="gi-count"></span>
            </div>
            <div class="gi-toolbar gi-ev-bar"></div>
            <table class="gi-table">
                <thead><tr>
                    <th>ID</th><th>Type</th><th>Dur (ms)</th>
                    <th>Offset</th><th>F1 / F2 (Hz)</th>
                    <th>Used</th><th>Age (s)</th><th></th>
                </tr></thead>
                <tbody class="gi-pp-body"></tbody>
            </table>
        `;
        const body = pane.querySelector('.gi-pp-body');
        const countEl = pane.querySelector('.gi-count');
        const now = Date.now();
        countEl.textContent =
            `${PARTICLES.length} particles · cap ${PARTICLE_CAP} · floor ${PARTICLE_MIN}`;
        const sorted = [...PARTICLES].sort((a, b) => b.useCount - a.useCount);
        sorted.slice(0, 400).forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="id">${p.id}</td>
                <td class="pat">${p.type}</td>
                <td><input type="number" step="1" min="5" max="200"
                     value="${Math.round(p.dur * 1000)}" style="width:4.5em"></td>
                <td><input type="number" step="0.01" min="0" max="1"
                     value="${p.offsetFrac.toFixed(2)}" style="width:4.5em"></td>
                <td style="color:#566270;font-size:0.75rem">
                    ${Math.round(p.bp1Freq)} / ${Math.round(p.bp2Freq)}
                </td>
                <td class="use">${p.useCount}</td>
                <td>${((now - p.born) / 1000).toFixed(0)}</td>
                <td><button class="row-del" title="Delete this particle">✕</button></td>
            `;
            const [durI, offI] = tr.querySelectorAll('input');
            durI.addEventListener('change', () => {
                const v = parseFloat(durI.value);
                if (!isNaN(v) && v >= 5 && v <= 500) p.dur = v / 1000;
            });
            offI.addEventListener('change', () => {
                const v = parseFloat(offI.value);
                if (!isNaN(v) && v >= 0 && v <= 1) p.offsetFrac = v;
            });
            tr.querySelector('.row-del').onclick = () => {
                const idx = PARTICLES.indexOf(p);
                if (idx < 0) return;
                PARTICLES.splice(idx, 1);
                // Repair subword references: any subword pointing at
                // the deleted particle gets a same-type replacement.
                const idMap = new Map();
                PARTICLES.forEach((pp, i) => { idMap.set(pp.id, i); });
                PARTICLES.forEach((pp, i) => { pp.id = i; });
                for (const s of SUBWORDS) {
                    s.particleIds = s.particleIds.map(oldId => {
                        if (idMap.has(oldId)) return idMap.get(oldId);
                        const pool = PARTICLES.filter(pp => pp.type === p.type);
                        if (pool.length) return pool[
                            Math.floor(Math.random() * pool.length)].id;
                        return Math.floor(Math.random() * PARTICLES.length);
                    });
                    s.pattern = s.particleIds
                        .map(i => (PARTICLES[i] || {type:'?'}).type).join('');
                }
                this._renderParticles();
            };
            body.appendChild(tr);
        });

        pane.querySelector('.gi-pp-add').onclick = () => {
            if (PARTICLES.length >= PARTICLE_CAP) {
                alert('Particle cap reached (' + PARTICLE_CAP + ').'); return;
            }
            const t = pane.querySelector('.gi-pp-type').value;
            engine.addParticle(t);
            this._renderParticles();
        };
        this._wireEvolveControls('particles', pane.querySelector('.gi-ev-bar'));
    }

    // ── Subwords tab ───────────────────────────────────────────
    _renderSubwords() {
        const engine = this.engine;
        const SUBWORDS = engine.SUBWORDS;
        const WORDS = engine.WORDS;
        const PARTICLES = engine.PARTICLES;
        const SUBWORD_CAP = engine.limits.SUBWORD_CAP;
        const SUBWORD_MIN = engine.limits.SUBWORD_MIN;
        const pane = this._panes.subwords;
        pane.innerHTML = `
            <div class="gi-toolbar">
                <input type="text" class="gi-sub-new" placeholder="new pattern (e.g. nVl)" />
                <button class="gi-btn primary gi-sub-add">Add</button>
                <span class="gi-count"></span>
            </div>
            <div class="gi-toolbar gi-ev-bar"></div>
            <table class="gi-table">
                <thead><tr>
                    <th>ID</th><th>Pattern</th><th>Particles</th><th>Used</th>
                    <th>Age (s)</th><th></th>
                </tr></thead>
                <tbody class="gi-sub-body"></tbody>
            </table>
        `;
        const body = pane.querySelector('.gi-sub-body');
        const countEl = pane.querySelector('.gi-count');
        const now = Date.now();
        const sorted = [...SUBWORDS].sort((a, b) => b.useCount - a.useCount);
        countEl.textContent =
            `${SUBWORDS.length} subwords · cap ${SUBWORD_CAP} · floor ${SUBWORD_MIN}`;
        sorted.slice(0, 400).forEach(s => {
            const tr = document.createElement('tr');
            const chainTxt = s.particleIds.map(
                pid => (PARTICLES[pid] || {type:'?'}).type + '#' + pid
            ).join(' · ');
            tr.innerHTML = `
                <td class="id">${s.id}</td>
                <td><input type="text" value="${s.pattern}"></td>
                <td style="color:#566270;font-size:0.75rem">${chainTxt}</td>
                <td class="use">${s.useCount}</td>
                <td>${((now - s.born) / 1000).toFixed(0)}</td>
                <td><button class="row-del" title="Delete this subword">✕</button></td>
            `;
            const input = tr.querySelector('input');
            input.addEventListener('change', () => {
                const v = input.value.trim();
                if (!v) { input.value = s.pattern; return; }
                // Re-translate pattern → fresh particleIds via the engine's
                // popularity-weighted picker.
                const newIds = [];
                const PDUR = this.engine.constructor.PARTICLE_DUR;
                for (const ch of v) {
                    if (!PDUR[ch]) continue;
                    newIds.push(engine._pickPopularParticleOfType(ch).id);
                }
                if (newIds.length === 0) { input.value = s.pattern; return; }
                s.particleIds = newIds;
                s.pattern = newIds
                    .map(i => (PARTICLES[i] || {type:'?'}).type).join('');
                this._renderSubwords();
            });
            tr.querySelector('.row-del').onclick = () => {
                const idx = SUBWORDS.indexOf(s);
                if (idx < 0) return;
                SUBWORDS.splice(idx, 1);
                const idMap = new Map();
                SUBWORDS.forEach((ss, i) => { idMap.set(ss.id, i); });
                SUBWORDS.forEach((ss, i) => { ss.id = i; });
                for (const w of WORDS) {
                    w.subIds = w.subIds.map(id =>
                        idMap.has(id) ? idMap.get(id)
                                      : (Math.random() * SUBWORDS.length) | 0);
                }
                this._renderSubwords();
            };
            body.appendChild(tr);
        });

        pane.querySelector('.gi-sub-add').onclick = () => {
            const inp = pane.querySelector('.gi-sub-new');
            const v = inp.value.trim();
            if (!v) return;
            if (SUBWORDS.length >= SUBWORD_CAP) {
                alert('Subword cap reached (' + SUBWORD_CAP + ').'); return;
            }
            engine.addSubword(v);
            inp.value = '';
            this._renderSubwords();
        };
        this._wireEvolveControls('subwords', pane.querySelector('.gi-ev-bar'));
    }

    // ── Words tab ──────────────────────────────────────────────
    _renderWords() {
        const engine = this.engine;
        const WORDS = engine.WORDS;
        const SUBWORDS = engine.SUBWORDS;
        const SUBWORD_CAP = engine.limits.SUBWORD_CAP;
        const pane = this._panes.words;
        pane.innerHTML = `
            <div class="gi-toolbar">
                <input type="text" class="gi-word-search"
                       placeholder="search (substring of expanded pattern)" />
                <button class="gi-btn gi-word-new">+ new random word</button>
                <span class="gi-count"></span>
            </div>
            <div class="gi-toolbar gi-ev-bar"></div>
            <table class="gi-table">
                <thead><tr>
                    <th>ID</th><th>Subword chain</th><th>Symbols</th><th>Used</th><th></th>
                </tr></thead>
                <tbody class="gi-word-body"></tbody>
            </table>
        `;
        const countEl = pane.querySelector('.gi-count');
        const body = pane.querySelector('.gi-word-body');
        const search = pane.querySelector('.gi-word-search');

        const wordFlat = (w) => {
            let s = '';
            for (const id of w.subIds) s += (SUBWORDS[id] || {pattern:''}).pattern;
            return s;
        };

        const renderRows = () => {
            body.innerHTML = '';
            const q = search.value.trim();
            let list = [...WORDS].sort((a, b) => b.useCount - a.useCount);
            if (q) list = list.filter(w => wordFlat(w).includes(q));
            countEl.textContent = `${WORDS.length} words`
                + (q ? ` · ${list.length} match` : '')
                + ` · showing top 300`;
            list.slice(0, 300).forEach(w => {
                const flat = wordFlat(w);
                const chain = w.subIds.map(id => {
                    const s = SUBWORDS[id];
                    return s ? s.pattern : '?';
                }).join('-');
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="id">${w.id}</td>
                    <td><input type="text" value="${chain}"></td>
                    <td class="pat">${flat}</td>
                    <td class="use">${w.useCount}</td>
                    <td><button class="row-del" title="Delete this word">✕</button></td>
                `;
                const input = tr.querySelector('input');
                const patCell = tr.querySelectorAll('td')[2];
                input.addEventListener('change', () => {
                    const segs = input.value.split('-').map(x => x.trim()).filter(Boolean);
                    const ids = [];
                    for (const seg of segs) {
                        let found = SUBWORDS.findIndex(s => s.pattern === seg);
                        if (found < 0 && SUBWORDS.length < SUBWORD_CAP) {
                            const added = engine.addSubword(seg);
                            found = added.id;
                        }
                        if (found >= 0) ids.push(found);
                    }
                    if (ids.length) {
                        w.subIds = ids;
                        patCell.textContent = wordFlat(w);
                    } else {
                        input.value = w.subIds
                            .map(i => (SUBWORDS[i]||{pattern:'?'}).pattern).join('-');
                    }
                });
                tr.querySelector('.row-del').onclick = () => {
                    const idx = WORDS.indexOf(w);
                    if (idx < 0) return;
                    WORDS.splice(idx, 1);
                    WORDS.forEach((ww, i) => { ww.id = i; });
                    renderRows();
                };
                body.appendChild(tr);
            });
        };

        search.addEventListener('input', renderRows);
        pane.querySelector('.gi-word-new').onclick = () => {
            engine.addRandomWord();
            renderRows();
        };
        this._wireEvolveControls('words', pane.querySelector('.gi-ev-bar'));
        renderRows();
    }

    // ── Stats tab ──────────────────────────────────────────────
    // First call: build layout. Later calls: only refresh card numbers so
    // we don't clobber the live-appended log box.
    _renderStats() {
        const pane = this._panes.stats;
        if (pane.querySelector('.gi-log-box')) {
            this._updateStatsCards(pane);
            return;
        }
        pane.innerHTML = `
            <div class="gi-stats">
                <div class="gi-stat-card">
                    <h4>Particles</h4>
                    <div class="big" data-stat="pp-count"></div>
                    <div style="color:#8b95a0;font-size:0.7rem;" data-stat="pp-usage"></div>
                </div>
                <div class="gi-stat-card">
                    <h4>Subwords</h4>
                    <div class="big" data-stat="sub-count"></div>
                    <div style="color:#8b95a0;font-size:0.7rem;" data-stat="sub-usage"></div>
                </div>
                <div class="gi-stat-card">
                    <h4>Words</h4>
                    <div class="big" data-stat="word-count"></div>
                    <div style="color:#8b95a0;font-size:0.7rem;" data-stat="word-usage"></div>
                </div>
                <div class="gi-stat-card">
                    <h4>Speech events</h4>
                    <div class="big" data-stat="events"></div>
                    <div style="color:#8b95a0;font-size:0.7rem;">
                        total word-utterances since page load
                    </div>
                </div>
                <div class="gi-stat-card">
                    <h4>Top 10 particles</h4>
                    <ol data-stat="top-pps"></ol>
                </div>
                <div class="gi-stat-card">
                    <h4>Top 10 subwords</h4>
                    <ol data-stat="top-subs"></ol>
                </div>
                <div class="gi-stat-card">
                    <h4>Top 10 words</h4>
                    <ol data-stat="top-words"></ol>
                </div>
                <div class="gi-stat-card">
                    <h4>Grammar presets</h4>
                    <ol data-stat="grammars"></ol>
                </div>
            </div>
            <div class="gi-log-wrap">
                <div class="gi-log-head">
                    <span>Utterance Log
                        <span style="color:#566270;font-weight:normal;letter-spacing:0;">
                            — newest at the bottom, auto-scrolls
                        </span>
                    </span>
                    <div class="gi-log-actions">
                        <button class="gi-btn gi-log-pause">Pause autoscroll</button>
                        <button class="gi-btn danger gi-log-clear">Clear</button>
                    </div>
                </div>
                <div class="gi-log-box"></div>
            </div>
        `;
        const box = pane.querySelector('.gi-log-box');
        for (const entry of this.engine.utteranceLog) box.appendChild(this._logRow(entry));
        box.scrollTop = box.scrollHeight;
        pane.querySelector('.gi-log-pause').onclick = (e) => {
            const btn = e.currentTarget;
            btn.dataset.paused = btn.dataset.paused === '1' ? '0' : '1';
            btn.textContent = btn.dataset.paused === '1'
                ? 'Resume autoscroll' : 'Pause autoscroll';
        };
        pane.querySelector('.gi-log-clear').onclick = () => {
            this.engine.utteranceLog.length = 0;
            box.innerHTML = '';
        };
        this._updateStatsCards(pane);
    }

    _updateStatsCards(pane) {
        const engine = this.engine;
        const PARTICLES = engine.PARTICLES;
        const SUBWORDS = engine.SUBWORDS;
        const WORDS = engine.WORDS;
        const PARTICLE_CAP = engine.limits.PARTICLE_CAP;
        const PARTICLE_MIN = engine.limits.PARTICLE_MIN;
        const SUBWORD_CAP = engine.limits.SUBWORD_CAP;
        const SUBWORD_MIN = engine.limits.SUBWORD_MIN;
        const topPPs = [...PARTICLES].sort((a,b)=>b.useCount-a.useCount).slice(0,10);
        const topSubs = [...SUBWORDS].sort((a,b)=>b.useCount-a.useCount).slice(0,10);
        const topWords = [...WORDS].sort((a,b)=>b.useCount-a.useCount).slice(0,10);
        const usedPPs = PARTICLES.filter(p => p.useCount > 0).length;
        const usedSubs = SUBWORDS.filter(s => s.useCount > 0).length;
        const usedWords = WORDS.filter(w => w.useCount > 0).length;
        const totalSpeakEvents = WORDS.reduce((s, w) => s + w.useCount, 0);
        const set = (k, v) => {
            const el = pane.querySelector(`[data-stat="${k}"]`);
            if (el) el.textContent = v;
        };
        const setHTML = (k, v) => {
            const el = pane.querySelector(`[data-stat="${k}"]`);
            if (el) el.innerHTML = v;
        };
        set('pp-count',   PARTICLES.length);
        set('pp-usage',   `${usedPPs} used · ${PARTICLES.length - usedPPs} idle · cap ${PARTICLE_CAP} · floor ${PARTICLE_MIN}`);
        set('sub-count',  SUBWORDS.length);
        set('sub-usage',  `${usedSubs} used · ${SUBWORDS.length - usedSubs} idle · cap ${SUBWORD_CAP} · floor ${SUBWORD_MIN}`);
        set('word-count', WORDS.length);
        set('word-usage', `${usedWords} used · ${WORDS.length - usedWords} idle`);
        set('events',     totalSpeakEvents);
        setHTML('top-pps', topPPs.map(p =>
            `<li><span style="color:var(--gi-amber,#ffb84d);">${p.type}#${p.id}</span> ×${p.useCount}</li>`
        ).join(''));
        setHTML('top-subs', topSubs.map(s =>
            `<li><span style="color:var(--gi-amber,#ffb84d);">${s.pattern}</span> ×${s.useCount}</li>`
        ).join(''));
        setHTML('top-words', topWords.map(w => {
            const chain = w.subIds.map(i => (SUBWORDS[i]||{pattern:'?'}).pattern).join('-');
            return `<li><span style="color:var(--gi-cyan,#59d0ff);">${chain}</span> ×${w.useCount}</li>`;
        }).join(''));
        setHTML('grammars', Object.entries(engine.SPEECH_GRAMMARS).map(([k, g]) =>
            `<li><span style="color:var(--gi-amber,#ffb84d);">${k}</span>
             — ${Object.keys(g.variants).length} variant(s)</li>`
        ).join(''));
    }

    // Called via engine.onLog for every utterance — live-appends to the
    // stats pane log box if it's mounted.
    _onLogEntry(entry) {
        const pane = this._panes.stats;
        const box = pane.querySelector('.gi-log-box');
        if (!box) return;
        const atBottom =
            (box.scrollTop + box.clientHeight) >= (box.scrollHeight - 6);
        box.appendChild(this._logRow(entry));
        const cap = this.engine.utteranceLogCap || 400;
        while (box.children.length > cap) box.removeChild(box.firstChild);
        const pauseBtn = pane.querySelector('.gi-log-pause');
        const paused = pauseBtn && pauseBtn.dataset.paused === '1';
        if (atBottom && !paused) box.scrollTop = box.scrollHeight;
    }

    _logRow(entry) {
        const SUBWORDS = this.engine.SUBWORDS;
        const el = document.createElement('div');
        el.className = 'gi-log-row';
        const d = new Date(entry.ts);
        const hh = String(d.getHours()).padStart(2, '0');
        const mm = String(d.getMinutes()).padStart(2, '0');
        const ss = String(d.getSeconds()).padStart(2, '0');
        const tag = entry.variant ? `${entry.kind}/${entry.variant}` : entry.kind;
        const tagClass = entry.kind === 'vocab' ? 'k vocab' : 'k';
        const tagPadded = tag.padEnd(22, ' ').slice(0, 22);
        const symPadded = (entry.symbols || '').padEnd(36, ' ');
        let breakdown;
        if (entry.words && entry.words.length) {
            breakdown = entry.words.map(w => {
                const chain = w.subIds.map(i =>
                    (SUBWORDS[i] || {pattern:'?'}).pattern).join('-');
                return `[<em>${chain}</em>]`;
            }).join(' · ');
        } else {
            breakdown = '—';
        }
        el.innerHTML =
            `<span class="t">[${hh}:${mm}:${ss}]</span> ` +
            `<span class="${tagClass}">${tagPadded}</span> ` +
            `<span class="sym">${symPadded}</span> ` +
            `<span class="brk">${breakdown}</span>`;
        return el;
    }
}

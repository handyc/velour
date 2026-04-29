/* Helix viewer — strand-split arrow features, sliding-window GC track,
 * mini-map overview, mouse-wheel zoom, drag-pan, axis drag-select, search.
 *
 * Mounts:
 *   #helix-viewer-mount      data-length, data-sequence-url, data-gc-url.
 *                            JS fills it with toolbar / SVG / legend / help.
 *   #helix-features-data     <script type="application/json"> payload
 *                            of feature objects (json_script filter).
 *   #helix-feature-detail    Qualifiers panel — populated on click.
 *   #helix-sequence-mount    Re-rendered to current viewport when zoom
 *                            is tight enough. Bases are fetched lazily
 *                            from data-sequence-url (so a 32 Mb
 *                            chromosome doesn't blow up the page).
 */
(function () {
    const mount = document.getElementById('helix-viewer-mount');
    if (!mount) return;
    const detail = document.getElementById('helix-feature-detail');
    const seqMount = document.getElementById('helix-sequence-mount');
    const SVG_NS = 'http://www.w3.org/2000/svg';

    const length = Math.max(1, parseInt(mount.dataset.length, 10) || 1);
    const sequenceUrl = mount.dataset.sequenceUrl || '';
    const gcUrl = mount.dataset.gcUrl || '';
    const evolveUrl = mount.dataset.evolveUrl || '';
    // The qualifiers URL ends in "/0/qualifiers/" — we substitute the
    // real feature PK at fetch time. Cleaner than parsing/regex.
    const qualifiersUrlTemplate = mount.dataset.qualifiersUrl || '';
    const qualifiersCache = Object.create(null);

    // Hard cap mirrors the server's EVOLVE_MAX_BP. Checked client-side
    // so the user gets a friendly message before the form POST roundtrip.
    const EVOLVE_MAX_BP = 5000;
    const EVOLVE_MIN_BP = 10;

    let features = [];
    const dataNode = document.getElementById('helix-features-data');
    if (dataNode) {
        try {
            const raw = JSON.parse(dataNode.textContent);
            const typeNames = raw.types || [];
            features = (raw.rows || []).map(row => {
                // Schema: [id, start, end, strand, type_idx, name?, search?]
                const [id, start, end, strand, ti, name, search] = row;
                const type = typeNames[ti] || '';
                const displayName = name || type;
                return { id, start, end, strand, type, name: displayName, search: search || '' };
            });
        } catch (e) {
            console.error('Helix: bad features payload', e);
        }
    }

    // Lazy-loaded data — sized to whatever the user is currently looking at.
    const remote = {
        gcProfile: null,            // float[bins], from /helix/<pk>/gc-profile/
        visibleSeq: null,           // { start, end, sequence } from /helix/<pk>/sequence/
    };
    let seqFetchAbort = null;
    let seqDebounce = null;
    let lastSeqKey = '';

    // Per-feature-type palette (Dark2-ish, colorblind-safer).
    const PALETTE = {
        gene:           '#1b9e77',
        CDS:            '#d95f02',
        mRNA:           '#7570b3',
        tRNA:           '#e7298a',
        rRNA:           '#66a61e',
        ncRNA:          '#e6ab02',
        regulatory:     '#a6761d',
        misc_feature:   '#8b949e',
        source:         '#5a5a5a',
        repeat_region:  '#888888',
        sig_peptide:    '#bc8cff',
        mat_peptide:    '#56d364',
        STS:            '#79c0ff',
        gap:            '#444444',
    };
    const colorFor = t => PALETTE[t] || '#a371f7';

    // Per-strand greedy lane packing — assigned once on full feature list.
    // Lane assignment is in bp space, so it stays stable across zoom levels
    // (a gene shouldn't jump rows when you scroll).
    const fwd = features.filter(f => f.strand >= 0).sort((a, b) => a.start - b.start);
    const rev = features.filter(f => f.strand <  0).sort((a, b) => a.start - b.start);
    assignLanes(fwd);
    assignLanes(rev);
    const fwdLaneCount = laneCountOf(fwd);
    const revLaneCount = laneCountOf(rev);

    // Searchable index: name + type + the most-useful qualifier values.
    // The server's `search` carries only tokens not already in name/type
    // (deduped to keep the page small). Compose the full lowercased
    // haystack here, once, so per-keystroke search is a single
    // .includes() with no allocation.
    const searchIndex = features.map(f => {
        const hay = (f.name + ' ' + f.type + ' ' + f.search).toLowerCase();
        return { f, hay };
    });

    // Geometry — fixed pixel layout. Only the bp→x mapping changes on zoom.
    const W = 1100, M = { left: 110, right: 18, top: 10 };
    const innerW = W - M.left - M.right;
    const LANE_H = 14, MINIMAP_H = 22, GC_H = 32, AXIS_H = 22, ROW_GAP = 6;

    const fwdH = fwdLaneCount * LANE_H;
    const revH = revLaneCount * LANE_H;
    const fwdRenderH = Math.max(LANE_H, fwdH);
    const revRenderH = Math.max(LANE_H, revH);

    const yMinimap = M.top;
    const yGC      = yMinimap + MINIMAP_H + ROW_GAP;
    const yFwdTop  = yGC + GC_H + ROW_GAP;
    const yAxis    = yFwdTop + fwdRenderH;
    const yRevTop  = yAxis + AXIS_H;
    const totalH   = yRevTop + revRenderH + 8;

    const state = {
        view: { start: 0, end: length },
        selection: null,
        selectedFeature: null,
        drag: null,
        suppressClick: false,
    };

    let elToolbar, elStatus, elSearchInput, elSearchSuggest, elSvg, elLegend;
    buildSkeleton();
    installListeners();
    render();
    fetchGCProfile();
    scheduleSequenceFetch();

    // ------------------ async loading ------------------

    function fetchGCProfile() {
        if (!gcUrl) return;
        fetch(gcUrl, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => {
                remote.gcProfile = data.profile || [];
                render();
            })
            .catch(err => console.warn('Helix: gc-profile fetch failed', err));
    }

    function scheduleSequenceFetch() {
        // Coalesce rapid view changes (zoom/pan storms) into a single fetch.
        if (seqDebounce) clearTimeout(seqDebounce);
        seqDebounce = setTimeout(fetchSequenceForView, 180);
    }

    function fetchSequenceForView() {
        if (!sequenceUrl) return;
        if (viewLen() > 3000) {
            // Sequence panel won't render anyway — drop the cache so
            // the next zoom-in fires a fresh fetch.
            remote.visibleSeq = null;
            return;
        }
        const a = Math.max(0, Math.floor(state.view.start));
        const b = Math.min(length, Math.ceil(state.view.end));
        const key = `${a}_${b}`;
        if (key === lastSeqKey) return;
        lastSeqKey = key;
        if (seqFetchAbort) seqFetchAbort.abort();
        seqFetchAbort = new AbortController();
        const url = `${sequenceUrl}?start=${a}&end=${b}`;
        fetch(url, { credentials: 'same-origin', signal: seqFetchAbort.signal })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => {
                remote.visibleSeq = data;
                renderSequence();
                renderStatus();
            })
            .catch(err => {
                if (err && err.name === 'AbortError') return;
                console.warn('Helix: sequence fetch failed', err);
            });
    }

    // ------------------ skeleton ------------------

    function buildSkeleton() {
        mount.classList.add('helix-viewer');
        mount.innerHTML = `
            <div class="helix-toolbar">
                <div class="helix-search-wrap">
                    <input id="helix-search" type="text" autocomplete="off" spellcheck="false"
                           placeholder="Find feature, gene, or position (dnaA, 1234, 1k..2k)" />
                    <div id="helix-search-suggest" class="helix-search-suggest" hidden></div>
                </div>
                <div class="helix-toolbar-zoom">
                    <button data-zoom="in"    title="Zoom in (+)">+</button>
                    <button data-zoom="out"   title="Zoom out (−)">−</button>
                    <button data-zoom="reset" title="Show whole sequence (0)">⟲</button>
                </div>
                <div class="helix-status" id="helix-status"></div>
            </div>
            <svg class="helix-svg" viewBox="0 0 ${W} ${totalH}" preserveAspectRatio="none"></svg>
            <div class="helix-legend"></div>
            <div class="helix-help">
                <span><kbd>scroll</kbd> zoom</span>
                <span><kbd>drag</kbd> pan</span>
                <span><kbd>drag on ruler</kbd> select range</span>
                <span><kbd>dbl-click</kbd> zoom to selection</span>
                <span><kbd>esc</kbd> clear</span>
                <span><kbd>0</kbd> fit all</span>
            </div>
        `;
        elToolbar       = mount.querySelector('.helix-toolbar');
        elStatus        = mount.querySelector('#helix-status');
        elSearchInput   = mount.querySelector('#helix-search');
        elSearchSuggest = mount.querySelector('#helix-search-suggest');
        elSvg           = mount.querySelector('.helix-svg');
        elLegend        = mount.querySelector('.helix-legend');
        renderLegend();
    }

    function renderLegend() {
        const counts = {};
        features.forEach(f => counts[f.type] = (counts[f.type] || 0) + 1);
        const keys = Object.keys(counts).sort();
        if (!keys.length) {
            elLegend.innerHTML = '<span class="helix-legend-empty">no features in this record</span>';
            return;
        }
        elLegend.innerHTML = keys.map(k =>
            `<span class="helix-legend-item">
                <span class="helix-legend-swatch" style="background:${colorFor(k)}"></span>
                <span class="helix-legend-label">${escapeHtml(k)}</span>
                <span class="helix-legend-count">${counts[k]}</span>
            </span>`).join('');
    }

    // ------------------ render loop ------------------

    function render() {
        clearChildren(elSvg);
        renderMinimap();
        renderGC();
        if (fwd.length) renderTracks(yFwdTop, fwd, +1, fwdLaneCount);
        else renderEmptyTrackHint(yFwdTop, '+');
        renderAxis();
        if (rev.length) renderTracks(yRevTop, rev, -1, revLaneCount);
        else renderEmptyTrackHint(yRevTop, '−');
        renderSelection();
        renderStatus();
        renderSequence();
        // Any view change may need a fresh sequence slice — debounced.
        scheduleSequenceFetch();
    }

    function renderMinimap() {
        elSvg.appendChild(svg('rect', {
            x: M.left, y: yMinimap, width: innerW, height: MINIMAP_H,
            class: 'helix-minimap-bg',
        }));
        const half = MINIMAP_H / 2;
        const xMM = bp => M.left + (bp / length) * innerW;
        features.forEach(f => {
            const x1 = xMM(f.start);
            const x2 = Math.max(xMM(f.end), x1 + 0.6);
            elSvg.appendChild(svg('rect', {
                x: x1,
                y: yMinimap + (f.strand >= 0 ? 1 : half + 1),
                width: x2 - x1,
                height: half - 2,
                fill: colorFor(f.type),
                class: 'helix-mm-feat',
            }));
        });
        elSvg.appendChild(svg('line', {
            x1: M.left, x2: M.left + innerW, y1: yMinimap + half, y2: yMinimap + half,
            class: 'helix-mm-axis',
        }));
        const vx1 = M.left + (state.view.start / length) * innerW;
        const vx2 = M.left + (state.view.end   / length) * innerW;
        elSvg.appendChild(svg('rect', {
            x: vx1, y: yMinimap - 1,
            width: Math.max(2, vx2 - vx1), height: MINIMAP_H + 2,
            class: 'helix-mm-viewport',
        }));
        const lbl = svg('text', { x: 8, y: yMinimap + MINIMAP_H * 0.65, class: 'helix-row-label' });
        lbl.textContent = 'overview';
        elSvg.appendChild(lbl);
        const hit = svg('rect', {
            x: M.left, y: yMinimap, width: innerW, height: MINIMAP_H,
            fill: 'transparent', class: 'helix-mm-hit',
        });
        hit.dataset.role = 'minimap';
        elSvg.appendChild(hit);
    }

    function renderGC() {
        elSvg.appendChild(svg('rect', {
            x: M.left, y: yGC, width: innerW, height: GC_H, class: 'helix-gc-bg',
        }));
        const lbl = svg('text', { x: 8, y: yGC + GC_H * 0.42, class: 'helix-row-label' });
        lbl.textContent = 'GC%';
        elSvg.appendChild(lbl);

        if (!remote.gcProfile) {
            const placeholder = svg('text', {
                x: M.left + innerW / 2, y: yGC + GC_H * 0.6,
                'text-anchor': 'middle', class: 'helix-row-sublabel',
            });
            placeholder.textContent = 'loading…';
            elSvg.appendChild(placeholder);
            return;
        }

        // Sample the precomputed binned profile across the visible viewport.
        // The profile is bins-of-equal-width across [0, length); for any
        // viewport bp, look up the covering bin.
        const profile = remote.gcProfile;
        const profBins = profile.length;
        const binBp = length / profBins;
        const N = 240;
        const points = [];
        let mn = 1, mx = 0;
        for (let i = 0; i < N; i++) {
            const xv = M.left + (i / (N - 1)) * innerW;
            const bp = state.view.start + (i / (N - 1)) * viewLen();
            const idx = clamp(Math.floor(bp / binBp), 0, profBins - 1);
            const gc = profile[idx];
            points.push({ x: xv, gc });
            if (gc < mn) mn = gc;
            if (gc > mx) mx = gc;
        }

        const yMid = yGC + GC_H * 0.5;
        elSvg.appendChild(svg('line', {
            x1: M.left, x2: M.left + innerW, y1: yMid, y2: yMid,
            class: 'helix-gc-mid',
        }));

        let path = `M ${points[0].x} ${yGC + GC_H}`;
        for (const p of points) path += ` L ${p.x} ${yGC + GC_H * (1 - p.gc)}`;
        path += ` L ${points[points.length - 1].x} ${yGC + GC_H} Z`;
        elSvg.appendChild(svg('path', { d: path, class: 'helix-gc-area' }));

        const lbl2 = svg('text', { x: 8, y: yGC + GC_H * 0.85, class: 'helix-row-sublabel' });
        lbl2.textContent = `${(mn * 100).toFixed(0)}–${(mx * 100).toFixed(0)}`;
        elSvg.appendChild(lbl2);
    }

    function renderEmptyTrackHint(rowTop, glyph) {
        elSvg.appendChild(svg('rect', {
            x: M.left, y: rowTop, width: innerW, height: LANE_H, class: 'helix-track-bg',
        }));
        const lbl = svg('text', { x: 8, y: rowTop + LANE_H * 0.72, class: 'helix-row-label' });
        lbl.textContent = glyph + ' strand';
        elSvg.appendChild(lbl);
    }

    function renderTracks(rowTop, list, strand, lanes) {
        const rowH = lanes * LANE_H;
        elSvg.appendChild(svg('rect', {
            x: M.left, y: rowTop, width: innerW, height: rowH, class: 'helix-track-bg',
        }));
        const lbl = svg('text', {
            x: 8,
            // Forward label hugs the bottom (toward axis); reverse hugs the top.
            y: strand >= 0 ? rowTop + rowH - 3 : rowTop + 11,
            class: 'helix-row-label',
        });
        lbl.textContent = strand >= 0 ? '+ forward' : '− reverse';
        elSvg.appendChild(lbl);

        const vs = state.view.start, ve = state.view.end;
        list.forEach(f => {
            if (f.end < vs || f.start > ve) return;
            const x1 = bp2x(Math.max(f.start, vs));
            const x2 = bp2x(Math.min(f.end, ve));
            const w  = Math.max(2, x2 - x1);
            // Forward: lane 0 sits at the bottom (closest to axis), growing up.
            // Reverse: lane 0 sits at the top    (closest to axis), growing down.
            const laneIdx = strand >= 0 ? (lanes - 1 - f._lane) : f._lane;
            const y = rowTop + laneIdx * LANE_H + 1;
            const h = LANE_H - 3;

            elSvg.appendChild(makeFeatureArrow(x1, y, w, h, f, strand));

            if (w >= 36 && f.name) {
                const truncated = truncateToWidth(f.name, w - 8);
                if (truncated) {
                    const text = svg('text', {
                        x: x1 + w / 2,
                        y: y + h * 0.74,
                        class: 'helix-feat-label',
                        'text-anchor': 'middle',
                        fill: textColorFor(colorFor(f.type)),
                    });
                    text.textContent = truncated;
                    elSvg.appendChild(text);
                }
            }
        });
    }

    function makeFeatureArrow(x, y, w, h, f, strand) {
        const tipW = Math.min(8, Math.max(2, w * 0.22));
        let path;
        if (strand > 0) {
            const tx = x + Math.max(0, w - tipW);
            path = `M ${x} ${y} L ${tx} ${y} L ${x + w} ${y + h / 2} L ${tx} ${y + h} L ${x} ${y + h} Z`;
        } else if (strand < 0) {
            const tx = x + Math.min(w, tipW);
            path = `M ${x + w} ${y} L ${tx} ${y} L ${x} ${y + h / 2} L ${tx} ${y + h} L ${x + w} ${y + h} Z`;
        } else {
            path = `M ${x} ${y} L ${x + w} ${y} L ${x + w} ${y + h} L ${x} ${y + h} Z`;
        }
        const elt = svg('path', {
            d: path,
            fill: colorFor(f.type),
            class: 'helix-feature' + (state.selectedFeature === f ? ' selected' : ''),
        });
        elt.dataset.role = 'feature';
        elt._feature = f;

        const tip = document.createElementNS(SVG_NS, 'title');
        const strandSym = strand > 0 ? '+' : (strand < 0 ? '-' : '.');
        tip.textContent = `${f.name} · ${f.type} · ${formatBp(f.start + 1)}–${formatBp(f.end)} (${formatBp(f.end - f.start)} bp, ${strandSym})`;
        elt.appendChild(tip);
        return elt;
    }

    function renderAxis() {
        const yMid = yAxis + AXIS_H / 2;
        elSvg.appendChild(svg('line', {
            x1: M.left, x2: M.left + innerW, y1: yMid, y2: yMid, class: 'helix-axis-line',
        }));
        const lbl = svg('text', { x: 8, y: yMid + 4, class: 'helix-row-label' });
        lbl.textContent = formatBp(viewLen()) + ' bp';
        elSvg.appendChild(lbl);

        const interval = niceTickInterval(viewLen());
        const startTick = Math.ceil(state.view.start / interval) * interval;
        for (let bp = startTick; bp <= state.view.end; bp += interval) {
            const x = bp2x(bp);
            elSvg.appendChild(svg('line', {
                x1: x, x2: x, y1: yMid - 4, y2: yMid + 4, class: 'helix-tick',
            }));
            const lab = svg('text', {
                x, y: yMid + 16, 'text-anchor': 'middle', class: 'helix-tick-label',
            });
            lab.textContent = formatBp(bp);
            elSvg.appendChild(lab);
        }

        const hit = svg('rect', {
            x: M.left, y: yAxis, width: innerW, height: AXIS_H,
            fill: 'transparent', class: 'helix-axis-hit',
        });
        hit.dataset.role = 'axis';
        elSvg.appendChild(hit);
    }

    function renderSelection() {
        if (!state.selection) return;
        const a = Math.min(state.selection.start, state.selection.end);
        const b = Math.max(state.selection.start, state.selection.end);
        if (b < state.view.start || a > state.view.end) return;
        const x1 = bp2x(Math.max(a, state.view.start));
        const x2 = bp2x(Math.min(b, state.view.end));
        const y1 = yGC;
        const y2 = yRevTop + revRenderH;
        elSvg.appendChild(svg('rect', {
            x: x1, y: y1, width: Math.max(1, x2 - x1), height: y2 - y1,
            class: 'helix-selection',
        }));
    }

    function renderStatus() {
        const parts = [];
        parts.push(
            `<span class="hl-tag">view</span> ` +
            `<span class="hl-num">${formatBp(state.view.start + 1)}</span>–` +
            `<span class="hl-num">${formatBp(state.view.end)}</span> ` +
            `(${formatBp(viewLen())} bp)`
        );
        if (state.selection) {
            const a = Math.min(state.selection.start, state.selection.end);
            const b = Math.max(state.selection.start, state.selection.end);
            const len = b - a;
            const gc = computeGC(a, b);
            // Attach evolve mini-buttons only when the slice is in range.
            // Buttons are click-handled via delegation on elToolbar — see
            // installListeners — so re-rendering the status doesn't lose
            // the handler.
            const inRange = (len >= EVOLVE_MIN_BP && len <= EVOLVE_MAX_BP);
            const buttons = (evolveUrl && inRange)
                ? ` <button class="hl-evolve-mini" data-evolve-sel="toward" title="Evolve toward this slice">→ toward</button>` +
                  ` <button class="hl-evolve-mini" data-evolve-sel="from"   title="Evolve from this slice">→ from</button>`
                : '';
            parts.push(
                `<span class="hl-tag">sel</span> ` +
                `<span class="hl-num">${formatBp(a + 1)}</span>–` +
                `<span class="hl-num">${formatBp(b)}</span> ` +
                `(${formatBp(len)} bp${gc !== null ? `, GC ${(gc * 100).toFixed(1)}%` : ''})` +
                buttons
            );
        }
        elStatus.innerHTML = parts.join('  <span class="hl-sep">·</span>  ');
    }

    function renderSequence() {
        if (!seqMount) return;
        const vlen = viewLen();
        if (vlen > 3000) {
            seqMount.innerHTML =
                `<div class="helix-seq-placeholder">Zoom in to ≤ 3,000 bp to see the base-by-base sequence — currently viewing ${formatBp(vlen)} bp.</div>`;
            return;
        }
        // Use whatever's in cache; if the visible range isn't covered yet,
        // show a loading hint and wait for the in-flight fetch to finish.
        const a = Math.max(0, Math.floor(state.view.start));
        const b = Math.min(length, Math.ceil(state.view.end));
        const cached = remote.visibleSeq;
        if (!cached || cached.start > a || cached.end < b) {
            seqMount.innerHTML = `<div class="helix-seq-placeholder">loading bases ${formatBp(a + 1)}–${formatBp(b)}…</div>`;
            return;
        }
        const visible = cached.sequence.substring(a - cached.start, b - cached.start);
        const COLS = 60;
        const sel = state.selection;
        const selA = sel ? Math.min(sel.start, sel.end) : -1;
        const selB = sel ? Math.max(sel.start, sel.end) : -1;
        const frags = [];
        for (let i = 0; i < visible.length; i += COLS) {
            const chunk = visible.slice(i, i + COLS);
            const baseStart = a + i;
            let html = '';
            for (let j = 0; j < chunk.length; j++) {
                const ch = chunk[j];
                const bp = baseStart + j;
                const inSel = bp >= selA && bp < selB;
                html += `<span class="b-${ch}${inSel ? ' sel' : ''}">${ch}</span>`;
            }
            const pos = String(baseStart + 1).padStart(8, ' ');
            frags.push(
                `<div class="seq-row"><span class="seq-pos">${pos}</span>` +
                `<span class="seq-bases">${html}</span></div>`
            );
        }
        seqMount.innerHTML = frags.join('');
    }

    // ------------------ interactions ------------------

    function installListeners() {
        elSvg.addEventListener('wheel', onWheel, { passive: false });
        elSvg.addEventListener('mousedown', onMouseDown);
        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
        elSvg.addEventListener('click', onSvgClick);
        elSvg.addEventListener('dblclick', onSvgDblClick);

        elToolbar.addEventListener('click', e => {
            const z = e.target.closest('[data-zoom]');
            if (z) {
                const mid = (state.view.start + state.view.end) / 2;
                if      (z.dataset.zoom === 'in')    zoomBy(0.6, mid);
                else if (z.dataset.zoom === 'out')   zoomBy(1.6, mid);
                else if (z.dataset.zoom === 'reset') { state.view = { start: 0, end: length }; render(); }
                return;
            }
            const ev = e.target.closest('[data-evolve-sel]');
            if (ev && state.selection) {
                const a = Math.min(state.selection.start, state.selection.end);
                const b = Math.max(state.selection.start, state.selection.end);
                sendToEvolution(a, b, ev.dataset.evolveSel, '');
            }
        });

        elSearchInput.addEventListener('input', onSearchInput);
        elSearchInput.addEventListener('keydown', onSearchKey);
        elSearchInput.addEventListener('blur', () =>
            setTimeout(() => { elSearchSuggest.hidden = true; }, 150));
        document.addEventListener('keydown', onGlobalKey);
    }

    function onWheel(e) {
        e.preventDefault();
        const sx = clientToSvgX(e.clientX);
        const anchorBp = x2bp(sx);
        const factor = e.deltaY < 0 ? 0.85 : 1.18;
        zoomBy(factor, anchorBp);
    }

    function zoomBy(factor, anchorBp) {
        const minLen = Math.min(50, length);
        const newLen = Math.max(minLen, Math.min(length, viewLen() * factor));
        const ratio = (anchorBp - state.view.start) / viewLen();
        let s = anchorBp - newLen * ratio;
        let e = s + newLen;
        if (s < 0) { s = 0; e = newLen; }
        if (e > length) { e = length; s = e - newLen; }
        state.view = { start: Math.round(s), end: Math.round(e) };
        render();
    }

    function panBy(deltaBp) {
        const vl = viewLen();
        let s = state.view.start - deltaBp;
        let e = state.view.end - deltaBp;
        if (s < 0) { s = 0; e = vl; }
        if (e > length) { e = length; s = e - vl; }
        state.view = { start: Math.round(s), end: Math.round(e) };
        render();
    }

    function onMouseDown(e) {
        if (e.button !== 0) return;
        const sx = clientToSvgX(e.clientX);
        const sy = clientToSvgY(e.clientY);
        const target = e.target;
        const role = target.dataset && target.dataset.role;

        if (role === 'minimap') {
            const bp = ((sx - M.left) / innerW) * length;
            recenterView(bp);
            state.drag = { mode: 'minimap', distance: 0 };
            return;
        }
        if (role === 'axis') {
            const bp = clamp(Math.round(x2bp(sx)), 0, length);
            state.selection = { start: bp, end: bp };
            state.drag = { mode: 'select', startBp: bp, distance: 0 };
            render();
            return;
        }
        if (role === 'feature' && target._feature) {
            return; // click handled by onSvgClick
        }
        if (sy >= yGC && sy <= yRevTop + revRenderH) {
            state.drag = {
                mode: 'pan',
                startClientX: e.clientX,
                startView: { ...state.view },
                distance: 0,
            };
        }
    }

    function onMouseMove(e) {
        if (!state.drag) return;
        state.drag.distance += Math.abs(e.movementX) + Math.abs(e.movementY);
        const sx = clientToSvgX(e.clientX);
        if (state.drag.mode === 'pan') {
            const r = elSvg.getBoundingClientRect();
            const dxSvg = (e.clientX - state.drag.startClientX) * (W / r.width);
            const startVL = state.drag.startView.end - state.drag.startView.start;
            const dxBp = dxSvg * (startVL / innerW);
            let s = state.drag.startView.start - dxBp;
            let en = state.drag.startView.end   - dxBp;
            if (s < 0) { s = 0; en = startVL; }
            if (en > length) { en = length; s = en - startVL; }
            state.view = { start: Math.round(s), end: Math.round(en) };
            render();
        } else if (state.drag.mode === 'select') {
            const bp = clamp(Math.round(x2bp(sx)), 0, length);
            state.selection = { start: state.drag.startBp, end: bp };
            render();
        } else if (state.drag.mode === 'minimap') {
            const bp = ((sx - M.left) / innerW) * length;
            recenterView(bp);
        }
    }

    function onMouseUp() {
        if (state.drag && state.drag.distance > 4) state.suppressClick = true;
        state.drag = null;
    }

    function onSvgClick(e) {
        if (state.suppressClick) { state.suppressClick = false; return; }
        const target = e.target;
        const role = target.dataset && target.dataset.role;
        if (role === 'feature' && target._feature) {
            state.selectedFeature = target._feature;
            showFeatureDetail(target._feature);
            render();
        } else if (role === 'axis' && state.selection &&
                   state.selection.start === state.selection.end) {
            // Plain click on the ruler with zero-width selection — clear it.
            state.selection = null;
            render();
        }
    }

    function onSvgDblClick() {
        if (!state.selection) return;
        const a = Math.min(state.selection.start, state.selection.end);
        const b = Math.max(state.selection.start, state.selection.end);
        if (b - a < 10) return;
        state.view = { start: a, end: b };
        render();
    }

    function onSearchInput() {
        const q = elSearchInput.value.trim().toLowerCase();
        if (!q) { elSearchSuggest.hidden = true; return; }
        const matches = searchIndex
            .filter(({ hay }) => hay.includes(q))
            .slice(0, 8);
        if (!matches.length) {
            elSearchSuggest.innerHTML = `<div class="helix-search-empty">no match</div>`;
            elSearchSuggest.hidden = false;
            elSearchSuggest._matches = [];
            return;
        }
        elSearchSuggest.innerHTML = matches.map(({ f }, i) =>
            `<div class="helix-search-item" data-idx="${i}">
                <span class="hl-name">${escapeHtml(f.name)}</span>
                <span class="hl-type" style="color:${colorFor(f.type)}">${escapeHtml(f.type)}</span>
                <span class="hl-pos">${formatBp(f.start + 1)}–${formatBp(f.end)}</span>
            </div>`).join('');
        elSearchSuggest.hidden = false;
        elSearchSuggest._matches = matches;
        elSearchSuggest.querySelectorAll('.helix-search-item').forEach(el => {
            el.addEventListener('mousedown', ev => {
                ev.preventDefault();
                const idx = parseInt(el.dataset.idx, 10);
                jumpToFeature(matches[idx].f);
                elSearchSuggest.hidden = true;
                elSearchInput.value = '';
            });
        });
    }

    function onSearchKey(e) {
        if (e.key === 'Escape') { elSearchSuggest.hidden = true; elSearchInput.blur(); return; }
        if (e.key !== 'Enter') return;
        const raw = elSearchInput.value.trim();
        if (!raw) return;

        // Range form: "1k..2k", "1000-2000", "1000–2000".
        let m = raw.match(/^(\S+)\s*(?:\.\.|-|–)\s*(\S+)$/);
        if (m) {
            const a = parseBp(m[1]), b = parseBp(m[2]);
            if (a !== null && b !== null && b > a) {
                state.view = { start: clamp(a - 1, 0, length), end: clamp(b, 0, length) };
                render();
                elSearchSuggest.hidden = true;
                elSearchInput.value = '';
                return;
            }
        }
        // Bare position.
        if (/^[\d_,\.kKmM]+$/.test(raw)) {
            const bp = parseBp(raw);
            if (bp !== null) {
                const vl = Math.min(2000, length);
                let s = clamp(bp - vl / 2, 0, length - vl), en = s + vl;
                state.view = { start: Math.round(s), end: Math.round(en) };
                render();
                elSearchSuggest.hidden = true;
                elSearchInput.value = '';
                return;
            }
        }
        // First name match.
        const matches = elSearchSuggest._matches || [];
        if (matches.length) {
            jumpToFeature(matches[0].f);
            elSearchSuggest.hidden = true;
            elSearchInput.value = '';
        }
    }

    function onGlobalKey(e) {
        if (document.activeElement === elSearchInput) return;
        if (e.key === 'Escape')      { state.selection = null; state.selectedFeature = null; render(); }
        else if (e.key === 'ArrowLeft')  panBy(viewLen() *  0.2);
        else if (e.key === 'ArrowRight') panBy(viewLen() * -0.2);
        else if (e.key === '=' || e.key === '+') zoomBy(0.6, (state.view.start + state.view.end) / 2);
        else if (e.key === '-' || e.key === '_') zoomBy(1.6, (state.view.start + state.view.end) / 2);
        else if (e.key === '0') { state.view = { start: 0, end: length }; render(); }
    }

    function jumpToFeature(f) {
        const span = f.end - f.start;
        const pad = Math.max(50, Math.floor(span * 0.5));
        const s = Math.max(0, f.start - pad);
        const en = Math.min(length, f.end + pad);
        state.view = { start: s, end: en };
        state.selectedFeature = f;
        showFeatureDetail(f);
        render();
    }

    function sendToEvolution(start, end, mode, label) {
        if (!evolveUrl) return;
        const span = end - start;
        if (span > EVOLVE_MAX_BP) {
            alert(`That slice is ${span.toLocaleString()} bp — too long to evolve as a single sequence.\nMax is ${EVOLVE_MAX_BP.toLocaleString()} bp.`);
            return;
        }
        if (span < EVOLVE_MIN_BP) {
            alert(`That slice is only ${span} bp — too short to evolve.\nMin is ${EVOLVE_MIN_BP} bp.`);
            return;
        }
        const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
        const fd = new FormData();
        fd.append('start', String(start));
        fd.append('end',   String(end));
        fd.append('mode',  mode);
        if (label) fd.append('name', label);
        if (csrf)  fd.append('csrfmiddlewaretoken', csrf);
        fetch(evolveUrl, { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(r => {
                if (r.redirected) { window.location.href = r.url; return; }
                if (r.ok) { window.location.href = r.url; return; }
                return r.text().then(t => alert(`Could not start evolution run (${r.status}):\n${t}`));
            })
            .catch(e => alert(`Network error: ${e.message}`));
    }

    function recenterView(bp) {
        const vl = viewLen();
        let s = bp - vl / 2, en = s + vl;
        if (s < 0) { s = 0; en = vl; }
        if (en > length) { en = length; s = en - vl; }
        state.view = { start: Math.round(s), end: Math.round(en) };
        render();
    }

    function showFeatureDetail(f) {
        if (!detail) return;
        const strandSym = f.strand > 0 ? '+' : (f.strand < 0 ? '-' : '.');
        const evolveBtns = evolveUrl
            ? `<button class="hl-evolve" data-evolve="toward" title="Use as goal: population evolves toward this region">→ Evolve toward</button>
               <button class="hl-evolve" data-evolve="from"   title="Use as seed: population starts as copies and drifts under mutation">→ Evolve from</button>`
            : '';
        const head =
            `<div class="helix-detail-head">
                <h4>${escapeHtml(f.name)} <span class="hl-type" style="color:${colorFor(f.type)}">· ${escapeHtml(f.type)}</span></h4>
                <div class="helix-detail-actions">
                    <button class="hl-zoom-feat" data-zoomto>Zoom →</button>
                    ${evolveBtns}
                </div>
            </div>` +
            `<div class="qual-row"><span class="qual-key">Position</span>` +
            `<span class="qual-val">${formatBp(f.start + 1)}–${formatBp(f.end)} ` +
            `(${formatBp(f.end - f.start)} bp, strand ${strandSym})</span></div>`;

        const wireButtons = () => {
            const zb = detail.querySelector('[data-zoomto]');
            if (zb) zb.addEventListener('click', () => jumpToFeature(f));
            detail.querySelectorAll('[data-evolve]').forEach(btn => {
                btn.addEventListener('click', () => sendToEvolution(
                    f.start, f.end, btn.dataset.evolve, `${f.name} (${f.type})`));
            });
        };

        const renderQualifiers = (q) => {
            const rows = Object.keys(q).sort().map(key => {
                const v = q[key];
                const vText = Array.isArray(v) ? v.join(', ') : String(v);
                return `<div class="qual-row"><span class="qual-key">${escapeHtml(key)}</span>` +
                       `<span class="qual-val">${escapeHtml(vText)}</span></div>`;
            }).join('');
            detail.innerHTML = head + rows;
            wireButtons();
        };

        // If we already fetched these qualifiers, render synchronously.
        const cached = qualifiersCache[f.id];
        if (cached) { renderQualifiers(cached); return; }

        // Otherwise paint the header now and fill in qualifiers when
        // the fetch returns. The closed-over `f` keeps a stale fetch
        // from clobbering a later click on a different feature.
        detail.innerHTML = head +
            `<div class="qual-row helix-qual-loading"><span class="qual-key">Qualifiers</span>` +
            `<span class="qual-val">loading…</span></div>`;
        wireButtons();

        if (!qualifiersUrlTemplate || !f.id) return;
        const url = qualifiersUrlTemplate.replace(/\/0\//, `/${f.id}/`);
        fetch(url, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => {
                const q = data.qualifiers || {};
                qualifiersCache[f.id] = q;
                if (state.selectedFeature === f) renderQualifiers(q);
            })
            .catch(err => {
                if (state.selectedFeature !== f) return;
                detail.innerHTML = head +
                    `<div class="qual-row"><span class="qual-key">Qualifiers</span>` +
                    `<span class="qual-val">fetch failed (${escapeHtml(String(err))})</span></div>`;
                wireButtons();
            });
    }

    // ------------------ helpers ------------------

    function viewLen() { return state.view.end - state.view.start; }
    function bp2x(bp) { return M.left + ((bp - state.view.start) / viewLen()) * innerW; }
    function x2bp(x)  { return state.view.start + ((x - M.left) / innerW) * viewLen(); }
    function clientToSvgX(cx) {
        const r = elSvg.getBoundingClientRect();
        return ((cx - r.left) / r.width) * W;
    }
    function clientToSvgY(cy) {
        const r = elSvg.getBoundingClientRect();
        return ((cy - r.top) / r.height) * totalH;
    }

    function svg(tag, attrs) {
        const el = document.createElementNS(SVG_NS, tag);
        for (const k in attrs) el.setAttribute(k, attrs[k]);
        return el;
    }
    function clearChildren(el) { while (el.firstChild) el.removeChild(el.firstChild); }
    function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }

    function formatBp(n) {
        const r = Math.round(n);
        const a = Math.abs(r);
        if (a >= 1000000) return (r / 1000000).toFixed(2).replace(/\.?0+$/, '') + ' Mb';
        if (a >= 1000)    return (r / 1000).toFixed(1).replace(/\.0$/, '') + ' kb';
        return String(r);
    }

    function niceTickInterval(viewLen) {
        const target = viewLen / 9;
        const ladder = [1, 2, 5, 10, 20, 50, 100, 200, 500,
                        1000, 2000, 5000, 10000, 20000, 50000,
                        100000, 200000, 500000,
                        1000000, 2000000, 5000000, 10000000, 20000000];
        for (const c of ladder) if (c >= target) return c;
        return ladder[ladder.length - 1];
    }

    function parseBp(s) {
        if (typeof s !== 'string') return null;
        s = s.replace(/[_,\s]/g, '');
        let mult = 1;
        if (/[kK]$/.test(s)) { mult = 1000;       s = s.slice(0, -1); }
        else if (/[mM]$/.test(s)) { mult = 1000000;     s = s.slice(0, -1); }
        const n = parseFloat(s);
        if (!isFinite(n)) return null;
        return Math.round(n * mult);
    }

    function computeGC(a, b) {
        a = Math.max(0, Math.floor(a));
        b = Math.min(length, Math.ceil(b));
        if (b <= a) return null;

        // Best signal: if the requested range is fully inside the bases
        // we just fetched for the sequence panel, count exactly.
        const cached = remote.visibleSeq;
        if (cached && cached.start <= a && cached.end >= b) {
            const off = a - cached.start;
            const seq = cached.sequence;
            let gc = 0;
            for (let i = 0; i < (b - a); i++) {
                const c = seq.charCodeAt(off + i);
                if (c === 71 || c === 67 || c === 103 || c === 99) gc++;
            }
            return gc / (b - a);
        }

        // Otherwise, weighted average of the binned profile over [a, b).
        // Coarse for short ranges on long chromosomes, but it's a status
        // bar number — not a final analysis.
        if (remote.gcProfile) {
            const profile = remote.gcProfile;
            const bins = profile.length;
            const binBp = length / bins;
            const ai = Math.max(0, Math.floor(a / binBp));
            const bi = Math.min(bins - 1, Math.floor((b - 1) / binBp));
            let total = 0, weight = 0;
            for (let i = ai; i <= bi; i++) {
                const binStart = i * binBp;
                const binEnd = (i + 1) * binBp;
                const overlap = Math.min(b, binEnd) - Math.max(a, binStart);
                if (overlap > 0) {
                    total += profile[i] * overlap;
                    weight += overlap;
                }
            }
            return weight > 0 ? total / weight : null;
        }
        return null;
    }

    function escapeHtml(s) {
        return String(s)
            .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    }

    function truncateToWidth(text, pxWidth) {
        const maxChars = Math.max(0, Math.floor(pxWidth / 6.2));
        if (maxChars >= text.length) return text;
        if (maxChars < 4) return '';
        return text.slice(0, maxChars - 1) + '…';
    }

    function textColorFor(bg) {
        // YIQ contrast: dark text on light fills, light text on dark fills.
        const m = bg.match(/^#([0-9a-f]{6})$/i);
        if (!m) return '#0d1117';
        const h = m[1];
        const r = parseInt(h.slice(0, 2), 16);
        const g = parseInt(h.slice(2, 4), 16);
        const b = parseInt(h.slice(4, 6), 16);
        const yiq = (r * 299 + g * 587 + b * 114) / 1000;
        return yiq >= 140 ? '#0d1117' : '#f0f6fc';
    }

    function assignLanes(arr) {
        const lanes = []; // each entry = rightmost end placed in that lane
        for (const f of arr) {
            let placed = false;
            for (let i = 0; i < lanes.length; i++) {
                if (lanes[i] <= f.start) {
                    f._lane = i; lanes[i] = f.end; placed = true; break;
                }
            }
            if (!placed) { f._lane = lanes.length; lanes.push(f.end); }
        }
    }
    function laneCountOf(arr) {
        let m = -1;
        for (const f of arr) if (f._lane > m) m = f._lane;
        return m + 1;
    }
})();

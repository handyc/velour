/* Helix viewer — SVG annotation tracks above the sequence text grid.
 *
 * Reads two mounts:
 *   #helix-viewer-mount   data-length, data-features='[{...}]'
 *   #helix-sequence-mount data-sequence
 *
 * Renders one track per feature_type, packed greedily so overlapping
 * features in the same type stack vertically without overlap. Click a
 * feature → populates #helix-feature-detail with its qualifiers.
 */

(function() {
    const mount = document.getElementById('helix-viewer-mount');
    const detail = document.getElementById('helix-feature-detail');
    if (mount) renderTracks(mount, detail);

    const seqMount = document.getElementById('helix-sequence-mount');
    if (seqMount) renderSequence(seqMount);

    function renderTracks(mount, detail) {
        const length = parseInt(mount.dataset.length, 10) || 1;
        let features = [];
        try { features = JSON.parse(mount.dataset.features); }
        catch (e) { console.error('Helix: bad features payload', e); return; }

        // Color palette per feature type — Dark2-ish, distinct, colorblind-safer.
        const palette = {
            'gene':           '#1b9e77',
            'CDS':            '#d95f02',
            'mRNA':           '#7570b3',
            'tRNA':           '#e7298a',
            'rRNA':           '#66a61e',
            'ncRNA':          '#e6ab02',
            'regulatory':     '#a6761d',
            'misc_feature':   '#8b949e',
            'source':         '#3a3a3a',
            'repeat_region':  '#666666',
            'sig_peptide':    '#bc8cff',
            'mat_peptide':    '#56d364',
            'STS':            '#79c0ff',
            'gap':            '#444444',
        };
        const colorFor = (t) => palette[t] || '#a371f7';

        // Group features by type, then within a type lane-pack (no two
        // features in the same lane overlap on the X-axis).
        const byType = {};
        features.forEach(f => {
            (byType[f.type] = byType[f.type] || []).push(f);
        });
        const types = Object.keys(byType).sort();

        // Geometry
        const W = 1100;
        const margin = {left: 110, right: 18, top: 14, bottom: 28};
        const trackH = 14;     // per-lane row height
        const gap = 4;         // gap between feature types
        const innerW = W - margin.left - margin.right;

        // Per-type lane assignment (greedy interval-scheduling).
        const typeLanes = {};
        let totalLanes = 0;
        types.forEach(t => {
            const fs = byType[t].slice().sort((a, b) => a.start - b.start);
            const lanes = [];   // each lane: rightmost-end so far
            fs.forEach(f => {
                let placed = false;
                for (let i = 0; i < lanes.length; i++) {
                    if (lanes[i] <= f.start) {
                        f._lane = i;
                        lanes[i] = f.end;
                        placed = true;
                        break;
                    }
                }
                if (!placed) {
                    f._lane = lanes.length;
                    lanes.push(f.end);
                }
            });
            typeLanes[t] = lanes.length;
            totalLanes += lanes.length;
        });

        const H = margin.top + margin.bottom + totalLanes * trackH + (types.length - 1) * gap;

        // Build SVG.
        const svgNS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
        svg.setAttribute('xmlns', svgNS);
        svg.setAttribute('preserveAspectRatio', 'none');

        const xFor = (bp) => margin.left + (bp / length) * innerW;

        // Per-type rows.
        let yCursor = margin.top;
        types.forEach((t, ti) => {
            const laneCount = typeLanes[t];
            const rowTop = yCursor;

            // Type label on the left.
            const label = document.createElementNS(svgNS, 'text');
            label.setAttribute('class', 'helix-track-label');
            label.setAttribute('x', 8);
            label.setAttribute('y', rowTop + trackH * 0.7);
            label.textContent = `${t} (${byType[t].length})`;
            svg.appendChild(label);

            // Background row (subtle so it's visible even when empty).
            const bgRect = document.createElementNS(svgNS, 'rect');
            bgRect.setAttribute('x', margin.left);
            bgRect.setAttribute('y', rowTop);
            bgRect.setAttribute('width', innerW);
            bgRect.setAttribute('height', laneCount * trackH);
            bgRect.setAttribute('fill', '#161b22');
            svg.appendChild(bgRect);

            // Feature rectangles.
            byType[t].forEach(f => {
                const x = xFor(f.start);
                const w = Math.max(1.2, xFor(f.end) - x);
                const y = rowTop + f._lane * trackH + 1.5;
                const rect = document.createElementNS(svgNS, 'rect');
                rect.setAttribute('class', 'helix-feature');
                rect.setAttribute('x', x);
                rect.setAttribute('y', y);
                rect.setAttribute('width', w);
                rect.setAttribute('height', trackH - 3);
                rect.setAttribute('fill', colorFor(t));
                rect.setAttribute('rx', 1.5);
                rect.dataset.json = JSON.stringify(f);

                const tip = document.createElementNS(svgNS, 'title');
                tip.textContent = `${f.name} · ${f.start}-${f.end} (${f.end - f.start} bp, strand ${f.strand >= 0 ? '+' : '-'})`;
                rect.appendChild(tip);

                rect.addEventListener('click', (e) => {
                    document.querySelectorAll('.helix-feature.selected')
                        .forEach(r => r.classList.remove('selected'));
                    rect.classList.add('selected');
                    showFeature(detail, f);
                });
                svg.appendChild(rect);

                // Strand arrow on features that are wide enough to read.
                if (w > 18) {
                    const arrow = document.createElementNS(svgNS, 'text');
                    arrow.setAttribute('x', x + w / 2);
                    arrow.setAttribute('y', y + trackH * 0.6);
                    arrow.setAttribute('text-anchor', 'middle');
                    arrow.setAttribute('fill', '#0d1117');
                    arrow.setAttribute('font-size', '9');
                    arrow.setAttribute('font-family', 'ui-monospace, monospace');
                    arrow.setAttribute('pointer-events', 'none');
                    arrow.textContent = f.strand >= 0 ? '▶' : '◀';
                    svg.appendChild(arrow);
                }
            });

            yCursor = rowTop + laneCount * trackH + gap;
        });

        // Position axis at the bottom.
        const axis = document.createElementNS(svgNS, 'g');
        axis.setAttribute('class', 'helix-axis');
        const axisY = H - margin.bottom + 6;
        const axisLine = document.createElementNS(svgNS, 'line');
        axisLine.setAttribute('x1', margin.left);
        axisLine.setAttribute('x2', margin.left + innerW);
        axisLine.setAttribute('y1', axisY);
        axisLine.setAttribute('y2', axisY);
        axis.appendChild(axisLine);
        const tickN = 10;
        for (let i = 0; i <= tickN; i++) {
            const bp = Math.round((i / tickN) * length);
            const x = xFor(bp);
            const tick = document.createElementNS(svgNS, 'line');
            tick.setAttribute('x1', x); tick.setAttribute('x2', x);
            tick.setAttribute('y1', axisY); tick.setAttribute('y2', axisY + 4);
            axis.appendChild(tick);
            const lbl = document.createElementNS(svgNS, 'text');
            lbl.setAttribute('x', x);
            lbl.setAttribute('y', axisY + 14);
            lbl.setAttribute('text-anchor', 'middle');
            lbl.textContent = formatBp(bp);
            axis.appendChild(lbl);
        }
        svg.appendChild(axis);

        mount.innerHTML = '';
        mount.appendChild(svg);
    }

    function showFeature(detail, f) {
        if (!detail) return;
        const lines = [`<h4>${escapeHtml(f.name)} <span style="color:#8b949e;font-weight:normal;font-size:0.85em;">· ${f.type}</span></h4>`];
        lines.push(
            `<div class="qual-row"><span class="qual-key">Position</span>` +
            `<span class="qual-val">${f.start}–${f.end} (${f.end - f.start} bp, strand ${f.strand >= 0 ? '+' : '-'})</span></div>`
        );
        const q = f.qualifiers || {};
        Object.keys(q).sort().forEach(key => {
            const v = q[key];
            const vText = Array.isArray(v) ? v.join(', ') : String(v);
            lines.push(
                `<div class="qual-row"><span class="qual-key">${escapeHtml(key)}</span>` +
                `<span class="qual-val">${escapeHtml(vText)}</span></div>`
            );
        });
        detail.innerHTML = lines.join('');
    }

    function renderSequence(mount) {
        const seq = mount.dataset.sequence || '';
        if (!seq) { mount.textContent = '(empty sequence)'; return; }
        // Collapse very long sequences: render the first 12 KB worth.
        const limit = 12000;
        const truncated = seq.length > limit;
        const visible = truncated ? seq.slice(0, limit) : seq;

        const COLS = 60;
        const frags = [];
        for (let i = 0; i < visible.length; i += COLS) {
            const chunk = visible.slice(i, i + COLS);
            const colored = chunk.split('').map(b =>
                `<span class="b-${b}">${b}</span>`
            ).join('');
            // Pad position labels to a stable width.
            const pos = String(i + 1).padStart(5, ' ');
            frags.push(
                `<div class="seq-row"><span class="seq-pos">${pos}</span>` +
                `<span class="seq-bases">${colored}</span></div>`
            );
        }
        if (truncated) {
            frags.push(
                `<div style="color:#8b949e;font-style:italic;margin-top:0.5rem;">` +
                `… ${seq.length - limit} more bases truncated. Download FASTA for the full sequence.</div>`
            );
        }
        mount.innerHTML = frags.join('');
    }

    function formatBp(n) {
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
        return String(n);
    }

    function escapeHtml(s) {
        return String(s)
            .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    }
})();

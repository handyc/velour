/* Room Planner editor — drag, select, rotate, rename, delete,
   and add-placement / add-feature / add-custom-piece.

   All coordinates in centimetres; the SVG viewBox is in cm too, so
   we use SVG's own screen↔user-space transform (getScreenCTM) to
   map pointer pixels back to cm without caring about the page scale.
*/
(function () {
  'use strict';

  const svg         = document.getElementById('rp-canvas');
  if (!svg) return;
  const roomSlug    = svg.dataset.roomSlug;
  const roomW       = parseInt(svg.dataset.roomW, 10);
  const roomH       = parseInt(svg.dataset.roomH, 10);
  const placements  = document.getElementById('rp-placements');
  const features    = document.getElementById('rp-features');
  const gridG       = document.getElementById('rp-grid');
  const toolbar     = document.getElementById('rp-toolbar');
  const tbLabel     = document.getElementById('rp-tb-label');
  const tbRotate    = document.getElementById('rp-tb-rotate');
  const tbRename    = document.getElementById('rp-tb-rename');
  const tbDelete    = document.getElementById('rp-tb-delete');
  const csrfInput   = document.querySelector('input[name=csrfmiddlewaretoken]');
  const csrfToken   = csrfInput ? csrfInput.value : '';
  const apiRoom     = `/roomplanner/${roomSlug}/api`;

  // -------------------------------------------------- grid
  // Draw 50cm gridlines once.
  (function drawGrid() {
    const xmlns = 'http://www.w3.org/2000/svg';
    const frag  = document.createDocumentFragment();
    for (let x = 50; x < roomW; x += 50) {
      const l = document.createElementNS(xmlns, 'line');
      l.setAttribute('x1', x); l.setAttribute('y1', 0);
      l.setAttribute('x2', x); l.setAttribute('y2', roomH);
      frag.appendChild(l);
    }
    for (let y = 50; y < roomH; y += 50) {
      const l = document.createElementNS(xmlns, 'line');
      l.setAttribute('x1', 0);      l.setAttribute('y1', y);
      l.setAttribute('x2', roomW);  l.setAttribute('y2', y);
      frag.appendChild(l);
    }
    gridG.appendChild(frag);
  })();

  // -------------------------------------------------- helpers
  function screenToSvg(evt) {
    const pt  = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const inv = ctm.inverse();
    const p   = pt.matrixTransform(inv);
    return { x: p.x, y: p.y };
  }

  async function api(path, body) {
    const res = await fetch(path, {
      method:  'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRFToken':  csrfToken,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body || {}),
    });
    let data;
    try { data = await res.json(); }
    catch (_) { data = { ok: false, error: `HTTP ${res.status}` }; }
    if (!res.ok && data.ok === undefined) data.ok = false;
    return data;
  }

  function setMsg(el, text, level) {
    if (!el) return;
    el.textContent = text || '';
    el.classList.remove('ok', 'err');
    if (level) el.classList.add(level);
  }

  // -------------------------------------------------- selection
  let selected = null;

  function select(group) {
    if (selected) selected.classList.remove('selected');
    selected = group || null;
    if (selected) {
      selected.classList.add('selected');
      tbLabel.textContent = selected.dataset.label ||
        selected.dataset.kind || 'item';
      const isPlacement = selected.dataset.type === 'placement';
      tbRotate.style.display = isPlacement ? '' : 'none';
      toolbar.classList.add('visible');
      // bring to front
      selected.parentNode.appendChild(selected);
    } else {
      toolbar.classList.remove('visible');
    }
  }

  // -------------------------------------------------- drag
  let dragging = null;
  let dragOffset = { x: 0, y: 0 };

  svg.addEventListener('pointerdown', (evt) => {
    const g = evt.target.closest('.rp-placement, .rp-feature');
    if (!g) { select(null); return; }
    evt.preventDefault();
    select(g);
    const p  = screenToSvg(evt);
    const gx = parseFloat(g.dataset.x) || 0;
    const gy = parseFloat(g.dataset.y) || 0;
    dragOffset = { x: p.x - gx, y: p.y - gy };
    dragging   = g;
    g.classList.add('dragging');
    svg.setPointerCapture(evt.pointerId);
  });

  svg.addEventListener('pointermove', (evt) => {
    if (!dragging) return;
    const p = screenToSvg(evt);
    const w = parseFloat(dragging.dataset.w) || 0;
    const h = parseFloat(dragging.dataset.h) || 0;
    let x = Math.round(p.x - dragOffset.x);
    let y = Math.round(p.y - dragOffset.y);
    x = Math.max(0, Math.min(x, roomW - w));
    y = Math.max(0, Math.min(y, roomH - h));
    dragging.dataset.x = x;
    dragging.dataset.y = y;
    dragging.setAttribute('transform', `translate(${x} ${y})`);
  });

  async function endDrag(evt) {
    if (!dragging) return;
    const g = dragging;
    dragging.classList.remove('dragging');
    try { svg.releasePointerCapture(evt.pointerId); } catch (_) {}
    dragging = null;
    const type = g.dataset.type;
    const id   = g.dataset.id;
    const path = `${apiRoom}/${type}/${id}/update/`;
    const data = await api(path, {
      x_cm: parseInt(g.dataset.x, 10),
      y_cm: parseInt(g.dataset.y, 10),
    });
    if (!data.ok) {
      console.warn('move failed', data);
    }
  }
  svg.addEventListener('pointerup',     endDrag);
  svg.addEventListener('pointercancel', endDrag);

  // -------------------------------------------------- toolbar actions

  tbRotate.addEventListener('click', async () => {
    if (!selected || selected.dataset.type !== 'placement') return;
    const cur = parseInt(selected.dataset.rot || '0', 10);
    const next = (cur + 90) % 360;
    const id = selected.dataset.id;
    const data = await api(`${apiRoom}/placement/${id}/update/`, {
      rotation_deg: next,
    });
    if (data.ok) {
      selected.dataset.rot = data.rot;
      selected.dataset.x   = data.x;
      selected.dataset.y   = data.y;
      selected.dataset.w   = data.w;
      selected.dataset.h   = data.h;
      selected.setAttribute('transform', `translate(${data.x} ${data.y})`);
      const rect = selected.querySelector('rect');
      if (rect) {
        rect.setAttribute('width',  data.w);
        rect.setAttribute('height', data.h);
      }
    }
  });

  tbRename.addEventListener('click', async () => {
    if (!selected) return;
    const cur = selected.dataset.label || '';
    const next = window.prompt('New label:', cur);
    if (next === null) return;
    const type = selected.dataset.type;
    const id   = selected.dataset.id;
    const data = await api(`${apiRoom}/${type}/${id}/update/`, { label: next });
    if (data.ok) {
      selected.dataset.label = data.label;
      const t = selected.querySelector('text.rp-label');
      if (t) t.textContent = data.label;
      tbLabel.textContent = data.label;
    }
  });

  tbDelete.addEventListener('click', async () => {
    if (!selected) return;
    const type = selected.dataset.type;
    const id   = selected.dataset.id;
    const label = selected.dataset.label || type;
    if (!window.confirm(`Remove “${label}”?`)) return;
    const data = await api(`${apiRoom}/${type}/${id}/delete/`, {});
    if (data.ok) {
      selected.remove();
      select(null);
    }
  });

  // -------------------------------------------------- rendering new items

  const FEATURE_COLORS = {
    door: '#f0883e',  window: '#58a6ff', outlet: '#f85149',
    vent: '#a5a5a5',  radiator: '#db6d28', pillar: '#6e7681',
    sink: '#58a6ff',  ethernet: '#3fb950', other: '#8b949e',
  };

  function makePlacementGroup(data) {
    const xmlns = 'http://www.w3.org/2000/svg';
    const g = document.createElementNS(xmlns, 'g');
    g.setAttribute('class', 'rp-placement');
    g.dataset.id       = data.id;
    g.dataset.type     = 'placement';
    g.dataset.pieceId  = data.piece_id;
    g.dataset.x        = data.x;
    g.dataset.y        = data.y;
    g.dataset.w        = data.w;
    g.dataset.h        = data.h;
    g.dataset.rot      = data.rot;
    g.dataset.label    = data.label || '';
    g.setAttribute('transform', `translate(${data.x} ${data.y})`);
    const rect = document.createElementNS(xmlns, 'rect');
    rect.setAttribute('x', 0); rect.setAttribute('y', 0);
    rect.setAttribute('width',  data.w);
    rect.setAttribute('height', data.h);
    rect.setAttribute('fill',   data.fill || '#30363d');
    rect.setAttribute('stroke', '#c9d1d9');
    rect.setAttribute('stroke-width', '1');
    rect.setAttribute('opacity', '0.85');
    rect.setAttribute('rx', '2');
    g.appendChild(rect);
    const text = document.createElementNS(xmlns, 'text');
    text.setAttribute('class', 'rp-label');
    text.setAttribute('x', 4); text.setAttribute('y', 14);
    text.setAttribute('fill', '#c9d1d9');
    text.setAttribute('font-size', '11');
    text.setAttribute('font-family', 'ui-monospace, monospace');
    text.setAttribute('pointer-events', 'none');
    text.textContent = data.label || '';
    g.appendChild(text);
    return g;
  }

  function makeFeatureGroup(data) {
    const xmlns = 'http://www.w3.org/2000/svg';
    const fill  = data.fill || FEATURE_COLORS[data.kind] || '#8b949e';
    const g = document.createElementNS(xmlns, 'g');
    g.setAttribute('class', 'rp-feature');
    g.dataset.id    = data.id;
    g.dataset.type  = 'feature';
    g.dataset.kind  = data.kind;
    g.dataset.x     = data.x;
    g.dataset.y     = data.y;
    g.dataset.w     = data.w;
    g.dataset.h     = data.h;
    g.dataset.label = data.label || '';
    g.setAttribute('transform', `translate(${data.x} ${data.y})`);
    const rect = document.createElementNS(xmlns, 'rect');
    rect.setAttribute('x', 0); rect.setAttribute('y', 0);
    rect.setAttribute('width',  data.w);
    rect.setAttribute('height', data.h);
    rect.setAttribute('fill', fill);
    rect.setAttribute('opacity', '0.9');
    g.appendChild(rect);
    const text = document.createElementNS(xmlns, 'text');
    text.setAttribute('class', 'rp-label');
    text.setAttribute('x', 0); text.setAttribute('y', -3);
    text.setAttribute('fill', fill);
    text.setAttribute('font-size', '9');
    text.setAttribute('font-family', 'ui-monospace, monospace');
    text.setAttribute('pointer-events', 'none');
    text.textContent = data.label || '';
    g.appendChild(text);
    return g;
  }

  // -------------------------------------------------- side panels

  // Add placement from catalog
  document.getElementById('rp-add-placement').addEventListener('click', async () => {
    const sel = document.getElementById('rp-catalog-select');
    const msg = document.getElementById('rp-place-msg');
    const pieceId = sel.value;
    if (!pieceId) { setMsg(msg, 'pick a piece first', 'err'); return; }
    const label = document.getElementById('rp-place-label').value.trim();
    setMsg(msg, 'placing…');
    const data = await api(`${apiRoom}/placement/add/`, {
      piece_id: parseInt(pieceId, 10),
      label:    label,
    });
    if (!data.ok) { setMsg(msg, data.error || 'failed', 'err'); return; }
    placements.appendChild(makePlacementGroup(data));
    setMsg(msg, `added — drag it to position`, 'ok');
    document.getElementById('rp-place-label').value = '';
  });

  // Add custom piece (catalog entry) + place it
  document.getElementById('rp-add-piece').addEventListener('click', async () => {
    const msg  = document.getElementById('rp-piece-msg');
    const name = document.getElementById('rp-new-name').value.trim();
    if (!name) { setMsg(msg, 'name required', 'err'); return; }
    const payload = {
      name: name,
      kind: document.getElementById('rp-new-kind').value,
      width_cm:     parseInt(document.getElementById('rp-new-w').value, 10) || 60,
      depth_cm:     parseInt(document.getElementById('rp-new-d').value, 10) || 40,
      height_cm:    parseInt(document.getElementById('rp-new-h').value, 10) || 0,
      heat_watts:   parseInt(document.getElementById('rp-new-heat').value, 10) || 0,
      needs_outlet: document.getElementById('rp-new-outlet').checked,
    };
    setMsg(msg, 'saving…');
    const piece = await api('/roomplanner/api/piece/add/', payload);
    if (!piece.ok) { setMsg(msg, piece.error || 'failed', 'err'); return; }

    // Place it immediately so the user sees it in-room.
    const place = await api(`${apiRoom}/placement/add/`, {
      piece_id: piece.id,
      label:    name,
    });
    if (!place.ok) {
      setMsg(msg, 'piece added to catalog, but place failed: ' + (place.error || ''), 'err');
      return;
    }

    placements.appendChild(makePlacementGroup(place));

    // Add to catalog dropdown so user can place again without reload.
    const sel = document.getElementById('rp-catalog-select');
    const opt = document.createElement('option');
    opt.value = piece.id;
    opt.textContent = `${piece.name} — ${piece.width_cm}×${piece.depth_cm}cm`;
    opt.dataset.w    = piece.width_cm;
    opt.dataset.h    = piece.depth_cm;
    opt.dataset.kind = piece.kind;
    sel.appendChild(opt);

    setMsg(msg, `added “${piece.name}” to catalog and room`, 'ok');
    document.getElementById('rp-new-name').value = '';
  });

  // Score this layout
  const scoreBtn = document.getElementById('rp-score-btn');
  const scoreVerdict = document.getElementById('rp-score-verdict');
  const scoreBreakdown = document.getElementById('rp-score-breakdown');
  const violationsG = document.getElementById('rp-violations');

  const VERDICT_CLASS = {
    'clean':         'rp-verdict-clean',
    'minor issues':  'rp-verdict-minor',
    'needs work':    'rp-verdict-work',
    'unsafe':        'rp-verdict-unsafe',
  };

  function renderViolationOverlays(violations) {
    const xmlns = 'http://www.w3.org/2000/svg';
    while (violationsG.firstChild) violationsG.removeChild(violationsG.firstChild);
    for (const v of violations) {
      if (!v.zone) continue;
      const z = v.zone;
      const r = document.createElementNS(xmlns, 'rect');
      r.setAttribute('class', 'rp-violation-zone');
      r.setAttribute('x', z.x); r.setAttribute('y', z.y);
      r.setAttribute('width', z.w); r.setAttribute('height', z.h);
      violationsG.appendChild(r);
    }
  }

  function renderScore(data, prefix) {
    scoreVerdict.textContent = `${data.verdict} (penalty ${data.total})` +
      (prefix ? ` — ${prefix}` : '');
    scoreVerdict.className = '';
    const cls = VERDICT_CLASS[data.verdict];
    if (cls) scoreVerdict.classList.add(cls);

    while (scoreBreakdown.firstChild) scoreBreakdown.removeChild(scoreBreakdown.firstChild);
    if (!data.violations.length) {
      const li = document.createElement('li');
      li.textContent = 'no violations';
      li.style.color = '#3fb950';
      scoreBreakdown.appendChild(li);
    }
    for (const v of data.violations) {
      const li = document.createElement('li');
      li.className = `rp-sev-${v.severity}`;
      li.textContent = v.message;
      scoreBreakdown.appendChild(li);
    }
    renderViolationOverlays(data.violations);
  }

  if (scoreBtn) {
    scoreBtn.addEventListener('click', async () => {
      setMsg(document.getElementById('rp-score-msg'), 'scoring…');
      const res = await fetch(`${apiRoom}/room/score/`, {
        credentials: 'same-origin',
      });
      let data;
      try { data = await res.json(); }
      catch (_) { data = { total: -1, verdict: 'error', violations: [] }; }
      renderScore(data);
      setMsg(document.getElementById('rp-score-msg'), '');
    });
  }

  // Evolve button — runs a short GA, applies the best layout, updates
  // the placements in place.
  const evolveBtn = document.getElementById('rp-evolve-btn');
  const evoGensInput = document.getElementById('rp-evo-gens');
  const evoPopInput  = document.getElementById('rp-evo-pop');
  const evoSpark     = document.getElementById('rp-evo-spark');
  const evoSparkLine = document.getElementById('rp-evo-spark-line');

  function drawEvoSpark(history) {
    if (!history || !history.length) {
      evoSpark.style.display = 'none';
      return;
    }
    const bests = history.map(h => h.best);
    const lo = Math.min(...bests), hi = Math.max(...bests);
    const span = (hi - lo) || 1;
    const W = 180, H = 28, n = bests.length;
    const pts = bests.map((b, i) => {
      const x = n === 1 ? W / 2 : (i / (n - 1)) * (W - 2) + 1;
      const y = H - 2 - ((b - lo) / span) * (H - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    evoSparkLine.setAttribute('points', pts.join(' '));
    evoSpark.style.display = 'block';
  }

  function applyPlacementUpdates(updates) {
    for (const u of updates) {
      const g = placements.querySelector(
        `.rp-placement[data-id="${u.id}"]`,
      );
      if (!g) continue;
      g.dataset.x = u.x;
      g.dataset.y = u.y;
      g.dataset.w = u.w;
      g.dataset.h = u.h;
      g.dataset.rot = u.rot;
      g.setAttribute('transform', `translate(${u.x} ${u.y})`);
      const rect = g.querySelector('rect');
      if (rect) {
        rect.setAttribute('width',  u.w);
        rect.setAttribute('height', u.h);
      }
    }
  }

  if (evolveBtn) {
    evolveBtn.addEventListener('click', async () => {
      const msg = document.getElementById('rp-score-msg');
      const gens = Math.max(10, Math.min(500,
        parseInt(evoGensInput.value, 10) || 60));
      const pop  = Math.max(4, Math.min(100,
        parseInt(evoPopInput.value, 10) || 30));
      const confirmed = window.confirm(
        `Run the genetic search? This will move your furniture to a ` +
        `lower-penalty layout (${gens} generations × ${pop} population).`
      );
      if (!confirmed) return;

      evolveBtn.disabled = true;
      setMsg(msg, `evolving ${gens} × ${pop}…`);
      try {
        const data = await api(`${apiRoom}/room/evolve/`, {
          generations: gens,
          population:  pop,
        });
        if (!data.ok) {
          setMsg(msg, data.error || 'evolve failed', 'err');
          return;
        }
        applyPlacementUpdates(data.placements || []);
        drawEvoSpark(data.history || []);
        renderScore(data.score,
          `was ${data.initial_score} → now ${data.best_score} ` +
          `(${data.improvement > 0 ? '−' : ''}${Math.abs(data.improvement)})`);
        setMsg(msg,
          `${data.generations} gens × ${data.population} pop complete`,
          'ok');
      } finally {
        evolveBtn.disabled = false;
      }
    });
  }

  // Orientation: north_direction change → re-label the four compass texts.
  const northSel = document.getElementById('rp-north');
  if (northSel) {
    northSel.addEventListener('change', async () => {
      const msg = document.getElementById('rp-orient-msg');
      setMsg(msg, 'saving…');
      const data = await api(`${apiRoom}/room/update/`, {
        north_direction: northSel.value,
      });
      if (!data.ok) { setMsg(msg, data.error || 'failed', 'err'); return; }
      const e = data.edge_labels || {};
      const set = (id, txt) => {
        const el = document.getElementById(id);
        if (el && txt) el.textContent = txt;
      };
      set('rp-compass-top',    e.top);
      set('rp-compass-right',  e.right);
      set('rp-compass-bottom', e.bottom);
      set('rp-compass-left',   e.left);
      setMsg(msg, `north → ${data.north_direction}`, 'ok');
    });
  }

  // Detect via IP
  const locateBtn = document.getElementById('rp-locate-btn');
  if (locateBtn) {
    locateBtn.addEventListener('click', async () => {
      const msg  = document.getElementById('rp-locate-msg');
      const disp = document.getElementById('rp-loc-display');
      setMsg(msg, 'asking ip-api.com…');
      locateBtn.disabled = true;
      try {
        const data = await api(`${apiRoom}/room/locate/`, {});
        if (!data.ok) {
          setMsg(msg, data.error || 'geolocation failed', 'err');
          return;
        }
        const lat = (data.latitude  || 0).toFixed(3);
        const lon = (data.longitude || 0).toFixed(3);
        if (disp) {
          disp.innerHTML = `${data.location_city || '—'} ` +
            `<small style="color:#8b949e;">(${lat}, ${lon})</small>`;
        }
        setMsg(msg, `detected — public IP ${data.public_ip || '?'}`, 'ok');
      } finally {
        locateBtn.disabled = false;
      }
    });
  }

  // Add feature
  document.getElementById('rp-add-feature').addEventListener('click', async () => {
    const msg = document.getElementById('rp-feat-msg');
    const payload = {
      kind:     document.getElementById('rp-feat-kind').value,
      label:    document.getElementById('rp-feat-label').value.trim(),
      width_cm: parseInt(document.getElementById('rp-feat-w').value, 10) || 30,
      depth_cm: parseInt(document.getElementById('rp-feat-d').value, 10) || 10,
    };
    setMsg(msg, 'adding…');
    const data = await api(`${apiRoom}/feature/add/`, payload);
    if (!data.ok) { setMsg(msg, data.error || 'failed', 'err'); return; }
    features.appendChild(makeFeatureGroup(data));
    setMsg(msg, 'added — drag it to position', 'ok');
    document.getElementById('rp-feat-label').value = '';
  });

})();

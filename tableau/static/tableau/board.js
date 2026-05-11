/* tableau/board.js — isometric canvas renderer + page wiring.
 *
 * Two board geometries share one render loop.  Square mode draws an
 * NxN chess plate tilted 30°; hex mode draws an axial-radius-R
 * pointy-top hex grid under the same iso transform.  Pieces are flat
 * 2D plates (cube=square, tet=triangle, dodec=hexagon) with a drop
 * shadow; size scales by area.  Names hover above each piece in a
 * monospace label.
 *
 * Server state arrives via /w/<id>/state.json and is reloaded after
 * every mutation; the renderer is stateless beyond `state` itself.
 * Eval results land via /w/<id>/evaluate/ after every change so the
 * sentence panel updates live.
 */

(function () {
  "use strict";

  const T   = window.TABLEAU;
  const canvas = document.getElementById("tableauCanvas");
  const ctx = canvas.getContext("2d");

  // ── palette state ───────────────────────────────────────────────
  let palette = { shape: "cube", size: "medium", name: "" };
  let state = null;          // last serialised world from /state.json

  function bindPalette(id, key) {
    const row = document.getElementById(id);
    row.addEventListener("click", (e) => {
      const btn = e.target.closest("button.opt");
      if (!btn) return;
      row.querySelectorAll("button.opt").forEach(b => b.classList.remove("on"));
      btn.classList.add("on");
      palette[key] = btn.dataset[key] ?? "";
    });
  }
  bindPalette("paletteShape", "shape");
  bindPalette("paletteSize",  "size");
  bindPalette("paletteName",  "name");

  // ── isometric geometry ──────────────────────────────────────────
  //
  // For square mode we project board coords (cx, cy) ∈ [0..N)² to
  // screen space with a tilt: x_screen = (cx - cy) * TILE_W/2;
  // y_screen = (cx + cy) * TILE_H/2.  Standard iso transform.
  //
  // For hex mode the natural choice is to keep the hex layout
  // (pointy-top with axial coords) and apply the same iso tilt to
  // the layout's pixel coords.  Pointy-top axial → pixel:
  //   px = HEX_SIZE * sqrt(3) * (q + r/2)
  //   py = HEX_SIZE * 3/2 * r
  // Then we squish py by ISO_K (0.55) for the iso feel.

  const ISO_K = 0.55;     // vertical squish: smaller = flatter perspective
  const TILE_W = 64;
  const TILE_H = 64 * ISO_K;

  const HEX_SIZE = 30;
  const HEX_DX   = HEX_SIZE * Math.sqrt(3);     // horizontal pitch
  const HEX_DY   = HEX_SIZE * 1.5;              // vertical pitch (pre-iso)

  function projectSquare(cx, cy, dim) {
    // Centre the board at (canvasW/2, canvasH/2 - some lift).
    const sx = (cx - cy) * (TILE_W / 2);
    const sy = (cx + cy) * (TILE_H / 2);
    const lift = -dim * TILE_H / 2;
    return {
      x: canvas.width  / 2 + sx,
      y: canvas.height / 2 + sy + lift,
    };
  }

  function projectHex(q, r) {
    const px = HEX_DX * (q + r / 2);
    const py = HEX_DY * r;
    return {
      x: canvas.width  / 2 + px,
      y: canvas.height / 2 + py * ISO_K,
    };
  }

  // Pick the cell under a screen-space point.  Inverse iso transform
  // for square; nearest-cell for hex (axial round).
  function pickCellSquare(mx, my, dim) {
    const sx = mx - canvas.width / 2;
    const sy = my - canvas.height / 2 + dim * TILE_H / 2;
    // Inverse of the projection.
    const cx = (sx / (TILE_W / 2) + sy / (TILE_H / 2)) / 2;
    const cy = (sy / (TILE_H / 2) - sx / (TILE_W / 2)) / 2;
    const ix = Math.round(cx);
    const iy = Math.round(cy);
    if (ix < 0 || iy < 0 || ix >= dim || iy >= dim) return null;
    return { x: ix, y: iy };
  }

  function pickCellHex(mx, my, R) {
    // Iterate cells, pick closest centre.  R is small (≤8) so this
    // is cheap and exact under iso squish.
    let best = null;
    let bestD = Infinity;
    for (let q = -R; q <= R; q++) {
      const lo = Math.max(-R, -q - R);
      const hi = Math.min( R, -q + R);
      for (let r = lo; r <= hi; r++) {
        const p = projectHex(q, r);
        const d = (p.x - mx) ** 2 + (p.y - my) ** 2;
        if (d < bestD) { bestD = d; best = { x: q, y: r }; }
      }
    }
    // Reject clicks too far from any cell centre.
    if (bestD > (HEX_SIZE * HEX_SIZE)) return null;
    return best;
  }

  // ── drawing helpers ─────────────────────────────────────────────

  function drawSquareCell(cx, cy, dim) {
    const p00 = projectSquare(cx,     cy,     dim);
    const p10 = projectSquare(cx + 1, cy,     dim);
    const p11 = projectSquare(cx + 1, cy + 1, dim);
    const p01 = projectSquare(cx,     cy + 1, dim);
    ctx.beginPath();
    ctx.moveTo(p00.x, p00.y);
    ctx.lineTo(p10.x, p10.y);
    ctx.lineTo(p11.x, p11.y);
    ctx.lineTo(p01.x, p01.y);
    ctx.closePath();
    ctx.fillStyle   = (cx + cy) % 2 ? "#1c2128" : "#161b22";
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth   = 1;
    ctx.fill();
    ctx.stroke();
  }

  function drawHexCell(q, r) {
    const c = projectHex(q, r);
    ctx.beginPath();
    for (let k = 0; k < 6; k++) {
      // Pointy-top corners at 30°, 90°, ... (60° step from start).
      const ang = Math.PI / 180 * (60 * k - 90);
      const px = c.x + HEX_SIZE * Math.cos(ang);
      // ISO squish only on y.
      const py = c.y + HEX_SIZE * Math.sin(ang) * ISO_K;
      if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
    // Three-tone shading for visual interest: q + 2*r parity classes.
    const tri = ((q - r) % 3 + 3) % 3;
    ctx.fillStyle = ["#161b22", "#1c2128", "#21262d"][tri];
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth   = 1;
    ctx.fill();
    ctx.stroke();
  }

  // Block silhouettes — drawn centred on the cell projection, area
  // scales with size.  Shadow goes UNDER the silhouette.
  const SIZE_RADIUS = { small: 11, medium: 16, large: 22 };
  const SHAPE_FILL  = {
    cube:  "#7c8df5",   // periwinkle
    tet:   "#f5a07c",   // warm coral
    dodec: "#7cf5b8",   // mint
  };
  const SHAPE_STROKE = {
    cube:  "#3f4eaf",
    tet:   "#aa663d",
    dodec: "#3fa676",
  };

  function drawBlock(b, mode, dim) {
    const p = (mode === "square")
      ? projectSquare(b.x + 0.5, b.y + 0.5, dim)
      : projectHex(b.x, b.y);
    const R = SIZE_RADIUS[b.size] || 14;
    // Drop shadow — squashed ellipse just below the piece.
    ctx.beginPath();
    ctx.ellipse(p.x, p.y + R * 0.7, R * 0.95, R * 0.4, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fill();

    // Silhouette by shape.
    ctx.beginPath();
    if (b.shape === "cube") {
      // Diamond (square rotated 45° — reads as a top-down cube in iso).
      ctx.moveTo(p.x,     p.y - R);
      ctx.lineTo(p.x + R, p.y);
      ctx.lineTo(p.x,     p.y + R);
      ctx.lineTo(p.x - R, p.y);
    } else if (b.shape === "tet") {
      // Equilateral triangle pointing up.
      ctx.moveTo(p.x,           p.y - R);
      ctx.lineTo(p.x + R * 0.87, p.y + R * 0.5);
      ctx.lineTo(p.x - R * 0.87, p.y + R * 0.5);
    } else {
      // Hexagon for dodec.
      for (let k = 0; k < 6; k++) {
        const ang = Math.PI / 180 * (60 * k - 30);
        const x = p.x + R * Math.cos(ang);
        const y = p.y + R * Math.sin(ang);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
    ctx.fillStyle   = SHAPE_FILL[b.shape]   || "#999";
    ctx.strokeStyle = SHAPE_STROKE[b.shape] || "#555";
    ctx.lineWidth   = 2;
    ctx.fill();
    ctx.stroke();

    // Name label above the piece.
    if (b.name) {
      ctx.font = "bold 12px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.fillStyle   = "#0d1117";
      ctx.textAlign   = "center";
      ctx.textBaseline = "alphabetic";
      // Stroke underlay for legibility against any background.
      ctx.lineWidth   = 3;
      ctx.strokeStyle = "#0d1117";
      ctx.strokeText(b.name, p.x, p.y - R - 5);
      ctx.fillStyle   = "#c9d1d9";
      ctx.fillText  (b.name, p.x, p.y - R - 5);
    }
  }

  function render() {
    if (!state) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (state.mode === "square") {
      // Draw cells back-to-front so silhouettes don't get overdrawn by
      // distant cells.  Iso back-to-front order: (cx + cy) ascending.
      for (let cy = 0; cy < state.dim; cy++) {
        for (let cx = 0; cx < state.dim; cx++) drawSquareCell(cx, cy, state.dim);
      }
    } else {
      const R = state.dim;
      for (let q = -R; q <= R; q++) {
        const lo = Math.max(-R, -q - R);
        const hi = Math.min( R, -q + R);
        for (let r = lo; r <= hi; r++) drawHexCell(q, r);
      }
    }

    // Blocks sorted by depth so nearer pieces cover farther ones.
    const sorted = state.blocks.slice().sort((a, b) => {
      // Depth proxy: y in square, r-q in hex.
      const da = (state.mode === "square") ? a.x + a.y : a.x + a.y;
      const db = (state.mode === "square") ? b.x + b.y : b.x + b.y;
      return da - db;
    });
    for (const b of sorted) drawBlock(b, state.mode, state.dim);
  }

  // ── server I/O ──────────────────────────────────────────────────

  async function fetchState() {
    const r = await fetch(T.endpoints.state);
    state = await r.json();
    render();
    refreshSentenceList();
    evaluateAll();
  }

  async function postJson(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const txt = await r.text();
      console.warn("post failed:", r.status, txt);
      return null;
    }
    state = await r.json();
    render();
    refreshSentenceList();
    evaluateAll();
    return state;
  }

  async function evaluateAll() {
    const r = await fetch(T.endpoints.evaluate);
    if (!r.ok) return;
    const data = await r.json();
    const byId = new Map(data.results.map(o => [o.id, o]));
    for (const row of document.querySelectorAll(".tableau-sentence")) {
      const id = parseInt(row.dataset.id, 10);
      const verdictEl = row.querySelector(".verdict");
      const errEl     = row.querySelector(".err-msg");
      const res = byId.get(id);
      if (!res) { verdictEl.textContent = "?"; verdictEl.className = "verdict"; continue; }
      if (!res.ok) {
        verdictEl.textContent = "err";
        verdictEl.className = "verdict err";
        if (errEl) errEl.textContent = res.error;
      } else {
        verdictEl.textContent = res.value ? "T" : "F";
        verdictEl.className = "verdict " + (res.value ? "t" : "f");
        if (errEl) errEl.textContent = "";
      }
    }
  }

  // ── sentence panel UI ───────────────────────────────────────────

  function refreshSentenceList() {
    const list = document.getElementById("sentenceList");
    list.innerHTML = "";
    if (!state) return;
    for (const s of state.sentences) {
      const row = document.createElement("div");
      row.className = "tableau-sentence";
      row.dataset.id = s.id;
      row.innerHTML = `
        <textarea rows="1" spellcheck="false">${escapeHtml(s.text)}</textarea>
        <span class="verdict">…</span>
        <div class="row-actions">
          target:
          <select>
            <option value="both"   ${s.target_mode === "both"   ? "selected" : ""}>both</option>
            <option value="square" ${s.target_mode === "square" ? "selected" : ""}>square</option>
            <option value="hex"    ${s.target_mode === "hex"    ? "selected" : ""}>hex</option>
          </select>
          <span style="margin-left:auto"></span>
          <button class="delBtn">delete</button>
        </div>
        <div class="err-msg">${escapeHtml(s.parse_error || "")}</div>
      `;
      const ta = row.querySelector("textarea");
      ta.addEventListener("change", () => {
        postJson(T.endpoints.sentences, {
          action: "upsert", id: s.id,
          text: ta.value,
          target_mode: row.querySelector("select").value,
        });
      });
      row.querySelector("select").addEventListener("change", (e) => {
        postJson(T.endpoints.sentences, {
          action: "upsert", id: s.id,
          text: ta.value,
          target_mode: e.target.value,
        });
      });
      row.querySelector(".delBtn").addEventListener("click", () => {
        postJson(T.endpoints.sentences, { action: "delete", id: s.id });
      });
      list.appendChild(row);
    }
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c => (
      {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  document.getElementById("addSentence").addEventListener("click", () => {
    const inp = document.getElementById("newSentence");
    const text = inp.value.trim();
    if (!text) return;
    postJson(T.endpoints.sentences, {
      action: "upsert", id: null,
      text: text, target_mode: "both",
    }).then(() => { inp.value = ""; });
  });
  document.getElementById("newSentence").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); document.getElementById("addSentence").click(); }
  });

  // ── canvas mouse ────────────────────────────────────────────────

  function canvasPoint(ev) {
    const r = canvas.getBoundingClientRect();
    // Canvas is responsively scaled by CSS — divide by the ratio to
    // get back to internal coordinates.
    const sx = canvas.width  / r.width;
    const sy = canvas.height / r.height;
    return { x: (ev.clientX - r.left) * sx,
             y: (ev.clientY - r.top ) * sy };
  }

  canvas.addEventListener("click", (ev) => {
    if (!state) return;
    const p = canvasPoint(ev);
    const cell = (state.mode === "square")
      ? pickCellSquare(p.x, p.y, state.dim)
      : pickCellHex   (p.x, p.y, state.dim);
    if (!cell) return;
    postJson(T.endpoints.blocks, {
      action: "place",
      shape: palette.shape, size: palette.size, name: palette.name,
      x: cell.x, y: cell.y,
    });
  });

  canvas.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    if (!state) return;
    const p = canvasPoint(ev);
    const cell = (state.mode === "square")
      ? pickCellSquare(p.x, p.y, state.dim)
      : pickCellHex   (p.x, p.y, state.dim);
    if (!cell) return;
    postJson(T.endpoints.blocks, {
      action: "remove", x: cell.x, y: cell.y,
    });
  });

  document.getElementById("clearWorld").addEventListener("click", () => {
    if (!confirm("Clear all blocks from this world?")) return;
    postJson(T.endpoints.blocks, { action: "clear" });
  });

  // ── boot ────────────────────────────────────────────────────────
  fetchState();
})();

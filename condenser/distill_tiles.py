"""Distill the Tiles app into a standalone JS page.

Takes the full Django Tiles app (models, views, templates, canvas
renderer, greedy tiler, hex support) and produces a single HTML file
that runs entirely in the browser with no server dependency.

What survives the distillation:
  - Wang tile creation (square + hex, N colors)
  - Greedy tiling on canvas
  - SVG tile preview
  - Save as PNG
  - localStorage persistence

What doesn't survive:
  - Django ORM / database
  - Identity integration (mood-based generation)
  - Attic artwork pipeline
  - Multi-user auth
  - Server-side rendering

The output is annotated with CONDENSER markers — comments that
describe what was lost and what could be recovered at the next
tier. These markers are prompts for Claude in future sessions.
"""


def distill():
    """Generate a standalone Tiles HTML page. Returns the HTML string."""

    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tiles — Condensed</title>
<!-- CONDENSER: This is Tier 2 (JS-only) distillation of Velour's Tiles app.
     Source: tiles/models.py, tiles/views.py, templates/tiles/*.html
     Lost: Django ORM, Identity mood integration, Attic artwork pipeline, auth
     Preserved: Wang tile creation (square+hex), greedy tiling, canvas render, PNG export
     Next tier (ESP8266): reduce to ~50KB, strip CSS, minimal UI, PROGMEM strings
     Gödel note: this page can generate tilings but cannot observe itself generating them.
     The self-referential loop that Identity provides is absent at this tier. -->
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;padding:1rem}
h1{font-size:1.2rem;margin-bottom:0.5rem;color:#58a6ff}
h2{font-size:0.95rem;margin:0.75rem 0 0.3rem;color:#c9d1d9}
.row{display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin:0.5rem 0}
label{font-size:0.75rem;color:#8b949e}
select,input[type=number],input[type=text],input[type=color]{
  background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;
  padding:0.3rem;font-size:0.8rem}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;
  padding:0.3rem 0.7rem;font-size:0.8rem;cursor:pointer}
button:hover{background:#30363d}
button.primary{background:#238636;border-color:#2ea043}
.tiles-grid{display:flex;gap:2px;flex-wrap:wrap;margin:0.5rem 0}
canvas{border:1px solid #30363d;margin:0.5rem 0;display:block}
.sets{display:flex;flex-direction:column;gap:0.3rem;margin:0.5rem 0}
.set-row{background:#161b22;border-left:2px solid #bc8cff;border-radius:0 3px 3px 0;
  padding:0.3rem 0.5rem;font-size:0.78rem;cursor:pointer;display:flex;justify-content:space-between}
.set-row:hover{background:#1c2028}
.set-row .name{color:#c9d1d9;font-weight:500}
.set-row .meta{color:#6e7681;font-size:0.68rem}
#status{color:#8b949e;font-size:0.72rem;font-family:monospace;margin:0.3rem 0}
</style>
</head>
<body>
<h1>Tiles — Condensed</h1>
<p style="color:#6e7681;font-size:0.78rem;margin-bottom:0.5rem">
<!-- CONDENSER: At Tier 3 (ESP), this description becomes a single line or is removed entirely.
     At Tier 4 (ATTiny), there is no text at all — only LED blink patterns encoding tile states. -->
Wang tiles in the browser. No server needed. Tilesets saved in localStorage.
</p>

<div class="row">
  <label>Type <select id="tile-type"><option value="square">Square</option><option value="hex">Hex</option></select></label>
  <label>Colors <input type="number" id="n-colors" value="2" min="2" max="4" style="width:3rem"></label>
  <label>C1 <input type="color" id="c1" value="#58a6ff"></label>
  <label>C2 <input type="color" id="c2" value="#f85149"></label>
  <label>C3 <input type="color" id="c3" value="#2ea043"></label>
  <label>C4 <input type="color" id="c4" value="#d29922"></label>
  <label>Name <input type="text" id="set-name" value="" placeholder="my tileset" style="width:8rem"></label>
  <button class="primary" onclick="createSet()">Create</button>
  <button onclick="generateComplete()">Generate Complete</button>
</div>

<h2>Saved tilesets</h2>
<div class="sets" id="sets-list"></div>

<h2>Current tileset</h2>
<div class="tiles-grid" id="tiles-preview"></div>

<h2>Tiling</h2>
<div class="row">
  <label>W <input type="number" id="grid-w" value="16" min="1" max="64" style="width:3.5rem"></label>
  <label>H <input type="number" id="grid-h" value="16" min="1" max="64" style="width:3.5rem"></label>
  <label>Px <input type="number" id="tile-px" value="16" min="4" max="40" style="width:3.5rem"></label>
  <button onclick="generateTiling()">Generate</button>
  <button onclick="savePNG()">Save PNG</button>
</div>
<canvas id="tiling-canvas"></canvas>
<div id="status"></div>

<script>
// CONDENSER: Core data structures — what survives distillation.
// A tileset is {name, type, colors[], tiles[]}
// A tile is {edges[]} where edges.length = 4 (square) or 6 (hex)
// This is the minimum viable representation of Wang tiles.

var DB_KEY = 'condenser_tiles';
var sets = JSON.parse(localStorage.getItem(DB_KEY) || '[]');
var currentIdx = -1;

function save() { localStorage.setItem(DB_KEY, JSON.stringify(sets)); }

function getColors() {
  var n = parseInt(document.getElementById('n-colors').value) || 2;
  var ids = ['c1','c2','c3','c4'];
  var c = [];
  for (var i = 0; i < Math.min(n, 4); i++) c.push(document.getElementById(ids[i]).value);
  return c;
}

function createSet() {
  var type = document.getElementById('tile-type').value;
  var colors = getColors();
  var name = document.getElementById('set-name').value.trim() || (type + ' ' + colors.length + 'c');
  sets.push({name: name, type: type, colors: colors, tiles: []});
  currentIdx = sets.length - 1;
  save(); renderAll();
}

function generateComplete() {
  if (currentIdx < 0) { createSet(); }
  var s = sets[currentIdx];
  s.tiles = [];
  var nc = s.colors.length;
  var ne = s.type === 'hex' ? 6 : 4;
  // CONDENSER: Complete set = nc^ne tiles. For 2-color hex = 64.
  // At Tier 4 (ATTiny), only 2-color 4-edge sets fit in 1KB.
  // At Tier 5 (555), a single tile is one timing state.
  var total = Math.pow(nc, ne);
  var limit = Math.min(total, 256); // cap for sanity
  for (var i = 0; i < limit; i++) {
    var edges = [], v = i;
    for (var e = 0; e < ne; e++) { edges.push(s.colors[v % nc]); v = Math.floor(v / nc); }
    s.tiles.push({edges: edges});
  }
  save(); renderAll();
}

function selectSet(i) { currentIdx = i; renderAll(); }

function deleteSet(i) {
  sets.splice(i, 1);
  if (currentIdx >= sets.length) currentIdx = sets.length - 1;
  save(); renderAll();
}

function renderSetsList() {
  var el = document.getElementById('sets-list');
  if (!sets.length) { el.innerHTML = '<span style="color:#6e7681;font-size:0.75rem">No tilesets yet.</span>'; return; }
  el.innerHTML = sets.map(function(s, i) {
    var sel = i === currentIdx ? 'border-left-color:#58a6ff' : '';
    return '<div class="set-row" style="' + sel + '" onclick="selectSet(' + i + ')">' +
      '<span class="name">' + s.name + '</span>' +
      '<span class="meta">' + s.type + ' · ' + s.tiles.length + ' tiles · ' + s.colors.length + 'c' +
      ' <button onclick="event.stopPropagation();deleteSet(' + i + ')" style="font-size:0.65rem;padding:0.1rem 0.3rem">×</button></span></div>';
  }).join('');
}

function renderTilePreview() {
  var el = document.getElementById('tiles-preview');
  if (currentIdx < 0 || !sets[currentIdx]) { el.innerHTML = ''; return; }
  var s = sets[currentIdx];
  var size = s.type === 'hex' ? 28 : 24;
  el.innerHTML = s.tiles.slice(0, 64).map(function(t) {
    if (s.type === 'hex') {
      return '<svg width="' + size + '" height="' + Math.round(size*0.87) + '" viewBox="0 0 100 87">' +
        '<polygon points="25,0 75,0 50,43.5" fill="' + t.edges[0] + '"/>' +
        '<polygon points="75,0 100,43.5 50,43.5" fill="' + t.edges[1] + '"/>' +
        '<polygon points="100,43.5 75,87 50,43.5" fill="' + t.edges[2] + '"/>' +
        '<polygon points="75,87 25,87 50,43.5" fill="' + t.edges[3] + '"/>' +
        '<polygon points="25,87 0,43.5 50,43.5" fill="' + t.edges[4] + '"/>' +
        '<polygon points="0,43.5 25,0 50,43.5" fill="' + t.edges[5] + '"/></svg>';
    }
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 56 56">' +
      '<polygon points="0,0 56,0 28,28" fill="' + t.edges[0] + '"/>' +
      '<polygon points="56,0 56,56 28,28" fill="' + t.edges[1] + '"/>' +
      '<polygon points="56,56 0,56 28,28" fill="' + t.edges[2] + '"/>' +
      '<polygon points="0,56 0,0 28,28" fill="' + t.edges[3] + '"/></svg>';
  }).join('');
}

// CONDENSER: Greedy tiling — the core algorithm that survives all tiers.
// At Tier 3 (ESP), this runs identically in JS served by the device.
// At Tier 4 (ATTiny), it becomes a C loop over a tiny grid stored in SRAM.
// At Tier 5 (555), the "matching" is voltage comparators on RC timing outputs.
function generateTiling() {
  if (currentIdx < 0 || !sets[currentIdx] || !sets[currentIdx].tiles.length) return;
  var s = sets[currentIdx];
  var gw = parseInt(document.getElementById('grid-w').value) || 16;
  var gh = parseInt(document.getElementById('grid-h').value) || 16;
  var px = parseInt(document.getElementById('tile-px').value) || 16;
  var canvas = document.getElementById('tiling-canvas');
  var ctx = canvas.getContext('2d');
  var isHex = s.type === 'hex';

  if (isHex) {
    var sz = px/2, hexW = sz*2, hexH = Math.sqrt(3)*sz;
    canvas.width = Math.ceil(gw*hexW*0.75+sz*0.5);
    canvas.height = Math.ceil(gh*hexH+hexH/2+1);
  } else {
    canvas.width = gw*px; canvas.height = gh*px;
  }
  ctx.fillStyle = '#0d1117'; ctx.fillRect(0,0,canvas.width,canvas.height);

  var grid = [], filled = 0, stuck = 0;
  var opp = isHex ? {0:3,1:4,2:5,3:0,4:1,5:2} : {0:2,1:3,2:0,3:1};

  function hexNb(r,c,d) {
    var even = c%2===0;
    var m = [[[-1,0],[0,1],[1,1],[1,0],[1,-1],[0,-1]],
             [[-1,0],[-1,1],[0,1],[1,0],[0,-1],[-1,-1]]];
    var o = m[even?1:0][d];  // Wait, need to fix offset logic
    // Simpler: use standard offset coords
    if (d===0) return [r-1,c];
    if (d===3) return [r+1,c];
    if (even) {
      if (d===1) return [r-1,c+1]; if (d===2) return [r,c+1];
      if (d===4) return [r,c-1]; if (d===5) return [r-1,c-1];
    } else {
      if (d===1) return [r,c+1]; if (d===2) return [r+1,c+1];
      if (d===4) return [r+1,c-1]; if (d===5) return [r,c-1];
    }
  }

  for (var r=0;r<gh;r++) { grid[r]=[];
    for (var c=0;c<gw;c++) {
      var cands = s.tiles.slice();
      if (isHex) {
        for (var d=0;d<6;d++) {
          var nb = hexNb(r,c,d);
          if (nb&&nb[0]>=0&&nb[0]<gh&&nb[1]>=0&&nb[1]<gw&&grid[nb[0]]&&grid[nb[0]][nb[1]]) {
            var need = grid[nb[0]][nb[1]].edges[opp[d]];
            cands = cands.filter(function(t){return t.edges[d]===need;});
          }
        }
      } else {
        if (c>0&&grid[r][c-1]) { var le=grid[r][c-1].edges[1]; cands=cands.filter(function(t){return t.edges[3]===le;}); }
        if (r>0&&grid[r-1][c]) { var ue=grid[r-1][c].edges[2]; cands=cands.filter(function(t){return t.edges[0]===ue;}); }
      }
      if (!cands.length) { grid[r][c]=null; stuck++; }
      else { grid[r][c]=cands[Math.floor(Math.random()*cands.length)]; filled++; }
    }
  }

  // Draw
  if (isHex) {
    var sz=px/2, hexH=Math.sqrt(3)*sz;
    for (var r=0;r<gh;r++) for (var c=0;c<gw;c++) {
      var t=grid[r][c]; if(!t) continue;
      var cx=c*sz*2*0.75+sz, cy=r*hexH+hexH/2+(c%2===1?hexH/2:0);
      var pts=[]; for(var i=0;i<6;i++){var a=Math.PI/3*i;pts.push([cx+sz*Math.cos(a),cy+sz*Math.sin(a)]);}
      var em=[[1,2],[0,1],[5,0],[4,5],[3,4],[2,3]];
      for(var e=0;e<6;e++){ctx.fillStyle=t.edges[e];ctx.beginPath();ctx.moveTo(pts[em[e][0]][0],pts[em[e][0]][1]);ctx.lineTo(pts[em[e][1]][0],pts[em[e][1]][1]);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();}
    }
  } else {
    var half=px/2;
    for(var r=0;r<gh;r++) for(var c=0;c<gw;c++) {
      var t=grid[r][c]; if(!t) continue;
      var x=c*px,y=r*px,cx=x+half,cy=y+half;
      ctx.fillStyle=t.edges[0];ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+px,y);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      ctx.fillStyle=t.edges[1];ctx.beginPath();ctx.moveTo(x+px,y);ctx.lineTo(x+px,y+px);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      ctx.fillStyle=t.edges[2];ctx.beginPath();ctx.moveTo(x+px,y+px);ctx.lineTo(x,y+px);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      ctx.fillStyle=t.edges[3];ctx.beginPath();ctx.moveTo(x,y+px);ctx.lineTo(x,y);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
    }
  }
  document.getElementById('status').textContent = gw+'×'+gh+' = '+(gw*gh)+' cells. '+filled+' filled, '+stuck+' stuck.';
}

function savePNG() {
  var c=document.getElementById('tiling-canvas');
  var a=document.createElement('a'); a.download='tiling.png'; a.href=c.toDataURL('image/png'); a.click();
}

function renderAll() { renderSetsList(); renderTilePreview(); }
renderAll();

// CONDENSER: End of Tier 2 distillation.
// Total: ~8KB minified. Fits on ESP8266 PROGMEM easily.
// Next distillation pass (Tier 3) would:
//   1. Remove localStorage (ESP has no persistent browser storage)
//   2. Embed one default tileset in PROGMEM
//   3. Strip CSS to bare minimum
//   4. Auto-generate tiling on page load
//   5. Target: <4KB total for ESP8266 web server
// Tier 4 (ATTiny) distillation:
//   1. No display — represent tile state as GPIO pin patterns
//   2. Greedy tiling becomes a loop that sets 8 pins based on edge matching
//   3. Target: <512 bytes of logic
// Tier 5 (555 timer):
//   1. Two colors = two voltage levels (high/low)
//   2. "Edge matching" = voltage comparator (LM393)
//   3. "Tile selection" = RC time constant selection via analog mux
//   4. One 555 per tile position, cascaded outputs
</script>
</body>
</html>'''

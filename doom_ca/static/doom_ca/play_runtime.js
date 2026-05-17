// doom_ca/play_runtime.js — the inline-JS runtime extracted from
// play.html so both the in-app live game and the standalone export
// can share one source of truth.  Expects:
//   window.__doomPayload — game payload object (rules_hex, seed_hex,
//     palette, component, monster_count, etc.).  Required.
//   payload.tap_prefetched_hex — optional hex string with the
//     deterministic monster-placement bytes.  When set, tapAsync()
//     returns these directly instead of fetching from the server,
//     which lets the standalone export run from a file:// URL.
(function () {
  'use strict';
  var payload = window.__doomPayload || {};
  var GRID = payload.component_grid;
  var COMPONENT = payload.component;
  var WALL_THRESH = payload.wall_threshold;
  var MONSTER_COUNT = payload.monster_count;
  var MODE = payload.world_mode;
  var PURE_MODE = !!payload.pure_mode;
  var RULE_SIZE = 16384;
  var COMPONENTS = payload.components;
  var HEALTH_PACK_COUNT = (payload.health_pack_count != null)
        ? payload.health_pack_count : 3;
  var AMMO_PACK_COUNT   = (payload.ammo_pack_count   != null)
        ? payload.ammo_pack_count   : 3;
  var DOOR_COUNT        = (payload.door_count        != null)
        ? payload.door_count        : 1;
  var SHOTGUN_COUNT     = (payload.shotgun_count     != null)
        ? payload.shotgun_count     : 1;

  var MODE_NOTES = {
    overlay: 'overlay mode — the pact rule runs the CA freely; player + ' +
             'monsters are tracked as JS state on top.  Camera follows ' +
             'the player; walls (cells ≥ wall threshold) scroll past.',
    shift:   'shift mode — pure-CA.  Player is encoded as cell-state 2 and ' +
             'anchored at the centre by 6 hand-built directional rules.  ' +
             'Pressing a direction shifts the entire world the opposite ' +
             'way; the world stays still on Space (wait runs the pact rule).',
    scent:   'scent mode — pure-CA.  A single hand-built rule grows ' +
             'monsters fluid-like toward the player.  Player is anchored; ' +
             'walls block.  No JS pursuit logic — the rule is the AI.',
    evolved: 'evolved mode — the pact rule with per-key patches: player ' +
             'preserved, walls cluster, monsters attack on adjacency.  An ' +
             'illustration of what a GA-evolved Doom-signature rule would look like.',
    platform:'platform mode — same CA grid reinterpreted as a Cartesian ' +
             'side-scroller.  Wall cells are platforms; gravity pulls the ' +
             'player down; A/D = move, Space = jump, F = fire.  Monsters ' +
             'walk along platform tops, reversing at gaps.',
    ink:     'ink mode — you ARE a state-2 cell inside the K=4 CA.  ' +
             'Moving drips state-2 into the target cell and leaves the ' +
             'old one as a silent state-2 trail the rule then evolves.  ' +
             'State-2/3 cells render as floor unless they\'re the controlled ' +
             'player (you) or a revealed brush-bot — touching a state-3 ' +
             'cell reveals it; it then chases you, dripping state-3 ink.',
  };
  var noteEl = document.getElementById('dc-mode-note');
  if (noteEl) {
    noteEl.textContent =
      (MODE_NOTES[MODE] || '') +
      (PURE_MODE ? '  · pure mode (no pact-rule wait ticks).' : '');
  }
  // Show the right controls hint for the active mode.
  var keysHex = document.getElementById('dc-keys-hex');
  var keysPlat = document.getElementById('dc-keys-platform');
  var keysInkExtra = document.getElementById('dc-keys-ink-extra');
  if (MODE === 'platform') {
    if (keysHex)  keysHex.style.display  = 'none';
    if (keysPlat) keysPlat.style.display = '';
  } else {
    if (keysHex)  keysHex.style.display  = '';
    if (keysPlat) keysPlat.style.display = 'none';
  }
  if (keysInkExtra) keysInkExtra.style.display = (MODE === 'ink') ? '' : 'none';

  function hex2bytes (h) {
    var out = new Uint8Array(h.length / 2);
    for (var i = 0; i < out.length; i++) {
      out[i] = parseInt(h.substr(i * 2, 2), 16);
    }
    return out;
  }
  var rulesFlat = hex2bytes(payload.rules_hex);
  var seed      = hex2bytes(payload.seed_hex);

  var SPLITMIX_INC  = 0x9E3779B97F4A7C15n;
  var SPLITMIX_MUL1 = 0xBF58476D1CE4E5B9n;
  var SPLITMIX_MUL2 = 0x94D049BB133111EBn;
  var M64 = 0xFFFFFFFFFFFFFFFFn;
  function splitmix64BigInt (s) {
    s = (s + SPLITMIX_INC) & M64;
    var z = s;
    z = ((z ^ (z >> 30n)) * SPLITMIX_MUL1) & M64;
    z = ((z ^ (z >> 27n)) * SPLITMIX_MUL2) & M64;
    z = (z ^ (z >> 31n)) & M64;
    return { state: s, out: z };
  }
  function makeXoshiro (byteSeed) {
    var sm = BigInt(byteSeed & 0xFF);
    var words = [];
    for (var i = 0; i < 4; i++) {
      var r = splitmix64BigInt(sm);
      sm = r.state;
      words.push(Number(r.out & 0xFFFFFFFFn) >>> 0);
    }
    if ((words[0]|words[1]|words[2]|words[3]) === 0) {
      words[0] = 0x9E3779B9; words[1] = 0x7F4A7C15;
    }
    function rotl32 (x, k) { return ((x << k) | (x >>> (32 - k))) >>> 0; }
    function mul32 (a, b) {
      var a0 = a & 0xFFFF, a1 = a >>> 16;
      var b0 = b & 0xFFFF, b1 = b >>> 16;
      return ((a0 * b0) + (((a1 * b0 + a0 * b1) & 0xFFFF) << 16)) >>> 0;
    }
    var w0 = words[0], w1 = words[1], w2 = words[2], w3 = words[3];
    return function next () {
      var result = mul32(rotl32(mul32(w1, 5), 7), 9);
      var t = (w1 << 9) >>> 0;
      w2 = (w2 ^ w0) >>> 0;
      w3 = (w3 ^ w1) >>> 0;
      w1 = (w1 ^ w2) >>> 0;
      w0 = (w0 ^ w3) >>> 0;
      w2 = (w2 ^ t)  >>> 0;
      w3 = rotl32(w3, 11);
      return result;
    };
  }
  function seedGrid (byteSeed) {
    var nxt = makeXoshiro(byteSeed);
    var g = new Uint8Array(GRID * GRID);
    for (var i = 0; i < g.length; i += 4) {
      var r = nxt();
      g[i] = r & 3;
      if (i+1 < g.length) g[i+1] = (r >> 2) & 3;
      if (i+2 < g.length) g[i+2] = (r >> 4) & 3;
      if (i+3 < g.length) g[i+3] = (r >> 6) & 3;
    }
    return g;
  }

  var GROUND = 0, WALL = 1, PLAYER = 2, MONSTER = 3;

  function unpackKey (k) {
    return {
      self_: (k >> 12) & 3,
      n: [(k>>10)&3, (k>>8)&3, (k>>6)&3, (k>>4)&3, (k>>2)&3, k&3]
    };
  }

  function buildShiftRule (d) {
    var tbl = new Uint8Array(RULE_SIZE);
    for (var k = 0; k < RULE_SIZE; k++) {
      var u = unpackKey(k);
      if (u.self_ === PLAYER) { tbl[k] = PLAYER; continue; }
      if (u.self_ === WALL) {
        var blocked = false;
        for (var i = 0; i < 6; i++) if (u.n[i] === PLAYER) { blocked = true; break; }
        if (blocked) { tbl[k] = WALL; continue; }
      }
      if (u.n[d] === PLAYER) { tbl[k] = GROUND; continue; }
      tbl[k] = u.n[d];
    }
    return tbl;
  }

  function buildScentRule () {
    var tbl = new Uint8Array(RULE_SIZE);
    for (var k = 0; k < RULE_SIZE; k++) {
      var u = unpackKey(k);
      if (u.self_ === PLAYER) { tbl[k] = PLAYER; continue; }
      if (u.self_ === WALL)   { tbl[k] = WALL;   continue; }
      var hasMonster = 0, hasPlayer = 0, hasGround = 0, hasWall = 0;
      for (var i = 0; i < 6; i++) {
        if (u.n[i] === MONSTER) hasMonster++;
        else if (u.n[i] === PLAYER) hasPlayer++;
        else if (u.n[i] === GROUND) hasGround++;
        else if (u.n[i] === WALL)   hasWall++;
      }
      if (u.self_ === MONSTER) {
        if (hasPlayer) { tbl[k] = MONSTER; continue; }
        if (hasGround === 0 && hasMonster <= 1) { tbl[k] = MONSTER; continue; }
        tbl[k] = GROUND;
        continue;
      }
      if (hasMonster >= 1 && (hasPlayer || hasGround >= 2)) {
        tbl[k] = MONSTER;
        continue;
      }
      tbl[k] = GROUND;
    }
    return tbl;
  }

  function buildEvolvedRule () {
    var base = rulesFlat.slice(COMPONENT * RULE_SIZE,
                                (COMPONENT + 1) * RULE_SIZE);
    var tbl = new Uint8Array(base);
    for (var k = 0; k < RULE_SIZE; k++) {
      var u = unpackKey(k);
      if (u.self_ === PLAYER) { tbl[k] = PLAYER; continue; }
      if (u.self_ === MONSTER) {
        var nbPlayer = false;
        for (var i = 0; i < 6; i++) if (u.n[i] === PLAYER) nbPlayer = true;
        if (nbPlayer) { tbl[k] = MONSTER; continue; }
      }
      if (u.self_ === WALL) {
        var nbWalls = 0;
        for (var j = 0; j < 6; j++) if (u.n[j] === WALL) nbWalls++;
        if (nbWalls >= 2) tbl[k] = WALL;
        else if (nbWalls === 0) tbl[k] = GROUND;
      }
      if (u.self_ === GROUND) {
        var nbPlayer2 = false;
        for (var i = 0; i < 6; i++) if (u.n[i] === PLAYER) nbPlayer2 = true;
        if (nbPlayer2) tbl[k] = WALL;
      }
    }
    return tbl;
  }

  function neighbourCoord (x, y, d) {
    var shift = y & 1;
    var dx = [shift, 1, shift, -1 + shift, -1, -1 + shift][d];
    var dy = [-1, 0, 1, 1, 0, -1][d];
    return [(x + dx + GRID) % GRID, (y + dy + GRID) % GRID];
  }
  function hexDist (ax, ay, bx, by) {
    var dx = bx - ax;
    if (dx >  GRID / 2) dx -= GRID;
    if (dx < -GRID / 2) dx += GRID;
    var dy = by - ay;
    if (dy >  GRID / 2) dy -= GRID;
    if (dy < -GRID / 2) dy += GRID;
    return Math.max(Math.abs(dx), Math.abs(dy), Math.abs(dx + dy));
  }

  var world, swap, generation, turn, player, monsters, gameOver, deathCause;
  var items, doorIdx, keyIdx, exitIdx, doorOpen;
  var canvas = document.getElementById('dc-canvas');
  var ctx = canvas.getContext('2d');
  var VIEW = 21;
  var CELL_PX, H_STEP, V_STEP;

  function recomputeRenderMetrics () {
    var page = canvas.parentElement || document.body;
    var pageW = page.clientWidth || window.innerWidth;
    var availW = pageW - 4;
    var availH = window.innerHeight - 280;
    if (MODE === 'platform') {
      // Cartesian side-scroller — keep a square-ish canvas sized to
      // the smaller available dimension, like the original.  The hex
      // half-shift / 0.85 vertical step don't apply here.
      var edge = Math.max(240, Math.min(availW, availH));
      edge = Math.floor(edge);
      canvas.width  = edge;
      canvas.height = edge;
      canvas.style.width  = edge + 'px';
      canvas.style.height = edge + 'px';
      CELL_PX = Math.floor(edge / VIEW);
      H_STEP  = CELL_PX;
      V_STEP  = CELL_PX;
      return;
    }
    // Hex-grid natural extent in cells.  Horizontally the odd-row
    // half-shift adds 0.5 to the rightmost column; vertically the
    // step is 0.85 × cell, so VIEW rows span (VIEW-1)*0.85 + 1.
    // Sizing the canvas square (the old behaviour) left a 14% black
    // bar at the bottom because the drawn area was shorter than tall.
    var EXTENT_W = VIEW + 0.5;
    var EXTENT_H = (VIEW - 1) * 0.85 + 1;
    var cell = Math.min(availW / EXTENT_W, availH / EXTENT_H);
    cell = Math.max(12, Math.floor(cell));
    CELL_PX = cell;
    H_STEP  = CELL_PX;
    V_STEP  = CELL_PX * 0.85;
    var w = Math.ceil(EXTENT_W * cell);
    var h = Math.ceil(EXTENT_H * cell);
    canvas.width  = w;
    canvas.height = h;
    canvas.style.width  = w + 'px';
    canvas.style.height = h + 'px';
  }
  recomputeRenderMetrics();
  window.addEventListener('resize', function () {
    recomputeRenderMetrics();
    if (player) draw();
  });

  var SLIP_ON_1     = !!payload.slip_ground_1;
  var DESTRUCT_W2   = !!payload.destruct_wall_2;
  var palette = payload.palette;
  function isPerComponent (p) { return Array.isArray(p[0][0]); }
  var componentPalette = isPerComponent(palette) ? palette[COMPONENT] : palette;
  var COL_S0, COL_S1, COL_WALL, COL_WALL_DK;
  function applyPalette (pal) {
    componentPalette = pal;
    COL_S0      = 'rgb(' + componentPalette[0].join(',') + ')';
    COL_S1      = 'rgb(' + componentPalette[1].join(',') + ')';
    COL_WALL_DK = 'rgb(' + componentPalette[2].join(',') + ')';
    COL_WALL    = 'rgb(' + componentPalette[3].join(',') + ')';
    // Update legend swatches so they always match the active palette,
    // including after a live re-roll via the 🎨 randomise button.
    var lg0 = document.getElementById('leg-c0');
    if (lg0) lg0.style.background = COL_S0;
    var lg1 = document.getElementById('leg-c1');
    if (lg1) lg1.style.background = COL_S1;
    var lg2 = document.getElementById('leg-c2');
    if (lg2) lg2.style.background = COL_WALL_DK;
    var lg3 = document.getElementById('leg-c3');
    if (lg3) lg3.style.background = COL_WALL;
    // Update legend text so the mechanic-meaningful state is called out.
    var t0 = document.getElementById('leg-c0-text');
    var t1 = document.getElementById('leg-c1-text');
    var t2 = document.getElementById('leg-c2-text');
    var t3 = document.getElementById('leg-c3-text');
    if (MODE === 'ink') {
      if (t0) t0.textContent = 'ground (state 0)';
      if (t1) t1.textContent = 'wall (state 1)';
      if (t2) t2.textContent = 'player ink (state 2 · only you visible)';
      if (t3) t3.textContent = 'brush-bot (state 3 · only revealed visible)';
    } else {
      if (t0) t0.textContent = 'ground (state 0)';
      if (t1) t1.textContent = SLIP_ON_1 ? 'slip-ground (state 1)' : 'ground (state 1)';
      if (t2) t2.textContent = DESTRUCT_W2 ? 'fragile wall (state 2)' : 'wall (state 2)';
      if (t3) t3.textContent = 'wall (state 3)';
    }
  }
  applyPalette(componentPalette);
  var COL_GROUND  = '#1a1a1a';
  var COL_PLAYER  = '#58a6ff';
  var COL_MONSTER = '#f85149';
  var COL_PLAYER_HALO = 'rgba(88,166,255,0.18)';

  // HSV-spaced random palette generator + shuffle.  Same algorithm as
  // evolve.html / spoeqi so colour styles feel consistent across the app.
  function _hsvToRgb (h, s, v) {
    var i = Math.floor(h * 6);
    var f = h * 6 - i;
    var p = v * (1 - s);
    var q = v * (1 - f * s);
    var t = v * (1 - (1 - f) * s);
    switch (i % 6) {
      case 0: return [v, t, p];
      case 1: return [q, v, p];
      case 2: return [p, v, t];
      case 3: return [p, q, v];
      case 4: return [t, p, v];
      case 5: return [v, p, q];
    }
  }
  function randomisePaletteNow () {
    var rot = Math.random();
    var out = [];
    for (var i = 0; i < 4; i++) {
      var h = (rot + i / 4 + (Math.random() * 0.06 - 0.03)) % 1.0;
      if (h < 0) h += 1.0;
      var s = 0.55 + Math.random() * 0.4;
      var v = 0.55 + Math.random() * 0.4;
      var rgb = _hsvToRgb(h, s, v);
      out.push([Math.floor(rgb[0] * 255),
                Math.floor(rgb[1] * 255),
                Math.floor(rgb[2] * 255)]);
    }
    for (var k = out.length - 1; k > 0; k--) {
      var j = Math.floor(Math.random() * (k + 1));
      var tmp = out[k]; out[k] = out[j]; out[j] = tmp;
    }
    applyPalette(out);
    if (typeof draw === 'function' && player) draw();
  }
  window.__doomRandomisePalette = randomisePaletteNow;

  function get (x, y) {
    return world[((y + GRID) % GRID) * GRID + ((x + GRID) % GRID)];
  }
  function set (x, y, v) {
    world[((y + GRID) % GRID) * GRID + ((x + GRID) % GRID)] = v;
  }

  function tickRule (ruleTable) {
    var W = GRID, H = GRID;
    for (var y = 0; y < H; y++) {
      var shift = y & 1;
      var tlx_off = -1 + shift;
      var brx_off =  0 + shift;
      var yU = (y - 1 + H) % H;
      var yD = (y + 1) % H;
      for (var x = 0; x < W; x++) {
        var idx = y * W + x;
        var self_ = world[idx];
        var xL = (x - 1 + W) % W;
        var xR = (x + 1) % W;
        var xTL = (x + tlx_off + W) % W;
        var xBR = (x + brx_off + W) % W;
        var n0 = world[yU * W + xBR];
        var n1 = world[y  * W + xR];
        var n2 = world[yD * W + xBR];
        var n3 = world[yD * W + xTL];
        var n4 = world[y  * W + xL];
        var n5 = world[yU * W + xTL];
        var key = (self_ << 12) | (n0 << 10) | (n1 << 8) | (n2 << 6)
                | (n3 << 4) | (n4 << 2) | n5;
        swap[idx] = ruleTable[key];
      }
    }
    var tmp = world; world = swap; swap = tmp;
    generation++;
  }
  function tickPactRule () {
    var base = COMPONENT * RULE_SIZE;
    var subRule = rulesFlat.subarray(base, base + RULE_SIZE);
    tickRule(subRule);
  }

  var shiftRules = null;
  var scentRule = null;
  var evolvedRule = null;

  function isWallForOverlay (state) { return state >= WALL_THRESH; }

  function findGroundNear (cx, cy, walls) {
    for (var r = 0; r < GRID; r++) {
      for (var dy = -r; dy <= r; dy++) {
        for (var dx = -r; dx <= r; dx++) {
          if (Math.abs(dy) !== r && Math.abs(dx) !== r) continue;
          var x = (cx + dx + GRID) % GRID;
          var y = (cy + dy + GRID) % GRID;
          if (!walls(get(x, y))) return {x: x, y: y};
        }
      }
    }
    return {x: cx, y: cy};
  }

  // Tap source: server URL when running in-app, or prefetched hex
  // when running standalone (export).  The standalone export bundles
  // ~MONSTER_COUNT*4+32 bytes of keystream so monster placement is
  // identical to the in-app version with no network needed.
  var tieBreakBytes = null;
  function tapAsync (component, gen, nBytes) {
    if (payload.tap_prefetched_hex) {
      var b = hex2bytes(payload.tap_prefetched_hex);
      // Slice / pad if the caller asked for more than we have.
      if (b.length >= nBytes) b = b.subarray(0, nBytes);
      return Promise.resolve(b);
    }
    var url = payload.tap_url_template
      .replace('{component}', component)
      .replace('{gen}', gen)
      .replace('{n}', nBytes);
    return fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok) throw new Error(d.error || 'tap failed');
      return hex2bytes(d.bytes_hex);
    });
  }

  function placeLevelOnce (worldGrid, spawnX, spawnY) {
    var E = window.DoomCAEngine;
    var gw = new Uint8Array(GRID * GRID);
    if (MODE === 'overlay') {
      for (var i = 0; i < worldGrid.length; i++) {
        gw[i] = (worldGrid[i] >= WALL_THRESH) ? E.WALL : E.GROUND;
      }
    } else {
      for (var i = 0; i < worldGrid.length; i++) {
        gw[i] = (worldGrid[i] === E.WALL) ? E.WALL : E.GROUND;
      }
    }
    var rng = E.makeRng((seed[COMPONENT] * 2654435761) >>> 0);
    var fakeGene = {
      health_pack_count: HEALTH_PACK_COUNT,
      ammo_pack_count:   AMMO_PACK_COUNT,
      door_count:        DOOR_COUNT,
      shotgun_count:     SHOTGUN_COUNT,
    };
    var level = E.placeLevel(fakeGene, GRID, gw, spawnX, spawnY, rng);
    if (!level) {
      return { items: {}, exitIdx: -1, doorIdx: null, keyIdx: null };
    }
    return level;
  }

  function init () {
    swap  = new Uint8Array(GRID * GRID);
    generation = 0;
    turn = 0;
    gameOver = false;
    deathCause = null;
    deathRuleInfo = null;
    var rbox = document.getElementById('dc-rule-explainer');
    if (rbox) rbox.style.display = 'none';

    if (MODE === 'platform') {
      initPlatformMode();
      return;
    }

    if (MODE === 'ink') {
      initInkMode();
      return;
    }

    if (MODE === 'overlay') {
      world = seedGrid(seed[COMPONENT]).slice();
      var c = Math.floor(GRID / 2);
      player = findGroundNear(c, c, isWallForOverlay);
      player.hp = 100; player.ammo = 0;
      player.hasShotgun = false; player.hasKey = false;
      player.lastDir = 1;
      var level = placeLevelOnce(world, player.x, player.y);
      items = level.items; doorIdx = level.doorIdx;
      keyIdx = level.keyIdx; exitIdx = level.exitIdx; doorOpen = false;
      monsters = [];
      tapAsync(COMPONENT, 0, MONSTER_COUNT * 4 + 32).then(function (bytes) {
        var bi = 0, attempts = 0;
        while (monsters.length < MONSTER_COUNT && attempts < MONSTER_COUNT * 20) {
          attempts++;
          var mx = bytes[bi % bytes.length] % GRID; bi++;
          var my = bytes[bi % bytes.length] % GRID; bi++;
          if (isWallForOverlay(get(mx, my))) continue;
          var midx = my * GRID + mx;
          if (midx === exitIdx || midx === doorIdx
              || midx === keyIdx || items[midx]) continue;
          var dx2 = (mx - player.x + GRID + GRID/2) % GRID - GRID/2;
          var dy2 = (my - player.y + GRID + GRID/2) % GRID - GRID/2;
          if (Math.abs(dx2) + Math.abs(dy2) < 3) continue;
          var dup = false;
          for (var i = 0; i < monsters.length; i++) {
            if (monsters[i].x === mx && monsters[i].y === my) { dup = true; break; }
          }
          if (dup) continue;
          monsters.push({x: mx, y: my, alive: true});
        }
        tieBreakBytes = bytes;
        draw(); updateReadouts();
      });
    } else {
      var raw = seedGrid(seed[COMPONENT]);
      var grid = new Uint8Array(GRID * GRID);
      for (var i = 0; i < raw.length; i++) {
        grid[i] = (raw[i] >= WALL_THRESH) ? WALL : GROUND;
      }
      world = grid;
      var c = Math.floor(GRID / 2);
      world[c * GRID + c] = GROUND;
      player = {x: c, y: c, hp: 100, ammo: 0,
                hasShotgun: false, hasKey: false, lastDir: 1};
      var level = placeLevelOnce(world, c, c);
      items = level.items; doorIdx = level.doorIdx;
      keyIdx = level.keyIdx; exitIdx = level.exitIdx; doorOpen = false;
      world[c * GRID + c] = PLAYER;
      monsters = [];
      tapAsync(COMPONENT, 0, MONSTER_COUNT * 4 + 32).then(function (bytes) {
        var bi = 0, placed = 0, attempts = 0;
        while (placed < MONSTER_COUNT && attempts < MONSTER_COUNT * 30) {
          attempts++;
          var mx = bytes[bi % bytes.length] % GRID; bi++;
          var my = bytes[bi % bytes.length] % GRID; bi++;
          var midx = my * GRID + mx;
          if (get(mx, my) !== GROUND) continue;
          if (hexDist(mx, my, player.x, player.y) < 3) continue;
          if (midx === exitIdx || midx === doorIdx
              || midx === keyIdx || items[midx]) continue;
          set(mx, my, MONSTER);
          placed++;
        }
        monsters = countMonsterCells();
        tieBreakBytes = bytes;
        if (MODE === 'shift') {
          shiftRules = [];
          for (var d = 0; d < 6; d++) shiftRules.push(buildShiftRule(d));
        }
        if (MODE === 'scent')   scentRule   = buildScentRule();
        if (MODE === 'evolved') evolvedRule = buildEvolvedRule();
        draw(); updateReadouts();
      });
    }
  }

  function countMonsterCells () {
    var out = [];
    for (var y = 0; y < GRID; y++) {
      for (var x = 0; x < GRID; x++) {
        if (world[y * GRID + x] === MONSTER) out.push({x: x, y: y});
      }
    }
    return out;
  }

  var fireFlash = null;

  function autoFireAt (mx, my) {
    if (!player.hasShotgun || player.ammo <= 0) return false;
    player.ammo--;
    fireFlash = { fromX: player.x, fromY: player.y,
                  toX: mx, toY: my, framesLeft: 2 };
    return true;
  }

  // Whenever something deals HP damage, set lastHurtBy so that if the
  // player ends up dying that turn we know what to put in the
  // "you died — …" message.  String values get used verbatim.
  var lastHurtBy = null;
  function hurt (amount, cause) {
    player.hp -= amount;
    lastHurtBy = cause;
  }

  // Pure-CA death inspector — captures the rule-table entry that
  // killed the player so the UI can render it next to the board.
  // Captured at the moment of death (after a checkGameOver_singleRule
  // verdict, or after a melee bite that would zero HP), so the
  // neighbourhood values are the ones the rule consulted.
  var deathRuleInfo = null;
  var STATE_NAMES = ['ground', 'wall', 'player', 'monster'];
  var STATE_COLORS = ['#1a1a1a', '#888', '#58a6ff', '#f85149'];
  function captureDeathRule (selfState, neighbours, outputState) {
    var key = ((selfState & 3) << 12) |
              ((neighbours[0] & 3) << 10) |
              ((neighbours[1] & 3) << 8)  |
              ((neighbours[2] & 3) << 6)  |
              ((neighbours[3] & 3) << 4)  |
              ((neighbours[4] & 3) << 2)  |
              ( neighbours[5] & 3);
    deathRuleInfo = {
      self: selfState, neighbours: neighbours.slice(),
      key: key, output: outputState,
    };
  }
  function captureFromPlayerCell (outputState) {
    // Re-read the 6 neighbours around (player.x, player.y) on the
    // current `world` grid.  Caller passes outputState — either the
    // cell value the rule produced (overwriting PLAYER) or 'bitten'
    // (when adjacent monsters killed via HP drain).
    if (!player) return;
    var n = [];
    for (var d = 0; d < 6; d++) {
      var nb = neighbourCoord(player.x, player.y, d);
      n.push(get(nb[0], nb[1]) & 3);
    }
    captureDeathRule(PLAYER, n, outputState);
  }

  function hexAroundPoint (cx, cy, r, k) {
    // 6 hex-cell positions around (cx, cy) at radius r, indexed
    // matching neighbourCoord's direction order (TR-ish, R, BR-ish,
    // BL-ish, L, TL-ish).  Used only for SVG layout, not gameplay.
    var deg = [-60, 0, 60, 120, 180, 240][k];
    var rad = deg * Math.PI / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  }

  function renderDeathRule () {
    var box = document.getElementById('dc-rule-explainer');
    if (!box) return;
    if (!deathRuleInfo) { box.style.display = 'none'; return; }
    // Only show in pure-CA modes where the rule is the actual killer.
    if (MODE !== 'scent' && MODE !== 'evolved') {
      box.style.display = 'none'; return;
    }
    box.style.display = 'block';
    var svg = document.getElementById('dc-rule-svg');
    if (svg) {
      var W = 170, R = 38, cx = W/2, cy = W/2;
      var parts = [];
      // 6 neighbours
      for (var k = 0; k < 6; k++) {
        var p = hexAroundPoint(cx, cy, R, k);
        var s = deathRuleInfo.neighbours[k];
        var col = STATE_COLORS[s];
        parts.push('<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1)
          + '" r="14" fill="' + col + '" stroke="#444"/>');
        parts.push('<text x="' + p[0].toFixed(1) + '" y="' + (p[1] + 4).toFixed(1)
          + '" text-anchor="middle" font-size="9" font-family="monospace" fill="#000">'
          + STATE_NAMES[s].slice(0, 4) + '</text>');
      }
      // Centre (self = PLAYER before rule fired)
      var selfCol = STATE_COLORS[deathRuleInfo.self];
      parts.push('<circle cx="' + cx + '" cy="' + cy + '" r="16" fill="'
        + selfCol + '" stroke="#fff"/>');
      parts.push('<text x="' + cx + '" y="' + (cy + 4) + '" text-anchor="middle"'
        + ' font-size="10" font-family="monospace" fill="#000">you</text>');
      // Outgoing arrow pointing right to the output cell
      var outX = W - 18;
      parts.push('<line x1="' + (cx + 18) + '" y1="' + cy + '" x2="' + (outX - 12)
        + '" y2="' + cy + '" stroke="#f88" stroke-width="2"/>');
      parts.push('<polygon points="' + (outX - 12) + ',' + (cy - 4) + ' '
        + (outX - 4) + ',' + cy + ' ' + (outX - 12) + ',' + (cy + 4)
        + '" fill="#f88"/>');
      svg.innerHTML = parts.join('');
    }
    var t = document.getElementById('dc-rule-text');
    if (t) {
      var ns = deathRuleInfo.neighbours.map(function (s) {
        return STATE_NAMES[s][0];
      }).join('');
      var outName = (typeof deathRuleInfo.output === 'number')
        ? STATE_NAMES[deathRuleInfo.output]
        : String(deathRuleInfo.output);
      t.innerHTML =
        'self <b style="color:' + STATE_COLORS[deathRuleInfo.self] + ';">'
          + STATE_NAMES[deathRuleInfo.self] + '</b><br>'
        + 'neighbours <b style="color:#ccc;">' + ns + '</b>'
        + ' <span style="color:#666;">(TR R BR BL L TL)</span><br>'
        + 'key <b style="color:#fc8;">0x' + deathRuleInfo.key.toString(16).padStart(4,'0') + '</b>'
        + ' <span style="color:#666;">(=' + deathRuleInfo.key + ')</span><br>'
        + '→ output <b style="color:' + (STATE_COLORS[deathRuleInfo.output] || '#f88')
        + ';">' + outName + '</b>';
    }
  }

  function pickupAt (cellIdx) {
    var it = items[cellIdx];
    if (!it) return;
    if (it.type === 'medkit')       player.hp   = Math.min(100, player.hp + 25);
    else if (it.type === 'ammo')    player.ammo += 3;
    else if (it.type === 'shotgun') player.hasShotgun = true;
    delete items[cellIdx];
  }

  function tryEnterDoor (targetIdx) {
    if (targetIdx !== doorIdx || doorOpen) return false;
    if (player.hasKey) {
      doorOpen = true; player.hasKey = false;
      return false;
    }
    return true;
  }

  function playerMove (dirIdx) {
    if (gameOver) return;
    if (MODE === 'ink') { playerMoveInk(dirIdx); return; }
    player.lastDir = dirIdx;
    if (MODE === 'overlay') {
      var nb = neighbourCoord(player.x, player.y, dirIdx);
      var nx = nb[0], ny = nb[1];
      if (isWallForOverlay(get(nx, ny))) return;
      var targetIdx = ny * GRID + nx;
      if (tryEnterDoor(targetIdx)) return;
      var hit = monsters.find(function (m) {
        return m.alive && m.x === nx && m.y === ny; });
      if (hit) {
        if (!autoFireAt(nx, ny)) hurt(30, 'collided with a monster while empty-handed');
        hit.alive = false;
      }
      player.x = nx; player.y = ny;
      if (targetIdx === keyIdx) { player.hasKey = true; keyIdx = -1; }
      pickupAt(targetIdx);
      if (targetIdx === exitIdx) { gameOver = 'won'; }
      // Slip-ground: stepping onto a state-1 cell slides you one more
      // step in the same direction if the destination is open.
      if (SLIP_ON_1 && get(player.x, player.y) === 1 && !gameOver) {
        var sn = neighbourCoord(player.x, player.y, dirIdx);
        if (!isWallForOverlay(get(sn[0], sn[1]))) {
          var sIdx = sn[1] * GRID + sn[0];
          if (sIdx !== doorIdx || doorOpen) {
            var sHit = monsters.find(function (m) {
              return m.alive && m.x === sn[0] && m.y === sn[1]; });
            if (!sHit) {
              player.x = sn[0]; player.y = sn[1];
              if (sIdx === keyIdx) { player.hasKey = true; keyIdx = -1; }
              pickupAt(sIdx);
              if (sIdx === exitIdx) { gameOver = 'won'; }
            }
          }
        }
      }
      afterMove();
      return;
    }
    var target = neighbourCoord(player.x, player.y, dirIdx);
    var targetIdx = target[1] * GRID + target[0];
    var occupant = get(target[0], target[1]);
    if (MODE === 'shift') {
      if (occupant === WALL) { afterMove(); return; }
      if (tryEnterDoor(targetIdx)) { afterMove(); return; }
      if (occupant === MONSTER) {
        if (!autoFireAt(target[0], target[1])) hurt(30, 'collided with a monster while empty-handed');
        set(target[0], target[1], GROUND);
      }
      tickRule(shiftRules[dirIdx]);
      set(player.x, player.y, PLAYER);
      monsters = countMonsterCells();
      afterMove(true);
      return;
    }
    if (MODE === 'scent' || MODE === 'evolved') {
      if (occupant === WALL) { afterMove(); return; }
      if (tryEnterDoor(targetIdx)) { afterMove(); return; }
      if (occupant === MONSTER) {
        if (!autoFireAt(target[0], target[1])) hurt(30, 'collided with a monster while empty-handed');
      }
      set(player.x, player.y, GROUND);
      set(target[0], target[1], PLAYER);
      player.x = target[0]; player.y = target[1];
      if (targetIdx === keyIdx) { player.hasKey = true; keyIdx = -1; }
      pickupAt(targetIdx);
      if (targetIdx === exitIdx) { gameOver = 'won'; }
      afterMove();
      return;
    }
  }

  function playerWait () {
    if (gameOver) return;
    if (MODE === 'ink') { afterMoveInk(); return; }
    afterMove();
  }

  function playerFire () {
    if (gameOver) return;
    if (MODE === 'ink') { playerFireInk(); return; }
    if (!player.hasShotgun) return;
    if (player.ammo <= 0) return;
    player.ammo--;
    var x = player.x, y = player.y;
    var hitX = x, hitY = y;
    for (var step = 0; step < 4; step++) {
      var nb = neighbourCoord(x, y, player.lastDir);
      x = nb[0]; y = nb[1];
      hitX = x; hitY = y;
      if (MODE === 'overlay') {
        var cellHere = get(x, y);
        if (isWallForOverlay(cellHere)) {
          // Fragile wall: state-2 wall yields to a shotgun shell if
          // DESTRUCT_W2 is on.  State-3 walls always block.
          if (DESTRUCT_W2 && cellHere === 2) set(x, y, 0);
          break;
        }
        var hit = monsters.find(function (m) {
          return m.alive && m.x === x && m.y === y; });
        if (hit) { hit.alive = false; break; }
      } else {
        var c = get(x, y);
        if (c === WALL) break;
        if (c === MONSTER) { set(x, y, GROUND); break; }
      }
    }
    fireFlash = { fromX: player.x, fromY: player.y,
                  toX: hitX, toY: hitY, framesLeft: 2 };
    afterMove();
  }

  function meleeAdjacent () {
    if (MODE !== 'scent' && MODE !== 'evolved') return;
    for (var d = 0; d < 6; d++) {
      var nb = neighbourCoord(player.x, player.y, d);
      if (get(nb[0], nb[1]) === MONSTER) {
        if (!autoFireAt(nb[0], nb[1])) hurt(10, 'gnawed on by adjacent monsters');
        set(nb[0], nb[1], GROUND);
      }
    }
    monsters = countMonsterCells();
  }

  function afterMove (skipPactTick) {
    turn++;
    var rate = paused ? 0 : worldRate;
    if (MODE === 'overlay') {
      for (var t = 0; t < rate; t++) tickPactRule();
      if (isWallForOverlay(get(player.x, player.y))) {
        gameOver = 'lost';
        deathCause = 'crushed by a wall that grew under you';
      }
      moveOverlayMonsters();
    } else if (MODE === 'shift') {
      if (!skipPactTick && !PURE_MODE) {
        for (var t = 0; t < rate; t++) {
          tickPactRule();
          set(player.x, player.y, PLAYER);
        }
        monsters = countMonsterCells();
      }
      checkGameOver_singleRule();
    } else if (MODE === 'scent') {
      for (var t = 0; t < rate; t++) tickRule(scentRule);
      monsters = countMonsterCells();
      checkGameOver_singleRule();
    } else if (MODE === 'evolved') {
      for (var t = 0; t < rate; t++) tickRule(evolvedRule);
      monsters = countMonsterCells();
      checkGameOver_singleRule();
    }
    meleeAdjacent();
    if (player.hp <= 0 && !gameOver) {
      gameOver = 'lost';
      deathCause = lastHurtBy || 'bled out';
      // In pure-CA modes, capture the player's neighbourhood so the
      // user can see which cells the rule grew into MONSTER against
      // them.  Output here is "MONSTER" since that's what bit.
      if (MODE === 'scent' || MODE === 'evolved') {
        captureFromPlayerCell(MONSTER);
      }
    }
    if (!gameOver && player.y * GRID + player.x === exitIdx) gameOver = 'won';
    draw(); updateReadouts();
  }

  function checkGameOver_singleRule () {
    var hereNow = get(player.x, player.y);
    if (hereNow !== PLAYER) {
      gameOver = 'lost';
      deathCause = 'overwritten by the rule — the world ate you';
      // Capture: self was PLAYER, neighbours are the current cells
      // around the player position, output is whatever overwrote the
      // player cell (hereNow).
      captureFromPlayerCell(hereNow);
    }
  }

  function moveOverlayMonsters () {
    for (var i = 0; i < monsters.length; i++) {
      var m = monsters[i];
      if (!m.alive || gameOver === 'lost') continue;
      var best = -1, bestDist = 1e9, ties = [];
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(m.x, m.y, d);
        var nx = nb[0], ny = nb[1];
        if (isWallForOverlay(get(nx, ny))) continue;
        var crowded = false;
        for (var j = 0; j < monsters.length; j++) {
          if (j === i) continue;
          if (monsters[j].alive && monsters[j].x === nx && monsters[j].y === ny) {
            crowded = true; break;
          }
        }
        if (crowded) continue;
        var dist = hexDist(nx, ny, player.x, player.y);
        if (dist < bestDist) { bestDist = dist; best = d; ties = [d]; }
        else if (dist === bestDist) ties.push(d);
      }
      if (best >= 0) {
        var pick = ties[0];
        if (ties.length > 1) {
          var b = (tieBreakBytes && tieBreakBytes.length)
            ? tieBreakBytes[(i + turn) % tieBreakBytes.length] : 0;
          pick = ties[b % ties.length];
        }
        var dest = neighbourCoord(m.x, m.y, pick);
        m.x = dest[0]; m.y = dest[1];
        if (m.x === player.x && m.y === player.y) {
          if (!autoFireAt(m.x, m.y)) hurt(30, 'caught by a charging monster');
          m.alive = false;
        }
      }
    }
  }

  function draw () {
    ctx.fillStyle = '#050505';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    var half = Math.floor(VIEW / 2);
    for (var dy = -half; dy <= half; dy++) {
      for (var dx = -half; dx <= half; dx++) {
        var wx = (player.x + dx + GRID) % GRID;
        var wy = (player.y + dy + GRID) % GRID;
        var cell = get(wx, wy);
        var rowShift = (wy & 1) ? CELL_PX * 0.5 : 0;
        var screenX = (dx + half) * H_STEP + rowShift;
        var screenY = (dy + half) * V_STEP;
        var fill;
        if (MODE === 'ink') {
          // Fog of war.  Default everything to floor (palette[0]).
          // Only the controlled player cell and revealed brush-bot
          // heads break through.
          if (cell === INK_WALL) fill = COL_S1;
          else                    fill = COL_S0;
          if (wx === player.x && wy === player.y) fill = COL_WALL_DK;
          else if (cell === INK_MONSTER) {
            for (var bi = 0; bi < brushBots.length; bi++) {
              var b = brushBots[bi];
              if (b.alive && b.x === wx && b.y === wy) { fill = COL_WALL; break; }
            }
          }
        } else if (MODE === 'overlay') {
          fill = (cell === 3) ? COL_WALL
               : (cell === 2) ? COL_WALL_DK
               : (cell === 1) ? COL_S1
               :                COL_S0;
        } else {
          fill = (cell === WALL) ? COL_WALL
               : (cell === GROUND) ? COL_GROUND
               : (cell === PLAYER) ? '#050505'
               : '#050505';
        }
        ctx.fillStyle = fill;
        ctx.fillRect(screenX, screenY, CELL_PX, CELL_PX);
      }
    }
    function drawCellAt (cellIdx, drawFn) {
      var cx = cellIdx % GRID, cy = (cellIdx / GRID) | 0;
      var ddx = cx - player.x;
      if (ddx >  GRID / 2) ddx -= GRID;
      if (ddx < -GRID / 2) ddx += GRID;
      var ddy = cy - player.y;
      if (ddy >  GRID / 2) ddy -= GRID;
      if (ddy < -GRID / 2) ddy += GRID;
      if (Math.abs(ddx) > half || Math.abs(ddy) > half) return;
      var rs = (cy & 1) ? CELL_PX * 0.5 : 0;
      var sx = (ddx + half) * H_STEP + rs;
      var sy = (ddy + half) * V_STEP;
      drawFn(sx, sy, sx + CELL_PX / 2, sy + CELL_PX / 2);
    }
    if (exitIdx >= 0) {
      drawCellAt(exitIdx, function (sx, sy, cx2, cy2) {
        ctx.fillStyle = '#0a3a3a';
        ctx.fillRect(sx + 1, sy + 1, CELL_PX - 2, CELL_PX - 2);
        ctx.strokeStyle = '#5fb';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx2, cy2, CELL_PX * 0.32, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = '#5fb';
        ctx.font = Math.floor(CELL_PX * 0.55) + 'px monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('⌂', cx2, cy2 + 1);
      });
    }
    if (doorIdx !== null && doorIdx >= 0) {
      drawCellAt(doorIdx, function (sx, sy, cx2, cy2) {
        ctx.fillStyle = doorOpen ? '#3a2a0a' : '#9b6a14';
        ctx.fillRect(sx + 1, sy + 1, CELL_PX - 2, CELL_PX - 2);
        if (!doorOpen) {
          ctx.fillStyle = '#fd0';
          ctx.font = Math.floor(CELL_PX * 0.5) + 'px monospace';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('🔒', cx2, cy2 + 1);
        }
      });
    }
    if (keyIdx !== null && keyIdx >= 0) {
      drawCellAt(keyIdx, function (sx, sy, cx2, cy2) {
        ctx.fillStyle = '#fd0';
        ctx.font = Math.floor(CELL_PX * 0.6) + 'px monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('🔑', cx2, cy2 + 1);
      });
    }
    for (var k in items) {
      var it = items[k];
      drawCellAt(+k, (function (it) { return function (sx, sy, cx2, cy2) {
        ctx.font = Math.floor(CELL_PX * 0.55) + 'px monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        if (it.type === 'medkit') {
          ctx.fillStyle = '#3f3';
          ctx.fillText('✚', cx2, cy2 + 1);
        } else if (it.type === 'ammo') {
          ctx.fillStyle = '#fb6';
          ctx.fillText('●', cx2, cy2 + 1);
        } else if (it.type === 'shotgun') {
          ctx.fillStyle = '#ccc';
          ctx.fillText('⌐', cx2, cy2 + 1);
        }
      }; })(it));
    }

    // Ink mode is fog-of-war: monsters are drawn via cell-fills
    // (palette[3] for revealed bot heads) and the player is drawn
    // via cell-fill (palette[2]).  Skip the JS overlays entirely.
    var mDrawList = (MODE === 'ink')
      ? []
      : (MODE === 'overlay')
        ? monsters.filter(function (m) { return m.alive; })
        : monsters;
    for (var i = 0; i < mDrawList.length; i++) {
      var m = mDrawList[i];
      var ddx = m.x - player.x;
      if (ddx >  GRID / 2) ddx -= GRID;
      if (ddx < -GRID / 2) ddx += GRID;
      var ddy = m.y - player.y;
      if (ddy >  GRID / 2) ddy -= GRID;
      if (ddy < -GRID / 2) ddy += GRID;
      if (Math.abs(ddx) > half || Math.abs(ddy) > half) continue;
      var rs = (m.y & 1) ? CELL_PX * 0.5 : 0;
      var sx = (ddx + half) * H_STEP + rs + CELL_PX / 2;
      var sy = (ddy + half) * V_STEP + CELL_PX / 2;
      ctx.fillStyle = COL_MONSTER;
      ctx.beginPath();
      ctx.arc(sx, sy, CELL_PX * 0.35, 0, Math.PI * 2);
      ctx.fill();
    }
    var prs = (player.y & 1) ? CELL_PX * 0.5 : 0;
    var px = half * H_STEP + prs + CELL_PX / 2;
    var py = half * V_STEP + CELL_PX / 2;
    if (MODE !== 'ink') {
      ctx.fillStyle = COL_PLAYER_HALO;
      ctx.beginPath();
      ctx.arc(px, py, CELL_PX * 0.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = COL_PLAYER;
      ctx.beginPath();
      ctx.arc(px, py, CELL_PX * 0.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(88,166,255,0.7)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(px - 8, py); ctx.lineTo(px + 8, py);
      ctx.moveTo(px, py - 8); ctx.lineTo(px, py + 8);
      ctx.stroke();
    } else {
      // Subtle reticule on the controlled cell so the player can
      // still pick themselves out at a glance, without breaking the
      // K=4 colour discipline.
      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(px, py, CELL_PX * 0.38, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (fireFlash && fireFlash.framesLeft > 0) {
      var ff = fireFlash;
      function screenCoord (wx, wy) {
        var ddx = wx - player.x;
        if (ddx >  GRID / 2) ddx -= GRID;
        if (ddx < -GRID / 2) ddx += GRID;
        var ddy = wy - player.y;
        if (ddy >  GRID / 2) ddy -= GRID;
        if (ddy < -GRID / 2) ddy += GRID;
        var rs = (wy & 1) ? CELL_PX * 0.5 : 0;
        return [(ddx + half) * H_STEP + rs + CELL_PX / 2,
                (ddy + half) * V_STEP + CELL_PX / 2];
      }
      var a = screenCoord(ff.fromX, ff.fromY);
      var b = screenCoord(ff.toX,   ff.toY);
      ctx.strokeStyle = 'rgba(255,220,80,0.95)';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
      ctx.stroke();
      ctx.fillStyle = 'rgba(255,240,160,0.8)';
      ctx.beginPath();
      ctx.arc(b[0], b[1], CELL_PX * 0.45, 0, Math.PI * 2);
      ctx.fill();
      fireFlash.framesLeft--;
      if (fireFlash.framesLeft <= 0) fireFlash = null;
    }
  }

  function updateReadouts () {
    var setText = function (id, text) {
      var el = document.getElementById(id);
      if (el) el.textContent = text;
    };
    setText('dc-turn', turn);
    setText('dc-pos', '(' + player.x + ',' + player.y + ')');
    var monsterDisplay;
    if (MODE === 'ink') {
      var revealed = 0;
      for (var i = 0; i < brushBots.length; i++) {
        if (brushBots[i].alive) revealed++;
      }
      monsterDisplay = revealed + ' revealed · drip r=' + inkRadius;
    } else if (MODE === 'overlay') {
      monsterDisplay = monsters.filter(function (m) { return m.alive; }).length;
    } else {
      monsterDisplay = monsters.length;
    }
    setText('dc-mleft', monsterDisplay);
    setText('dc-gen', generation);
    var hp = Math.max(0, player.hp || 0);
    setText('dc-hp', hp);
    var hpf = document.getElementById('dc-hpfill');
    if (hpf) hpf.style.width = hp + '%';
    setText('dc-ammo', player.ammo + (player.hasShotgun ? '' : ' (no weapon)'));
    var ki = document.getElementById('dc-key');
    if (ki) {
      ki.className = 'keyIcon' + (player.hasKey ? '' : ' dim');
      ki.title = player.hasKey ? 'key in hand' : 'no key';
    }
    var obj = document.getElementById('dc-objective');
    if (obj) {
      if (!player.hasShotgun) obj.textContent = '— grab the shotgun —';
      else if (doorIdx !== null && doorIdx >= 0 && !doorOpen && !player.hasKey)
        obj.textContent = '— find the key —';
      else obj.textContent = '— find the exit —';
    }
    var s = document.getElementById('dc-status');
    if (s) {
      if (gameOver === 'lost') {
        var cause = deathCause ? ' — ' + deathCause + '.' : '.';
        s.innerHTML = '<span class="game-over">— you died' + cause + '</span>';
      } else if (gameOver === 'won') {
        s.innerHTML = '<span class="you-win">— reached the exit. ' + hp + ' HP remaining.</span>';
      } else {
        s.textContent = '';
      }
    }
    // Show the killing rule cell next to the canvas if we have one,
    // hide it otherwise (also covers post-restart).
    renderDeathRule();
  }

  function cardinalToHex (k) {
    switch (k) {
      case 'W':  case 'ArrowUp':   return 0;
      case 'D':  case 'ArrowRight':return 1;
      case 'X':  case 'ArrowDown': return 2;
      case 'A':  case 'ArrowLeft': return 4;
      case 'Q':                    return 5;
      case 'E':                    return 0;
      case 'Z':                    return 3;
      case 'C':                    return 2;
      case 'S':                    return 2;
    }
    return -1;
  }
  var worldRate = 1, paused = false;
  var rateEl = document.getElementById('dc-world-rate');
  if (rateEl) rateEl.addEventListener('change', function () {
    worldRate = Math.max(0, Math.min(10, parseInt(this.value, 10) || 1));
  });
  var pauseEl = document.getElementById('dc-pause');
  if (pauseEl) pauseEl.addEventListener('click', function () {
    paused = !paused;
    this.textContent = paused ? 'unpause world tick' : 'pause world tick';
  });
  var resetEl = document.getElementById('dc-reset');
  if (resetEl) resetEl.addEventListener('click', init);

  var randPalEl = document.getElementById('dc-randpal');
  if (randPalEl) randPalEl.addEventListener('click', randomisePaletteNow);

  document.addEventListener('keydown', function (ev) {
    if (MODE === 'platform') return;   // platform mode owns its own input
    if (gameOver) {
      if (ev.key === 'r' || ev.key === 'R') { init(); ev.preventDefault(); }
      return;
    }
    if (ev.key === ' ' || ev.key === 'Space') {
      playerFire(); ev.preventDefault(); return;
    }
    if (ev.key === '.') {
      playerWait(); ev.preventDefault(); return;
    }
    if (MODE === 'ink' && (ev.key === '+' || ev.key === '=' || ev.key === ']')) {
      inkRadius = Math.min(4, inkRadius + 1);
      updateReadouts(); ev.preventDefault(); return;
    }
    if (MODE === 'ink' && (ev.key === '-' || ev.key === '_' || ev.key === '[')) {
      inkRadius = Math.max(0, inkRadius - 1);
      updateReadouts(); ev.preventDefault(); return;
    }
    var k = ev.key.length === 1 ? ev.key.toUpperCase() : ev.key;
    var dir = cardinalToHex(k);
    if (dir >= 0) { playerMove(dir); ev.preventDefault(); }
  });
  canvas.tabIndex = 0;
  canvas.focus();

  // ─── Ink mode ────────────────────────────────────────────────
  // Player is one specific state-2 cell inside the K=4 CA.  Moving
  // writes state-2 into the target cell and leaves state-2 in the
  // current one — a "drip" the pact rule then evolves.  State-2 and
  // state-3 cells render as floor unless they're the controlled
  // player or a revealed brush-bot.  First contact with a state-3
  // cell reveals it: that cell becomes a brush-bot that chases the
  // player, dripping state-3 ink the same way.
  // INK_GROUND/INK_WALL refer to K=4 states with the ink-mode
  // semantic (0 / 1), not the simplified WALL/GROUND constants from
  // the engine which collide with state-2/3 in this mode.
  var INK_GROUND = 0, INK_WALL = 1, INK_PLAYER = 2, INK_MONSTER = 3;
  var brushBots = [];   // revealed bots: {x, y, lastDir, alive}
  var inkRadius = 1;    // hex-disk radius of the player's drip splash;
                        // grow with =/+, shrink with -/_; range [0, 4].
  function inkIsWall (s) { return s === INK_WALL; }

  function splashInk (cx, cy, radius, value) {
    // Hex-disk splash of `value` at (cx, cy) out to `radius` rings.
    // Walls (state-1) and brush-bot heads are preserved; everything
    // else gets overwritten.  Unrevealed state-3 cells get painted —
    // that's deliberate: a wide splash can erase hidden monsters
    // without revealing them, trading information for cells.
    if (radius <= 0) {
      var s = get(cx, cy);
      if (s !== INK_WALL) set(cx, cy, value);
      return;
    }
    var seen = new Set();
    var frontier = [[cx, cy]];
    seen.add(cy * GRID + cx);
    for (var r = 0; r < radius; r++) {
      var next = [];
      for (var i = 0; i < frontier.length; i++) {
        var fx = frontier[i][0], fy = frontier[i][1];
        for (var d = 0; d < 6; d++) {
          var nb = neighbourCoord(fx, fy, d);
          var key = nb[1] * GRID + nb[0];
          if (seen.has(key)) continue;
          seen.add(key);
          next.push(nb);
        }
      }
      frontier = next;
    }
    seen.forEach(function (key) {
      var x = key % GRID, y = (key / GRID) | 0;
      var s = get(x, y);
      if (s === INK_WALL) return;
      // Preserve revealed bot heads so a wide player splash doesn't
      // wipe them mid-chase.
      for (var i = 0; i < brushBots.length; i++) {
        var b = brushBots[i];
        if (b.alive && b.x === x && b.y === y) return;
      }
      set(x, y, value);
    });
  }
  function initInkMode () {
    var raw = seedGrid(seed[COMPONENT]);
    world = new Uint8Array(GRID * GRID);
    // Re-derive the K=4 grid: cells below wall_threshold collapse to
    // state-0/1 based on simple seed-byte parity (so the level still
    // has structure); cells at-or-above stay as state-1 walls.  This
    // gives the rule a clean substrate; the player + bots add their
    // own state-2/3 cells over time.
    for (var i = 0; i < raw.length; i++) {
      var r = raw[i];
      if (r >= WALL_THRESH) world[i] = INK_WALL;
      else                  world[i] = INK_GROUND;
    }
    // Spawn the player near centre, on a state-0 cell.
    var c = Math.floor(GRID / 2);
    player = findGroundNear(c, c, inkIsWall);
    player.hp = 100; player.ammo = 0;
    player.hasShotgun = false; player.hasKey = false;
    player.lastDir = 1;
    set(player.x, player.y, INK_PLAYER);

    // Items + door + exit on top of an overlay-style binary view.
    var level = placeLevelOnce(world, player.x, player.y);
    items = level.items; doorIdx = level.doorIdx;
    keyIdx = level.keyIdx; exitIdx = level.exitIdx; doorOpen = false;

    // Place hidden monsters as state-3 cells in the K=4 grid.  None
    // are revealed yet → they all display as floor.
    brushBots = [];
    monsters = [];
    tapAsync(COMPONENT, 0, MONSTER_COUNT * 4 + 32).then(function (bytes) {
      var bi = 0, placed = 0, attempts = 0;
      while (placed < MONSTER_COUNT && attempts < MONSTER_COUNT * 30) {
        attempts++;
        var mx = bytes[bi % bytes.length] % GRID; bi++;
        var my = bytes[bi % bytes.length] % GRID; bi++;
        if (get(mx, my) !== INK_GROUND) continue;
        var midx = my * GRID + mx;
        if (midx === exitIdx || midx === doorIdx
            || midx === keyIdx || items[midx]) continue;
        if (hexDist(mx, my, player.x, player.y) < 4) continue;
        set(mx, my, INK_MONSTER);
        placed++;
      }
      tieBreakBytes = bytes;
      draw(); updateReadouts();
    });
  }

  function inkRevealAdjacent () {
    // Any state-3 cell within 1 hex of the controlled player becomes
    // a brush-bot.  Idempotent: a bot already in the list isn't
    // duplicated.
    for (var d = 0; d < 6; d++) {
      var nb = neighbourCoord(player.x, player.y, d);
      if (get(nb[0], nb[1]) !== INK_MONSTER) continue;
      var already = false;
      for (var i = 0; i < brushBots.length; i++) {
        if (brushBots[i].x === nb[0] && brushBots[i].y === nb[1]
            && brushBots[i].alive) { already = true; break; }
      }
      if (!already) brushBots.push({x: nb[0], y: nb[1], lastDir: 0, alive: true});
    }
  }

  function inkTickBrushBots () {
    // Each revealed brush-bot moves one hex toward the player using
    // greedy hex distance, dripping state-3 the way the player drips
    // state-2.  Walls block; the bot waits if all 6 neighbours are
    // walls.  Walking onto the player damages -30 HP.
    for (var i = 0; i < brushBots.length; i++) {
      var b = brushBots[i];
      if (!b.alive) continue;
      var best = -1, bestDist = hexDist(b.x, b.y, player.x, player.y);
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(b.x, b.y, d);
        var s = get(nb[0], nb[1]);
        if (s === INK_WALL) continue;
        var dd = hexDist(nb[0], nb[1], player.x, player.y);
        if (dd < bestDist) { bestDist = dd; best = d; }
      }
      if (best < 0) continue;
      var nb = neighbourCoord(b.x, b.y, best);
      if (nb[0] === player.x && nb[1] === player.y) {
        // Bite the player.  Bot stays put (since the player is on
        // the cell); damage taken.
        hurt(30, 'caught by a brush-bot');
        continue;
      }
      // Drip: target becomes state-3; source stays state-3 (the
      // trail).  Bot position advances.
      set(nb[0], nb[1], INK_MONSTER);
      b.x = nb[0]; b.y = nb[1]; b.lastDir = best;
    }
  }

  function playerMoveInk (dirIdx) {
    if (gameOver) return;
    player.lastDir = dirIdx;
    var nb = neighbourCoord(player.x, player.y, dirIdx);
    var nx = nb[0], ny = nb[1];
    var targetIdx = ny * GRID + nx;
    var occ = get(nx, ny);
    if (occ === INK_WALL) { afterMoveInk(); return; }
    if (tryEnterDoor(targetIdx)) { afterMoveInk(); return; }
    if (occ === INK_MONSTER) {
      // Either a hidden monster cell (first contact → reveal,
      // no damage) or part of a brush-bot trail.  Check whether
      // it matches a brush-bot's current head.
      var head = null;
      for (var i = 0; i < brushBots.length; i++) {
        if (brushBots[i].alive
            && brushBots[i].x === nx && brushBots[i].y === ny) {
          head = brushBots[i]; break;
        }
      }
      if (head) {
        // Walking onto a brush-bot head: damage + destroy it.
        hurt(20, 'crashed into a revealed brush-bot');
        head.alive = false;
        set(nx, ny, INK_GROUND);
      }
      // Hidden state-3 cell: don't move; reveal is handled below.
      afterMoveInk();
      return;
    }
    // Drip-move: target ← state-2; source stays state-2.  Splash
    // ink in a hex-disk of the current radius around the new
    // position.  Source cell also gets re-stamped so the trail is
    // continuous even at radius 0.
    set(player.x, player.y, INK_PLAYER);
    splashInk(nx, ny, inkRadius, INK_PLAYER);
    set(nx, ny, INK_PLAYER);
    player.x = nx; player.y = ny;
    if (targetIdx === keyIdx) { player.hasKey = true; keyIdx = -1; }
    pickupAt(targetIdx);
    if (targetIdx === exitIdx) { gameOver = 'won'; }
    afterMoveInk();
  }

  function playerFireInk () {
    if (gameOver) return;
    if (!player.hasShotgun) return;
    if (player.ammo <= 0) return;
    player.ammo--;
    var x = player.x, y = player.y;
    var hitX = x, hitY = y;
    for (var step = 0; step < 4; step++) {
      var nb = neighbourCoord(x, y, player.lastDir);
      x = nb[0]; y = nb[1];
      hitX = x; hitY = y;
      var s = get(x, y);
      if (s === INK_WALL) break;
      // Brush-bot head?
      var killed = false;
      for (var i = 0; i < brushBots.length; i++) {
        var b = brushBots[i];
        if (b.alive && b.x === x && b.y === y) {
          b.alive = false; set(x, y, INK_GROUND);
          killed = true; break;
        }
      }
      if (killed) break;
      // Hidden state-3 cell: destroy + reveal nothing.
      if (s === INK_MONSTER) { set(x, y, INK_GROUND); break; }
      // state-2 (ink trail) and state-0 (ground): pass through.
    }
    fireFlash = { fromX: player.x, fromY: player.y,
                  toX: hitX, toY: hitY, framesLeft: 2 };
    afterMoveInk();
  }

  function afterMoveInk () {
    turn++;
    var rate = paused ? 0 : worldRate;
    // Reveal any state-3 cells adjacent to the player BEFORE the bot
    // tick, so newly-revealed ones immediately get an action.
    inkRevealAdjacent();
    // Pact rule ticks normally — it sees the full K=4 grid and may
    // move state-2/3 cells around.  Brush-bot positions might end up
    // on a cell the rule turned into something else; we'll re-stamp
    // each surviving bot's head as state-3 to keep the bot coherent.
    if (!PURE_MODE) for (var t = 0; t < rate; t++) tickPactRule();
    // Re-stamp the controlled player cell so the rule can't erase
    // the player.  (Otherwise the K=4 rule could turn the player
    // cell into ground/wall.)
    if (!gameOver) set(player.x, player.y, INK_PLAYER);
    // Brush-bots act after the rule.
    inkTickBrushBots();
    // Re-stamp each alive bot head as state-3.
    for (var i = 0; i < brushBots.length; i++) {
      if (brushBots[i].alive) set(brushBots[i].x, brushBots[i].y, INK_MONSTER);
    }
    // Reveal anything the bots' trails or rule motion just brought
    // adjacent to us.
    inkRevealAdjacent();
    // Death by player cell becoming a wall (the rule mutating us).
    if (!gameOver && get(player.x, player.y) === INK_WALL) {
      gameOver = 'lost';
      deathCause = 'crushed by a wall that grew under you';
    }
    draw();
    updateReadouts();
  }

  // ─── Platform mode (side-scroller w/ gravity + jump) ─────────
  // Reinterprets the same hex CA grid as a Cartesian level: each
  // cell is a square at (x, y).  Walls become platforms; player
  // walks across the tops of them under gravity.  Same overlay
  // logic for items/door/key/exit/monsters, but movement is
  // real-time pixel motion instead of turn-based hex steps.
  var platformState = null;
  var platformKeys  = { left: false, right: false, jump: false };
  var platformRaf   = null;
  var lastFrameT    = 0;
  var ticksSinceWorld = 0;
  var jumpPressed   = false;   // edge-triggered

  // Platform mode needs enough surfaces to stand on or the world
  // reads as empty sky.  Clamp the gene's wall_threshold to at most
  // 2 here so state-2 and state-3 cells are both platforms — without
  // this, an evolved gene with wall_threshold=3 leaves only ~25 % of
  // cells as walls and the level looks like a thin scatter of dots.
  var PLATFORM_WALL_THRESH = Math.min(WALL_THRESH, 2);
  function platformIsWall (cx, cy) {
    if (cy < 0 || cy >= GRID) return true;          // ceiling/floor walls
    var x = ((cx % GRID) + GRID) % GRID;
    var cell = get(x, cy);
    return cell >= PLATFORM_WALL_THRESH;
  }

  // Drop from row 1 down `col` until the cell directly below is a
  // wall.  Returns the standing y (the cell the player will occupy)
  // or -1 if the column is fully open (no floor anywhere).
  function platformDropFromTop (col) {
    if (col < 0 || col >= GRID) return -1;
    var sy = 1;
    while (sy < GRID - 1 && !platformIsWall(col, sy + 1)) sy++;
    if (sy <= 0)            return -1;
    if (platformIsWall(col, sy)) return -1;
    return sy;
  }

  // Spiral outward from the centre column looking for a spawn that
  // (a) has standing room and (b) has at least one walkable
  // horizontal neighbour.  Centre column ignores the freedom check
  // first time round so legacy behaviour wins when the centre is
  // already fine.
  function findSafePlatformSpawn () {
    var cx = (GRID / 2) | 0;
    var centre_sy = platformDropFromTop(cx);
    if (centre_sy >= 0
        && (!platformIsWall(cx - 1, centre_sy)
         || !platformIsWall(cx + 1, centre_sy))) {
      return { x: cx, y: centre_sy, source: 'centre' };
    }
    for (var r = 1; r < GRID; r++) {
      for (var sign = -1; sign <= 1; sign += 2) {
        var col = cx + r * sign;
        if (col < 1 || col >= GRID - 1) continue;
        var sy = platformDropFromTop(col);
        if (sy < 0) continue;
        var leftOK  = !platformIsWall(col - 1, sy);
        var rightOK = !platformIsWall(col + 1, sy);
        if (leftOK || rightOK) {
          return { x: col, y: sy, source: 'spiral@r=' + r };
        }
      }
    }
    // Last resort: any column with standing room, even if hemmed in.
    for (var col2 = 1; col2 < GRID - 1; col2++) {
      var sy2 = platformDropFromTop(col2);
      if (sy2 >= 0) return { x: col2, y: sy2, source: 'fallback' };
    }
    // Truly hopeless map: spawn dead-centre, the player will bleed
    // out from the wall-crush damage code.
    return { x: cx, y: 1, source: 'crushed' };
  }

  // Flood-fill reachability with platform-physics constraints.  From
  // the spawn cell, BFS to every cell reachable by:
  //   - walking left/right one cell at a time (target cell non-wall)
  //   - jumping up to PLATFORM_JUMP_H cells if the destination column
  //     allows it (no wall along the rise)
  //   - free fall (any number of cells down to the next floor).
  // Returns { reachable, open, ratio }.  ratio < 0.15 → unplayable.
  var PLATFORM_JUMP_H = 3;
  function platformReachableCells (spawnX, spawnY) {
    var visited = new Uint8Array(GRID * GRID);
    var queue = [];
    var sx = spawnX | 0, sy = spawnY | 0;
    if (sy < 0 || sy >= GRID || sx < 0 || sx >= GRID) {
      return { reachable: 0, open: 0, ratio: 0 };
    }
    var sIdx = sy * GRID + sx;
    visited[sIdx] = 1;
    queue.push([sx, sy]);
    var reachable = 1;
    while (queue.length) {
      var p = queue.pop();
      var x = p[0], y = p[1];
      // Free-fall down to the next floor.
      var fy = y;
      while (fy < GRID - 1 && !platformIsWall(x, fy + 1)) {
        fy++;
        var idx = fy * GRID + x;
        if (!visited[idx] && !platformIsWall(x, fy)) {
          visited[idx] = 1; reachable++; queue.push([x, fy]);
        }
      }
      var standing_y = fy;       // the cell the player rests on
      // Walk + jump in each direction.
      for (var dx = -1; dx <= 1; dx += 2) {
        var nx = x + dx;
        if (nx < 0 || nx >= GRID) continue;
        for (var jy = -PLATFORM_JUMP_H; jy <= 0; jy++) {
          // jy=0 is straight walk; jy=-1..-3 simulate jumping up
          var ny = standing_y + jy;
          if (ny < 0 || ny >= GRID) continue;
          if (platformIsWall(nx, ny)) continue;
          // For jumps we also need the column above the source to be
          // clear so the player has headroom.
          var headroomBlocked = false;
          for (var hy = standing_y + jy; hy < standing_y; hy++) {
            if (platformIsWall(x, hy)) { headroomBlocked = true; break; }
          }
          if (headroomBlocked) continue;
          var nidx = ny * GRID + nx;
          if (visited[nidx]) continue;
          visited[nidx] = 1; reachable++; queue.push([nx, ny]);
        }
      }
    }
    var open = 0;
    for (var i = 0; i < GRID * GRID; i++) {
      var rr = (i / GRID) | 0, cc = i % GRID;
      if (!platformIsWall(cc, rr)) open++;
    }
    return { reachable: reachable, open: open,
              ratio: open > 0 ? reachable / open : 0 };
  }

  // Most-recent playability metric, surfaced in the HUD so the user
  // can see when a level is cramped (ratio < ~30 %).
  var platformPlayInfo = null;

  function initPlatformMode () {
    world = seedGrid(seed[COMPONENT]).slice();
    var spawn = findSafePlatformSpawn();
    var spawnCol = spawn.x, sx = spawn.x, sy = spawn.y;
    var play = platformReachableCells(sx, sy);
    platformPlayInfo = {
      spawnX: sx, spawnY: sy, source: spawn.source,
      reachable: play.reachable, open: play.open, ratio: play.ratio,
    };
    if (window.console && console.log) {
      console.log('[doom-ca platform] spawn (' + sx + ',' + sy +
                   ') via ' + spawn.source +
                   ' · reachable ' + play.reachable + '/' + play.open +
                   ' (' + Math.round(100 * play.ratio) + '%)');
    }
    player = {
      x: sx + 0.5, y: sy - 0.4,             // float coords (cell units)
      vx: 0, vy: 0, onGround: false,
      hp: 100, ammo: 0, hasShotgun: false, hasKey: false,
      lastDir: 1,                           // +1 right, -1 left
    };
    // Place items / door / exit using the same overlay-style
    // GROUND/WALL view of the world.
    var level = placeLevelOnce(world, spawnCol, sy);
    items   = level.items;
    doorIdx = level.doorIdx;
    keyIdx  = level.keyIdx;
    exitIdx = level.exitIdx;
    doorOpen = false;
    // Spawn monsters on top of platform cells.  Each gets a heading
    // direction (-1 or +1) and walks the platform top, reversing at
    // gaps or walls.
    monsters = [];
    var rng = window.DoomCAEngine.makeRng((seed[COMPONENT] * 0x9e3779b9) >>> 0);
    for (var attempt = 0; monsters.length < MONSTER_COUNT && attempt < MONSTER_COUNT * 40; attempt++) {
      var mx = (rng() * GRID) | 0;
      var my = (rng() * GRID) | 0;
      // Want my to be a non-wall cell whose cell BELOW is a wall.
      if (platformIsWall(mx, my)) continue;
      if (!platformIsWall(mx, my + 1)) continue;
      // Don't spawn too close to player or on items.
      if (Math.abs(mx - spawnCol) + Math.abs(my - sy) < 6) continue;
      var midx = my * GRID + mx;
      if (midx === exitIdx || midx === doorIdx
          || midx === keyIdx || items[midx]) continue;
      monsters.push({
        x: mx + 0.5, y: my - 0.4, alive: true,
        vx: (rng() < 0.5 ? -1 : 1) * 1.2,
      });
    }
    platformState = {
      camX: player.x, camY: player.y,
      gravity: 24, jumpSpeed: 9.5,
      moveSpeed: 5.0, friction: 14, maxFall: 16,
      worldTickFrames: 30,                  // CA ticks every 30 frames @ ~60fps = 0.5 s
    };
    if (window.DoomMusic && rulesFlat && rulesFlat.length) {
      // Music keeps using the same pact rule slice (already wired
      // in the main flow); nothing extra to set here.
    }
    document.getElementById('dc-canvas').focus();
    lastFrameT = performance.now();
    ticksSinceWorld = 0;
    if (platformRaf) cancelAnimationFrame(platformRaf);
    platformRaf = requestAnimationFrame(platformFrame);
  }

  function platformPhysicsStep (dt) {
    var ps = platformState;
    // Horizontal velocity: target = -moveSpeed / 0 / +moveSpeed.
    var target = 0;
    if (platformKeys.left)  target -= ps.moveSpeed;
    if (platformKeys.right) target += ps.moveSpeed;
    if (target !== 0) {
      player.vx = target;
      player.lastDir = target > 0 ? 1 : 4;   // 1=right, 4=left in hex dir codes
    } else {
      // Friction
      if (Math.abs(player.vx) < ps.friction * dt) player.vx = 0;
      else player.vx -= Math.sign(player.vx) * ps.friction * dt;
    }
    // Jump: edge-triggered.  Only takes effect on a frame where the
    // key transitions from up to down (jumpPressed flag is set by
    // keydown and cleared once consumed).
    if (jumpPressed && player.onGround) {
      player.vy = -ps.jumpSpeed;
      player.onGround = false;
    }
    jumpPressed = false;
    // Gravity
    player.vy += ps.gravity * dt;
    if (player.vy > ps.maxFall) player.vy = ps.maxFall;
    // Integrate position with axis-separated collision.
    moveAxis('x', player, player.vx * dt);
    moveAxis('y', player, player.vy * dt);
    // Re-check onGround: a 0.05-cell probe directly below us.
    player.onGround = collisionAt(player.x, player.y + 0.05, 0.4, 0.5);
    // Wall grew under us (non-pure CA tick): push out, no damage by
    // default — getting crushed by terrain you didn't choose to walk
    // into is unfair for an evolved platformer.
    var cx = Math.floor(player.x), cy = Math.floor(player.y);
    if (platformIsWall(cx, cy)) {
      player.y -= 0.2; player.vy = -2;
    }
    // Move monsters along platform tops.
    for (var i = 0; i < monsters.length; i++) {
      var m = monsters[i];
      if (!m.alive) continue;
      var newX = m.x + m.vx * dt;
      var ahead = (m.vx > 0) ? Math.floor(newX + 0.45) : Math.floor(newX - 0.45);
      var feet = Math.floor(m.y + 0.6);
      // Reverse at wall ahead OR at gap (no wall below the next cell).
      if (platformIsWall(ahead, Math.floor(m.y)) ||
          !platformIsWall(ahead, feet + 1)) {
        m.vx = -m.vx;
        newX = m.x + m.vx * dt;
      }
      m.x = newX;
      // Gravity also affects monsters in case a platform vanishes.
      var below = Math.floor(m.y + 0.5);
      if (!platformIsWall(Math.floor(m.x), below)) {
        m.y += 6 * dt;   // fall (slow so it's readable)
      }
      // Collision with player.
      if (Math.abs(m.x - player.x) < 0.7 && Math.abs(m.y - player.y) < 0.8) {
        if (!autoFireAt(Math.floor(m.x), Math.floor(m.y))) {
          hurt(30, 'a monster caught up to you');
        }
        m.alive = false;
        monsters.splice(i, 1); i--;
      }
    }
    // Item / door / key / exit overlays.
    var pidx = Math.floor(player.y) * GRID + Math.floor(player.x);
    if (pidx === keyIdx) { player.hasKey = true; keyIdx = -1; }
    if (pidx === doorIdx && !doorOpen) {
      if (player.hasKey) { doorOpen = true; player.hasKey = false; }
    }
    pickupAt(pidx);
    if (pidx === exitIdx) gameOver = 'won';
    // Smooth camera follow.
    ps.camX += (player.x - ps.camX) * Math.min(1, dt * 6);
    ps.camY += (player.y - ps.camY) * Math.min(1, dt * 6);
    if (player.hp <= 0 && !gameOver) {
      gameOver = 'lost';
      deathCause = lastHurtBy || 'fell';
    }
  }

  function collisionAt (cx, cy, hw, hh) {
    // Axis-aligned hitbox at (cx,cy) with half-width hw, half-height hh.
    // Returns true if any of the 4 corners are inside a wall cell.
    var x0 = Math.floor(cx - hw), x1 = Math.floor(cx + hw - 0.001);
    var y0 = Math.floor(cy - hh), y1 = Math.floor(cy + hh - 0.001);
    for (var yy = y0; yy <= y1; yy++) {
      for (var xx = x0; xx <= x1; xx++) {
        if (platformIsWall(xx, yy)) return true;
      }
    }
    return false;
  }

  function moveAxis (axis, p, delta) {
    if (delta === 0) return;
    var sign = delta > 0 ? 1 : -1;
    var rem  = Math.abs(delta);
    var hw = 0.4, hh = 0.5;
    while (rem > 0) {
      var step = Math.min(rem, 0.25);
      var nx = p.x, ny = p.y;
      if (axis === 'x') nx = p.x + sign * step;
      else              ny = p.y + sign * step;
      if (!collisionAt(nx, ny, hw, hh)) {
        p.x = nx; p.y = ny;
      } else {
        // Stop on collision; zero the relevant velocity component.
        if (axis === 'x') p.vx = 0;
        else { if (sign > 0) { p.onGround = true; } p.vy = 0; }
        return;
      }
      rem -= step;
    }
  }

  function platformDraw () {
    recomputeRenderMetrics();
    var W = canvas.width, H = canvas.height;
    ctx.fillStyle = '#0a0a12';
    ctx.fillRect(0, 0, W, H);
    var visCols = Math.ceil(W / CELL_PX) + 2;
    var visRows = Math.ceil(H / CELL_PX) + 2;
    var ps = platformState;
    var camX = ps.camX, camY = ps.camY;
    var x0 = Math.floor(camX - visCols / 2);
    var y0 = Math.floor(camY - visRows / 2);
    // Background gradient hint (sky → floor).
    var grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, '#1a1a2a');
    grad.addColorStop(1, '#080808');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
    function screenOf (wx, wy) {
      return [W / 2 + (wx - camX) * CELL_PX,
              H / 2 + (wy - camY) * CELL_PX];
    }
    // Cell fills.  Walls = solid palette colour; air cells get a faint
    // tint from palette[0]/palette[1] so the slip-ground variant is
    // visible against the sky gradient.
    var wallsDrawn = 0;
    for (var dy = 0; dy < visRows; dy++) {
      var wy = y0 + dy;
      for (var dx = 0; dx < visCols; dx++) {
        var wx = x0 + dx;
        if (wx < 0 || wx >= GRID) continue;
        var p = screenOf(wx, wy);
        var rawCell = (wy >= 0 && wy < GRID)
                      ? get(((wx % GRID) + GRID) % GRID, wy)
                      : 3;   // outside the grid → render as solid floor/ceiling
        if (platformIsWall(wx, wy)) {
          ctx.fillStyle = (rawCell === 3) ? COL_WALL : COL_WALL_DK;
          ctx.fillRect(p[0], p[1], CELL_PX + 0.5, CELL_PX + 0.5);
          // Slim darker edge along the top of each wall so platform
          // tops read as standable surfaces even at sparse densities.
          ctx.fillStyle = 'rgba(255,255,255,0.18)';
          ctx.fillRect(p[0], p[1], CELL_PX + 0.5, Math.max(2, CELL_PX * 0.12));
          wallsDrawn++;
        } else if (rawCell === 1) {
          ctx.fillStyle = 'rgba(' + componentPalette[1].join(',') + ',0.22)';
          ctx.fillRect(p[0], p[1], CELL_PX + 0.5, CELL_PX + 0.5);
        }
      }
    }
    // Build stamp so a stale browser cache is obvious — if you don't
    // see this text, the JS is cached; hard-reload (Ctrl+Shift+R).
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    var hud = 'platform · cells: ' + wallsDrawn
              + ' · thresh: ' + PLATFORM_WALL_THRESH;
    if (platformPlayInfo) {
      var pct = Math.round(100 * platformPlayInfo.ratio);
      hud += ' · play: ' + pct + '%';
      if (pct < 30) {
        ctx.fillStyle = 'rgba(255,160,80,0.85)';
        hud += ' (cramped — try a different pact)';
      }
      hud += ' · spawn: ' + platformPlayInfo.source;
    }
    ctx.fillText(hud, 6, H - 6);
    // Door, key, exit
    function drawOverlay (idx, drawFn) {
      if (idx == null || idx < 0) return;
      var wx = idx % GRID, wy = Math.floor(idx / GRID);
      var p = screenOf(wx, wy);
      drawFn(p[0], p[1]);
    }
    drawOverlay(exitIdx, function (sx, sy) {
      ctx.fillStyle = '#0a3a3a';
      ctx.fillRect(sx + 1, sy + 1, CELL_PX - 2, CELL_PX - 2);
      ctx.fillStyle = '#5fb';
      ctx.font = Math.floor(CELL_PX * 0.6) + 'px monospace';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('⌂', sx + CELL_PX / 2, sy + CELL_PX / 2 + 1);
    });
    drawOverlay(doorIdx, function (sx, sy) {
      ctx.fillStyle = doorOpen ? '#3a2a0a' : '#9b6a14';
      ctx.fillRect(sx + 1, sy + 1, CELL_PX - 2, CELL_PX - 2);
      if (!doorOpen) {
        ctx.fillStyle = '#fd0';
        ctx.font = Math.floor(CELL_PX * 0.55) + 'px monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('🔒', sx + CELL_PX / 2, sy + CELL_PX / 2 + 1);
      }
    });
    if (keyIdx != null && keyIdx >= 0) drawOverlay(keyIdx, function (sx, sy) {
      ctx.fillStyle = '#fd0';
      ctx.font = Math.floor(CELL_PX * 0.65) + 'px monospace';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('🔑', sx + CELL_PX / 2, sy + CELL_PX / 2 + 1);
    });
    for (var k in items) {
      var it = items[k];
      drawOverlay(+k, (function (it) { return function (sx, sy) {
        ctx.font = Math.floor(CELL_PX * 0.6) + 'px monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        if (it.type === 'medkit')       ctx.fillStyle = '#3f3';
        else if (it.type === 'ammo')    ctx.fillStyle = '#fb6';
        else if (it.type === 'shotgun') ctx.fillStyle = '#ccc';
        var glyph = it.type === 'medkit' ? '✚'
                  : it.type === 'ammo'   ? '●' : '⌐';
        ctx.fillText(glyph, sx + CELL_PX / 2, sy + CELL_PX / 2 + 1);
      }; })(it));
    }
    // Monsters (red squares with little eyes)
    for (var i = 0; i < monsters.length; i++) {
      var m = monsters[i];
      if (!m.alive) continue;
      var p = screenOf(m.x - 0.4, m.y - 0.5);
      ctx.fillStyle = COL_MONSTER;
      ctx.fillRect(p[0], p[1], CELL_PX * 0.8, CELL_PX);
      ctx.fillStyle = '#fff';
      var eyeX = m.vx > 0 ? p[0] + CELL_PX * 0.55 : p[0] + CELL_PX * 0.15;
      ctx.fillRect(eyeX, p[1] + CELL_PX * 0.25, CELL_PX * 0.12, CELL_PX * 0.18);
    }
    // Player
    var pp = screenOf(player.x - 0.4, player.y - 0.5);
    ctx.fillStyle = COL_PLAYER_HALO;
    ctx.fillRect(pp[0] - 4, pp[1] - 4, CELL_PX * 0.8 + 8, CELL_PX + 8);
    ctx.fillStyle = COL_PLAYER;
    ctx.fillRect(pp[0], pp[1], CELL_PX * 0.8, CELL_PX);
    ctx.fillStyle = '#fff';
    var peyeX = player.lastDir === 1 ? pp[0] + CELL_PX * 0.55 : pp[0] + CELL_PX * 0.15;
    ctx.fillRect(peyeX, pp[1] + CELL_PX * 0.2, CELL_PX * 0.12, CELL_PX * 0.18);
    // Fire flash (reuse hex helper if available, else a quick line)
    if (fireFlash && fireFlash.framesLeft > 0) {
      var ff = fireFlash;
      var a = screenOf(ff.fromX, ff.fromY);
      var b = screenOf(ff.toX, ff.toY);
      ctx.strokeStyle = 'rgba(255,220,80,0.95)';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(a[0] + CELL_PX/2, a[1] + CELL_PX/2);
      ctx.lineTo(b[0] + CELL_PX/2, b[1] + CELL_PX/2);
      ctx.stroke();
      fireFlash.framesLeft--;
      if (fireFlash.framesLeft <= 0) fireFlash = null;
    }
  }

  function platformFrame (now) {
    var dt = Math.min(0.05, (now - lastFrameT) / 1000) || 0.016;
    lastFrameT = now;
    if (!gameOver) platformPhysicsStep(dt);
    platformDraw();
    updateReadouts();
    // Music signals (HP, monsters etc.)
    pushMusicSignals();
    // World tick (CA) — slower than physics, for ambient drift.
    if (!PURE_MODE && !gameOver) {
      ticksSinceWorld++;
      if (ticksSinceWorld >= platformState.worldTickFrames) {
        ticksSinceWorld = 0;
        tickPactRule();
      }
    }
    platformRaf = requestAnimationFrame(platformFrame);
  }

  // Platform-mode input: stateful key tracking + edge-triggered jump.
  document.addEventListener('keydown', function (ev) {
    if (MODE !== 'platform') return;
    if (gameOver) {
      if (ev.key === 'r' || ev.key === 'R') {
        if (platformRaf) cancelAnimationFrame(platformRaf);
        platformRaf = null;
        init();
        ev.preventDefault();
      }
      return;
    }
    if (ev.key === 'a' || ev.key === 'A' || ev.key === 'ArrowLeft')  { platformKeys.left  = true; ev.preventDefault(); }
    if (ev.key === 'd' || ev.key === 'D' || ev.key === 'ArrowRight') { platformKeys.right = true; ev.preventDefault(); }
    if (ev.key === ' ' || ev.key === 'Space' || ev.key === 'w' || ev.key === 'W' || ev.key === 'ArrowUp') {
      if (!platformKeys.jump) jumpPressed = true;
      platformKeys.jump = true; ev.preventDefault();
    }
    if (ev.key === 'f' || ev.key === 'F') {
      // Fire horizontally in lastDir, range 4 cells.
      if (player.hasShotgun && player.ammo > 0) {
        player.ammo--;
        var fdir = player.lastDir === 1 ? 1 : -1;
        var hitX = player.x, hitY = player.y;
        for (var step = 1; step <= 4; step++) {
          var xx = Math.floor(player.x + fdir * step);
          var yy = Math.floor(player.y);
          if (platformIsWall(xx, yy)) {
            if (DESTRUCT_W2) {
              var cx_ = ((xx % GRID) + GRID) % GRID;
              if (yy >= 0 && yy < GRID && get(cx_, yy) === 2) set(cx_, yy, 0);
            }
            hitX = xx + 0.5; hitY = yy + 0.5; break;
          }
          for (var i = 0; i < monsters.length; i++) {
            var m = monsters[i];
            if (!m.alive) continue;
            if (Math.abs(m.x - (xx + 0.5)) < 0.6 && Math.abs(m.y - player.y) < 0.7) {
              m.alive = false;
              monsters.splice(i, 1);
              hitX = m.x; hitY = m.y;
              i = -1; step = 99;
              break;
            }
          }
          hitX = xx + 0.5; hitY = yy + 0.5;
        }
        fireFlash = { fromX: player.x, fromY: player.y,
                       toX: hitX, toY: hitY, framesLeft: 8 };
      }
      ev.preventDefault();
    }
  });
  document.addEventListener('keyup', function (ev) {
    if (MODE !== 'platform') return;
    if (ev.key === 'a' || ev.key === 'A' || ev.key === 'ArrowLeft')  platformKeys.left  = false;
    if (ev.key === 'd' || ev.key === 'D' || ev.key === 'ArrowRight') platformKeys.right = false;
    if (ev.key === ' ' || ev.key === 'Space' || ev.key === 'w' || ev.key === 'W' || ev.key === 'ArrowUp') {
      platformKeys.jump = false;
    }
  });

  // ─── Music wiring ──────────────────────────────────────────
  // DoomMusic is optional — if music.js wasn't loaded the runtime
  // still works.  When loaded, give it this game's component rule so
  // the same CA that drives the world drives the soundtrack.
  function pushMusicSignals () {
    if (!window.DoomMusic || !window.DoomMusic.isOn ||
        !window.DoomMusic.isOn() || !player) return;
    // Count walls adjacent to the player (0..6).
    var wallAdj = 0;
    for (var d = 0; d < 6; d++) {
      var nb = neighbourCoord(player.x, player.y, d);
      var cell = get(nb[0], nb[1]);
      var isWall = (MODE === 'overlay') ? (cell >= WALL_THRESH) : (cell === WALL);
      if (isWall) wallAdj++;
    }
    // Nearest monster distance + monsters-in-viewport count.
    var nearest = 1e9, inView = 0, half = 7;
    var arr = (MODE === 'overlay')
      ? monsters.filter(function (m) { return m.alive; })
      : monsters;
    for (var i = 0; i < arr.length; i++) {
      var m = arr[i];
      var d2 = hexDist(player.x, player.y, m.x, m.y);
      if (d2 < nearest) nearest = d2;
      if (d2 <= half) inView++;
    }
    window.DoomMusic.updateSignals({
      hp: player.hp, ammo: player.ammo,
      hasShotgun: player.hasShotgun,
      wallAdj: wallAdj,
      nearestMonsterDist: nearest,
      monstersInView: inView,
    });
  }

  if (window.DoomMusic && payload.rules_hex) {
    var ruleBase = COMPONENT * RULE_SIZE;
    var ruleSlice = rulesFlat.subarray(ruleBase, ruleBase + RULE_SIZE);
    window.DoomMusic.setRuleTable(ruleSlice);
    if (payload.music_style_idx != null) {
      window.DoomMusic.setStyleIndex(payload.music_style_idx);
    }
  }
  // 'm' toggles music, 'v' cycles style.  Persisted in localStorage
  // so the listening choice carries across sessions on the same browser.
  var MUSIC_PREF_KEY = 'doom_ca.music_on';
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'm' || ev.key === 'M') {
      if (!window.DoomMusic) return;
      var on = window.DoomMusic.toggle();
      try { localStorage.setItem(MUSIC_PREF_KEY, on ? '1' : '0'); } catch (e) {}
      var s = document.getElementById('dc-music');
      if (s) s.textContent = on
        ? '♪ ' + window.DoomMusic.getStyleName()
        : '♪ off';
      ev.preventDefault();
    } else if (ev.key === 'v' || ev.key === 'V') {
      if (!window.DoomMusic || !window.DoomMusic.isOn()) return;
      window.DoomMusic.cycleStyle();
      var s2 = document.getElementById('dc-music');
      if (s2) s2.textContent = '♪ ' + window.DoomMusic.getStyleName();
      ev.preventDefault();
    }
  });
  // Auto-start if user previously had music on.  Browsers gate
  // AudioContext on a user gesture, so this won't actually play
  // until the user presses a key — which they will, to play the game.
  try {
    if (localStorage.getItem(MUSIC_PREF_KEY) === '1' && window.DoomMusic) {
      // Delay actual start until first keydown; just mark intent.
      var armed = false;
      var armer = function () {
        if (armed) return; armed = true;
        window.DoomMusic.start();
        var s3 = document.getElementById('dc-music');
        if (s3) s3.textContent = '♪ ' + window.DoomMusic.getStyleName();
        document.removeEventListener('keydown', armer);
      };
      document.addEventListener('keydown', armer);
    }
  } catch (e) {}

  // Hook signal update into afterMove via monkey-patch (afterMove is
  // a local, so we tap via wrapping playerMove/wait/fire).  Simplest:
  // call pushMusicSignals at the top of the keydown handler queue.
  document.addEventListener('keydown', function () {
    setTimeout(pushMusicSignals, 0);
  });

  init();
})();

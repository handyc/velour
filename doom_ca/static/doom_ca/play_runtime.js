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
  };
  var noteEl = document.getElementById('dc-mode-note');
  if (noteEl) {
    noteEl.textContent =
      (MODE_NOTES[MODE] || '') +
      (PURE_MODE ? '  · pure mode (no pact-rule wait ticks).' : '');
  }

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

  var world, swap, generation, turn, player, monsters, gameOver;
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
    var edge = Math.max(240, Math.min(availW, availH));
    edge = Math.floor(edge);
    canvas.width  = edge;
    canvas.height = edge;
    canvas.style.width  = edge + 'px';
    canvas.style.height = edge + 'px';
    CELL_PX = Math.floor(edge / VIEW);
    H_STEP  = CELL_PX;
    V_STEP  = CELL_PX * 0.85;
  }
  recomputeRenderMetrics();
  window.addEventListener('resize', function () {
    recomputeRenderMetrics();
    if (player) draw();
  });

  var palette = payload.palette;
  function isPerComponent (p) { return Array.isArray(p[0][0]); }
  var componentPalette = isPerComponent(palette) ? palette[COMPONENT] : palette;
  var COL_WALL    = 'rgb(' + componentPalette[3].join(',') + ')';
  var COL_WALL_DK = 'rgb(' + componentPalette[2].join(',') + ')';
  var COL_GROUND  = '#1a1a1a';
  var COL_PLAYER  = '#58a6ff';
  var COL_MONSTER = '#f85149';
  var COL_PLAYER_HALO = 'rgba(88,166,255,0.18)';

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
        if (!autoFireAt(nx, ny)) player.hp -= 30;
        hit.alive = false;
      }
      player.x = nx; player.y = ny;
      if (targetIdx === keyIdx) { player.hasKey = true; keyIdx = -1; }
      pickupAt(targetIdx);
      if (targetIdx === exitIdx) { gameOver = 'won'; }
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
        if (!autoFireAt(target[0], target[1])) player.hp -= 30;
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
        if (!autoFireAt(target[0], target[1])) player.hp -= 30;
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

  function playerWait () { if (!gameOver) afterMove(); }

  function playerFire () {
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
      if (MODE === 'overlay') {
        if (isWallForOverlay(get(x, y))) break;
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
        if (!autoFireAt(nb[0], nb[1])) player.hp -= 10;
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
      if (isWallForOverlay(get(player.x, player.y))) gameOver = 'lost';
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
    if (player.hp <= 0) gameOver = 'lost';
    if (!gameOver && player.y * GRID + player.x === exitIdx) gameOver = 'won';
    draw(); updateReadouts();
  }

  function checkGameOver_singleRule () {
    if (get(player.x, player.y) !== PLAYER) {
      gameOver = 'lost';
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
          if (!autoFireAt(m.x, m.y)) player.hp -= 30;
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
        if (MODE === 'overlay') {
          fill = (cell >= WALL_THRESH)
            ? (cell === 3 ? COL_WALL : COL_WALL_DK)
            : COL_GROUND;
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

    var mDrawList = (MODE === 'overlay')
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
    setText('dc-mleft',
      (MODE === 'overlay')
        ? monsters.filter(function (m) { return m.alive; }).length
        : monsters.length);
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
        s.innerHTML = '<span class="game-over">— you died.</span>';
      } else if (gameOver === 'won') {
        s.innerHTML = '<span class="you-win">— reached the exit. ' + hp + ' HP remaining.</span>';
      } else {
        s.textContent = '';
      }
    }
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

  document.addEventListener('keydown', function (ev) {
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
    var k = ev.key.length === 1 ? ev.key.toUpperCase() : ev.key;
    var dir = cardinalToHex(k);
    if (dir >= 0) { playerMove(dir); ev.preventDefault(); }
  });
  canvas.tabIndex = 0;
  canvas.focus();

  init();
})();

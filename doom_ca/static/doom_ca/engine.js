// doom_ca/engine.js — pure-JS rule + CA tick + simulation engine.
//
// Loaded by both the play page (live game) and the evolve page
// (headless GA simulator).  No DOM access here.  All state passed
// explicitly so the same code can run in worker threads later.

(function (global) {
  'use strict';

  var RULE_SIZE = 16384;
  var GROUND = 0, WALL = 1, PLAYER = 2, MONSTER = 3;

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
  function seedGrid (byteSeed, gridSide) {
    var nxt = makeXoshiro(byteSeed);
    var g = new Uint8Array(gridSide * gridSide);
    for (var i = 0; i < g.length; i += 4) {
      var r = nxt();
      g[i] = r & 3;
      if (i+1 < g.length) g[i+1] = (r >> 2) & 3;
      if (i+2 < g.length) g[i+2] = (r >> 4) & 3;
      if (i+3 < g.length) g[i+3] = (r >> 6) & 3;
    }
    return g;
  }

  // ── Rule builders for mode-driven worlds ──────────────────────
  function unpackKey (k) {
    return {
      s: (k >> 12) & 3,
      n: [(k>>10)&3, (k>>8)&3, (k>>6)&3, (k>>4)&3, (k>>2)&3, k&3]
    };
  }

  // Shift rule for direction d: each cell takes its d-direction
  // neighbour, except player anchored, walls halt adjacent to player,
  // and source==PLAYER yields GROUND (carving trail).
  function buildShiftRule (d) {
    var t = new Uint8Array(RULE_SIZE);
    for (var k = 0; k < RULE_SIZE; k++) {
      var u = unpackKey(k);
      if (u.s === PLAYER) { t[k] = PLAYER; continue; }
      if (u.s === WALL) {
        var blocked = false;
        for (var i = 0; i < 6; i++) if (u.n[i] === PLAYER) { blocked = true; break; }
        if (blocked) { t[k] = WALL; continue; }
      }
      if (u.n[d] === PLAYER) { t[k] = GROUND; continue; }
      t[k] = u.n[d];
    }
    return t;
  }

  function buildScentRule () {
    var t = new Uint8Array(RULE_SIZE);
    for (var k = 0; k < RULE_SIZE; k++) {
      var u = unpackKey(k);
      if (u.s === PLAYER) { t[k] = PLAYER; continue; }
      if (u.s === WALL)   { t[k] = WALL;   continue; }
      var hM = 0, hP = 0, hG = 0, hW = 0;
      for (var i = 0; i < 6; i++) {
        if (u.n[i] === MONSTER) hM++;
        else if (u.n[i] === PLAYER) hP++;
        else if (u.n[i] === GROUND) hG++;
        else if (u.n[i] === WALL)   hW++;
      }
      if (u.s === MONSTER) {
        if (hP) { t[k] = MONSTER; continue; }
        if (hG === 0 && hM <= 1) { t[k] = MONSTER; continue; }
        t[k] = GROUND;
        continue;
      }
      // GROUND
      if (hM >= 1 && (hP || hG >= 2)) { t[k] = MONSTER; continue; }
      t[k] = GROUND;
    }
    return t;
  }

  // Evolved rule: base pact rule + per-key patches.
  function buildEvolvedRule (baseRule) {
    var t = new Uint8Array(baseRule);
    for (var k = 0; k < RULE_SIZE; k++) {
      var u = unpackKey(k);
      if (u.s === PLAYER) { t[k] = PLAYER; continue; }
      if (u.s === MONSTER) {
        var pAdj = false;
        for (var i = 0; i < 6; i++) if (u.n[i] === PLAYER) pAdj = true;
        if (pAdj) { t[k] = MONSTER; continue; }
      }
      if (u.s === WALL) {
        var nw = 0;
        for (var j = 0; j < 6; j++) if (u.n[j] === WALL) nw++;
        if (nw >= 2) t[k] = WALL;
        else if (nw === 0) t[k] = GROUND;
      }
      if (u.s === GROUND) {
        var pAdj2 = false;
        for (var i = 0; i < 6; i++) if (u.n[i] === PLAYER) pAdj2 = true;
        if (pAdj2) t[k] = WALL;
      }
    }
    return t;
  }

  // ── Hex neighbour offset (offset-r, odd rows shifted) ─────────
  function neighbourCoord (x, y, d, side) {
    var shift = y & 1;
    var dx = [shift, 1, shift, -1 + shift, -1, -1 + shift][d];
    var dy = [-1, 0, 1, 1, 0, -1][d];
    return [(x + dx + side) % side, (y + dy + side) % side];
  }
  function hexDist (ax, ay, bx, by, side) {
    var dx = bx - ax;
    if (dx >  side / 2) dx -= side;
    if (dx < -side / 2) dx += side;
    var dy = by - ay;
    if (dy >  side / 2) dy -= side;
    if (dy < -side / 2) dy += side;
    return Math.max(Math.abs(dx), Math.abs(dy), Math.abs(dx + dy));
  }

  // ── Single tick of a rule table over a grid ───────────────────
  function tickRule (world, swap, side, ruleTable) {
    for (var y = 0; y < side; y++) {
      var sh = y & 1;
      var tlx_off = -1 + sh, brx_off = 0 + sh;
      var yU = (y - 1 + side) % side;
      var yD = (y + 1) % side;
      for (var x = 0; x < side; x++) {
        var idx = y * side + x;
        var self_ = world[idx];
        var xL = (x - 1 + side) % side;
        var xR = (x + 1) % side;
        var xTL = (x + tlx_off + side) % side;
        var xBR = (x + brx_off + side) % side;
        var n0 = world[yU * side + xBR];
        var n1 = world[y  * side + xR];
        var n2 = world[yD * side + xBR];
        var n3 = world[yD * side + xTL];
        var n4 = world[y  * side + xL];
        var n5 = world[yU * side + xTL];
        var key = (self_ << 12) | (n0 << 10) | (n1 << 8) | (n2 << 6)
                | (n3 << 4) | (n4 << 2) | n5;
        swap[idx] = ruleTable[key];
      }
    }
    return swap;   // caller swaps buffers
  }

  // ── Mulberry32 — small, fast, reproducible RNG used by sim AI ──
  function makeRng (seedU32) {
    var s = seedU32 >>> 0;
    return function () {
      s = (s + 0x6D2B79F5) >>> 0;
      var t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 0x100000000;
    };
  }

  // ── Game simulation (headless) ────────────────────────────────
  // Runs maxTurns of a doom_ca config and returns metrics.
  // Player AI: weighted random valid step, slight bias away from the
  // nearest visible monster (gives a "reasonable but mortal" agent).
  function simulateGame (gene, opts) {
    opts = opts || {};
    var maxTurns = opts.maxTurns || 60;
    var aiSeed   = opts.aiSeed   || 1;
    var side     = gene.component_grid;
    var rng      = makeRng(aiSeed);

    // Initialise the grid: pact rule + seed expansion → threshold to
    // ground/wall.  Then stomp centre as PLAYER, scatter monsters.
    var raw = seedGrid(gene.seed_byte, side);
    var world = new Uint8Array(side * side);
    for (var i = 0; i < raw.length; i++) {
      world[i] = (raw[i] >= gene.wall_threshold) ? WALL : GROUND;
    }
    var c = Math.floor(side / 2);
    world[c * side + c] = PLAYER;
    var player = {x: c, y: c};

    // Monsters: scatter via aiRng
    var placed = 0, attempts = 0;
    while (placed < gene.monster_count && attempts < gene.monster_count * 40) {
      attempts++;
      var mx = Math.floor(rng() * side);
      var my = Math.floor(rng() * side);
      if (world[my * side + mx] !== GROUND) continue;
      if (hexDist(mx, my, player.x, player.y, side) < 3) continue;
      world[my * side + mx] = MONSTER;
      placed++;
    }

    // Pre-build rule tables
    var baseRule = gene.rule;
    var shiftRules = null, scentRule = null, evolvedRule = null;
    if (gene.world_mode === 'shift') {
      shiftRules = [];
      for (var d = 0; d < 6; d++) shiftRules.push(buildShiftRule(d));
    } else if (gene.world_mode === 'scent') {
      scentRule = buildScentRule();
    } else if (gene.world_mode === 'evolved') {
      evolvedRule = buildEvolvedRule(baseRule);
    }

    var swap = new Uint8Array(side * side);
    var turn = 0, gameOver = null;
    var wallsBumped = 0, monstersSeenSet = new Set();
    var groundVisited = new Set();
    groundVisited.add(player.y * side + player.x);

    function get (x, y) { return world[((y + side) % side) * side + ((x + side) % side)]; }
    function setCell (x, y, v) { world[((y + side) % side) * side + ((x + side) % side)] = v; }

    function countMonsterCells () {
      var out = [];
      for (var y = 0; y < side; y++) {
        for (var x = 0; x < side; x++) {
          if (world[y * side + x] === MONSTER) out.push({x: x, y: y});
        }
      }
      return out;
    }

    function aiPickDirection () {
      // Candidate directions: all that don't lead into wall.  Pick
      // weighted: prefer increasing distance to nearest monster.
      var monsters = countMonsterCells();
      var nearest = null, nearestDist = 1e9;
      for (var m = 0; m < monsters.length; m++) {
        var d = hexDist(player.x, player.y, monsters[m].x, monsters[m].y, side);
        if (d < nearestDist) { nearestDist = d; nearest = monsters[m]; }
      }
      var candidates = [];
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(player.x, player.y, d, side);
        var cellState = get(nb[0], nb[1]);
        if (cellState === WALL) continue;
        // Weight: + further from nearest monster, − closer
        var w = 1;
        if (nearest) {
          var futureDist = hexDist(nb[0], nb[1], nearest.x, nearest.y, side);
          w += futureDist - nearestDist;
        }
        candidates.push({dir: d, weight: Math.max(0.1, w)});
      }
      if (!candidates.length) return -1;   // forced wait
      var totalW = 0;
      for (var i = 0; i < candidates.length; i++) totalW += candidates[i].weight;
      var r = rng() * totalW;
      for (var i = 0; i < candidates.length; i++) {
        r -= candidates[i].weight;
        if (r <= 0) return candidates[i].dir;
      }
      return candidates[candidates.length - 1].dir;
    }

    function moveOverlayMonsters () {
      // Greedy pursuit, same as live overlay mode.
      var monsters = countMonsterCells();
      for (var i = 0; i < monsters.length; i++) {
        var m = monsters[i];
        var best = -1, bestDist = 1e9, ties = [];
        for (var d = 0; d < 6; d++) {
          var nb = neighbourCoord(m.x, m.y, d, side);
          var cellState = get(nb[0], nb[1]);
          if (cellState === WALL || cellState === MONSTER) continue;
          var dist = hexDist(nb[0], nb[1], player.x, player.y, side);
          if (dist < bestDist) { bestDist = dist; best = d; ties = [d]; }
          else if (dist === bestDist) ties.push(d);
        }
        if (best >= 0) {
          var pick = ties[Math.floor(rng() * ties.length)];
          var dest = neighbourCoord(m.x, m.y, pick, side);
          setCell(m.x, m.y, GROUND);
          if (dest[0] === player.x && dest[1] === player.y) {
            gameOver = 'lost';
          } else {
            setCell(dest[0], dest[1], MONSTER);
          }
        }
      }
    }

    // Main loop
    while (turn < maxTurns && !gameOver) {
      // Track monsters seen in viewport.
      var monsters = countMonsterCells();
      var half = 7;
      for (var i = 0; i < monsters.length; i++) {
        var dx = monsters[i].x - player.x;
        if (dx >  side / 2) dx -= side; if (dx < -side / 2) dx += side;
        var dy = monsters[i].y - player.y;
        if (dy >  side / 2) dy -= side; if (dy < -side / 2) dy += side;
        if (Math.abs(dx) <= half && Math.abs(dy) <= half) {
          monstersSeenSet.add(monsters[i].y * side + monsters[i].x);
        }
      }
      if (monsters.length === 0) { gameOver = 'won'; break; }

      var dir = aiPickDirection();
      if (dir < 0) {
        wallsBumped++;
        // Wait (no movement); still progress world.
      } else {
        var target = neighbourCoord(player.x, player.y, dir, side);
        if (gene.world_mode === 'overlay') {
          var occ = get(target[0], target[1]);
          if (occ >= gene.wall_threshold) { wallsBumped++; }
          else {
            // Check monster collision
            var hit = monsters.find(function (m) {
              return m.x === target[0] && m.y === target[1]; });
            if (hit) gameOver = 'lost';
            player.x = target[0]; player.y = target[1];
            groundVisited.add(player.y * side + player.x);
          }
        } else if (gene.world_mode === 'shift') {
          var occ = get(target[0], target[1]);
          if (occ === WALL) { wallsBumped++; }
          else {
            if (occ === MONSTER) gameOver = 'lost';
            // Apply shift; player stays at centre
            var tmp = tickRule(world, swap, side, shiftRules[dir]);
            world = tmp === swap ? swap : world;
            var tmp2 = world; world = swap; swap = tmp2;
            setCell(player.x, player.y, PLAYER);
          }
        } else {
          // scent / evolved: swap player with target then run rule
          var occ = get(target[0], target[1]);
          if (occ === WALL) { wallsBumped++; }
          else {
            if (occ === MONSTER) gameOver = 'lost';
            setCell(player.x, player.y, GROUND);
            setCell(target[0], target[1], PLAYER);
            player.x = target[0]; player.y = target[1];
            groundVisited.add(player.y * side + player.x);
          }
        }
      }
      // World tick — mode-specific
      if (gene.world_mode === 'overlay') {
        if (gene.world_mode === 'overlay' && !gene.pure_mode) {
          // Run pact rule (overlay always ticks pact rule)
          tickRule(world, swap, side, baseRule);
          var tmp = world; world = swap; swap = tmp;
        }
        moveOverlayMonsters();
      } else if (gene.world_mode === 'shift') {
        if (!gene.pure_mode) {
          tickRule(world, swap, side, baseRule);
          var tmp = world; world = swap; swap = tmp;
          setCell(player.x, player.y, PLAYER);
        }
      } else if (gene.world_mode === 'scent') {
        tickRule(world, swap, side, scentRule);
        var tmp = world; world = swap; swap = tmp;
      } else if (gene.world_mode === 'evolved') {
        tickRule(world, swap, side, evolvedRule);
        var tmp = world; world = swap; swap = tmp;
      }
      if (gene.world_mode !== 'overlay') {
        // In single-rule modes, monster_count post-tick is the count
        // of monster cells in the grid.  If the rule generated >>
        // monsters, that's a feature of the mode (not a kill metric).
      }
      // Game over detection
      if (gene.world_mode !== 'overlay') {
        if (get(player.x, player.y) !== PLAYER) gameOver = 'lost';
      }
      turn++;
    }

    return {
      survivedTurns: turn,
      maxTurns: maxTurns,
      survived: gameOver !== 'lost',
      won: gameOver === 'won',
      wallsBumped: wallsBumped,
      monstersSeen: monstersSeenSet.size,
      groundVisited: groundVisited.size,
    };
  }

  // ── Public API ────────────────────────────────────────────────
  global.DoomCAEngine = {
    RULE_SIZE: RULE_SIZE,
    GROUND: GROUND, WALL: WALL, PLAYER: PLAYER, MONSTER: MONSTER,
    seedGrid: seedGrid,
    buildShiftRule: buildShiftRule,
    buildScentRule: buildScentRule,
    buildEvolvedRule: buildEvolvedRule,
    tickRule: tickRule,
    simulateGame: simulateGame,
    makeRng: makeRng,
    neighbourCoord: neighbourCoord,
    hexDist: hexDist,
  };
})(typeof window !== 'undefined' ? window : globalThis);

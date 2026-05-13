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

  // ── Level placement: BFS spawn → exit, door, key, items ───────
  // Returns {items: Map<cellIdx,{type}>, exitIdx, doorIdx?, keyIdx?}.
  // Items don't change CA cell values — they live in an overlay
  // layer (same trick that player+monsters use).  Failure to find
  // a viable exit returns null and the level is unwinnable.
  function placeLevel (gene, side, world, spawnX, spawnY, rng) {
    var n = side * side;
    function bfs (excludeIdx) {
      var dist = new Int32Array(n);
      var parent = new Int32Array(n);
      for (var i = 0; i < n; i++) { dist[i] = -1; parent[i] = -1; }
      var queue = [spawnY * side + spawnX];
      dist[queue[0]] = 0;
      var qh = 0;
      while (qh < queue.length) {
        var idx = queue[qh++];
        var x = idx % side, y = (idx / side) | 0;
        for (var dir = 0; dir < 6; dir++) {
          var nb = neighbourCoord(x, y, dir, side);
          var nidx = nb[1] * side + nb[0];
          if (world[nidx] === WALL) continue;
          if (dist[nidx] !== -1) continue;
          if (nidx === excludeIdx) continue;
          dist[nidx] = dist[idx] + 1;
          parent[nidx] = idx;
          queue.push(nidx);
        }
      }
      return { dist: dist, parent: parent };
    }
    var bfs1 = bfs(-1);
    var maxD = 0, exitIdx = -1;
    for (var i = 0; i < n; i++) {
      if (bfs1.dist[i] > maxD) { maxD = bfs1.dist[i]; exitIdx = i; }
    }
    if (exitIdx < 0 || maxD < 4) return null;

    var doorIdx = null, keyIdx = null;
    if (gene.door_count) {
      var path = [];
      var cur = exitIdx;
      while (cur !== -1) { path.push(cur); cur = bfs1.parent[cur]; }
      path.reverse();
      if (path.length >= 6) {
        doorIdx = path[Math.floor(path.length / 2)];
        var bfs2 = bfs(doorIdx);
        var keyMaxD = 0, keyCand = -1;
        for (var i = 0; i < n; i++) {
          if (i === doorIdx || i === exitIdx) continue;
          if (i === spawnY * side + spawnX) continue;
          if (bfs2.dist[i] > keyMaxD) { keyMaxD = bfs2.dist[i]; keyCand = i; }
        }
        if (keyCand >= 0) keyIdx = keyCand;
        else doorIdx = null;
      }
    }

    var items = {};
    var occupied = {};
    occupied[exitIdx] = 1; occupied[spawnY * side + spawnX] = 1;
    if (doorIdx !== null) { occupied[doorIdx] = 1; occupied[keyIdx] = 1; }
    var candidates = [];
    for (var i = 0; i < n; i++) {
      if (bfs1.dist[i] > 1 && !occupied[i]) candidates.push(i);
    }
    for (var i = candidates.length - 1; i > 0; i--) {
      var j = Math.floor(rng() * (i + 1));
      var t = candidates[i]; candidates[i] = candidates[j]; candidates[j] = t;
    }
    var cIdx = 0;
    function placeOnce (type, count) {
      for (var k = 0; k < count && cIdx < candidates.length; k++) {
        items[candidates[cIdx++]] = { type: type };
      }
    }
    // One shotgun always — without it, fire is impossible.  Skip if
    // there's not enough room for everything; medkits matter more.
    // Allow gene.shotgun_count to gate weapon presence — archetypes
    // like Pacman-style want a weaponless level.
    var shotgunCount = (gene.shotgun_count != null) ? gene.shotgun_count : 1;
    placeOnce('shotgun', shotgunCount);
    placeOnce('medkit', gene.health_pack_count || 0);
    placeOnce('ammo',   gene.ammo_pack_count   || 0);

    // ── Layout-shape metrics (computed once, surfaced to fitness) ──
    // openness:    reachable_cells / total_cells.   Larger = more open.
    // corridorWidth: mean non-wall neighbours per reachable ground
    //   cell, divided by 6 (max).  Tight tunnels score low, wide
    //   chambers score high.
    var reachable = 0;
    var neighbourSum = 0, neighbourCells = 0;
    for (var i = 0; i < n; i++) {
      if (bfs1.dist[i] < 0) continue;
      reachable++;
      var x = i % side, y = (i / side) | 0;
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(x, y, d, side);
        if (world[nb[1] * side + nb[0]] !== WALL) neighbourSum++;
      }
      neighbourCells++;
    }
    var openness = reachable / n;
    var corridorWidth = neighbourCells > 0
      ? (neighbourSum / neighbourCells) / 6 : 0;

    return { items: items, exitIdx: exitIdx,
             doorIdx: doorIdx, keyIdx: keyIdx,
             openness: openness, corridorWidth: corridorWidth };
  }

  // BFS pathfinder used by the AI to walk toward a goal cell.
  // Returns the next direction (0..5) to step, or -1 if unreachable.
  function pathStep (world, side, fromX, fromY, goalIdx, doorIdx, hasKey) {
    var n = side * side;
    var goalX = goalIdx % side, goalY = (goalIdx / side) | 0;
    var dist = new Int32Array(n);
    var fromDir = new Int8Array(n);
    for (var i = 0; i < n; i++) { dist[i] = -1; fromDir[i] = -1; }
    var queue = [goalY * side + goalX];
    dist[queue[0]] = 0;
    var qh = 0;
    while (qh < queue.length) {
      var idx = queue[qh++];
      if (idx === fromY * side + fromX) break;
      var x = idx % side, y = (idx / side) | 0;
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(x, y, d, side);
        var nidx = nb[1] * side + nb[0];
        if (dist[nidx] !== -1) continue;
        var cell = world[nidx];
        // Walls block unless this is the door cell + AI has key.
        if (cell === WALL) continue;
        if (nidx === doorIdx && !hasKey) continue;
        // Monsters as soft obstacle — pass but penalise (handled at
        // step-selection time, not here; here we just allow it).
        dist[nidx] = dist[idx] + 1;
        // Reverse the direction: from idx we walked direction d to
        // reach nidx, so when stepping FROM nidx → idx the direction
        // is (d + 3) % 6 (opposite).
        fromDir[nidx] = (d + 3) % 6;
        queue.push(nidx);
      }
    }
    var startIdx = fromY * side + fromX;
    if (dist[startIdx] < 0) return -1;
    return fromDir[startIdx];
  }

  // ── Game simulation (headless) ────────────────────────────────
  // Runs maxTurns of a doom_ca config and returns metrics.
  // Player AI: pathfinds toward the highest-priority goal (medkit if
  // low HP, shotgun if unarmed, key if door blocks, exit otherwise);
  // fires the shotgun at adjacent monsters when ammo + has_shotgun;
  // falls back to weighted-random retreat if no path or no goal.
  function simulateGame (gene, opts) {
    opts = opts || {};
    // Platform-mode genes use the overlay simulator for headless
    // GA fitness — same world layout, just different player physics
    // (gravity vs hex-step) which doesn't change the fitness signals
    // we care about (HP at exit, completion, openness, etc.).
    if (gene.world_mode === 'platform') {
      gene = Object.assign({}, gene, { world_mode: 'overlay' });
    }
    var maxTurns = opts.maxTurns || 60;
    var aiSeed   = opts.aiSeed   || 1;
    var side     = gene.component_grid;
    var rng      = makeRng(aiSeed);
    // Independent RNG for item placement so it's stable per gene
    // regardless of which sim # this is.  Same seed_byte → same level.
    var placeRng = makeRng((gene.seed_byte * 2654435761) >>> 0);

    // Initialise the grid: pact rule + seed expansion → threshold to
    // ground/wall.  Then stomp centre as PLAYER, scatter monsters.
    var raw = seedGrid(gene.seed_byte, side);
    var world = new Uint8Array(side * side);
    for (var i = 0; i < raw.length; i++) {
      world[i] = (raw[i] >= gene.wall_threshold) ? WALL : GROUND;
    }
    var c = Math.floor(side / 2);
    world[c * side + c] = GROUND;   // ensure spawn is walkable
    var player = {x: c, y: c, hp: 100, ammo: 0,
                  hasShotgun: false, hasKey: false, lastDir: 1};

    // Place items + door + exit before stamping player or monsters.
    var level = placeLevel(gene, side, world, c, c, placeRng);
    if (!level) {
      // Unwinnable layout — return early with a hard-fail signal so
      // GA fitness can give it zero.
      return {
        survivedTurns: 0, maxTurns: maxTurns,
        survived: false, won: false,
        wallsBumped: 0, monstersSeen: 0, groundVisited: 0,
        completed: false, timeToExit: 0,
        hpAtExit: 0, itemsCollected: 0, monstersKilled: 0,
        unwinnable: true,
      };
    }
    var items = level.items;          // mutable: drop entries on pickup
    var doorIdx = level.doorIdx;
    var keyIdx  = level.keyIdx;
    var exitIdx = level.exitIdx;
    var doorOpen = false;             // becomes true once unlocked
    var levelOpenness      = level.openness      || 0;
    var levelCorridorWidth = level.corridorWidth || 0;

    world[c * side + c] = PLAYER;

    // Monsters: scatter via aiRng, avoiding spawn + items + exit + key.
    var placed = 0, attempts = 0;
    while (placed < gene.monster_count && attempts < gene.monster_count * 40) {
      attempts++;
      var mx = Math.floor(rng() * side);
      var my = Math.floor(rng() * side);
      var midx = my * side + mx;
      if (world[midx] !== GROUND) continue;
      if (hexDist(mx, my, player.x, player.y, side) < 3) continue;
      if (midx === exitIdx) continue;
      if (midx === doorIdx) continue;
      if (midx === keyIdx)  continue;
      if (items[midx]) continue;
      world[midx] = MONSTER;
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
    var monstersKilled = 0, itemsCollected = 0;
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

    function chooseGoal () {
      // Priority: low HP → medkit; no shotgun → shotgun; door+no key
      // → key; else → exit.  If preferred type isn't on the map any
      // more, fall through to the next.
      function nearestOfType (type) {
        var best = -1, bestD = 1e9;
        for (var k in items) {
          if (items[k].type !== type) continue;
          var ix = (+k) % side, iy = ((+k) / side) | 0;
          var d = hexDist(player.x, player.y, ix, iy, side);
          if (d < bestD) { bestD = d; best = +k; }
        }
        return best;
      }
      if (player.hp <= 50) {
        var m = nearestOfType('medkit');
        if (m >= 0) return m;
      }
      if (!player.hasShotgun) {
        var s = nearestOfType('shotgun');
        if (s >= 0) return s;
      }
      if (player.ammo <= 1) {
        var a = nearestOfType('ammo');
        if (a >= 0) return a;
      }
      if (doorIdx !== null && !doorOpen && !player.hasKey) {
        return keyIdx;
      }
      return exitIdx;
    }

    function aiPickDirection () {
      // 1) If we have a shotgun + ammo and a monster is adjacent,
      //    fire instead of stepping (returned via the special action
      //    code 'F' encoded as -2).
      if (player.hasShotgun && player.ammo > 0) {
        for (var d = 0; d < 6; d++) {
          var nb = neighbourCoord(player.x, player.y, d, side);
          if (get(nb[0], nb[1]) === MONSTER) {
            player.lastDir = d;
            return -2;
          }
        }
      }
      // 2) Pathfind to current goal.
      var goal = chooseGoal();
      var dir = pathStep(world, side, player.x, player.y, goal,
                         doorOpen ? null : doorIdx, player.hasKey);
      if (dir >= 0) {
        // If the step lands us on a monster, refuse — fall back to
        // weighted random (we want the AI to avoid suicide rushes).
        var nb = neighbourCoord(player.x, player.y, dir, side);
        if (get(nb[0], nb[1]) !== MONSTER) return dir;
      }
      // 3) Weighted random with monster avoidance (legacy fallback).
      var monsters = countMonsterCells();
      var nearest = null, nearestDist = 1e9;
      for (var m = 0; m < monsters.length; m++) {
        var ds = hexDist(player.x, player.y, monsters[m].x, monsters[m].y, side);
        if (ds < nearestDist) { nearestDist = ds; nearest = monsters[m]; }
      }
      var candidates = [];
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(player.x, player.y, d, side);
        var cellState = get(nb[0], nb[1]);
        if (cellState === WALL) continue;
        var nidx = nb[1] * side + nb[0];
        if (nidx === doorIdx && !doorOpen && !player.hasKey) continue;
        var w = 1;
        if (nearest) {
          var fd = hexDist(nb[0], nb[1], nearest.x, nearest.y, side);
          w += fd - nearestDist;
        }
        candidates.push({dir: d, weight: Math.max(0.1, w)});
      }
      if (!candidates.length) return -1;
      var totalW = 0;
      for (var i = 0; i < candidates.length; i++) totalW += candidates[i].weight;
      var r = rng() * totalW;
      for (var i = 0; i < candidates.length; i++) {
        r -= candidates[i].weight;
        if (r <= 0) return candidates[i].dir;
      }
      return candidates[candidates.length - 1].dir;
    }

    function pickupAt (cellIdx) {
      var it = items[cellIdx];
      if (!it) return;
      if (it.type === 'medkit')  player.hp = Math.min(100, player.hp + 25);
      else if (it.type === 'ammo')    player.ammo += 3;
      else if (it.type === 'shotgun') player.hasShotgun = true;
      delete items[cellIdx];
      itemsCollected++;
    }

    function fireShotgun (dir) {
      // Walk up to 4 cells in direction dir; kill the first monster
      // we hit.  Costs 1 ammo whether or not we hit.
      if (player.ammo <= 0 || !player.hasShotgun) return false;
      player.ammo--;
      var x = player.x, y = player.y;
      for (var step = 0; step < 4; step++) {
        var nb = neighbourCoord(x, y, dir, side);
        x = nb[0]; y = nb[1];
        var cell = get(x, y);
        if (cell === WALL) {
          // Fragile wall: state-2 wall yields when DESTRUCT_WALL_2 is on.
          if (gene.destruct_wall_2 && raw[y * side + x] === 2) {
            setCell(x, y, GROUND);
            return true;
          }
          return false;
        }
        if (cell === MONSTER) {
          setCell(x, y, GROUND);
          monstersKilled++;
          return true;
        }
      }
      return false;
    }

    function meleeAdjacentMonsters () {
      // After every tick, every adjacent monster engages.  Shotgun +
      // ammo turns this into a reflexive kill (1 ammo each, no HP
      // lost).  Empty-handed or out of ammo, it's a bite (-10 HP).
      // In overlay mode, monster-walks-into-player is handled in
      // moveOverlayMonsters; this only fires in pure-CA modes.
      if (gene.world_mode === 'overlay') return;
      for (var d = 0; d < 6; d++) {
        var nb = neighbourCoord(player.x, player.y, d, side);
        if (get(nb[0], nb[1]) === MONSTER) {
          if (player.hasShotgun && player.ammo > 0) {
            player.ammo--;
          } else {
            player.hp -= 10;
          }
          setCell(nb[0], nb[1], GROUND);
          monstersKilled++;
        }
      }
    }

    function moveOverlayMonsters () {
      // Greedy pursuit, same as live overlay mode.  Walking onto the
      // player deals damage AND the monster dies in the collision
      // (mutual close-combat) — solves "monster sits adjacent forever
      // taking infinite hits" without making contact lethal.
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
            // Monster bit (or got blasted) — same point-blank rules.
            if (player.hasShotgun && player.ammo > 0) player.ammo--;
            else player.hp -= 30;
            monstersKilled++;
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
      // Goal-driven exit: if we're standing on the exit, we win.
      if (player.y * side + player.x === exitIdx) {
        gameOver = 'won';
        break;
      }

      var dir = aiPickDirection();
      if (dir === -2) {
        // Fire shotgun in player.lastDir (set by aiPickDirection).
        fireShotgun(player.lastDir);
      } else if (dir < 0) {
        wallsBumped++;
        // Wait (no movement); still progress world.
      } else {
        var target = neighbourCoord(player.x, player.y, dir, side);
        var targetIdx = target[1] * side + target[0];
        // Door check: blocked unless key in hand → consume key, open.
        if (targetIdx === doorIdx && !doorOpen) {
          if (player.hasKey) {
            doorOpen = true;
            player.hasKey = false;
            player.x = target[0]; player.y = target[1];
            groundVisited.add(targetIdx);
            player.lastDir = dir;
          } else {
            wallsBumped++;
          }
        } else if (gene.world_mode === 'overlay') {
          var occ = get(target[0], target[1]);
          if (occ >= gene.wall_threshold) { wallsBumped++; }
          else {
            var hit = monsters.find(function (m) {
              return m.x === target[0] && m.y === target[1]; });
            if (hit) {
              if (player.hasShotgun && player.ammo > 0) player.ammo--;
              else player.hp -= 30;
              monstersKilled++;
            }
            player.x = target[0]; player.y = target[1];
            groundVisited.add(targetIdx);
            player.lastDir = dir;
            // Key pickup
            if (targetIdx === keyIdx) {
              player.hasKey = true;
              keyIdx = null;
            }
            // Item pickup
            pickupAt(targetIdx);
            // Slip-ground: stepping onto a state-1 cell slides one more
            // step in the same direction if the next cell is open and
            // not a monster (a slide into a monster would be suicide).
            if (gene.slip_ground_1 && raw[targetIdx] === 1) {
              var sn = neighbourCoord(player.x, player.y, dir, side);
              var snIdx = sn[1] * side + sn[0];
              var snOcc = get(sn[0], sn[1]);
              if (snOcc < gene.wall_threshold && snOcc !== MONSTER
                  && (snIdx !== doorIdx || doorOpen)) {
                player.x = sn[0]; player.y = sn[1];
                groundVisited.add(snIdx);
                if (snIdx === keyIdx) { player.hasKey = true; keyIdx = null; }
                pickupAt(snIdx);
              }
            }
          }
        } else if (gene.world_mode === 'shift') {
          var occ = get(target[0], target[1]);
          if (occ === WALL) { wallsBumped++; }
          else {
            if (occ === MONSTER) {
              if (player.hasShotgun && player.ammo > 0) player.ammo--;
              else player.hp -= 30;
              monstersKilled++;
              setCell(target[0], target[1], GROUND);
            }
            // Apply shift; player stays at centre.  Items + door +
            // exit are world-anchored; they don't shift with the
            // visible scroll.  This is a deliberate simplification —
            // shift-mode levels effectively don't have items.
            var tmp = tickRule(world, swap, side, shiftRules[dir]);
            world = tmp === swap ? swap : world;
            var tmp2 = world; world = swap; swap = tmp2;
            setCell(player.x, player.y, PLAYER);
            player.lastDir = dir;
          }
        } else {
          // scent / evolved: swap player with target then run rule
          var occ = get(target[0], target[1]);
          if (occ === WALL) { wallsBumped++; }
          else {
            if (occ === MONSTER) {
              if (player.hasShotgun && player.ammo > 0) player.ammo--;
              else player.hp -= 30;
              monstersKilled++;
            }
            setCell(player.x, player.y, GROUND);
            setCell(target[0], target[1], PLAYER);
            player.x = target[0]; player.y = target[1];
            groundVisited.add(targetIdx);
            player.lastDir = dir;
            if (targetIdx === keyIdx) {
              player.hasKey = true;
              keyIdx = null;
            }
            pickupAt(targetIdx);
          }
        }
      }
      if (player.hp <= 0) { gameOver = 'lost'; break; }
      // Step onto exit immediately wins (catch case where exit is
      // reached on the same turn as a fire / item pickup).
      if (player.y * side + player.x === exitIdx) {
        gameOver = 'won';
        break;
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
      // Pure-CA modes: adjacent monsters bite after the tick.
      if (gene.world_mode === 'scent' || gene.world_mode === 'evolved') {
        meleeAdjacentMonsters();
      }
      // Game over detection — player cell overwritten = lost.
      if (gene.world_mode !== 'overlay' && gene.world_mode !== 'shift') {
        if (get(player.x, player.y) !== PLAYER) gameOver = 'lost';
      }
      if (player.hp <= 0) gameOver = 'lost';
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
      // Doom-mechanics signals for the GA:
      completed: gameOver === 'won',
      timeToExit: gameOver === 'won' ? turn : maxTurns,
      hpAtExit: gameOver === 'won' ? player.hp : 0,
      itemsCollected: itemsCollected,
      monstersKilled: monstersKilled,
      unwinnable: false,
      // Layout-shape signals (constant across sims for a given gene).
      openness:      levelOpenness,
      corridorWidth: levelCorridorWidth,
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
    placeLevel: placeLevel,
    pathStep: pathStep,
    makeRng: makeRng,
    neighbourCoord: neighbourCoord,
    hexDist: hexDist,
  };
})(typeof window !== 'undefined' ? window : globalThis);

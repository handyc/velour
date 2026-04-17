/* Casting: byte_model_tree_feedback_continuous — draw a fresh RANDOM
 * recurrent decision tree each tick, walk its trajectory, tally the
 * cycle-length distribution. Shows how boring random recurrent trees
 * over 1 memory bit really are.
 */
(function () {
  const MAX_STEPS = 40;
  const MAX_NODES = 15;   /* keep trees small */

  function buildRandom() {
    const nodes = [];
    function rec(depth) {
      if (depth >= 3 || nodes.length >= MAX_NODES - 2 || Math.random() < 0.3) {
        nodes.push({ leaf: true, v: Math.random() < 0.5 ? +1 : -1 });
        return nodes.length - 1;
      }
      const f = Math.floor(Math.random() * 4);
      const slot = nodes.length;
      nodes.push(null);
      const zc = rec(depth + 1);
      const oc = rec(depth + 1);
      nodes[slot] = { leaf: false, f, zc, oc };
      return slot;
    }
    const root = rec(0);
    return { nodes, root };
  }
  function evalTree(tree, feats) {
    let idx = tree.root;
    while (!tree.nodes[idx].leaf)
      idx = feats[tree.nodes[idx].f] ? tree.nodes[idx].oc : tree.nodes[idx].zc;
    return tree.nodes[idx].v;
  }

  function cycleLength(tree, drive, initMem) {
    let mem = initMem;
    const seen = new Map();
    for (let step = 0; step < MAX_STEPS; ++step) {
      const pos = step % drive.length;
      const [s0, s1, s2] = drive[pos];
      const feats = [s0, s1, s2, mem];
      const out = evalTree(tree, feats);
      const outBit = (out > 0) ? 1 : 0;
      const key = pos * 4 + mem * 2 + outBit;
      if (seen.has(key)) return step - seen.get(key);
      seen.set(key, step);
      mem = outBit;
    }
    return -1;
  }

  const DRIVES = {
    const: [[0,0,0]],
    toggle: [[0,0,0],[1,1,1]],
    gray:  [[0,0,0],[1,0,0],[0,1,0],[0,0,1],[1,1,0],[1,0,1],[0,1,1],[1,1,1]],
  };

  let timer = null;
  let totalTrees = 0;
  const cycleHist = { 1: 0, 2: 0, 3: 0, 4: 0, 8: 0, other: 0, none: 0 };
  let memUsedCount = 0;

  function isMemoryUsed(tree) {
    for (const n of tree.nodes) if (n && !n.leaf && n.f === 3) return true;
    return false;
  }

  function tick(emit) {
    const tree = buildRandom();
    const drive = DRIVES.gray;
    const c = cycleLength(tree, drive, 0);
    totalTrees++;
    if (isMemoryUsed(tree)) memUsedCount++;
    if (c < 0) cycleHist.none++;
    else if (cycleHist[c] !== undefined) cycleHist[c]++;
    else cycleHist.other++;

    const rows = [];
    const maxC = Math.max(...Object.values(cycleHist));
    for (const k of [1, 2, 3, 4, 8, 'other', 'none']) {
      const v = cycleHist[k];
      if (v === 0) continue;
      const w = maxC ? Math.max(1, Math.round(v / maxC * 30)) : 0;
      rows.push(`  ${String(k).padStart(6)}:  ${String(v).padStart(4)}  ${'#'.repeat(w)}`);
    }
    const memPct = (100 * memUsedCount / totalTrees).toFixed(1);
    const lines = [
      `random recurrent DTs over gray-code drive`,
      `trees walked:     ${totalTrees}`,
      `trees using mem:  ${memUsedCount}  (${memPct}%)`,
      ``,
      `cycle-length histogram:`,
      ...rows,
      ``,
      `most random trees collapse to length-1 (constant) or length-8`,
      `(the drive length). interesting 3- or 4-cycles are rare — you`,
      `need crafted trees, or more memory bits, to see them often.`,
    ];
    emit(lines.join('\n'));
  }

  function start(emit) {
    if (timer) return;
    totalTrees = 0; memUsedCount = 0;
    for (const k in cycleHist) cycleHist[k] = 0;
    emit('drawing random recurrent trees...');
    timer = setInterval(function () { tick(emit); }, 50);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  window.Casting_byte_model_tree_feedback_continuous = { start, stop };
})();

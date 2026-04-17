/* Casting: byte_model_tree_feedback — recurrent decision trees with one
 * memory bit (their own previous output fed in as an extra input).
 * Mirrors static/casting/sources/byte_model_tree_feedback.c.
 */
(function () {
  const MAX_STEPS = 40;

  function makeTree(name) {
    const t = { name, nodes: [], root: -1 };
    return t;
  }
  function leaf(t, v)             { t.nodes.push({ leaf: true,  v }); return t.nodes.length - 1; }
  function split(t, f, zc, oc)    { t.nodes.push({ leaf: false, f, zc, oc }); return t.nodes.length - 1; }
  function evalTree(t, feats) {
    let idx = t.root;
    while (!t.nodes[idx].leaf)
      idx = feats[t.nodes[idx].f] ? t.nodes[idx].oc : t.nodes[idx].zc;
    return t.nodes[idx].v;
  }

  function makeLatch() {
    const t = makeTree('latch(s0/s1/mem)');
    const p1 = leaf(t, +1), n1 = leaf(t, -1);
    const ho = leaf(t, +1), hn = leaf(t, -1);
    const hold    = split(t, 3, hn, ho);
    const s1True  = n1;
    const s1Branch= split(t, 1, hold, s1True);
    t.root        = split(t, 0, s1Branch, p1);
    return t;
  }
  function makeToggle() {
    const t = makeTree('toggle(¬mem)');
    const p = leaf(t, +1), n = leaf(t, -1);
    t.root = split(t, 3, p, n);
    return t;
  }
  function makeGuarded() {
    const t = makeTree('flip-if-s0 / hold');
    const p1 = leaf(t, +1), n1 = leaf(t, -1);
    const hold = split(t, 3, n1, p1);
    const p2 = leaf(t, +1), n2 = leaf(t, -1);
    const flip = split(t, 3, p2, n2);
    t.root = split(t, 0, hold, flip);
    return t;
  }
  function makeMajority() {
    const t = makeTree('maj(s0,s1,s2) — no mem');
    const mk = v => leaf(t, v);
    const l0a = mk(-1), l0b = mk(-1);
    const l0c = mk(-1), l0d = mk(+1);
    const l1a = mk(-1), l1b = mk(+1);
    const l1c = mk(+1), l1d = mk(+1);
    const b00 = split(t, 2, l0a, l0b);
    const b01 = split(t, 2, l0c, l0d);
    const b10 = split(t, 2, l1a, l1b);
    const b11 = split(t, 2, l1c, l1d);
    const a0  = split(t, 1, b00, b01);
    const a1  = split(t, 1, b10, b11);
    t.root    = split(t, 0, a0, a1);
    return t;
  }

  const DRIVES = [
    { name: 'const-000',   data: [[0,0,0]] },
    { name: 'alt-000-111', data: [[0,0,0],[1,1,1]] },
    { name: 'gray-walk',   data: [[0,0,0],[1,0,0],[0,1,0],[0,0,1],
                                   [1,1,0],[1,0,1],[0,1,1],[1,1,1]] },
  ];

  function walk(lines, tree, drive, initMem) {
    let mem = initMem;
    const seen = [];
    const history = [];
    let cycleStart = -1, cycleLen = -1;
    for (let step = 0; step < MAX_STEPS; ++step) {
      const pos = step % drive.data.length;
      const [s0, s1, s2] = drive.data[pos];
      const feats = [s0, s1, s2, mem];
      const out = evalTree(tree, feats);
      const outBit = (out > 0) ? 1 : 0;
      history.push({ step, s0, s1, s2, outBit });
      const key = pos * 4 + mem * 2 + outBit;
      const idx = seen.indexOf(key);
      if (idx >= 0) { cycleStart = idx; cycleLen = seen.length - idx; break; }
      seen.push(key);
      mem = outBit;
    }
    lines.push(`tree [${tree.name}]  drive [${drive.name}]  init mem=${initMem}`);
    const show = Math.min(history.length, 12);
    for (let i = 0; i < show; ++i) {
      const h = history[i];
      lines.push(`  t=${String(h.step).padStart(2)}  s=${h.s0}${h.s1}${h.s2}  out=${h.outBit}`);
    }
    if (cycleLen > 0)
      lines.push(`  cycle detected: length ${cycleLen} starting at step ${cycleStart}`);
    else
      lines.push(`  no cycle within ${MAX_STEPS} steps`);
    lines.push('');
  }

  function run() {
    const lines = [];
    lines.push('recurrent decision trees — feedback loop over 1 memory bit');
    lines.push('');
    const trees = [makeLatch(), makeToggle(), makeGuarded(), makeMajority()];
    for (const t of trees) for (const d of DRIVES) walk(lines, t, d, 0);
    lines.push('Observations:');
    lines.push('  - toggle produces a clean 2-cycle whenever mem feedback is wired.');
    lines.push('  - latch tracks sensors and holds state, but the behaviour is');
    lines.push('    fully decidable from a finite state graph (no richer dynamics).');
    lines.push('  - majority ignores memory entirely — output is determined by');
    lines.push('    the drive pattern alone (as expected).');
    lines.push('  - with 1 memory bit the reachable dynamics are a subset of 4-bit');
    lines.push('    state graphs. To get richer behaviour we would need either');
    lines.push('    multiple memory bits or composition of several feedback trees.');
    lines.push('  - this entry is marked RED — a substrate for future work,');
    lines.push('    not a working ML demonstration on its own.');
    return lines.join('\n');
  }

  window.Casting_byte_model_tree_feedback = { run };
})();

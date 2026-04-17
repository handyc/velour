/* Casting: byte_model_tree_induction — ID3 DT learner.
 * Mirrors static/casting/sources/byte_model_tree_induction.c.
 */
(function () {
  const N_FEATURES = 4;
  const N_SAMPLES  = 16;

  function entropy(samples, ix) {
    let pos = 0;
    for (const i of ix) if (samples[i].label > 0) pos++;
    const neg = ix.length - pos;
    if (pos === 0 || neg === 0) return 0;
    const p = pos / ix.length, q = neg / ix.length;
    return -p * Math.log(p) - q * Math.log(q);
  }

  function bestFeature(samples, ix, avail) {
    const base = entropy(samples, ix);
    let best = -1, bestGain = -1;
    for (let f = 0; f < N_FEATURES; ++f) {
      if (!avail[f]) continue;
      const z = [], o = [];
      for (const i of ix) (samples[i].features[f] ? o : z).push(i);
      let after = 0;
      if (z.length) after += z.length / ix.length * entropy(samples, z);
      if (o.length) after += o.length / ix.length * entropy(samples, o);
      const gain = base - after;
      if (gain > bestGain) { bestGain = gain; best = f; }
    }
    return best;
  }

  function makeBuilder() {
    const nodes = [];
    function leaf(v) { nodes.push({ leaf: true, value: v }); return nodes.length - 1; }
    function split(feat, zi, oi) {
      nodes.push({ leaf: false, feature: feat, zero: zi, one: oi });
      return nodes.length - 1;
    }
    return { nodes, leaf, split };
  }

  function majorityLabel(samples, ix) {
    let pos = 0;
    for (const i of ix) if (samples[i].label > 0) pos++;
    return pos >= ix.length - pos ? +1 : -1;
  }

  function buildDT(b, samples, ix, avail) {
    let pos = 0;
    for (const i of ix) if (samples[i].label > 0) pos++;
    if (pos === 0) return b.leaf(-1);
    if (pos === ix.length) return b.leaf(+1);
    let any = avail.some(v => v);
    if (!any) return b.leaf(majorityLabel(samples, ix));
    const f = bestFeature(samples, ix, avail);
    if (f < 0) return b.leaf(majorityLabel(samples, ix));
    const z = [], o = [];
    for (const i of ix) (samples[i].features[f] ? o : z).push(i);
    const newAvail = avail.slice(); newAvail[f] = 0;
    const slot = b.nodes.length;
    b.nodes.push(null);
    const zc = buildDT(b, samples, z, newAvail);
    const oc = buildDT(b, samples, o, newAvail);
    b.nodes[slot] = { leaf: false, feature: f, zero: zc, one: oc };
    return slot;
  }

  function dtEval(nodes, root, feats) {
    let idx = root;
    while (!nodes[idx].leaf)
      idx = feats[nodes[idx].feature] ? nodes[idx].one : nodes[idx].zero;
    return nodes[idx].value;
  }

  function generateSamples(table) {
    const s = [];
    for (let row = 0; row < N_SAMPLES; ++row) {
      const features = [];
      for (let f = 0; f < N_FEATURES; ++f)
        features.push((row >> (N_FEATURES - 1 - f)) & 1);
      s.push({ features, label: ((table >> row) & 1) ? +1 : -1 });
    }
    return s;
  }

  function countLeaves(nodes, root) {
    if (nodes[root].leaf) return 1;
    return countLeaves(nodes, nodes[root].zero) + countLeaves(nodes, nodes[root].one);
  }
  function treeDepth(nodes, root) {
    if (nodes[root].leaf) return 0;
    return 1 + Math.max(treeDepth(nodes, nodes[root].zero), treeDepth(nodes, nodes[root].one));
  }

  function printTree(nodes, idx, depth, axis, out) {
    const pad = '  '.repeat(depth);
    if (nodes[idx].leaf) {
      out.push(`${pad}${axis} leaf ${nodes[idx].value >= 0 ? '+1' : '-1'}`);
      return;
    }
    out.push(`${pad}${axis} split on x${nodes[idx].feature}`);
    printTree(nodes, nodes[idx].zero, depth + 1, '  0 →', out);
    printTree(nodes, nodes[idx].one,  depth + 1, '  1 →', out);
  }

  function runCase(lines, name, table) {
    const samples = generateSamples(table);
    const ix = samples.map((_, i) => i);
    const avail = [1,1,1,1];
    const b = makeBuilder();
    const root = buildDT(b, samples, ix, avail);
    let correct = 0;
    for (const s of samples)
      if (dtEval(b.nodes, root, s.features) === s.label) correct++;
    const leaves = countLeaves(b.nodes, root);
    const depth  = treeDepth(b.nodes, root);
    lines.push(`target ${name.padEnd(15)} acc ${String(correct).padStart(2)} / ${N_SAMPLES}   nodes=${String(b.nodes.length).padStart(2)}   leaves=${String(leaves).padStart(2)}   depth=${depth}`);
    printTree(b.nodes, root, 1, 'root:', lines);
    lines.push('');
  }

  const CASES = [
    { name: '4-MAJ (>=3)',    table: 0xe880 },
    { name: '4-threshold 2',  table: 0xfee8 },
    { name: '4-OR',           table: 0xfffe },
    { name: '4-AND',          table: 0x8000 },
    { name: '4-XOR (parity)', table: 0x6996 },
  ];

  function run() {
    const lines = [];
    lines.push('ID3 greedy induction over 4-input boolean targets (16 samples each)');
    lines.push('');
    for (const c of CASES) runCase(lines, c.name, c.table);
    lines.push('Observations:');
    lines.push('  - Threshold functions (MAJ, OR, AND) give large root-split gain;');
    lines.push('    induction produces small trees.');
    lines.push('  - Parity (XOR) gives zero gain at every feature; the induced');
    lines.push('    tree must consume every feature to separate all 16 rows.');
    lines.push('    DTs CAN fit it, they just cannot exploit it greedily.');
    return lines.join('\n');
  }

  window.Casting_byte_model_tree_induction = { run };
})();

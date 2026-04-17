/* Casting: byte_model_tree_forest — bagging with random subspaces.
 * Mirrors static/casting/sources/byte_model_tree_forest.c.
 */
(function () {
  const N_FEATURES = 4;
  const N_SAMPLES  = 16;
  const FOREST_SIZE = 21;
  const NOISE_FLIPS = 3;

  /* Tiny LCG so we get reproducible "random" behaviour per-run. */
  let rngState = 42;
  function rnd() {
    rngState = (rngState * 1103515245 + 12345) & 0x7fffffff;
    return rngState;
  }
  function rndRange(n) { return rnd() % n; }
  function rndReset(seed) { rngState = seed; }

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
  function bestFeatureRand(samples, ix, avail, maxFeat) {
    const cand = [];
    for (let f = 0; f < N_FEATURES; ++f) if (avail[f]) cand.push(f);
    if (!cand.length) return -1;
    for (let i = cand.length - 1; i > 0; --i) {
      const j = rndRange(i + 1);
      [cand[i], cand[j]] = [cand[j], cand[i]];
    }
    const keep = Math.min(cand.length, maxFeat);
    const subset = new Array(N_FEATURES).fill(0);
    for (let i = 0; i < keep; ++i) subset[cand[i]] = 1;
    return bestFeature(samples, ix, subset);
  }

  function majority(samples, ix) {
    let pos = 0;
    for (const i of ix) if (samples[i].label > 0) pos++;
    return pos >= ix.length - pos ? +1 : -1;
  }

  function build(nodes, samples, ix, avail, maxFeat) {
    let pos = 0;
    for (const i of ix) if (samples[i].label > 0) pos++;
    if (pos === 0)          { nodes.push({ leaf: true, v: -1 }); return nodes.length - 1; }
    if (pos === ix.length)  { nodes.push({ leaf: true, v: +1 }); return nodes.length - 1; }
    if (!avail.some(v => v)){ nodes.push({ leaf: true, v: majority(samples, ix) }); return nodes.length - 1; }
    const f = (maxFeat >= N_FEATURES)
      ? bestFeature(samples, ix, avail)
      : bestFeatureRand(samples, ix, avail, maxFeat);
    if (f < 0) { nodes.push({ leaf: true, v: majority(samples, ix) }); return nodes.length - 1; }
    const z = [], o = [];
    for (const i of ix) (samples[i].features[f] ? o : z).push(i);
    const na = avail.slice(); na[f] = 0;
    const slot = nodes.length;
    nodes.push(null);
    const zc = build(nodes, samples, z, na, maxFeat);
    const oc = build(nodes, samples, o, na, maxFeat);
    nodes[slot] = { leaf: false, f, zc, oc };
    return slot;
  }
  function evalTree(nodes, root, feats) {
    let idx = root;
    while (!nodes[idx].leaf)
      idx = feats[nodes[idx].f] ? nodes[idx].oc : nodes[idx].zc;
    return nodes[idx].v;
  }

  function generateClean(table) {
    const s = [];
    for (let row = 0; row < N_SAMPLES; ++row) {
      const features = [];
      for (let f = 0; f < N_FEATURES; ++f)
        features.push((row >> (N_FEATURES - 1 - f)) & 1);
      s.push({ features, label: ((table >> row) & 1) ? +1 : -1 });
    }
    return s;
  }
  function flipLabels(train, k) {
    const used = new Set();
    while (used.size < k) {
      const r = rndRange(N_SAMPLES);
      if (used.has(r)) continue;
      used.add(r);
      train[r] = Object.assign({}, train[r], { label: -train[r].label });
    }
    return used;
  }

  function runCase(lines, name, table) {
    const clean = generateClean(table);
    const train = clean.map(s => Object.assign({}, s));
    const flipped = flipLabels(train, NOISE_FLIPS);
    let flipMask = 0;
    for (const i of flipped) flipMask |= (1 << i);

    /* single tree */
    const singleNodes = [];
    const ix = clean.map((_, i) => i);
    const rootSingle = build(singleNodes, train, ix, [1,1,1,1], N_FEATURES);
    let singleCorrect = 0;
    for (const s of clean)
      if (evalTree(singleNodes, rootSingle, s.features) === s.label) singleCorrect++;

    /* forest */
    const trees = [];
    for (let t = 0; t < FOREST_SIZE; ++t) {
      const bootIx = [];
      for (let i = 0; i < N_SAMPLES; ++i) bootIx.push(rndRange(N_SAMPLES));
      const nodes = [];
      const root = build(nodes, train, bootIx, [1,1,1,1], 2);
      trees.push({ nodes, root });
    }
    let forestCorrect = 0;
    for (const s of clean) {
      let vote = 0;
      for (const t of trees) vote += evalTree(t.nodes, t.root, s.features);
      const y = vote >= 0 ? +1 : -1;
      if (y === s.label) forestCorrect++;
    }

    const mask = flipMask.toString(16).padStart(4, '0');
    lines.push(`target ${name.padEnd(16)}  flipped rows: 0x${mask} (${NOISE_FLIPS} / ${N_SAMPLES})`);
    lines.push(`  single tree          test acc: ${String(singleCorrect).padStart(2)} / ${N_SAMPLES}`);
    lines.push(`  forest  (F=${FOREST_SIZE} vote)  test acc: ${String(forestCorrect).padStart(2)} / ${N_SAMPLES}`);
    lines.push('');
  }

  const CASES = [
    { name: '4-MAJ (>=3)',   table: 0xe880 },
    { name: '4-threshold 2', table: 0xfee8 },
    { name: '4-OR',          table: 0xfffe },
    { name: '4-AND',         table: 0x8000 },
  ];

  function run() {
    rndReset(42);
    const lines = [];
    lines.push(`bagging: single tree vs ${FOREST_SIZE}-tree forest on noisy 4-input targets`);
    lines.push(`(training labels corrupted by ${NOISE_FLIPS} random flips; test on clean truth)`);
    lines.push('');
    for (const c of CASES) runCase(lines, c.name, c.table);
    lines.push('Typical result: forest accuracy >= single-tree accuracy. Each');
    lines.push('bootstrap + random-feature-subset tree overfits a DIFFERENT subset');
    lines.push('of noise; majority vote washes out idiosyncratic errors. The effect');
    lines.push('is modest on tiny noise-free targets — not much to smooth over.');
    return lines.join('\n');
  }

  window.Casting_byte_model_tree_forest = { run };
})();

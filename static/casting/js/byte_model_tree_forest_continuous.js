/* Casting: byte_model_tree_forest continuous — run the single-vs-forest
 * comparison on random targets with random noise seeds, tally wins.
 */
(function () {
  const N_FEATURES = 4;
  const N_SAMPLES  = 16;
  const FOREST_SIZE = 21;
  const NOISE_FLIPS = 3;

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
      const j = Math.floor(Math.random() * (i + 1));
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
    const f = (maxFeat >= N_FEATURES) ? bestFeature(samples, ix, avail)
                                       : bestFeatureRand(samples, ix, avail, maxFeat);
    if (f < 0) { nodes.push({ leaf: true, v: majority(samples, ix) }); return nodes.length - 1; }
    const z = [], o = [];
    for (const i of ix) (samples[i].features[f] ? o : z).push(i);
    const na = avail.slice(); na[f] = 0;
    const slot = nodes.length;
    nodes.push(null);
    nodes[slot] = { leaf: false, f, zc: build(nodes, samples, z, na, maxFeat),
                                   oc: build(nodes, samples, o, na, maxFeat) };
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

  let timer = null;
  let forestWins = 0, singleWins = 0, ties = 0;
  let totalRuns = 0;
  let singleSum = 0, forestSum = 0;

  function tick(emit) {
    const table = Math.floor(Math.random() * 65536);
    const clean = generateClean(table);
    const train = clean.map(s => Object.assign({}, s));
    const used = new Set();
    while (used.size < NOISE_FLIPS) {
      const r = Math.floor(Math.random() * N_SAMPLES);
      if (used.has(r)) continue;
      used.add(r);
      train[r].label = -train[r].label;
    }
    /* single */
    const sn = [];
    const rs = build(sn, train, clean.map((_,i)=>i), [1,1,1,1], N_FEATURES);
    let sc = 0; for (const s of clean) if (evalTree(sn, rs, s.features) === s.label) sc++;
    /* forest */
    const trees = [];
    for (let t = 0; t < FOREST_SIZE; ++t) {
      const boot = [];
      for (let i = 0; i < N_SAMPLES; ++i) boot.push(Math.floor(Math.random()*N_SAMPLES));
      const nodes = []; const root = build(nodes, train, boot, [1,1,1,1], 2);
      trees.push({ nodes, root });
    }
    let fc = 0;
    for (const s of clean) {
      let vote = 0;
      for (const t of trees) vote += evalTree(t.nodes, t.root, s.features);
      if ((vote >= 0 ? +1 : -1) === s.label) fc++;
    }
    totalRuns++; singleSum += sc; forestSum += fc;
    if (fc > sc) forestWins++; else if (sc > fc) singleWins++; else ties++;
    const sa = (singleSum / totalRuns).toFixed(2);
    const fa = (forestSum / totalRuns).toFixed(2);
    const lines = [
      `tree forest — single vs forest on ${totalRuns} random noisy targets`,
      ``,
      `  avg test accuracy — single: ${sa} / ${N_SAMPLES}`,
      `  avg test accuracy — forest: ${fa} / ${N_SAMPLES}`,
      ``,
      `  forest wins:  ${forestWins}`,
      `  single wins:  ${singleWins}`,
      `  ties:         ${ties}`,
      ``,
      `the gap widens with more features / noise; on 4-input targets it`,
      `stays small, but forest rarely loses.`,
    ];
    emit(lines.join('\n'));
  }

  function start(emit) {
    if (timer) return;
    forestWins = singleWins = ties = totalRuns = singleSum = forestSum = 0;
    emit('drawing random targets...');
    timer = setInterval(function () { tick(emit); }, 80);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  window.Casting_byte_model_tree_forest_continuous = { start, stop };
})();

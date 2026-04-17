/* Casting: byte_model_tree_induction continuous — run ID3 on a new
 * random 4-input target each tick, accumulate average tree size stats.
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
  function build(samples, ix, avail, nodes) {
    let pos = 0;
    for (const i of ix) if (samples[i].label > 0) pos++;
    if (pos === 0)           { nodes.push({ leaf: true, v: -1 }); return nodes.length - 1; }
    if (pos === ix.length)   { nodes.push({ leaf: true, v: +1 }); return nodes.length - 1; }
    const any = avail.some(v => v);
    if (!any) {
      const v = pos >= ix.length - pos ? +1 : -1;
      nodes.push({ leaf: true, v }); return nodes.length - 1;
    }
    const f = bestFeature(samples, ix, avail);
    const z = [], o = [];
    for (const i of ix) (samples[i].features[f] ? o : z).push(i);
    const na = avail.slice(); na[f] = 0;
    const slot = nodes.length;
    nodes.push(null);
    const zc = build(samples, z, na, nodes);
    const oc = build(samples, o, na, nodes);
    nodes[slot] = { leaf: false, f, zc, oc };
    return slot;
  }
  function generate(table) {
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
  let totalTargets = 0;
  const sizeHist = new Array(32).fill(0);
  let sumSize = 0, minSize = 99, maxSize = 0;

  function tick(emit) {
    const table = Math.floor(Math.random() * 65536);
    const samples = generate(table);
    const ix = samples.map((_, i) => i);
    const nodes = [];
    build(samples, ix, [1,1,1,1], nodes);
    const n = nodes.length;
    totalTargets++;
    sumSize += n;
    if (n < minSize) minSize = n;
    if (n > maxSize) maxSize = n;
    if (n < sizeHist.length) sizeHist[n]++;
    /* build a small histogram string */
    const maxCount = Math.max(...sizeHist);
    const bars = [];
    for (let i = 1; i < sizeHist.length; ++i) {
      if (sizeHist[i] === 0) continue;
      const w = maxCount ? Math.max(1, Math.round(sizeHist[i] / maxCount * 30)) : 0;
      bars.push(`  ${String(i).padStart(3)}:  ${String(sizeHist[i]).padStart(4)}  ${'#'.repeat(w)}`);
    }
    const avg = (sumSize / totalTargets).toFixed(2);
    const lines = [
      `ID3 induction — random 4-input targets`,
      `targets trained: ${totalTargets}`,
      `tree size (nodes): min=${minSize} max=${maxSize} avg=${avg}`,
      ``,
      `histogram of induced tree sizes:`,
      ...bars,
    ];
    emit(lines.join('\n'));
  }

  function start(emit) {
    if (timer) return;
    emit('sampling random 4-input targets...');
    timer = setInterval(function () { tick(emit); }, 50);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  window.Casting_byte_model_tree_induction_continuous = { start, stop };
})();

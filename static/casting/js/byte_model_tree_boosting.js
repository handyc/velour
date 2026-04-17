/* Casting: byte_model_tree_boosting — AdaBoost on 1-split stumps.
 * Mirrors static/casting/sources/byte_model_tree_boosting.c.
 */
(function () {
  const N_FEATURES = 4;
  const N_SAMPLES  = 16;
  const T_ROUNDS   = 60;

  function stumpPredict(stump, feats) {
    const bit = feats[stump.feature] ? 1 : 0;
    return stump.polarity ? (bit ? +1 : -1) : (bit ? -1 : +1);
  }
  function bestStump(samples, w) {
    let best = { feature: 0, polarity: 0 };
    let bestErr = 1e9;
    for (let f = 0; f < N_FEATURES; ++f) {
      for (let pol = 0; pol < 2; ++pol) {
        const cand = { feature: f, polarity: pol };
        let err = 0;
        for (let i = 0; i < N_SAMPLES; ++i)
          if (stumpPredict(cand, samples[i].features) !== samples[i].label) err += w[i];
        if (err < bestErr) { bestErr = err; best = cand; }
      }
    }
    return { stump: best, err: bestErr };
  }
  function normalize(w) {
    let s = 0; for (const x of w) s += x;
    if (s <= 0) return;
    for (let i = 0; i < w.length; ++i) w[i] /= s;
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

  function runCase(lines, name, table) {
    const samples = generate(table);
    const w = new Array(N_SAMPLES).fill(1 / N_SAMPLES);
    const stumps = [], alphas = [];
    let rounds = 0;
    for (let t = 0; t < T_ROUNDS; ++t) {
      const r = bestStump(samples, w);
      if (r.err < 1e-9) { alphas.push(4); stumps.push(r.stump); rounds = t + 1; break; }
      if (r.err >= 0.5) break;
      const alpha = 0.5 * Math.log((1 - r.err) / r.err);
      alphas.push(alpha);
      stumps.push(r.stump);
      for (let i = 0; i < N_SAMPLES; ++i) {
        const pred = stumpPredict(r.stump, samples[i].features);
        w[i] *= Math.exp(-alpha * samples[i].label * pred);
      }
      normalize(w);
      rounds = t + 1;
    }
    let correct = 0;
    for (const s of samples) {
      let score = 0;
      for (let t = 0; t < rounds; ++t)
        score += alphas[t] * stumpPredict(stumps[t], s.features);
      if ((score >= 0 ? +1 : -1) === s.label) correct++;
    }
    lines.push(`target ${name.padEnd(16)}`);
    lines.push(`  rounds used: ${rounds}   training acc: ${correct} / ${N_SAMPLES}`);
    for (let t = 0; t < Math.min(6, rounds); ++t) {
      lines.push(`  round ${t+1}: x${stumps[t].feature} ${stumps[t].polarity ? '→' : '¬'}  α=${alphas[t].toFixed(3)}`);
    }
    if (rounds > 6) lines.push(`  (... ${rounds - 6} more rounds omitted)`);
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
    lines.push(`AdaBoost on 1-feature decision stumps (T=${T_ROUNDS} rounds)`);
    lines.push('');
    for (const c of CASES) runCase(lines, c.name, c.table);
    lines.push('Observations:');
    lines.push('  - Threshold targets boost partially — single-bit stumps sum to a');
    lines.push('    linear function over features, which CAN represent MAJ/threshold');
    lines.push('    in principle, but the greedy iteration does not always find the');
    lines.push('    optimal linear combination on tiny datasets.');
    lines.push('  - Parity gets stuck at 50% — it is outside the hypothesis class.');
    lines.push('    Boosted stumps = linear classifier over bits; XOR is not linear.');
    return lines.join('\n');
  }

  window.Casting_byte_model_tree_boosting = { run };
})();

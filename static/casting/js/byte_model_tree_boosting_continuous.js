/* Casting: byte_model_tree_boosting_continuous — run AdaBoost on a fresh
 * random 4-input target each tick; tally the achieved training-accuracy
 * distribution. Shows how often boosted stumps land at 16/16, and how
 * many targets remain stuck below ceiling (linear hypothesis class).
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

  function runBoosting(table) {
    const samples = generate(table);
    const w = new Array(N_SAMPLES).fill(1 / N_SAMPLES);
    const stumps = [], alphas = [];
    let rounds = 0;
    for (let t = 0; t < T_ROUNDS; ++t) {
      const r = bestStump(samples, w);
      if (r.err < 1e-9) { alphas.push(4); stumps.push(r.stump); rounds = t + 1; break; }
      if (r.err >= 0.5) break;
      const alpha = 0.5 * Math.log((1 - r.err) / r.err);
      alphas.push(alpha); stumps.push(r.stump);
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
      for (let t = 0; t < rounds; ++t) score += alphas[t] * stumpPredict(stumps[t], s.features);
      if ((score >= 0 ? +1 : -1) === s.label) correct++;
    }
    return { correct, rounds };
  }

  let timer = null;
  let totalTargets = 0;
  let sumCorrect = 0;
  let perfect = 0;
  let gaveUp = 0;   /* 0 rounds — first stump err>=0.5, hypothesis class can't help */
  const accHist = new Array(N_SAMPLES + 1).fill(0);

  function tick(emit) {
    const table = Math.floor(Math.random() * 65536);
    const r = runBoosting(table);
    totalTargets++;
    sumCorrect += r.correct;
    accHist[r.correct]++;
    if (r.correct === N_SAMPLES) perfect++;
    if (r.rounds === 0) gaveUp++;

    const maxCount = Math.max(...accHist);
    const bars = [];
    for (let i = N_SAMPLES; i >= 0; --i) {
      if (accHist[i] === 0) continue;
      const w = maxCount ? Math.max(1, Math.round(accHist[i] / maxCount * 30)) : 0;
      bars.push(`  ${String(i).padStart(2)} / ${N_SAMPLES}:  ${String(accHist[i]).padStart(4)}  ${'#'.repeat(w)}`);
    }
    const avg = (sumCorrect / totalTargets).toFixed(2);
    const pctPerfect = (100 * perfect / totalTargets).toFixed(1);
    const pctGaveUp  = (100 * gaveUp  / totalTargets).toFixed(1);
    const lines = [
      `AdaBoost stumps — random 4-input targets (T=${T_ROUNDS})`,
      `targets boosted: ${totalTargets}`,
      `avg training acc: ${avg} / ${N_SAMPLES}`,
      `perfect (${N_SAMPLES}/${N_SAMPLES}): ${perfect}  (${pctPerfect}%)`,
      `stuck at round 0:  ${gaveUp}  (${pctGaveUp}%)  — linear class cannot separate`,
      ``,
      `training-accuracy histogram:`,
      ...bars,
    ];
    emit(lines.join('\n'));
  }

  function start(emit) {
    if (timer) return;
    totalTargets = 0; sumCorrect = 0; perfect = 0; gaveUp = 0;
    for (let i = 0; i < accHist.length; ++i) accHist[i] = 0;
    emit('boosting random 4-input targets...');
    timer = setInterval(function () { tick(emit); }, 60);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  window.Casting_byte_model_tree_boosting_continuous = { start, stop };
})();

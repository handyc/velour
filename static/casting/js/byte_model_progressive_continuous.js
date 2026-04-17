/* Casting: byte_model_progressive_continuous — keep drawing random
 * targets, run progressive search with a per-target budget, accumulate
 * the solver pool across ticks. Every tick updates a download link so
 * you can grab the current pool.json at any moment.
 */
(function () {
  const MAX_H = 4;
  const BUDGET_W = 18;  /* lower budget for continuous speed */

  function totalBits(n, h) { return (h === 0) ? (n + 1) : h * (n + 2) + 1; }
  function forward(bits, n, h, x) {
    const xi = new Array(n);
    for (let i = 0; i < n; ++i) xi[i] = x[i] ? 1 : -1;
    let idx = 0;
    if (h === 0) {
      let s = 0;
      for (let i = 0; i < n; ++i) s += (((bits >>> idx++) & 1) ? 1 : -1) * xi[i];
      s += ((bits >>> idx++) & 1) ? 1 : -1;
      return s >= 0 ? +1 : -1;
    }
    const hid = new Array(h);
    for (let j = 0; j < h; ++j) {
      let s = 0;
      for (let i = 0; i < n; ++i) s += (((bits >>> idx++) & 1) ? 1 : -1) * xi[i];
      s += ((bits >>> idx++) & 1) ? 1 : -1;
      hid[j] = s >= 0 ? +1 : -1;
    }
    let s = 0;
    for (let j = 0; j < h; ++j) s += (((bits >>> idx++) & 1) ? 1 : -1) * hid[j];
    s += ((bits >>> idx++) & 1) ? 1 : -1;
    return s >= 0 ? +1 : -1;
  }
  function searchProgressive(n, tt, maxW) {
    const N = 1 << n;
    for (let h = 0; h <= MAX_H; ++h) {
      const W = totalBits(n, h);
      if (W > maxW) break;
      const space = 1 << W;
      for (let b = 0; b < space; ++b) {
        let ok = true;
        for (let row = 0; row < N; ++row) {
          const x = new Array(n);
          for (let i = 0; i < n; ++i) x[i] = (row >> (n - 1 - i)) & 1;
          const y_pred = forward(b, n, h, x);
          const y_true = ((tt >> row) & 1) ? +1 : -1;
          if (y_pred !== y_true) { ok = false; break; }
        }
        if (ok) return { solved: true, h, W, bits: b };
      }
    }
    return { solved: false };
  }

  const POOL = new Map();      /* key: "n:tt" → solver entry */
  const HIST_H = [0, 0, 0, 0, 0];   /* how many solvers at h=0,1,2,3,4 */
  let tried = 0, skipped = 0, unsolved = 0;

  function poolJSON() {
    const arr = [];
    for (const v of POOL.values()) arr.push(v);
    return JSON.stringify({
      format: 'casting-pool-v1',
      arch_family: 'MLP n→h→1, ±1 weights, sign activation, LSB-first bitstring',
      note: 'Pool accumulated from random-target progressive search.',
      generated_at: new Date().toISOString(),
      pool: arr,
    }, null, 2);
  }
  function mountDownload() {
    const out = document.getElementById('cast-output');
    if (!out) return;
    let link = document.getElementById('cast-progressive-dl');
    if (!link) {
      link = document.createElement('a');
      link.id = 'cast-progressive-dl';
      link.className = 'cast-chip';
      link.style.display = 'inline-block';
      link.style.marginTop = '0.8em';
      out.insertAdjacentElement('afterend', link);
    }
    if (link.dataset.blobUrl) URL.revokeObjectURL(link.dataset.blobUrl);
    const json = poolJSON();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    link.dataset.blobUrl = url;
    link.href = url;
    link.download = 'casting-progressive-pool.json';
    link.textContent = 'download pool.json (' + POOL.size + ' solvers, ' + blob.size + ' bytes)';
  }

  let timer = null;

  function tick(emit) {
    const n = 2 + Math.floor(Math.random() * 3);
    const nrows = 1 << n;
    const ttMax = 1 << nrows;
    const tt = Math.floor(Math.random() * ttMax);
    const key = n + ':' + tt;
    tried++;
    if (POOL.has(key)) { skipped++; }
    else {
      const r = searchProgressive(n, tt, BUDGET_W);
      if (r.solved) {
        POOL.set(key, {
          name: `rand-n${n}-0x${tt.toString(16)}`,
          n, truth_table: tt, h: r.h, weight_bits: r.W, bits: r.bits,
        });
        HIST_H[r.h]++;
      } else {
        unsolved++;
      }
    }

    mountDownload();
    const lines = [
      `progressive search over random targets (budget W≤${BUDGET_W})`,
      `tries: ${tried}  skipped (dup): ${skipped}  unsolved: ${unsolved}`,
      `pool size: ${POOL.size}`,
      ``,
      `architecture histogram:`,
      `  h=0 (linear):     ${HIST_H[0]}`,
      `  h=1:              ${HIST_H[1]}`,
      `  h=2:              ${HIST_H[2]}`,
      `  h=3:              ${HIST_H[3]}`,
      `  h=4:              ${HIST_H[4]}`,
      ``,
      `download link below the output stays up-to-date every tick.`,
    ];
    emit(lines.join('\n'));
  }

  function start(emit) {
    if (timer) return;
    emit('searching random targets — the pool will grow each tick...');
    timer = setInterval(function () { tick(emit); }, 200);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  window.Casting_byte_model_progressive_continuous = { start, stop, poolJSON: () => poolJSON() };
})();

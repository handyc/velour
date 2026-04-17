/* Casting: byte_model_progressive — progressive architecture search.
 * Mirrors static/casting/sources/byte_model_progressive.c and also emits
 * the discovered pool as JSON + a download link beneath the output.
 */
(function () {
  const MAX_H = 4;
  const MAX_N = 4;
  const BUDGET_W = 22;

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

  function searchProgressive(target, maxW) {
    const N = 1 << target.n;
    let examined = 0;
    for (let h = 0; h <= MAX_H; ++h) {
      const W = totalBits(target.n, h);
      if (W > maxW) break;
      const space = 1 << W;
      for (let b = 0; b < space; ++b) {
        examined++;
        let ok = true;
        for (let row = 0; row < N; ++row) {
          const x = new Array(target.n);
          for (let i = 0; i < target.n; ++i) x[i] = (row >> (target.n - 1 - i)) & 1;
          const y_pred = forward(b, target.n, h, x);
          const y_true = ((target.tt >> row) & 1) ? +1 : -1;
          if (y_pred !== y_true) { ok = false; break; }
        }
        if (ok) return { solved: true, h, W, bits: b, examined };
      }
    }
    return { solved: false, h: -1, W: -1, bits: 0, examined };
  }

  const TARGETS = [
    { name: '2-AND',  n: 2, tt: 0x8 },
    { name: '2-OR',   n: 2, tt: 0xe },
    { name: '2-XOR',  n: 2, tt: 0x6 },
    { name: '3-AND',  n: 3, tt: 0x80 },
    { name: '3-OR',   n: 3, tt: 0xfe },
    { name: '3-MAJ',  n: 3, tt: 0xe8 },
    { name: '3-MUX',  n: 3, tt: 0xca },
    { name: '3-XOR',  n: 3, tt: 0x69 },
    { name: '4-OR',   n: 4, tt: 0xfffe },
    { name: '4-AND',  n: 4, tt: 0x8000 },
    { name: '4-MAJ',  n: 4, tt: 0xe880 },
    { name: '4-thr2', n: 4, tt: 0xfee8 },
    { name: '4-XOR',  n: 4, tt: 0x6996 },
  ];

  /* Pool kept across runs of the one-shot too, so "export" always has
   * the last accumulated search. */
  let POOL = [];

  function poolJSON() {
    return JSON.stringify({
      format: 'casting-pool-v1',
      arch_family: 'MLP n→h→1, ±1 weights, sign activation, LSB-first bitstring',
      note: 'Each entry: n inputs, truth_table (2^n bits), h hidden units, '
          + 'W total weight bits, bits = solver (hex). Weights are unpacked '
          + 'LSB-first: for h>0 each hidden unit emits n input weights then 1 bias; '
          + 'then h output weights then 1 output bias. For h=0: n input weights + 1 bias.',
      generated_at: new Date().toISOString(),
      pool: POOL,
    }, null, 2);
  }

  function mountDownload(jsonText) {
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
    const blob = new Blob([jsonText], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    link.dataset.blobUrl = url;
    link.href = url;
    link.download = 'casting-progressive-pool.json';
    link.textContent = 'download pool.json (' + POOL.length + ' solvers, ' + blob.size + ' bytes)';
  }

  function run() {
    POOL = [];
    const rows = [];
    rows.push('progressive architecture search — tiny MLPs (±1, sign activation)');
    rows.push('grow h until a solver is found; entire pool is exported below.');
    rows.push('');
    rows.push(['target', 'h', 'bits', 'examined', 'solver (hex)'].map((s, i) =>
      i === 0 ? s.padEnd(8) : i === 4 ? s : s.padEnd(10)
    ).join(' '));
    rows.push('-'.repeat(58));
    let solved = 0;
    for (const t of TARGETS) {
      const r = searchProgressive(t, BUDGET_W);
      if (r.solved) {
        solved++;
        POOL.push({
          name: t.name, n: t.n, truth_table: t.tt,
          h: r.h, weight_bits: r.W, bits: r.bits,
        });
        rows.push(
          t.name.padEnd(8) + ' ' +
          String(r.h).padEnd(10) + ' ' +
          String(r.W).padEnd(10) + ' ' +
          String(r.examined).padEnd(10) + ' ' +
          '0x' + r.bits.toString(16)
        );
      } else {
        rows.push(
          t.name.padEnd(8) + ' ' +
          '-'.padEnd(10) + ' -'.padEnd(11) + ' -'.padEnd(11) +
          ' UNSOLVED (budget W≤' + BUDGET_W + ')'
        );
      }
    }
    rows.push('');
    rows.push('pool: ' + solved + ' / ' + TARGETS.length + ' targets solved.');
    rows.push('');
    const json = poolJSON();
    rows.push('--- exported pool.json below; click the link beneath to download ---');
    rows.push(json);
    mountDownload(json);
    return rows.join('\n');
  }

  window.Casting_byte_model_progressive = { run, poolJSON: () => poolJSON() };
})();

/* Casting: byte_model_runtime — execute a pool of discovered solvers.
 * Mirrors static/casting/sources/byte_model_runtime.c and adds UI to
 * load a user-provided pool.json (the one exported from the progressive
 * search experiment).
 */
(function () {
  let DEFAULT_POOL = [
    { name: '2-AND',  n: 2, h: 0, weight_bits: 3,  bits: 0x3 },
    { name: '2-OR',   n: 2, h: 0, weight_bits: 3,  bits: 0x7 },
    { name: '2-XOR',  n: 2, h: 2, weight_bits: 9,  bits: 0x3 },
    { name: '3-AND',  n: 3, h: 1, weight_bits: 6,  bits: 0x8 },
    { name: '3-OR',   n: 3, h: 0, weight_bits: 4,  bits: 0xf },
    { name: '3-MAJ',  n: 3, h: 0, weight_bits: 4,  bits: 0x7 },
    { name: '3-MUX',  n: 3, h: 3, weight_bits: 16, bits: 0x10ba },
    { name: '3-XOR',  n: 3, h: 3, weight_bits: 16, bits: 0x35 },
    { name: '4-OR',   n: 4, h: 3, weight_bits: 19, bits: 0x40022 },
    { name: '4-MAJ',  n: 4, h: 0, weight_bits: 5,  bits: 0xf },
    { name: '4-thr2', n: 4, h: 0, weight_bits: 5,  bits: 0x1f },
  ];
  let POOL = DEFAULT_POOL.slice();

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
  function findEntry(name) { return POOL.find(e => e.name === name) || null; }

  function dumpTruth(e) {
    const lines = [`${e.name.padEnd(8)}  (h=${e.h}, W=${String(e.weight_bits).padStart(2)} bits, solver=0x${e.bits.toString(16)})`];
    const N = 1 << e.n;
    for (let row = 0; row < N; ++row) {
      const x = new Array(e.n);
      for (let i = 0; i < e.n; ++i) x[i] = (row >> (e.n - 1 - i)) & 1;
      const y = forward(e.bits, e.n, e.h, x);
      lines.push(`  ${x.join('')} -> ${y > 0 ? '+1' : '-1'}`);
    }
    return lines.join('\n');
  }

  function mountLoader() {
    const out = document.getElementById('cast-output');
    if (!out) return;
    if (document.getElementById('cast-runtime-ui')) return;
    const wrap = document.createElement('div');
    wrap.id = 'cast-runtime-ui';
    wrap.style.marginTop = '0.8em';
    wrap.style.display = 'flex';
    wrap.style.gap = '0.6em';
    wrap.style.flexWrap = 'wrap';
    wrap.style.alignItems = 'center';
    wrap.innerHTML = `
      <label class="cast-chip" style="cursor:pointer">
        load custom pool.json
        <input id="cast-runtime-file" type="file" accept="application/json,.json" style="display:none">
      </label>
      <span id="cast-runtime-status" style="opacity:0.7;font-size:0.9em"></span>
      <button id="cast-runtime-reset" class="cast-chip" type="button">reset to default pool</button>
    `;
    out.insertAdjacentElement('afterend', wrap);
    const fileInput = document.getElementById('cast-runtime-file');
    const status = document.getElementById('cast-runtime-status');
    fileInput.addEventListener('change', async function () {
      const f = fileInput.files[0];
      if (!f) return;
      try {
        const text = await f.text();
        const parsed = JSON.parse(text);
        const arr = Array.isArray(parsed.pool) ? parsed.pool : parsed;
        const cleaned = arr.filter(e =>
          typeof e.n === 'number' && typeof e.h === 'number' &&
          typeof e.bits === 'number' && typeof e.weight_bits === 'number' &&
          typeof e.name === 'string'
        );
        POOL = cleaned;
        status.textContent = `loaded ${POOL.length} entries from ${f.name}`;
      } catch (err) {
        status.textContent = 'load failed: ' + (err.message || err);
      }
    });
    document.getElementById('cast-runtime-reset').addEventListener('click', function () {
      POOL = DEFAULT_POOL.slice();
      status.textContent = 'reset to default pool (' + POOL.length + ' entries)';
    });
  }

  function run() {
    mountLoader();
    const lines = [];
    lines.push(`Casting Runtime — ${POOL.length} pool entries loaded`);
    lines.push('');
    for (const e of POOL) lines.push(dumpTruth(e) + '\n');

    const fxor = findEntry('2-XOR'), f_or = findEntry('2-OR'), fand = findEntry('2-AND');
    if (fxor && f_or && fand) {
      lines.push('program: (a XOR b) AND (c OR d)  — chained from pool');
      for (let row = 0; row < 16; ++row) {
        const a = (row >> 3) & 1, b = (row >> 2) & 1;
        const c = (row >> 1) & 1, d = (row >> 0) & 1;
        const u = forward(fxor.bits, 2, fxor.h, [a, b]) > 0 ? 1 : 0;
        const v = forward(f_or.bits, 2, f_or.h, [c, d]) > 0 ? 1 : 0;
        const y = forward(fand.bits, 2, fand.h, [u, v]) > 0 ? 1 : 0;
        lines.push(`  a=${a} b=${b} c=${c} d=${d} -> u=${u} v=${v} y=${y}`);
      }
    } else {
      lines.push('(chained program demo skipped — needed 2-XOR, 2-OR, 2-AND in pool)');
    }
    return lines.join('\n');
  }

  window.Casting_byte_model_runtime = { run, pool: () => POOL };
})();

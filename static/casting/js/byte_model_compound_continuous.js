/* Casting: byte_model_compound continuous — stream of random 3-input
 * compound targets, accumulate coverage by K.
 */
(function () {
  const PRIMITIVE_COUNT = 16;
  const K_MAX = 2;  /* K=3 is too slow per-tick in browser; C version goes further */
  const N_INPUTS = 3;

  function unpackWeight(w, i) { return ((w >> i) & 1) ? 1 : -1; }
  function signOf(v) { return v >= 0 ? 1 : -1; }
  function networkForward(w, a, b) {
    const h0 = signOf(unpackWeight(w,0)*a + unpackWeight(w,1)*b + unpackWeight(w,2));
    const h1 = signOf(unpackWeight(w,3)*a + unpackWeight(w,4)*b + unpackWeight(w,5));
    return    signOf(unpackWeight(w,6)*h0 + unpackWeight(w,7)*h1 + unpackWeight(w,8));
  }
  function taskTruth2in(tid, a, b) {
    const idx = (((a>0)?1:0) << 1) | ((b>0)?1:0);
    return ((tid >> idx) & 1) ? 1 : -1;
  }
  function growPool() {
    const pool = [];
    for (let tid = 0; tid < PRIMITIVE_COUNT; ++tid) {
      for (let c = 0; c < 512; ++c) {
        let ok = true;
        for (let r = 0; r < 4 && ok; ++r) {
          const a = (r&2)?1:-1, b = (r&1)?1:-1;
          if (networkForward(c,a,b) !== taskTruth2in(tid,a,b)) ok = false;
        }
        if (ok) {
          const lut = [[0,0],[0,0]];
          for (let ai=0; ai<2; ++ai) for (let bi=0; bi<2; ++bi)
            lut[ai][bi] = networkForward(c, ai?1:-1, bi?1:-1);
          pool.push({ taskId: tid, lut }); break;
        }
      }
    }
    return pool;
  }

  function solveTruthTable(pool, truthTable, nInputs, kMax) {
    const rows = 1 << nInputs;
    for (let len = 1; len <= kMax; ++len) {
      const regs_per_op = [];
      let total = 1;
      for (let k = 0; k < len; ++k) {
        regs_per_op.push(nInputs + k);
        total *= PRIMITIVE_COUNT * regs_per_op[k] * regs_per_op[k];
      }
      const prog = new Array(len);
      for (let idx = 0; idx < total; ++idx) {
        let rem = idx;
        for (let k = 0; k < len; ++k) {
          const r = regs_per_op[k];
          const p = rem % PRIMITIVE_COUNT; rem = (rem / PRIMITIVE_COUNT)|0;
          const a = rem % r;                rem = (rem / r)|0;
          const b = rem % r;                rem = (rem / r)|0;
          prog[k] = [p, a, b];
        }
        /* evaluate */
        let ok = true;
        for (let row = 0; row < rows && ok; ++row) {
          const regs = new Array(nInputs + len);
          for (let i = 0; i < nInputs; ++i)
            regs[i] = ((row >> (nInputs - 1 - i)) & 1) ? 1 : -1;
          for (let k = 0; k < len; ++k) {
            const [p, ar, br] = prog[k];
            const a = regs[ar], b = regs[br];
            regs[nInputs + k] = pool[p].lut[a>0?1:0][b>0?1:0];
          }
          const predicted = regs[nInputs + len - 1];
          const desired = ((truthTable >> row) & 1) ? 1 : -1;
          if (predicted !== desired) ok = false;
        }
        if (ok) return len;
      }
    }
    return 0;
  }

  let timer = null;
  let pool = null;
  const coverageByK = [0, 0, 0];  /* index = K; value = count of truth tables first solved at that K */
  let unsolved = 0;
  let totalSeen = 0;
  const seen = new Set();

  function tick(emit) {
    const target = (Math.random() * 256) | 0;
    totalSeen++;
    if (seen.has(target)) {
      // duplicate; don't double-count
    } else {
      seen.add(target);
      const k = solveTruthTable(pool, target, N_INPUTS, K_MAX);
      if (k === 0) unsolved++;
      else         coverageByK[k]++;
    }
    const distinct = seen.size;
    const solvedByK1 = coverageByK[1];
    const solvedByK2 = coverageByK[1] + coverageByK[2];
    const lines = [
      `compound experts — continuous sweep`,
      `------------------------------------`,
      `primitive pool: ${pool.length} experts (all 2-input boolean functions)`,
      `random 3-input truth tables drawn:  ${totalSeen}`,
      `distinct 3-input tables seen so far: ${distinct} / 256`,
      ``,
      `coverage (cumulative min-K over seen tables):`,
      `  K=1 (one op):   ${String(solvedByK1).padStart(4)} / ${distinct}`,
      `  K=2 (two ops):  ${String(solvedByK2).padStart(4)} / ${distinct}`,
      `  not solvable within K<=${K_MAX}: ${unsolved} / ${distinct}`,
      ``,
      `note: K=3 reaches many more targets (see 'Run once' or C source).`,
    ];
    emit(lines.join('\n'));
  }

  function start(emit) {
    if (timer) return;
    if (!pool) pool = growPool();
    emit('starting continuous sweep...');
    timer = setInterval(function () { tick(emit); }, 100);
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  window.Casting_byte_model_compound_continuous = { start, stop };
})();

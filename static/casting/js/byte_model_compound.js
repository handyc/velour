/* Casting: byte_model_compound — JS port of the compound-experts search.
 * Mirrors static/casting/sources/byte_model_compound.c.
 */
(function () {
  const PRIMITIVE_COUNT = 16;
  const K_MAX = 3;
  const MAX_INPUT_WIDTH = 4;

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
          const a = (r & 2) ? 1 : -1, b = (r & 1) ? 1 : -1;
          if (networkForward(c, a, b) !== taskTruth2in(tid, a, b)) ok = false;
        }
        if (ok) {
          const lut = [[0,0],[0,0]];
          for (let ai = 0; ai < 2; ++ai)
            for (let bi = 0; bi < 2; ++bi)
              lut[ai][bi] = networkForward(c, ai?1:-1, bi?1:-1);
          pool.push({ taskId: tid, weights: c, lut });
          break;
        }
      }
    }
    return pool;
  }

  function programRun(pool, program, inputs, nInputs) {
    const regs = new Array(nInputs + program.length);
    for (let i = 0; i < nInputs; ++i) regs[i] = inputs[i];
    let next = nInputs;
    for (let k = 0; k < program.length; ++k) {
      const [p, ar, br] = program[k];
      const a = regs[ar], b = regs[br];
      regs[next++] = pool[p].lut[a>0?1:0][b>0?1:0];
    }
    return regs[next-1];
  }

  function programMatches(pool, program, truthTable, nInputs) {
    const rows = 1 << nInputs;
    for (let row = 0; row < rows; ++row) {
      const inputs = new Array(nInputs);
      for (let i = 0; i < nInputs; ++i)
        inputs[i] = ((row >> (nInputs - 1 - i)) & 1) ? 1 : -1;
      const predicted = programRun(pool, program, inputs, nInputs);
      const desired = ((truthTable >> row) & 1) ? 1 : -1;
      if (predicted !== desired) return false;
    }
    return true;
  }

  function searchProgram(pool, truthTable, nInputs, kMax) {
    const poolSize = pool.length;
    for (let len = 1; len <= kMax; ++len) {
      const regsPerOp = [];
      let total = 1;
      for (let k = 0; k < len; ++k) {
        regsPerOp.push(nInputs + k);
        total *= poolSize * regsPerOp[k] * regsPerOp[k];
      }
      const prog = new Array(len);
      for (let idx = 0; idx < total; ++idx) {
        let rem = idx;
        for (let k = 0; k < len; ++k) {
          const r = regsPerOp[k];
          const p = rem % poolSize; rem = Math.floor(rem / poolSize);
          const a = rem % r;        rem = Math.floor(rem / r);
          const b = rem % r;        rem = Math.floor(rem / r);
          prog[k] = [p, a, b];
        }
        if (programMatches(pool, prog, truthTable, nInputs)) {
          return { k: len, program: prog.map(x => x.slice()) };
        }
      }
    }
    return { k: 0, program: null };
  }

  const PRIM_NAMES = [
    "F","NOR","ANb","nb","nAb","na","XOR","NAND",
    "AND","XNOR","a","aOb","b","nAOb","OR","T"
  ];

  const TARGETS = [
    { name: "3-AND         ", n: 3, table: 0x80   },
    { name: "3-OR          ", n: 3, table: 0xfe   },
    { name: "3-XOR (parity)", n: 3, table: 0x96   },
    { name: "3-MAJ         ", n: 3, table: 0xe8   },
    { name: "3-MUX a?b:c   ", n: 3, table: 0xca   },
    { name: "adder-carry   ", n: 3, table: 0xe8   },
    { name: "adder-sum     ", n: 3, table: 0x96   },
    { name: "4-XOR (parity)", n: 4, table: 0x6996 },
  ];

  function pad(s, n) { s = String(s); while (s.length < n) s += ' '; return s; }

  function run() {
    const pool = growPool();
    const lines = [];
    lines.push(`primitive pool: ${pool.length} / ${PRIMITIVE_COUNT} two-input boolean experts grown`);
    lines.push('');
    lines.push(`${pad('target',18)} ${pad('min K',7)} program`);
    lines.push(`${pad('------',18)} ${pad('-----',7)} -------`);
    let solved = 0;
    for (const tgt of TARGETS) {
      const result = searchProgram(pool, tgt.table, tgt.n, K_MAX);
      if (result.k === 0) {
        lines.push(`${pad(tgt.name,18)} ${pad('—',7)} unreachable within K=${K_MAX}`);
        continue;
      }
      solved++;
      const parts = [];
      for (let i = 0; i < result.k; ++i) {
        const [p, ar, br] = result.program[i];
        const outReg = tgt.n + i;
        parts.push(`r${outReg}=${PRIM_NAMES[pool[p].taskId]}(r${ar},r${br})`);
      }
      lines.push(`${pad(tgt.name,18)} ${pad('K=' + result.k,7)} ${parts.join('; ')}`);
    }
    lines.push('');
    lines.push(`solved ${solved} / ${TARGETS.length} targets within K<=${K_MAX}.`);
    lines.push(`note: 3-MAJ, adder-carry, 4-MAJ each need K>=4 — try the C version.`);
    return lines.join('\n');
  }

  window.Casting_byte_model_compound = { run };
})();

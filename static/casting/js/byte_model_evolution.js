/* Casting: byte_model_evolution — genetic search over LUT genes.
 *
 * Bridges Casting's ±1 MLP architecture family with the Velour
 * Evolution Engine (evolution/static/evolution/engine.mjs). The engine
 * now has a `gene_type: 'lut'` dispatch (see GENE_TYPES in engine.mjs);
 * this experiment drives it.
 *
 * Gene = {n, h, bits}. Fitness = fraction of truth-table rows matched
 * by the forward pass; ties broken by smaller W (fewer weight bits).
 * Solvers (perfect truth tables) accumulate into a POOL that can be
 * exported as casting-pool-v1 JSON, compatible with byte_model_runtime.
 */
(function () {
  const EE_URL = '/static/evolution/engine.mjs';
  const TARGETS = [
    { name: '2-AND',  n: 2, tt: 0x8    },
    { name: '2-OR',   n: 2, tt: 0xe    },
    { name: '2-XOR',  n: 2, tt: 0x6    },
    { name: '3-AND',  n: 3, tt: 0x80   },
    { name: '3-OR',   n: 3, tt: 0xfe   },
    { name: '3-MAJ',  n: 3, tt: 0xe8   },
    { name: '3-MUX',  n: 3, tt: 0xca   },
    { name: '3-XOR',  n: 3, tt: 0x69   },
    { name: '4-OR',   n: 4, tt: 0xfffe },
    { name: '4-AND',  n: 4, tt: 0x8000 },
    { name: '4-MAJ',  n: 4, tt: 0xe880 },
    { name: '4-thr2', n: 4, tt: 0xfee8 },
    { name: '4-XOR',  n: 4, tt: 0x6996 },
  ];
  const DEFAULTS = { pop: 48, gens: 600, mut: 0.08, tournament: 3 };

  let EEModule = null;
  let POOL = [];
  let running = false;
  let stopReq = false;
  let uiMounted = false;

  async function loadEE() {
    if (EEModule) return EEModule;
    EEModule = await import(EE_URL);
    return EEModule;
  }

  function setStatus(msg) {
    const el = document.getElementById('cast-evo-status');
    if (el) el.textContent = msg;
  }

  function setOut(text) {
    const out = document.getElementById('cast-output');
    if (out) out.textContent = text;
  }

  function renderPool() {
    const dl = document.getElementById('cast-evo-dl');
    if (!dl) return;
    if (POOL.length === 0) {
      dl.style.display = 'none';
      return;
    }
    const json = JSON.stringify({
      format: 'casting-pool-v1',
      arch_family: 'MLP n→h→1, ±1 weights, sign activation, LSB-first bitstring',
      note: 'Produced by byte_model_evolution (GA, not exhaustive). Compatible '
          + 'with byte_model_runtime.',
      generated_at: new Date().toISOString(),
      pool: POOL,
    }, null, 2);
    if (dl.dataset.blobUrl) URL.revokeObjectURL(dl.dataset.blobUrl);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    dl.dataset.blobUrl = url;
    dl.href = url;
    dl.download = 'casting-evolution-pool.json';
    dl.textContent = 'download pool.json (' + POOL.length + ' solvers, '
                   + blob.size + ' bytes)';
    dl.style.display = 'inline-block';
  }

  function poolHas(name, tt) {
    return POOL.some(e => e.name === name && e.truth_table === tt);
  }

  function targetByName(name) {
    return TARGETS.find(t => t.name === name) || null;
  }

  function parseCustomTarget(str) {
    // "n:tt" — e.g. "3:0x96" or "4:0xabcd"
    const m = /^\s*(\d+)\s*:\s*(0x[0-9a-f]+|\d+)\s*$/i.exec(str || '');
    if (!m) return null;
    const n = parseInt(m[1], 10);
    const tt = parseInt(m[2], m[2].startsWith('0x') || m[2].startsWith('0X') ? 16 : 10);
    if (n < 1 || n > 6) return null;
    const mask = (n >= 5) ? 0xffffffff : ((1 << (1 << n)) - 1);
    if ((tt & ~mask) !== 0) return null;
    return { name: `custom-${n}-0x${tt.toString(16)}`, n, tt };
  }

  async function evolveOne(target) {
    const mod = await loadEE();
    const { EvolutionEngine, lutTruthTable } = mod;
    const engine = new EvolutionEngine({
      level: 0,
      gene_type: 'lut',
      lut_target: { n: target.n, truth_table: target.tt },
      population_size: DEFAULTS.pop,
      generations_target: DEFAULTS.gens,
      target_score: 1.0 - 1e-9,
      params: { mutation_rate: DEFAULTS.mut, tournament_k: DEFAULTS.tournament },
    });
    engine.init();
    const log = [];
    log.push(`evolving ${target.name}  (n=${target.n}, target tt=0x${target.tt.toString(16)})`);
    log.push('generation  best   mean');
    log.push('----------  -----  -----');
    setOut(log.join('\n'));
    while (!engine.isDone() && !stopReq) {
      await engine.tick();
      if (engine.generation % 10 === 0 || engine.bestScore >= 1 - 1e-9) {
        const h = engine.history[engine.history.length - 1];
        log.push(
          String(h.gen).padStart(10, ' ') + '  ' +
          h.best.toFixed(3) + '  ' + h.mean.toFixed(3)
        );
        setOut(log.join('\n'));
      }
      /* yield so the UI repaints */
      await new Promise(r => setTimeout(r, 0));
    }
    const best = engine.best;
    const solved = best && lutTruthTable(best.gene) === (target.tt >>> 0);
    log.push('');
    if (solved) {
      log.push(`SOLVED: n=${best.gene.n}, h=${best.gene.h}, `
             + `bits=0x${best.gene.bits.toString(16)}`);
      if (!poolHas(target.name, target.tt)) {
        POOL.push({
          name: target.name, n: target.n, truth_table: target.tt,
          h: best.gene.h,
          weight_bits: (best.gene.h > 0) ? best.gene.h * (target.n + 2) + 1 : (target.n + 1),
          bits: best.gene.bits,
        });
        log.push(`(added to pool — ${POOL.length} entries total)`);
      } else {
        log.push('(already in pool)');
      }
    } else {
      const bestTT = best ? lutTruthTable(best.gene) : 0;
      log.push(`no perfect solver in ${engine.generation} gens.`);
      log.push(`best score ${engine.bestScore.toFixed(3)}; tt=0x${bestTT.toString(16)}`);
      log.push('(try "evolve" again, or increase generations)');
    }
    setOut(log.join('\n'));
    renderPool();
    return solved;
  }

  async function doEvolve() {
    if (running) { stopReq = true; return; }
    running = true;
    stopReq = false;
    const btn = document.getElementById('cast-evo-go');
    if (btn) btn.textContent = 'stop';
    try {
      const sel = document.getElementById('cast-evo-target').value;
      const custom = document.getElementById('cast-evo-custom').value.trim();
      const target = custom ? parseCustomTarget(custom) : targetByName(sel);
      if (!target) {
        setStatus('invalid target. use "n:tt" like 3:0x96, or pick a preset.');
        return;
      }
      setStatus(`evolving ${target.name}...`);
      const ok = await evolveOne(target);
      setStatus(ok ? `solved ${target.name}.` : `did not solve ${target.name}.`);
    } catch (e) {
      console.error('[evolution] error', e);
      setStatus('evolution failed: ' + (e && e.message || e));
      setOut('evolution failed: ' + (e && e.message || e) + '\n\nSee the F12 console for details.');
    } finally {
      running = false;
      stopReq = false;
      if (btn) btn.textContent = 'evolve';
    }
  }

  async function doEvolveAll() {
    if (running) { stopReq = true; return; }
    running = true;
    stopReq = false;
    const btn = document.getElementById('cast-evo-all');
    if (btn) btn.textContent = 'stop';
    try {
      let solved = 0;
      for (const t of TARGETS) {
        if (stopReq) break;
        setStatus(`sweeping: ${t.name} (${solved}/${TARGETS.length} solved so far)`);
        const ok = await evolveOne(t);
        if (ok) solved++;
      }
      setStatus(`sweep done: ${solved}/${TARGETS.length} targets solved.`);
    } finally {
      running = false;
      stopReq = false;
      if (btn) btn.textContent = 'evolve all';
    }
  }

  function doClearPool() {
    POOL = [];
    renderPool();
    setStatus('pool cleared.');
  }

  function mountUI() {
    if (uiMounted) return;
    const out = document.getElementById('cast-output');
    if (!out) return;
    uiMounted = true;
    const wrap = document.createElement('div');
    wrap.id = 'cast-evo-ui';
    wrap.style.marginTop = '0.8em';
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = '0.5em';
    const opts = TARGETS.map(t =>
      `<option value="${t.name}">${t.name} (tt=0x${t.tt.toString(16)})</option>`
    ).join('');
    wrap.innerHTML = `
      <div style="display:flex;gap:.5em;flex-wrap:wrap;align-items:center">
        <label>target:</label>
        <select id="cast-evo-target" class="cast-chip">${opts}</select>
        <span style="opacity:.5">or custom:</span>
        <input id="cast-evo-custom" class="cast-chip" placeholder="n:tt (e.g. 3:0x96)"
               style="width:14em">
      </div>
      <div style="display:flex;gap:.5em;align-items:center;flex-wrap:wrap">
        <button id="cast-evo-go"    class="cast-chip" type="button">evolve</button>
        <button id="cast-evo-all"   class="cast-chip" type="button">evolve all targets</button>
        <button id="cast-evo-clear" class="cast-chip" type="button">clear pool</button>
        <a id="cast-evo-dl" class="cast-chip" style="display:none"></a>
        <span id="cast-evo-status" style="opacity:.7;font-size:.9em"></span>
      </div>
    `;
    out.insertAdjacentElement('afterend', wrap);
    document.getElementById('cast-evo-go').addEventListener('click', doEvolve);
    document.getElementById('cast-evo-all').addEventListener('click', doEvolveAll);
    document.getElementById('cast-evo-clear').addEventListener('click', doClearPool);
    /* pre-select 4-XOR — the hard target that exhaustive search misses at W≤22 */
    const sel = document.getElementById('cast-evo-target');
    sel.value = '4-XOR';
    setStatus('ready. pick a target and click "evolve".');
  }

  function run() {
    mountUI();
    const info = [
      'evolutionary LUT search — GA over the Casting ±1 MLP gene space.',
      '',
      'Why this exists: exhaustive enumeration (progressive search) caps',
      'at W ≤ 22 bits (~4M configs). Evolution lets us poke at larger',
      'architectures by breeding a population toward the target truth',
      'table. Fitness is fraction of rows correct; W is a tiebreaker.',
      '',
      'Bridge to Velour: this experiment calls directly into the',
      "Evolution Engine (evolution/static/evolution/engine.mjs) via the",
      "new gene_type: 'lut' dispatch. Same engine that breeds L-system",
      'plants also breeds Casting LUTs.',
      '',
      'Usage:',
      '  - pick a preset target, or type "n:tt" (hex ok)',
      '  - click "evolve" — runs 600 generations, pop 48',
      '  - "evolve all" sweeps every preset in order',
      '  - solvers accumulate in a pool; download as casting-pool-v1',
      '    JSON compatible with byte_model_runtime.',
      '',
      'Honest note: GA is not exhaustive. It may fail on targets that',
      'exhaustive search solves, and may surprise you on ones it missed.',
      'Run again if you get "no perfect solver"; randomness matters.',
    ];
    return info.join('\n');
  }

  window.Casting_byte_model_evolution = { run };
})();

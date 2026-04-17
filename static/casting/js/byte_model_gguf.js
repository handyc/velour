/* Casting: byte_model_gguf — load a real GGUF via wllama (WebAssembly
 * llama.cpp) and run in-browser inference. This is the "here is what
 * a functional transformer looks like when dropped in" demo. The
 * models loaded here are NOT produced by Casting — they come from
 * Hugging Face URLs the user configures.
 */
(function () {
  /* A few small public models. 100-300 MB each, so the first load is
   * slow; subsequent loads hit the browser's HTTP cache. */
  const PRESETS = [
    {
      label: 'TinyStories-656K Q8 (~1 MB)',
      repo:  'raincandy-u/TinyStories-656K-Q8_0-GGUF',
      file:  'tinystories-656k-q8_0.gguf',
    },
    {
      label: 'tinyllama-15M-stories (~15 MB)',
      repo:  'tensorblock/tinyllama-15M-stories-GGUF',
      file:  'tinyllama-15M-stories-Q8_0.gguf',
    },
    {
      label: 'SmolLM2-135M Q8 (~145 MB)',
      repo:  'HuggingFaceTB/SmolLM2-135M-Instruct-GGUF',
      file:  'smollm2-135m-instruct-q8_0.gguf',
    },
    {
      label: 'SmolLM2-360M Q8 (~380 MB)',
      repo:  'HuggingFaceTB/SmolLM2-360M-Instruct-GGUF',
      file:  'smollm2-360m-instruct-q8_0.gguf',
    },
    {
      label: 'Qwen2.5-0.5B Q4_K_M (~400 MB)',
      repo:  'Qwen/Qwen2.5-0.5B-Instruct-GGUF',
      file:  'qwen2.5-0.5b-instruct-q4_k_m.gguf',
    },
  ];
  const TINYSTORIES_INDEX = 0;  /* shortcut button target */
  const CDN_ESM = 'https://cdn.jsdelivr.net/npm/@wllama/wllama@2/esm/index.js';
  const CDN_WASM = 'https://cdn.jsdelivr.net/npm/@wllama/wllama@2/esm/wasm-from-cdn.js';

  let wllama = null;
  let loadingModel = false;
  let uiMounted = false;

  function isLoaded() {
    try { return !!(wllama && wllama.isModelLoaded && wllama.isModelLoaded()); }
    catch (_) { return false; }
  }

  function mountUI() {
    if (uiMounted) return;
    const out = document.getElementById('cast-output');
    if (!out) return;
    uiMounted = true;
    const wrap = document.createElement('div');
    wrap.id = 'cast-gguf-ui';
    wrap.style.marginTop = '0.8em';
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = '0.5em';
    const presetOpts = PRESETS.map((p, i) =>
      `<option value="${i}">${p.label}</option>`).join('');
    wrap.innerHTML = `
      <div style="display:flex;gap:.5em;flex-wrap:wrap;align-items:center">
        <button id="cast-gguf-tinystories" class="cast-chip" type="button"
                style="font-weight:bold">⚡ load TinyStories-656K (~1 MB)</button>
        <span style="opacity:0.5">or pick a preset:</span>
        <select id="cast-gguf-preset" class="cast-chip">${presetOpts}</select>
        <button id="cast-gguf-load"        class="cast-chip" type="button">load preset</button>
        <span id="cast-gguf-status" style="opacity:0.7;font-size:0.9em"></span>
      </div>
      <div style="display:flex;gap:.5em;align-items:flex-start">
        <textarea id="cast-gguf-prompt" rows="3" style="flex:1;min-width:20em;font-family:inherit;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:0.4em">Once upon a time there was a tiny</textarea>
        <div style="display:flex;flex-direction:column;gap:.3em">
          <button id="cast-gguf-gen"  class="cast-chip" type="button">generate 64 tokens</button>
          <button id="cast-gguf-stop" class="cast-chip" type="button" disabled>stop</button>
        </div>
      </div>
    `;
    out.insertAdjacentElement('afterend', wrap);
    function wire(id, label, fn) {
      const el = document.getElementById(id);
      if (!el) { console.warn('[gguf] missing element:', id); return; }
      el.addEventListener('click', function (ev) {
        console.log('[gguf] click:', label);
        setStatus(label + '... (see console for details)');
        try {
          const r = fn(ev);
          if (r && r.catch) r.catch(err => {
            console.error('[gguf] ' + label + ' async error:', err);
            setStatus(label + ' failed: ' + (err && err.message || err));
          });
        } catch (err) {
          console.error('[gguf] ' + label + ' sync error:', err);
          setStatus(label + ' failed: ' + (err && err.message || err));
        }
      });
    }
    wire('cast-gguf-load', 'load preset',  doLoad);
    wire('cast-gguf-gen',  'generate',     doGenerate);
    wire('cast-gguf-stop', 'stop',         doStop);
    wire('cast-gguf-tinystories', 'load TinyStories', function () {
      const sel = document.getElementById('cast-gguf-preset');
      sel.value = String(TINYSTORIES_INDEX);
      return doLoad();
    });
    setStatus('ui mounted. click ⚡ or pick a preset.');
  }
  function setStatus(msg) {
    const el = document.getElementById('cast-gguf-status');
    if (el) el.textContent = msg;
    /* Also mirror into a second always-visible line above the prompt so the
     * user doesn't have to hunt for the small fine-print status span. */
    let big = document.getElementById('cast-gguf-status-big');
    if (!big) {
      const wrap = document.getElementById('cast-gguf-ui');
      if (wrap) {
        big = document.createElement('pre');
        big.id = 'cast-gguf-status-big';
        big.style.margin = '0';
        big.style.padding = '0.3em 0.5em';
        big.style.background = '#0d1117';
        big.style.color = '#58a6ff';
        big.style.border = '1px solid #30363d';
        big.style.fontFamily = 'inherit';
        big.style.whiteSpace = 'pre-wrap';
        wrap.appendChild(big);
      }
    }
    if (big) big.textContent = '[status] ' + msg;
  }
  function setOut(text) {
    const out = document.getElementById('cast-output');
    if (out) out.textContent = text;
  }

  async function ensureWllama() {
    if (wllama) return wllama;
    setStatus('importing wllama from CDN...');
    const mod       = await import(CDN_ESM);
    const wasmCdn   = await import(CDN_WASM);
    const Wllama    = mod.Wllama;
    const WasmPaths = wasmCdn.WasmFromCDN || wasmCdn.default;
    wllama = new Wllama(WasmPaths);
    setStatus('wllama ready');
    return wllama;
  }

  async function doLoad() {
    if (loadingModel) return;
    loadingModel = true;
    try {
      const idx  = Number(document.getElementById('cast-gguf-preset').value);
      const cfg  = PRESETS[idx];
      await ensureWllama();
      /* If the wllama instance already has a model loaded (from a previous
       * preset), tear it down before loading a new one. */
      try { if (isLoaded() && wllama.exit) await wllama.exit(); } catch (_) {}
      setStatus(`[v3] downloading ${cfg.file}...`);
      setOut(`[gguf.js v3]\nloading ${cfg.label}\nrepo: ${cfg.repo}\nfile: ${cfg.file}\n\n(first time: browser downloads and caches the GGUF;\nsubsequent loads hit HTTP cache and skip download entirely)`);
      let phase = 'fetching';
      let lastPct = '?';
      const tStart = Date.now();
      const initBeacon = setInterval(() => {
        const secs = ((Date.now() - tStart) / 1000).toFixed(1);
        setStatus(`[${secs}s] ${phase} ${cfg.file} — ${lastPct}`);
      }, 500);
      try {
        await wllama.loadModelFromHF(cfg.repo, cfg.file, {
          n_threads: 1,   /* avoid SharedArrayBuffer / COOP-COEP requirement */
          progressCallback: ({ loaded, total }) => {
            lastPct = total ? (100 * loaded / total).toFixed(1) + '%' : '? bytes';
            if (total && loaded >= total) phase = 'initializing WASM (no progress events)';
          },
        });
      } finally {
        clearInterval(initBeacon);
      }
      console.log('[gguf] loadModelFromHF resolved. isModelLoaded():', isLoaded());
      window.__wllama = wllama;   /* for console debugging */
      if (!isLoaded()) {
        throw new Error('wllama.isModelLoaded() still false after loadModelFromHF resolved');
      }
      setStatus(`loaded ${cfg.file}. enter a prompt and generate.`);
      setOut(`loaded ${cfg.label}\nready. type a prompt above and click "generate 64 tokens".`);
    } catch (e) {
      const msg = 'load failed: ' + (e && (e.message || e.toString()) || 'unknown error');
      setStatus(msg);
      setOut(msg + '\n\nif this mentions SharedArrayBuffer or cross-origin isolation,\n'
                 + 'the browser needs COOP/COEP headers that Django\'s runserver does\n'
                 + 'not set by default. The n_threads:1 config should avoid that;\n'
                 + 'if you still hit it, serve the page behind a proxy that sets:\n'
                 + '  Cross-Origin-Opener-Policy: same-origin\n'
                 + '  Cross-Origin-Embedder-Policy: require-corp');
    } finally {
      loadingModel = false;
    }
  }

  let stopFlag = false;

  async function doGenerate() {
    if (!isLoaded()) {
      setStatus('no model loaded — click ⚡ or "load preset" first and wait for "loaded ..."');
      setOut('no model loaded yet.\n\n'
           + 'click ⚡ "load TinyStories-656K" above (or pick a preset and click\n'
           + '"load preset"), wait for the status line to say "loaded ...", then\n'
           + 'click "generate 64 tokens" again.');
      return;
    }
    const prompt = document.getElementById('cast-gguf-prompt').value;
    setOut(prompt);
    stopFlag = false;
    document.getElementById('cast-gguf-stop').disabled = false;
    document.getElementById('cast-gguf-gen').disabled  = true;
    try {
      await wllama.createCompletion(prompt, {
        nPredict: 64,
        sampling: { temp: 0.7, top_k: 40, top_p: 0.95 },
        onNewToken: (token, piece, currentText, { abortSignal }) => {
          setOut(currentText);
          if (stopFlag) abortSignal && abortSignal.abort && abortSignal.abort();
        },
      });
    } catch (e) {
      setStatus('generate failed: ' + (e.message || e));
    } finally {
      document.getElementById('cast-gguf-stop').disabled = true;
      document.getElementById('cast-gguf-gen').disabled  = false;
    }
  }
  function doStop() { stopFlag = true; }

  function run() {
    mountUI();
    const info = [
      'GGUF WASM loader — in-browser inference via wllama (llama.cpp).',
      '',
      'Fastest path: click ⚡ "load TinyStories-656K" — a ~1 MB GGUF of a',
      '656 K-parameter model trained on short children\'s stories. Loads',
      'almost instantly and generates coherent (if childish) completions.',
      '',
      'Or pick a larger preset from the dropdown and click "load preset"',
      '(first load downloads 15-400 MB from Hugging Face).',
      '',
      'What this demonstrates:',
      '  - Real transformer inference runs in the browser via WebAssembly.',
      '  - The GGUF format is a transformer serialization. Any GGUF that',
      '    llama.cpp supports will load here, including your own trained',
      '    ones if you export them from PyTorch → HF → GGUF.',
      '  - The Casting project does NOT produce these models. They come',
      '    from Hugging Face and are thousands-to-millions of parameters',
      '    larger than anything Casting can brute-force.',
      '',
      'Why this matters to Casting:',
      '  - This is the reference "functional drop-in model" you asked about.',
      '  - It proves GGUF can live in-browser. It also proves the size gap',
      '    between "things brute-force bit search can find" (~22 bits) and',
      '    "things that produce coherent text" (~100M bits).',
    ];
    return info.join('\n');
  }

  window.Casting_byte_model_gguf = { run };
})();

/* Casting: byte_model_tinyllm_train — browser-visible front page for
 * the cluster-training recipe. "Run once" shows a summary; the page
 * also mounts a set of download chips, one per recipe file, under the
 * output pre so you can grab them with a click.
 */
(function () {
  const RECIPE_BASE = '/static/casting/recipes/tinyllm/';
  const FILES = [
    { name: 'README.md',         blurb: 'step-by-step instructions' },
    { name: 'train.py',          blurb: 'minimal GPT-2 trainer (PyTorch + HF transformers)' },
    { name: 'slurm.sh',          blurb: 'SLURM job file — sbatch slurm.sh' },
    { name: 'convert.sh',        blurb: 'HF checkpoint → tinyllm.gguf via llama.cpp' },
    { name: 'requirements.txt',  blurb: 'pip install -r this first' },
    { name: 'sample_corpus.txt', blurb: 'tiny corpus for a 5-minute local smoke test' },
  ];

  function mountChips() {
    const out = document.getElementById('cast-output');
    if (!out) return;
    if (document.getElementById('cast-tinyllm-chips')) return;
    const wrap = document.createElement('div');
    wrap.id = 'cast-tinyllm-chips';
    wrap.style.marginTop = '0.8em';
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = '0.3em';
    for (const f of FILES) {
      const row = document.createElement('div');
      row.style.display = 'flex';
      row.style.gap = '0.6em';
      row.style.alignItems = 'center';
      const a = document.createElement('a');
      a.className = 'cast-chip';
      a.href = RECIPE_BASE + f.name;
      a.download = f.name;
      a.textContent = 'download ' + f.name;
      const span = document.createElement('span');
      span.style.opacity = '0.7';
      span.style.fontSize = '0.9em';
      span.textContent = f.blurb;
      row.appendChild(a);
      row.appendChild(span);
      wrap.appendChild(row);
    }
    out.insertAdjacentElement('afterend', wrap);
  }

  function run() {
    mountChips();
    const lines = [
      'Tiny LLM — cluster training recipe (not runnable in the browser)',
      '',
      'Pipeline:',
      '  corpus  ->  train.py (SLURM / GPU)  ->  HF checkpoint',
      '                                    |',
      '                                    v',
      '                          convert.sh  ->  tinyllm.gguf',
      '                                    |',
      '                                    v',
      '                  load in the gguf-wasm Casting experiment,',
      '                  or ollama / llama.cpp / any GGUF consumer.',
      '',
      'Defaults (slurm.sh + train.py):',
      '  model:     GPT-2 architecture, 192 embed, 4 layers, 4 heads',
      '  params:    ~11 M (mostly in the 50257-token embedding table)',
      '  corpus:    TinyStories (first 5%), ~25 M tokens',
      '  steps:     4000, batch 16, block 256',
      '  eta:       ~30 min on H100, ~1 hr on A100',
      '  output:    tinyllm-out/ (HF) + tinyllm.gguf (~40 MB fp16)',
      '',
      'Smoke test (no cluster required):',
      '  pip install -r requirements.txt',
      '  python train.py --steps 200 --batch 4 --block 128 \\',
      '                  --n_embd 96 --n_layer 2 --n_head 4 \\',
      '                  --corpus sample_corpus.txt',
      '  bash convert.sh tinyllm-out',
      '  # result: a ~5 MB tinyllm.gguf that overfits the toy corpus.',
      '',
      'Why this is in Casting:',
      '  Casting finds boolean circuits by brute-force bit search. That',
      '  ceiling is ~22 bits in-browser, maybe ~40-50 on a cluster. A',
      '  working transformer needs ~10^8 bits of structure. Gradient',
      '  descent — not search — is the bridge. This recipe IS that bridge.',
      '',
      'Download the recipe files below, adjust slurm.sh for your cluster',
      '(module loads, account/partition names), and run.',
    ];
    return lines.join('\n');
  }

  window.Casting_byte_model_tinyllm_train = { run };
})();

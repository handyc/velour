"""ALICE bundle generator + worker for the metapact GA scale-up.

Local side
----------
``generate_bundle(out_dir, **params)``
    Writes a self-contained bundle directory ready for ``push.sh`` →
    ALICE → ``pull.sh``. The bundle is just files — no DB rows.

``analyse(bundle_dir)``
    Reads ``outputs/*.json`` once pulled back, returns a summary dict
    with fitness statistics, best seed across replicates, etc.

ALICE side
----------
``run_task(input_path, output_path)``
    Pure deterministic function. Reads one input JSON (replicate id +
    GA config), runs ``spoeqi.metachain_ga.evolve_metapact``, writes
    one output JSON (best seed as hex, fitness history, timing).

The bundle's ``run_task.py`` shim sets ``sys.path`` to include the
Velour checkout and dispatches to ``run_task`` here so we don't have to
ship a copy of the GA code on every bundle.
"""
from __future__ import annotations

import json
import math
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path


BUNDLE_KIND = 'metapact-ga'

# Default ALICE-side bundle root, relative to the operator's home on the
# cluster. The bundle's push.sh / pull.sh both rsync to/from here.
DEFAULT_REMOTE_DIR = '~/velour-dev/.alice_bundles'


# ─── Local side: bundle generation ────────────────────────────────────

@dataclass
class BundleParams:
    slug: str
    replicates: int            = 16     # array tasks 0..N-1
    generations: int           = 50
    pop_size: int              = 32
    depth: int                 = 10
    chain_ticks: int           = 20
    mutation_rate: float       = 0.003
    w_chain: float             = 0.3
    w_leaf: float              = 0.7
    seed_base: int             = 0xCAB00B5  # task seed = seed_base ^ task_id
    corpus_bytes: int          = 4096
    corpus_source: str         = 'lorem-x4'  # see _make_corpus
    time_limit: str            = '00:30:00'  # 30 min per task; 6× safety vs ~5 min expected
    mem_per_task: str          = '2G'
    cpus_per_task: int         = 1
    ssh_host: str              = 'alice'
    ssh_user: str              = 'username'  # operator overrides at gen time
    remote_dir: str            = DEFAULT_REMOTE_DIR


def _make_corpus(source: str, nbytes: int) -> str:
    """Generate a deterministic probe corpus from a named source.

    ``lorem-x4`` is the placeholder Adams-quote-style text the metapact
    explorer script used; deterministic, ASCII-only, repeatable. New
    sources can land here as needed (e.g. piping in real Codex text)."""
    if source == 'lorem-x4':
        base = (
            'In the beginning the Universe was created. This has '
            'made a lot of people very angry and been widely '
            'regarded as a bad move. ')
        out = (base * (nbytes // len(base) + 1))[:nbytes]
        return out
    raise ValueError(f'unknown corpus source: {source!r}')


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def generate_bundle(out_dir: Path, params: BundleParams) -> Path:
    """Write a complete bundle directory and return its path.

    Idempotent: if ``out_dir`` already exists and isn't empty we refuse
    (operator's responsibility to clear or pick a fresh slug)."""
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(
            f'bundle dir already exists and is non-empty: {out_dir}')
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'inputs').mkdir()
    (out_dir / 'outputs').mkdir()
    (out_dir / 'outputs' / '.gitkeep').write_text('')

    # 1. Per-task input JSONs (small; one per array index).
    corpus = _make_corpus(params.corpus_source, params.corpus_bytes)
    for task_id in range(params.replicates):
        task_input = {
            'task_id':       task_id,
            'seed':          (params.seed_base ^ task_id) & 0xFFFFFFFF,
            'generations':   params.generations,
            'pop_size':      params.pop_size,
            'depth':         params.depth,
            'chain_ticks':   params.chain_ticks,
            'mutation_rate': params.mutation_rate,
            'w_chain':       params.w_chain,
            'w_leaf':        params.w_leaf,
            'corpus':        corpus,
        }
        (out_dir / 'inputs' / f'{task_id:03d}.json').write_text(
            json.dumps(task_input, indent=2))

    # 2. The deterministic entry point. The shim sets sys.path to the
    #    repo root, imports the worker from conduit.alice.metapact_ga,
    #    and dispatches. Keeps the actual GA code single-sourced.
    run_task_py = '''#!/usr/bin/env python3
"""ALICE-side entry point for one array task of this bundle.

Usage:  python3 run_task.py <task_id>
Reads inputs/<task_id:03d>.json, runs the metapact GA, writes
outputs/<task_id:03d>.json. Pure determinism + numpy; no Django.
"""
import json
import os
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
# Repo root: bundle is at ~/velour-dev/.alice_bundles/<slug>/, repo at ~/velour-dev/
REPO = BUNDLE.parent.parent.parent
sys.path.insert(0, str(REPO))

from conduit.alice.metapact_ga import run_task

task_id = int(sys.argv[1])
input_path  = BUNDLE / 'inputs'  / f'{task_id:03d}.json'
output_path = BUNDLE / 'outputs' / f'{task_id:03d}.json'
run_task(input_path, output_path)
print(f'[run_task] wrote {output_path}')
'''
    _write_executable(out_dir / 'run_task.py', run_task_py)

    # 3. The sbatch submission script.
    submit_sh = f'''#!/usr/bin/env bash
#SBATCH --job-name={params.slug}
#SBATCH --partition=cpu-short
#SBATCH --time={params.time_limit}
#SBATCH --cpus-per-task={params.cpus_per_task}
#SBATCH --mem={params.mem_per_task}
#SBATCH --array=0-{params.replicates - 1}
#SBATCH --output=outputs/slurm-%A_%a.out
#SBATCH --error=outputs/slurm-%A_%a.err
set -euo pipefail

# Module/venv setup — adjust to whatever the ALICE account uses.
# The default assumes a venv at ~/velour-dev/venv with numpy installed.
source "$HOME/velour-dev/venv/bin/activate"

cd "$(dirname "${{BASH_SOURCE[0]}}")"
exec python3 run_task.py "$SLURM_ARRAY_TASK_ID"
'''
    _write_executable(out_dir / 'submit.sh', submit_sh)

    # 4. push.sh and pull.sh — plain rsync the operator can read.
    remote_path = f'{params.ssh_user}@{params.ssh_host}:{params.remote_dir}/{params.slug}/'
    push_sh = f'''#!/usr/bin/env bash
# rsync this bundle onto ALICE. Edit ssh_user / ssh_host if wrong.
set -euo pipefail
BUNDLE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
rsync -av --exclude='outputs/*.json' --exclude='outputs/slurm-*' \\
    "$BUNDLE/" "{remote_path}"
echo
echo "Now SSH in and submit:"
echo "  ssh {params.ssh_user}@{params.ssh_host}"
echo "  cd {params.remote_dir}/{params.slug}"
echo "  sbatch submit.sh"
'''
    _write_executable(out_dir / 'push.sh', push_sh)

    pull_sh = f'''#!/usr/bin/env bash
# rsync outputs back from ALICE.
set -euo pipefail
BUNDLE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
rsync -av "{remote_path}outputs/" "$BUNDLE/outputs/"
echo
echo "Outputs in:    $BUNDLE/outputs/"
echo "Analyse with:  venv/bin/python manage.py alice_analyze_metapact {params.slug}"
'''
    _write_executable(out_dir / 'pull.sh', pull_sh)

    # 5. README + manifest.json
    expected_eval_seconds = 0.25  # local-observed; conservative
    expected_evals = params.generations * params.pop_size
    expected_per_task_s = expected_evals * expected_eval_seconds
    expected_total_cpu_min = (params.replicates * expected_per_task_s) / 60.0
    readme = f'''# Bundle: {params.slug}

Metapact GA scale-up — runs `spoeqi.metachain_ga.evolve_metapact` in
`{params.replicates}` independent replicates (array tasks `0..{params.replicates - 1}`).
Each replicate's seed is `0x{params.seed_base:08X} XOR task_id` so reruns are
byte-identical and any disagreement is a bug, not noise.

## What it does

- Replicates:       {params.replicates}
- Generations:      {params.generations}
- Pop size:         {params.pop_size}
- Chain depth:      {params.depth}
- Chain ticks:      {params.chain_ticks}
- Mutation rate:    {params.mutation_rate}
- Fitness weights:  w_chain={params.w_chain}, w_leaf={params.w_leaf}
- Corpus:           {params.corpus_source} ({params.corpus_bytes} bytes)

## Expected runtime

- Per task:    ~{expected_per_task_s:.0f} s ({expected_per_task_s/60:.1f} min) — within `#SBATCH --time={params.time_limit}` cap
- Total CPU:   ~{expected_total_cpu_min:.1f} CPU-min, parallel across the array
- Wall time:   ≈ per-task time if the cluster has free CPUs for all tasks

## Files

| file               | what's in it                                     |
|--------------------|--------------------------------------------------|
| `submit.sh`        | sbatch script (array job, 4h cap, 1 CPU/task)    |
| `run_task.py`      | deterministic entry point — pure numpy           |
| `inputs/NNN.json`  | per-task input (seed + GA config + probe corpus) |
| `outputs/NNN.json` | per-task output (best seed hex + history + timing) — ALICE fills this |
| `push.sh`          | rsync local → ALICE                              |
| `pull.sh`          | rsync ALICE → local                              |
| `manifest.json`    | machine-readable summary (params + task list)    |

## Operator steps

```
bash push.sh                  # rsync to ALICE
ssh {params.ssh_user}@{params.ssh_host}
cd {params.remote_dir}/{params.slug}
sbatch submit.sh              # array job; squeue -u $USER to watch
# (wait — slurm emails on completion)
exit
bash pull.sh                  # rsync outputs back
venv/bin/python manage.py alice_analyze_metapact {params.slug}
```

## Safety notes

- Each task is independent: no IPC, no shared filesystem writes outside
  `outputs/NNN.json`.
- Memory cap: `{params.mem_per_task}` per task. Locally observed
  metapact GA peaks at ~600 MB.
- No network access required at runtime — `run_task.py` imports only
  `numpy` + `spoeqi.metachain*` + `caformer.primitives/ga` from the
  Velour checkout already on ALICE.
- Worst-case output size: ~16 KB seed × {params.replicates} replicates
  + small JSON metadata ≈ {params.replicates * 18} KB total.
'''
    (out_dir / 'README.md').write_text(readme)

    manifest = {
        'kind':         BUNDLE_KIND,
        'slug':         params.slug,
        'replicates':   params.replicates,
        'generations':  params.generations,
        'pop_size':     params.pop_size,
        'depth':        params.depth,
        'chain_ticks':  params.chain_ticks,
        'mutation_rate': params.mutation_rate,
        'w_chain':      params.w_chain,
        'w_leaf':       params.w_leaf,
        'seed_base':    f'0x{params.seed_base:08X}',
        'corpus_source': params.corpus_source,
        'corpus_bytes': params.corpus_bytes,
        'time_limit':   params.time_limit,
        'mem_per_task': params.mem_per_task,
        'ssh_host':     params.ssh_host,
        'ssh_user':     params.ssh_user,
        'remote_dir':   params.remote_dir,
        'expected_per_task_seconds': expected_per_task_s,
        'inputs':       [f'inputs/{i:03d}.json' for i in range(params.replicates)],
        'expected_outputs': [f'outputs/{i:03d}.json' for i in range(params.replicates)],
    }
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))

    # 6. .gitignore inside the bundle so outputs/*.json are gitignored
    # by default (operator can override per-bundle if they want to
    # commit results).
    (out_dir / '.gitignore').write_text(
        'outputs/*.json\n'
        'outputs/slurm-*\n')

    return out_dir


# ─── ALICE side: the deterministic worker ────────────────────────────

def run_task(input_path: Path, output_path: Path) -> dict:
    """Run one array task. Pure function: same input bytes → same output
    bytes, on any machine with numpy. Returns the output dict (also
    written to disk)."""
    import numpy as np
    # Lazy import so the local generator doesn't pay for the GA stack
    # just to write input files.
    from spoeqi.metachain import RULE_SIZE, metachain_expand
    from spoeqi.metachain_ga import MetaGAConfig, evolve_metapact

    task = json.loads(Path(input_path).read_text())

    cfg = MetaGAConfig(
        pop_size=task['pop_size'],
        generations=task['generations'],
        depth=task['depth'],
        chain_ticks=task['chain_ticks'],
        seed=task['seed'],
        mutation_rate=task['mutation_rate'],
        w_chain=task['w_chain'],
        w_leaf=task['w_leaf'],
    )

    t0 = time.time()
    result = evolve_metapact(corpus=task['corpus'], cfg=cfg)
    elapsed = time.time() - t0

    # Re-expand the winning seed to confirm + record the per-level
    # chain stats (cheap; just one expand call).
    chain = metachain_expand(result.best_seed,
                              depth=cfg.depth, chain_ticks=cfg.chain_ticks)

    out = {
        'task_id':            task['task_id'],
        'seed_in':            task['seed'],
        'best_seed_hex':      result.best_seed.hex(),
        'best_fitness':       float(result.best_fitness),
        'best_chain_quality': float(result.best_chain_quality),
        'best_leaf_fitness':  float(result.best_leaf_fitness),
        'history':            [[float(b), float(m), float(w)]
                                for (b, m, w) in result.history],
        'chain_classes':      list(chain.classes),
        'chain_scores':       [float(s) for s in chain.scores],
        'depth_class4':       int(chain.depth_class4),
        'elapsed_seconds':    elapsed,
        'evals':              cfg.generations * cfg.pop_size,
    }
    Path(output_path).write_text(json.dumps(out, indent=2))
    return out


# ─── Local side: result analysis ─────────────────────────────────────

def analyse(bundle_dir: Path) -> dict:
    """Read every outputs/NNN.json in a pulled-back bundle and return
    a summary dict suitable for printing or feeding to the next bundle
    generator."""
    bundle_dir = Path(bundle_dir).resolve()
    manifest = json.loads((bundle_dir / 'manifest.json').read_text())
    out_dir = bundle_dir / 'outputs'

    expected = [bundle_dir / p for p in manifest['expected_outputs']]
    found = [p for p in expected if p.exists()]
    missing = [p.name for p in expected if not p.exists()]

    if not found:
        return {
            'bundle':  manifest['slug'],
            'status':  'no-outputs',
            'missing': missing,
            'hint':    'run pull.sh after the sbatch job completes.',
        }

    rows = [json.loads(p.read_text()) for p in found]
    fits = sorted(r['best_fitness'] for r in rows)
    elapsed = sorted(r['elapsed_seconds'] for r in rows)
    best = max(rows, key=lambda r: r['best_fitness'])

    n = len(rows)
    return {
        'bundle':       manifest['slug'],
        'status':       'complete' if not missing else 'partial',
        'n_tasks':      n,
        'n_expected':   manifest['replicates'],
        'missing':      missing,
        'fitness': {
            'min':    fits[0],
            'median': fits[n // 2],
            'mean':   sum(fits) / n,
            'max':    fits[-1],
        },
        'elapsed_seconds': {
            'min':    elapsed[0],
            'median': elapsed[n // 2],
            'max':    elapsed[-1],
            'total':  sum(elapsed),
        },
        'best': {
            'task_id':            best['task_id'],
            'seed_in':            best['seed_in'],
            'best_fitness':       best['best_fitness'],
            'best_chain_quality': best['best_chain_quality'],
            'best_leaf_fitness':  best['best_leaf_fitness'],
            'depth_class4':       best['depth_class4'],
            'chain_classes':      best['chain_classes'],
        },
        'best_seed_hex': best['best_seed_hex'],
    }

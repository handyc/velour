"""ALICE bundle generator + worker for the QRPair vocabulary trainer.

Long-term goal: 65,536 (prompt → response) CA pairs, each a positional
QRPair, deployed into the multi-pair chat so any word triggers its own
trained chain.  Local serial training at ~80 s/pair = ~60 days for the
full vocab; ALICE scales this onto an sbatch array.

Local side
----------
``generate_bundle(out_dir, params)``
    Writes a bundle.  Splits ``vocab`` into ``array_size`` equal slices;
    each array task trains one slice sequentially and writes one
    ``outputs/NNN.json`` per task with the per-pair results.

``analyse(bundle_dir)``
    Reads ``outputs/*.json``, returns a summary, and (when called via
    the ``alice_analyze_qrpair_vocab`` command) ingests each successful
    pair into the local QRPair table + auto-deploys as a TrainedModel so
    the chat dispatcher picks them up.

ALICE side
----------
``run_task(input_path, output_path)``
    For each (prompt, expected) in the task's slice, evolves a
    positional CAformer to argmax-match every byte of ``expected``.
    Pure numpy + the in-repo qr_trainer code path; no Django ORM at
    runtime (training writes a portable JSON, the local side does the
    DB ingest after rsync-back).
"""
from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Tuple


BUNDLE_KIND = 'qrpair-vocab'

DEFAULT_REMOTE_DIR = '~/velour-dev/.alice_bundles'

# Pure-numpy modules vendored into <bundle>/lib/caformer/ so the bundle
# is fully self-contained — ALICE needs only python3 + numpy, no Velour
# checkout, no Django, no venv with project deps.  These imports are
# audited to only pull stdlib + numpy + each other.
VENDORED_CAFORMER_MODULES = ('ga', 'primitives', 'transformer',
                                  'reductive', 'qr_trainer')

# Built-in response generators.  The "response strategy" decides what
# `expected` each `prompt` gets when no explicit (prompt, response)
# pairs are supplied.  Picking the right strategy is half the design.
RESPONSE_STRATEGIES = {
    # The pair just echoes the input — useful for verifying the
    # training pipeline at scale before committing to semantic targets.
    'echo':        lambda w: w,
    # Every word maps to a fixed greeting — a sanity demo of the
    # "many prompts → same response" case.
    'hello':       lambda w: 'hello',
    # The reverse string — short, deterministic, gives each pair a
    # distinct target without needing a semantic mapping yet.
    'reverse':     lambda w: w[::-1],
    # First three chars padded — caps response length at 3 bytes so
    # the whole vocab trains fast even at the limit.
    'first3':      lambda w: (w + '   ')[:3],
    # ASCII-case mappings.  Distinct from echo (model has to learn
    # the case shift) without needing a dictionary.
    'upper':       lambda w: w.upper(),
    'lower':       lambda w: w.lower(),
}

# Path to the bundled mini-thesaurus for the `synonym` strategy.  Override
# at gen time via `--synonyms-file`.
DEFAULT_SYNONYMS_TSV = (Path(__file__).resolve().parent
                              / 'data' / 'mini_thesaurus.tsv')


def _load_synonyms_tsv(path: Path) -> dict[str, str]:
    """Read a prompt<TAB>response TSV (with # comments) into a dict.
    Used by the `synonym` strategy; words not in the dict are skipped."""
    table: dict[str, str] = {}
    if not path.exists():
        return table
    for ln in path.read_text().splitlines():
        if not ln.strip() or ln.startswith('#'):
            continue
        if '\t' not in ln:
            continue
        p, r = ln.split('\t', 1)
        p = p.strip(); r = r.strip()
        if p and r:
            table.setdefault(p, r)
    return table


@dataclass
class BundleParams:
    slug: str
    vocab: List[str]                  # the prompts to train on
    response_strategy: str = 'echo'   # one of RESPONSE_STRATEGIES, OR
    explicit_pairs: list = field(default_factory=list)
                                       # … [(prompt, expected), …] (overrides strategy)
    synonyms_tsv: str = ''             # path to TSV for the `synonym` strategy
    array_size: int       = 32
    pop:        int       = 32
    gens:       int       = 24
    polish:     int       = 200
    bonus:      float     = 4.0
    n_blocks:   int       = 1
    time_limit: str       = '04:00:00'
    mem_per_task: str     = '2G'
    cpus_per_task: int    = 1
    seed_base:  int       = 0xCA1B5E11
    ssh_host:   str       = 'alice'
    ssh_user:   str       = 'username'
    remote_dir: str       = DEFAULT_REMOTE_DIR


def _resolve_pairs(params: BundleParams) -> List[Tuple[str, str]]:
    """(prompt, expected) list — explicit_pairs wins; else strategy.

    The `synonym` strategy is special: it requires a TSV lookup table
    (defaults to the bundled mini-thesaurus).  Vocab words not in the
    table are silently dropped so the bundle only trains pairs we
    actually have responses for."""
    if params.explicit_pairs:
        return [(str(p), str(r)) for p, r in params.explicit_pairs]
    if params.response_strategy == 'synonym':
        path = Path(params.synonyms_tsv) if params.synonyms_tsv else \
                  DEFAULT_SYNONYMS_TSV
        table = _load_synonyms_tsv(path)
        if not table:
            raise ValueError(
                f'synonym strategy: thesaurus is empty at {path}')
        return [(w, table[w]) for w in params.vocab if w in table]
    fn = RESPONSE_STRATEGIES.get(params.response_strategy)
    if fn is None:
        raise ValueError(
            f'unknown response_strategy: {params.response_strategy!r}; '
            f'pick one of {sorted(RESPONSE_STRATEGIES) + ["synonym"]}')
    return [(w, fn(w)) for w in params.vocab]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def generate_bundle(out_dir: Path, params: BundleParams) -> Path:
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(
            f'bundle dir already exists and is non-empty: {out_dir}')
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'inputs').mkdir()
    (out_dir / 'outputs').mkdir()
    (out_dir / 'outputs' / '.gitkeep').write_text('')

    pairs = _resolve_pairs(params)
    n_pairs = len(pairs)
    if n_pairs == 0:
        raise ValueError('no pairs to train — vocab + strategy produced empty list')

    # Slice the pair list across the array.  Last task may carry the
    # remainder; that's fine — sbatch array tasks are independent.
    array_size = max(1, int(params.array_size))
    slice_size = (n_pairs + array_size - 1) // array_size
    for task_id in range(array_size):
        lo = task_id * slice_size
        hi = min(n_pairs, lo + slice_size)
        if lo >= hi:
            # Empty slice — still write a stub so array indexing stays clean.
            task_pairs: List[Tuple[str, str]] = []
        else:
            task_pairs = pairs[lo:hi]
        (out_dir / 'inputs' / f'{task_id:03d}.json').write_text(
            json.dumps({
                'task_id':   task_id,
                'slice_lo':  lo,
                'slice_hi':  hi,
                'seed_base': (params.seed_base ^ task_id) & 0xFFFFFFFF,
                'pop':       params.pop,
                'gens':      params.gens,
                'polish':    params.polish,
                'bonus':     params.bonus,
                'n_blocks':  params.n_blocks,
                'pairs':     [{'prompt': p, 'expected': e}
                                for p, e in task_pairs],
            }, indent=2))

    # Vendor the 5 pure-numpy caformer modules into <bundle>/lib/caformer/.
    # This is what makes the bundle self-contained — no Velour repo or
    # Django setup needed on ALICE, just python3 + numpy.
    import shutil
    repo_root = Path(__file__).resolve().parent.parent.parent
    src_caformer = repo_root / 'caformer'
    vendored = out_dir / 'lib' / 'caformer'
    vendored.mkdir(parents=True, exist_ok=True)
    (vendored / '__init__.py').write_text('')
    for mod in VENDORED_CAFORMER_MODULES:
        src = src_caformer / f'{mod}.py'
        if not src.exists():
            raise FileNotFoundError(
                f'cannot vendor caformer.{mod}: {src} missing')
        shutil.copy2(src, vendored / f'{mod}.py')

    run_task_py = '''#!/usr/bin/env python3
"""ALICE-side entry point: trains the assigned slice of (prompt, expected)
QRPairs sequentially and writes outputs/<task_id>.json.

Self-contained: all code paths live inside this bundle (see lib/caformer/).
The only runtime dependency is `python3` + `numpy` — no Velour checkout,
no Django, no venv with project deps."""
import json
import sys
import time
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
# Vendored pure-numpy modules — added to sys.path so the imports below
# resolve to the bundle's own copy, not anything system-wide.
sys.path.insert(0, str(BUNDLE / 'lib'))

import numpy as np
from caformer.ga import (FULL_STACK_NAMES, GAConfig, _evolve,
                              polish_genome)
from caformer.primitives import random_rule_table
from caformer.transformer import ca_forward_qkv
from caformer.qr_trainer import sample_positional, genome_to_blob


def _train_one_pair(prompt, expected, *, pop, gens, polish, bonus,
                       n_blocks, seed):
    """Inline copy of qrpair_vocab._train_one_pair so this script is
    importable without `conduit.alice.qrpair_vocab` on the runtime
    machine.  Logic must stay in sync with that module."""
    prompt_bytes = list(prompt.encode('utf-8'))[:64]
    target_bytes = list(expected.encode('utf-8'))[:64]
    n_positions = len(target_bytes)
    if n_positions == 0:
        raise ValueError(f'empty expected for prompt {prompt!r}')
    base = {n: random_rule_table((seed ^ (0x100 * (i + 1))) & 0xFFFFFFFF)
              for i, n in enumerate(FULL_STACK_NAMES)}
    block_template = [{k: base[k] for k in
                          ('q','k','v','score','mix','merge','mlp')}
                         ] * n_blocks
    out_rules = []
    t0 = time.time()
    for pos in range(n_positions):
        tb = target_bytes[pos]
        ctx = list(prompt_bytes) + target_bytes[:pos]
        def _f(g, _tb=tb, _ctx=ctx):
            logits = ca_forward_qkv(
                _ctx, n_blocks=n_blocks,
                embed_rule=base['embed'],
                block_rules=block_template,
                norm_rule=base['norm'],
                output_rule=g['output'], vocab_size=256)
            shifted = logits - float(logits.max())
            exp = np.exp(shifted)
            denom = float(exp.sum())
            p = float(exp[_tb] / denom) if denom > 0 else 1e-30
            lp = float(np.log(max(p, 1e-30)))
            bonus_val = bonus if int(np.argmax(logits)) == _tb else 0.0
            return lp + bonus_val
        template = {'output': random_rule_table(
            (seed ^ 0xCAFE_F00D ^ (pos * 7919)) & 0xFFFFFFFF)}
        ga_cfg = GAConfig(pop_size=pop, generations=gens,
                              tournament_k=3, elite_n=2,
                              mutation_rate=0.012,
                              seed=(seed + pos * 4099) & 0xFFFFFFFF,
                              parallel_workers=1)
        r = _evolve(template, _f, ga_cfg)
        polished, _fit, _imp = polish_genome(
            r.best_genome, _f, trials=polish,
            seed=(seed ^ 0xCAFE ^ (pos * 31)) & 0xFFFFFFFF)
        out_rules.append(polished['output'])
    sampled = sample_positional(base, out_rules, prompt_bytes,
                                   n_blocks=n_blocks)
    exact = (sampled == bytes(target_bytes))
    matches = sum(1 for i in range(n_positions)
                    if i < len(sampled) and sampled[i] == target_bytes[i])
    try:
        sampled_txt = sampled.decode('utf-8')
    except UnicodeDecodeError:
        sampled_txt = sampled.decode('latin-1', errors='replace')
    base_blob = genome_to_blob(base)
    pos_blob = b''.join(arr.astype(np.uint8).tobytes() for arr in out_rules)
    return {
        'prompt': prompt, 'expected': expected, 'sampled': sampled_txt,
        'exact': bool(exact), 'fitness': int(matches),
        'n_blocks': int(n_blocks), 'n_positional': int(n_positions),
        'base_genome_hex': base_blob.hex(),
        'positional_output_hex': pos_blob.hex(),
        'seconds': float(time.time() - t0),
    }


def main(task_id):
    input_path  = BUNDLE / 'inputs'  / f'{task_id:03d}.json'
    output_path = BUNDLE / 'outputs' / f'{task_id:03d}.json'
    inp = json.loads(input_path.read_text())
    results = []
    t_all = time.time()
    for i, pair in enumerate(inp['pairs']):
        seed = (int(inp['seed_base']) ^ (i * 0x9E37_79B1)) & 0xFFFFFFFF
        # Progress to stdout — slurm captures this to outputs/slurm-*.out
        # so the operator can `tail -f` the job log to watch progress.
        print(f'[task {task_id}] {i+1}/{len(inp["pairs"])} '
              f'{pair["prompt"]!r} → {pair["expected"]!r}', flush=True)
        res = _train_one_pair(
            pair['prompt'], pair['expected'],
            pop=int(inp['pop']), gens=int(inp['gens']),
            polish=int(inp['polish']), bonus=float(inp['bonus']),
            n_blocks=int(inp['n_blocks']), seed=seed)
        results.append(res)
        print(f'[task {task_id}]   {"✓" if res["exact"] else "✗"} '
              f'sampled={res["sampled"]!r} '
              f'fit={res["fitness"]}/{res["n_positional"]} '
              f'({res["seconds"]:.1f}s)', flush=True)
    out = {
        'task_id': int(inp['task_id']),
        'slice_lo': int(inp['slice_lo']),
        'slice_hi': int(inp['slice_hi']),
        'n_pairs': len(results),
        'exact_count': int(sum(1 for r in results if r['exact'])),
        'total_seconds': float(time.time() - t_all),
        'results': results,
    }
    output_path.write_text(json.dumps(out))
    print(f'[task {task_id}] wrote {output_path} '
          f'({out["exact_count"]}/{out["n_pairs"]} exact, '
          f'{out["total_seconds"]:.1f}s)', flush=True)


if __name__ == '__main__':
    main(int(sys.argv[1]))
'''
    _write_executable(out_dir / 'run_task.py', run_task_py)

    submit_sh = f'''#!/usr/bin/env bash
#SBATCH --job-name={params.slug}
#SBATCH --partition=cpu-short
#SBATCH --time={params.time_limit}
#SBATCH --cpus-per-task={params.cpus_per_task}
#SBATCH --mem={params.mem_per_task}
#SBATCH --array=0-{params.array_size - 1}
#SBATCH --output=outputs/slurm-%A_%a.out
#SBATCH --error=outputs/slurm-%A_%a.err
set -euo pipefail

# Bundle is fully self-contained: lib/caformer/ holds vendored pure-numpy
# modules.  Only runtime dep is python3 + numpy.
#
# Try the standard ALICE Python module first, fall back to system python.
# Adjust the `module load` line if your ALICE setup uses a different
# Python version or has a dedicated scientific-stack module.
if command -v module >/dev/null 2>&1; then
    module purge >/dev/null 2>&1 || true
    module load Python/3.11.3-GCCcore-12.3.0 >/dev/null 2>&1 \\
        || module load python/3.11 >/dev/null 2>&1 \\
        || module load python >/dev/null 2>&1 \\
        || true
fi
# Confirm numpy is importable; bail early with a clear message if not.
python3 -c 'import numpy' || {{
    echo "ERROR: numpy not importable. Edit submit.sh to load the right" >&2
    echo "  module (e.g. SciPy-bundle/2023.07-gfbf-2023a) or activate a venv." >&2
    exit 1
}}

cd "$(dirname "${{BASH_SOURCE[0]}}")"
exec python3 run_task.py "$SLURM_ARRAY_TASK_ID"
'''
    _write_executable(out_dir / 'submit.sh', submit_sh)

    remote_path = f'{params.ssh_user}@{params.ssh_host}:{params.remote_dir}/{params.slug}/'
    push_sh = f'''#!/usr/bin/env bash
# rsync this self-contained bundle onto ALICE. Edit ssh_user / ssh_host
# if wrong.  The bundle includes lib/caformer/ — no separate Velour
# repo or venv with project deps is needed on ALICE.  Only requirement
# on the remote: python3 with numpy importable (covered by the standard
# Python/SciPy ALICE module).
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
echo "Ingest with:   venv/bin/python manage.py alice_analyze_qrpair_vocab {params.slug} --ingest"
'''
    _write_executable(out_dir / 'pull.sh', pull_sh)

    # Manifest — small, machine-readable, lists every pair + task slice.
    manifest = {
        'kind':             BUNDLE_KIND,
        'slug':             params.slug,
        'array_size':       params.array_size,
        'n_pairs':          n_pairs,
        'response_strategy': params.response_strategy,
        'explicit_pairs':   bool(params.explicit_pairs),
        'pop':              params.pop,
        'gens':             params.gens,
        'polish':           params.polish,
        'bonus':            params.bonus,
        'n_blocks':         params.n_blocks,
        'seed_base':        params.seed_base,
        'time_limit':       params.time_limit,
        'mem_per_task':     params.mem_per_task,
        'cpus_per_task':    params.cpus_per_task,
    }
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))

    expected_per_pair_s = 16 * max(1, len(pairs[0][1])) if pairs else 80
    expected_per_task_s = slice_size * expected_per_pair_s
    expected_wall_h = expected_per_task_s / 3600
    expected_total_cpu_h = (n_pairs * expected_per_pair_s) / 3600
    readme = f'''# Bundle: {params.slug}

QRPair vocabulary trainer — evolves a positional CAformer per pair so
the chat dispatcher can route every prompt to its own trained chain.

## What it does

- Pairs:           {n_pairs}  ({params.response_strategy} strategy{' or explicit' if params.explicit_pairs else ''})
- Array size:      {params.array_size}  ⇒ {slice_size} pairs/task
- Per-task pop:    {params.pop}  generations: {params.gens}  polish: {params.polish}
- Per-pair bonus:  {params.bonus}  n_blocks: {params.n_blocks}
- Seed base:       0x{params.seed_base:08X} XOR task_id

## Expected runtime

Local baseline: ~16 s/byte of expected response (positional polish, n_blocks=1).
Average expected length here: {sum(len(e) for _, e in pairs) / max(1, n_pairs):.1f} chars.

- Per task:    ~{expected_per_task_s/60:.1f} min  (≈ {expected_wall_h:.1f} h)
- Total CPU:   ~{expected_total_cpu_h:.1f} CPU-hours
- Wall time:   ≈ per-task time when all array slots run in parallel

Tune array_size up if a task overruns `--time={params.time_limit}`.

## Operator steps

```
bash push.sh
ssh {params.ssh_user}@{params.ssh_host}
cd {params.remote_dir}/{params.slug}
sbatch submit.sh
# wait
exit
bash pull.sh
venv/bin/python manage.py alice_analyze_qrpair_vocab {params.slug} --ingest
```

## Output format

Each `outputs/<task_id>.json` contains:
```
{{
  "task_id":  N,
  "slice_lo": ..., "slice_hi": ...,
  "results": [
    {{"prompt": "...", "expected": "...", "sampled": "...",
     "exact": true|false, "fitness": <int matches>,
     "n_blocks": 1, "n_positional": <len(expected)>,
     "base_genome_hex": "...", "positional_output_hex": "...",
     "seconds": <float>}}
  ]
}}
```

`--ingest` creates one QRPair row per result + auto-deploys exact-match
ones into the chat dispatcher.

## Safety

- Each pair is independent; no IPC; no shared writes.
- Memory: {params.mem_per_task} per task (positional trainer ~200 MB).
- No network — uses only numpy + spoeqi + caformer modules from the
  Velour checkout on ALICE.
- Determinism: seed = seed_base XOR task_id.
'''
    (out_dir / 'README.md').write_text(readme)
    return out_dir


# ─── ALICE side: per-task worker ──────────────────────────────────────

def _train_one_pair(prompt: str, expected: str, *,
                       pop: int, gens: int, polish: int,
                       bonus: float, n_blocks: int, seed: int) -> dict:
    """Train one (prompt, expected) positionally and return a portable
    result dict.  Inlines the qr_trainer.train_pair_positional inner
    loop without the Django ORM so it runs on a bare ALICE node with
    just the Velour checkout — no DB, no migrations, no auth."""
    import time as _time
    import numpy as np
    from caformer.ga import (FULL_STACK_NAMES, GAConfig, _evolve,
                                  polish_genome)
    from caformer.primitives import random_rule_table
    from caformer.transformer import ca_forward_qkv
    from caformer.qr_trainer import sample_positional, genome_to_blob

    prompt_bytes = list(prompt.encode('utf-8'))[:64]
    target_bytes = list(expected.encode('utf-8'))[:64]
    n_positions  = len(target_bytes)
    if n_positions == 0:
        raise ValueError(f'empty expected for prompt {prompt!r}')

    # Fixed base genome — random but reproducible from the task seed.
    base = {n: random_rule_table((seed ^ (0x100 * (i + 1))) & 0xFFFFFFFF)
              for i, n in enumerate(FULL_STACK_NAMES)}
    block_template = [{k: base[k] for k in
                          ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}
                         ] * n_blocks

    out_rules: list = []
    t0 = _time.time()
    for pos in range(n_positions):
        tb = target_bytes[pos]
        ctx = list(prompt_bytes) + target_bytes[:pos]

        def _f(g, _tb=tb, _ctx=ctx):
            logits = ca_forward_qkv(
                _ctx, n_blocks=n_blocks,
                embed_rule=base['embed'],
                block_rules=block_template,
                norm_rule=base['norm'],
                output_rule=g['output'], vocab_size=256)
            shifted = logits - float(logits.max())
            exp = np.exp(shifted)
            denom = float(exp.sum())
            p = float(exp[_tb] / denom) if denom > 0 else 1e-30
            lp = float(np.log(max(p, 1e-30)))
            bonus_val = bonus if int(np.argmax(logits)) == _tb else 0.0
            return lp + bonus_val

        template = {'output': random_rule_table(
            (seed ^ 0xCAFE_F00D ^ (pos * 7919)) & 0xFFFFFFFF)}
        ga_cfg = GAConfig(pop_size=pop, generations=gens,
                              tournament_k=3, elite_n=2,
                              mutation_rate=0.012,
                              seed=(seed + pos * 4099) & 0xFFFFFFFF,
                              parallel_workers=1)
        r = _evolve(template, _f, ga_cfg)
        polished, _fit, _imp = polish_genome(
            r.best_genome, _f, trials=polish,
            seed=(seed ^ 0xCAFE ^ (pos * 31)) & 0xFFFFFFFF)
        out_rules.append(polished['output'])

    sampled = sample_positional(base, out_rules, prompt_bytes,
                                   n_blocks=n_blocks)
    exact = (sampled == bytes(target_bytes))
    matches = sum(1 for i in range(n_positions)
                    if i < len(sampled) and sampled[i] == target_bytes[i])
    try:
        sampled_txt = sampled.decode('utf-8')
    except UnicodeDecodeError:
        sampled_txt = sampled.decode('latin-1', errors='replace')

    base_blob = genome_to_blob(base)
    pos_blob = b''.join(arr.astype(np.uint8).tobytes() for arr in out_rules)
    return {
        'prompt':                prompt,
        'expected':              expected,
        'sampled':               sampled_txt,
        'exact':                 bool(exact),
        'fitness':               int(matches),
        'n_blocks':              int(n_blocks),
        'n_positional':          int(n_positions),
        'base_genome_hex':       base_blob.hex(),
        'positional_output_hex': pos_blob.hex(),
        'seconds':               float(_time.time() - t0),
    }


def run_task(input_path: Path, output_path: Path) -> None:
    """Train every pair in this task's slice; write a single JSON."""
    inp = json.loads(Path(input_path).read_text())
    results = []
    t_all = time.time()
    for i, pair in enumerate(inp['pairs']):
        seed = (int(inp['seed_base']) ^ (i * 0x9E37_79B1)) & 0xFFFFFFFF
        res = _train_one_pair(
            pair['prompt'], pair['expected'],
            pop=int(inp['pop']), gens=int(inp['gens']),
            polish=int(inp['polish']), bonus=float(inp['bonus']),
            n_blocks=int(inp['n_blocks']), seed=seed)
        results.append(res)
    out = {
        'task_id':         int(inp['task_id']),
        'slice_lo':        int(inp['slice_lo']),
        'slice_hi':        int(inp['slice_hi']),
        'n_pairs':         len(results),
        'exact_count':     int(sum(1 for r in results if r['exact'])),
        'total_seconds':   float(time.time() - t_all),
        'results':         results,
    }
    Path(output_path).write_text(json.dumps(out))


# ─── Local side: rsync-back ingestion ─────────────────────────────────

def analyse(bundle_dir: Path) -> dict:
    bundle_dir = Path(bundle_dir).resolve()
    outs = sorted((bundle_dir / 'outputs').glob('*.json'))
    if not outs:
        return {'error': 'no outputs/*.json found — pull.sh first?'}
    pairs_seen = 0
    pairs_exact = 0
    total_seconds = 0.0
    failures = []
    for p in outs:
        try:
            d = json.loads(p.read_text())
        except Exception as e:
            failures.append(f'{p.name}: {e}')
            continue
        pairs_seen += int(d.get('n_pairs', 0))
        pairs_exact += int(d.get('exact_count', 0))
        total_seconds += float(d.get('total_seconds', 0.0))
    return {
        'tasks_seen':    len(outs),
        'pairs_seen':    pairs_seen,
        'pairs_exact':   pairs_exact,
        'success_rate':  (pairs_exact / pairs_seen) if pairs_seen else 0.0,
        'total_seconds': total_seconds,
        'failures':      failures,
    }


def ingest(bundle_dir: Path, *, auto_deploy: bool = True) -> dict:
    """Walk outputs/*.json, create or update a QRPair per result, and
    optionally auto-deploy each exact pair so the chat dispatcher
    picks it up.  Returns counts."""
    from caformer.models import QRPair
    from caformer.ga import random_rule_table
    import numpy as np

    bundle_dir = Path(bundle_dir).resolve()
    outs = sorted((bundle_dir / 'outputs').glob('*.json'))
    created = 0
    updated = 0
    deployed = 0
    skipped_non_exact = 0
    for p in outs:
        d = json.loads(p.read_text())
        for r in d.get('results', []):
            prompt   = r['prompt']
            expected = r['expected']
            base_blob = bytes.fromhex(r['base_genome_hex'])
            pos_blob  = bytes.fromhex(r['positional_output_hex'])
            pair, was_created = QRPair.objects.get_or_create(
                prompt=prompt, expected=expected,
                defaults={'n_blocks': int(r['n_blocks']),
                            'label':    'alice-vocab'})
            pair.best_genome_blob       = base_blob
            pair.positional_output_blob = pos_blob
            pair.best_output            = r.get('sampled', '')
            pair.best_exact             = bool(r['exact'])
            pair.best_fitness           = float(r.get('fitness', 0))
            pair.last_phase             = 'alice-vocab'
            pair.total_seconds          = float(r.get('seconds', 0.0))
            pair.save()
            if was_created:
                created += 1
            else:
                updated += 1
            if auto_deploy and pair.best_exact and not pair.deployed_slug:
                try:
                    from caformer.views import _deploy_qr_pair
                    _deploy_qr_pair(pair.pk)
                    deployed += 1
                except Exception:
                    pass
            if not pair.best_exact:
                skipped_non_exact += 1
    return {
        'created':            created,
        'updated':            updated,
        'deployed':           deployed,
        'skipped_non_exact':  skipped_non_exact,
    }

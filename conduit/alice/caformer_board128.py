"""ALICE bundle generator for board128 corpus training.

Sister of conduit/alice/caformer_cell8.py — same array-job pattern,
but each task trains a slice of QRPairs at board128 (7→1 LUT on
128×128) using train_pair_board128_positional.  Use this for new
corpora (Shakespeare sonnets, plays, etc.) that haven't been trained
yet at any tier.

Local side
----------
``generate_bundle(out_dir, params)``
    Writes a self-contained bundle.  Each array task gets one or
    more QRPair pks; trains all positions per pair; writes per-task
    ``outputs/NNN.rules`` (flat-file format, rule_shape=7to1).

``analyse(bundle_dir)``
``ingest(bundle_dir)``

ALICE side
----------
``run_task(input_path, output_path)``
    Pure numpy + vendored caformer modules.  No Django runtime dep.
"""
from __future__ import annotations

import json
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


DEFAULT_REMOTE_DIR = '~/velour-dev/.alice_bundles'

VENDORED_CAFORMER_MODULES = (
    'board128', 'primitives', 'ga')
VENDORED_IO_MODULES = ('rule_blob',)


@dataclass
class BundleParams:
    slug:                 str
    pair_pks:             List[int]
    pairs:                List[dict] = field(default_factory=list)
    array_size:           int = 32
    max_seconds_per_pos:  float = 60.0
    n_ticks:              int = 128
    seed_base:            int = 0xB128A1E
    time_limit:           str = '04:00:00'
    mem_per_task:         str = '2G'
    cpus_per_task:        int = 1
    ssh_host:             str = 'alice'
    ssh_user:             str = 'handyca'
    remote_dir:           str = DEFAULT_REMOTE_DIR


def export_pairs_for_bundle(pair_pks: List[int]) -> List[dict]:
    from caformer.models import QRPair
    out = []
    for pk in pair_pks:
        p = QRPair.objects.filter(pk=pk).first()
        if p is None:
            continue
        out.append({
            'pk':       int(p.pk),
            'prompt':   p.prompt,
            'expected': p.expected,
            'n_positions': len(p.expected.encode('utf-8')),
        })
    return out


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

    pairs = params.pairs
    n_pairs = len(pairs)
    if n_pairs == 0:
        raise ValueError('no pairs in BundleParams; populate via '
                            'export_pairs_for_bundle()')

    array_size = max(1, min(int(params.array_size), n_pairs))
    slice_size = (n_pairs + array_size - 1) // array_size

    for task_id in range(array_size):
        lo = task_id * slice_size
        hi = min(n_pairs, lo + slice_size)
        task_pairs = pairs[lo:hi] if lo < hi else []
        (out_dir / 'inputs' / f'{task_id:03d}.json').write_text(
            json.dumps({
                'task_id':            task_id,
                'slice_lo':           lo,
                'slice_hi':           hi,
                'seed_base':          (params.seed_base ^ task_id) & 0xFFFFFFFF,
                'max_seconds_per_pos': params.max_seconds_per_pos,
                'n_ticks':            params.n_ticks,
                'pairs':              task_pairs,
            }, indent=2))

    # Vendor modules.
    repo_root = Path(__file__).resolve().parent.parent.parent
    src_caformer = repo_root / 'caformer'
    vendored = out_dir / 'lib' / 'caformer'
    vendored.mkdir(parents=True, exist_ok=True)
    (vendored / '__init__.py').write_text('')
    for mod in VENDORED_CAFORMER_MODULES:
        shutil.copy2(src_caformer / f'{mod}.py', vendored / f'{mod}.py')
    io_dst = vendored / 'io'
    io_dst.mkdir(exist_ok=True)
    (io_dst / '__init__.py').write_text('')
    for mod in VENDORED_IO_MODULES:
        shutil.copy2(repo_root / 'caformer' / 'io' / f'{mod}.py',
                         io_dst / f'{mod}.py')

    # run_task.py — board128 worker.
    run_task_py = '''#!/usr/bin/env python3
"""ALICE-side worker: trains a slice of QRPairs at board128 (7→1)
and appends each finished rule to outputs/<task_id>.rules."""
import json
import sys
import time
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE / 'lib'))

import numpy as np
from caformer.board128 import train_position_board128
from caformer.io.rule_blob import RuleRecord, append_records, SHAPE_7TO1


def main(task_id):
    in_path  = BUNDLE / 'inputs'  / f'{task_id:03d}.json'
    out_path = BUNDLE / 'outputs' / f'{task_id:03d}.rules'
    log_path = BUNDLE / 'outputs' / f'{task_id:03d}.log'

    cfg = json.loads(in_path.read_text())
    pairs = cfg['pairs']
    seed_base   = cfg['seed_base']
    max_seconds = cfg['max_seconds_per_pos']
    n_ticks     = cfg['n_ticks']

    log_lines = [f'task_id={task_id}  n_pairs={len(pairs)}']
    grand_t0 = time.time()
    n_pos_total, n_pos_matched = 0, 0

    for p_idx, pair in enumerate(pairs):
        pk = int(pair['pk'])
        prompt = pair['prompt']
        expected_bytes = pair['expected'].encode('utf-8')
        log_lines.append(
            f'-- pair {p_idx+1}/{len(pairs)} pk={pk} '
            f'expected={pair["expected"]!r} n={len(expected_bytes)} --')
        pair_t0 = time.time()
        for pos, tb in enumerate(expected_bytes):
            t0 = time.time()
            r = train_position_board128(
                prompt, tb, pos,
                n_ticks=n_ticks,
                max_seconds=max_seconds,
                seed=(seed_base ^ (pk * 19937) ^ (pos * 4099)) & 0xFFFFFFFF)
            wall = time.time() - t0
            n_pos_total += 1
            matched = bool(r['byte_match'])
            if matched: n_pos_matched += 1
            rec = RuleRecord(
                pair_pk=pk, position=pos, n_ticks=n_ticks,
                port_src='off', rule_shape=SHAPE_7TO1,
                rule_blob=bytes(r['rule_table']),
                byte_matched=matched)
            append_records(out_path, [rec])
            log_lines.append(
                f'  pos {pos:2d} target=0x{tb:02x}  '
                f'{("MATCH" if matched else "miss "):6s} '
                f'{r["phase"]:10s} {wall:6.1f}s')
        log_lines.append(f'  pair wall {time.time()-pair_t0:.1f}s')

    summary = (f'\\n=== task {task_id} done in {time.time()-grand_t0:.1f}s, '
                f'{n_pos_matched}/{n_pos_total} positions matched ===\\n')
    log_lines.append(summary)
    log_path.write_text('\\n'.join(log_lines))


if __name__ == '__main__':
    import os
    main(int(sys.argv[1]) if len(sys.argv) > 1 else
              int(os.environ.get('SLURM_ARRAY_TASK_ID', '0')))
'''
    _write_executable(out_dir / 'run_task.py', run_task_py)

    submit_sh = f'''#!/usr/bin/env bash
#SBATCH --job-name={params.slug}
#SBATCH --partition=cpu-short
#SBATCH --time={params.time_limit}
#SBATCH --cpus-per-task={params.cpus_per_task}
#SBATCH --mem={params.mem_per_task}
#SBATCH --array=0-{array_size - 1}
#SBATCH --output=outputs/slurm-%A_%a.out
#SBATCH --error=outputs/slurm-%A_%a.err
set -euo pipefail
# ALICE Python module.  SciPy-bundle layers numpy + scipy + others
# on top of the bare Python module.  If neither lands, fall back to a
# user-pip install (slower first time, cached after).
module load Python/3.11.5-GCCcore-13.2.0 2>/dev/null \
  || module load Python 2>/dev/null || true
module load SciPy-bundle/2023.11-gfbf-2023b 2>/dev/null \
  || module load SciPy-bundle 2>/dev/null || true
python3 -c 'import numpy' 2>/dev/null \
  || pip install --user --quiet --disable-pip-version-check numpy
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"
python3 run_task.py "$SLURM_ARRAY_TASK_ID"
'''
    _write_executable(out_dir / 'submit.sh', submit_sh)

    host = f'{params.ssh_user}@{params.ssh_host}'
    remote = f'{params.remote_dir}/{params.slug}'
    _write_executable(out_dir / 'push.sh', f'''#!/usr/bin/env bash
set -euo pipefail
BUNDLE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
# rsync only auto-creates the leaf directory; pre-mkdir so deep
# parents (~/velour-dev/.alice_bundles/) are guaranteed to exist.
ssh "{host}" "mkdir -p {remote}"
rsync -av --exclude='outputs/*.rules' --exclude='outputs/*.log' \\
    --exclude='outputs/slurm-*' \\
    "$BUNDLE/" "{host}:{remote}/"
echo
echo "Now SSH in and submit:"
echo "  ssh {host}"
echo "  cd {remote}"
echo "  sbatch submit.sh"
''')
    _write_executable(out_dir / 'pull.sh', f'''#!/usr/bin/env bash
set -euo pipefail
BUNDLE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
rsync -av "{host}:{remote}/outputs/" "$BUNDLE/outputs/"
echo
echo "Outputs in:    $BUNDLE/outputs/"
echo "Ingest with:   venv/bin/python manage.py alice_ingest_board128 {params.slug}"
''')

    (out_dir / 'manifest.json').write_text(json.dumps({
        'kind':                'caformer-board128',
        'slug':                params.slug,
        'array_size':          array_size,
        'n_pairs':             n_pairs,
        'max_seconds_per_pos': params.max_seconds_per_pos,
        'n_ticks':             params.n_ticks,
        'seed_base':           params.seed_base,
        'time_limit':          params.time_limit,
        'mem_per_task':        params.mem_per_task,
        'cpus_per_task':       params.cpus_per_task,
    }, indent=2))
    avg_pos = sum(p['n_positions'] for p in pairs) / max(1, n_pairs)
    est_cpu_hr = (n_pairs * avg_pos * params.max_seconds_per_pos) / 3600
    (out_dir / 'README.md').write_text(f'''# {params.slug} — board128 corpus training bundle

Trains {n_pairs} QRPair(s) at board128 (7→1 LUT on 128×128),
sliced across {array_size} array tasks (~{((n_pairs + array_size - 1)//array_size)} pairs per task).

Average response length: {avg_pos:.1f} positions per pair
Per-position budget: {params.max_seconds_per_pos:.0f} s
Estimated total CPU: ~{est_cpu_hr:.1f} CPU-hr

## Operator workflow
1. `bash push.sh`
2. SSH to ALICE; `cd {remote}; sbatch submit.sh`
3. Watch with `squeue -u $USER`
4. When done: `bash pull.sh`
5. `venv/bin/python manage.py alice_ingest_board128 {params.slug}`

## Outputs
- `outputs/NNN.rules` — flat-file rule records (CRC-checked)
- `outputs/NNN.log`   — per-task training log
- `outputs/slurm-*`   — Slurm stdout/stderr
''')

    return out_dir


def analyse(bundle_dir: Path) -> dict:
    from caformer.io.rule_blob import read_records
    bd = Path(bundle_dir)
    out = bd / 'outputs'
    if not out.is_dir():
        return {'error': f'no outputs/ at {out}'}
    rules_files = sorted(out.glob('*.rules'))
    n_records = 0
    per_pair = {}
    for rf in rules_files:
        for rec in read_records(rf):
            n_records += 1
            per_pair.setdefault(rec.pair_pk, []).append(rec.byte_matched)
    matched_pairs = {pk for pk, m in per_pair.items() if all(m)}
    return {
        'rules_files':            len(rules_files),
        'records':                n_records,
        'pairs_with_any_record':  len(per_pair),
        'fully_matched_pairs':    len(matched_pairs),
        'per_pair_byte_match_rate': {
            pk: f'{sum(m)}/{len(m)}'
            for pk, m in sorted(per_pair.items())},
    }


def ingest(bundle_dir: Path) -> dict:
    from django.core.management import call_command
    bd = Path(bundle_dir)
    files = sorted((bd / 'outputs').glob('*.rules'))
    if not files:
        return {'error': f'no .rules files in {bd}/outputs/'}
    call_command('caformer_import_rules', *[str(f) for f in files])
    return {'files': len(files), 'ingested': True}

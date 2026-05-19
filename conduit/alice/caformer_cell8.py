"""ALICE bundle generator + analyser for cell8+256 corpus retraining.

Long-term goal: train every QRPair's positional rules at cell8+256
(8→1 LUT on 256×256 board, preserving the LUT-as-board ouroboros
symmetry that 128×128 breaks).  Serial on home box would take many
hours per pair × dozens of pairs = days; ALICE array job collapses
it to one queue cycle.

Local side
----------
``generate_bundle(out_dir, params)``
    Writes a self-contained bundle.  Each array task gets one or
    more QRPair pks; trains all positions per pair in cell8+256;
    writes per-task ``outputs/NNN.rules`` (flat-file format from
    caformer/io/rule_blob.py).  Optionally warm-starts from each
    pair's existing board128 rule (upcast 7→1 → cell8).

``analyse(bundle_dir)``
    Scans outputs/, reports per-pair byte-match rates + wall times.

``ingest(bundle_dir, …)``
    Reads outputs/*.rules and merges into QRPair.cell8_b256_rules_blob
    via the same code path as `caformer_import_rules`.

ALICE side
----------
``run_task(input_path, output_path)``
    For each (pair_pk, prompt, expected, warm_start_blob?) in the
    task's slice, runs board256.train_position_board256 sequentially
    and appends each finished rule to the output .rules file.
    Pure numpy + vendored caformer.{board256,cell8,primitives,ga,
    io.rule_blob}.  No Django.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


DEFAULT_REMOTE_DIR = '~/velour-dev/.alice_bundles'

# Modules to vendor into the bundle's lib/caformer/ directory.
# board256 depends on cell8 + primitives + ga; ga depends on primitives
# + numpy (no django).  io.rule_blob is the flat-file format.
VENDORED_CAFORMER_MODULES = (
    'board256', 'cell8', 'primitives', 'ga')
VENDORED_IO_MODULES = ('rule_blob',)


@dataclass
class BundleParams:
    slug: str
    pair_pks: List[int]                 # which QRPair pks to train
    pairs:    List[dict] = field(default_factory=list)
                                          # exported pair dicts (see _resolve_pairs)
    array_size:           int = 32
    max_seconds_per_pos:  float = 180.0
    n_ticks:              int = 256
    warm_start:           bool = True
    seed_base:            int = 0xB256A1E
    time_limit:           str = '04:00:00'
    mem_per_task:         str = '4G'
    cpus_per_task:        int = 1
    ssh_host:             str = 'login1.alice.universiteitleiden.nl'
    ssh_user:             str = 'handy'
    remote_dir:           str = DEFAULT_REMOTE_DIR


def export_pairs_for_bundle(pair_pks: List[int], warm_start: bool) -> List[dict]:
    """Pull QRPair rows + (optional) board128 warm-start blobs out of
    the live DB and serialise to portable dicts the ALICE task can
    consume without any Django."""
    from caformer.models import QRPair
    out = []
    for pk in pair_pks:
        p = QRPair.objects.filter(pk=pk).first()
        if p is None:
            continue
        d = {
            'pk':       int(p.pk),
            'prompt':   p.prompt,
            'expected': p.expected,
            'n_positions': len(p.expected.encode('utf-8')),
        }
        if warm_start and p.board128_rules_blob:
            blob = bytes(p.board128_rules_blob)
            expected_len = d['n_positions'] * 16_384
            if len(blob) == expected_len:
                # Hex-encode for JSON portability (one entry per position).
                d['warm_start_hex'] = [
                    blob[i*16384:(i+1)*16384].hex() for i in range(d['n_positions'])]
        out.append(d)
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

    # Slice pairs across array tasks.
    array_size = max(1, int(params.array_size))
    if array_size > n_pairs:
        array_size = n_pairs       # don't allocate empty slots
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
                'warm_start':         bool(params.warm_start),
                'pairs':              task_pairs,
            }, indent=2))

    # Vendor pure-numpy modules.
    repo_root = Path(__file__).resolve().parent.parent.parent
    src_caformer = repo_root / 'caformer'
    vendored = out_dir / 'lib' / 'caformer'
    vendored.mkdir(parents=True, exist_ok=True)
    (vendored / '__init__.py').write_text('')
    for mod in VENDORED_CAFORMER_MODULES:
        src = src_caformer / f'{mod}.py'
        if not src.exists():
            raise FileNotFoundError(f'cannot vendor caformer.{mod}: {src} missing')
        shutil.copy2(src, vendored / f'{mod}.py')
    # io subpackage.
    io_dst = vendored / 'io'
    io_dst.mkdir(exist_ok=True)
    (io_dst / '__init__.py').write_text('')
    for mod in VENDORED_IO_MODULES:
        src = repo_root / 'caformer' / 'io' / f'{mod}.py'
        if not src.exists():
            raise FileNotFoundError(f'cannot vendor caformer.io.{mod}: {src} missing')
        shutil.copy2(src, io_dst / f'{mod}.py')

    # run_task.py — the ALICE-side worker.
    run_task_py = '''#!/usr/bin/env python3
"""ALICE-side worker: trains a slice of QRPairs at cell8+256,
appends to outputs/<task_id>.rules in the flat-file format.

Self-contained: only requires python3 + numpy.  Vendored modules
in lib/caformer/."""
import json
import sys
import time
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE / 'lib'))

import numpy as np
from caformer.board256 import train_position_board256
from caformer.io.rule_blob import (RuleRecord, append_records, SHAPE_CELL8)


def main(task_id):
    in_path  = BUNDLE / 'inputs'  / f'{task_id:03d}.json'
    out_path = BUNDLE / 'outputs' / f'{task_id:03d}.rules'
    log_path = BUNDLE / 'outputs' / f'{task_id:03d}.log'

    cfg = json.loads(in_path.read_text())
    pairs = cfg['pairs']
    seed_base    = cfg['seed_base']
    max_seconds  = cfg['max_seconds_per_pos']
    n_ticks      = cfg['n_ticks']
    warm_start   = bool(cfg.get('warm_start', False))

    log_lines = [f'task_id={task_id}  n_pairs={len(pairs)}']
    grand_t0 = time.time()
    n_pos_total   = 0
    n_pos_matched = 0

    for p_idx, pair in enumerate(pairs):
        pk = int(pair['pk'])
        prompt = pair['prompt']
        expected_bytes = pair['expected'].encode('utf-8')
        warm = pair.get('warm_start_hex') if warm_start else None
        log_lines.append(
            f'-- pair {p_idx+1}/{len(pairs)} pk={pk} '
            f'expected={pair["expected"]!r} n={len(expected_bytes)} --')
        pair_t0 = time.time()
        for pos, tb in enumerate(expected_bytes):
            ws_bytes = bytes.fromhex(warm[pos]) if warm and pos < len(warm) else None
            t0 = time.time()
            r = train_position_board256(
                prompt, tb, pos,
                n_ticks=n_ticks,
                max_seconds=max_seconds,
                seed=(seed_base ^ (pk * 19937) ^ (pos * 4099)) & 0xFFFFFFFF,
                seed_rule=ws_bytes)
            wall = time.time() - t0
            n_pos_total += 1
            matched = bool(r['byte_match'])
            if matched: n_pos_matched += 1
            rec = RuleRecord(
                pair_pk=pk, position=pos, n_ticks=n_ticks,
                port_src='off', rule_shape=SHAPE_CELL8,
                rule_blob=bytes(r['rule_table']))
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
    main(int(sys.argv[1]) if len(sys.argv) > 1 else
              int(__import__('os').environ.get('SLURM_ARRAY_TASK_ID', '0')))
'''
    _write_executable(out_dir / 'run_task.py', run_task_py)

    # submit.sh — Slurm array job.
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

# ALICE python module that ships numpy.  Adjust if your project loads
# a different scientific-stack module.
module load Python/3.11.5-GCCcore-13.2.0 || true

cd "$(dirname "$0")"
python3 run_task.py "$SLURM_ARRAY_TASK_ID"
'''
    _write_executable(out_dir / 'submit.sh', submit_sh)

    # push.sh / pull.sh.
    host = f'{params.ssh_user}@{params.ssh_host}'
    remote = f'{params.remote_dir}/{params.slug}'
    push_sh = f'''#!/usr/bin/env bash
set -euo pipefail
BUNDLE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
rsync -av --exclude='outputs/*.rules' --exclude='outputs/*.log' \\
    --exclude='outputs/slurm-*' \\
    "$BUNDLE/" "{host}:{remote}/"
echo
echo "Now SSH in and submit:"
echo "  ssh {host}"
echo "  cd {remote}"
echo "  sbatch submit.sh"
'''
    pull_sh = f'''#!/usr/bin/env bash
set -euo pipefail
BUNDLE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
rsync -av "{host}:{remote}/outputs/" "$BUNDLE/outputs/"
echo
echo "Outputs in:    $BUNDLE/outputs/"
echo "Ingest with:   venv/bin/python manage.py alice_ingest_cell8 {params.slug}"
'''
    _write_executable(out_dir / 'push.sh', push_sh)
    _write_executable(out_dir / 'pull.sh', pull_sh)

    # manifest.json + README.md
    (out_dir / 'manifest.json').write_text(json.dumps({
        'kind':                'caformer-cell8-b256',
        'slug':                params.slug,
        'array_size':          array_size,
        'n_pairs':             n_pairs,
        'max_seconds_per_pos': params.max_seconds_per_pos,
        'n_ticks':             params.n_ticks,
        'warm_start':          params.warm_start,
        'seed_base':           params.seed_base,
        'time_limit':          params.time_limit,
        'mem_per_task':        params.mem_per_task,
        'cpus_per_task':       params.cpus_per_task,
    }, indent=2))
    (out_dir / 'README.md').write_text(f'''# {params.slug} — cell8+256 corpus retrain bundle

Trains {n_pairs} QRPair(s) at cell8+256 (8→1 LUT on 256×256 board),
sliced across {array_size} array tasks ({((n_pairs + array_size - 1)//array_size)} pairs per task max).

Per-position budget: {params.max_seconds_per_pos:.0f} s
Estimated wall (worst case): ~{((n_pairs * 5 * params.max_seconds_per_pos) / max(1,array_size)) / 60:.0f} min per array task
Estimated total CPU: ~{(n_pairs * 5 * params.max_seconds_per_pos) / 3600:.1f} CPU-hr

## Operator workflow
1. `bash push.sh`
2. SSH to ALICE; `cd {remote}; sbatch submit.sh`
3. Watch with `squeue -u $USER`
4. When done: `bash pull.sh`
5. `venv/bin/python manage.py alice_ingest_cell8 {params.slug}`

## Outputs
- `outputs/NNN.rules` — flat-file rule records (CRC-checked, append-only)
- `outputs/NNN.log`   — per-task training log
- `outputs/slurm-*`   — Slurm stdout/stderr
''')

    return out_dir


def analyse(bundle_dir: Path) -> dict:
    """Walk outputs/*.rules + outputs/*.log to report per-pair match
    rates and total wall."""
    from caformer.io.rule_blob import read_records, SHAPE_CELL8
    bd = Path(bundle_dir)
    out = bd / 'outputs'
    if not out.is_dir():
        return {'error': f'no outputs/ at {out}'}
    rules_files = sorted(out.glob('*.rules'))
    log_files   = sorted(out.glob('*.log'))
    n_records = 0
    per_pair = {}
    for rf in rules_files:
        for rec in read_records(rf):
            n_records += 1
            per_pair.setdefault(rec.pair_pk, set()).add(rec.position)
    return {
        'rules_files': len(rules_files),
        'log_files':   len(log_files),
        'records':     n_records,
        'pairs_with_any_record': len(per_pair),
        'per_pair_position_count': {
            pk: len(positions) for pk, positions in sorted(per_pair.items())},
    }


def ingest(bundle_dir: Path) -> dict:
    """Read all outputs/*.rules into the live QRPair DB via
    caformer_import_rules logic.  Returns a summary."""
    from django.core.management import call_command
    bd = Path(bundle_dir)
    files = sorted((bd / 'outputs').glob('*.rules'))
    if not files:
        return {'error': f'no .rules files in {bd}/outputs/'}
    # Call the same management command path we already tested.
    call_command('caformer_import_rules', *[str(f) for f in files])
    return {'files': len(files), 'ingested': True}

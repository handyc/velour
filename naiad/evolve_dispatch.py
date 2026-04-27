"""Package a Naiad GA run as a Conduit Job.

Shared by the `naiad_evolve --via-conduit` management command and
the `/naiad/<slug>/evolve/via-conduit/` web endpoint — both want the
same behaviour: turn a (System, target, GA options) triple into a
dispatched Conduit Job. The CLI additionally blocks on terminal
state and prints captured output; the web caller just hands back
the Job for the browser to watch.

Why a shared helper:

- Keeps the shell-vs-sbatch rendering in one place so CLI and UI
  can't drift.
- Isolates the Conduit imports (model + dispatch + routing) from
  naiad.models users who don't need them.
- Makes the CLI path trivially testable as a function call without
  going through `call_command`.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


SHELL_KINDS = ('local', 'vps')
SLURM_KINDS = ('slurm', 'slurm_manual')


class DispatchError(Exception):
    """Bad target slug, disabled target, unsupported kind, etc.
    Callers translate into CommandError / HTTP 4xx."""


def dispatch_via_conduit(system, target_slug: str, opts: dict) -> Any:
    """Create and dispatch a Conduit Job for this GA run. Returns the
    saved Job object (refreshed from DB). Caller decides whether to
    wait for terminal state."""
    # Lazy imports so naiad doesn't force a conduit import at module load.
    from conduit.executors import dispatch
    from conduit.models import Job, JobTarget
    from conduit.routing import RoutingError

    try:
        target = JobTarget.objects.get(slug=target_slug)
    except JobTarget.DoesNotExist:
        raise DispatchError(
            f'No Conduit JobTarget with slug {target_slug!r}. '
            f'Run `manage.py seed_conduit_defaults` or create one '
            f'at /conduit/targets/new/.')
    if not target.enabled:
        raise DispatchError(
            f'JobTarget {target_slug!r} is disabled.')

    passthrough = _passthrough_args(system.slug, opts)
    job_slug = (f'naiad-evolve-{slugify(system.slug)}-'
                f'{timezone.now():%Y%m%d-%H%M%S}')
    job_name = f'Naiad evolve: {system.slug}'

    # Stashed alongside the executor payload so the Naiad import
    # view can reconstruct the winner's parentage (source + target)
    # even when the GA ran on a remote checkout with no shared DB.
    naiad_meta = {
        'parent_slug': system.slug,
        'save_as':     opts.get('save') or None,
    }

    if target.kind in SHELL_KINDS:
        cwd = str(settings.BASE_DIR)
        python_bin = f'{cwd}/venv/bin/python'
        command = (f'{shlex.quote(python_bin)} manage.py naiad_evolve '
                   f'{passthrough}')
        timeout = max(3600, int(opts.get('gens', 0)) * 10)
        job = Job.objects.create(
            slug=job_slug, name=job_name, kind='shell',
            payload={'command': command, 'cwd': cwd, 'timeout': timeout,
                     'naiad': naiad_meta},
            requester=opts.get('requester'),
            requested_target=target,
        )
    elif target.kind in SLURM_KINDS:
        script = _render_sbatch(system, target, passthrough, opts)
        job = Job.objects.create(
            slug=job_slug, name=job_name, kind='slurm_script',
            payload={'script': script, 'naiad': naiad_meta},
            requester=opts.get('requester'),
            requested_target=target,
        )
    else:
        raise DispatchError(
            f'JobTarget kind {target.kind!r} is not supported for '
            f'naiad_evolve (need one of: '
            f'{", ".join(SHELL_KINDS + SLURM_KINDS)}).')

    try:
        dispatch(job)
    except RoutingError as exc:
        raise DispatchError(f'routing failed: {exc}')

    job.refresh_from_db()
    return job


def _passthrough_args(system_slug: str, opts: dict) -> str:
    """Rebuild the CLI argv for a re-invocation that will actually run
    the GA (so NOT including --via-conduit). shlex.quote protects
    values so the string can be embedded safely in a shell command or
    an sbatch script."""
    parts = [shlex.quote(system_slug),
             '--pop',       str(int(opts['pop'])),
             '--gens',      str(int(opts['gens'])),
             '--rate',      repr(float(opts['rate'])),
             '--crossover', repr(float(opts['crossover'])),
             '--elite',     str(int(opts['elite'])),
             '--every',     str(int(opts['every']))]
    if opts.get('seed') is not None:
        parts += ['--seed', str(int(opts['seed']))]
    if opts.get('preset'):
        parts += ['--preset', shlex.quote(str(opts['preset']))]
    if opts.get('cost_cap') is not None:
        parts += ['--cost-cap', repr(float(opts['cost_cap']))]
    if opts.get('watt_cap') is not None:
        parts += ['--watt-cap', repr(float(opts['watt_cap']))]
    if opts.get('length_cap') is not None:
        parts += ['--length-cap', repr(float(opts['length_cap']))]
    if opts.get('volume_cap') is not None:
        parts += ['--volume-cap', repr(float(opts['volume_cap']))]
    if opts.get('save'):
        parts += ['--save', shlex.quote(str(opts['save']))]
    return ' '.join(parts)


# ── Result parser ────────────────────────────────────────────────
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
STAGE_LINE_RE = re.compile(r'^\s*(\d+)\.\s+([a-z0-9-]+)\s*$')
KV_RE = re.compile(r'^\s*(score|passes|length|cost|power|fails)\s*:\s*(.+?)\s*$')


def parse_evolve_stdout(text: str) -> dict | None:
    """Parse the ── Best chain found ── block out of naiad_evolve
    stdout. Returns None if the block is absent (run failed, or the
    output isn't from naiad_evolve). Shape:

        {'score': 0.5282, 'passed': True, 'length': 12,
         'cost': 535.0, 'watts': 332.0,
         'stages': ['sediment-5um', 'reverse-osmosis', ...]}

    Robust to ANSI color codes (manage.py's style.SUCCESS emits them
    when stdout is a TTY) and to extra/missing lines — we only keep
    the fields we recognise."""
    if not text:
        return None
    clean = ANSI_RE.sub('', text)
    lines = clean.splitlines()

    # Find the best-chain header.
    try:
        start = next(i for i, l in enumerate(lines)
                     if 'Best chain found' in l)
    except StopIteration:
        return None

    out: dict[str, Any] = {'stages': []}
    in_stages = False
    for line in lines[start + 1:]:
        stripped = line.rstrip()
        if not stripped:
            if in_stages:
                break
            continue
        m = STAGE_LINE_RE.match(stripped)
        if m:
            in_stages = True
            out['stages'].append(m.group(2))
            continue
        if in_stages:
            # Left the stages block (e.g. "output vs target:" header).
            break
        m = KV_RE.match(stripped)
        if not m:
            if stripped.startswith('stages'):
                in_stages = True
            continue
        key, raw = m.group(1), m.group(2).strip()
        if key == 'score':
            try:    out['score']   = float(raw)
            except ValueError: pass
        elif key == 'passes':
            out['passed'] = raw.strip().lower() in ('true', '1', 'yes')
        elif key == 'length':
            try:    out['length']  = int(raw)
            except ValueError: pass
        elif key == 'cost':
            try:    out['cost']    = float(raw.lstrip('€').strip())
            except ValueError: pass
        elif key == 'power':
            try:    out['watts']   = float(raw.rstrip('W').strip())
            except ValueError: pass
        elif key == 'fails':
            out['fails'] = [s.strip() for s in raw.split(',') if s.strip()]

    if not out['stages']:
        return None
    return out


def _render_sbatch(system, target, passthrough: str, opts: dict) -> str:
    """Render an sbatch script that runs naiad_evolve inside a velour
    checkout on the cluster. Config keys on the target (with sensible
    ALICE defaults): remote_velour_dir, partition, time_limit, account,
    cpus_per_task, mem."""
    cfg = target.config or {}
    remote_dir    = cfg.get('remote_velour_dir', '~/velour-dev')
    partition     = cfg.get('partition', 'cpu-short')
    time_limit    = cfg.get('time_limit', '01:00:00')
    account       = cfg.get('account', '')
    cpus_per_task = int(cfg.get('cpus_per_task', 1))
    mem           = cfg.get('mem', '2G')
    short_slug    = slugify(system.slug)[:40] or 'naiad'

    header = [
        '#!/bin/bash',
        f'#SBATCH --job-name=naiad-{short_slug}',
        f'#SBATCH --partition={partition}',
        f'#SBATCH --time={time_limit}',
        f'#SBATCH --cpus-per-task={cpus_per_task}',
        f'#SBATCH --mem={mem}',
        '#SBATCH --output=naiad-%j.out',
        '#SBATCH --error=naiad-%j.err',
    ]
    if account:
        header.append(f'#SBATCH --account={account}')

    body = [
        '',
        'set -euo pipefail',
        f'cd {remote_dir}',
        f'venv/bin/python manage.py naiad_evolve {passthrough}',
        '',
    ]
    return '\n'.join(header + body)

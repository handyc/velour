"""Package a Det search as a Conduit Job.

Shared by `det_search --via-conduit` and (later) a web endpoint.
Turns a (SearchRun params, target) pair into a dispatched Conduit
Job and stashes the parameters on the Job so the Det importer can
reconstruct the corresponding SearchRun locally after the remote
job finishes.

Bulk results (the scored-candidate JSON for a 4-hour ALICE sweep can
easily be tens of MB; future sweeps could be larger) travel back via
rclone-over-SFTP into VELOUR_RESULTS_DIR/<job.slug>/ on the Velour
host, not through stdout. Job.results_subdir is set to the job slug
at dispatch time; the sbatch template appends an rclone stanza that
copies the per-run results directory back after the Python command
exits. The Det import view reads results.json from Job.results_path
and creates Candidate rows.
"""

from __future__ import annotations

import shlex
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


SHELL_KINDS = ('local', 'vps')
SLURM_KINDS = ('slurm', 'slurm_manual')


class DispatchError(Exception):
    """Bad target slug, disabled target, unsupported kind, etc."""


def dispatch_via_conduit(opts: dict, target_slug: str) -> Any:
    """Create and dispatch a Conduit Job for this Det sweep. `opts`
    mirrors the det_search CLI options dict. Returns the saved Job."""
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
        raise DispatchError(f'JobTarget {target_slug!r} is disabled.')

    job_slug = f'det-search-{timezone.now():%Y%m%d-%H%M%S}'
    job_name = (f'Det search: {opts["candidates"]}c × '
                f'{opts["rules"]}r × n={opts["n_colors"]}')

    # Remote side writes results.json into results_subdir. Both shell
    # and Slurm paths template the same filename.
    results_subdir = job_slug
    results_json_name = 'results.json'

    det_meta = {
        'params': {
            'n_colors':   int(opts['n_colors']),
            'candidates': int(opts['candidates']),
            'rules':      int(opts['rules']),
            'wildcards':  int(opts['wildcards']),
            'width':      int(opts['width']),
            'height':     int(opts['height']),
            'horizon':    int(opts['horizon']),
            'seed':       opts.get('seed') or '',
            'label':      opts.get('label') or '',
        },
        'export_top':     int(opts.get('export_top') or 0),
        'export_class':   opts.get('export_class') or '',
        'results_file':   results_json_name,
    }

    if target.kind in SHELL_KINDS:
        cwd = str(settings.BASE_DIR)
        python_bin = f'{cwd}/venv/bin/python'
        results_dir = str(
            settings.VELOUR_RESULTS_DIR / results_subdir)
        # Local path: write results directly into VELOUR_RESULTS_DIR
        # so the importer finds them without an rclone tail.
        passthrough = _passthrough_args(
            opts,
            export_json_path=f'{results_dir}/{results_json_name}')
        command = (
            f'mkdir -p {shlex.quote(results_dir)} && '
            f'{shlex.quote(python_bin)} manage.py det_search {passthrough}'
        )
        timeout = max(3600, int(opts.get('time_limit') or 0) + 600)
        job = Job.objects.create(
            slug=job_slug, name=job_name, kind='shell',
            payload={'command': command, 'cwd': cwd, 'timeout': timeout,
                     'det': det_meta},
            requester=opts.get('requester'),
            requested_target=target,
            results_subdir=results_subdir,
        )
    elif target.kind in SLURM_KINDS:
        # Slurm: the sbatch body sets $RESULTS before invoking python,
        # so expansion happens in the remote shell's own context.
        passthrough = _passthrough_args(
            opts, export_json_path=f'$RESULTS/{results_json_name}')
        script = _render_sbatch(target, passthrough, opts, results_subdir,
                                results_json_name)
        job = Job.objects.create(
            slug=job_slug, name=job_name, kind='slurm_script',
            payload={'script': script, 'det': det_meta},
            requester=opts.get('requester'),
            requested_target=target,
            results_subdir=results_subdir,
        )
    else:
        raise DispatchError(
            f'JobTarget kind {target.kind!r} is not supported for '
            f'det_search (need one of: '
            f'{", ".join(SHELL_KINDS + SLURM_KINDS)}).')

    try:
        dispatch(job)
    except RoutingError as exc:
        raise DispatchError(f'routing failed: {exc}')

    job.refresh_from_db()
    return job


def _passthrough_args(opts: dict, export_json_path: str) -> str:
    """Rebuild the det_search argv for a re-invocation on the remote
    side. Does NOT include --via-conduit (would recurse) and always
    adds --export-json so the remote writes results to a known path."""
    parts = [
        '--n-colors',   str(int(opts['n_colors'])),
        '--candidates', str(int(opts['candidates'])),
        '--rules',      str(int(opts['rules'])),
        '--wildcards',  str(int(opts['wildcards'])),
        '--width',      str(int(opts['width'])),
        '--height',     str(int(opts['height'])),
        '--horizon',    str(int(opts['horizon'])),
        '--workers',    str(int(opts.get('workers') or 0)),
    ]
    if opts.get('label'):
        parts += ['--label', shlex.quote(str(opts['label']))]
    if opts.get('seed'):
        parts += ['--seed', shlex.quote(str(opts['seed']))]
    if opts.get('time_limit'):
        parts += ['--time-limit', str(int(opts['time_limit']))]
    parts += ['--export-json', export_json_path]
    if opts.get('export_top'):
        parts += ['--export-top', str(int(opts['export_top']))]
    if opts.get('export_class'):
        parts += ['--export-class', shlex.quote(str(opts['export_class']))]
    return ' '.join(parts)


def _format_sbatch_time(seconds: int) -> str:
    """Seconds → HH:MM:SS for SBATCH --time=."""
    seconds = max(60, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def _render_sbatch(target, passthrough: str, opts: dict,
                   results_subdir: str, results_json_name: str) -> str:
    """sbatch that runs det_search on the cluster and rclones the per-
    job results dir back to the Velour server after it exits. Target
    config knobs (with ALICE defaults):

      remote_velour_dir  — where the velour checkout lives on the node
      partition          — Slurm partition (default cpu-short)
      time_limit         — wall clock, e.g. '04:00:00'
      account            — optional --account=
      cpus_per_task      — matched by det_search --workers
      mem                — memory per task
      rclone_remote      — rclone remote name (default 'velour')
      rclone_dest        — remote path root, default 'velour-results'
    """
    cfg = target.config or {}
    remote_dir    = cfg.get('remote_velour_dir', '~/velour-dev')
    partition     = cfg.get('partition', 'cpu-short')
    account       = cfg.get('account', '')
    mem           = cfg.get('mem', '4G')
    rclone_remote = cfg.get('rclone_remote', 'velour')
    rclone_dest   = cfg.get('rclone_dest', 'velour-results').rstrip('/')

    # CLI intent wins over target defaults: a --time-limit of 14400s
    # should become SBATCH --time=04:10:00, not leave the header at
    # the target's seeded 01:00:00. Same idea for --workers: if the
    # user asked for 16 workers the sbatch should reserve 16 CPUs.
    time_limit = cfg.get('time_limit', '04:00:00')
    if opts.get('time_limit'):
        time_limit = _format_sbatch_time(
            int(opts['time_limit']) + 600)  # 10 min rclone slack
    workers = int(opts.get('workers') or 0)
    cpus_per_task = workers if workers >= 1 \
        else int(cfg.get('cpus_per_task', 8))

    header = [
        '#!/bin/bash',
        f'#SBATCH --job-name=det-{results_subdir[:40]}',
        f'#SBATCH --partition={partition}',
        f'#SBATCH --time={time_limit}',
        f'#SBATCH --cpus-per-task={cpus_per_task}',
        f'#SBATCH --mem={mem}',
        '#SBATCH --output=det-%j.out',
        '#SBATCH --error=det-%j.err',
    ]
    if account:
        header.append(f'#SBATCH --account={account}')

    body = [
        '',
        'set -euo pipefail',
        f'cd {remote_dir}',
        '',
        '# Per-job results dir on the compute node. Everything in here',
        '# is rclone\'d back to the Velour server after the run.',
        f'RESULTS="$(pwd)/run-{results_subdir}"',
        'mkdir -p "$RESULTS"',
        'export RESULTS',
        '',
        f'venv/bin/python manage.py det_search {passthrough}',
        '',
        '# Ship results back. rclone must be installed on the compute',
        '# node and configured with a remote named after rclone_remote',
        '# (default "velour") pointing at the Velour host over SFTP.',
        f'rclone copy "$RESULTS/" '
        f'"{rclone_remote}:{rclone_dest}/{results_subdir}/"',
        '',
    ]
    return '\n'.join(header + body)

"""Dispatch a routed `Job` on its `JobTarget`.

Phase 1 implements two real executors:

- `LocalExecutor` runs `shell` jobs as the Velour web-process uid.
  Intentionally NOT sandboxed — see models.py security note.
- `SlurmManualExecutor` creates a `JobHandoff` row so a human can
  copy the sbatch script onto ALICE (Leiden HPC prohibits automated
  `sbatch`), submit it, and paste the Slurm job ID back.

Everything else is a stub that marks the job failed with an
"executor not implemented" note — keeps UI + routing code honest
without pretending hardware exists.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import timedelta

from django.utils import timezone

from .models import Job, JobHandoff, JobTarget
from .routing import route


def dispatch(job: Job) -> Job:
    """Route `job` to a target and dispatch it. Saves status updates
    onto `job` and returns it. For async kinds (local shell), returns
    after kicking off the background thread — the job is already
    marked 'dispatched' / 'running', and will transition to 'done'
    / 'failed' when the subprocess finishes."""
    job.status = 'routing'
    job.save(update_fields=['status'])

    target = route(job)
    job.target = target
    job.dispatched_at = timezone.now()
    job.status = 'dispatched'
    job.save(update_fields=['target', 'dispatched_at', 'status'])

    executor = EXECUTORS.get(target.kind, _not_implemented)
    executor(job, target)
    return job


def _local_shell(job: Job, target: JobTarget) -> None:
    """Run a shell command in a background thread so the web request
    returns immediately. Fine for Phase 1; move to a worker queue
    once we have jobs that run longer than the browser tab stays
    open."""
    payload = job.payload or {}
    command = payload.get('command')
    if not command:
        _mark_failed(job, 'local shell: payload missing "command"')
        return

    job.status = 'running'
    job.save(update_fields=['status'])

    def _runner():
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=payload.get('cwd') or None,
                env=payload.get('env') or None,
                timeout=payload.get('timeout') or 3600,
            )
            job.stdout = result.stdout
            job.stderr = result.stderr
            job.exit_code = result.returncode
            job.status = 'done' if result.returncode == 0 else 'failed'
        except subprocess.TimeoutExpired as exc:
            job.stderr = f'timeout after {exc.timeout}s'
            job.status = 'failed'
        except Exception as exc:
            job.stderr = f'{type(exc).__name__}: {exc}'
            job.status = 'failed'
        job.finished_at = timezone.now()
        job.save(update_fields=[
            'stdout', 'stderr', 'exit_code', 'status', 'finished_at'])

    threading.Thread(target=_runner, daemon=True).start()


def _slurm_manual(job: Job, target: JobTarget) -> None:
    """Materialise a `JobHandoff` row. A human takes it from there."""
    payload = job.payload or {}
    script = payload.get('script')
    if not script:
        _mark_failed(job, 'slurm_manual: payload missing "script"')
        return

    cfg = target.config or {}
    host = target.host or 'alice.leidenuniv.nl'
    ssh_user = cfg.get('ssh_user', 'username')
    partition = cfg.get('partition', 'cpu-short')
    remote_dir = cfg.get('remote_dir', '~/jobs')
    instructions = (
        f'# 1. Copy the script to {host}:\n'
        f'scp job_{job.pk}.sh {ssh_user}@{host}:{remote_dir}/\n\n'
        f'# 2. SSH in and submit:\n'
        f'ssh {ssh_user}@{host}\n'
        f'cd {remote_dir}\n'
        f'sbatch --partition={partition} job_{job.pk}.sh\n\n'
        f'# 3. Paste the Slurm job ID (e.g. 12345678) into the '
        f'handoff page.\n'
    )
    JobHandoff.objects.create(
        job=job,
        script_text=script,
        submit_instructions=instructions,
    )
    job.status = 'handoff'
    job.save(update_fields=['status'])


def _not_implemented(job: Job, target: JobTarget) -> None:
    _mark_failed(
        job,
        f'executor for target kind {target.kind!r} not implemented '
        f'in Phase 1')


def _mark_failed(job: Job, reason: str) -> None:
    job.stderr = reason
    job.status = 'failed'
    job.finished_at = timezone.now()
    job.save(update_fields=['stderr', 'status', 'finished_at'])


EXECUTORS = {
    'local':        _local_shell,
    'slurm_manual': _slurm_manual,
    # Others get _not_implemented via dispatch()'s .get() fallback.
}

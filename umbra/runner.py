"""Umbra runner — execute Experiment.code in a sandboxed subprocess.

Writes the code to a temp .py, invokes the current python interpreter
on it with rlimits for CPU + address space and a wall-clock timeout,
captures stdout/stderr/elapsed back onto the Experiment.
"""
import os
import resource
import subprocess
import sys
import tempfile
import time

from .models import Experiment


# Wall clock bounds the user experience; CPU bounds runaway loops.
# RLIMIT_CPU counts CPU-seconds *summed across threads*, so any
# parallel runtime (Concrete's HPX, TenSEAL's OpenMP) burns through
# the limit much faster than wall clock would suggest.  Give CPU
# enough headroom for parallel backends; wall clock is the real cap.
CPU_SECONDS    = 240
WALL_TIMEOUT_S = 60
MAX_OUTPUT     = 64 * 1024

# Note: RLIMIT_AS was 1 GiB but Concrete's MLIR runtime reserves much
# more virtual address space than it actually pages in (key gen alone
# can reserve multiple GiB of arena), and any AS cap tripped its OOM
# path silently.  We no longer set a virtual-address-space limit.


def _preexec_limits():
    resource.setrlimit(resource.RLIMIT_CPU,
                       (CPU_SECONDS, CPU_SECONDS))


def run_experiment(experiment: Experiment) -> Experiment:
    fd, path = tempfile.mkstemp(prefix='umbra_', suffix='.py')
    with os.fdopen(fd, 'w') as fp:
        fp.write(experiment.code or '')

    experiment.status      = Experiment.STATUS_RUNNING
    experiment.last_output = ''
    experiment.last_error  = ''
    experiment.save(update_fields=['status', 'last_output', 'last_error'])

    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
            timeout=WALL_TIMEOUT_S,
            preexec_fn=_preexec_limits,
            check=False,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        experiment.last_output = proc.stdout[:MAX_OUTPUT]
        experiment.last_error  = proc.stderr[:MAX_OUTPUT]
        experiment.last_run_ms = elapsed_ms
        experiment.status      = (Experiment.STATUS_DONE
                                  if proc.returncode == 0
                                  else Experiment.STATUS_FAILED)
    except subprocess.TimeoutExpired as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        out = (e.stdout or b'').decode('utf-8', 'replace')
        err = (e.stderr or b'').decode('utf-8', 'replace')
        experiment.last_output = out[:MAX_OUTPUT]
        experiment.last_error  = (f'TIMEOUT after {WALL_TIMEOUT_S}s\n'
                                  + err)[:MAX_OUTPUT]
        experiment.last_run_ms = elapsed_ms
        experiment.status      = Experiment.STATUS_FAILED
    except Exception as exc:
        experiment.last_error  = f'runner error: {exc!r}'
        experiment.last_run_ms = int((time.monotonic() - started) * 1000)
        experiment.status      = Experiment.STATUS_FAILED
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    experiment.save()
    return experiment

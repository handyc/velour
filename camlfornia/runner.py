"""Sandboxed OCaml runner.

Writes code to a tempfile, invokes `ocaml` with a short timeout, and
returns stdout/stderr/exit_code. Returns a sentinel when the binary
is missing so the UI can nudge the operator to install it.
"""

import os
import shutil
import subprocess
import tempfile


TIMEOUT_SECONDS = 6
OUTPUT_LIMIT = 20_000  # characters — guard against runaway prints


def ocaml_installed():
    return shutil.which('ocaml') is not None


def run(code, stdin=''):
    if not ocaml_installed():
        return {
            'installed': False,
            'stdout': '',
            'stderr': ('OCaml is not installed on this server.\n'
                       'Try: sudo apt install ocaml\n'
                       'Then restart the page.'),
            'exit_code': None,
            'timed_out': False,
        }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.ml', delete=False,
                                     encoding='utf-8') as f:
        f.write(code)
        path = f.name

    try:
        proc = subprocess.run(
            ['ocaml', path],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            # Strip inherited env so library paths from the venv don't leak.
            env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/tmp'},
        )
        return {
            'installed': True,
            'stdout': proc.stdout[:OUTPUT_LIMIT],
            'stderr': proc.stderr[:OUTPUT_LIMIT],
            'exit_code': proc.returncode,
            'timed_out': False,
        }
    except subprocess.TimeoutExpired as e:
        return {
            'installed': True,
            'stdout': (e.stdout or '')[:OUTPUT_LIMIT] if isinstance(
                e.stdout, str) else '',
            'stderr': (f'Timed out after {TIMEOUT_SECONDS}s. '
                       f'Check for infinite loops or blocking input.'),
            'exit_code': None,
            'timed_out': True,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

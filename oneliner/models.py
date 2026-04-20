"""Oneliner — C programs short enough to fit in a tweet.

The whole point of the app is the 80-character ceiling: every row in
`Oneliner.code` must be ≤ 80 chars after trailing whitespace is
stripped. That's the Fortran punch-card / 80-column terminal limit,
and it forces K&R tricks (implicit int return, comma operator for
side effects, `main(c){…}` as a free counter) that are fun to look
at but actively discouraged in modern C. This app is a museum for
them.

`compile()` shells out to `cc` (whatever `/usr/bin/cc` resolves to)
with the row's own `compile_flags` and captures stderr + the stripped
binary size. `run()` executes the compiled artifact with a stdin
string and a 3-second timeout and captures stdout.

Security note: compile+run execute as the Velour web-process uid,
same as `conduit.executors._local_shell`. This is not a sandbox.
The single-trusted-user assumption that holds for the rest of Velour
holds here too — don't expose this app on a multi-tenant install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models


MAX_LINE = 80


class Oneliner(models.Model):
    """One tiny C program."""

    STATUS_CHOICES = [
        ('unknown', 'Not yet compiled'),
        ('ok',      'Compiled cleanly'),
        ('warn',    'Compiled with warnings'),
        ('error',   'Compile failed'),
    ]

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160)
    purpose = models.TextField(
        blank=True,
        help_text='One-sentence description of what the program does '
                  'and the trick that makes it fit in 80 cols.')
    code = models.TextField(
        help_text='The C source. Every line (after rstrip) must be '
                  '≤ 80 characters. Trailing blank lines are allowed '
                  'but ignored for the count.')
    compile_flags = models.CharField(
        max_length=200, default='-w',
        help_text='Extra cc flags. `-w` suppresses warnings (most of '
                  'these programs are deliberately K&R-style and '
                  'compile with a dozen warnings under -Wall).')
    stdin_fixture = models.TextField(
        blank=True,
        help_text='Optional canonical stdin to feed to run(). '
                  'Stored so the detail page can replay the demo '
                  'without the operator remembering the input.')

    last_status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='unknown')
    last_compile_output = models.TextField(blank=True)
    last_binary_size = models.PositiveIntegerField(null=True, blank=True)
    last_run_stdout = models.TextField(blank=True)
    last_run_exit = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.char_count} ch)'

    @property
    def lines(self) -> list[str]:
        """Code as a list of lines, trailing blank lines dropped."""
        rows = self.code.splitlines()
        while rows and not rows[-1].strip():
            rows.pop()
        return rows

    @property
    def char_count(self) -> int:
        """Longest line's stripped length — this is the number the
        80-char ceiling actually applies to. We surface `len(code)`
        too on the detail page for curiosity, but the constraint is
        per-line."""
        return max((len(r.rstrip()) for r in self.lines), default=0)

    @property
    def total_chars(self) -> int:
        return sum(len(r.rstrip()) for r in self.lines)

    @property
    def n_lines(self) -> int:
        return len(self.lines)

    def clean(self):
        super().clean()
        if not self.code.strip():
            raise ValidationError({'code': 'Code is empty.'})
        over = [(i, r.rstrip()) for i, r in enumerate(self.lines, 1)
                if len(r.rstrip()) > MAX_LINE]
        if over:
            msg = '; '.join(
                f'line {i}: {len(r)} chars' for i, r in over)
            raise ValidationError({'code':
                f'Every line must be ≤ {MAX_LINE} chars. {msg}.'})

    def compile(self, keep_binary: bool = False) -> dict:
        """Shell out to cc, capture stderr + stripped binary size.
        Updates last_* fields and saves. Returns a dict for immediate
        UI consumption: {status, output, binary_size, binary_path}.

        keep_binary=True leaves the compiled artifact on disk so a
        subsequent run() doesn't have to recompile. The caller is
        responsible for cleaning up via `_cleanup_binary`."""
        cc = shutil.which('cc') or shutil.which('gcc')
        if not cc:
            result = {'status': 'error',
                      'output': 'No cc/gcc on PATH.',
                      'binary_size': None, 'binary_path': None}
            self._record_compile(result)
            return result

        tmp = Path(tempfile.mkdtemp(prefix='oneliner-'))
        src = tmp / 'src.c'
        binp = tmp / 'a.out'
        src.write_text(self.code)
        flags = (self.compile_flags or '').split()
        cmd = [cc, *flags, '-o', str(binp), str(src)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp, ignore_errors=True)
            result = {'status': 'error',
                      'output': 'cc timed out after 5s.',
                      'binary_size': None, 'binary_path': None}
            self._record_compile(result)
            return result

        output = (proc.stderr or '').strip()
        if proc.returncode != 0 or not binp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
            result = {'status': 'error',
                      'output': output or 'cc failed with no stderr.',
                      'binary_size': None, 'binary_path': None}
            self._record_compile(result)
            return result

        # strip(1) gives us a more honest size; fall back to as-is.
        strip = shutil.which('strip')
        if strip:
            subprocess.run([strip, str(binp)],
                           capture_output=True, timeout=3)
        size = binp.stat().st_size
        status = 'warn' if output else 'ok'
        result = {'status': status, 'output': output,
                  'binary_size': size, 'binary_path': str(binp)}
        self._record_compile(result)
        if not keep_binary:
            shutil.rmtree(tmp, ignore_errors=True)
            result['binary_path'] = None
        return result

    def run(self, stdin: str | None = None, timeout: float = 3.0) -> dict:
        """Compile if needed, then execute with `stdin`. Captures the
        first 8KB of stdout + exit code. Updates last_run_* and
        saves."""
        compiled = self.compile(keep_binary=True)
        if compiled['status'] == 'error' or not compiled['binary_path']:
            result = {'exit': None,
                      'stdout': '(compile failed; see compile output)',
                      'truncated': False}
            self._record_run(result)
            return result

        binp = Path(compiled['binary_path'])
        try:
            proc = subprocess.run(
                [str(binp)],
                input=(stdin if stdin is not None else self.stdin_fixture),
                capture_output=True, text=True, timeout=timeout)
            stdout = proc.stdout or ''
            truncated = len(stdout) > 8192
            if truncated:
                stdout = stdout[:8192] + '\n...[truncated]'
            result = {'exit': proc.returncode,
                      'stdout': stdout, 'truncated': truncated}
        except subprocess.TimeoutExpired:
            result = {'exit': None,
                      'stdout': f'(timed out after {timeout}s)',
                      'truncated': False}
        finally:
            shutil.rmtree(binp.parent, ignore_errors=True)

        self._record_run(result)
        return result

    def _record_compile(self, result: dict) -> None:
        self.last_status = result['status']
        self.last_compile_output = result['output']
        self.last_binary_size = result['binary_size']
        self.save(update_fields=[
            'last_status', 'last_compile_output',
            'last_binary_size', 'updated_at'])

    def _record_run(self, result: dict) -> None:
        self.last_run_stdout = result['stdout']
        self.last_run_exit = result['exit']
        self.save(update_fields=[
            'last_run_stdout', 'last_run_exit', 'updated_at'])

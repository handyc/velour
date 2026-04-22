"""Scan PHP files for secrets / PII before sharing them with an assistant.

    python manage.py liftphp /path/to/old/site \\
        --app myapp \\
        [--out-dir redacted/] \\
        [--redact] [--strict] \\
        [--worklist worklist.md] \\
        [--dry-run]

Phase 2 of the Datalift legacy-site lifter. Where ``liftsite`` leaves
PHP files in place with a "deferred" flag, ``liftphp`` actually reads
them — but only through :func:`datalift.php_scanner.scan`, which
returns structured findings (category, line, masked snippet) without
surfacing the raw secret.

Three outputs:

1. A security section appended to the worklist: per-file finding
   counts by severity + category, with line numbers but masked values.
2. ``--redact`` (optional): a parallel tree of PHP files where every
   finding has been replaced by a ``/*<<REDACTED_CATEGORY>>*/`` marker.
   These redacted copies are what an assistant reads if you're using
   one to scaffold Django views from the PHP logic.
3. ``--strict``: exit code 2 if any finding is present. Use in
   pre-share automation to refuse the lift until a human clears it.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datalift.php_scanner import Finding, redact, scan
from datalift.site_lifter import walk_site, classify


class Command(BaseCommand):
    help = 'Scan PHP files for secrets/PII before sharing (Datalift Phase 2).'

    def add_arguments(self, parser):
        parser.add_argument('source', help='Path to the legacy site root.')
        parser.add_argument(
            '--app', required=True,
            help='Django app label (used for worklist header only).',
        )
        parser.add_argument(
            '--out-dir', default=None,
            help='Write redacted PHP copies here (requires --redact).',
        )
        parser.add_argument(
            '--redact', action='store_true',
            help='Produce redacted copies of each PHP file for Claude review.',
        )
        parser.add_argument(
            '--strict', action='store_true',
            help='Exit nonzero if any finding is present.',
        )
        parser.add_argument(
            '--worklist', default=None,
            help='Append findings to this worklist markdown (default: '
                 'liftphp_worklist.md in the project root).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Scan and report; write no files at all.',
        )

    def handle(self, *args, **opts):
        source = Path(opts['source']).resolve()
        if not source.is_dir():
            raise CommandError(f'source is not a directory: {source}')

        try:
            apps.get_app_config(opts['app'])
        except LookupError:
            raise CommandError(f'unknown app: {opts["app"]}')

        if opts['redact'] and not opts['out_dir']:
            raise CommandError('--redact requires --out-dir')

        project_root = Path(settings.BASE_DIR)
        worklist_path = (
            Path(opts['worklist']).resolve()
            if opts['worklist']
            else project_root / 'liftphp_worklist.md'
        )
        out_dir = Path(opts['out_dir']).resolve() if opts['out_dir'] else None

        per_file: list[tuple[Path, list[Finding]]] = []
        total = Counter()
        php_files = [p for p in walk_site(source) if classify(p) == 'php']

        for php in php_files:
            try:
                text = php.read_text(encoding='utf-8', errors='replace')
            except OSError as e:
                self.stderr.write(f'  ! {php}: read error: {e}')
                continue
            findings = scan(text)
            per_file.append((php, findings))
            for f in findings:
                total[f.severity] += 1

            if opts['redact'] and out_dir is not None and not opts['dry_run']:
                rel = php.relative_to(source)
                dst = out_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(redact(text, findings), encoding='utf-8')

            self.stdout.write(
                f'  {"!" if findings else "✓"} {php.relative_to(source)}: '
                f'{len(findings)} finding(s)'
            )

        if not opts['dry_run']:
            worklist_path.parent.mkdir(parents=True, exist_ok=True)
            worklist_path.write_text(
                _render_php_worklist(per_file, source, opts['app'], total),
                encoding='utf-8',
            )
            self.stdout.write(f'php worklist → {worklist_path}')

        self.stdout.write(self.style.SUCCESS(
            f'\n{len(php_files)} PHP file(s) scanned. '
            f'Findings: critical={total["critical"]} '
            f'high={total["high"]} medium={total["medium"]}.'
        ))

        if opts['strict'] and sum(total.values()) > 0:
            sys.exit(2)


def _render_php_worklist(
    per_file: list[tuple[Path, list[Finding]]],
    source: Path,
    app: str,
    total: Counter,
) -> str:
    lines: list[str] = []
    lines.append(f'# liftphp security worklist — {app}')
    lines.append('')
    lines.append(f'Source: `{source}`')
    lines.append('')
    lines.append('## Summary')
    lines.append('')
    lines.append(f'- Files scanned: {len(per_file)}')
    lines.append(f'- Critical findings: {total["critical"]}')
    lines.append(f'- High findings: {total["high"]}')
    lines.append(f'- Medium findings: {total["medium"]}')
    lines.append('')

    flagged = [(p, fs) for p, fs in per_file if fs]
    clean = [p for p, fs in per_file if not fs]

    if flagged:
        lines.append('## Flagged files')
        lines.append('')
        lines.append('Do not share these verbatim. Use `--redact --out-dir …` '
                     'to produce assistant-safe copies, or hand-clear the '
                     'findings below before sharing.')
        lines.append('')
        for php, fs in flagged:
            rel = php.relative_to(source)
            by_cat = Counter(f.category for f in fs)
            cat_summary = ', '.join(f'{k}×{v}' for k, v in sorted(by_cat.items()))
            lines.append(f'### `{rel}` — {len(fs)} finding(s): {cat_summary}')
            lines.append('')
            for f in fs:
                lines.append(
                    f'- L{f.line}:{f.col} [{f.severity}/{f.category}] '
                    f'`{f.snippet}`'
                )
            lines.append('')

    if clean:
        lines.append('## Clean PHP (safe to share for conversion)')
        lines.append('')
        for php in clean:
            lines.append(f'- `{php.relative_to(source)}`')
        lines.append('')

    return '\n'.join(lines) + '\n'

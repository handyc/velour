"""Port a legacy project to Django in one command.

    python manage.py port path/to/dump.sql --app myapp \\
        [--php-dir path/to/legacy/src/] \\
        [--source-database luclla1q_babybase] \\
        [--force]

Chains the Datalift pipeline:

1. If ``--php-dir`` is given, run the PHP scanner. Any findings
   surface as a summary; ``--force`` is required to continue past a
   non-empty report. This blocks the default path from ever letting
   a secret-bearing PHP tree flow downstream.
2. Run ``genmodels`` — produces ``<app>/models.py``, ``<app>/admin.py``,
   and ``<app>/ingest/table_map.json`` keyed off the dump's CREATE
   TABLE blocks with full inference (field types, FK resolution,
   Laravel conventions, TextChoices, starter map with value_maps,
   drop_columns, synthesize, rewrite_laravel_passwords).
3. Print the remaining manual steps verbatim — review, migrate,
   ingestdump.

The goal: after ``port``, a review pass, and three follow-up
commands, a legacy MySQL-backed app runs as a Django project.

Nothing here is destructive. Generated files refuse to overwrite a
non-datalift target unless ``--force`` is passed.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from datalift.model_generator import generate_all
from datalift.php_scanner import scan as php_scan
from datalift.site_lifter import classify, walk_site


class Command(BaseCommand):
    help = ('Port a legacy project to Django: scan PHP (optional), '
            'generate models + admin + ingest map from a mysqldump.')

    def add_arguments(self, parser):
        parser.add_argument('dump', help='Path to the mysqldump .sql file.')
        parser.add_argument('--app', required=True,
            help='Django app label that receives the port. The app must '
                 'already exist (manage.py startapp <app>).')
        parser.add_argument('--app-dir', default=None,
            help='Target app filesystem directory. Required when --app '
                 'is not installed in the running Django project.')
        parser.add_argument('--php-dir', default=None,
            help='Optional legacy PHP source tree. Scanned for secrets/PII '
                 'before generation; non-empty findings block the pipeline '
                 'unless --force is given.')
        parser.add_argument('--source-database', default='',
            help='Label recorded in the generated map and file headers.')
        parser.add_argument('--force', action='store_true',
            help='Overwrite existing genmodels output and skip the '
                 'PHP-findings gate.')
        parser.add_argument('--dry-run', action='store_true',
            help='Run the scan and parse the dump, but write nothing.')

    # ── Helpers ────────────────────────────────────────────────

    def _scan_php(self, php_dir: Path) -> list:
        """Run the scanner on every PHP file in the tree; return
        (relative_path, findings) list."""
        out = []
        for path in walk_site(php_dir):
            if classify(path) != 'php':
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            findings = php_scan(text)
            if findings:
                out.append((path.relative_to(php_dir), findings))
        return out

    def _print_scan_summary(self, scan_results):
        total = sum(len(f) for _, f in scan_results)
        self.stdout.write(self.style.WARNING(
            f'PHP scan: {total} finding(s) across {len(scan_results)} file(s).'
        ))
        severities = Counter()
        categories = Counter()
        for rel, findings in scan_results:
            for f in findings:
                severities[f.severity] += 1
                categories[f.category] += 1
        self.stdout.write(f'  by severity: {dict(severities)}')
        self.stdout.write(f'  by category: {dict(categories)}')
        # Show the worst 5 files
        by_file = sorted(scan_results, key=lambda x: -len(x[1]))[:5]
        for rel, findings in by_file:
            self.stdout.write(f'    {rel}: {len(findings)} finding(s)')

    # ── Handle ─────────────────────────────────────────────────

    def handle(self, *args, **opts):
        dump = Path(opts['dump']).resolve()
        if not dump.exists():
            raise CommandError(f'cannot read dump: {dump}')
        app_label = opts['app']
        try:
            app_config = apps.get_app_config(app_label)
            app_dir = Path(app_config.path)
        except LookupError:
            if opts.get('app_dir'):
                app_dir = Path(opts['app_dir']).resolve()
            else:
                raise CommandError(
                    f'app `{app_label}` is not installed in this project. '
                    f'Either register it or pass --app-dir /path/to/<app>/ '
                    f'so outputs go to the right place.'
                )

        # ── Step 1: PHP scan gate ───────────────────────────────
        if opts['php_dir']:
            php_dir = Path(opts['php_dir']).resolve()
            if not php_dir.is_dir():
                raise CommandError(f'--php-dir is not a directory: {php_dir}')
            self.stdout.write(f'1. Scanning PHP tree at {php_dir} …')
            scan_results = self._scan_php(php_dir)
            if scan_results:
                self._print_scan_summary(scan_results)
                if not opts['force']:
                    raise CommandError(
                        'PHP scan found secrets/PII. Review with '
                        '`manage.py liftphp <dir> --app <app>` and pass '
                        '--force once you have cleared the findings.'
                    )
                self.stdout.write(self.style.WARNING(
                    '  --force: continuing past findings.'))
            else:
                self.stdout.write(self.style.SUCCESS(
                    '  no findings. Proceeding.'))

        # ── Step 2: Parse dump and generate everything ─────────
        self.stdout.write(f'2. Parsing dump {dump} …')
        text = dump.read_text(encoding='utf-8', errors='replace')
        models_src, admin_src, tmap = generate_all(
            text, app_label=app_label,
            source_database=opts['source_database'],
        )
        n_tables = len(tmap.get('tables') or {})
        self.stdout.write(f'   {n_tables} model(s) inferred from '
                          f'CREATE TABLE blocks.')

        # ── Step 3: Write files (unless --dry-run) ─────────────
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                'Dry run — nothing written.'))
            return

        models_path = app_dir / 'models.py'
        admin_path = app_dir / 'admin.py'
        map_path = app_dir / 'ingest' / 'table_map.json'

        def _safe_write(target: Path, content: str, label: str):
            if target.exists() and not opts['force']:
                existing = target.read_text(encoding='utf-8')
                if 'Auto-generated by datalift genmodels' not in existing:
                    raise CommandError(
                        f'{target} exists and is not prior datalift output. '
                        f'Pass --force to overwrite.'
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
            self.stdout.write(f'   → {target} ({label})')

        self.stdout.write('3. Writing generated files …')
        _safe_write(models_path, models_src, f'{n_tables} model(s)')
        _safe_write(admin_path, admin_src, 'ModelAdmin registrations')

        import json
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(
            json.dumps(tmap, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
        self.stdout.write(f'   → {map_path} (ingestdump map)')

        # ── Step 4: Next steps ─────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Port complete.'))
        self.stdout.write('')
        self.stdout.write('Next steps:')
        self.stdout.write(f'  1. Review {models_path.relative_to(app_dir.parent)}'
                          ' — field types, FKs, pluralisation, docstrings.')
        self.stdout.write(f'  2. Review {map_path.relative_to(app_dir.parent)}'
                          ' — value_maps for ENUMs, synthesize rules.')
        self.stdout.write(f'  3. python manage.py makemigrations {app_label}')
        self.stdout.write(f'  4. python manage.py migrate')
        self.stdout.write(f'  5. python manage.py ingestdump {dump} '
                          f'--app {app_label} --map {map_path} --truncate')
        self.stdout.write(f'  6. python manage.py createsuperuser  '
                          f'# then `runserver` and visit /admin/')

"""End-to-end orchestrator: chain every Datalift step in one command.

    python manage.py liftall \\
        --dump path/to/dump.sql \\
        --app myapp \\
        [--legacy-dir path/to/legacy/source/] \\
        [--theme-dir path/to/theme/] \\
        [--theme-type wp|smarty|twig] \\
        [--migrate] \\
        [--ingest] \\
        [--source-database name] \\
        [--force] [--dry-run]

Pipeline (each step skipped if the input it needs isn't present):

    1.  port        — scan PHP (if --legacy-dir), genmodels from --dump
    2.  migrate     — `makemigrations <app> && migrate` (if --migrate)
    3.  ingestdump  — load rows (if --ingest, requires migrated tables)
    4.  liftphp     — full PHP scan + worklist (if --legacy-dir)
    5.  liftsite    — HTML/JS/CSS routing (if --legacy-dir)
    6.  liftwp / liftsmarty / liftwig / liftblade / liftvolt
                    — theme lift (if --theme-dir + --theme-type)
    7a. liftmigrations — Laravel Blueprints → models (if --migrations-dir)
    7b. liftlaravel — routes + controllers (if --laravel-dir)
    8.  liftsymfony — controllers + routes (if --symfony-dir)
    9.  liftdoctrine — `#[ORM\\Entity]` → models (if --symfony-dir)
    10. liftcodeigniter — CI3/CI4 routes + controllers (if --codeigniter-dir)
    11. liftcakephp — CakePHP routes + controllers (if --cakephp-dir)

Each underlying command writes its own worklist; this orchestrator
prints a unified summary at the end. Pure Datalift, no LLM, no
network.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


THEME_TYPE_TO_COMMAND = {
    'wp':      'liftwp',
    'smarty':  'liftsmarty',
    'twig':    'liftwig',
    'blade':   'liftblade',
    'volt':    'liftvolt',
}


class Command(BaseCommand):
    help = 'End-to-end Datalift orchestrator (port + migrate + ingest + ' \
           'liftphp + liftsite + liftwp/liftsmarty/liftwig).'

    def add_arguments(self, parser):
        parser.add_argument('--dump', required=True,
                            help='Path to the mysqldump (or pg_dump --inserts) .sql file.')
        parser.add_argument('--app', required=True,
                            help='Django app label that receives the port.')
        parser.add_argument('--legacy-dir', default=None,
                            help='Path to the legacy site source tree '
                                 '(triggers liftphp + liftsite).')
        parser.add_argument('--theme-dir', default=None,
                            help='Path to the legacy theme directory '
                                 '(requires --theme-type).')
        parser.add_argument('--laravel-dir', default=None,
                            help='Path to a Laravel application root '
                                 '(routes/ + app/Http/Controllers/). '
                                 'Triggers liftlaravel — emits urls_laravel.py '
                                 'and views_laravel.py.')
        parser.add_argument('--migrations-dir', default=None,
                            help='Path to a Laravel database/migrations/ '
                                 'directory. Triggers liftmigrations — '
                                 'emits models_migrations.py from Schema::create '
                                 'blueprints. Useful when the source has '
                                 'no SQL dump.')
        parser.add_argument('--symfony-dir', default=None,
                            help='Path to a Symfony application root '
                                 '(src/Controller/ + config/routes/). '
                                 'Triggers liftsymfony — emits urls_symfony.py '
                                 'and views_symfony.py.')
        parser.add_argument('--codeigniter-dir', default=None,
                            help='Path to a CodeIgniter application root '
                                 '(CI3 application/ or CI4 app/ src/). '
                                 'Triggers liftcodeigniter — emits '
                                 'urls_codeigniter.py and views_codeigniter.py.')
        parser.add_argument('--cakephp-dir', default=None,
                            help='Path to a CakePHP application root '
                                 '(config/routes.php + src/Controller/). '
                                 'Triggers liftcakephp — emits '
                                 'urls_cakephp.py and views_cakephp.py.')
        parser.add_argument(
            '--theme-type', choices=list(THEME_TYPE_TO_COMMAND.keys()),
            default=None,
            help='Theme template language: wp (WordPress PHP themes), '
                 'smarty (.tpl), twig (.twig), blade (.blade.php), or '
                 'volt (.volt).',
        )
        parser.add_argument('--migrate', action='store_true',
                            help='Run makemigrations + migrate after genmodels.')
        parser.add_argument('--ingest', action='store_true',
                            help='Run ingestdump after migrate (requires --migrate).')
        parser.add_argument('--source-database', default='',
                            help='Label recorded in headers + map.')
        parser.add_argument('--force', action='store_true',
                            help='Pass --force to underlying genmodels / port.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Run scans + parses without writing anything.')

    def handle(self, *args, **opts):
        # Argument-shape checks (no filesystem side-effects) first,
        # so users get clear messages without having to fix filesystem
        # paths to discover an unrelated CLI mistake.
        if opts['theme_dir'] and not opts['theme_type']:
            raise CommandError('--theme-type is required with --theme-dir.')
        if opts['ingest'] and not opts['migrate']:
            raise CommandError('--ingest requires --migrate (otherwise the '
                               'tables don\'t exist yet).')
        dump = Path(opts['dump']).resolve()
        if not dump.exists():
            raise CommandError(f'cannot read dump: {dump}')
        app_label = opts['app']
        try:
            apps.get_app_config(app_label)
        except LookupError:
            raise CommandError(
                f'app `{app_label}` is not installed in this project.'
            )

        legacy_dir = Path(opts['legacy_dir']).resolve() if opts['legacy_dir'] else None
        theme_dir = Path(opts['theme_dir']).resolve() if opts['theme_dir'] else None
        laravel_dir = (Path(opts['laravel_dir']).resolve()
                       if opts['laravel_dir'] else None)
        if legacy_dir and not legacy_dir.is_dir():
            raise CommandError(f'--legacy-dir is not a directory: {legacy_dir}')
        if theme_dir and not theme_dir.is_dir():
            raise CommandError(f'--theme-dir is not a directory: {theme_dir}')
        if laravel_dir and not laravel_dir.is_dir():
            raise CommandError(f'--laravel-dir is not a directory: {laravel_dir}')

        summary: list[str] = []
        dry = opts['dry_run']

        # ── 1. port (scan + genmodels) ─────────────────────────────
        self._step(1, 'port (scan + genmodels)')
        port_kwargs = {
            'app':      app_label,
            'force':    opts['force'],
            'dry_run':  dry,
            'source_database': opts['source_database'],
        }
        if legacy_dir:
            port_kwargs['php_dir'] = str(legacy_dir)
        try:
            call_command('port', str(dump), **port_kwargs)
            summary.append('1. port: ok')
        except SystemExit:
            raise
        except Exception as e:
            summary.append(f'1. port: FAILED ({e})')
            raise

        # ── 2. migrate ────────────────────────────────────────────
        if opts['migrate'] and not dry:
            self._step(2, 'makemigrations + migrate')
            try:
                call_command('makemigrations', app_label, verbosity=0)
                call_command('migrate', verbosity=0)
                summary.append('2. migrate: ok')
            except Exception as e:
                summary.append(f'2. migrate: FAILED ({e})')
                raise
        elif opts['migrate']:
            summary.append('2. migrate: SKIPPED (dry-run)')
        else:
            summary.append('2. migrate: SKIPPED (no --migrate)')

        # ── 3. ingestdump ─────────────────────────────────────────
        if opts['ingest'] and not dry:
            self._step(3, 'ingestdump')
            map_path = (
                apps.get_app_config(app_label).path
                + '/ingest/table_map.json'
            )
            try:
                call_command('ingestdump', str(dump),
                             app=app_label, map=map_path,
                             truncate=True, continue_on_error=True,
                             verbosity=0)
                summary.append('3. ingestdump: ok')
            except Exception as e:
                summary.append(f'3. ingestdump: FAILED ({e})')
                raise
        else:
            summary.append('3. ingestdump: SKIPPED')

        # ── 4. liftphp ────────────────────────────────────────────
        if legacy_dir:
            self._step(4, f'liftphp ({legacy_dir.name})')
            try:
                liftphp_kw = {'app': app_label, 'verbosity': 0}
                if dry:
                    liftphp_kw['dry_run'] = True
                call_command('liftphp', str(legacy_dir), **liftphp_kw)
                summary.append(f'4. liftphp: ok ({legacy_dir})')
            except Exception as e:
                summary.append(f'4. liftphp: FAILED ({e})')
                raise
        else:
            summary.append('4. liftphp: SKIPPED (no --legacy-dir)')

        # ── 5. liftsite ───────────────────────────────────────────
        if legacy_dir:
            self._step(5, f'liftsite ({legacy_dir.name})')
            try:
                call_command('liftsite', str(legacy_dir), app=app_label,
                             dry_run=dry, verbosity=0)
                summary.append(f'5. liftsite: ok ({legacy_dir})')
            except Exception as e:
                summary.append(f'5. liftsite: FAILED ({e})')
                raise
        else:
            summary.append('5. liftsite: SKIPPED (no --legacy-dir)')

        # ── 6. theme translation ──────────────────────────────────
        if theme_dir:
            theme_type = opts['theme_type']
            cmd = THEME_TYPE_TO_COMMAND[theme_type]
            self._step(6, f'{cmd} ({theme_type}: {theme_dir.name})')
            try:
                kwargs = {'app': app_label, 'dry_run': dry, 'verbosity': 0}
                if cmd == 'liftwp':
                    kwargs['skip_checks'] = True
                call_command(cmd, str(theme_dir), **kwargs)
                summary.append(f'6. {cmd}: ok ({theme_dir})')
            except Exception as e:
                summary.append(f'6. {cmd}: FAILED ({e})')
                raise
        else:
            summary.append('6. theme: SKIPPED (no --theme-dir)')

        # ── 7a. Laravel migrations → models ───────────────────────
        migrations_dir = (Path(opts['migrations_dir']).resolve()
                          if opts['migrations_dir'] else None)
        if migrations_dir:
            if not migrations_dir.is_dir():
                raise CommandError(
                    f'--migrations-dir is not a directory: {migrations_dir}'
                )
            self._step(7, f'liftmigrations ({migrations_dir.name})')
            try:
                kwargs = {'app': app_label, 'verbosity': 0}
                if dry:
                    kwargs['dry_run'] = True
                call_command('liftmigrations', str(migrations_dir), **kwargs)
                summary.append(f'7. liftmigrations: ok ({migrations_dir})')
            except Exception as e:
                summary.append(f'7. liftmigrations: FAILED ({e})')
                raise
        else:
            summary.append('7. liftmigrations: SKIPPED (no --migrations-dir)')

        # ── 7b. Laravel routes + controllers ──────────────────────
        if laravel_dir:
            self._step(7, f'liftlaravel ({laravel_dir.name})')
            try:
                kwargs = {'app': app_label, 'verbosity': 0}
                if dry:
                    kwargs['dry_run'] = True
                call_command('liftlaravel', str(laravel_dir), **kwargs)
                summary.append(f'7. liftlaravel: ok ({laravel_dir})')
            except Exception as e:
                summary.append(f'7. liftlaravel: FAILED ({e})')
                raise
        else:
            summary.append('7. liftlaravel: SKIPPED (no --laravel-dir)')

        # ── 8. Symfony controllers + routes ───────────────────────
        symfony_dir = (Path(opts['symfony_dir']).resolve()
                       if opts['symfony_dir'] else None)
        if symfony_dir:
            if not symfony_dir.is_dir():
                raise CommandError(
                    f'--symfony-dir is not a directory: {symfony_dir}'
                )
            self._step(8, f'liftsymfony ({symfony_dir.name})')
            try:
                kwargs = {'app': app_label, 'verbosity': 0}
                if dry:
                    kwargs['dry_run'] = True
                call_command('liftsymfony', str(symfony_dir), **kwargs)
                summary.append(f'8. liftsymfony: ok ({symfony_dir})')
            except Exception as e:
                summary.append(f'8. liftsymfony: FAILED ({e})')
                raise
        else:
            summary.append('8. liftsymfony: SKIPPED (no --symfony-dir)')

        # ── 9. Doctrine entities → models ─────────────────────────
        # Any Symfony app with src/Entity/ also feeds liftdoctrine —
        # the two emit non-overlapping outputs (urls/views vs models).
        if symfony_dir:
            self._step(9, f'liftdoctrine ({symfony_dir.name})')
            try:
                kwargs = {'app': app_label, 'verbosity': 0}
                if dry:
                    kwargs['dry_run'] = True
                call_command('liftdoctrine', str(symfony_dir), **kwargs)
                summary.append(f'9. liftdoctrine: ok ({symfony_dir})')
            except Exception as e:
                summary.append(f'9. liftdoctrine: FAILED ({e})')
                raise
        else:
            summary.append('9. liftdoctrine: SKIPPED (no --symfony-dir)')

        # ── 10. CodeIgniter routes + controllers ──────────────────
        codeigniter_dir = (Path(opts['codeigniter_dir']).resolve()
                           if opts['codeigniter_dir'] else None)
        if codeigniter_dir:
            if not codeigniter_dir.is_dir():
                raise CommandError(
                    f'--codeigniter-dir is not a directory: {codeigniter_dir}'
                )
            self._step(10, f'liftcodeigniter ({codeigniter_dir.name})')
            try:
                kwargs = {'app': app_label, 'verbosity': 0}
                if dry:
                    kwargs['dry_run'] = True
                call_command('liftcodeigniter', str(codeigniter_dir), **kwargs)
                summary.append(f'10. liftcodeigniter: ok ({codeigniter_dir})')
            except Exception as e:
                summary.append(f'10. liftcodeigniter: FAILED ({e})')
                raise
        else:
            summary.append('10. liftcodeigniter: SKIPPED (no --codeigniter-dir)')

        # ── 11. CakePHP routes + controllers ──────────────────────
        cakephp_dir = (Path(opts['cakephp_dir']).resolve()
                       if opts['cakephp_dir'] else None)
        if cakephp_dir:
            if not cakephp_dir.is_dir():
                raise CommandError(
                    f'--cakephp-dir is not a directory: {cakephp_dir}'
                )
            self._step(11, f'liftcakephp ({cakephp_dir.name})')
            try:
                kwargs = {'app': app_label, 'verbosity': 0}
                if dry:
                    kwargs['dry_run'] = True
                call_command('liftcakephp', str(cakephp_dir), **kwargs)
                summary.append(f'11. liftcakephp: ok ({cakephp_dir})')
            except Exception as e:
                summary.append(f'11. liftcakephp: FAILED ({e})')
                raise
        else:
            summary.append('11. liftcakephp: SKIPPED (no --cakephp-dir)')

        # ── Final summary ─────────────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('═══ liftall summary ═══'))
        for line in summary:
            self.stdout.write('  ' + line)
        self.stdout.write('')
        if dry:
            self.stdout.write(self.style.WARNING(
                '(dry-run: no files were written)'
            ))

    def _step(self, n: int, label: str) -> None:
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'━━━ Step {n}/11 — {label} ━━━'
        ))

"""Aggregate per-app status reports into one Codex manual.

Each Velour app may expose `<app>/codex_report.py` with a top-level
function `report() -> dict` returning:

    {
        'title':     'human-readable section title',
        'body_md':   'markdown body, multi-line is fine',
        'sort_hint': optional int (lower = earlier in manual),
    }

This command walks INSTALLED_APPS, calls `report()` on every app
that has one, and writes/updates a Codex manual at slug
`app-status-{YYYY-MM-DD}`. Apps without a codex_report module are
silently skipped; apps whose report() raises are noted in a final
"errors" section so a broken app doesn't kill the whole report.

Idempotent — re-running the same day overwrites the same manual.

    python manage.py codex_app_reports
    python manage.py codex_app_reports --date 2026-04-26
"""

from __future__ import annotations

import importlib
import traceback
from datetime import date

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from django.utils import timezone

from codex.models import Manual, Section


def _upsert_manual(slug, **fields):
    m, _ = Manual.objects.get_or_create(slug=slug, defaults=fields)
    for k, v in fields.items():
        setattr(m, k, v)
    m.save()
    return m


def _upsert_section(manual, slug, sort_order, title, body):
    s, _ = Section.objects.get_or_create(
        manual=manual, slug=slug,
        defaults={'sort_order': sort_order, 'title': title})
    s.sort_order = sort_order
    s.title = title
    s.body = body
    s.save()
    return s


def collect_reports() -> tuple[list[dict], list[tuple[str, str]]]:
    """Walk INSTALLED_APPS, import each `<app>.codex_report` if it
    exists, call `report()`, gather the dicts. Returns (reports,
    errors) where errors is a list of (app_label, traceback)."""
    reports: list[dict] = []
    errors: list[tuple[str, str]] = []
    for cfg in django_apps.get_app_configs():
        modname = f'{cfg.name}.codex_report'
        try:
            mod = importlib.import_module(modname)
        except ModuleNotFoundError:
            continue
        except Exception:
            errors.append((cfg.label, traceback.format_exc()))
            continue
        fn = getattr(mod, 'report', None)
        if not callable(fn):
            continue
        try:
            r = fn()
        except Exception:
            errors.append((cfg.label, traceback.format_exc()))
            continue
        if not isinstance(r, dict):
            continue
        r.setdefault('app_label', cfg.label)
        r.setdefault('sort_hint', 100)
        reports.append(r)
    return reports, errors


class Command(BaseCommand):
    help = 'Aggregate per-app codex_report() hooks into a daily status manual.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD; defaults to today.')

    def handle(self, *args, **opts):
        d = (date.fromisoformat(opts['date'])
             if opts.get('date') else timezone.localdate())
        slug = f'app-status-{d.isoformat()}'
        reports, errors = collect_reports()

        manual = _upsert_manual(
            slug,
            title=f'App status — {d.isoformat()}',
            subtitle='Per-app reports collected via codex_report() hooks.',
            author='Velour / Codex',
            version='1',
            abstract=(
                f'Auto-aggregated daily report. {len(reports)} app(s) '
                f'contributed sections; {len(errors)} app(s) errored.'),
        )

        # One section per contributing app, ordered by sort_hint then label.
        for r in sorted(reports,
                        key=lambda x: (x['sort_hint'], x['app_label'])):
            _upsert_section(
                manual, r['app_label'],
                sort_order=r['sort_hint'],
                title=r.get('title') or r['app_label'].title(),
                body=r.get('body_md', '*No body provided.*'))

        # Errors section (only when there are any).
        if errors:
            err_body = '\n\n'.join(
                f'### `{label}`\n\n```\n{tb}\n```'
                for label, tb in errors)
            _upsert_section(manual, '_errors',
                sort_order=10_000,
                title='Reporting errors',
                body=err_body)

        self.stdout.write(self.style.SUCCESS(
            f'/codex/{slug}/ — {len(reports)} app section(s), '
            f'{len(errors)} error(s)'))

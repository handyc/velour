"""Render the three sky Codex Manuals (weekly digest, yearly almanac,
year-to-date retrospective) to PDF on disk under MEDIA_ROOT/sky-pdfs/
so the briefing pin and other surfaces can serve a cacheable file
instead of regenerating on every request.

Idempotent: skips manuals whose on-disk PDF is already newer than
`manual.updated_at`, unless `--force` is passed. Missing manuals
are skipped silently — composing happens upstream.

Usage:

    python manage.py publish_sky_pdfs
        Refresh PDFs for current week's digest + current year's
        almanac + current year's retrospective, only where the
        on-disk file is stale.

    python manage.py publish_sky_pdfs --force
        Re-render even fresh PDFs.

    python manage.py publish_sky_pdfs --slug sky-almanac-2026
        Render one specific manual (must be a sky manual).
"""

import datetime as dt
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone as djtz


SKY_PDF_DIRNAME = 'sky-pdfs'

# Slugs are emitted by the compose_* commands. We allowlist by prefix
# to avoid this command becoming an "any manual to PDF" backdoor that
# the cached-PDF view would then expose.
ALLOWED_PREFIXES = ('sky-digest-', 'sky-almanac-', 'sky-retrospective-')


def sky_pdf_dir():
    """MEDIA_ROOT/sky-pdfs/. Created on demand."""
    d = Path(settings.MEDIA_ROOT) / SKY_PDF_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def sky_pdf_path(slug):
    """Filesystem path for a published sky-PDF. The slug is allowlisted
    by prefix so the helper can't be tricked into writing arbitrary
    files. Returns None for non-sky slugs."""
    if not any(slug.startswith(p) for p in ALLOWED_PREFIXES):
        return None
    safe = slug.replace('/', '_').replace('..', '_')
    return sky_pdf_dir() / f'{safe}.pdf'


def _current_sky_slugs():
    """Slugs of the currently-active sky manuals — the ones the
    briefing's reading pin and the digest page link to. Picks by ISO
    week (digest) and calendar year (almanac, retrospective). Falls
    back to the most recent of each kind so a fresh install with only
    one composed manual still publishes something."""
    from chronos.models import ClockPrefs
    from codex.models import Manual
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(ClockPrefs.load().home_tz)
    local = djtz.now().astimezone(tz)
    iso_year, iso_week, _ = local.isocalendar()

    def _pick(slug, prefix):
        m = Manual.objects.filter(slug=slug).first()
        if m:
            return m.slug
        latest = (Manual.objects.filter(slug__startswith=prefix)
                  .order_by('-updated_at').first())
        return latest.slug if latest else None

    return [s for s in (
        _pick(f'sky-digest-{iso_year}-w{iso_week:02d}', 'sky-digest-'),
        _pick(f'sky-almanac-{local.year}',              'sky-almanac-'),
        _pick(f'sky-retrospective-{local.year}',        'sky-retrospective-'),
    ) if s]


def publish_one(slug, *, force=False):
    """Render a single sky manual to its cached path. Returns one of
    'wrote', 'fresh', 'missing', 'rejected' for the caller to log."""
    from codex.models import Manual
    from codex.rendering.tufte import render_manual_to_pdf

    path = sky_pdf_path(slug)
    if path is None:
        return 'rejected'

    manual = Manual.objects.filter(slug=slug).first()
    if not manual:
        return 'missing'

    if not force and path.exists():
        # Stale only if the manual was updated after the PDF was written.
        pdf_mtime = dt.datetime.fromtimestamp(
            path.stat().st_mtime, tz=dt.timezone.utc,
        )
        if pdf_mtime >= manual.updated_at:
            return 'fresh'

    pdf_bytes = render_manual_to_pdf(manual)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(pdf_bytes)
    tmp.replace(path)  # atomic on the same filesystem
    manual.last_built_at = djtz.now()
    manual.save(update_fields=['last_built_at'])
    return 'wrote'


class Command(BaseCommand):
    help = 'Render the active sky Codex Manuals to cached PDFs on disk.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Re-render even when the on-disk PDF is '
                                 'newer than manual.updated_at.')
        parser.add_argument('--slug', default=None,
                            help='Render one specific manual by slug. Must '
                                 'be a sky-* slug.')

    def handle(self, *args, **opts):
        slugs = [opts['slug']] if opts['slug'] else _current_sky_slugs()
        if not slugs:
            self.stdout.write(self.style.WARNING(
                'No sky manuals composed yet — nothing to publish. '
                'Run compose_pass_digest / compose_sky_almanac / '
                'compose_sky_retrospective first.'
            ))
            return

        wrote = fresh = missing = rejected = 0
        for slug in slugs:
            result = publish_one(slug, force=opts['force'])
            if result == 'wrote':
                wrote += 1
                self.stdout.write(f'  wrote  {slug}')
            elif result == 'fresh':
                fresh += 1
                self.stdout.write(f'  fresh  {slug} (no change)')
            elif result == 'missing':
                missing += 1
                self.stdout.write(self.style.WARNING(
                    f'  missing {slug} (manual does not exist)'
                ))
            elif result == 'rejected':
                rejected += 1
                self.stdout.write(self.style.ERROR(
                    f'  rejected {slug} (not a sky-* slug)'
                ))

        self.stdout.write(self.style.SUCCESS(
            f'Done. {wrote} written · {fresh} fresh · '
            f'{missing} missing · {rejected} rejected.'
        ))

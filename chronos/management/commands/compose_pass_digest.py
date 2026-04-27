"""Compose a weekly Codex Manual ranking the top viewable satellite
passes for the next 7 days.

Idempotent per ISO week: a manual with slug `sky-digest-<YYYY>-W<NN>`
is created once and re-rendered (sections wiped + rewritten) on
subsequent runs the same week.

Same `top_viewable_passes` ranker that drives /chronos/sky/digest/.
The Codex Manual is the persistent published artifact; the page
is the live reading.

Usage:

    python manage.py compose_pass_digest
        Compose the digest for the current ISO week.

    python manage.py compose_pass_digest --quiet
        Suppress per-section output (useful from cron).
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz
from django.utils.text import slugify
from zoneinfo import ZoneInfo


def _local_tz():
    from chronos.models import ClockPrefs
    return ZoneInfo(ClockPrefs.load().home_tz)


def _compose_body(now, tz):
    """Build the Markdown body of the digest's lead section."""
    from chronos.views import top_viewable_passes
    rows = top_viewable_passes(now, days=7, limit=20)

    lines = []
    if not rows:
        lines.append(
            'No clear-sky satellite passes are forecast over the observer '
            'location in the next 7 days. Either every visible pass falls '
            'under heavy cloud cover, or the watched satellites\' ground '
            'tracks miss this latitude this week.'
        )
        return '\n'.join(lines), 0

    lines.append(
        f'**{len(rows)} viewable passes** ranked by viewing quality '
        f'(max altitude × duration × clear-sky fraction).'
    )
    lines.append('')
    lines.append('| # | When (local) | Object | Max alt | Duration | Cloud | Score |')
    lines.append('|--:|:--|:--|--:|--:|--:|--:|')
    for i, r in enumerate(rows, start=1):
        local = r['event'].start.astimezone(tz)
        when = local.strftime('%a %d %b · %H:%M')
        obj = r['event'].title.split(' · ')[0]
        lines.append(
            f'| {i} | {when} | {obj} | {r["max_alt"]}° | '
            f'{r["duration_s"]} s | {r["weather"]["cloud_pct"]:.0f}% | '
            f'{r["score"]:.0f} |'
        )

    lines.append('')
    lines.append('## Top of the week')
    lines.append('')
    top = rows[0]
    local = top['event'].start.astimezone(tz)
    lines.append(
        f'**{top["event"].title}** · {local:%A %d %B %H:%M} local. '
        f'Maximum altitude **{top["max_alt"]}°**, duration **{top["duration_s"]}s**, '
        f'forecast **{top["weather"]["label"]}** '
        f'({top["weather"]["cloud_pct"]:.0f}% cloud).'
    )

    return '\n'.join(lines), len(rows)


def _per_night_body(now, tz):
    """Build a "by night" markdown body — list each night's passes
    in chronological order."""
    from collections import defaultdict
    from chronos.views import top_viewable_passes
    rows = top_viewable_passes(now, days=7, limit=20)

    by_night = defaultdict(list)
    for r in rows:
        local = r['event'].start.astimezone(tz)
        # Pre-dawn (before noon local) belongs to the previous evening's plan
        night_key = local.date() if local.hour >= 12 else (local - dt.timedelta(days=1)).date()
        by_night[night_key].append((local, r))

    lines = []
    if not by_night:
        return 'No clear-sky passes in the window.'

    for date_key in sorted(by_night.keys()):
        lines.append(f'## {date_key:%A %d %B} → into the night')
        lines.append('')
        for local, r in sorted(by_night[date_key], key=lambda p: p[0]):
            obj = r['event'].title.split(' · ')[0]
            lines.append(
                f'- **{local:%H:%M}** · {obj} · max **{r["max_alt"]}°** '
                f'· {r["duration_s"]} s · {r["weather"]["label"]}'
            )
        lines.append('')

    return '\n'.join(lines)


class Command(BaseCommand):
    help = 'Compose a weekly Codex Manual of top viewable sat passes.'

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        from codex.models import Manual, Section
        from chronos.models import ClockPrefs

        prefs = ClockPrefs.load()
        tz = _local_tz()
        now = djtz.now()
        local = now.astimezone(tz)
        iso_year, iso_week, _ = local.isocalendar()
        slug = f'sky-digest-{iso_year}-w{iso_week:02d}'
        title = f'Sky Digest · Week {iso_week} of {iso_year}'

        manual, created = Manual.objects.update_or_create(
            slug=slug,
            defaults={
                'title':    title,
                'subtitle': (
                    f'Top satellite passes from '
                    f'{prefs.home_lat:.2f}°N {prefs.home_lon:.2f}°E '
                    f'· generated {local:%a %d %b %Y %H:%M %Z}'
                ),
                'format':   'short',
                'author':   'Velour · Chronos',
                'abstract': (
                    'A ranked guide to the next seven days of viewable '
                    'satellite passes from the configured observer location. '
                    'Each pass is scored on maximum altitude, duration, and '
                    'forecast cloud cover — higher is better. Cloud cover '
                    'comes from the Open-Meteo /v1/forecast endpoint, '
                    'satellites from CelesTrak TLE.'
                ),
            },
        )

        # Wipe and re-write the sections so the digest always reflects
        # the latest forecast + TLE state.
        manual.sections.all().delete()

        body, count = _compose_body(now, tz)
        Section.objects.create(
            manual=manual, title='Top viewable passes',
            body=body, sort_order=10,
        )
        Section.objects.create(
            manual=manual, title='By night',
            body=_per_night_body(now, tz), sort_order=20,
        )
        Section.objects.create(
            manual=manual, title='Notes',
            body=(
                f'Score formula: max altitude (°) × duration (s) × '
                f'(100 − cloud %) ÷ 100. A pass at zenith for 7 minutes '
                f'under clear skies scores ~38 000.\n\n'
                f'Viewable threshold: cloud cover < 60 % AND no rain '
                f'forecast over the pass window (±30 min).\n\n'
                f'Forecast horizon: ~5 days (Open-Meteo). Passes beyond '
                f'that fall back to the historical climatology baseline.'
            ),
            sort_order=30,
        )

        manual.save(update_fields=['updated_at'])
        action = 'created' if created else 're-rendered'
        if not opts['quiet']:
            self.stdout.write(self.style.SUCCESS(
                f'{action} {manual.title} · {count} passes ranked '
                f'(slug {manual.slug})'
            ))

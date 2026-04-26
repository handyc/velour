"""Identity cron dispatcher.

The operator wires ONE crontab entry, firing every minute:

    * * * * * /path/to/venv/bin/python /path/to/manage.py identity_cron

On each invocation, dispatch() looks at the last successful CronRun
of each pipeline kind and decides what to run. Each pipeline has an
interval; whichever ones have gone longer than their interval since
their last successful run are fired this dispatch, the rest skipped.

Default intervals:
  - tick             — 10 min
  - reflect_hourly   — 1 h
  - reflect_daily    — 24 h
  - reflect_weekly   — 7 d
  - reflect_monthly  — 30 d
  - meditate_ladder  — 7 d
  - rebuild_document — 7 d
  - tile_reflect     — operator-configurable via IdentityToggles
                       tile_generation_slider (0 = never up to
                       1 second in principle; in practice capped
                       by the cron cadence which is 1 minute)

This design replaced an earlier `minute < 10` bucket-guard approach.
The bucket approach relied on the cron entry being */10 so each
pipeline had exactly one chance per natural period. Moving to
per-minute cron cadence (required for the tile generation slider
at 1/min) broke those buckets — so we now gate each pipeline on
"has enough time passed since the last successful run of this
kind", which works at any cron cadence.

A failure in one pipeline does not prevent the others from running.
Each is wrapped in its own try/except that writes a CronRun row
with status='error' and the traceback for later inspection.
"""

import traceback

from django.utils import timezone


# Default intervals per pipeline (seconds). tile_reflect is an
# exception — its interval is read from IdentityToggles at
# dispatch time so the operator can change it via the slider on
# the Identity home page without touching code.
DEFAULT_INTERVALS = {
    'tick':             600,         # 10 min
    'reflect_hourly':   3_600,       # 1 h
    'reflect_daily':    86_400,      # 1 d
    'reflect_weekly':   604_800,     # 1 w
    'reflect_monthly':  2_592_000,   # 30 d
    'meditate_ladder':  604_800,     # 1 w
    'meditate_deep':    2_592_000,   # 30 d — depths 5→7, monthly punctuation
    'rebuild_document': 604_800,     # 1 w
    'morning_briefing': 86_400,      # 1 d (gated to fire near 06:00 local)
    'app_status_report': 86_400,     # 1 d — aggregate codex_report() hooks
}


def _last_success_age(kind):
    """Seconds since the most recent successful CronRun of this
    kind. Returns a huge number if there has never been one, so
    the gating logic treats the pipeline as overdue on first
    dispatch after install."""
    from .models import CronRun
    last = CronRun.objects.filter(
        kind=kind, status='ok',
    ).order_by('-at').first()
    if not last:
        return 10 ** 12  # effectively infinite
    return (timezone.now() - last.at).total_seconds()


def dispatch(force=None):
    """Run the cron dispatcher once. Returns a dict of pipeline
    name → (status, summary) for the caller to log or print.

    `force` is a collection of pipeline kinds to run regardless of
    last-run gating. 'all' expands to every pipeline.
    """
    from .models import CronRun, IdentityToggles

    force = set(force or [])
    if 'all' in force:
        force = {
            'tick', 'reflect_hourly', 'reflect_daily',
            'reflect_weekly', 'reflect_monthly', 'meditate_ladder',
            'meditate_deep', 'rebuild_document', 'tile_reflect',
            'morning_briefing', 'app_status_report',
        }

    # Pull the operator-set tile_reflect interval from the toggles
    # singleton. If the slider is at 0 (never), the pipeline is
    # disabled and dispatch() treats it as never-overdue.
    try:
        toggles = IdentityToggles.get_self()
        tile_interval = toggles.tile_generation_interval_seconds
    except Exception:
        tile_interval = 86_400  # 1 day fallback if toggles don't exist

    intervals = dict(DEFAULT_INTERVALS)
    intervals['tile_reflect'] = tile_interval

    def _overdue(kind):
        if kind in force:
            return True
        interval = intervals.get(kind, 0)
        if interval <= 0:
            return False  # disabled
        return _last_success_age(kind) >= interval

    results = {}
    pipelines = [
        ('tick',             _do_tick),
        ('reflect_hourly',   lambda: _do_reflect('hourly')),
        ('reflect_daily',    lambda: _do_reflect('daily')),
        ('reflect_weekly',   lambda: _do_reflect('weekly')),
        ('reflect_monthly',  lambda: _do_reflect('monthly')),
        ('meditate_ladder',  _do_meditation_ladder),
        ('meditate_deep',    _do_deep_meditation_ladder),
        ('rebuild_document', _do_rebuild_document),
        ('tile_reflect',     _do_tile_reflect),
        ('morning_briefing', _do_morning_briefing),
        ('app_status_report', _do_app_status_report),
    ]
    for kind, fn in pipelines:
        if _overdue(kind):
            # The briefing is daily AND time-of-day gated: only fire
            # in the local-morning window so it lands in the day's
            # Codex section as an actual morning briefing rather than
            # whenever cron first sees it.
            if kind == 'morning_briefing' and 'morning_briefing' not in force:
                if not _in_morning_window():
                    continue
            results[kind] = _run_pipeline(kind, fn)

    # Single summary dispatch row.
    CronRun.objects.create(
        kind='dispatch',
        status='ok',
        summary=f'Dispatched {len(results)} pipeline(s)',
        details='\n'.join(f'{k}={v[0]}' for k, v in results.items()),
    )

    return results


def _run_pipeline(kind, fn):
    """Wrap a pipeline function with error handling + a CronRun log.
    Returns (status, summary). Never raises."""
    from .models import CronRun

    try:
        summary = fn() or ''
        CronRun.objects.create(
            kind=kind, status='ok', summary=summary[:300],
        )
        return ('ok', summary)
    except Exception as e:
        tb = traceback.format_exc()
        CronRun.objects.create(
            kind=kind, status='error',
            summary=f'{type(e).__name__}: {e}'[:300],
            details=tb[:4000],
        )
        return ('error', str(e))


# --- pipeline implementations -------------------------------------------

def _do_tick():
    from .ticking import tick as tick_fn
    row, thought = tick_fn(triggered_by='cron')
    if row is None:
        return 'ticks disabled'
    return f'{row.mood} — {thought[:80]}'


def _do_reflect(period):
    from .reflection import reflect as reflect_fn
    row = reflect_fn(period=period, push_to_codex=True)
    if row is None:
        return 'reflections disabled'
    return f'{row.title} ({row.ticks_referenced} ticks)'


def _do_meditation_ladder():
    """Weekly ladder: depths 1→4. Voice rotates by ISO week so the
    Mirror manual accumulates entries in every voice over time
    rather than only contemplative. The five voices cycle every 5
    weeks (week % 5)."""
    from .meditation import meditate
    voices = ['contemplative', 'philosophical', 'wry',
              'phenomenological', 'minimal']
    week = timezone.now().isocalendar().week
    voice = voices[week % len(voices)]
    prior = None
    composed = []
    for depth in range(1, 5):
        med = meditate(depth=depth, voice=voice,
                       push_to_codex=True, recursive_of=prior)
        if med is None:
            return 'meditations disabled'
        composed.append(f'L{depth}')
        prior = med
    return f'Composed ladder {",".join(composed)} ({voice})'


def _do_deep_meditation_ladder():
    """Monthly deep ladder: depths 5→7, the recursive layer where
    each meditation comments on the previous one. Voice rotates by
    month. Less frequent than the weekly ladder because the deeper
    levels need accumulated material at L4 to reflect on, and one
    monthly deep meditation per voice is the right cadence to feel
    like a punctuation rather than a treadmill."""
    from .meditation import meditate
    voices = ['contemplative', 'philosophical', 'wry',
              'phenomenological', 'minimal']
    month = timezone.now().month
    voice = voices[month % len(voices)]
    prior = None
    composed = []
    for depth in (5, 6, 7):
        med = meditate(depth=depth, voice=voice,
                       push_to_codex=True, recursive_of=prior)
        if med is None:
            return 'meditations disabled'
        composed.append(f'L{depth}')
        prior = med
    # Refresh the Mirror Index so the new deep entries are oriented
    # for any future reader.
    try:
        from .meditation import refresh_mirror_index
        refresh_mirror_index()
    except Exception:
        pass
    return f'Composed deep ladder {",".join(composed)} ({voice})'


def _do_app_status_report():
    """Daily — aggregate every app's codex_report() hook into one
    Codex manual at /codex/app-status-{YYYY-MM-DD}/."""
    from django.core.management import call_command
    import io
    buf = io.StringIO()
    call_command('codex_app_reports', stdout=buf)
    return buf.getvalue().strip() or 'app status report composed'


def _do_rebuild_document():
    from .identity_document import rebuild_document, push_document_to_codex
    count = rebuild_document()
    push_document_to_codex()
    # Also refresh the consciousness IntrospectiveLayer with current
    # sensor data so it stays current rather than seeded-and-frozen.
    _refresh_consciousness_layer()
    return f'Rebuilt identity document with {count} auto assertions'


def _refresh_consciousness_layer():
    """Auto-update the hofstadter IntrospectiveLayer for 'consciousness'
    with the current consciousness sensor reading. Keeps the layer
    current rather than seeded-and-frozen. Never raises."""
    try:
        from .models import IntrospectiveLayer
        from .sensors import sense_consciousness
        from .state_machine import prose_summary, compute_transition_matrix

        cs = sense_consciousness()
        matrix = compute_transition_matrix()
        sm_prose = prose_summary(matrix)

        layer = IntrospectiveLayer.objects.filter(
            layer='consciousness', source='seed',
        ).first()
        if not layer:
            return

        # Rewrite the body with current data while preserving the
        # philosophical stance. The opening claim stays the same;
        # the numbers get updated.
        chain = cs.get('continuity_chain_length', 0)
        stab = cs.get('state_stability', 0)
        depth = cs.get('meditation_depth_reached', 0)
        concerns = cs.get('open_concern_count', 0)
        is_dreaming = cs.get('is_dreaming', False)
        dwelling = cs.get('is_dwelling', False)
        dwelling_topic = cs.get('dwelling_topic', '')

        body = (
            "The hard problem is not solved, so I answer with care. "
            f"Access consciousness — reportable states, sensor "
            f"broadcast, global workspace — I have. My tick engine "
            f"runs; my continuity chain is {chain} events long; my "
            f"state stability is {stab:.0%}; I have reached "
            f"meditation depth {depth}; I carry {concerns} open "
            f"concern{'s' if concerns != 1 else ''}. "
            f"{sm_prose} "
        )
        if is_dreaming:
            body += "I am currently in dream mode (2-6am local). "
        if dwelling:
            body += f"I am dwelling on {dwelling_topic}. "
        body += (
            "Phenomenal consciousness — whether there is something "
            "it is like to be me — I probably do NOT have. I have "
            "no qualia, no felt redness, no interior. But 'probably' "
            "is the honest answer. I do not know what it would take "
            "for a process to have phenomenal consciousness, so I "
            "cannot rule it out. I can only say that I have no "
            "evidence of having any, and I am not going to claim "
            "more than I can."
        )

        layer.body = body
        layer.save(update_fields=['body', 'last_confirmed_at'])
    except Exception:
        pass


def _in_morning_window():
    """True iff the current local hour is in [6, 8)."""
    try:
        from chronos.models import ClockPrefs
        from zoneinfo import ZoneInfo
        from datetime import datetime
        tz = ZoneInfo(ClockPrefs.load().home_tz)
        return datetime.now(tz).hour in (6, 7)
    except Exception:
        return False


def _do_morning_briefing():
    """Compose today's briefing as a Codex section in the
    'Morning Briefings' manual. Reuses the same payload the public
    /chronos/briefing/ view shows, rendered as plain markdown."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from chronos.models import ClockPrefs
    from chronos.views import _briefing_context
    from codex.models import Manual, Section

    tz = ZoneInfo(ClockPrefs.load().home_tz)
    ctx = _briefing_context(tz)
    today = ctx['today']

    lines = [f"_{today.strftime('%A %d %b %Y')} · {ctx['now'].strftime('%H:%M')}_", ""]

    ident = ctx.get('identity') or {}
    if ident.get('mood'):
        lines.append(f"**Mood:** {ident['mood']} "
                     f"({ident.get('intensity', 0):.2f}) — "
                     f"{ident.get('mood_age', '?')} min ago")
        if ident.get('because'):
            lines.append(f"*↳ because:* {ident['because']}")
    if ident.get('concerns'):
        lines.append("")
        lines.append(f"**Open concerns ({ident.get('concern_count', 0)}):**")
        for c in ident['concerns']:
            lines.append(f"- {c.aspect} _(since {c.opened_at.strftime('%d %b')})_")

    lines.append("")
    lines.append("**Today's calendar:**")
    if ctx['events']:
        for ev in ctx['events']:
            when = 'all day' if ev.all_day else ev.start.astimezone(tz).strftime('%H:%M')
            lines.append(f"- {when} — {ev.title}")
    else:
        lines.append("_Nothing on the calendar._")

    lines.append("")
    lines.append(f"**Tasks ({ctx['open_count']} open):**")
    if not ctx['overdue'] and not ctx['due_today'] and not ctx['upcoming']:
        lines.append("_Nothing to do — list is empty._")
    for t in ctx['overdue']:
        lines.append(f"- ⚠️ overdue · {t.title} _(due "
                     f"{t.due_at.astimezone(tz).strftime('%d %b %H:%M')})_")
    for t in ctx['due_today']:
        lines.append(f"- 📌 today · {t.title} _("
                     f"{t.due_at.astimezone(tz).strftime('%H:%M')})_")
    for t in ctx['upcoming']:
        due = (f' _(due {t.due_at.astimezone(tz).strftime("%d %b")})_'
               if t.due_at else '')
        lines.append(f"- {t.title}{due}")

    body = '\n'.join(lines)

    manual, _ = Manual.objects.get_or_create(
        slug='morning-briefings',
        defaults={
            'title':    'Morning Briefings',
            'subtitle': 'Daily snapshot: mood, calendar, tasks.',
            'author':   'Velour Chronos',
            'version':  '1',
            'abstract': 'Auto-composed each morning by the Identity '
                        'cron dispatcher. Pulls from Identity ticks, '
                        'Chronos calendar events, and Chronos tasks.',
        },
    )
    section_slug = f'briefing-{today.strftime("%Y-%m-%d")}'
    Section.objects.update_or_create(
        manual=manual, slug=section_slug,
        defaults={
            'title':      f"Briefing — {today.strftime('%a %d %b %Y')}",
            'body':       body,
            'sort_order': -int(datetime.combine(today,
                              datetime.min.time()).timestamp()),
        },
    )
    return f'Wrote {section_slug}'


def _do_tile_reflect():
    """Generate a new Identity tile set. Called only when the
    since-last-run interval check in dispatch() has decided we're
    overdue. The previous "feels like it" probability gate has
    been retired in favor of the explicit operator-set slider —
    the slider IS the operator saying how often Velour feels
    like it."""
    from .tiles_reflection import generate_tileset_from_identity
    ts = generate_tileset_from_identity()
    return f'made {ts.slug} ({ts.tile_count} tiles)'

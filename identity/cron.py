"""Identity cron dispatcher.

The operator wires ONE crontab entry:

    */10 * * * * /path/to/venv/bin/python /path/to/manage.py identity_cron

Everything else is this module's job. On each invocation, dispatch()
looks at the current wall clock and decides which Identity pipelines
to fire:

  - Tick: always (on the 10-minute cadence)
  - Hourly reflection: top of the hour (minute < 10, i.e. first
    dispatch after the hour rolled over)
  - Daily reflection: minute < 10 AND hour == 0 (midnight)
  - Weekly reflection: minute < 10 AND hour == 0 AND weekday == Monday
  - Monthly reflection: minute < 10 AND hour == 0 AND day == 1
  - Meditation ladder (L1-L4): minute < 10 AND hour == 0 AND
    weekday == Sunday

The "minute < 10" guard is how we turn a */10 crontab entry into a
single-dispatch-per-period fire. Because cron only fires every 10
minutes, the first dispatch after the period boundary gets the
reflection; subsequent dispatches that same hour just do ticks.

A stronger version of this would track the last-run timestamp per
pipeline in the database and refuse to double-fire even if the cron
schedule drifted — but the minute<10 guard is good enough for the
single-operator single-host case and doesn't require extra state.

Each decision is logged to a CronRun row so the operator can see
what fired and what was skipped. A failure in one pipeline does not
prevent the others from running — each pipeline is wrapped in its
own try/except that writes a CronRun row with status='error'.
"""

import traceback

from django.utils import timezone


def dispatch(force=None):
    """Run the cron dispatcher once. Returns a dict of pipeline
    name → (status, summary) for the caller to log or print.

    `force` is an optional set of pipeline kinds to run regardless of
    the clock — useful for the 'run cron now' button in the UI and
    for testing. Accepted values: 'tick', 'reflect_hourly',
    'reflect_daily', 'reflect_weekly', 'reflect_monthly',
    'meditate_ladder', or 'all' to run everything.
    """
    from .models import CronRun

    now = timezone.now()
    force = set(force or [])
    if 'all' in force:
        force = {
            'tick', 'reflect_hourly', 'reflect_daily',
            'reflect_weekly', 'reflect_monthly', 'meditate_ladder',
            'rebuild_document', 'tile_reflect',
        }

    results = {}

    # --- Tick: always (every 10 minutes under */10 cron) -------------
    if 'tick' in force or True:  # ticks always run
        results['tick'] = _run_pipeline('tick', _do_tick)

    # --- Hourly reflection: first dispatch after hour boundary -------
    if 'reflect_hourly' in force or (now.minute < 10):
        results['reflect_hourly'] = _run_pipeline(
            'reflect_hourly', lambda: _do_reflect('hourly'))

    # --- Daily reflection: midnight ---------------------------------
    if 'reflect_daily' in force or (now.minute < 10 and now.hour == 0):
        results['reflect_daily'] = _run_pipeline(
            'reflect_daily', lambda: _do_reflect('daily'))

    # --- Weekly reflection: Monday midnight -------------------------
    if 'reflect_weekly' in force or (
            now.minute < 10 and now.hour == 0 and now.weekday() == 0):
        results['reflect_weekly'] = _run_pipeline(
            'reflect_weekly', lambda: _do_reflect('weekly'))

    # --- Monthly reflection: first of the month midnight ------------
    if 'reflect_monthly' in force or (
            now.minute < 10 and now.hour == 0 and now.day == 1):
        results['reflect_monthly'] = _run_pipeline(
            'reflect_monthly', lambda: _do_reflect('monthly'))

    # --- Meditation ladder: Sunday midnight -------------------------
    if 'meditate_ladder' in force or (
            now.minute < 10 and now.hour == 0 and now.weekday() == 6):
        results['meditate_ladder'] = _run_pipeline(
            'meditate_ladder', _do_meditation_ladder)

    # --- Identity document rebuild: Sunday midnight -----------------
    if 'rebuild_document' in force or (
            now.minute < 10 and now.hour == 0 and now.weekday() == 6):
        results['rebuild_document'] = _run_pipeline(
            'rebuild_document', _do_rebuild_document)

    # --- Tile reflection: hourly check, probabilistic fire ----------
    # This one is checked on every hourly cadence (minute < 10), but
    # the actual generation is gated by identity_feels_like_making_tiles
    # which rolls a state-driven probability. Most checks do nothing.
    if 'tile_reflect' in force or (now.minute < 10):
        results['tile_reflect'] = _run_pipeline(
            'tile_reflect', _do_tile_reflect)

    # Single dispatch row summarizing the whole run
    parts = [f'{k}={v[0]}' for k, v in results.items()]
    CronRun.objects.create(
        kind='dispatch',
        status='ok',
        summary=f'Dispatched {len(results)} pipelines',
        details='\n'.join(parts),
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
    return f'{row.mood} — {thought[:80]}'


def _do_reflect(period):
    from .reflection import reflect as reflect_fn
    row = reflect_fn(period=period, push_to_codex=True)
    return f'{row.title} ({row.ticks_referenced} ticks)'


def _do_meditation_ladder():
    from .meditation import meditate
    prior = None
    composed = []
    for depth in range(1, 5):
        med = meditate(depth=depth, voice='contemplative',
                        push_to_codex=True, recursive_of=prior)
        composed.append(f'L{depth}')
        prior = med
    return f'Composed ladder {",".join(composed)}'


def _do_rebuild_document():
    from .identity_document import rebuild_document, push_document_to_codex
    count = rebuild_document()
    push_document_to_codex()
    return f'Rebuilt identity document with {count} auto assertions'


def _do_tile_reflect():
    """Check if Identity feels like making a tile set. If so, make
    one. If not, return the reason — cron logs the no-op so the
    operator can see the decision."""
    from .tiles_reflection import (
        identity_feels_like_making_tiles,
        generate_tileset_from_identity,
    )
    should, reason = identity_feels_like_making_tiles()
    if not should:
        return f'did not feel like it — {reason}'
    ts = generate_tileset_from_identity()
    return f'made {ts.slug} (tiles={ts.tile_count}) — {reason}'

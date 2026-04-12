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
    'rebuild_document': 604_800,     # 1 w
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
            'rebuild_document', 'tile_reflect',
        }

    # Pull the operator-set tile_reflect interval from the toggles
    # singleton. If the slider is at 0 (never), the pipeline is
    # disabled and dispatch() treats it as never-overdue.
    try:
        toggles = IdentityToggles.get_self()
        tile_interval = toggles.tile_generation_interval_seconds
    except Exception:
        tile_interval = 60

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
        ('rebuild_document', _do_rebuild_document),
        ('tile_reflect',     _do_tile_reflect),
    ]
    for kind, fn in pipelines:
        if _overdue(kind):
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
    from .meditation import meditate
    prior = None
    composed = []
    for depth in range(1, 5):
        med = meditate(depth=depth, voice='contemplative',
                       push_to_codex=True, recursive_of=prior)
        if med is None:
            return 'meditations disabled'
        composed.append(f'L{depth}')
        prior = med
    return f'Composed ladder {",".join(composed)}'


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

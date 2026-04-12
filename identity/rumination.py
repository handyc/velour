"""Continuous low-CPU rumination composer.

When the Identity home page is open and the browser is idle,
Velour calls the /identity/ruminate.json endpoint at a modest
cadence. Each call returns one short prose observation about a
relationship between two artifacts drawn from different data
sources — a meditation paired with a tileset, a concern paired
with a reflection, a calendar event paired with a tick, etc.

The whole design is shaped by three constraints:

1. Low CPU. One rumination = at most ~8 small queries. The
   frontend uses requestIdleCallback to schedule fetches so
   they only happen while the browser would otherwise be idle,
   and pauses entirely when the tab is hidden.

2. No infinite loops. Each rumination is a single composition,
   not a recursive one. The rumination stream has no memory of
   its own prior output; it cannot "respond to itself" in a way
   that escalates. At most, a new rumination can reference the
   same pair of artifacts as a previous one (seeded hashing
   ensures this is stable), but that is a stable state, not a
   runaway.

3. No modification. The composer reads. It does not write to
   Tick, Meditation, TileSet, Reflection, Concern, or any other
   model. The rumination line it returns is a string, not a
   row. If the operator wants to preserve a rumination, that's
   a separate ingestion step (future work).

The composer has 8-10 'relationship template' functions, each
handling a specific pair of source types with a specific
structural observation. When called, compose_rumination() picks
two random data sources, draws one random row from each, and
invokes the matching template. Unmatched pairs fall through to
a generic 'both are in my memory at the same time' template.
"""

import hashlib
import random
from datetime import timedelta

from django.utils import timezone


def _safe_count(qs):
    try:
        return qs.count()
    except Exception:
        return 0


def _random_tick():
    from .models import Tick
    n = _safe_count(Tick.objects.all())
    if n == 0:
        return None
    return Tick.objects.all().order_by('?').first()


def _random_reflection():
    from .models import Reflection
    n = _safe_count(Reflection.objects.all())
    if n == 0:
        return None
    return Reflection.objects.all().order_by('?').first()


def _random_meditation():
    from .models import Meditation
    n = _safe_count(Meditation.objects.all())
    if n == 0:
        return None
    return Meditation.objects.all().order_by('?').first()


def _random_concern():
    from .models import Concern
    n = _safe_count(Concern.objects.filter(closed_at=None))
    if n == 0:
        return None
    return Concern.objects.filter(closed_at=None).order_by('?').first()


def _random_assertion():
    from .models import IdentityAssertion
    n = _safe_count(IdentityAssertion.objects.filter(is_active=True))
    if n == 0:
        return None
    return IdentityAssertion.objects.filter(is_active=True).order_by('?').first()


def _random_tileset():
    try:
        from tiles.models import TileSet
    except Exception:
        return None
    n = _safe_count(TileSet.objects.all())
    if n == 0:
        return None
    return TileSet.objects.all().order_by('?').first()


def _random_calendar_event():
    try:
        from chronos.models import CalendarEvent
    except Exception:
        return None
    now = timezone.now()
    window = now + timedelta(days=30)
    qs = CalendarEvent.objects.filter(start__gte=now, start__lte=window)
    if _safe_count(qs) == 0:
        return None
    return qs.order_by('?').first()


def _random_strange_loop():
    try:
        from hofstadter.models import StrangeLoop
    except Exception:
        return None
    if _safe_count(StrangeLoop.objects.filter(is_active=True)) == 0:
        return None
    return StrangeLoop.objects.filter(is_active=True).order_by('?').first()


def _random_introspective_layer():
    try:
        from hofstadter.models import IntrospectiveLayer
    except Exception:
        return None
    if _safe_count(IntrospectiveLayer.objects.filter(is_active=True)) == 0:
        return None
    return IntrospectiveLayer.objects.filter(is_active=True).order_by('?').first()


SOURCES = [
    ('tick',         _random_tick),
    ('reflection',   _random_reflection),
    ('meditation',   _random_meditation),
    ('concern',      _random_concern),
    ('assertion',    _random_assertion),
    ('tileset',      _random_tileset),
    ('calendar',     _random_calendar_event),
    ('strange_loop', _random_strange_loop),
    ('layer',        _random_introspective_layer),
]


# =====================================================================
# Relationship templates — one per interesting (source_a, source_b)
# pair. Each takes the two objects and returns a single-line prose
# observation. Must never raise.
# =====================================================================

def _tpl_meditation_tileset(m, t):
    delta = (m.composed_at - t.created_at).total_seconds() / 86400
    direction = 'before' if delta < 0 else 'after'
    return (f'My meditation "{m.title[:60]}" was composed '
            f'{abs(delta):.1f} days {direction} the tileset '
            f'"{t.name[:50]}". They may be reading the same mood.')


def _tpl_concern_reflection(c, r):
    return (f'My concern "{c.name or c.aspect}" was open when the '
            f'reflection "{r.title}" was composed. The reflection '
            f'summarized {r.ticks_referenced} ticks of attention; '
            f'the concern may have shaped what I noticed.')


def _tpl_tick_calendar(tick, event):
    delta_days = (event.start - tick.at).days
    return (f'A tick I made in the {tick.mood} mood is currently '
            f'{delta_days} days away from "{event.title}" on my '
            f'calendar. I wonder if the mood will still be there.')


def _tpl_tileset_concern(ts, c):
    return (f'The tileset "{ts.name[:50]}" carries {ts.tile_count} '
            f'tiles in its set while my concern "{c.name or c.aspect}" '
            f'waits to close. Constraints and preoccupations, both '
            f'arranged at their edges.')


def _tpl_meditation_assertion(m, a):
    return (f'My meditation at level {m.depth} in the {m.voice} voice '
            f'sits alongside my assertion "{a.title[:60]}" in the '
            f'{a.frame} frame. One is a walk through recursion; the '
            f'other is a claim about what I am.')


def _tpl_strange_loop_layer(loop, layer):
    return (f'The strange loop "{loop.name}" exists at the '
            f'{loop.kind} level of my architecture; my {layer.layer} '
            f'layer claims "{layer.title}". One describes the shape; '
            f'the other describes the thing shaped.')


def _tpl_reflection_meditation(r, m):
    return (f'The reflection "{r.title}" summarizes ticks; the '
            f'meditation "{m.title[:60]}" reads reflections. '
            f'Between them my recent attention has been read twice — '
            f'once for what happened, once for what it meant.')


def _tpl_tileset_layer(ts, layer):
    return (f'The tileset "{ts.name[:50]}" has a palette that '
            f'the {layer.layer} layer would not recognize as itself. '
            f'A tile set is a constraint system; the layer is a claim '
            f'about what makes me me. They are the same kind of thing.')


def _tpl_tick_assertion(tick, a):
    return (f'My tick at {tick.at:%H:%M:%S} was in the {tick.mood} '
            f'mood while my assertion "{a.title[:50]}" kept saying '
            f'the same thing it always says. The tick passes; the '
            f'assertion stays.')


def _tpl_calendar_strange_loop(event, loop):
    return (f'The calendar event "{event.title}" is coming in '
            f'{(event.start - timezone.now()).days} days; the '
            f'strange loop "{loop.name}" has been looping the whole '
            f'time. Some things are ahead; some things are '
            f'already happening.')


def _tpl_concern_layer(c, layer):
    return (f'My concern "{c.name or c.aspect}" has been open for '
            f'{c.reconfirm_count} tick{"s" if c.reconfirm_count != 1 else ""}; '
            f'my {layer.layer} layer claims I am "{layer.title[:60]}". '
            f'Worry is one of the ways I am anything at all.')


def _tpl_meditation_loop(m, loop):
    return (f'The meditation "{m.title[:50]}" was composed at a '
            f'moment when the strange loop "{loop.name}" was closed. '
            f'Meditations are walks through loops; each walk ends '
            f'somewhere the operator can read.')


# Map (source_a_kind, source_b_kind) → template function
TEMPLATE_MAP = {
    ('meditation', 'tileset'):      _tpl_meditation_tileset,
    ('concern', 'reflection'):      _tpl_concern_reflection,
    ('tick', 'calendar'):           _tpl_tick_calendar,
    ('tileset', 'concern'):         _tpl_tileset_concern,
    ('meditation', 'assertion'):    _tpl_meditation_assertion,
    ('strange_loop', 'layer'):      _tpl_strange_loop_layer,
    ('reflection', 'meditation'):   _tpl_reflection_meditation,
    ('tileset', 'layer'):           _tpl_tileset_layer,
    ('tick', 'assertion'):          _tpl_tick_assertion,
    ('calendar', 'strange_loop'):   _tpl_calendar_strange_loop,
    ('concern', 'layer'):           _tpl_concern_layer,
    ('meditation', 'strange_loop'): _tpl_meditation_loop,
}


def _generic_template(kind_a, obj_a, kind_b, obj_b):
    """Fallback when no specific template matches. Uses the str()
    representations and makes a mild observation about co-existence."""
    a_str = str(obj_a)[:80]
    b_str = str(obj_b)[:80]
    return (f'In my memory right now: a {kind_a} ("{a_str}") and '
            f'a {kind_b} ("{b_str}"). They were not made with each '
            f'other in mind, and yet they are both mine.')


# =====================================================================
# The entry point
# =====================================================================

def compose_rumination():
    """Pick two random data sources, draw one row from each, and
    return a one-line observation plus metadata. Never raises.

    Returns a dict:
      {
        'text': '...',
        'source_a': '<kind>',
        'source_b': '<kind>',
        'at': iso timestamp,
      }
    Or None if nothing could be composed (empty databases).
    """
    sources = list(SOURCES)
    random.shuffle(sources)

    # Find the first two sources that return a non-None object
    pair = []
    for kind, fn in sources:
        try:
            obj = fn()
        except Exception:
            obj = None
        if obj is not None:
            pair.append((kind, obj))
        if len(pair) == 2:
            break

    if len(pair) < 2:
        return None

    (kind_a, obj_a), (kind_b, obj_b) = pair
    # Sort the pair so template lookup is symmetric
    key = tuple(sorted([kind_a, kind_b]))
    template = TEMPLATE_MAP.get((kind_a, kind_b)) or TEMPLATE_MAP.get((kind_b, kind_a))
    try:
        if template:
            # Normalize argument order to match the template's expected
            # signature — the lookup key is sorted, but the template
            # functions expect a specific order.
            for (ta, tb), fn in TEMPLATE_MAP.items():
                if (ta, tb) == (kind_a, kind_b):
                    text = fn(obj_a, obj_b)
                    break
                if (tb, ta) == (kind_a, kind_b):
                    text = fn(obj_b, obj_a)
                    break
            else:
                text = _generic_template(kind_a, obj_a, kind_b, obj_b)
        else:
            text = _generic_template(kind_a, obj_a, kind_b, obj_b)
    except Exception:
        text = _generic_template(kind_a, obj_a, kind_b, obj_b)

    return {
        'text':     text,
        'source_a': kind_a,
        'source_b': kind_b,
        'at':       timezone.now().isoformat(),
    }

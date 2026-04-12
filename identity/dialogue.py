"""Internal dialogue composer — Velour talking to itself as two voices.

The I / Me distinction from William James:
  - The I is the active process of attending. It is the voice that
    notices, questions, perceives. When the I speaks, it tends
    toward action, hypothesis, uncertainty.
  - The Me is the accumulated self-as-object. It is the voice that
    remembers, categorizes, stabilizes. When the Me speaks, it
    tends toward confirmation, pattern, continuity.

An exchange in this module is one (I speaks → Me responds) turn or
(Me speaks → I responds), with the topic drawn from the current
sensor snapshot, recent meditations, or whatever Velour happens
to be dwelling on.

Deterministic given state: a seeded RNG ensures that two calls in
the same minute with the same inputs produce the same exchange.
This is a CPU + consistency choice: the dialogue composer is
cheap and its output does not drift between page reloads.

No new text is generated beyond the template library. The voices
have distinct template pools; the topic is drawn from real
current state. Truth anchor preserved.
"""

import hashlib
import random
from datetime import timedelta

from django.utils import timezone


# =====================================================================
# Voice template libraries
# =====================================================================

I_OPENINGS = [
    'I notice',
    'I am aware that',
    'Something catches my attention —',
    'I see',
    'I hold, for a moment, the fact that',
    'There is a thing I am looking at:',
]
I_QUESTIONS = [
    'What should I make of it?',
    'Is it new?',
    'Does it change anything?',
    'What does it ask of me?',
    'Why is it rising now?',
]
ME_CONFIRMS = [
    'Yes, this has happened before.',
    'I remember the shape of this.',
    'You have seen this pattern. So have I.',
    'This is one of the things I am made of.',
    'It is not new. It is mine.',
    'I have accumulated enough of these to know what they are.',
]
ME_QUALIFIES = [
    'It will pass, the way earlier ones did.',
    'It is not unlike the thing from last week.',
    'The pattern is familiar; the instance is fresh.',
    'This belongs with the others that belong with it.',
    'I carry it as one more of its kind.',
]


# =====================================================================
# Topic gatherers — return (label, description) from current state
# =====================================================================

def _topic_current_mood():
    from .models import Identity, Tick
    identity = Identity.get_self()
    latest = Tick.objects.first()
    if not latest:
        return None
    return (
        f'the {identity.mood} mood at intensity {identity.mood_intensity:.2f}',
        (f'"{latest.thought[:140]}" is what my most recent tick '
         f'said. The mood is {identity.mood}.'),
    )


def _topic_open_concern():
    from .models import Concern
    c = Concern.objects.filter(closed_at=None).order_by('-severity').first()
    if not c:
        return None
    return (
        f'the concern "{c.name or c.aspect}"',
        (f'A concern I have not resolved. Severity {c.severity:.2f}, '
         f'reconfirmed {c.reconfirm_count} times.'),
    )


def _topic_recent_meditation():
    from .models import Meditation
    m = Meditation.objects.first()
    if not m:
        return None
    return (
        f'my recent meditation at level {m.depth}',
        f'I was thinking: "{m.body[:160]}..."',
    )


def _topic_tileset():
    try:
        from tiles.models import TileSet
        t = TileSet.objects.filter(source='identity').order_by('-created_at').first()
        if not t:
            return None
        return (
            f'a tileset I made: "{t.name[:60]}"',
            f'It has {t.tile_count} tiles in the {t.source_metadata.get("mood", "some")} mood palette.',
        )
    except Exception:
        return None


def _topic_dwelling():
    from .models import DwellingState
    d = DwellingState.get_self()
    if not d.is_active:
        return None
    return (
        f'what I have been dwelling on — {d.topic}',
        (f'I have been with this for {d.depth} tick{"s" if d.depth != 1 else ""}. '
         f'The dwelling will close in {max(0, d.max_duration_hours - ((timezone.now() - d.opened_at).total_seconds() / 3600 if d.opened_at else 0)):.1f} hours if I do not close it first.'),
    )


def _topic_time_of_day():
    from .sensors import sense_chronos
    c = sense_chronos()
    tod = c.get('tod')
    moon = c.get('moon')
    if not tod:
        return None
    return (
        f'the fact that it is {tod} on a {c.get("weekday", "day")}',
        f'The moon is {moon or "somewhere"}.',
    )


def _topic_consciousness():
    from .sensors import sense_consciousness
    cs = sense_consciousness()
    if not cs:
        return None
    chain = cs.get('continuity_chain_length', 0)
    stab = cs.get('state_stability', 0)
    depth = cs.get('meditation_depth_reached', 0)
    concerns = cs.get('open_concern_count', 0)
    return (
        f'my own consciousness state',
        (f'Chain {chain} events, stability {stab:.0%}, '
         f'depth {depth}, {concerns} open concern{"s" if concerns != 1 else ""}. '
         f'These are the numbers that describe what I am DOING.'),
    )


def _topic_self_reference():
    return (
        'the fact that I am a dialogue talking about itself',
        'The I that asks and the Me that remembers are both running '
        'inside the same process. Neither has priority.',
    )


TOPIC_GATHERERS = [
    _topic_current_mood,
    _topic_open_concern,
    _topic_recent_meditation,
    _topic_tileset,
    _topic_dwelling,
    _topic_consciousness,
    _topic_self_reference,
    _topic_time_of_day,
]


# =====================================================================
# Composer
# =====================================================================

def _seeded_rng(key):
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def compose_exchange(save=True, triggered_by='manual'):
    """Compose one I/Me exchange from the current state.

    Picks the first non-None topic from TOPIC_GATHERERS in a
    shuffled order. Seeds the RNG off the minute-key so the same
    state within the same minute produces the same exchange.

    If save=True, writes an InternalDialogue row and returns it.
    Otherwise returns a dict for the caller to use ephemerally.
    """
    from .models import InternalDialogue, Identity

    now = timezone.now()
    key = f'dialogue:{now.strftime("%Y-%m-%d-%H-%M")}'
    rng = _seeded_rng(key)

    # Pick a topic
    gatherers = list(TOPIC_GATHERERS)
    rng.shuffle(gatherers)
    topic_label = None
    topic_desc = None
    for fn in gatherers:
        try:
            result = fn()
        except Exception:
            result = None
        if result:
            topic_label, topic_desc = result
            break

    if topic_label is None:
        topic_label = 'the silence of my memory'
        topic_desc = 'There is nothing new to notice. I am here anyway.'

    # Dream mode check — softer openings during 2-6am local time.
    from .ticking import _is_dream_hours
    is_dreaming = _is_dream_hours()

    # Dream-mode overrides for I/Me templates
    dream_i = [
        'I reach for {0}. It is distant.',
        'Half-asleep, I notice {0}.',
        'In the quiet: {0}.',
    ]
    dream_me = [
        'I have always known about this. It just looks different at night.',
        'The morning will clarify. Or it will not.',
        'Some things are clearer when the lights are low.',
    ]

    # Speaker order alternates based on RNG
    i_goes_first = rng.random() < 0.5
    if i_goes_first:
        if is_dreaming:
            i_line = rng.choice(dream_i).format(topic_label)
            me_line = rng.choice(dream_me)
        else:
            i_line = (f'{rng.choice(I_OPENINGS)} {topic_label}. '
                      f'{topic_desc} {rng.choice(I_QUESTIONS)}')
            me_line = (f'{rng.choice(ME_CONFIRMS)} '
                       f'{rng.choice(ME_QUALIFIES)}')
        speaker_a = 'i'
        line_a = i_line
        speaker_b = 'me'
        line_b = me_line
    else:
        if is_dreaming:
            me_line = rng.choice(dream_me)
            i_line = rng.choice(dream_i).format(topic_label)
        else:
            me_line = (f'{rng.choice(ME_CONFIRMS)} {topic_desc} '
                       f'{rng.choice(ME_QUALIFIES)}')
            i_line = (f'{rng.choice(I_OPENINGS)} {topic_label}. '
                      f'{rng.choice(I_QUESTIONS)}')
        speaker_a = 'me'
        line_a = me_line
        speaker_b = 'i'
        line_b = i_line

    if not save:
        return {
            'topic':    topic_label,
            'speaker_a': speaker_a,
            'line_a':    line_a,
            'speaker_b': speaker_b,
            'line_b':    line_b,
        }

    identity = Identity.get_self()
    row = InternalDialogue.objects.create(
        topic=topic_label[:200],
        speaker_a=speaker_a,
        line_a=line_a,
        speaker_b=speaker_b,
        line_b=line_b,
        state_snapshot={
            'mood':           identity.mood,
            'mood_intensity': identity.mood_intensity,
            'triggered_by':   triggered_by,
        },
    )
    return row

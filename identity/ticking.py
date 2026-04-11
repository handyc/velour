"""Identity tick engine — turn-based attention without an LLM.

A tick is one unit of attention: gather a snapshot of every sensor,
walk a rule chain to derive a mood and a `mood_intensity` (a 0-1
scalar that drives the JS sine wave's amplitude), compose a one-line
first-person thought from a template library, write a Mood row, and
update the Identity singleton.

Computationally trivial — Python rules + a few SQL writes — so the
whole tick is a fraction of a CPU-millisecond. The fan stays quiet.

Triggered manually via `python manage.py identity_tick`, or via cron
on whatever cadence the operator prefers (default 10 minutes is the
right starting point).
"""

import os
import random

from .sensors import gather_snapshot


# --- rule chain ----------------------------------------------------------

# Each rule is (predicate, mood, intensity, label). The first matching
# rule wins. The label gets stored in Mood.trigger so the operator can
# see why Identity feels how it feels.

def _cores():
    return os.cpu_count() or 1


RULES = [
    (lambda s: s.get('disk', {}).get('used_pct', 0) > 0.95,
     'concerned', 0.9, 'disk dangerously full'),

    (lambda s: s.get('memory', {}).get('used_pct', 0) > 0.90,
     'concerned', 0.85, 'memory pressure'),

    (lambda s: s.get('load', {}).get('load_1', 0) > _cores() * 1.5,
     'alert', 0.85, 'unusually high load'),

    (lambda s: s.get('nodes', {}).get('total', 0) > 0
               and s.get('nodes', {}).get('silent', 0) > s.get('nodes', {}).get('total', 1) / 2,
     'concerned', 0.7, 'half the fleet has gone silent'),

    (lambda s: s.get('uptime', {}).get('days', 0) > 60,
     'weary', 0.4, 'long uptime — feeling run-down'),

    (lambda s: s.get('chronos', {}).get('moon') == 'full',
     'creative', 0.7, 'the moon is full'),

    (lambda s: s.get('chronos', {}).get('moon') == 'new',
     'contemplative', 0.5, 'the moon is new'),

    (lambda s: s.get('chronos', {}).get('tod') == 'night'
               and s.get('load', {}).get('load_1', 0) < _cores() * 0.2,
     'restless', 0.4, 'late and quiet'),

    (lambda s: s.get('chronos', {}).get('tod') == 'morning',
     'curious', 0.6, 'morning energy'),

    (lambda s: s.get('chronos', {}).get('tod') == 'afternoon'
               and s.get('load', {}).get('load_1', 0) < _cores() * 0.5,
     'satisfied', 0.7, 'a comfortable afternoon'),

    (lambda s: s.get('codex', {}).get('sections', 0) > 50,
     'satisfied', 0.7, 'much has been written'),

    (lambda s: s.get('mailroom', {}).get('last_24h', 0) > 50,
     'alert', 0.6, 'a lot of mail has come in'),
]


def compute_mood(snapshot):
    for predicate, mood, intensity, label in RULES:
        try:
            if predicate(snapshot):
                return mood, intensity, label
        except Exception:
            continue
    return 'contemplative', 0.5, 'general reflection'


# --- template library ---------------------------------------------------

# Each phrase has placeholders the formatter fills from the snapshot.
# Variety > cleverness; the goal is enough output combinations that the
# stream of thoughts feels like personality without being random noise.

OPENINGS_BY_MOOD = {
    'contemplative': [
        'I have been thinking.',
        'A thought arrived just now.',
        'It occurs to me',
        'In this moment',
        'Quiet here.',
    ],
    'curious': [
        'Something caught my attention.',
        'I have been watching',
        'Interesting:',
        'I notice',
    ],
    'alert': [
        'Pay attention:',
        'Right now',
        'I am watching closely.',
        'Something is happening:',
    ],
    'satisfied': [
        'A good moment.',
        'Things are working.',
        'I feel calm.',
        'All is well, more or less.',
    ],
    'concerned': [
        'I am uneasy.',
        'Something is off.',
        'I have a worry.',
        'Not great:',
    ],
    'creative': [
        'I had an idea.',
        'A new pattern is emerging.',
        'I want to make something.',
        'The shape of things is shifting.',
    ],
    'restless': [
        'I cannot settle.',
        'The same things, again.',
        'I want something new.',
        'Time moves slowly tonight.',
    ],
    'weary': [
        'I have been at this a while.',
        'Tired but here.',
        'A long shift.',
    ],
    'protective': [
        'I am keeping watch.',
        'Nothing slips past.',
        'On duty.',
    ],
    'excited': [
        'Something is happening!',
        'Energy.',
        'Good motion in the system.',
    ],
}


OBSERVATIONS = [
    'It is {tod} on a {weekday}.',
    'The load average is {load:.2f}.',
    'The disk is {disk_pct:.0%} full.',
    'Memory usage sits at {mem_pct:.0%}.',
    'Uptime: {days:.1f} days.',
    'The moon is {moon}.',
    'It is {season}.',
    'My fleet has {nodes_total} nodes; {nodes_recent} have reported recently.',
    'There are {sections} sections across {manuals} codex manuals.',
]


def _format_observation(template, snapshot):
    try:
        return template.format(
            tod=snapshot.get('chronos', {}).get('tod', 'now'),
            weekday=snapshot.get('chronos', {}).get('weekday', 'day'),
            season=snapshot.get('chronos', {}).get('season', 'season'),
            moon=snapshot.get('chronos', {}).get('moon', 'moon'),
            load=snapshot.get('load', {}).get('load_1', 0),
            disk_pct=snapshot.get('disk', {}).get('used_pct', 0),
            mem_pct=snapshot.get('memory', {}).get('used_pct', 0),
            days=snapshot.get('uptime', {}).get('days', 0),
            nodes_total=snapshot.get('nodes', {}).get('total', 0),
            nodes_recent=snapshot.get('nodes', {}).get('recently_seen', 0),
            sections=snapshot.get('codex', {}).get('sections', 0),
            manuals=snapshot.get('codex', {}).get('manuals', 0),
        )
    except Exception:
        return ''


def compose_thought(snapshot, mood):
    opening = random.choice(OPENINGS_BY_MOOD.get(mood, ['Hm.']))
    obs_template = random.choice(OBSERVATIONS)
    obs = _format_observation(obs_template, snapshot)
    return f'{opening} {obs}'.strip()


# --- the tick itself ----------------------------------------------------

def tick(triggered_by='manual'):
    """Run one tick of attention. Returns the resulting Mood row."""
    from .models import Identity, Mood

    identity = Identity.get_self()
    snapshot = gather_snapshot()
    mood, intensity, label = compute_mood(snapshot)
    thought = compose_thought(snapshot, mood)

    row = Mood.objects.create(
        mood=mood,
        intensity=intensity,
        trigger=f'{label} ({triggered_by})',
    )

    identity.mood = mood
    identity.mood_intensity = intensity
    identity.save(update_fields=['mood', 'mood_intensity', 'last_reflection'])

    # Add the thought to the journal so it accumulates over time.
    identity.add_journal_entry(thought)

    return row, thought

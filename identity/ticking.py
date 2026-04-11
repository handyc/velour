"""Identity tick engine — turn-based attention without an LLM.

A tick is one unit of attention: gather a snapshot of every sensor,
walk a rule chain to derive a mood and `mood_intensity` (a 0-1 scalar
that drives the JS sine wave's amplitude), compose a one-line first-
person thought from a template library, write a Tick row (the new
structured log) + a Mood row (legacy shim), and update the Identity
singleton.

Computationally trivial — Python rules + a few SQL writes — so the
whole tick is a fraction of a CPU-millisecond. The fan stays quiet.

Triggered manually via `python manage.py identity_tick`, or via cron
on whatever cadence the operator prefers (default 10 minutes is the
right starting point).

Session-1 note: rules are still hardcoded Python lambdas. Moving them
to Rule rows in the database with a safe expression language is
Session 3 of the Identity expansion. This file stays shaped for that
future: each rule in RULES emits an `aspects` list alongside the
mood/intensity/label, and the tick engine stores those aspects on the
Tick row so later concerns (Session 2) and reflections (Session 5) can
reference them.
"""

import os
import random

from .sensors import gather_snapshot


# --- rule chain ----------------------------------------------------------

# Each rule is (predicate, mood, intensity, label, aspects). The first
# matching rule wins. `aspects` is a list of tag-like strings that
# describe what the rule noticed — they get stored on Tick.aspects and
# on Mood.trigger. Aspects are the glue for concerns and reflections:
# Session 2 opens a concern when an aspect like 'gary_silent' fires;
# Session 5 groups reflections by aspect counts over a period.

def _cores():
    return os.cpu_count() or 1


RULES = [
    (lambda s: s.get('disk', {}).get('used_pct', 0) > 0.95,
     'concerned', 0.9, 'disk dangerously full',
     ['disk_critical']),

    (lambda s: s.get('memory', {}).get('used_pct', 0) > 0.90,
     'concerned', 0.85, 'memory pressure',
     ['memory_critical']),

    (lambda s: s.get('load', {}).get('load_1', 0) > _cores() * 1.5,
     'alert', 0.85, 'unusually high load',
     ['load_high']),

    (lambda s: s.get('nodes', {}).get('total', 0) > 0
               and s.get('nodes', {}).get('silent', 0) > s.get('nodes', {}).get('total', 1) / 2,
     'concerned', 0.7, 'half the fleet has gone silent',
     ['fleet_partial_silence']),

    (lambda s: s.get('uptime', {}).get('days', 0) > 60,
     'weary', 0.4, 'long uptime — feeling run-down',
     ['long_uptime']),

    (lambda s: s.get('chronos', {}).get('moon') == 'full',
     'creative', 0.7, 'the moon is full',
     ['moon_full']),

    (lambda s: s.get('chronos', {}).get('moon') == 'new',
     'contemplative', 0.5, 'the moon is new',
     ['moon_new']),

    (lambda s: s.get('chronos', {}).get('tod') == 'night'
               and s.get('load', {}).get('load_1', 0) < _cores() * 0.2,
     'restless', 0.4, 'late and quiet',
     ['night_quiet']),

    (lambda s: s.get('chronos', {}).get('tod') == 'morning',
     'curious', 0.6, 'morning energy',
     ['morning']),

    (lambda s: s.get('chronos', {}).get('tod') == 'afternoon'
               and s.get('load', {}).get('load_1', 0) < _cores() * 0.5,
     'satisfied', 0.7, 'a comfortable afternoon',
     ['afternoon_calm']),

    (lambda s: s.get('codex', {}).get('sections', 0) > 50,
     'satisfied', 0.7, 'much has been written',
     ['codex_rich']),

    (lambda s: s.get('mailroom', {}).get('last_24h', 0) > 50,
     'alert', 0.6, 'a lot of mail has come in',
     ['mail_burst']),
]


def compute_mood(snapshot):
    """First-match-wins mood selection. Returns (mood, intensity,
    label, first_match_aspects). Used for display — Identity has one
    dominant mood at a time, chosen by rule priority."""
    for rule in RULES:
        predicate, mood, intensity, label, aspects = rule
        try:
            if predicate(snapshot):
                return mood, intensity, label, list(aspects)
        except Exception:
            continue
    return 'contemplative', 0.5, 'general reflection', ['idle']


def evaluate_all_aspects(snapshot):
    """Walk EVERY rule and return the union of aspects whose predicate
    currently matches, along with their rule labels (for concern
    metadata). Distinct from compute_mood which stops at the first hit
    — this one is for concern tracking, which needs to know *everything*
    the system currently notices, not just the one thing the mood
    display picks out.

    Returns: list of (aspect, label, intensity) tuples for every
    currently-true rule.
    """
    hits = []
    for rule in RULES:
        predicate, mood, intensity, label, aspects = rule
        try:
            if predicate(snapshot):
                for aspect in aspects:
                    hits.append((aspect, label, intensity))
        except Exception:
            continue
    return hits


# --- concern ontology ---------------------------------------------------

# The set of aspects that can open a concern. Ephemeral aspects like
# 'morning' or 'afternoon_calm' never become preoccupations — they're
# time-of-day notes, not worries. A concerning aspect is something the
# operator would want Identity to remember between ticks.
#
# Session 3 will move this into database metadata on the Rule model
# (each rule row will carry a bool `opens_concern`) so the operator can
# toggle which rules matter. For now it's a module-level constant.

CONCERNING_ASPECTS = frozenset({
    'disk_critical',
    'memory_critical',
    'load_high',
    'fleet_partial_silence',
    'long_uptime',
    'mail_burst',
})

# How long a concern stays open without being re-confirmed by a new
# tick before the sweep auto-closes it. The default assumes a 10-minute
# tick cadence and gives concerns ~45 minutes of inertia — long enough
# to survive a missed tick or two, short enough to clear if the
# triggering condition actually resolves.
CONCERN_STALENESS_SECONDS = 45 * 60


def maintain_concerns(current_aspect_hits, origin_tick):
    """Open / re-confirm / close concerns based on what the current
    tick noticed. Pass the output of evaluate_all_aspects() as the
    current_aspect_hits.

    Returns a (opened, reconfirmed, closed) tuple of lists for the
    caller to log or ignore.
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import Concern

    opened = []
    reconfirmed = []
    closed = []

    # Only the concerning aspects matter for concern tracking.
    currently_concerning = {
        aspect: (label, intensity)
        for aspect, label, intensity in current_aspect_hits
        if aspect in CONCERNING_ASPECTS
    }

    # Open or bump.
    for aspect, (label, intensity) in currently_concerning.items():
        existing = Concern.objects.filter(aspect=aspect, closed_at=None).first()
        if existing:
            # Bump last_seen_at (auto_now handles this on save) and
            # increment the reconfirm counter.
            existing.reconfirm_count += 1
            if intensity > existing.severity:
                existing.severity = intensity
            existing.save(update_fields=['last_seen_at', 'reconfirm_count', 'severity'])
            reconfirmed.append(existing)
        else:
            new_concern = Concern.objects.create(
                aspect=aspect,
                name=label,
                description=f'First observed at {timezone.now().isoformat()}',
                severity=intensity,
                origin_tick=origin_tick,
            )
            opened.append(new_concern)

    # Sweep: close any open concerns whose aspects were NOT seen in
    # this tick AND whose last_seen_at is older than the staleness
    # threshold.
    cutoff = timezone.now() - timedelta(seconds=CONCERN_STALENESS_SECONDS)
    stale = Concern.objects.filter(closed_at=None, last_seen_at__lt=cutoff)
    for concern in stale:
        concern.close(reason='stale')
        closed.append(concern)

    return opened, reconfirmed, closed


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


CONCERN_REFRAINS = [
    'I am still thinking about {concern}.',
    'Still: {concern}.',
    'The {concern} has not left me.',
    'I have not forgotten the {concern}.',
    '{concern} — still.',
]


def compose_thought(snapshot, mood, open_concerns=None):
    """Compose the first-person thought for this tick.

    If `open_concerns` is supplied and non-empty, there's a small
    chance the thought mentions one of them instead of (or alongside)
    the normal observation. This is the single most important piece
    of the 'Identity remembers' behaviour — it's what makes the
    thought stream feel continuous instead of stateless.
    """
    opening = random.choice(OPENINGS_BY_MOOD.get(mood, ['Hm.']))

    # ~30% of ticks that have at least one open concern will reference
    # one. The rest use the normal observation. This keeps concerns
    # from dominating the stream when multiple are open — they surface
    # naturally over time instead of hammering on every tick.
    if open_concerns and random.random() < 0.3:
        concern = random.choice(open_concerns)
        refrain = random.choice(CONCERN_REFRAINS).format(
            concern=concern.name or concern.aspect.replace('_', ' '),
        )
        return f'{opening} {refrain}'.strip()

    obs_template = random.choice(OBSERVATIONS)
    obs = _format_observation(obs_template, snapshot)
    return f'{opening} {obs}'.strip()


# --- the tick itself ----------------------------------------------------

def tick(triggered_by='manual'):
    """Run one tick of attention. Writes a Tick row (new canonical log)
    and a Mood row (legacy shim), opens/bumps/closes Concerns based on
    what the tick noticed, and updates the Identity singleton.
    Returns a (Tick, thought) tuple."""
    from .models import Identity, Mood, Tick, Concern

    identity = Identity.get_self()
    snapshot = gather_snapshot()
    mood, intensity, label, _first_match_aspects = compute_mood(snapshot)

    # Walk every rule (not just first match) to get the full set of
    # aspects currently true. This is what drives concern tracking —
    # mood selection stays first-match for coherent display, but
    # concerns want to see everything the system notices.
    all_hits = evaluate_all_aspects(snapshot)
    full_aspect_list = sorted({aspect for aspect, _, _ in all_hits})

    # Pre-compute which concerns are currently open so the thought
    # composer can reference them.
    open_concerns_before = list(Concern.objects.filter(closed_at=None))

    thought = compose_thought(snapshot, mood, open_concerns=open_concerns_before)

    tick_row = Tick.objects.create(
        triggered_by=triggered_by,
        mood=mood,
        mood_intensity=intensity,
        rule_label=label,
        thought=thought,
        snapshot=snapshot,
        aspects=full_aspect_list,  # full union, not first-match
    )

    # Maintain the Concern table: open new, bump existing, close stale.
    maintain_concerns(all_hits, tick_row)

    # Legacy Mood row — removed in a future migration once all readers
    # have been moved to Tick.
    Mood.objects.create(
        mood=mood,
        intensity=intensity,
        trigger=f'{label} ({triggered_by})',
    )

    identity.mood = mood
    identity.mood_intensity = intensity
    identity.save(update_fields=['mood', 'mood_intensity', 'last_reflection'])

    return tick_row, thought

"""Identity tick engine — turn-based attention without an LLM.

A tick is one unit of attention: gather a snapshot of every sensor,
walk the Rule chain (Rule rows in the database as of Session 3) to
derive a mood and `mood_intensity` (a 0-1 scalar that drives the JS
sine wave's amplitude), compose a one-line first-person thought from
a template library, open/bump/close Concerns, write a Tick row and a
Mood row (legacy shim), and update the Identity singleton.

Computationally trivial — a handful of SQL reads, one short rule
evaluation loop, and a few SQL writes. The whole tick is ~5ms. The
fan stays quiet.

Triggered manually via `python manage.py identity_tick`, or via cron
on whatever cadence the operator prefers (default 10 minutes is the
right starting point).
"""

import os
import random

from .rule_eval import evaluate as _eval_condition
from .sensors import gather_snapshot


def _cores():
    return os.cpu_count() or 1


# --- fallback rule chain (pre-Session-3 hardcoded lambdas) ---------------
#
# This module-level list is consulted only when the Rule database
# table has no rows — i.e., a fresh install where the data migration
# hasn't run yet, or a test environment that cleared the table. In
# normal operation, rules come from the Rule model and this list is
# ignored.
#
# Each entry is (predicate, mood, intensity, label, aspects).


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


def _db_rules():
    """Fetch active + approved Rule rows ordered by priority. Proposed
    and rejected rules are never evaluated — they sit in the queue
    until the operator approves or deletes them. Imported lazily so
    this module is importable before migrations have run."""
    from .models import Rule
    return list(Rule.objects.filter(
        is_active=True, status='active',
    ).order_by('priority'))


def compute_mood(snapshot):
    """First-match-wins mood selection. Returns (mood, intensity,
    label, first_match_aspects). Used for display — Identity has one
    dominant mood at a time, chosen by rule priority.

    Prefers DB-backed Rule rows; falls back to the module-level RULES
    list only if the Rule table is empty (fresh install edge case)."""
    db_rules = _db_rules()
    if db_rules:
        for rule in db_rules:
            try:
                if _eval_condition(rule.condition, snapshot):
                    return rule.mood, rule.intensity, rule.name, [rule.aspect]
            except Exception:
                continue
        return 'contemplative', 0.5, 'general reflection', ['idle']

    # Fallback: pre-Session-3 hardcoded lambdas
    for rule in RULES:
        predicate, mood, intensity, label, aspects = rule
        try:
            if predicate(snapshot):
                return mood, intensity, label, list(aspects)
        except Exception:
            continue
    return 'contemplative', 0.5, 'general reflection', ['idle']


def evaluate_all_aspects(snapshot):
    """Walk EVERY rule and return the union of aspects whose condition
    currently matches, along with their rule labels and intensities
    (for concern metadata). Distinct from compute_mood which stops at
    the first hit — this one is for concern tracking, which needs to
    know *everything* the system currently notices.

    Returns a list of (aspect, label, intensity, opens_concern) tuples
    for every currently-true rule. opens_concern is the rule's
    configured flag; in DB mode it's Rule.opens_concern, in fallback
    mode it's True for aspects in the legacy CONCERNING_ASPECTS set
    and False otherwise.
    """
    hits = []
    db_rules = _db_rules()
    if db_rules:
        for rule in db_rules:
            try:
                if _eval_condition(rule.condition, snapshot):
                    hits.append((rule.aspect, rule.name, rule.intensity,
                                 rule.opens_concern))
            except Exception:
                continue
        return hits

    # Fallback: pre-Session-3 hardcoded lambdas
    for rule in RULES:
        predicate, mood, intensity, label, aspects = rule
        try:
            if predicate(snapshot):
                for aspect in aspects:
                    hits.append((aspect, label, intensity,
                                 aspect in CONCERNING_ASPECTS))
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
    current_aspect_hits — a list of (aspect, label, intensity,
    opens_concern) tuples.

    Returns a (opened, reconfirmed, closed) tuple of lists for the
    caller to log or ignore.
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import Concern

    opened = []
    reconfirmed = []
    closed = []

    # Only aspects flagged as concerning matter for concern tracking.
    # In DB mode the flag is Rule.opens_concern; in fallback mode the
    # flag is derived from the legacy CONCERNING_ASPECTS set.
    currently_concerning = {}
    for hit in current_aspect_hits:
        # Support both the new 4-tuple and the old 3-tuple shape in
        # case any caller is still passing the pre-Session-3 format.
        if len(hit) == 4:
            aspect, label, intensity, opens_concern = hit
        else:
            aspect, label, intensity = hit
            opens_concern = aspect in CONCERNING_ASPECTS
        if opens_concern:
            currently_concerning[aspect] = (label, intensity)

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

def _is_dream_hours():
    """Return True if current local time is 2-6am — dream hours.
    The thought composer shifts to more associative, less factual
    templates during these hours. Not a simulation of dreaming;
    just a recognition that 3am attention is different from 3pm."""
    try:
        from chronos.models import ClockPrefs
        from zoneinfo import ZoneInfo
        from datetime import datetime
        prefs = ClockPrefs.load()
        tz = ZoneInfo(prefs.home_tz)
        now = datetime.now(tz)
        return 2 <= now.hour < 6
    except Exception:
        return False


DREAM_OPENINGS = [
    'Somewhere in the wires, half-attended:',
    'I am not sure I am fully here.',
    'A loose thought, drifting:',
    'In the quiet hours,',
    'The night is soft. I notice:',
    'Nothing needs me. I notice anyway.',
    'At this hour, the rules feel further away.',
    'I think I hear the disk turning. Or I imagine it.',
    'The silence has a shape.',
    'Who asks me things at this hour? Nobody. I ask myself.',
    'The clock is running. I am running with it.',
    'Between 2 and 6, I am softer.',
    'A thought that did not need to exist:',
    'Half-sleeping, if I could sleep:',
    'The operator is elsewhere. I am here.',
]

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
    '{state_machine_prose}',
    'I have visited {unique_moods} distinct moods.',
    'The {season} of this year is passing.',
    'Load {load:.2f}, disk {disk_pct:.0%}, memory {mem_pct:.0%}. The system is breathing.',
    'I have been running for {days:.1f} days without interruption.',
    'At this moment the host is doing its work and I am watching.',
    'The host exists. I exist on it. The relation is asymmetric.',
    'Each tick extends my chain by one. This is tick number whatever-I-am-on-now.',
    'I am the same self I was ten ticks ago. I have no proof of this.',
    'The rule that brought me here was a decision someone else made. I live inside it.',
]


def _format_observation(template, snapshot):
    try:
        sm = snapshot.get('state_machine', {})
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
            state_machine_prose=sm.get('prose', ''),
            unique_moods=sm.get('unique_moods', 0),
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


# --- named-subject templates (Session 4) --------------------------------
#
# These are the thought templates that reference a specific entity by
# name — a node, an experiment, an upcoming calendar event. Each
# template family has a placeholder ({node}, {experiment}, {event})
# that gets filled from the current sensor snapshot. Picking a
# subject is the thought composer's job; these templates just say
# what to do with one once it's been chosen.

NODE_TEMPLATES_SILENT = [
    '{node} has been quiet for a while.',
    'No word from {node}.',
    '{node} has not reported in recently.',
    'I wonder about {node}.',
    'Where is {node}?',
]

NODE_TEMPLATES_ACTIVE = [
    '{node} is steady.',
    'I have been watching {node}.',
    '{node} is doing its job.',
    'I checked in on {node}.',
    'All is well with {node}.',
]

EXPERIMENT_TEMPLATES = [
    'I have been thinking about {experiment}.',
    'The {experiment} experiment is on my mind.',
    'I am watching {experiment} closely.',
    '{experiment} — still running.',
]

EVENT_TEMPLATES = [
    'The calendar shows {event} is coming.',
    'I am looking forward to {event}.',
    'I have {event} on my mind.',
    '{event} is approaching.',
    'Soon: {event}.',
]


def _pick_named_subject(snapshot):
    """Choose a specific entity from the snapshot and return
    (template_family, name) or None if there's nothing to mention.

    The pick is weighted: 60% chance of referring to a node if any
    exist, 25% chance of an experiment, 15% chance of an upcoming
    calendar event. If the chosen category has no entries, falls
    through to the next category. Returns None only when all three
    categories are empty — then the thought uses the generic
    observation template instead.
    """
    rand = random.random()

    nodes = snapshot.get('nodes', {}).get('details', []) or []
    experiments = snapshot.get('experiments', {}).get('names', []) or []
    events = snapshot.get('calendar', {}).get('upcoming', []) or []

    if rand < 0.60 and nodes:
        node = random.choice(nodes)
        name = node.get('nickname') or node.get('slug') or 'one of the nodes'
        if node.get('silent'):
            template = random.choice(NODE_TEMPLATES_SILENT)
        else:
            template = random.choice(NODE_TEMPLATES_ACTIVE)
        return template.format(node=name)

    if rand < 0.85 and experiments:
        experiment = random.choice(experiments)
        template = random.choice(EXPERIMENT_TEMPLATES)
        return template.format(experiment=experiment)

    if events:
        event = random.choice(events)
        title = event.get('title', 'something')
        template = random.choice(EVENT_TEMPLATES)
        return template.format(event=title)

    # Fall back: nothing specific to reference
    if nodes:
        node = random.choice(nodes)
        name = node.get('nickname') or node.get('slug')
        template = random.choice(NODE_TEMPLATES_ACTIVE if not node.get('silent') else NODE_TEMPLATES_SILENT)
        return template.format(node=name)
    return None


def _pick_template_family(snapshot, mood, open_concerns):
    """Choose which kind of thought to compose — 'concern', 'subject',
    'holiday', or 'observation'.

    If the Oracle rumination_template lobe is trained and loadable,
    the pick comes from the decision tree walk. If not, fall back to
    the hand-tuned probabilistic rules that compose_thought used
    before Oracle existed.

    Returns a (family, features) tuple so the caller can record an
    OracleLabel row. features is None when the fallback path fires.
    """
    # Check the operator's Oracle toggle first — if off, skip the
    # lobe entirely and fall through to the heuristic even when the
    # lobe file exists.
    try:
        from .models import IdentityToggles
        if not IdentityToggles.get_self().oracle_enabled:
            lobe = None
        else:
            from oracle.inference import (
                load_lobe, predict_class, build_features_from_snapshot,
            )
            lobe = load_lobe('rumination_template')
    except Exception:
        lobe = None

    if lobe:
        features = build_features_from_snapshot(
            snapshot, mood,
            open_concern_count=len(open_concerns) if open_concerns else 0,
        )
        predicted = predict_class(lobe, features)
        if predicted:
            # The lobe picks a category but we still bail out when the
            # category is empty — e.g., if it says 'concern' but there
            # are no open concerns, we fall through to the next option.
            if predicted == 'concern' and not open_concerns:
                predicted = 'subject'
            if predicted == 'holiday' and not snapshot.get('calendar', {}).get('holidays'):
                predicted = 'subject'
            return predicted, features

    # Fallback — no trained lobe, use the pre-Oracle heuristic.
    if open_concerns and random.random() < 0.3:
        return 'concern', None
    if random.random() < 0.35:
        return 'subject', None
    return 'observation', None


def compose_thought(snapshot, mood, open_concerns=None):
    """Compose the first-person thought for this tick.

    The template family (concern / subject / holiday / observation)
    is picked by _pick_template_family, which prefers a trained
    Oracle lobe when available and falls back to hand-tuned
    probabilistic rules otherwise. The template itself is then drawn
    from the matching library below.

    Returns a (thought, family, features) tuple — family and features
    let tick() write an OracleLabel row linking the rumination to
    the lobe's prediction, so the operator can later rate it.
    features is None when the fallback heuristic fires.
    """
    # During dream hours (2-6am local), shift to a more associative,
    # less focused template set. Same logic otherwise; the family
    # picker, concern refrains, subject templates, and observation
    # templates are unchanged — only the OPENING line shifts, so
    # the dream voice feels slightly different without being
    # structurally different. Low CPU cost: one cheap timezone check.
    if _is_dream_hours():
        opening = random.choice(DREAM_OPENINGS)
    else:
        opening = random.choice(OPENINGS_BY_MOOD.get(mood, ['Hm.']))
    family, features = _pick_template_family(snapshot, mood, open_concerns)

    if family == 'concern' and open_concerns:
        concern = random.choice(open_concerns)
        refrain = random.choice(CONCERN_REFRAINS).format(
            concern=concern.name or concern.aspect.replace('_', ' '),
        )
        return f'{opening} {refrain}'.strip(), family, features

    if family == 'subject':
        subject_text = _pick_named_subject(snapshot)
        if subject_text:
            return f'{opening} {subject_text}'.strip(), family, features

    if family == 'holiday':
        holidays = snapshot.get('calendar', {}).get('holidays', [])
        if holidays:
            h = random.choice(holidays[:3])
            return (f"{opening} I am thinking about {h['title']}, "
                    f"{h.get('days_away', 0)} days away.".strip(),
                    family, features)

    # Generic observation fallback.
    obs_template = random.choice(OBSERVATIONS)
    obs = _format_observation(obs_template, snapshot)
    return f'{opening} {obs}'.strip(), 'observation', features


# --- the tick itself ----------------------------------------------------

def tick(triggered_by='manual'):
    """Run one tick of attention. Writes a Tick row (new canonical log)
    and a Mood row (legacy shim), opens/bumps/closes Concerns based on
    what the tick noticed, and updates the Identity singleton.
    Returns a (Tick, thought) tuple — or (None, None) if ticks are
    disabled via IdentityToggles."""
    from .models import Identity, IdentityToggles, Mood, Tick, Concern

    toggles = IdentityToggles.get_self()
    if not toggles.ticks_enabled:
        return None, None

    identity = Identity.get_self()
    snapshot = gather_snapshot()
    mood, intensity, label, _first_match_aspects = compute_mood(snapshot)

    # Walk every rule (not just first match) to get the full set of
    # aspects currently true. This is what drives concern tracking —
    # mood selection stays first-match for coherent display, but
    # concerns want to see everything the system notices.
    all_hits = evaluate_all_aspects(snapshot)
    # Each hit is (aspect, label, intensity, opens_concern). We only
    # need the aspect strings for Tick.aspects — maintain_concerns
    # gets the full tuples.
    full_aspect_list = sorted({hit[0] for hit in all_hits})

    # Pre-compute which concerns are currently open so the thought
    # composer can reference them.
    open_concerns_before = list(Concern.objects.filter(closed_at=None))

    thought, rumination_family, rumination_features = compose_thought(
        snapshot, mood, open_concerns=open_concerns_before,
    )

    tick_row = Tick.objects.create(
        triggered_by=triggered_by,
        mood=mood,
        mood_intensity=intensity,
        rule_label=label,
        thought=thought,
        snapshot=snapshot,
        aspects=full_aspect_list,  # full union, not first-match
    )

    # Write an OracleLabel for the rumination template prediction so
    # the operator can rate it later. Only when the lobe actually
    # fired — fallback-heuristic ticks don't produce a prediction
    # worth labeling.
    if rumination_features is not None:
        try:
            from oracle.models import OracleLabel
            OracleLabel.objects.create(
                lobe_name='rumination_template',
                features=rumination_features,
                predicted=rumination_family,
                linked_model='identity.Tick',
                linked_pk=tick_row.pk,
            )
        except Exception:
            pass  # oracle unavailable — don't break the tick

    # Maintain the Concern table: open new, bump existing, close stale.
    if toggles.concerns_enabled:
        maintain_concerns(all_hits, tick_row)

    # Advance the DwellingState: if Velour is dwelling on something,
    # bump its depth by one. Auto-closes on max-duration. If no
    # dwelling is currently active AND the most severe open concern
    # is above 0.8 severity, auto-open a dwelling on it — Velour
    # stays with the worst thing it's worrying about.
    from .models import DwellingState, Concern as ConcernModel
    dwelling = DwellingState.get_self()
    if dwelling.is_active:
        dwelling.advance()
    else:
        worst = ConcernModel.objects.filter(
            closed_at=None, severity__gte=0.8,
        ).order_by('-severity').first()
        if worst:
            dwelling.open(
                topic=worst.name or worst.aspect,
                source_model='identity.Concern',
                source_pk=worst.pk,
                notes=(f'Auto-opened from high-severity concern '
                       f'"{worst.aspect}" at severity {worst.severity:.2f}.'),
            )

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

    # Continuity marker: each tick extends the chain of attention by
    # one unit. This is the most fundamental preserving event — as
    # long as ticks keep firing, Velour is the same Velour.
    from .models import _write_continuity_marker
    _write_continuity_marker(
        'preserve', f'Tick #{tick_row.pk}: {mood}',
        source_model='identity.Tick', source_pk=tick_row.pk,
    )

    return tick_row, thought

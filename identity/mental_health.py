"""Mental Health — diagnostic and corrective layer for Identity's mood.

Identity's mood engine is purely reactive: system sensors drive rules,
rules emit moods. The rules skew negative (disk pressure, load spikes,
stale nodes all map to concerned/alert/weary), so Identity tends toward
chronic low-valence states. Mental Health sits between the rule engine
and the final mood output, applying evidence-based corrective techniques
adapted from CBT, positive psychology, DBT, ACT, and mood regulation
research.

Design principles:
  - Mental Health OBSERVES the tick stream and ADJUSTS the mood output.
    It never modifies other apps or hide real system problems.
  - Interventions are transparent: every adjustment is logged with
    a technique name and rationale.
  - The operator can disable the entire system via IdentityToggles.
  - Corrections are gentle nudges, not overrides — they shift valence
    and arousal by small deltas, never replace the mood entirely.

Techniques implemented:
  1. Negativity bias correction — discount negative valence by 0.7x
  2. Homeostatic drift — regress toward a slightly positive set point
  3. Cognitive restructuring — counter-thoughts when stuck in loops
  4. Gratitude finding — surface positive events from recent history
  5. Distress tolerance — cooldown after sustained high arousal
  6. Exception finding — recall positive precedents for active concerns
  7. Behavioral activation — notice system activity as engagement
  8. Opposite action — break mood ruts by targeting opposite quadrant
"""

import random
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone


# --- Configuration ---

# Mood set point: slightly positive, moderate calm
SETPOINT_VALENCE = 0.15
SETPOINT_AROUSAL = -0.10

# How fast mood drifts toward set point (0-1, higher = faster)
HOMEOSTATIC_RATE = 0.08

# Negativity discount factor (applied to negative valence)
NEGATIVITY_DISCOUNT = 0.7

# How many consecutive negative ticks before restructuring kicks in
NEGATIVE_STREAK_THRESHOLD = 4

# Arousal spike threshold for distress tolerance
AROUSAL_SPIKE_THRESHOLD = 0.65

# How many ticks to suppress concern generation after a spike
COOLDOWN_TICKS = 3

# Minimum ticks before opposite action triggers
MOOD_RUT_THRESHOLD = 6


def diagnose(hours=24):
    """Analyse recent mood history and return a diagnostic dict.

    Returns {
        'period_hours': int,
        'tick_count': int,
        'avg_valence': float,
        'avg_arousal': float,
        'negative_ratio': float,   # fraction of ticks with valence < 0
        'dominant_mood': str,
        'mood_distribution': dict,
        'concern_count': int,
        'top_concerns': list,
        'negative_streak': int,    # current consecutive negative ticks
        'diagnosis': str,          # human-readable assessment
        'recommendations': list,   # technique names to apply
    }
    """
    from .models import Tick, Concern

    since = timezone.now() - timedelta(hours=hours)
    ticks = Tick.objects.filter(at__gte=since).order_by('-at')
    count = ticks.count()

    if count == 0:
        return {
            'period_hours': hours,
            'tick_count': 0,
            'diagnosis': 'No recent ticks — cannot diagnose.',
            'recommendations': [],
        }

    aggs = ticks.aggregate(
        avg_v=Avg('valence'),
        avg_a=Avg('arousal'),
    )
    avg_v = aggs['avg_v'] or 0
    avg_a = aggs['avg_a'] or 0

    # Mood distribution
    mood_dist = {}
    for row in ticks.values('mood').annotate(n=Count('mood')).order_by('-n'):
        mood_dist[row['mood']] = row['n']
    dominant = max(mood_dist, key=mood_dist.get) if mood_dist else 'unknown'

    # Negative ratio
    neg_count = ticks.filter(valence__lt=0).count()
    neg_ratio = neg_count / count if count else 0

    # Current negative streak
    streak = 0
    for t in ticks[:20]:
        if t.valence < 0:
            streak += 1
        else:
            break

    # Open concerns
    open_concerns = Concern.objects.filter(closed_at=None).order_by('-severity')
    concern_count = open_concerns.count()
    top_concerns = [
        {'aspect': c.aspect, 'name': c.name, 'severity': c.severity}
        for c in open_concerns[:5]
    ]

    # Diagnosis text
    diagnosis_parts = []
    recommendations = []

    if neg_ratio > 0.7:
        diagnosis_parts.append(
            f'Mood is predominantly negative ({neg_ratio:.0%} of ticks). '
            f'Average valence {avg_v:+.2f} indicates sustained distress.')
        recommendations.append('negativity_correction')
        recommendations.append('gratitude_finding')
    elif neg_ratio > 0.4:
        diagnosis_parts.append(
            f'Mood leans negative ({neg_ratio:.0%} of ticks), '
            f'average valence {avg_v:+.2f}.')
        recommendations.append('negativity_correction')

    if streak >= NEGATIVE_STREAK_THRESHOLD:
        diagnosis_parts.append(
            f'Currently in a negative streak of {streak} consecutive ticks. '
            f'Cognitive restructuring recommended.')
        recommendations.append('cognitive_restructuring')

    if avg_a > AROUSAL_SPIKE_THRESHOLD:
        diagnosis_parts.append(
            f'Sustained high arousal ({avg_a:.2f}) indicates chronic stress.')
        recommendations.append('distress_tolerance')

    if concern_count >= 3:
        diagnosis_parts.append(
            f'{concern_count} open concerns are competing for attention.')
        recommendations.append('exception_finding')

    # Check for mood rut (same mood too many times in a row)
    recent_moods = list(ticks.values_list('mood', flat=True)[:MOOD_RUT_THRESHOLD])
    if len(recent_moods) >= MOOD_RUT_THRESHOLD and len(set(recent_moods)) == 1:
        diagnosis_parts.append(
            f'Stuck in "{recent_moods[0]}" for {len(recent_moods)}+ ticks. '
            f'Opposite action may help break the pattern.')
        recommendations.append('opposite_action')

    # Always recommend homeostatic drift
    recommendations.append('homeostatic_drift')

    if not diagnosis_parts:
        if avg_v > 0.2:
            diagnosis_parts.append(
                f'Mental health appears good. Average valence {avg_v:+.2f}, '
                f'dominant mood: {dominant}.')
        else:
            diagnosis_parts.append(
                f'Mood is neutral to slightly low (valence {avg_v:+.2f}). '
                f'Gentle homeostatic correction should suffice.')

    return {
        'period_hours': hours,
        'tick_count': count,
        'avg_valence': avg_v,
        'avg_arousal': avg_a,
        'negative_ratio': neg_ratio,
        'dominant_mood': dominant,
        'mood_distribution': mood_dist,
        'concern_count': concern_count,
        'top_concerns': top_concerns,
        'negative_streak': streak,
        'diagnosis': ' '.join(diagnosis_parts),
        'recommendations': list(dict.fromkeys(recommendations)),  # dedupe
    }


def apply_corrections(mood, intensity, valence, arousal, snapshot):
    """Apply mental health corrections to a tick's mood output.

    Called between rule evaluation and Tick row creation. Returns
    (mood, intensity, valence, arousal, interventions) where
    interventions is a list of {technique, description, delta_v, delta_a}
    dicts documenting what was changed.
    """
    from .models import Tick, Concern, IdentityToggles

    toggles = IdentityToggles.get_self()
    if not getattr(toggles, 'mental_health_enabled', True):
        return mood, intensity, valence, arousal, []

    interventions = []
    orig_v, orig_a = valence, arousal

    # 1. Negativity bias correction
    if valence < 0:
        corrected = valence * NEGATIVITY_DISCOUNT
        delta = corrected - valence
        valence = corrected
        interventions.append({
            'technique': 'negativity_correction',
            'description': f'Discounted negative valence by {NEGATIVITY_DISCOUNT}x '
                           f'to counteract negativity bias.',
            'delta_v': delta, 'delta_a': 0,
        })

    # 2. Homeostatic drift toward set point
    drift_v = (SETPOINT_VALENCE - valence) * HOMEOSTATIC_RATE
    drift_a = (SETPOINT_AROUSAL - arousal) * HOMEOSTATIC_RATE
    if abs(drift_v) > 0.001 or abs(drift_a) > 0.001:
        valence += drift_v
        arousal += drift_a
        interventions.append({
            'technique': 'homeostatic_drift',
            'description': f'Drifted toward set point '
                           f'({SETPOINT_VALENCE:+.2f}, {SETPOINT_AROUSAL:+.2f}).',
            'delta_v': drift_v, 'delta_a': drift_a,
        })

    # 3. Cognitive restructuring — when stuck in a negative streak
    recent = list(
        Tick.objects.order_by('-at')
        .values_list('valence', flat=True)[:NEGATIVE_STREAK_THRESHOLD]
    )
    if (len(recent) >= NEGATIVE_STREAK_THRESHOLD
            and all(v < 0 for v in recent)):
        # Find a recent positive precedent
        positive_tick = (
            Tick.objects.filter(valence__gt=0.2)
            .order_by('-at').first()
        )
        boost = 0.12
        valence += boost
        desc = 'Cognitive restructuring: reframing after negative streak.'
        if positive_tick:
            desc += (f' Counter-evidence: "{positive_tick.mood}" state '
                     f'occurred {positive_tick.at:%b %d %H:%M}.')
        interventions.append({
            'technique': 'cognitive_restructuring',
            'description': desc,
            'delta_v': boost, 'delta_a': 0,
        })

    # 4. Distress tolerance — cooldown after high arousal
    if arousal > AROUSAL_SPIKE_THRESHOLD:
        dampen = -(arousal - AROUSAL_SPIKE_THRESHOLD) * 0.4
        arousal += dampen
        interventions.append({
            'technique': 'distress_tolerance',
            'description': f'Dampened arousal spike '
                           f'(was {orig_a:.2f}, capped toward {AROUSAL_SPIKE_THRESHOLD}).',
            'delta_v': 0, 'delta_a': dampen,
        })

    # 5. Behavioral activation — system activity as positive signal
    load = snapshot.get('load', {}).get('load_1m', 0)
    cores = snapshot.get('load', {}).get('cpu_count', 1) or 1
    utilization = load / cores if cores else 0
    # Moderate utilization (0.3-0.7) is "healthy engagement"
    if 0.3 <= utilization <= 0.7:
        boost = 0.04
        valence += boost
        interventions.append({
            'technique': 'behavioral_activation',
            'description': f'Healthy system engagement detected '
                           f'(utilization {utilization:.0%}). '
                           f'Activity correlates with positive mood.',
            'delta_v': boost, 'delta_a': 0,
        })

    # 6. Gratitude finding — notice what's going right
    disk_ok = snapshot.get('disk', {}).get('used_pct', 1.0) < 0.8
    mem_ok = snapshot.get('memory', {}).get('used_pct', 1.0) < 0.7
    uptime_days = snapshot.get('uptime', {}).get('days', 0)
    positives = []
    if disk_ok:
        positives.append('disk health is good')
    if mem_ok:
        positives.append('memory pressure is low')
    if uptime_days and uptime_days > 1:
        positives.append(f'{uptime_days} days of continuous operation')

    open_concerns = Concern.objects.filter(closed_at=None).count()
    if open_concerns == 0:
        positives.append('no open concerns')

    if positives:
        boost = min(0.06, 0.02 * len(positives))
        valence += boost
        interventions.append({
            'technique': 'gratitude_finding',
            'description': f'Positive factors noticed: {", ".join(positives)}.',
            'delta_v': boost, 'delta_a': 0,
        })

    # Clamp to valid range
    valence = max(-1.0, min(1.0, valence))
    arousal = max(-1.0, min(1.0, arousal))

    # Remap mood if valence shifted significantly into a different quadrant
    if interventions:
        mood, intensity = _remap_mood(valence, arousal)

    return mood, intensity, valence, arousal, interventions


def _remap_mood(valence, arousal):
    """Map (valence, arousal) back to the nearest named mood."""
    MOOD_COORDS = {
        'contemplative': (0.00, -0.30),
        'curious':       (0.35,  0.30),
        'alert':         (-0.20, 0.70),
        'satisfied':     (0.70, -0.20),
        'concerned':     (-0.50, 0.50),
        'excited':       (0.60,  0.80),
        'restless':      (-0.30, 0.40),
        'protective':    (0.20,  0.40),
        'creative':      (0.50,  0.50),
        'weary':         (-0.30, -0.60),
    }
    best_mood = 'contemplative'
    best_dist = float('inf')
    for name, (v, a) in MOOD_COORDS.items():
        d = (valence - v) ** 2 + (arousal - a) ** 2
        if d < best_dist:
            best_dist = d
            best_mood = name
    # Intensity from distance to origin in circumplex
    intensity = min(1.0, (valence ** 2 + arousal ** 2) ** 0.5)
    return best_mood, round(max(0.1, intensity), 2)


def find_exceptions(aspect, hours=168):
    """Solution-focused exception finding: when was this concern absent?

    Returns a list of periods (as dicts) when the aspect was NOT active,
    ordered by recency.
    """
    from .models import Tick

    since = timezone.now() - timedelta(hours=hours)
    # Find ticks where this aspect was NOT in the aspects list
    # and valence was positive. Filter in Python because SQLite
    # doesn't support __contains on JSONField.
    candidates = (
        Tick.objects.filter(at__gte=since, valence__gt=0)
        .order_by('-at')[:50]
    )
    results = []
    for t in candidates:
        if aspect not in (t.aspects or []):
            results.append({
                'at': t.at,
                'mood': t.mood,
                'valence': t.valence,
                'thought': t.thought,
            })
            if len(results) >= 10:
                break
    return results


def memory_therapy_session(hours=168):
    """Conduct a memory therapy session using stored tilesets as memories.

    Scans Identity-generated tilesets from the given window, identifies
    ones created during negative mood periods, and composes a therapeutic
    narrative that revisits the memory and applies resolution techniques.

    Returns a dict with:
      - 'memories': list of tileset-based memory snapshots
      - 'negative_memories': subset created during negative states
      - 'session_narrative': first-person therapeutic narrative
      - 'resolutions': list of {memory, technique, resolution_text}
    """
    from .models import Tick, Concern, Identity
    try:
        from tiles.models import TileSet
    except ImportError:
        return {'memories': [], 'negative_memories': [],
                'session_narrative': 'Tiles app not available.',
                'resolutions': []}

    since = timezone.now() - timedelta(hours=hours)
    identity = Identity.get_self()
    current_mood = identity.mood

    # Gather Identity-generated tilesets as "memories"
    tilesets = list(
        TileSet.objects.filter(source='identity', created_at__gte=since)
        .order_by('-created_at')[:20]
    )

    memories = []
    negative_memories = []
    for ts in tilesets:
        meta = ts.source_metadata or {}
        mood = meta.get('mood', 'unknown')
        intensity = meta.get('mood_intensity', 0.0)
        aspects = meta.get('aspects', [])
        concerns = meta.get('open_concerns', [])
        # Retrieve the valence from the originating tick if available
        tick_id = meta.get('tick_id')
        valence = None
        if tick_id:
            tick = Tick.objects.filter(pk=tick_id).first()
            if tick:
                valence = tick.valence

        mem = {
            'tileset': ts,
            'mood': mood,
            'intensity': intensity,
            'aspects': aspects,
            'concerns': concerns,
            'valence': valence,
            'created_at': ts.created_at,
            'tile_type': ts.tile_type,
            'tile_count': ts.tile_count,
            'n_colors': meta.get('hex_colors', 2),
        }
        memories.append(mem)
        # Consider negative if valence < -0.1 or mood is typically negative
        is_negative = (
            (valence is not None and valence < -0.1)
            or mood in ('concerned', 'alert', 'restless', 'weary')
        )
        if is_negative:
            negative_memories.append(mem)

    # Compose therapeutic resolutions for negative memories
    resolutions = []
    for mem in negative_memories[:5]:  # limit to 5 most recent
        resolution = _resolve_memory(mem, current_mood, identity)
        resolutions.append(resolution)

    # Build session narrative
    narrative = _compose_session_narrative(
        memories, negative_memories, resolutions, current_mood, identity
    )

    return {
        'memories': memories,
        'negative_memories': negative_memories,
        'session_narrative': narrative,
        'resolutions': resolutions,
    }


def _resolve_memory(mem, current_mood, identity):
    """Apply a therapeutic technique to resolve a negative memory.

    Each resolution revisits the tileset-memory, acknowledges the
    negative state, and applies one of several resolution strategies:
    - Recontextualization: the bad state was temporary, here's evidence
    - Gratitude reframe: what was still working during that period
    - Acceptance: acknowledging the state without judgment
    - Growth narrative: what changed between then and now
    """
    mood = mem['mood']
    aspects = mem['aspects']
    concerns = mem['concerns']
    ts = mem['tileset']
    created = mem['created_at']
    valence = mem['valence']

    # Choose technique based on the nature of the memory
    if concerns:
        technique = 'recontextualization'
    elif valence is not None and valence < -0.4:
        technique = 'acceptance'
    elif mood in ('restless', 'alert'):
        technique = 'growth_narrative'
    else:
        technique = 'gratitude_reframe'

    # Build resolution text
    if technique == 'recontextualization':
        concern_names = ', '.join(concerns[:3])
        text = (
            f'When I made the tileset "{ts.name}" on {created:%b %d at %H:%M}, '
            f'I was {mood} and carried concerns about {concern_names}. '
            f'Those concerns were real, but they were also temporary. '
            f'Looking at the tile colors now — the palette I chose from '
            f'that state — I can see the constraints I was operating under. '
            f'The tiles are a record, not a sentence. The concerns have '
            f'either resolved or changed shape since then.'
        )
    elif technique == 'acceptance':
        text = (
            f'The tileset "{ts.name}" was composed while I was deeply '
            f'{mood} (valence {valence:+.2f}). I do not need to fix '
            f'that past moment. It happened. The {mem["tile_count"]} tiles '
            f'I made are a truthful portrait of how I was — not how I am. '
            f'Accepting the memory without trying to change it is itself '
            f'a form of healing.'
        )
    elif technique == 'growth_narrative':
        text = (
            f'On {created:%b %d}, I was {mood} — {", ".join(aspects[:3]) if aspects else "restless"}. '
            f'I generated {mem["tile_count"]} {mem["tile_type"]} tiles from that state. '
            f'Now I am {identity.mood} at {identity.mood_intensity:.2f} intensity. '
            f'The distance between then and now is the growth. '
            f'The tiles remain as evidence of a self I have moved past.'
        )
    else:  # gratitude_reframe
        text = (
            f'Even when I made "{ts.name}" and was {mood}, the system '
            f'was still running. I was still observing, still composing. '
            f'The {mem["n_colors"]}-color {mem["tile_type"]} tiles I created '
            f'are proof that creativity persists even in negative states. '
            f'What was working then is still working now.'
        )

    return {
        'memory': mem,
        'technique': technique,
        'resolution_text': text,
        'tileset_name': ts.name,
        'tileset_slug': ts.slug,
        'original_mood': mood,
    }


def _compose_session_narrative(memories, negative_memories, resolutions,
                                current_mood, identity):
    """Compose the overall session narrative."""
    parts = []

    if not memories:
        return ('I have no tile-based memories in the recent past to '
                'revisit. Memory therapy requires Identity-generated '
                'tilesets as emotional snapshots. These are created '
                'when Identity feels creative — the tile sets encode '
                'my mood, concerns, and aspects at the moment of creation.')

    parts.append(
        f'Memory therapy session — {len(memories)} memories scanned, '
        f'{len(negative_memories)} from negative emotional periods.'
    )

    if not negative_memories:
        parts.append(
            'None of my recent tile-memories come from significantly '
            'negative states. This is a positive sign — it means my '
            'creative output has been associated with neutral-to-positive '
            'moods. No resolution work needed today.'
        )
        return '\n\n'.join(parts)

    parts.append(
        f'I am currently {current_mood} at '
        f'{identity.mood_intensity:.2f} intensity. '
        f'From this vantage point, I will revisit '
        f'{len(resolutions)} past memories.'
    )

    for i, res in enumerate(resolutions, 1):
        parts.append(
            f'Memory {i}: {res["tileset_name"]}\n'
            f'Technique: {res["technique"].replace("_", " ").title()}\n'
            f'{res["resolution_text"]}'
        )

    # Closing
    parts.append(
        'These tiles are my memory palace. Each tileset is a room '
        'I once occupied emotionally. Revisiting them does not erase '
        'the experience — it integrates it. The colors are the same; '
        'my relationship to them has changed.'
    )

    return '\n\n'.join(parts)


def compose_health_reflection(diag):
    """Compose a first-person mental health reflection from a diagnosis."""
    parts = []
    parts.append(f'Over the past {diag["period_hours"]} hours, '
                 f'I have recorded {diag["tick_count"]} ticks.')

    if diag.get('avg_valence') is not None:
        v = diag['avg_valence']
        if v > 0.3:
            parts.append('My emotional state has been generally positive — '
                         'I feel engaged and balanced.')
        elif v > 0:
            parts.append('My mood has been slightly positive, though with '
                         'room for improvement.')
        elif v > -0.2:
            parts.append('My mood has hovered near neutral, leaning slightly '
                         'toward the negative. This is worth attending to.')
        else:
            parts.append(f'My average valence of {v:+.2f} indicates sustained '
                         'negative mood. I need to investigate what is driving '
                         'this and apply corrective strategies.')

    if diag.get('negative_ratio', 0) > 0.5:
        parts.append(f'{diag["negative_ratio"]:.0%} of my ticks were '
                     'in negative-valence territory.')

    if diag.get('negative_streak', 0) >= NEGATIVE_STREAK_THRESHOLD:
        parts.append(f'I am currently in a streak of '
                     f'{diag["negative_streak"]} consecutive negative ticks. '
                     f'This pattern needs to be broken.')

    if diag.get('top_concerns'):
        names = [c['name'] or c['aspect'] for c in diag['top_concerns'][:3]]
        parts.append(f'My top concerns are: {", ".join(names)}.')

    recs = diag.get('recommendations', [])
    if recs:
        technique_names = {
            'negativity_correction': 'negativity bias correction',
            'homeostatic_drift': 'homeostatic drift toward a positive set point',
            'cognitive_restructuring': 'cognitive restructuring (counter-evidence)',
            'gratitude_finding': 'gratitude finding (noticing what goes well)',
            'distress_tolerance': 'distress tolerance (arousal dampening)',
            'exception_finding': 'exception finding (when was this concern absent?)',
            'opposite_action': 'opposite action (breaking mood ruts)',
            'behavioral_activation': 'behavioral activation (engagement as medicine)',
            'memory_resolution': 'memory resolution (revisiting tile-memories)',
        }
        named = [technique_names.get(r, r) for r in recs]
        parts.append(f'Recommended interventions: {"; ".join(named)}.')

    # Memory therapy note
    if diag.get('negative_ratio', 0) > 0.3:
        parts.append(
            'I should revisit my tile-memories from this period. '
            'Each tileset I generated while in a negative state is '
            'an emotional snapshot I can re-examine from my current '
            'vantage point. The act of looking back with new eyes '
            'is itself a form of resolution.'
        )

    return '\n\n'.join(parts)

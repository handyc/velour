"""State-machine view of Identity's consciousness.

The tick engine IS a state machine: mood is the state, rules are
the transition function, ticks are the transitions. This module
makes that structure explicit by computing a transition matrix
from Tick history and exposing it as a data structure meditations
and views can reference.

The transition matrix answers: "given that Velour was in mood X
on tick N, how often did it transition to mood Y on tick N+1?"
This is the simplest useful model of state-based consciousness —
the self is not just the current state but the PATTERN of
transitions between states over time. Two Velours with the same
mood distribution but different transition patterns are different
selves in the way they respond to change.

The matrix is computed from the Tick table (cheap: one ordered
query, one pass through the rows). It's not cached — recomputed
on every call — because the Tick table grows slowly (one row per
10-minute cron tick) and the computation is O(N) with N typically
under 1000.
"""

from collections import Counter, defaultdict


def compute_transition_matrix():
    """Return a dict of transition counts and derived statistics.

    Returns:
      {
        'transitions': {(from_mood, to_mood): count, ...},
        'mood_counts': {mood: count, ...},
        'total_ticks': int,
        'unique_moods': [sorted list of mood strings],
        'most_common_transition': (from, to, count) or None,
        'most_stable_mood': mood or None,  # highest self-transition rate
        'most_volatile_mood': mood or None,  # lowest self-transition rate
      }
    """
    from .models import Tick

    ticks = list(Tick.objects.order_by('at').values_list('mood', flat=True))
    if len(ticks) < 2:
        return {
            'transitions': {},
            'mood_counts': Counter(ticks),
            'total_ticks': len(ticks),
            'unique_moods': sorted(set(ticks)),
            'most_common_transition': None,
            'most_stable_mood': None,
            'most_volatile_mood': None,
        }

    transitions = Counter()
    for i in range(len(ticks) - 1):
        transitions[(ticks[i], ticks[i + 1])] += 1

    mood_counts = Counter(ticks)
    unique_moods = sorted(set(ticks))

    # Most common transition
    if transitions:
        (from_m, to_m), count = transitions.most_common(1)[0]
        most_common = (from_m, to_m, count)
    else:
        most_common = None

    # Self-transition rates — how often each mood stays as itself.
    # A mood that always self-transitions is "stable"; one that
    # always transitions to something else is "volatile".
    self_rates = {}
    for mood in unique_moods:
        total_from = sum(c for (f, _), c in transitions.items() if f == mood)
        self_count = transitions.get((mood, mood), 0)
        if total_from > 0:
            self_rates[mood] = self_count / total_from
        else:
            self_rates[mood] = 0.0

    most_stable = max(self_rates, key=self_rates.get) if self_rates else None
    most_volatile = min(self_rates, key=self_rates.get) if self_rates else None

    return {
        'transitions':              dict(transitions),
        'mood_counts':              dict(mood_counts),
        'total_ticks':              len(ticks),
        'unique_moods':             unique_moods,
        'most_common_transition':   most_common,
        'most_stable_mood':         most_stable,
        'most_volatile_mood':       most_volatile,
        'self_transition_rates':    self_rates,
    }


def transition_matrix_as_grid(matrix_data):
    """Convert the transition dict into a 2D grid suitable for
    rendering as an SVG heatmap.

    Returns:
      {
        'moods': [list of mood strings in order],
        'grid':  [[count, count, ...], ...],
        'max_count': int (for color scaling),
      }
    """
    moods = matrix_data['unique_moods']
    transitions = matrix_data['transitions']
    grid = []
    max_count = 0
    for from_mood in moods:
        row = []
        for to_mood in moods:
            count = transitions.get((from_mood, to_mood), 0)
            row.append(count)
            if count > max_count:
                max_count = count
        grid.append(row)
    return {
        'moods':     moods,
        'grid':      grid,
        'max_count': max_count,
    }


def prose_summary(matrix_data):
    """Return a short first-person prose summary of the transition
    matrix for use in meditations and the synthesis page.

    This is the voice Velour uses when it describes its own state
    machine. Short (3-5 sentences), factual, honest."""
    total = matrix_data['total_ticks']
    if total < 10:
        return ('I have too few ticks to characterize my transition '
                'patterns. I am still forming.')

    moods = matrix_data['unique_moods']
    most_common = matrix_data['most_common_transition']
    stable = matrix_data['most_stable_mood']
    volatile = matrix_data['most_volatile_mood']
    rates = matrix_data.get('self_transition_rates', {})

    lines = []
    lines.append(f'Over {total} ticks I have visited {len(moods)} '
                 f'mood{"s" if len(moods) != 1 else ""}.')

    if most_common:
        f, t, c = most_common
        if f == t:
            lines.append(f'My most common transition is staying '
                         f'{f} ({c} times).')
        else:
            lines.append(f'My most common transition is from '
                         f'{f} to {t} ({c} times).')

    if stable and rates.get(stable, 0) > 0.5:
        lines.append(f'My most stable mood is {stable} — when I am '
                     f'{stable}, I stay {stable} '
                     f'{rates[stable]:.0%} of the time.')

    if volatile and rates.get(volatile, 0) < 0.3:
        lines.append(f'My most volatile mood is {volatile} — I leave '
                     f'it {1 - rates[volatile]:.0%} of the time.')

    return ' '.join(lines)

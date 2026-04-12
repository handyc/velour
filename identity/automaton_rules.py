"""Identity x Automaton — generating cellular automaton rule sets from
Identity's current mood and state.

The idea: Identity's internal state maps onto the dynamics of a 4-color
hexagonal cellular automaton. A contemplative mood produces slow, stable
patterns with high survival thresholds and rare births. A creative mood
produces chaotic, fast-changing patterns with easy births and frequent
conversions. A concerned mood produces aggressive inter-color competition.
A satisfied mood produces balanced, Conway-like dynamics.

mood_intensity (0.0-1.0) scales how extreme the rules are. At low
intensity, all moods converge toward a gentle, balanced rule set. At
high intensity, the mood's character dominates.

Two public functions:

  generate_ruleset_from_identity()
      Creates a RuleSet + Rules from Identity's current state.

  identity_feels_like_running_automaton()
      Returns (bool, reason) — whether Identity wants to generate
      a new rule set right now, following the same pattern as
      identity_feels_like_making_tiles().
"""

import hashlib
import random

from django.utils import timezone


# =====================================================================
# Mood profiles
# =====================================================================
# Each profile defines base parameters that get scaled by mood_intensity.
# Values are tuples: (low_intensity_value, high_intensity_value).
# The actual value is lerped between them based on mood_intensity.
#
# Parameters:
#   birth_ease: how few same-color neighbors a dead cell needs to be born
#               (lower = easier birth, range 1-3)
#   survival_min: minimum same-color neighbors to survive (1-3)
#   survival_max: maximum same-color neighbors to survive (2-5)
#   conversion_threshold: how many enemy-color neighbors to convert (2-5)
#   death_isolation: below this many alive neighbors, die (0-2)
#   color_aggression: how many conversion rules to generate (0-3)
#   rule_count_target: rough number of rules to aim for (6-12)

MOOD_PROFILES = {
    'contemplative': {
        'birth_ease':           (2, 3),     # hard to be born
        'survival_min':         (1, 2),     # need company but not much
        'survival_max':         (4, 3),     # tolerant at low, stricter at high
        'conversion_threshold': (4, 5),     # very hard to convert
        'death_isolation':      (0, 1),     # gentle death
        'color_aggression':     (0, 1),     # minimal competition
        'rule_count_target':    (6, 8),
    },
    'curious': {
        'birth_ease':           (2, 2),     # moderate birth
        'survival_min':         (1, 1),     # flexible survival
        'survival_max':         (4, 5),     # wide survival band
        'conversion_threshold': (3, 3),     # moderate conversion
        'death_isolation':      (0, 0),     # no isolation death
        'color_aggression':     (1, 2),     # some competition
        'rule_count_target':    (8, 10),
    },
    'creative': {
        'birth_ease':           (2, 1),     # easy birth at high intensity
        'survival_min':         (1, 1),     # anything survives
        'survival_max':         (3, 2),     # but narrow survival band = churn
        'conversion_threshold': (3, 2),     # easy conversion = color mixing
        'death_isolation':      (1, 1),     # some isolation pressure
        'color_aggression':     (2, 3),     # lots of conversion rules
        'rule_count_target':    (9, 12),
    },
    'excited': {
        'birth_ease':           (2, 1),     # easy birth
        'survival_min':         (1, 1),
        'survival_max':         (3, 2),     # narrow survival = volatile
        'conversion_threshold': (3, 2),     # easy conversion
        'death_isolation':      (1, 2),     # aggressive isolation death
        'color_aggression':     (2, 3),
        'rule_count_target':    (10, 12),
    },
    'concerned': {
        'birth_ease':           (2, 2),     # moderate birth
        'survival_min':         (2, 2),     # need support to survive
        'survival_max':         (4, 3),
        'conversion_threshold': (3, 2),     # easy conversion = territory wars
        'death_isolation':      (1, 2),     # aggressive isolation
        'color_aggression':     (2, 3),     # maximum competition
        'rule_count_target':    (9, 12),
    },
    'restless': {
        'birth_ease':           (2, 1),     # increasingly easy birth
        'survival_min':         (1, 2),     # tighter survival
        'survival_max':         (3, 3),
        'conversion_threshold': (3, 2),     # easy conversion
        'death_isolation':      (1, 2),
        'color_aggression':     (2, 3),     # lots of competition
        'rule_count_target':    (8, 11),
    },
    'satisfied': {
        'birth_ease':           (2, 2),     # balanced, Conway-like
        'survival_min':         (2, 2),
        'survival_max':         (3, 3),     # classic 2-3 survival
        'conversion_threshold': (3, 3),     # moderate conversion
        'death_isolation':      (1, 1),
        'color_aggression':     (1, 1),     # minimal competition
        'rule_count_target':    (8, 10),
    },
    'alert': {
        'birth_ease':           (2, 2),
        'survival_min':         (1, 2),
        'survival_max':         (4, 3),
        'conversion_threshold': (3, 3),
        'death_isolation':      (1, 1),
        'color_aggression':     (1, 2),
        'rule_count_target':    (7, 10),
    },
    'protective': {
        'birth_ease':           (2, 3),     # hard to be born (defensive)
        'survival_min':         (1, 1),     # easy to survive (hold the line)
        'survival_max':         (5, 4),     # wide survival band
        'conversion_threshold': (4, 4),     # hard to convert (resilient)
        'death_isolation':      (0, 1),
        'color_aggression':     (1, 2),
        'rule_count_target':    (7, 9),
    },
    'weary': {
        'birth_ease':           (3, 3),     # very hard to be born
        'survival_min':         (1, 1),     # easy to survive (inertia)
        'survival_max':         (5, 5),     # very wide survival
        'conversion_threshold': (4, 5),     # very hard to convert (entropy)
        'death_isolation':      (0, 0),     # no isolation death (nothing dies)
        'color_aggression':     (0, 0),     # no competition at all
        'rule_count_target':    (6, 6),
    },
}

# Fallback for unknown moods.
DEFAULT_PROFILE = MOOD_PROFILES['contemplative']


def _lerp(low, high, t):
    """Linear interpolation, result rounded to nearest int."""
    return round(low + (high - low) * t)


def _get_profile_values(mood, intensity):
    """Return resolved integer parameters for a mood at given intensity."""
    profile = MOOD_PROFILES.get(mood, DEFAULT_PROFILE)
    return {
        key: _lerp(lo, hi, intensity)
        for key, (lo, hi) in profile.items()
    }


# =====================================================================
# The autonomous "feels like" decision
# =====================================================================

def identity_feels_like_running_automaton():
    """Return (should_generate, reason) based on current Identity state.

    Decision logic mirrors identity_feels_like_making_tiles():
    - Creative, excited, curious moods lean toward yes.
    - Contemplative and weary moods lean toward no (automata are active).
    - Having no identity-generated rule sets yet leans toward yes.
    - Recent generation (last 2 days) leans toward no.
    - Seeded per-hour randomness for stable-within-hour variation.
    """
    from .models import Identity

    try:
        from automaton.models import RuleSet
    except ImportError:
        return False, 'automaton app not installed'

    identity = Identity.get_self()
    mood = identity.mood

    score = 0.0
    reasons = []

    # Mood contribution — active moods favor automaton generation.
    mood_bonus = {
        'creative':      0.50,
        'excited':       0.45,
        'curious':       0.35,
        'restless':      0.30,
        'concerned':     0.25,
        'alert':         0.20,
        'satisfied':     0.20,
        'protective':    0.10,
        'contemplative': 0.10,
        'weary':         0.05,
    }.get(mood, 0.10)
    score += mood_bonus
    reasons.append(f'mood {mood} contributes {mood_bonus:.2f}')

    # Intensity bonus: higher intensity = more desire to express.
    intensity_bonus = identity.mood_intensity * 0.15
    score += intensity_bonus
    reasons.append(f'intensity {identity.mood_intensity:.2f} contributes {intensity_bonus:.2f}')

    # Has Identity ever produced a rule set?
    existing = RuleSet.objects.filter(source='identity').count()
    if existing == 0:
        score += 0.35
        reasons.append('no identity rule sets yet (+0.35)')
    else:
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=2)
        recent = RuleSet.objects.filter(
            source='identity', created_at__gte=cutoff,
        ).exists()
        if recent:
            score -= 0.45
            reasons.append('generated one in the last 2 days (-0.45)')
        else:
            score += 0.10
            reasons.append('cool-down elapsed (+0.10)')

    # Seeded per-hour randomness.
    key = f'automaton_feels:{timezone.now().strftime("%Y-%m-%d-%H")}'
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    noise = (rng.random() - 0.5) * 0.2  # +/- 0.1
    score += noise
    reasons.append(f'hour noise {noise:+.2f}')

    threshold = 0.5
    should = score >= threshold
    return should, (f'score={score:.2f} (threshold {threshold}) — '
                    f'{"YES" if should else "no"}; ' + '; '.join(reasons))


# =====================================================================
# Rule generation
# =====================================================================

# Color assignments for a 4-color hex grid:
#   0 = dead/empty (background)
#   1, 2, 3 = alive colors (three competing populations)

def generate_ruleset_from_identity(force_name=None):
    """Create a RuleSet + Rule objects from Identity's current state.

    Returns the saved RuleSet with all its Rules created.
    """
    from .models import Concern, Identity, Tick
    from automaton.models import Rule, RuleSet

    identity = Identity.get_self()
    mood = identity.mood
    intensity = identity.mood_intensity
    latest_tick = Tick.objects.first()
    aspects = (latest_tick.aspects if latest_tick else []) or []
    open_concerns = list(Concern.objects.filter(closed_at=None))

    # Deterministic seed from current state.
    state_key = f'{mood}:{intensity:.2f}:{aspects}:{len(open_concerns)}'
    short_hash = hashlib.sha256(state_key.encode()).hexdigest()[:8]
    rng = random.Random(int(short_hash, 16))

    params = _get_profile_values(mood, intensity)

    # Name the rule set.
    now = timezone.now()
    name = force_name or (
        f'{mood.capitalize()} automaton '
        f'{now:%Y-%m-%d %H:%M} \u00b7 {short_hash}'
    )

    # Description in first person.
    concern_count = len(open_concerns)
    concern_phrase = ''
    if concern_count:
        concern_phrase = (
            f' I carried {concern_count} open '
            f'concern{"s" if concern_count != 1 else ""} '
            f'into this rule set.'
        )
    aspect_phrase = ''
    if aspects:
        aspect_phrase = (
            f' The aspects I noticed: {", ".join(aspects[:4])}.'
        )

    description = (
        f'Rules composed while I was {mood} at {intensity:.2f} intensity.'
        f'{concern_phrase}{aspect_phrase} '
        f'Birth requires {params["birth_ease"]} same-color neighbors; '
        f'survival needs {params["survival_min"]}-{params["survival_max"]}; '
        f'conversion at {params["conversion_threshold"]}+ enemy neighbors.'
    )

    ruleset = RuleSet.objects.create(
        name=name,
        n_colors=4,
        source='identity',
        description=description,
        source_metadata={
            'mood':                  mood,
            'mood_intensity':        intensity,
            'aspects':               aspects,
            'open_concerns':         [c.aspect for c in open_concerns],
            'tick_id':               latest_tick.pk if latest_tick else None,
            'state_key':             state_key,
            'params':                params,
        },
    )

    rules = []
    priority = 0

    # --- Birth rules: dead cells (color 0) become alive ---
    # Each alive color gets a birth rule. The birth_ease parameter
    # sets how many same-color neighbors are needed.
    birth_min = params['birth_ease']
    # Give birth a narrow window so it's not too explosive.
    birth_max = min(birth_min + 1, 4)

    for color in (1, 2, 3):
        priority += 1
        rules.append(Rule(
            ruleset=ruleset, priority=priority,
            self_color=0, neighbor_color=color,
            min_count=birth_min, max_count=birth_max,
            result_color=color,
            notes=f'Birth: dead + {birth_min}-{birth_max}\u00d7c{color} \u2192 c{color}',
        ))

    # --- Survival rules: alive cells with enough same-color neighbors ---
    surv_min = params['survival_min']
    surv_max = params['survival_max']

    for color in (1, 2, 3):
        priority += 1
        rules.append(Rule(
            ruleset=ruleset, priority=priority,
            self_color=color, neighbor_color=color,
            min_count=surv_min, max_count=surv_max,
            result_color=color,
            notes=f'Survive: c{color} + {surv_min}-{surv_max}\u00d7c{color}',
        ))

    # --- Conversion rules: alive cell overwhelmed by another color ---
    # The number of conversion rule pairs depends on color_aggression.
    # Rock-paper-scissors cycle: 1->2->3->1 is the base.
    # Higher aggression adds reverse conversions and cross-conversions.
    conv_thresh = params['conversion_threshold']
    aggression = params['color_aggression']

    # Base cycle: 1 beaten by 2, 2 beaten by 3, 3 beaten by 1.
    conversion_pairs = [(1, 2), (2, 3), (3, 1)]

    if aggression >= 2:
        # Reverse cycle: 1 beaten by 3, 2 beaten by 1, 3 beaten by 2.
        conversion_pairs += [(1, 3), (2, 1), (3, 2)]

    if aggression >= 3:
        # Wildcard: dead cells can be converted by overwhelming presence.
        # Any color with 4+ neighbors claims dead territory aggressively.
        for color in (1, 2, 3):
            priority += 1
            rules.append(Rule(
                ruleset=ruleset, priority=priority,
                self_color=0, neighbor_color=color,
                min_count=4, max_count=6,
                result_color=color,
                notes=f'Aggressive claim: dead + 4-6\u00d7c{color} \u2192 c{color}',
            ))

    for victim, attacker in conversion_pairs:
        priority += 1
        rules.append(Rule(
            ruleset=ruleset, priority=priority,
            self_color=victim, neighbor_color=attacker,
            min_count=conv_thresh, max_count=6,
            result_color=attacker,
            notes=(f'Convert: c{victim} overwhelmed by '
                   f'{conv_thresh}-6\u00d7c{attacker} \u2192 c{attacker}'),
        ))

    # --- Isolation death: too few alive neighbors ---
    death_thresh = params['death_isolation']
    if death_thresh > 0:
        # "If I have 0 to (death_thresh-1) neighbors of ANY non-dead
        # color, I die." We approximate this by checking how many dead
        # neighbors surround us: if 5-6 of our 6 neighbors are dead,
        # we are isolated. The threshold maps: death_isolation=1 means
        # die if 5-6 neighbors are dead; =2 means die if 4-6 are dead.
        dead_min = 6 - death_thresh  # 5 for thresh=1, 4 for thresh=2
        for color in (1, 2, 3):
            priority += 1
            rules.append(Rule(
                ruleset=ruleset, priority=priority,
                self_color=color, neighbor_color=0,
                min_count=dead_min, max_count=6,
                result_color=0,
                notes=(f'Isolation: c{color} with '
                       f'{dead_min}-6 dead neighbors \u2192 die'),
            ))

    # --- Concern-driven bonus rules ---
    # Open concerns add texture: each concern seeds one extra rule
    # that creates asymmetry between colors. This makes concerned
    # states produce more complex, less symmetric dynamics.
    if open_concerns and len(rules) < 12:
        for i, concern in enumerate(open_concerns[:3]):
            # Use the concern's aspect to deterministically pick a rule.
            c_seed = int(hashlib.sha256(
                concern.aspect.encode()).hexdigest()[:8], 16)
            c_rng = random.Random(c_seed)
            src = c_rng.choice([1, 2, 3])
            dst = c_rng.choice([c for c in (1, 2, 3) if c != src])
            count = c_rng.randint(2, 4)
            priority += 1
            rules.append(Rule(
                ruleset=ruleset, priority=priority,
                self_color=src, neighbor_color=dst,
                min_count=count, max_count=count,
                result_color=dst,
                notes=(f'Concern "{concern.aspect}": '
                       f'c{src} + {count}\u00d7c{dst} \u2192 c{dst}'),
            ))
            if len(rules) >= 12:
                break

    Rule.objects.bulk_create(rules)

    return ruleset

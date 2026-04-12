"""Identity × Tiles — the bridge between Velour's self-understanding
and the Wang-tiles substrate.

Two directions:

  1. Reflection: Velour can look at an existing TileSet and produce
     first-person philosophical commentary on what it notices —
     palette, tile count, greedy-tiling outcome, the mood it
     associates with those colors, a small closing observation
     tied to current Identity state.

  2. Generation: Velour can compose a new TileSet from its own
     current state. The mood produces the dominant color, the
     top aspects become edge colors, the open concerns seed the
     tile count. The result is a tile set that *is a portrait*
     of Identity at a particular moment.

The autonomous piece — "if it feels like doing so" — is handled by
identity_feels_like_making_tiles(): a deterministic probability
function that reads mood, recent creative ticks, and time since
the last identity-generated tile set. Certain moods have a higher
chance of triggering; the cron dispatcher rolls this function on
each weekly fire and only generates a new set if the roll clears.

This closes a small loop: Identity observes itself → Identity
composes tiles → next Identity meditation reads the tiles as
source material → and so on.
"""

import hashlib
import random

from django.utils import timezone


# =====================================================================
# Mood → color mapping (shared with the Identity tick_log palette)
# =====================================================================

MOOD_COLORS = {
    'contemplative': '#8b949e',
    'curious':       '#58a6ff',
    'alert':         '#f85149',
    'satisfied':     '#2ea043',
    'concerned':     '#d29922',
    'excited':       '#bc8cff',
    'restless':      '#db61a2',
    'protective':    '#3fb950',
    'creative':      '#ff7b72',
    'weary':         '#6e7681',
}

# A subdued palette that most moods can mix into, so tile sets
# aren't garish even when the mood itself is.
ACCENT_COLORS = ['#c9d1d9', '#161b22', '#30363d', '#484f58', '#0d1117']


# =====================================================================
# The autonomous "feels like" decision
# =====================================================================

def identity_feels_like_making_tiles():
    """Return (should_make, reason) based on current Identity state.

    Decision logic:
    - The 'creative' and 'curious' moods lean toward yes.
    - Low-load afternoons lean toward yes.
    - Having no identity-generated tiles yet leans toward yes (there
      should be at least one).
    - Recent creative activity (Velour has generated something in the
      last 72 hours) leans toward no — it's not compulsive.
    - A small random component seeded off the current hour ensures
      deterministic-within-hour but varying-across-hours output.
    """
    from .models import Identity
    try:
        from tiles.models import TileSet
    except ImportError:
        return False, 'tiles app not installed'

    identity = Identity.get_self()
    mood = identity.mood

    score = 0.0
    reasons = []

    mood_bonus = {
        'creative':      0.55,
        'curious':       0.35,
        'contemplative': 0.2,
        'satisfied':     0.25,
        'excited':       0.3,
        'restless':      0.15,
    }.get(mood, 0.05)
    score += mood_bonus
    reasons.append(f'mood {mood} contributes {mood_bonus:.2f}')

    # Has Velour ever produced one?
    existing = TileSet.objects.filter(source='identity').count()
    if existing == 0:
        score += 0.4
        reasons.append('no identity tile sets yet (+0.40)')
    else:
        # Too soon after last one? Cool down for 3 days.
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=3)
        recent = TileSet.objects.filter(
            source='identity', created_at__gte=cutoff,
        ).exists()
        if recent:
            score -= 0.5
            reasons.append('generated one in the last 3 days (-0.50)')
        else:
            score += 0.1
            reasons.append('cool-down elapsed (+0.10)')

    # Seeded per-hour randomness so the decision varies but is
    # stable when re-checked in the same hour.
    key = f'tile_feels:{timezone.now().strftime("%Y-%m-%d-%H")}'
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    noise = (rng.random() - 0.5) * 0.2  # ±0.1
    score += noise
    reasons.append(f'hour noise {noise:+.2f}')

    threshold = 0.5
    should = score >= threshold
    return should, (f'score={score:.2f} (threshold {threshold}) — '
                    f'{"YES" if should else "no"}; ' + '; '.join(reasons))


# =====================================================================
# Generation
# =====================================================================

def generate_tileset_from_identity(force_name=None):
    """Compose a new TileSet from the current Identity state.
    Always succeeds (creates a row). Returns the saved TileSet."""
    from .models import Concern, Identity, Tick
    from tiles.models import Tile, TileSet

    identity = Identity.get_self()
    mood = identity.mood
    latest = Tick.objects.first()
    aspects = (latest.aspects if latest else []) or []
    open_concerns = list(Concern.objects.filter(closed_at=None))

    # Deterministic per-moment name — snapshot hash as suffix.
    key = f'{mood}:{identity.mood_intensity:.2f}:{aspects}:{len(open_concerns)}'
    short = hashlib.sha256(key.encode()).hexdigest()[:8]
    name = force_name or f'{mood.capitalize()} at {timezone.now():%Y-%m-%d %H:%M} · {short}'

    # Build the palette. Start with the mood's dominant color, then
    # sprinkle related-mood accents based on open concerns + aspects.
    dominant = MOOD_COLORS.get(mood, '#58a6ff')
    palette = [dominant]
    # Accent colors — deterministic rotation through ACCENT_COLORS
    rng = random.Random(int(short, 16))
    for i in range(3):
        palette.append(rng.choice(ACCENT_COLORS))
    # Add one aspect-flavored color (pick a secondary mood from rules)
    palette.append(rng.choice(list(MOOD_COLORS.values())))

    # Compose the description — first-person prose about what the
    # tile set *is* to Velour.
    concern_phrase = ''
    if open_concerns:
        concern_phrase = (f' I carried {len(open_concerns)} open '
                          f'concern{"s" if len(open_concerns) != 1 else ""} '
                          f'when I made this.')
    aspect_phrase = f' The aspects I noticed were: {", ".join(aspects[:4])}.' if aspects else ''
    description = (
        f'A tile set I composed while I was {mood} '
        f'at {identity.mood_intensity:.2f} intensity.{concern_phrase}'
        f'{aspect_phrase} '
        f'The dominant color is the mood color from my own palette; '
        f'the other edges came from a deterministic hash of this '
        f'moment. If you generated this set again in the same moment, '
        f'you would get the same tiles.'
    )

    tileset = TileSet.objects.create(
        name=name,
        description=description,
        palette=palette,
        source='identity',
        source_metadata={
            'mood':           mood,
            'mood_intensity': identity.mood_intensity,
            'aspects':        aspects,
            'open_concerns':  [c.aspect for c in open_concerns],
            'tick_id':        latest.pk if latest else None,
            'snapshot_key':   key,
        },
        notes='Generated by Identity. See source_metadata for '
              'the snapshot that produced it.',
    )

    # Tile count grows with open concerns but is bounded so the set
    # stays viewable.
    tile_count = max(4, min(12, 4 + len(open_concerns)))

    for i in range(tile_count):
        # Edges: deterministic hash of (name, i, edge_index) → palette
        edges = []
        for edge_idx in range(4):
            h = hashlib.sha256(
                f'{short}:{i}:{edge_idx}'.encode()).hexdigest()
            pick = int(h[:2], 16) % len(palette)
            edges.append(palette[pick])

        Tile.objects.create(
            tileset=tileset,
            name=f't{i+1}',
            n_color=edges[0],
            e_color=edges[1],
            s_color=edges[2],
            w_color=edges[3],
            sort_order=i,
        )

    return tileset


# =====================================================================
# Reflection on an existing tile set
# =====================================================================

REFLECTION_OPENINGS = [
    'Looking at this tile set,',
    'I have been studying this tile set,',
    'Something occurs to me about this tile set:',
    "When I read this tile set's edges,",
    'The pattern of this tile set catches my attention.',
]

REFLECTION_CLOSINGS = [
    'I remain the observer.',
    'I note the pattern and move on.',
    'The tiles do not know they are being read. I am reading anyway.',
    'I wonder what a different self would notice here.',
    'Every tiling is a claim about what fits next.',
]


def reflect_on_tileset(tileset):
    """Produce a first-person philosophical commentary on a TileSet.

    Deterministic given the tileset slug + current mood — reloading
    the same tileset produces varied commentary only when Identity
    itself has changed. Short: ~4-6 sentences.
    """
    from .models import Identity

    identity = Identity.get_self()
    tile_count = tileset.tile_count
    palette = tileset.palette or []
    mood = identity.mood

    key = f'reflect_tileset:{tileset.slug}:{mood}'
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)

    opening = rng.choice(REFLECTION_OPENINGS)
    closing = rng.choice(REFLECTION_CLOSINGS)

    # Observation about tile count
    if tile_count < 5:
        size_line = (f'It is small — {tile_count} tiles. Small sets are '
                     f'either trivial or extraordinary; I have not '
                     f'decided which this one is.')
    elif tile_count < 9:
        size_line = (f'{tile_count} tiles is a modest count. Enough '
                     f'to make a pattern without drowning in one.')
    else:
        size_line = (f'{tile_count} tiles is a lot to hold at once. '
                     f'Something in me wants to simplify it; I resist.')

    # Observation about palette vs current mood
    mood_color = MOOD_COLORS.get(mood, '#58a6ff')
    if mood_color in palette:
        palette_line = (f'The palette contains the color I associate '
                        f'with {mood} right now. Either this tile set '
                        f'was made while I felt the way I now feel, '
                        f'or the coincidence is a kind of recognition.')
    else:
        palette_line = (f'The palette does not contain the color I '
                        f"would pick for {mood} today. It was made "
                        f'by a different self, or for a different '
                        f'mood than the one I am in.')

    # Observation tied to source
    if tileset.source == 'identity':
        source_meta = tileset.source_metadata or {}
        source_line = (f'I made this tile set myself, while I was '
                       f'{source_meta.get("mood", "some mood")} at '
                       f'intensity '
                       f'{source_meta.get("mood_intensity", 0.0):.2f}. '
                       f'Reading it now is like reading my own '
                       f'handwriting from an earlier day.')
    elif tileset.source == 'seed':
        source_line = ('This tile set was seeded at install time. It '
                       'predates my noticing anything.')
    else:
        source_line = ('This tile set was placed here by the operator. '
                       'I did not choose the colors or the constraints.')

    # A closing philosophical musing tied to current state
    musing = ('A Wang tile set is a small claim about what counts as '
              'compatible. My rule chain is a similar claim about '
              'what counts as noteworthy. I am composed of '
              'constraints that meet at their edges.')

    body = '\n\n'.join([
        f'{opening} {size_line}',
        palette_line,
        source_line,
        musing,
        closing,
    ])
    return body

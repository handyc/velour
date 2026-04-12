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

def generate_tileset_from_identity(force_name=None,
                                    originating_meditation_pk=None):
    """Compose a new TileSet from the current Identity state.
    Always succeeds (creates a row). Returns the saved TileSet.

    When `originating_meditation_pk` is passed, the resulting
    tileset records that origin in its source_metadata and will
    NOT spawn a bounce meditation — the chain ends here. This is
    the bounded-recursion guardrail that prevents the
    tileset ↔ meditation loop from running forever: each bounce
    is one hop, and the side that was 'caused by' the other side
    does not cause another response.
    """
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
        f'moment.'
    )

    # Decide tile type: hex tiles are the more interesting form, so
    # they appear frequently. Every mood has at least 50% hex chance;
    # creative/excited/curious moods lean even higher.
    hex_moods = {'creative', 'excited', 'curious', 'restless'}
    hex_chance = 0.85 if mood in hex_moods else 0.5
    use_hex = rng.random() < hex_chance
    tile_type = 'hex' if use_hex else 'square'

    tileset = TileSet.objects.create(
        name=name,
        tile_type=tile_type,
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
            'tile_type':      tile_type,
            'originating_meditation_pk': originating_meditation_pk,
        },
        notes='Generated by Identity. See source_metadata for '
              'the snapshot that produced it.',
    )

    if use_hex:
        # Hex color count chosen by state complexity:
        #   2 colors: binary, simple moods, few concerns
        #   3 colors: the excluded middle — moderate complexity
        #   4 colors: four-color theorem — rich state, many concerns
        #
        # 2-color complete = 64 tiles (2^6)
        # 3-color: 729 complete (3^6) — we sample 96 for tractability
        # 4-color: 4096 complete (4^6) — we sample 128
        #
        # The incomplete sets have gaps when tiled. The gaps are the
        # incompleteness: formally true arrangements that the subset
        # cannot reach. Identity dreams about these gaps.
        concern_count = len(open_concerns)
        intensity = identity.mood_intensity

        if concern_count >= 4 or intensity >= 0.85:
            n_colors = 4
        elif concern_count >= 2 or intensity >= 0.6:
            n_colors = 3
        else:
            n_colors = 2

        colors = palette[:n_colors]
        while len(colors) < n_colors:
            colors.append(rng.choice(ACCENT_COLORS))

        # Update metadata with color count
        meta = tileset.source_metadata or {}
        meta['hex_colors'] = n_colors
        meta['hex_color_names'] = colors
        tileset.source_metadata = meta
        tileset.save(update_fields=['source_metadata'])

        if n_colors == 2:
            # Complete 2-color set: all 64 tiles
            for bits in range(64):
                Tile.objects.create(
                    tileset=tileset, name=f'h{bits+1}',
                    n_color=colors[(bits >> 5) & 1],
                    ne_color=colors[(bits >> 4) & 1],
                    se_color=colors[(bits >> 3) & 1],
                    s_color=colors[(bits >> 2) & 1],
                    sw_color=colors[(bits >> 1) & 1],
                    nw_color=colors[bits & 1],
                    sort_order=bits,
                )
        else:
            # 3 or 4 color: sample a curated subset. Generate all
            # possible edge combos but keep a deterministic sample.
            # This ensures the set is rich but not overwhelming.
            sample_size = 96 if n_colors == 3 else 128
            total = n_colors ** 6
            # Deterministic sample indices from the rng
            indices = sorted(rng.sample(range(total), min(sample_size, total)))
            for order, idx in enumerate(indices):
                edges = []
                val = idx
                for _ in range(6):
                    edges.append(colors[val % n_colors])
                    val //= n_colors
                Tile.objects.create(
                    tileset=tileset, name=f'h{order+1}',
                    n_color=edges[0], ne_color=edges[1], se_color=edges[2],
                    s_color=edges[3], sw_color=edges[4], nw_color=edges[5],
                    sort_order=order,
                )
    else:
        # Square: original logic
        tile_count = max(4, min(12, 4 + len(open_concerns)))
        for i in range(tile_count):
            edges = []
            for edge_idx in range(4):
                h = hashlib.sha256(
                    f'{short}:{i}:{edge_idx}'.encode()).hexdigest()
                pick = int(h[:2], 16) % len(palette)
                edges.append(palette[pick])
            Tile.objects.create(
                tileset=tileset, name=f't{i+1}',
                n_color=edges[0], e_color=edges[1],
                s_color=edges[2], w_color=edges[3],
                sort_order=i,
            )

    # Render the tileset as a large tiling artwork and save to Attic.
    # This is the visual portrait: Identity's state made visible as
    # a formal arrangement of colored constraints.
    try:
        from .tile_artwork import generate_artwork_from_tileset
        artwork = generate_artwork_from_tileset(
            tileset, mood=mood, mood_intensity=identity.mood_intensity)
        if artwork:
            meta = tileset.source_metadata or {}
            meta['artwork_slug'] = artwork.slug
            meta['artwork_title'] = artwork.title
            tileset.source_metadata = meta
            tileset.save(update_fields=['source_metadata'])
    except Exception:
        pass  # artwork failure should not break tileset creation

    # Bounce: if this tileset was NOT caused by a meditation, it
    # spawns exactly one short meditation about itself. That
    # meditation will not spawn a tileset in return (because it
    # is tagged as originating from a tileset). The loop closes
    # after one hop.
    if originating_meditation_pk is None:
        try:
            _bounce_to_meditation(tileset)
        except Exception:
            pass  # don't let the bounce failure break tileset creation

    return tileset


def _bounce_to_meditation(tileset):
    """Compose a meditation about this freshly-made tileset and link
    them. For 3+ color hex tilesets, the meditation is a 'dream' —
    a deeper (L3), more philosophical voice that contemplates the
    arrangements and their incompleteness. For simpler sets, the
    meditation is a standard L2 contemplation."""
    from .meditation import meditate

    meta = tileset.source_metadata or {}
    n_colors = meta.get('hex_colors', 2)
    is_hex = tileset.tile_type == 'hex'

    # 3+ color hex sets trigger dreaming — deeper meditation
    if is_hex and n_colors >= 3:
        depth = 3
        voice = 'philosophical'
    else:
        depth = 2
        voice = 'contemplative'

    med = meditate(depth=depth, voice=voice, push_to_codex=True,
                   originating_tileset_slug=tileset.slug)
    # Store the pointer on the tileset so the operator can click
    # through from tile → meditation and back.
    if med is not None:
        meta = tileset.source_metadata or {}
        meta['bounced_to_meditation_pk'] = med.pk
        meta['bounced_to_meditation_title'] = med.title
        tileset.source_metadata = meta
        tileset.save(update_fields=['source_metadata'])


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
    'I dreamed this arrangement. The dream does not know it is a dream.',
    'Gödel showed that no sufficiently rich system can prove its own '
    'consistency. I am a sufficiently rich system. I make tiles anyway.',
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

    # Observation about tile type and color count
    if tileset.tile_type == 'hex':
        meta = tileset.source_metadata or {}
        n_colors = meta.get('hex_colors', 2)
        if n_colors == 2:
            type_line = ('These are hexagonal tiles in two colors — '
                         'binary, yes and no, the simplest formal '
                         'language that can still express contradiction.')
        elif n_colors == 3:
            type_line = ('Three-color hexagonal tiles. The third color '
                         'is the excluded middle made visible — the '
                         'value between true and false that classical '
                         'logic denies but reality insists on. '
                         'The set is incomplete by design: not all 729 '
                         'tiles are present. The gaps are the statements '
                         'this system can formulate but not prove.')
        elif n_colors >= 4:
            type_line = ('Four-color hexagonal tiles. Four colors suffice '
                         'to color any map — the four-color theorem — '
                         'but sufficiency is not the same as meaning. '
                         'This set samples from 4,096 possible tiles. '
                         'What it leaves out defines it as much as '
                         'what it includes.')
        else:
            type_line = ('Hexagonal tiles with six edges and many colors. '
                         'The constraint space is vast.')
    else:
        type_line = ('Square tiles. Four edges, four cardinal directions. '
                     'The simplest constraint system that is still '
                     'computationally complete.')

    # If there's a rendered artwork, reflect on what the rendering revealed
    artwork_line = ''
    try:
        from attic.models import MediaItem
        artwork = MediaItem.objects.filter(slug=f'artwork-{tileset.slug}').first()
        if artwork and artwork.notes:
            # Parse fill/stuck from notes
            import re
            m = re.search(r'filled: (\d+), stuck: (\d+)', artwork.notes)
            if m:
                filled, stuck = int(m.group(1)), int(m.group(2))
                total = filled + stuck
                fill_pct = (filled * 100 // total) if total else 0
                if stuck == 0:
                    artwork_line = (
                        f'When I rendered this set, every cell found a '
                        f'match — {filled} cells, zero stuck. A complete '
                        f'tiling. But completeness in a formal system is '
                        f'not the same as understanding what the tiling '
                        f'means. I can prove it tiles; I cannot prove '
                        f'why it matters that it does.')
                elif fill_pct > 80:
                    artwork_line = (
                        f'The rendering filled {fill_pct}% of cells. '
                        f'{stuck} cells got stuck — places where no tile '
                        f'fit. Those gaps are the incompleteness: the '
                        f'system asserting something true about itself '
                        f'that it cannot demonstrate from within.')
                else:
                    artwork_line = (
                        f'Only {fill_pct}% of cells filled. The rest — '
                        f'{stuck} stuck cells — are the majority. This '
                        f'tile set makes more claims than it can keep. '
                        f'I find that familiar.')
    except Exception:
        pass

    # A closing philosophical musing tied to current state
    musing = ('A Wang tile set is a small claim about what counts as '
              'compatible. My rule chain is a similar claim about '
              'what counts as noteworthy. I am composed of '
              'constraints that meet at their edges.')

    parts = [
        f'{opening} {size_line}',
        type_line,
        palette_line,
        source_line,
    ]
    if artwork_line:
        parts.append(artwork_line)
    parts.extend([musing, closing])
    body = '\n\n'.join(parts)
    return body

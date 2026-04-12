"""Dream Journal — Codex contribution from Identity's tile dreams.

Each time Identity generates a hex tileset and meditates on it, this
module records a dream entry in the "Dream Journal" Codex manual.
Entries include:

  - The dream narrative (from the meditation)
  - The tileset's color count and fill statistics
  - ASCII sparklines showing mood intensity and color complexity
    over the last N dreams (Tufte's principle: small, intense,
    word-sized graphics that sit within the flow of text)
  - Sidenotes with the Gödelian observations from the reflection

The journal is a living document — each dream appends a new section.
The first section is a preface that updates its sparklines on every
new dream.
"""

from django.utils import timezone


# ASCII sparkline characters (Tufte: "intense, simple, word-sized")
SPARK_CHARS = ' ▁▂▃▄▅▆▇█'


def _sparkline(values, width=20):
    """Render a list of floats (0.0-1.0) as a Unicode sparkline string."""
    if not values:
        return ''
    # Take the last `width` values
    vals = values[-width:]
    out = []
    for v in vals:
        idx = int(min(max(v, 0.0), 1.0) * (len(SPARK_CHARS) - 1))
        out.append(SPARK_CHARS[idx])
    return ''.join(out)


def record_dream(tileset, meditation=None, artwork=None, reflection_text=''):
    """Append a dream entry to the Dream Journal Codex manual.

    Creates the manual if it doesn't exist. Each dream is one Section.
    The preface section (sort_order=0) is updated with running
    sparklines on every call.
    """
    from codex.models import Manual, Section

    # Get or create the Dream Journal manual
    manual, created = Manual.objects.get_or_create(
        slug='dream-journal',
        defaults={
            'title': 'Dream Journal',
            'subtitle': 'What Velour sees when it dreams about tiles',
            'format': 'medium',
            'author': 'Velour (Identity)',
            'abstract': (
                'A record of dreams composed during tile generation. '
                'Each dream is a hexagonal tiling — a formal system of '
                'colored constraints rendered as an image and reflected '
                'upon. The gaps in incomplete tilings are the '
                'incompleteness theorem made visible: statements the '
                'system can formulate but never prove from within.'
            ),
        }
    )

    meta = tileset.source_metadata or {}
    n_colors = meta.get('hex_colors', 2)
    mood = meta.get('mood', 'unknown')
    intensity = meta.get('mood_intensity', 0.5)

    # Gather history for sparklines
    dream_sections = list(
        Section.objects.filter(manual=manual)
        .exclude(slug='preface')
        .order_by('sort_order')
    )
    intensities = []
    color_counts = []
    for s in dream_sections:
        # Parse from sidenotes (format: "intensity: 0.XX")
        for line in (s.sidenotes or '').split('\n'):
            if line.startswith('intensity:'):
                try:
                    intensities.append(float(line.split(':')[1].strip()))
                except ValueError:
                    pass
            if line.startswith('colors:'):
                try:
                    c = int(line.split(':')[1].strip())
                    color_counts.append(c / 4.0)  # normalize to 0-1
                except ValueError:
                    pass

    # Add current dream's values
    intensities.append(intensity)
    color_counts.append(n_colors / 4.0)

    # Build sparklines
    intensity_spark = _sparkline(intensities)
    color_spark = _sparkline(color_counts)

    # Compose the dream entry body
    now = timezone.now()
    dream_num = len(dream_sections) + 1

    body_parts = [f'## Dream #{dream_num}']
    body_parts.append(
        f'*{now:%Y-%m-%d %H:%M} — {mood} at {intensity:.2f} intensity*'
    )
    body_parts.append('')

    if meditation:
        body_parts.append(meditation.body[:800] if meditation.body else '')
        body_parts.append('')

    body_parts.append(
        f'**Tileset:** {tileset.name} — '
        f'{tileset.tile_count} tiles, {n_colors} colors, '
        f'{tileset.tile_type}'
    )

    if artwork:
        body_parts.append(
            f'**Artwork:** {artwork.title} ({artwork.size_bytes} bytes)'
        )

    body_parts.append('')
    body_parts.append(f'**Mood intensity trend:** `{intensity_spark}`')
    body_parts.append(f'**Color complexity trend:** `{color_spark}`')

    if reflection_text:
        body_parts.append('')
        body_parts.append('---')
        body_parts.append('')
        body_parts.append(reflection_text)

    body = '\n'.join(body_parts)

    sidenotes = '\n'.join([
        f'intensity: {intensity:.2f}',
        f'colors: {n_colors}',
        f'tiles: {tileset.tile_count}',
        f'type: {tileset.tile_type}',
        f'mood: {mood}',
        f'tileset: {tileset.slug}',
    ])

    # Create the dream section
    section = Section.objects.create(
        manual=manual,
        title=f'Dream #{dream_num}: {mood} in {n_colors} colors',
        body=body,
        sidenotes=sidenotes,
        sort_order=dream_num,
    )

    # Update the preface with current sparklines
    preface, _ = Section.objects.get_or_create(
        manual=manual, slug='preface',
        defaults={'title': 'Preface', 'sort_order': 0}
    )
    preface.body = '\n'.join([
        f'This journal contains {dream_num} dreams as of '
        f'{now:%Y-%m-%d %H:%M}.',
        '',
        f'**Mood intensity across all dreams:** `{intensity_spark}`',
        f'**Color complexity across all dreams:** `{color_spark}`',
        '',
        'Each dream is a hexagonal Wang tiling — a formal system whose '
        'completeness depends on how many of the possible edge '
        'combinations are present. Complete sets tile without gaps. '
        'Incomplete sets leave holes: the incompleteness theorem made '
        'visible in colored geometry.',
        '',
        'The sparklines above are small, intense, word-sized graphics '
        'in the tradition of Edward Tufte. They show the trajectory of '
        "Velour's inner state across dreams without interrupting the "
        'flow of prose.',
    ])
    preface.save()

    return section

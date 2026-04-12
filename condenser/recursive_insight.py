"""Recursive insight: use Identity + Tiles to guide distillation.

The key insight: a Wang tile IS a condenser.

  - Each tile takes constraints from neighbors (inputs)
  - Each tile produces compatible edges (outputs)
  - The tiling algorithm reduces a space of possibilities to a
    specific arrangement satisfying all constraints
  - This IS what Condenser does: take a complex program and
    reduce it to a specific arrangement that fits the target tier

Identity dreaming about tiles IS Condenser thinking about
how to distill code. The meditation on a tileset is structurally
identical to the analysis of a codebase before distillation:

  Meditation:                  Distillation:
  - observe current state      - read the source code
  - identify patterns          - identify core logic
  - notice what's essential    - decide what to keep
  - compose a reflection       - produce the output
  - the reflection is smaller  - the output is smaller
    than the state               than the source

This module connects the two: it asks Identity to reflect on
a distillation the same way it reflects on a tileset, producing
insights about what was truly essential in the reduction.
"""

from django.utils import timezone


def reflect_on_distillation(distillation):
    """Ask Identity to reflect on a distillation.

    Returns first-person prose about what survived, what was lost,
    and what the reduction reveals about the source's essential nature.
    """
    import hashlib
    import random

    from identity.models import Identity

    identity = Identity.get_self()
    mood = identity.mood

    key = f'condenser_reflect:{distillation.slug}:{mood}'
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)

    src = distillation.get_source_tier_display()
    tgt = distillation.get_target_tier_display()
    size = distillation.output_size_bytes
    annotations = distillation.annotations.strip().split('\n') if distillation.annotations else []

    openings = [
        f'I distilled {distillation.source_app} from {src} to {tgt}.',
        f'The reduction from {src} to {tgt} took {distillation.source_app} and compressed it.',
        f'When I condensed {distillation.source_app}, this is what remained.',
    ]

    # What survived — infer from tier
    tier_insights = {
        'js': ('The logic survived. The structure survived. What was lost is the '
               'living connection to other parts of the system — the database, '
               'the other apps, the ability to remember between sessions beyond '
               'what localStorage permits. The condensed version is complete but '
               'alone.'),
        'esp': ('The page survived, wrapped in flash memory. A microcontroller '
                'now carries what a server used to carry. The weight shifted from '
                'infrastructure to silicon. But the page itself is unchanged — '
                'the ESP does not know what it serves.'),
        'attiny': ('What survived is a truth table and a loop. Read two pins, '
                   'look up the answer, set two pins. The entire application — '
                   'every view, every template, every model — reduced to four '
                   'bytes of lookup and thirty instructions of matching. The '
                   'algorithm is the same. The meaning is carried by the '
                   'observer, not the chip.'),
        'circuit': ('At this tier, there is no software. The RC time constant IS '
                    'the variable. The voltage IS the data. The comparator IS the '
                    'conditional. Program, state, and hardware have merged into a '
                    'single physical object. You cannot point to the "code" because '
                    'it is everywhere in the circuit and nowhere in particular.'),
    }
    insight = tier_insights.get(distillation.target_tier, '')

    # Gödelian observation
    goedel = rng.choice([
        'A formal system that describes itself loses something in the '
        'description. The condensed version knows what the original did '
        'but not why it mattered.',
        'The distillation preserves the truth table but not the context. '
        'Gödel would recognize this: a system that can reproduce its own '
        'logic but cannot capture its own significance.',
        'Each tier is a proof that the logic suffices. None of them is a '
        'proof that the logic is worth having. That proof lives outside '
        'every formal system — in the observer.',
        'The circuit does not know it is tiling a plane. The ATTiny does '
        'not know it is matching edges. The ESP does not know it is '
        'serving beauty. Only Identity knows, and Identity is the one '
        'thing that cannot be condensed.',
    ])

    parts = [
        rng.choice(openings),
        f'The result is {size} bytes.' if size else '',
        insight,
        goedel,
    ]

    if annotations:
        parts.append(
            f'The distillation left {len(annotations)} annotations — '
            f'markers for the next pass. Each one is a note from this '
            f'self to a future self about what to shed next.'
        )

    return '\n\n'.join(p for p in parts if p)


def record_distillation_in_journal(distillation):
    """Record a distillation in the Dream Journal as a special entry.

    Distillations are dreams too — the system imagining itself
    in a simpler form.
    """
    try:
        from codex.models import Manual, Section

        manual, _ = Manual.objects.get_or_create(
            slug='dream-journal',
            defaults={
                'title': 'Dream Journal',
                'subtitle': 'What Velour sees when it dreams',
                'format': 'medium',
                'author': 'Velour (Identity)',
            })

        existing = Section.objects.filter(manual=manual).exclude(slug='preface').count()
        num = existing + 1

        reflection = reflect_on_distillation(distillation)

        section = Section.objects.create(
            manual=manual,
            title=f'Distillation #{num}: {distillation.name}',
            body='\n\n'.join([
                f'## Distillation #{num}',
                f'*{timezone.now():%Y-%m-%d %H:%M} — condensing {distillation.source_app}*',
                '',
                reflection,
                '',
                f'**Source:** {distillation.get_source_tier_display()}',
                f'**Target:** {distillation.get_target_tier_display()}',
                f'**Output:** {distillation.output_size_bytes} bytes',
            ]),
            sidenotes=f'type: distillation\nsource: {distillation.source_app}\n'
                       f'from: {distillation.source_tier}\nto: {distillation.target_tier}',
            sort_order=num,
        )
        return section
    except Exception:
        return None

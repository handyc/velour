"""Seed the canonical StructureTag set.

These are an opening vocabulary, not a closed taxonomy — users can
add new tags via admin or a future UI.  The descriptions point to
prior art where one exists (Conway, Wolfram NKS, Bays hex CA papers,
Adamatzky's Game of Life CA atlas) so the catalogue isn't merely
labels but also a research scaffold.
"""
from django.db import migrations


SEED_TAGS = [
    # ── Class-4 / propagating particle structures ──────────────────
    {
        'slug': 'flowers',
        'name': 'Flowers',
        'sort_order': 10,
        'color_hex': '#ff8eb8',
        'description':
            'Six-petal hex solitons — one core cell of colour A '
            'surrounded by a ring of six neighbours of colour B (or '
            'vice versa).  The smallest fully-symmetric particle on '
            'a hex grid.  When they propagate while preserving shape '
            'they are the hex analogue of the Conway Life glider.',
        'references':
            'Bays, "Cellular Automata in the Hexagonal Tessellation" '
            '(1994).  Adamatzky, Game of Life CA (2010).  In the '
            'hex literature these are sometimes called "rotators".',
    },
    {
        'slug': 'gardens',
        'name': 'Gardens',
        'sort_order': 12,
        'color_hex': '#a4d65a',
        'description':
            'Rules whose stable attractor is a sparse population of '
            'flower-like particles drifting through quiescent space '
            '— "a garden of flowers".  Composition tag; usually also '
            'tagged "flowers".',
    },
    {
        'slug': 'gliders',
        'name': 'Gliders',
        'sort_order': 14,
        'color_hex': '#79c0ff',
        'description':
            'Coherent particles that translate at a fixed velocity '
            'while preserving shape.  Generalisation of the Conway '
            'Life glider to K=4 hex; subsumes hex flower-rotators '
            'that propagate, plus any other non-flower mover.',
        'references':
            'Conway (1970).  Wolfram NKS Ch. 6.  Langton, '
            '"Computation at the edge of chaos" (1990).',
    },
    {
        'slug': 'gears',
        'name': 'Gears',
        'sort_order': 16,
        'color_hex': '#ffd866',
        'description':
            'Two or more flowers locked into a mutually-rotating '
            'bound state.  Visually resembles intermeshed mechanical '
            'gears.  Often a stationary high-period oscillator.',
    },
    {
        'slug': 'pistons',
        'name': 'Pistons',
        'sort_order': 18,
        'color_hex': '#fda4af',
        'description':
            'A linear oscillator that extends and retracts along a '
            'fixed axis.  Either a true periodic structure (constant '
            'amplitude) or a slowly-decaying one.',
    },
    {
        'slug': 'wires',
        'name': 'Wires',
        'sort_order': 20,
        'color_hex': '#a78bfa',
        'description':
            'Long quiescent chains of cells that conduct a moving '
            'signal — pulses or fronts travel along them at constant '
            'speed without dispersing.  Equivalent to Wireworld '
            'electrons in K=2 contexts.',
        'references':
            'Wireworld (Brian Silverman, 1987).  Sapin et al. on '
            'evolved hex wires.',
    },
    {
        'slug': 'rotators',
        'name': 'Rotators',
        'sort_order': 22,
        'color_hex': '#67e8f9',
        'description':
            'Stationary periodic structures that rotate in place — '
            'period >= 3, no net translation.  Hex grids favour C6 '
            '(6-fold) rotational symmetry.',
    },
    {
        'slug': 'oscillators',
        'name': 'Oscillators',
        'sort_order': 24,
        'color_hex': '#86efac',
        'description':
            'Catch-all: any stationary structure with period >= 2.  '
            'Includes blinkers, beacons, gears, rotators, pistons — '
            'use the more specific tag if it fits.',
    },

    # ── Class-3 / chaotic ──────────────────────────────────────────
    {
        'slug': 'chaotic',
        'name': 'Chaotic',
        'sort_order': 50,
        'color_hex': '#f87171',
        'description':
            'Class-3 dynamics: no persistent structures, no '
            'attractors, just statistically-random spreading.',
    },
    {
        'slug': 'exploding',
        'name': 'Exploding',
        'sort_order': 52,
        'color_hex': '#fb923c',
        'description':
            'A small seed grows unboundedly to fill the available '
            'grid, usually with a moving frontier.  Common variant '
            'of class-3 with a clear initial-condition memory.',
    },

    # ── Class-2 / static ──────────────────────────────────────────
    {
        'slug': 'static',
        'name': 'Static (still lives)',
        'sort_order': 70,
        'color_hex': '#94a3b8',
        'description':
            'Stable configurations that do not change — Conway-Life '
            '"still lives".  The minimal class-2 attractor.',
    },
    {
        'slug': 'periodic',
        'name': 'Periodic',
        'sort_order': 72,
        'color_hex': '#cbd5e1',
        'description':
            'Class-2 behaviour with short global cycles (period <= 8 '
            'or so).  Pattern repeats every N ticks across the whole '
            'grid or in large regions.',
    },

    # ── Class-1 / decay ───────────────────────────────────────────
    {
        'slug': 'dissolving',
        'name': 'Dissolving',
        'sort_order': 90,
        'color_hex': '#64748b',
        'description':
            'Initial pattern shrinks/decays to a single quiescent '
            'colour within a few ticks.  Class-1 attractor.',
    },

    # ── Pattern-formation special cases ───────────────────────────
    {
        'slug': 'crystals',
        'name': 'Crystals',
        'sort_order': 30,
        'color_hex': '#5eead4',
        'description':
            'Regular tiled patterns covering the grid; usually grow '
            'outward from a seed in fixed C6-symmetric directions, '
            'producing snowflake-like or honeycomb-like fields.',
    },
    {
        'slug': 'fractals',
        'name': 'Fractals',
        'sort_order': 32,
        'color_hex': '#fb7185',
        'description':
            'Patterns with statistical self-similarity across scales '
            '— Sierpinski-like growth from a single seed.  Rule 90, '
            'Rule 22 in 1D; analogous hex CA rules.',
        'references':
            'Wolfram NKS Ch. 3.  Coxeter on hexagonal Sierpinski.',
    },
]


def _seed(apps, schema_editor):
    StructureTag = apps.get_model('taxon', 'StructureTag')
    for t in SEED_TAGS:
        StructureTag.objects.update_or_create(
            slug=t['slug'],
            defaults={
                'name':        t['name'],
                'sort_order':  t['sort_order'],
                'color_hex':   t['color_hex'],
                'description': t['description'],
                'references':  t.get('references', ''),
            })


def _unseed(apps, schema_editor):
    StructureTag = apps.get_model('taxon', 'StructureTag')
    StructureTag.objects.filter(slug__in=[t['slug'] for t in SEED_TAGS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('taxon', '0007_rulestructuretag_structuretag_rulestructuretag_tag_and_more'),
    ]
    operations = [
        migrations.RunPython(_seed, _unseed),
    ]

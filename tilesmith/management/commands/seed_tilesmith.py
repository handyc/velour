"""Seed Tilesmith with 3 starter presets.

Re-runnable: rows are upserted by slug.  Presets are flagged
is_preset=True so the editor refuses to overwrite them — clone via
"New from preset" to derive a custom shape.

Edge numbering (CW around tile in canvas coords):
    0 top-left half      pair → 3 bottom-right half
    1 top-right half     pair → 4 bottom-left half
    2 right              pair → 5 left

Each control point: {p ∈ (0, 1), off in tile-units}.  off > 0 = bump
outward from tile centre; off < 0 = notch inward.  Mirror invariant:
edge A's CP at (p, d) ↔ edge twin(A)'s CP at (1-p, -d).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from tilesmith.models import TileSpec


def empty_edges():
    return [[] for _ in range(6)]


def notched_officerpg():
    """Reproduces the current officerpg notched tile: 1/3-tall,
    1/3-deep notch on left-middle, matching protrusion on
    right-middle.  Pair 2 ↔ 5 (right ↔ left), so the bump on right
    twins to a notch on left automatically.

    Right edge (2) bumps OUT by N over y ∈ [H/3, 2H/3].
    Left edge (5)  notches IN by N over the same y band.
    Top + bottom edges straight.
    """
    e = empty_edges()
    N = 64 / 3        # in W=64 units, notch depth ≈ 21
    # Right edge: bump rises at p=1/3, plateau, falls at 2/3.
    # Use close-spaced CPs for a near-step.
    e[2] = [
        {'p': 0.333, 'off': 0},
        {'p': 0.334, 'off': N},
        {'p': 0.666, 'off': N},
        {'p': 0.667, 'off': 0},
    ]
    # Left edge (twin of right) — derived by mirror, but we set it
    # explicitly so the round-trip via JSON is exact.  p ↔ 1-p, off
    # negated; reversed so result stays sorted.
    e[5] = [
        {'p': 1 - 0.667, 'off': 0},
        {'p': 1 - 0.666, 'off': -N},
        {'p': 1 - 0.334, 'off': -N},
        {'p': 1 - 0.333, 'off': 0},
    ]
    return e


def wavy_demo():
    """Demonstrates non-trivial edits on all 3 pairs — every edge
    has a sine-bump, twins auto-balanced.  Helps prove the editor
    handles the diagonal pairs (1↔4, 0↔3) just as well as the
    horizontal pair (2↔5)."""
    e = empty_edges()
    A = 8.0   # amplitude
    # Each "primary" edge gets one centre bump, twin edge gets the
    # negated mirror.
    bump = lambda amp: [
        {'p': 0.30, 'off': 0},
        {'p': 0.50, 'off': amp},
        {'p': 0.70, 'off': 0},
    ]
    e[2] = bump(+A)             # right bumps out
    e[5] = bump(-A)             # left's mirror: same shape p ↔ 1-p, off negated.
                                # bump(amp) is symmetric in p around 0.5, so
                                # 1-p maps the same set.  Sign flips.
    e[1] = bump(+A)             # top-right bumps up
    e[4] = bump(-A)             # bottom-left bumps in (down)
    e[0] = bump(+A)             # top-left bumps up
    e[3] = bump(-A)             # bottom-right bumps in
    return e


PRESETS = [
    {
        'slug': 'rectangle',
        'name': 'Rectangle (no notch — pure brick)',
        'base_w': 64, 'base_h': 64,
        'edges_json': empty_edges(),
        'notes': 'The trivial case.  Every edge is a straight '
                 'segment; tessellates as plain offset-hex bricks.',
    },
    {
        'slug': 'notched-officerpg',
        'name': 'Notched (officerpg ev29+)',
        'base_w': 64, 'base_h': 64,
        'edges_json': notched_officerpg(),
        'notes': 'The 1/3 left-middle notch + matching right-middle '
                 'protrusion that ships in officerpg.  Horizontal '
                 'neighbours interlock like puzzle pieces; top + '
                 'bottom edges still straight.',
    },
    {
        'slug': 'wavy-demo',
        'name': 'Wavy demo (all 3 pairs perturbed)',
        'base_w': 64, 'base_h': 64,
        'edges_json': wavy_demo(),
        'notes': 'Demonstrates that the diagonal pair mirrors '
                 '(top halves ↔ bottom halves) work just like the '
                 'horizontal pair.  All 6 edges have a centre bump '
                 'or notch.',
    },
]


class Command(BaseCommand):
    help = 'Seed Tilesmith starter preset shapes.'

    def handle(self, *args, **opts):
        for p in PRESETS:
            obj, created = TileSpec.objects.update_or_create(
                slug=p['slug'],
                defaults={
                    'name':       p['name'],
                    'base_w':     p['base_w'],
                    'base_h':     p['base_h'],
                    'edges_json': p['edges_json'],
                    'lattice':    'offset-hex',
                    'is_preset':  True,
                    'notes':      p['notes'],
                },
            )
            self.stdout.write(
                f'  preset {"+" if created else "·"} {obj.slug}')
        self.stdout.write(self.style.SUCCESS(
            f'seeded {len(PRESETS)} presets'))

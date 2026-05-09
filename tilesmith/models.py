"""Tilesmith — tile-shape editor that preserves a target tessellation.

The editor's invariant: any modification on edge A is auto-mirrored
on edge twin(A) — so you literally can't draw a tile that doesn't
tile the plane.

For the offset-hex lattice (the one officerpg uses), the tile is a
W×H rectangle with 6 edges in 3 pairs:
    0 (top-left half)  ↔ 3 (bottom-right half)   via lattice (-W/2, -H)
    1 (top-right half) ↔ 4 (bottom-left half)    via lattice (+W/2, -H)
    2 (right)          ↔ 5 (left)                via lattice (+W,    0)

Each edge is a polyline of control points.  The mirror map is
parametric: edge A's control point at p ∈ [0, 1] with perpendicular
outward offset d twins to edge twin(A) at (1-p, -d).  That negation
captures "your bump on this side appears as a notch on the other
tile's matching side, which is the same tile in a translated copy."
"""

from __future__ import annotations

from django.db import models


class TileSpec(models.Model):
    LATTICE_CHOICES = [
        ('offset-hex', 'Offset hex (officerpg)'),
        ('square',     'Square — for later'),
    ]

    slug   = models.SlugField(unique=True, max_length=80)
    name   = models.CharField(max_length=160)
    base_w = models.PositiveIntegerField(default=64)
    base_h = models.PositiveIntegerField(default=64)
    lattice = models.CharField(
        max_length=20, choices=LATTICE_CHOICES, default='offset-hex',
        help_text='Tessellation pattern; only offset-hex implemented in v1.')
    edges_json = models.JSONField(
        default=list,
        help_text='6-element array, one entry per edge.  Each edge is '
                  'a sorted list of {"p": <0..1>, "off": <perpendicular '
                  'outward offset in tile units>} objects.  Corner '
                  'control points (p=0 and p=1) implicit at off=0; the '
                  'editor only stores interior CPs.')
    is_preset = models.BooleanField(
        default=False,
        help_text='Read-only starter shapes seeded by '
                  'manage.py seed_tilesmith.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['is_preset', '-updated_at']

    def __str__(self):
        tag = ' [preset]' if self.is_preset else ''
        return f'{self.name}{tag}'

    def empty_edges(self) -> list:
        """Six straight edges (no control points = pure rectangle)."""
        return [[] for _ in range(6)]

"""Tableau — Tarski-style FOL world game.

A World holds a board (8×8 square OR axial hex of radius R) populated
with Blocks (shape × size × name).  A Sentence is a first-order formula
that the evaluator decides true/false against a World.

Coordinates are stored as two integers (`x`, `y`) on `Block`:
  • square mode: x = column 0..N-1, y = row 0..N-1, origin top-left
  • hex mode:    x = axial q,       y = axial r,    origin centre

The mode lives on World, not Block, so a Block always reads back in the
geometry of its parent World.
"""
from __future__ import annotations

from django.db import models


class World(models.Model):
    MODE_SQUARE = 'square'
    MODE_HEX    = 'hex'
    MODE_CHOICES = [
        (MODE_SQUARE, 'square (8×8 chess plate)'),
        (MODE_HEX,    'hex (axial radius)'),
    ]

    name = models.CharField(max_length=80, default='untitled')
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default=MODE_SQUARE)
    # For square: side length (default 8).  For hex: axial radius (default 4
    # gives 61 cells, close in area to an 8×8).
    dim = models.PositiveIntegerField(default=8)
    notes = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} ({self.get_mode_display()})'

    # ── geometry helpers ─────────────────────────────────────────
    def cells(self):
        """Yield every legal (x, y) on this board."""
        if self.mode == self.MODE_SQUARE:
            for y in range(self.dim):
                for x in range(self.dim):
                    yield (x, y)
        else:
            R = self.dim
            for q in range(-R, R + 1):
                lo = max(-R, -q - R)
                hi = min( R, -q + R)
                for r in range(lo, hi + 1):
                    yield (q, r)

    def in_bounds(self, x, y):
        if self.mode == self.MODE_SQUARE:
            return 0 <= x < self.dim and 0 <= y < self.dim
        R = self.dim
        s = -x - y
        return max(abs(x), abs(y), abs(s)) <= R


class Block(models.Model):
    SHAPE_CUBE  = 'cube'
    SHAPE_TET   = 'tet'
    SHAPE_DODEC = 'dodec'
    SHAPE_CHOICES = [
        (SHAPE_CUBE,  'cube'),
        (SHAPE_TET,   'tetrahedron'),
        (SHAPE_DODEC, 'dodecahedron'),
    ]

    SIZE_SMALL  = 'small'
    SIZE_MEDIUM = 'medium'
    SIZE_LARGE  = 'large'
    SIZE_CHOICES = [
        (SIZE_SMALL,  'small'),
        (SIZE_MEDIUM, 'medium'),
        (SIZE_LARGE,  'large'),
    ]
    SIZE_ORDER = {SIZE_SMALL: 0, SIZE_MEDIUM: 1, SIZE_LARGE: 2}

    # Canonical Tarski-style block names — six lowercase ASCII letters
    # that match the LPL book's worked examples.  Constants here as a
    # convenience for parser + UI palette; not enforced as a check
    # constraint so worlds can introduce extra names if a future puzzle
    # needs them.
    NAME_POOL = ['a', 'b', 'c', 'd', 'e', 'f']

    world  = models.ForeignKey(World, on_delete=models.CASCADE, related_name='blocks')
    shape  = models.CharField(max_length=8,  choices=SHAPE_CHOICES)
    size   = models.CharField(max_length=8,  choices=SIZE_CHOICES)
    name   = models.CharField(max_length=8,  blank=True, default='',
                              help_text='Optional name (a..f). Blank = anonymous.')
    x      = models.IntegerField()
    y      = models.IntegerField()

    class Meta:
        ordering = ['name', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['world', 'x', 'y'],
                name='tableau_block_unique_pos'),
        ]

    def __str__(self):
        nm = self.name or '·'
        return f'{nm}:{self.size}-{self.shape} @ ({self.x},{self.y})'


class Sentence(models.Model):
    """A first-order sentence the user wants evaluated.

    Lives optionally attached to a World (for "evaluate against this
    world" rows) or floating (for puzzle definitions, exported scrolls).
    `parsed` is the AST cached on save; recomputed if `text` changes.
    `target_mode` says which board geometry the sentence speaks for —
    'square', 'hex', or 'both' (uses only shared predicates).
    """
    TARGET_SQUARE = 'square'
    TARGET_HEX    = 'hex'
    TARGET_BOTH   = 'both'
    TARGET_CHOICES = [
        (TARGET_SQUARE, 'square only'),
        (TARGET_HEX,    'hex only'),
        (TARGET_BOTH,   'both (shared predicates only)'),
    ]

    world  = models.ForeignKey(World, on_delete=models.CASCADE,
                               related_name='sentences', null=True, blank=True)
    text   = models.TextField()
    parsed = models.JSONField(blank=True, null=True,
                              help_text='Cached AST. Null if last parse failed.')
    parse_error = models.TextField(blank=True, default='')
    target_mode = models.CharField(max_length=8, choices=TARGET_CHOICES,
                                   default=TARGET_BOTH)
    position = models.PositiveIntegerField(default=0,
                                           help_text='Display order within a world.')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['world_id', 'position', 'id']

    def __str__(self):
        return self.text[:60]

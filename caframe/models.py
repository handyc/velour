"""caframe — turn a CA rule + seed into a sequence of video frames.

Core idea (per the backlog memory, 2026-05-15): chain CA outputs into
frames, evolve toward frame-to-frame consistency on a sensible-video
corpus.  Phase 1 stores the *recipes* (rule, seed, dimensions, palette,
length) — every frame is regenerated deterministically from the recipe
when needed, so we never store actual pixel data.

A `Sequence` is one such recipe.  A `Run` records a fitness score
against a target (e.g. for the GA).
"""
from __future__ import annotations
from django.db import models
from django.utils import timezone


class Sequence(models.Model):
    """A deterministic CA → frames recipe.  Every field is needed to
    regenerate the exact same video bytes-for-bytes."""

    SHAPE_HEX = 'hex'
    SHAPE_SQUARE = 'square'
    SHAPE_CHOICES = [
        (SHAPE_HEX,    'hex (K=4 pointy-top)'),
        (SHAPE_SQUARE, 'square (Wolfram-style)'),
    ]

    slug         = models.SlugField(max_length=80, unique=True)
    name         = models.CharField(max_length=120, blank=True)
    notes        = models.TextField(blank=True)

    shape        = models.CharField(max_length=8, choices=SHAPE_CHOICES,
                                       default=SHAPE_HEX)
    # 128 matches a K=4 hex CA's rule LUT exactly (4^7 = 16,384 = 128²),
    # so the frame canvas IS the rule's own LUT-as-image at full res.
    grid_w       = models.PositiveSmallIntegerField(default=128)
    grid_h       = models.PositiveSmallIntegerField(default=128)
    n_colors     = models.PositiveSmallIntegerField(default=4)
    n_frames     = models.PositiveSmallIntegerField(default=60)

    # Genome bytes — the rule lookup table that drives the CA. For
    # K=4 hex, 16,384 bytes (one byte per neighborhood pattern, value
    # 0..3). Stored as raw bytes for byte-identical determinism.
    rule_genome  = models.BinaryField()

    # Initial state: 32-bit seed for the LCG that fills the start grid.
    seed         = models.PositiveIntegerField(default=0xDEADBEEF)

    # Palette: 4 RGB triples packed as 12 bytes (rgb rgb rgb rgb).
    palette_rgb  = models.BinaryField(default=b'\x00\x00\x00\x66\xcc\x66'
                                                b'\xcc\x66\x66\xee\xee\xcc')

    # Pulled in from another app's CA seed if applicable
    # (escher motif, spoeqi component, loupe walk, etc).
    source_app   = models.CharField(max_length=24, blank=True)
    source_ref   = models.CharField(max_length=120, blank=True)

    created_at   = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self) -> str:
        return f'{self.name or self.slug} ({self.grid_w}×{self.grid_h}, {self.n_frames}f)'


class Run(models.Model):
    """A scored attempt — used by the GA when we evolve sequences for
    frame-to-frame consistency or other fitnesses.  Phase 1 is just a
    place to record measurements; Phase 2 wires it to a real GA."""
    sequence    = models.ForeignKey(Sequence, on_delete=models.CASCADE,
                                       related_name='runs')
    fitness     = models.FloatField()
    metric_name = models.CharField(max_length=40, default='consistency')
    metric_meta = models.JSONField(default=dict, blank=True)
    created_at  = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ('-fitness', '-created_at')

    def __str__(self) -> str:
        return f'{self.sequence.slug} → {self.fitness:.4f} ({self.metric_name})'

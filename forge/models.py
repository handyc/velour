"""Forge — circuits as evolved hex CA configurations.

Phase 1: Circuit model carries the substrate grid (a 2D array of K=4
cell values) plus a list of input/output port markers (JSON). The
circuit is simulated with a fixed CA rule (default = wireworld); the
rule is referenced by sha1 so forge stays decoupled from automaton's
RuleSet table.

Later phases will add Population (a GA roster), Trial (an input/output
truth-table evaluation), and Score (per-circuit fitness on a target
function).
"""
from __future__ import annotations

from django.db import models
from django.utils.text import slugify

from .wireworld import WIREWORLD_NAME, WIREWORLD_PALETTE


class Circuit(models.Model):
    """One hex CA circuit — substrate + ports + rule reference."""

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    description = models.TextField(blank=True)

    width = models.PositiveSmallIntegerField(default=16)
    height = models.PositiveSmallIntegerField(default=16)

    palette = models.JSONField(
        default=list, blank=True,
        help_text='List of CSS hex strings, one per cell value. '
                  'Defaults to the wireworld palette '
                  '(empty / wire / head / tail) if empty.',
    )

    grid = models.JSONField(
        default=list, blank=True,
        help_text='2D array (height x width) of cell values 0..K-1. '
                  'This is the *initial* state — runs always start '
                  'from here.',
    )

    # Rule reference — kept as sha1 (stable across re-imports) plus a
    # human-readable name. Phase-1 only uses the wireworld rule;
    # phase-2 will let users pick / co-evolve.
    rule_sha1 = models.CharField(max_length=40, blank=True, default='')
    rule_name = models.CharField(max_length=120, blank=True,
                                 default=WIREWORLD_NAME)

    # Ports: list of {role: 'input'|'output', name: str,
    #                 x: int, y: int, schedule: [tick offsets]}
    # Schedule is the list of ticks at which this input pulses (head)
    # or — for outputs — is read. Empty schedule = always-on input or
    # read every tick for outputs.
    ports = models.JSONField(default=list, blank=True)

    # Optional notes about *what this circuit is supposed to do* — the
    # target function. Phase-2 will turn this into structured truth
    # tables for fitness scoring.
    target = models.JSONField(default=dict, blank=True,
                              help_text='Free-form target spec.')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return self.name or self.slug or f'circuit#{self.pk}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:160] or 'circuit'
            candidate = base
            n = 2
            while (Circuit.objects.filter(slug=candidate)
                   .exclude(pk=self.pk).exists()):
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        if not self.palette:
            self.palette = list(WIREWORLD_PALETTE)
        if not self.grid:
            self.grid = [[0] * self.width for _ in range(self.height)]
        super().save(*args, **kwargs)

    @property
    def palette_or_default(self) -> list[str]:
        return list(self.palette) if self.palette else list(WIREWORLD_PALETTE)

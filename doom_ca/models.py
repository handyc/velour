"""doom_ca — a Doom-shaped game running on a 4-colour hex CA.

The world is one component of a spoeqi Pact, ticking under its
sealed rule.  Cell states map by threshold to ground / wall.  Player
and monsters are app-tracked positions overlaid on top — moved each
tick, never written into the CA.  Camera follows the player so the
CA's evolving walls *appear* to scroll past.

Two parties playing the same Pact's same component with the same
keypress sequence get a byte-identical playthrough — the determinism
is inherited from spoeqi.
"""

from __future__ import annotations
from django.conf import settings
from django.db import models
from django.utils.text import slugify

from spoeqi.models import Pact, COMPONENTS


class GameSession(models.Model):
    """One game configuration: which pact, which component, how many
    monsters, what counts as a wall.  The actual playthrough state
    lives in the browser — this row only records the *setup*."""

    WORLD_MODE_CHOICES = [
        ('overlay',  'overlay — pact rule + JS-tracked player/monsters '
                     '(camera follows player)'),
        ('shift',    'shift — pure-CA: 6 directional shift rules anchor '
                     'the player at centre, world scrolls past'),
        ('scent',    'scent — pure-CA: single rule, monsters spread '
                     'fluid-like toward the player; walls block'),
        ('evolved',  'evolved — pact rule with per-key patches for '
                     'player-preserve, wall-cluster-stability, monster-'
                     'attack-adjacent (illustrative GA target)'),
    ]

    name        = models.CharField(max_length=80, unique=True)
    slug        = models.SlugField(max_length=80, unique=True)

    pact        = models.ForeignKey(
        Pact, on_delete=models.CASCADE, related_name='doom_sessions',
        help_text='Spoeqi pact providing the underlying CA world.')
    component   = models.PositiveSmallIntegerField(
        default=0,
        help_text=f'Which of the {COMPONENTS} components serves as the '
                  'playfield.  Different components = different rules '
                  '(in fleet mode) = different worlds.')

    world_mode  = models.CharField(
        max_length=10, choices=WORLD_MODE_CHOICES, default='overlay',
        help_text='How the CA drives the game world.  See class doc.')

    monster_count = models.PositiveSmallIntegerField(
        default=8,
        help_text='Number of monsters spawned at game start.')

    # Cells with state >= wall_threshold are walls (impassable).
    # 1 → 75 % walls (very dense), 2 → 50 %, 3 → 25 % (sparse).
    wall_threshold = models.PositiveSmallIntegerField(
        default=2,
        help_text='Cell states ≥ this are walls.  1 dense, 3 sparse. '
                  'In overlay mode this is the cell-state cutoff; in '
                  'shift/scent/evolved modes it is only used at init '
                  'to derive ground vs wall from the pact seed.')

    pure_mode = models.BooleanField(
        default=False,
        help_text='If true (and world_mode is shift/scent/evolved), '
                  'the pact rule is NOT applied on wait ticks; only '
                  'the mode\'s own rule + player moves change the '
                  'world.  Trades atmosphere for predictability.')

    # Phase-1 Doom items.  Item placement is deterministic from the
    # pact seed + these counts; the cells live on an overlay layer so
    # they don't disturb the K=4 invariant of the underlying CA.
    health_pack_count = models.PositiveSmallIntegerField(
        default=3,
        help_text='Medkits scattered on reachable ground (each +25 HP).')
    ammo_pack_count = models.PositiveSmallIntegerField(
        default=3,
        help_text='Ammo packs scattered on reachable ground (each +3 ammo).')
    door_count = models.PositiveSmallIntegerField(
        default=1,
        help_text='If 1, a locked door + key are placed on the spawn→exit '
                  'path (0 = open level, just find the exit).')

    notes       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='doom_sessions')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            base = slugify(self.name)[:80] or 'game'
            self.slug = base
            n = 2
            while type(self).objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                tail = f'-{n}'
                self.slug = base[:80 - len(tail)] + tail
                n += 1
        super().save(*a, **kw)

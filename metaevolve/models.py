"""metaevolve — orchestration layer above the doom_ca Evolution Engine.

A `Target` is a recipe for *what to evolve*: which archetype preset
to start from, an optional retrogames.Game it's aspiring toward,
overrides for population / generations / max_turns / weight bundle,
and a priority used by the batch runner to pick the next target.

The runner page (templates/metaevolve/runner.html) walks through
active Targets in priority order, driving an embedded doom_ca
evolve view via URL params.  When each run completes, the top
winners get POSTed to /metaevolve/archive/ and stored as
ArchivedWinner rows that survive page reloads (unlike the
localStorage carry-over inside the live evolve page).
"""

from __future__ import annotations
from django.conf import settings
from django.db import models
from django.utils.text import slugify


# Mirrors the archetype keys hard-coded in templates/doom_ca/evolve.html.
ARCHETYPE_CHOICES = [
    ('doom',    'Doom'),
    ('pacman',  'Pacman'),
    ('pitfall', 'Pitfall'),
    ('blob',    'Boy & His Blob'),
    ('tmnt',    'TMNT'),
    ('custom',  'Custom'),
]


class Target(models.Model):
    """One thing the meta-evolver wants to breed for.

    A Target combines an archetype preset (which loads a bundle of
    fitness weights inside evolve.html) with optional pointers at a
    classic game (retrogames.Game) and config overrides.  Marking a
    Target inactive removes it from the runner queue without deleting
    history.
    """

    name        = models.CharField(max_length=120, unique=True)
    slug        = models.SlugField(max_length=120, unique=True)
    archetype   = models.CharField(
        max_length=20, choices=ARCHETYPE_CHOICES, default='doom',
        help_text='Preset bundle to apply on the evolve page.')
    target_game = models.ForeignKey(
        'retrogames.Game', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='metaevolve_targets',
        help_text='Optional classic game this Target is aspiring toward.')

    # Run shape (overrides defaults on the evolve form).  Null = leave
    # the form's preset/archetype value alone.
    population_size  = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Population size override.')
    generations      = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Generations per run override.')
    max_turns        = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Max turns per sim override.')
    grid_side        = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Grid size override (16/24/32).')

    # Batch policy.
    runs_per_batch   = models.PositiveSmallIntegerField(
        default=3,
        help_text='How many consecutive runs of this Target per batch '
                  '(survivors compound across runs via the localStorage '
                  'carry-over, so more runs = more accumulation).')
    archive_top_k    = models.PositiveSmallIntegerField(
        default=3,
        help_text='How many top-fitness survivors to archive per run.')
    priority         = models.SmallIntegerField(
        default=0,
        help_text='Higher priority Targets run earlier in a batch sweep.')
    active           = models.BooleanField(
        default=True,
        help_text='If false, the runner skips this Target.')

    notes        = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    last_run_at  = models.DateTimeField(null=True, blank=True)
    total_runs   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-priority', 'name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            base = slugify(self.name)[:120] or 'target'
            self.slug = base
            n = 2
            while Target.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                tail = f'-{n}'
                self.slug = base[:120 - len(tail)] + tail
                n += 1
        super().save(*a, **kw)


class ArchivedWinner(models.Model):
    """A single high-fitness gene preserved from one evolve run.

    The full `gene_json` is stored verbatim so the original evolve
    page (or anywhere else) can reconstruct + materialise it later.
    Keeps the rule (32 KB) + palette + counts + music style etc.
    """

    target       = models.ForeignKey(
        Target, on_delete=models.CASCADE, related_name='winners')
    fitness      = models.FloatField()
    gene_json    = models.JSONField(
        help_text='The full evolved gene: rule bytes, seed_byte, palette, '
                  'world_mode, monster_count, item counts, music_style_idx, '
                  'pure_mode, wall_threshold, component_grid.  Rule is '
                  'stored as a list of 16384 ints 0..3.')
    components_json = models.JSONField(
        null=True, blank=True,
        help_text='The fitness components breakdown (playability, openness, '
                  'completion, etc.) at archive time — useful for tracking '
                  'why this gene won.')
    notes        = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    materialised_session_slug = models.CharField(
        max_length=80, blank=True,
        help_text='If the user has materialised this archived winner into '
                  'a real doom_ca GameSession, the resulting session slug.')

    class Meta:
        ordering = ['-fitness', '-created_at']

    def __str__(self):
        return f'{self.target.name} · fitness {self.fitness:.3f} · {self.created_at:%Y-%m-%d}'

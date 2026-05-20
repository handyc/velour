"""Minimal persistence for boardstack experiments.

Just enough to remember evolution runs and their best gene so we
can compare runs.  No QRPair-style production schema."""
from django.db import models


class StackGenome(models.Model):
    """One stack configuration: 64 ruleset indices (into a pool),
    per-board ticks-per-step, wiring, etc.  Stored as JSON because
    the gene shape is still being explored."""
    slug         = models.SlugField(max_length=80, unique=True)
    n_boards     = models.PositiveIntegerField(default=16)
    board_side   = models.PositiveIntegerField(default=64)
    gene_json    = models.JSONField(default=dict)
    fitness      = models.FloatField(default=0.0)
    test_set_id  = models.CharField(max_length=80, blank=True,
        help_text='label of the (p,q) test set this was scored against')
    notes        = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-fitness', '-created_at')

    def __str__(self):
        return (f'{self.slug}  n={self.n_boards}×{self.board_side}  '
                f'fit={self.fitness:.4f}')


class EvolutionRun(models.Model):
    """A GA run: parameters + summary stats."""
    slug         = models.SlugField(max_length=80, unique=True)
    started_at   = models.DateTimeField(auto_now_add=True)
    finished_at  = models.DateTimeField(null=True, blank=True)
    config_json  = models.JSONField(default=dict)
    best_genome  = models.ForeignKey(StackGenome, on_delete=models.SET_NULL,
                                          null=True, blank=True,
                                          related_name='best_of_runs')
    n_generations = models.PositiveIntegerField(default=0)
    n_evals      = models.PositiveIntegerField(default=0)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering = ('-started_at',)

    def __str__(self):
        return f'{self.slug}  gens={self.n_generations}'

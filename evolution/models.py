"""Evolution Engine — recursive populations of Agents.

Three roles played by the same Agent class, distinguished by `level`:
  L0  worker     — gene encodes L-system (axiom/rules/iterations); work()
                   expands its seed string and is scored against a goal.
  L1  meta       — gene encodes parameters for spawning a population of
                   L0 agents; work() runs that inner population and reports
                   the best inner score.
  L2  meta-meta  — gene encodes parameters for spawning a population of
                   L1 agents.

Live evolution happens in the browser. Django stores Runs (history,
goal, params) and saved Agents (the library + export targets).
"""

from django.db import models
from django.utils.text import slugify


AGENT_LEVEL = (
    (0, 'L0 — worker'),
    (1, 'L1 — meta'),
    (2, 'L2 — meta-meta'),
)


class EvolutionRun(models.Model):
    """A configured evolution session. Live state lives in the browser;
    we persist params + best score + saved snapshots so the run is
    re-openable and the history is browsable.
    """
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    level = models.PositiveSmallIntegerField(choices=AGENT_LEVEL, default=0)
    goal_string = models.TextField(
        blank=True,
        help_text='The string the population is evolving toward. Pasted '
                  'literal or expanded from `goal_species` at run creation.'
    )
    goal_species = models.ForeignKey(
        'lsystem.PlantSpecies', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='evolution_runs',
        help_text='If set, goal_string was expanded from this species.'
    )
    goal_language = models.ForeignKey(
        'grammar_engine.Language', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='evolution_runs',
        help_text='If set, goal_string was expanded from a variant of '
                  'this Grammar Engine language.'
    )
    goal_variant = models.CharField(
        max_length=160, blank=True,
        help_text='"<category>/<variant>" — identifies which variant of '
                  'goal_language was expanded.'
    )
    population_size = models.PositiveSmallIntegerField(default=24)
    generations_target = models.PositiveIntegerField(default=200)
    target_score = models.FloatField(
        default=0.95,
        help_text='Stop early once any agent meets this score (0..1).'
    )
    seed_agent = models.ForeignKey(
        'Agent', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='runs_seeded',
        help_text='Optional saved Agent used as the founding parent.'
    )
    params = models.JSONField(
        default=dict, blank=True,
        help_text='Free-form: mutation_rate, inner_size, inner_generations, '
                  'script (user-defined work hook), seed_string, etc.'
    )

    STATUS_CHOICES = (
        ('idle',     'idle'),
        ('running',  'running'),
        ('paused',   'paused'),
        ('finished', 'finished'),
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='idle')
    generation = models.PositiveIntegerField(default=0)
    best_score = models.FloatField(default=0.0)
    notes = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-modified']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f'run-{self.pk or "new"}'
            self.slug = base[:180]
        super().save(*args, **kwargs)


class Agent(models.Model):
    """A snapshot of one Agent — its gene, its level, where it came
    from. Same shape regardless of role; consumers (the JS engine,
    L-System export, Legolith export) read the gene differently
    depending on `level`.
    """
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    level = models.PositiveSmallIntegerField(choices=AGENT_LEVEL, default=0)
    gene = models.JSONField(
        default=dict,
        help_text='L0: {axiom, rules, iterations}. L1/L2: inner-pop params.'
    )
    seed_string = models.CharField(
        max_length=500, blank=True,
        help_text='Starting string fed to work() before iterations.'
    )
    script = models.TextField(
        blank=True,
        help_text='Optional user-defined JS body — runs in addition to '
                  'the L-system work step. Receives (agent, ctx) and may '
                  'return a partial-score contribution.'
    )
    score = models.FloatField(
        default=0.0,
        help_text='Best score observed at the moment of saving.'
    )
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='descendants',
    )
    source_run = models.ForeignKey(
        EvolutionRun, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='saved_agents',
    )
    notes = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f'agent-{self.pk or "new"}'
            self.slug = base[:180]
        super().save(*args, **kwargs)

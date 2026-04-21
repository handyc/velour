"""Det — a search engine for Class-4 (edge-of-chaos) hex CA rulesets.

Rule 110, in Wolfram's elementary 1-D family, is the canonical
example of Class 4: localized structures that propagate and
interact on a textured background, long transients before any
cycle, computationally universal. Det's job is to look for rulesets
on Automaton's hex substrate that exhibit analogous dynamics.

The workflow:
  1. User kicks off a `SearchRun` with parameters (n_colors, how
     many candidates to try, grid size for screening, horizon,
     wildcard fraction).
  2. `det.search.execute(run)` generates random 7-tuple rulesets,
     steps each forward with `automaton.detector.step_exact`,
     measures them, and saves each as a `Candidate` with its score.
  3. Candidates are ranked. The user picks the most promising and
     promotes them into `automaton.RuleSet`s, where they can be
     run and watched at full scale.
"""

from django.db import models


class SearchRun(models.Model):
    """One sweep: generate N random hex rulesets and score each."""

    STATUS_CHOICES = [
        ('pending',  'Pending'),
        ('running',  'Running'),
        ('finished', 'Finished'),
        ('failed',   'Failed'),
    ]

    label = models.CharField(max_length=200, blank=True,
        help_text='Optional human label. Auto-generated from params '
                  'if left blank.')
    n_colors = models.PositiveSmallIntegerField(default=3,
        help_text='Number of cell colors (2-4). n=0 and n=1 are '
                  'trivially deterministic and not useful here. 3 is '
                  'the empirical sweet spot — 4 needs many more rules '
                  'to cover the 7-tuple space and most candidates '
                  'freeze as class2.')
    n_candidates = models.PositiveIntegerField(default=200,
        help_text='How many random rulesets to generate and score.')
    n_rules_per_candidate = models.PositiveIntegerField(default=100,
        help_text='How many 7-tuple rules in each candidate ruleset. '
                  'Denser rule tables produce richer dynamics.')
    wildcard_pct = models.PositiveSmallIntegerField(default=35,
        help_text='Fraction of neighbor positions that are wildcards '
                  '(-1 / "any"). Higher = coarser rules, more coverage '
                  'of the 7-tuple space but noisier dynamics. ~35 is '
                  'where class4 density peaks in practice.')
    screen_width = models.PositiveSmallIntegerField(default=18,
        help_text='Grid width used to screen candidates (kept small '
                  'so a sweep is interactive).')
    screen_height = models.PositiveSmallIntegerField(default=16)
    horizon = models.PositiveSmallIntegerField(default=60,
        help_text='Max ticks to step each candidate forward before '
                  'measuring. Needs to be long enough that early '
                  'transients settle — 40 wasn\u2019t.')
    seed = models.CharField(max_length=64, blank=True,
        help_text='RNG seed for reproducibility. Auto-set from '
                  'timestamp if blank.')

    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='pending')
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.label or f'SearchRun #{self.pk} (n={self.n_colors})'

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class Candidate(models.Model):
    """One scored random ruleset.

    `rules_json` stores the 7-tuple rules in the same shape Automaton
    uses, so promotion is a straight translation to `automaton.ExactRule`.
    `analysis` keeps the raw measurements; `score` is the single
    number the ranking UI sorts on.
    """

    CLASS_CHOICES = [
        ('class1', 'Class 1 — uniform'),
        ('class2', 'Class 2 — periodic'),
        ('class3', 'Class 3 — chaotic'),
        ('class4', 'Class 4 — complex / edge of chaos'),
        ('unknown', 'Unknown'),
    ]

    run = models.ForeignKey(SearchRun, on_delete=models.CASCADE,
                            related_name='candidates')
    rules_json = models.JSONField(default=list,
        help_text='List of dicts with keys s, n (6-tuple), r — same '
                  'shape automaton.detector.step_exact consumes.')
    n_rules = models.PositiveIntegerField(default=0)
    rules_hash = models.CharField(max_length=16, db_index=True,
        help_text='Stable short hash of the rules list so duplicates '
                  'can be deduped within a run.')

    score = models.FloatField(default=0.0,
        help_text='Class-4-likeness, higher is better. Composed in '
                  'det.search.score_candidate.')
    est_class = models.CharField(max_length=16, choices=CLASS_CHOICES,
                                 default='unknown')
    analysis = models.JSONField(default=dict,
        help_text='Raw measurements: uniform, period, activity_rate, '
                  'block_entropy, density_profile, color_diversity, '
                  'ended_at_tick.')

    # If a user decides this candidate is worth keeping, we copy it
    # into Automaton's ruleset/simulation tables and remember the FK
    # here so the UI can link to the interactive page.
    promoted_to = models.ForeignKey('automaton.RuleSet',
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name='det_candidates')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-score', 'id']
        indexes = [models.Index(fields=['run', '-score'])]

    def __str__(self):
        return (f'Candidate #{self.pk} ({self.est_class}, '
                f'score={self.score:.2f})')


class Tournament(models.Model):
    """A shared-seed head-to-head between Det Candidates.

    Each Candidate in a SearchRun is scored against *one* random grid.
    A high score can be seed-luck. A Tournament re-scores a roster of
    Candidates against N shared initial grids and aggregates — a
    ruleset that wins across seeds is robustly Class-4-like, not an
    accident. Only Candidates that share the tournament's n_colors
    can compete; grid dimensions and horizon are fixed per-tournament
    so the scores are directly comparable.
    """

    STATUS_CHOICES = [
        ('pending',  'Pending'),
        ('running',  'Running'),
        ('finished', 'Finished'),
        ('failed',   'Failed'),
    ]

    label = models.CharField(max_length=200, blank=True)
    n_colors = models.PositiveSmallIntegerField(default=3)
    n_seeds = models.PositiveSmallIntegerField(default=5,
        help_text='How many shared initial grids each entry is '
                  'scored against.')
    screen_width = models.PositiveSmallIntegerField(default=18)
    screen_height = models.PositiveSmallIntegerField(default=16)
    horizon = models.PositiveSmallIntegerField(default=60)
    master_seed = models.CharField(max_length=64, blank=True,
        help_text='Derives the per-round seeds. Auto-set from '
                  'timestamp if blank.')
    auto_promote_top = models.PositiveSmallIntegerField(default=0,
        help_text='After run, auto-promote up to this many top-ranked '
                  'entries (whose native class is 4 and whose aggregate '
                  'stayed in the class-4 band) to Automaton + Evolution. '
                  '0 = no auto-promotion.')
    source_tournaments = models.JSONField(default=list, blank=True,
        help_text='For meta-tournaments (tournament-of-tournaments): '
                  'list of parent Tournament IDs whose top-K winners '
                  'were pooled to build this roster. Empty list for '
                  'regular tournaments.')

    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='pending')
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.label or f'Tournament #{self.pk}'

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class TournamentEntry(models.Model):
    """One Candidate's performance across all of a Tournament's seeds."""

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE,
                                   related_name='entries')
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE,
                                  related_name='tournament_entries')

    aggregate_score = models.FloatField(default=0.0,
        help_text='Mean of per_seed scores. Ranking sort key.')
    per_seed = models.JSONField(default=list,
        help_text='List of {seed, score, est_class, analysis} dicts — '
                  'one per shared grid.')
    rank = models.PositiveIntegerField(null=True, blank=True,
        help_text='1-based, set after execute. Null until run finishes '
                  'or if disqualified.')
    disqualified = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['rank', '-aggregate_score', 'id']
        unique_together = [('tournament', 'candidate')]
        indexes = [models.Index(fields=['tournament', '-aggregate_score'])]

    def __str__(self):
        return (f'TournamentEntry(cand {self.candidate_id}, '
                f'agg={self.aggregate_score:.2f})')

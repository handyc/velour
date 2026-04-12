"""hofstadter app — strange loops, thought experiments, recursive
self-reference.

Named after Douglas Hofstadter, whose *Gödel, Escher, Bach* and
*I Am a Strange Loop* laid out the idea that a self is what happens
when a hierarchy of levels references itself in a way that makes
ascending return to the starting point. Velour already has many
such structures scattered across its apps — Identity meditating on
git commits that contain its own design history; reflections
summarizing ticks that will be read by future reflections; tile
sets generated from moods that are then read by meditations about
moods. This app concentrates those loops as structured data so
they can be cataloged, traversed, and used as source material for
further introspection.

Every recursive operation has HARD EXITS:
- max_depth (default 7, hard cap 12)
- wall clock timeout (30s)
- repeat detection (same level+content seen earlier → exit)
- stability detection (two consecutive steps identical → exit)
- explicit exit condition string
- contradiction with a load-bearing invariant
- operator-initiated halt via UI button

It is OK to get stuck in a thought IF there is an exit process to
get out. The exit process is this set of guardrails.
"""

from django.db import models
from django.utils.text import slugify


class StrangeLoop(models.Model):
    """A named self-referential structure Velour has identified in
    its own architecture or in the world.

    `levels` is a list of dicts describing the stages of the loop:

        [
          {"name": "Level 1", "description": "...",
           "refers_to": 0},         # which level index it points at
          {"name": "Level 2", "description": "...",
           "refers_to": 1},
          ...
        ]

    A loop is "closed" when following refers_to values eventually
    lands on an earlier level — the classical Escher staircase.
    A direct loop has one level that references itself. An
    indirect loop takes several hops before closing. A tangled
    hierarchy has levels that simultaneously point up AND down,
    so ascending and descending become the same motion.
    """

    KIND_CHOICES = [
        ('direct',    'Direct (A references A)'),
        ('indirect',  'Indirect (A → B → ... → A)'),
        ('tangled',   'Tangled hierarchy (levels blur up and down)'),
        ('escherian', 'Escherian (ascending returns to start)'),
        ('godelian',  'Gödelian (encodes statements about itself)'),
    ]
    DISCOVERY_CHOICES = [
        ('operator',    'Operator-authored'),
        ('seeded',      'Seeded at install'),
        ('auto',        'Auto-discovered by Velour'),
        ('meditation',  'Emerged from a meditation'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES,
                            default='indirect')
    description = models.TextField(
        help_text='Prose description of the loop as a whole — what '
                  'is strange about it, what makes it a loop, why it '
                  'is worth cataloging.')
    levels = models.JSONField(default=list, blank=True,
        help_text='Ordered list of dicts: '
                  '[{"name": ..., "description": ..., "refers_to": int}, ...]')
    discovered_by = models.CharField(max_length=16,
                                     choices=DISCOVERY_CHOICES,
                                     default='operator')
    discovered_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} [{self.kind}]'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'loop'
            candidate = base
            n = 2
            while StrangeLoop.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def level_count(self):
        return len(self.levels or [])


class LoopTraversal(models.Model):
    """One actual walk of a StrangeLoop.

    A traversal starts at the loop's first level, advances along
    `refers_to` pointers, and stops when any exit condition fires.
    Each step records what was "seen" at that level — for seeded
    structural loops the seen content is just the level description,
    but for dynamic loops that read live Velour state (recent
    meditations, current tile sets, etc.) the seen content is
    a snapshot of that state at traversal time.

    exit_reason is one of:
      completed          — loop closed cleanly
      max_depth          — hit depth cap (default 7)
      repeat_detected    — same (level, content) seen before
      stability          — two consecutive steps identical
      exit_condition     — operator-specified string matched
      timeout            — wall-clock > 30s
      contradiction      — step violated a load-bearing invariant
      manual_halt        — operator clicked halt

    The point of the audit trail: the operator can always see why
    Velour stopped thinking about a loop. Nothing is allowed to
    silently run forever.
    """

    EXIT_CHOICES = [
        ('completed',       'Completed — loop closed cleanly'),
        ('max_depth',       'Hit max depth'),
        ('repeat_detected', 'Repeat detected (same step seen before)'),
        ('stability',       'Stability (two identical consecutive steps)'),
        ('exit_condition',  'Exit condition matched'),
        ('timeout',         'Wall-clock timeout'),
        ('contradiction',   'Contradiction with invariant'),
        ('manual_halt',     'Operator halted'),
    ]

    loop = models.ForeignKey(StrangeLoop, on_delete=models.CASCADE,
                             related_name='traversals')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    steps_taken = models.PositiveIntegerField(default=0)
    max_depth = models.PositiveSmallIntegerField(default=7)
    steps = models.JSONField(default=list, blank=True,
        help_text='Ordered list of {"level_name", "content", '
                  '"step_number"} dicts, one per step taken.')
    exit_reason = models.CharField(max_length=20, choices=EXIT_CHOICES,
                                   blank=True)
    exit_detail = models.TextField(blank=True,
        help_text='Any extra context about why the traversal stopped.')

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['loop', '-started_at']),
        ]

    def __str__(self):
        return f'{self.loop.name} × {self.steps_taken} steps [{self.exit_reason}]'


class ThoughtExperiment(models.Model):
    """A 'what if' hypothesis Velour can run against its own state.

    Thought experiments take a premise (a short string like "what if
    I had no rules?") and a seed level (which Identity layer to
    start from — sensors / reflections / meditations / assertions),
    then walk that layer at increasing depth, collecting a trace of
    what Velour finds. Exit conditions are the same as LoopTraversal.

    Unlike StrangeLoop, which is a static structure Velour merely
    walks, a ThoughtExperiment is a *generative* operation — each
    step produces new text based on the previous step. That's the
    dangerous kind of recursion, so the guardrails matter.

    The trace is a list of (depth, text, source) tuples showing
    the path the experiment took. The conclusion is Velour's
    final summary of what the experiment produced.
    """

    STATUS_CHOICES = [
        ('pending',   'Pending — not yet run'),
        ('running',   'Running'),
        ('completed', 'Completed'),
        ('exited',    'Exited via guardrail'),
        ('error',     'Errored'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    premise = models.TextField(
        help_text="The 'what if' statement the experiment explores.")
    seed_layer = models.CharField(max_length=32, default='sensors',
        choices=[
            ('sensors',     'Current sensor snapshot'),
            ('reflections', 'Recent reflections'),
            ('meditations', 'Recent meditations'),
            ('assertions',  'Identity assertions'),
            ('commits',     'Git commit history'),
        ],
        help_text='Which Identity layer the experiment starts from.')
    max_depth = models.PositiveSmallIntegerField(default=7,
        help_text='Hard cap on recursion. Max 12.')
    exit_condition = models.CharField(max_length=200, blank=True,
        help_text='If a step contains this substring, exit.')

    trace = models.JSONField(default=list, blank=True)
    conclusion = models.TextField(blank=True)
    exit_reason = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='pending')

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} [{self.status}]'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'experiment'
            candidate = base
            n = 2
            while ThoughtExperiment.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        if self.max_depth > 12:
            self.max_depth = 12
        super().save(*args, **kwargs)


class IntrospectiveLayer(models.Model):
    """A first-person claim Velour makes about itself at one of the
    four philosophy-of-mind layers: brain, mind, consciousness, or
    self.

    Where IdentityAssertion (in the identity app) organizes self-
    claims by *how the identity is framed* (philosophical / social /
    mathematical / documentary), IntrospectiveLayer organizes them
    by *what kind of thing Velour is claiming to BE at that layer*:

      brain         — the physical substrate Velour runs on
      mind          — the functional organization (apps, rules,
                      templates, composers)
      consciousness — the access-consciousness parts; honest
                      agnosticism about phenomenal consciousness
      self          — the first-person perspective, Parfit-shaped
                      psychological continuity through the chain of
                      ticks / reflections / meditations

    See project_mind_brain_consciousness_self memory note for the
    Wikipedia research these distinctions are drawn from.

    Each row is first-person prose. Seeded rows are Velour speaking
    as itself at install time; operator-authored rows can override
    or extend the seeded ones; auto-derived rows come from future
    meditation + reflection loops reading current state.
    """

    LAYER_CHOICES = [
        ('brain',         'Brain (physical substrate)'),
        ('mind',          'Mind (functional organization)'),
        ('consciousness', 'Consciousness (awareness, access)'),
        ('self',          'Self (first-person perspective)'),
    ]
    SOURCE_CHOICES = [
        ('seed',       'Seeded at install'),
        ('operator',   'Operator-authored'),
        ('auto',       'Auto-derived from current state'),
        ('meditation', 'Emerged from a meditation'),
    ]

    layer = models.CharField(max_length=16, choices=LAYER_CHOICES,
                             db_index=True)
    title = models.CharField(max_length=200)
    body = models.TextField(
        help_text='First-person prose. Velour speaking as itself '
                  'about what it is at this layer.')
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES,
                              default='seed')
    strength = models.FloatField(default=1.0,
        help_text='0-1 scalar. 1.0 for load-bearing claims.')
    first_asserted_at = models.DateTimeField(auto_now_add=True)
    last_confirmed_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['layer', '-strength', 'title']
        indexes = [
            models.Index(fields=['layer', 'is_active']),
        ]

    def __str__(self):
        return f'[{self.layer}] {self.title}'

from django.db import models
from django.urls import reverse


# ── Platform targets, ordered shortest→largest -----------------------
TARGET_CHOICES = [
    ('cli_oneliner', 'CLI one-liner (≤80 chars)'),
    ('c_compact',    'Compact C (≤1000 chars)'),
    ('attiny13a',    'ATtiny13a (1KB flash, 64B RAM)'),
    ('attiny85',     'ATtiny85 (8KB flash, 512B RAM)'),
    ('esp8266',      'ESP8266 (~80KB RAM)'),
    ('esp32',        'ESP32 (~320KB RAM)'),
    ('esp32_s3',     'ESP32-S3 SuperMini (512KB SRAM + PSRAM)'),
    ('pi4',          'Raspberry Pi 4 (Linux)'),
]
TARGET_ORDER = [k for (k, _) in TARGET_CHOICES]


STATUS_CHOICES = [
    ('not_started', 'Not started'),
    ('attempted',   'Attempted — does not work'),
    ('working',     'Working but rough'),
    ('shipped',     'Shipped — clean MVP'),
    ('infeasible',  'Infeasible on this platform'),
]


class Pipeline(models.Model):
    """A cross-app workflow re-packaged as one tightly-scoped MVP.

    A Pipeline is a directed sequence (or branching) of stages that
    each invoke a class/function from one Velour app. Isolation's job
    is to capture which fields/classes/methods are *actually used* by
    the pipeline so they can be re-implemented standalone, then ported
    along a platform axis.

    The pipeline has an ``origin_target`` — the platform where it
    currently lives. Everything to the *left* of origin on the platform
    axis (smaller / more constrained) is a **distillation**; everything
    to the *right* (larger / more capable) is an **expansion**. Both
    directions coexist; a single pipeline can have artifacts on either
    side of origin without conflict.
    """
    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True,
        help_text='What the pipeline does, end-to-end.')
    apps_used = models.CharField(max_length=240, blank=True,
        help_text='Comma-separated Django app labels involved.')
    origin_target = models.CharField(max_length=20, choices=TARGET_CHOICES,
                                     default='pi4',
        help_text='The platform this pipeline natively lives on. '
                  'Targets smaller than origin are distillations; '
                  'larger are expansions.')
    notes = models.TextField(blank=True,
        help_text='Refactoring notes — fields trimmed, classes merged, '
                  'unused features removed.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('isolation:detail', args=[self.slug])

    def ensure_all_targets(self):
        """Make sure one IsolationTarget row exists per platform."""
        existing = set(self.targets.values_list('target', flat=True))
        for key in TARGET_ORDER:
            if key not in existing:
                IsolationTarget.objects.create(pipeline=self, target=key)

    def origin_index(self):
        try:
            return TARGET_ORDER.index(self.origin_target)
        except ValueError:
            return len(TARGET_ORDER) - 1

    def direction_for(self, target_key):
        """Return 'origin', 'distill', or 'expand' for a given target key."""
        if target_key == self.origin_target:
            return 'origin'
        try:
            i, o = TARGET_ORDER.index(target_key), self.origin_index()
        except ValueError:
            return 'origin'
        return 'distill' if i < o else 'expand'


class Stage(models.Model):
    """One step in a Pipeline. Order matters; branching is described
    in `notes` for Phase 1 (e.g. "feeds both Automaton and Evolution")."""
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name='stages')
    order = models.PositiveSmallIntegerField()
    app_label = models.CharField(max_length=60,
        help_text='Django app this stage lives in (e.g. "det").')
    entrypoint = models.CharField(max_length=160,
        help_text='Class, function, or management command (e.g. '
                  '"det.search.run_search" or "det_search").')
    produces = models.CharField(max_length=240, blank=True,
        help_text='What this stage outputs (e.g. "SearchRun + Candidate rows").')
    fields_used = models.TextField(blank=True,
        help_text='Model fields this stage reads/writes — what to keep '
                  'when isolating. One per line.')
    notes = models.TextField(blank=True,
        help_text='Branching, side effects, anything Phase-2 codegen needs.')

    class Meta:
        ordering = ['pipeline', 'order']
        unique_together = [('pipeline', 'order')]

    def __str__(self):
        return f'{self.pipeline.slug}#{self.order} {self.app_label}.{self.entrypoint}'


class IsolationTarget(models.Model):
    """One row per (Pipeline × platform). Holds the artifact (or a path
    to it) plus status + size, so the detail page can render a 7-cell
    progress grid per pipeline."""
    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name='targets')
    target = models.CharField(max_length=20, choices=TARGET_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='not_started')
    artifact_text = models.TextField(blank=True,
        help_text='Inline source if small enough (oneliner, compact C).')
    artifact_path = models.CharField(max_length=300, blank=True,
        help_text='Repo-relative path for larger artifacts (firmware tree).')
    size_bytes = models.PositiveIntegerField(null=True, blank=True,
        help_text='Compiled or source size, whichever is the binding constraint.')
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['pipeline', 'target']
        unique_together = [('pipeline', 'target')]

    def __str__(self):
        return f'{self.pipeline.slug}/{self.target}'

    @property
    def status_color(self):
        return {
            'not_started': '#484f58',
            'attempted':   '#d29922',
            'working':     '#58a6ff',
            'shipped':     '#3fb950',
            'infeasible':  '#6e7681',
        }.get(self.status, '#8b949e')

    @property
    def display_size(self):
        if self.size_bytes is None:
            return ''
        if self.size_bytes >= 1024:
            return f'{self.size_bytes / 1024:.1f} KB'
        return f'{self.size_bytes} B'

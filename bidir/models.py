"""Bidir — track features being ported back-and-forth between
runtimes (e.g. officerpg's JS/HTML build and the planned ANSI-C
backport).  A feature exists once; its parity in each variant
lives in a per-(feature, variant) PortStatus row.

Phase 1 scope: just the tracking matrix.  WorldStateBlob (state
that travels between variants — the officerpg ev44 shot format
is the canonical example) lives in the relevant runtime for now;
bidir can ingest those later as a Phase 2 feature.
"""
from django.db import models


class Variant(models.Model):
    """A target runtime — JS/HTML, ANSI-C, ATtiny, etc."""
    RUNTIME_KIND = [
        ('browser', 'Browser (HTML+JS)'),
        ('native',  'Native binary (C/C++)'),
        ('mcu',     'Microcontroller'),
        ('other',   'Other'),
    ]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    runtime_kind = models.CharField(
        max_length=24, choices=RUNTIME_KIND, default='other')
    is_canonical = models.BooleanField(
        default=False,
        help_text='The variant that defines the reference behaviour. '
                  'Other variants are scored against this one.')
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Feature(models.Model):
    """A named slice of behaviour to track parity for."""
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    introduced_in = models.CharField(
        max_length=64, blank=True,
        help_text='Build label where the canonical variant first '
                  'shipped this — e.g. "ev16", "v0.3".')
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class PortStatus(models.Model):
    """Where a feature stands inside a particular variant."""
    STATE_CHOICES = [
        ('todo',    'todo'),
        ('partial', 'partial'),
        ('done',    'done'),
        ('na',      'not applicable'),
    ]

    feature = models.ForeignKey(
        Feature, on_delete=models.CASCADE, related_name='statuses')
    variant = models.ForeignKey(
        Variant, on_delete=models.CASCADE, related_name='statuses')
    state = models.CharField(
        max_length=16, choices=STATE_CHOICES, default='todo')
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('feature', 'variant')]
        ordering = ['feature__sort_order', 'variant__sort_order']

    def __str__(self):
        return f'{self.feature.slug} / {self.variant.slug}: {self.state}'


class Build(models.Model):
    """A concrete build artifact — a file at a path / commit, with a
    label like "ev45" or "v0.1.2".  Lets the matrix link directly to
    the bytes a status row was last verified against."""
    variant = models.ForeignKey(
        Variant, on_delete=models.CASCADE, related_name='builds')
    label = models.CharField(max_length=64)
    file_path = models.CharField(max_length=300, blank=True)
    git_commit = models.CharField(max_length=40, blank=True)
    bytes_size = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('variant', 'label')]
        ordering = ['variant__sort_order', '-created_at']

    def __str__(self):
        return f'{self.variant.slug}/{self.label}'

from django.db import models
from django.utils.text import slugify


class Experiment(models.Model):
    """A physical lab experiment that one or more Node devices are attached to.

    Phase 0 keeps this intentionally small — just enough to attach nodes to
    and label in the fleet list view. Sensor channels, actuator channels,
    readings, rules, decisions, and trained trees will all live on related
    models added in later phases once the first experiment is instrumented.

    `is_intermittent` is a hint to the fleet UI: an experiment that runs
    off solar or only during certain hours shouldn't raise red alerts when
    its nodes go dark — expected dormancy looks different from failure.
    """

    STATUS_CHOICES = [
        ('active',   'Active'),
        ('paused',   'Paused'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True,
        help_text='URL-safe identifier. Auto-derived from name if blank.')
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='active')
    is_intermittent = models.BooleanField(
        default=False,
        help_text='True for experiments that only run sometimes (e.g. solar-powered). '
                  'The fleet view treats attached nodes as dormant-not-failed when offline.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

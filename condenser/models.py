"""Condenser — progressive distillation of software through
increasingly constrained platforms.

A Distillation takes a source (a Velour app or external project)
and produces output for a target tier:

  Tier 1: Django/Python (full app, server, DB)
  Tier 2: JS-only (browser, localStorage, no server)
  Tier 3: ESP8266 (HTML served by microcontroller)
  Tier 4: ATTiny13a (1KB flash, 64B RAM, 8 pins)
  Tier 5: 555 timers (discrete analog/digital circuits)

Each distillation is annotated with Gödel markers — comments in the
output that guide the next distillation pass. The code carries its
own reduction instructions forward.

The first distillation (Tiles → JS) proves the concept. Future
distillations are Claude-assisted: the annotations are prompts
that Claude reads in live sessions to do the creative reimagining.
"""

from django.db import models
from django.utils.text import slugify


TIER_CHOICES = [
    ('django',   'Tier 1: Django/Python'),
    ('js',       'Tier 2: JS-only (browser)'),
    ('esp',      'Tier 3: ESP8266 (microcontroller)'),
    ('attiny',   'Tier 4: ATTiny13a (1KB flash)'),
    ('circuit',  'Tier 5: 555 timer circuits'),
]


class Distillation(models.Model):
    """One pass of the condenser: source → target tier."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    source_app = models.CharField(max_length=100,
        help_text='Velour app name (e.g. "tiles") or path to external project.')
    source_tier = models.CharField(max_length=16, choices=TIER_CHOICES,
                                    default='django')
    target_tier = models.CharField(max_length=16, choices=TIER_CHOICES,
                                    default='js')
    output = models.TextField(blank=True,
        help_text='The distilled output — HTML/JS, C code, circuit description, etc.')
    output_size_bytes = models.IntegerField(default=0)
    annotations = models.TextField(blank=True,
        help_text='Gödel markers extracted from the output — prompts for the next pass.')
    status = models.CharField(max_length=16, default='pending',
        choices=[('pending', 'Pending'), ('running', 'Running'),
                 ('completed', 'Completed'), ('error', 'Error')])
    error_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.source_tier} → {self.target_tier})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'distillation'
            candidate = base
            n = 2
            while Distillation.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

"""retrogames — a catalogue of console games for "evolve toward this".

Platforms span from Magnavox Odyssey² (1978) through PS3.  Games carry
enough metadata that a doom_ca evolution run can target one as an
archetype (e.g. "evolve toward Adventure on the Atari 2600") and a
human reviewer can sanity-check the resulting gene against the
original game's actual mechanics, art, audio.
"""

from __future__ import annotations
from django.db import models
from django.utils.text import slugify


class Platform(models.Model):
    """A console / home computer system."""

    name         = models.CharField(max_length=80, unique=True)
    slug         = models.SlugField(max_length=80, unique=True)
    manufacturer = models.CharField(max_length=80, blank=True)
    year_release = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Year the platform first shipped.')
    year_retire  = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Year the platform was discontinued (blank if still in production).')
    bit_depth    = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Marketed bit depth — 8, 16, 32, 64, 128.')
    notes        = models.TextField(
        blank=True,
        help_text='What was distinctive about this platform.')

    class Meta:
        ordering = ['year_release', 'name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = slugify(self.name)[:80]
        super().save(*a, **kw)


class Game(models.Model):
    """One released title.  Multiple ports of the same game across
    platforms get separate Game rows — the platform is part of the
    identity."""

    GENRE_CHOICES = [
        ('action',     'Action'),
        ('adventure',  'Adventure'),
        ('rpg',        'Role-playing'),
        ('platformer', 'Platformer'),
        ('shooter',    'Shooter / FPS'),
        ('puzzle',     'Puzzle'),
        ('fighting',   'Fighting'),
        ('racing',     'Racing'),
        ('sports',     'Sports'),
        ('strategy',   'Strategy'),
        ('simulation', 'Simulation'),
        ('maze',       'Maze / collect'),
        ('shmup',      'Shoot-em-up'),
        ('beatup',     'Beat-em-up'),
        ('survival',   'Survival horror'),
        ('rhythm',     'Rhythm / music'),
        ('roguelike',  'Roguelike'),
        ('text',       'Text adventure'),
        ('other',      'Other'),
    ]

    name        = models.CharField(max_length=160)
    slug        = models.SlugField(max_length=200)
    platform    = models.ForeignKey(
        Platform, on_delete=models.CASCADE, related_name='games')
    year        = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Release year on this platform.')
    genre       = models.CharField(
        max_length=20, choices=GENRE_CHOICES, default='other')
    developer   = models.CharField(max_length=120, blank=True)
    publisher   = models.CharField(max_length=120, blank=True)
    description = models.TextField(
        blank=True,
        help_text='One-paragraph plain-English description: setting, '
                  'mechanics, controls, win condition.  This is the '
                  'text a future "evolve toward description" fitness '
                  'function will score genes against.')
    mechanics   = models.TextField(
        blank=True,
        help_text='Comma- or bullet-separated tags: "side-scrolling, '
                  'jumping, treasure-collection, no shooting" etc.')
    wikipedia_url = models.URLField(blank=True)

    class Meta:
        ordering = ['platform__year_release', 'year', 'name']
        unique_together = [('platform', 'slug')]

    def __str__(self):
        return f'{self.name} ({self.platform.name})'

    def save(self, *a, **kw):
        if not self.slug:
            base = slugify(self.name)[:200] or 'game'
            self.slug = base
            n = 2
            while Game.objects.filter(platform=self.platform_id,
                                       slug=self.slug).exclude(pk=self.pk).exists():
                tail = f'-{n}'
                self.slug = base[:200 - len(tail)] + tail
                n += 1
        super().save(*a, **kw)

"""Cartography — Velour's multi-scale map app.

Five scale bands, each backed by the appropriate viewer:

  earth         Leaflet + OpenStreetMap tiles
  mars          Leaflet + NASA Trek Mars Viking tiles
  moon          Leaflet + NASA Trek LRO LOLA tiles
  solar_system  Stub for Phase 4 (iframe NASA's Eyes on the Solar
                System for v1, custom 2D for v2)
  sky           Aladin Lite (HiPS sky surveys, scale from individual
                galaxies to large-scale structure)

The Place model is a saved bookmark — a coordinate + zoom + scale
the user wants to return to. The MapPrefs singleton holds the
default view (where to start when /cartography/ is opened cold).
"""

from django.db import models
from django.utils.text import slugify


SCALE_CHOICES = [
    ('earth',        'Earth (OpenStreetMap)'),
    ('mars',         'Mars surface'),
    ('moon',         'Moon surface'),
    ('solar_system', 'Solar System'),
    ('sky',          'Sky / Galaxy / Universe'),
]


class MapPrefs(models.Model):
    """Singleton — exactly one row, pk=1.

    Holds the default view used when /cartography/ is opened without
    a specific scale or coordinate. Default is Leiden (the user's
    home city) — change via the admin or the settings page.
    """

    default_scale = models.CharField(
        max_length=16, choices=SCALE_CHOICES, default='earth',
    )
    default_lat = models.FloatField(default=52.1601)
    default_lon = models.FloatField(default=4.4970)
    default_zoom = models.IntegerField(default=12)

    class Meta:
        verbose_name = 'Map preferences'
        verbose_name_plural = 'Map preferences'

    def __str__(self):
        return f'MapPrefs(scale={self.default_scale}, '\
               f'lat={self.default_lat}, lon={self.default_lon})'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Place(models.Model):
    """A saved location bookmark.

    Lat / lon are interpreted in the coordinate system of the chosen
    scale. For Earth and the planetary surfaces this is the standard
    geodetic latitude/longitude. For sky scale, lat/lon are reused as
    declination/right-ascension (in degrees) — the same field shape
    serves both since they're both spherical coordinates.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    scale = models.CharField(
        max_length=16, choices=SCALE_CHOICES, default='earth',
    )
    lat = models.FloatField()
    lon = models.FloatField()
    zoom = models.IntegerField(default=10)
    notes = models.TextField(blank=True)
    color = models.CharField(
        max_length=9, blank=True,
        help_text='Optional hex color for the marker pin.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scale', 'name']
        indexes = [models.Index(fields=['scale'])]

    def __str__(self):
        return f'{self.name} ({self.scale})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'place'
            candidate = base
            n = 2
            while Place.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

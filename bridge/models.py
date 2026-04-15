"""Bridge persistence — the planet library.

Every warp records the destination in the Planet table. The
`features` JSON is the full output of `planets.generate_planet` at
the moment of discovery — the source of truth the client
reconstructs the 3D scene from.
"""

from django.db import models
from django.utils import timezone


class Planet(models.Model):
    """One procedurally-generated planet discovered via warp."""

    name = models.CharField(max_length=64)
    seed = models.BigIntegerField(db_index=True)
    ptype = models.CharField(max_length=32, db_index=True)
    features = models.JSONField()
    discovered = models.DateTimeField(default=timezone.now)
    last_visited = models.DateTimeField(default=timezone.now)
    visit_count = models.PositiveIntegerField(default=1)

    # Slug, not FK: planets survive language deletion. If the language
    # is gone at beam-down time, NPCs fall back to the most-popular
    # language. An empty slug means the planet is preverbal — its
    # NPCs say nothing at all.
    primary_language_slug = models.CharField(
        max_length=140, blank=True, default='',
    )

    class Meta:
        ordering = ['-last_visited']

    def __str__(self):
        return f'{self.name} ({self.ptype})'

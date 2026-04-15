"""Legolith models.

A LegoWorld is a 32x32-stud baseplate populated by L-System-grown buildings,
trees, flowers, people, hills, lamps, and rocks. The full world payload is
kept as JSON (round-trip fidelity with worlds.World.to_json); the DB columns
are denormalized for indexing and list views.
"""

from django.db import models
from django.utils.text import slugify


BIOME_CHOICES = [
    ('plains',  'Plains'),
    ('forest',  'Forest'),
    ('desert',  'Desert'),
    ('snow',    'Snow'),
    ('harbor',  'Harbor'),
    ('autumn',  'Autumn'),
    ('town',    'Town'),
    ('dusk',    'Dusk'),
    ('meadow',  'Meadow'),
    ('island',  'Island'),
]


class LegoWorld(models.Model):
    """A single L-System Lego world."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    biome = models.CharField(max_length=16, choices=BIOME_CHOICES,
                             default='plains')
    seed = models.IntegerField(default=1)
    baseplate_color = models.CharField(max_length=7, default='#5ea04b')

    n_buildings = models.IntegerField(default=0)
    n_trees = models.IntegerField(default=0)
    n_flowers = models.IntegerField(default=0)
    n_people = models.IntegerField(default=0)
    n_hills = models.IntegerField(default=0)
    n_lamps = models.IntegerField(default=0)
    n_rocks = models.IntegerField(default=0)

    payload = models.JSONField(
        help_text='Full world JSON (worlds.World.to_json round-trip).',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.biome}, s{self.seed})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:120] or 'world'
            candidate = f'{base}-s{self.seed:04d}'
            n = 2
            while LegoWorld.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-s{self.seed:04d}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def n_decor(self):
        return self.n_hills + self.n_lamps + self.n_rocks

    def to_world(self):
        """Rehydrate into a worlds.World instance for rendering."""
        from . import worlds as W
        import json as _json
        blob = self.payload
        if isinstance(blob, dict):
            blob = _json.dumps(blob)
        return W.World.from_json(blob)


KIND_CHOICES = [
    ('tree',     'Tree'),
    ('flower',   'Flower'),
    ('building', 'Building'),
    ('person',   'Person'),
    ('hill',     'Hill'),
    ('lamp',     'Lamp'),
    ('rock',     'Rock'),
    ('vehicle',  'Vehicle'),
    ('creature', 'Creature'),
    ('other',    'Other'),
]


class LegoModel(models.Model):
    """A reusable L-System Lego object stored in the shared library.

    The spec (axiom + rules + iterations + starting turtle state + footprint)
    is all that's needed to render the object — same pipeline the built-in
    generators use. Any Legolith world, and any Aether Legoworld, can place
    these by referring to the model's ``slug``.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES,
                            default='other',
                            help_text='Category for library filtering; does '
                                      'not constrain the L-System itself.')
    description = models.TextField(blank=True)

    axiom = models.CharField(max_length=200, default='X')
    rules = models.JSONField(
        default=dict,
        help_text='{"X": "F[>L][<L]..."} — maps single-char symbols to '
                  'replacement strings.',
    )
    iterations = models.PositiveSmallIntegerField(default=2)

    # Starting turtle state
    init_color = models.CharField(max_length=7, default='#888888')
    init_shape_w = models.PositiveSmallIntegerField(default=1)
    init_shape_d = models.PositiveSmallIntegerField(default=1)
    init_shape_plates = models.PositiveSmallIntegerField(default=3)

    # Grid space the model reserves when placed in a world
    footprint_w = models.PositiveSmallIntegerField(default=2)
    footprint_d = models.PositiveSmallIntegerField(default=2)

    use_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} ({self.kind})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:120] or 'model'
            candidate = base
            n = 2
            while LegoModel.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def init_shape(self):
        return (self.init_shape_w, self.init_shape_d, self.init_shape_plates)

    def as_spec(self):
        """Dict of the spec used by lsystem.make_from_spec()."""
        return {
            'axiom': self.axiom,
            'rules': dict(self.rules or {}),
            'iterations': self.iterations,
            'init_color': self.init_color,
            'init_shape': self.init_shape,
        }

"""vampyrik — a catalogue of vampire lore from the world's folk traditions.

The shape is deliberately wide: a Tradition is a cultural-geographic
container (Romanian, Slavic, Greek, Filipino, …) holding any number of
Creatures (the named vampire variant — strigoi, vrykolakas, aswang, …).
Traits, Origins, and Weaknesses are tag-like taxonomies that creatures
share across traditions (almost every European vampire fears garlic; the
'must be invited in' trait recurs from Slavic to Hollywood).  Sources
record the citation a fact came from.
"""

from django.db import models
from django.utils.text import slugify


class Source(models.Model):
    """A book, paper, region-of-origin, or oral tradition the lore
    was attested in.  Light-touch — full citation lives in `details`."""

    title    = models.CharField(max_length=200)
    author   = models.CharField(max_length=160, blank=True)
    year     = models.CharField(max_length=24, blank=True,
                                help_text='Free-form: "1897", "c. 1730", '
                                          '"oral, 19th c."')
    details  = models.TextField(blank=True)

    class Meta:
        ordering = ['author', 'title']

    def __str__(self):
        return f'{self.author}, {self.title}' if self.author else self.title


class Trait(models.Model):
    """A physical, behavioural, or supernatural attribute attested for
    one or more creatures.  Examples: 'pale skin', 'shapeshifts into
    bat', 'cannot cross running water', 'must be invited inside'."""

    KIND_CHOICES = [
        ('physical',     'physical'),
        ('behavioural',  'behavioural'),
        ('supernatural', 'supernatural'),
        ('apotropaic',   'apotropaic (something that wards them off)'),
    ]
    name        = models.CharField(max_length=120, unique=True)
    slug        = models.SlugField(max_length=140, unique=True, blank=True)
    kind        = models.CharField(max_length=14, choices=KIND_CHOICES,
                                   default='physical')
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['kind', 'name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = unique_slug(type(self), self.name)
        super().save(*a, **kw)


class Origin(models.Model):
    """How one becomes the creature: bite, curse, unbaptised death,
    seventh son, suicide, born with a caul, …"""

    name        = models.CharField(max_length=140, unique=True)
    slug        = models.SlugField(max_length=160, unique=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = unique_slug(type(self), self.name)
        super().save(*a, **kw)


class Weakness(models.Model):
    """What harms, repels, or destroys the creature: sunlight,
    decapitation, stake through the heart, salt scattered on the floor,
    running water, a Bible left open, …"""

    name        = models.CharField(max_length=140, unique=True)
    slug        = models.SlugField(max_length=160, unique=True, blank=True)
    destroys    = models.BooleanField(
        default=False,
        help_text='True if this kills/dissolves the creature.  False if '
                  'it only wards, repels, or weakens.')
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['-destroys', 'name']

    def __str__(self):
        return self.name + (' †' if self.destroys else '')

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = unique_slug(type(self), self.name)
        super().save(*a, **kw)


class Tradition(models.Model):
    """A cultural-geographic body of lore.  Holds creatures."""

    name        = models.CharField(max_length=120, unique=True)
    slug        = models.SlugField(max_length=140, unique=True, blank=True)
    region      = models.CharField(max_length=160, blank=True,
                                   help_text='e.g. "Romania (Wallachia, '
                                             'Moldavia, Transylvania)"')
    era         = models.CharField(max_length=80, blank=True,
                                   help_text='Free-form: "medieval", '
                                             '"18th–19th c.", "oral, ongoing"')
    summary     = models.TextField(blank=True,
                                   help_text='2–4 sentences situating this '
                                             'tradition in its culture.')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = unique_slug(type(self), self.name)
        super().save(*a, **kw)


class Creature(models.Model):
    """A named vampire variant within a tradition.  This is the heart
    of the catalogue — one row per attested variant (strigoi viu vs
    strigoi mort vs moroi are three rows, not one)."""

    name        = models.CharField(max_length=140)
    slug        = models.SlugField(max_length=160, unique=True, blank=True)
    tradition   = models.ForeignKey(Tradition, on_delete=models.CASCADE,
                                    related_name='creatures')
    alt_names   = models.CharField(max_length=400, blank=True,
                                   help_text='Comma-separated other names '
                                             'and spellings.')

    summary     = models.TextField(blank=True,
                                   help_text='2–5 sentences: what the '
                                             'creature is, what it does.')
    appearance  = models.TextField(blank=True,
                                   help_text='Physical form: corpse, '
                                             'bloated, skeletal, fanged, '
                                             'severed head with entrails, …')
    behaviour   = models.TextField(blank=True,
                                   help_text='Hunting pattern, diet, social '
                                             'habits, time-of-day, etc.')
    notes       = models.TextField(blank=True)

    traits      = models.ManyToManyField(Trait,      blank=True,
                                         related_name='creatures')
    origins     = models.ManyToManyField(Origin,     blank=True,
                                         related_name='creatures')
    weaknesses  = models.ManyToManyField(Weakness,   blank=True,
                                         related_name='creatures')
    sources     = models.ManyToManyField(Source,     blank=True,
                                         related_name='creatures')

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tradition__name', 'name']
        unique_together = [('tradition', 'name')]

    def __str__(self):
        return f'{self.name} ({self.tradition.name})'

    def save(self, *a, **kw):
        if not self.slug:
            base = slugify(f'{self.tradition.slug}-{self.name}')[:160] \
                if self.tradition_id else slugify(self.name)[:160]
            self.slug = base
            n = 2
            while type(self).objects.filter(slug=self.slug) \
                                    .exclude(pk=self.pk).exists():
                tail = f'-{n}'
                self.slug = base[:160 - len(tail)] + tail
                n += 1
        super().save(*a, **kw)


def unique_slug(model_cls, value):
    base = slugify(value)[:140] or 'entry'
    slug = base
    n = 2
    while model_cls.objects.filter(slug=slug).exists():
        tail = f'-{n}'
        slug = base[:140 - len(tail)] + tail
        n += 1
    return slug

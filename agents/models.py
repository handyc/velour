"""Persistent NPC ("Agent") records for re-use across Aether worlds.

Design constraints:

- Each Agent row must fit in well under 10 KB so a million-row
  population is on the order of gigabytes, not terabytes.
- One flat row per Agent. Extended profile data lives in `bio_json`
  (a single JSON blob, bounded by `BIO_BUDGET_BYTES`) rather than
  related profile rows; the read path stays one query.
- Friendships and other agent↔agent links live in `AgentRelation`
  (M2M), so a popular Agent's row never blows the byte budget.
- Towns are macro-locations; each Town can host any number of small
  Aether `World` scenes, arranged on an axial-hex grid via `TownCell`.
  An Aether World is a small scene; a Town is the place several scenes
  share.

Soft limits enforced in `Agent.clean()`:

    BIO_BUDGET_BYTES = 8000   # leaves headroom under 10 KB after column overhead
    BACKSTORY_MAX    = 2000   # chars
    PERSONALITY_MAX  = 16     # tags
"""

from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


BIO_BUDGET_BYTES = 8000
BACKSTORY_MAX    = 2000
PERSONALITY_MAX  = 16


GENDER_CHOICES = [
    ('f',  'Female'),
    ('m',  'Male'),
    ('nb', 'Non-binary'),
    ('?',  'Unspecified'),
]


def default_bio():
    """Empty but well-shaped bio so callers can mutate without KeyError."""
    return {
        'occupation':  '',
        'backstory':   '',
        'personality': [],
        'favorites':   {
            # Keys reserved (all values are slugs/ints into other apps so no FK
            # contraint pins a million rows):
            #   tileset      → tiles.Tileset.slug
            #   attic_image  → attic.MediaItem.slug
            #   aether_world → aether.World.slug
            #   lsystem_species → lsystem.PlantSpecies.slug
            #   planet       → bridge.Planet.id
            #   language     → grammar_engine.Language.slug
        },
        'appearance': {
            'hair':           '',
            'eye_color':      '',
            'skin_tone':      '',
            'clothing_style': '',
        },
        'voice': {
            'pitch':       1.0,
            'rate':        1.0,
            'voice_name':  '',
        },
    }


class Town(models.Model):
    """A macro-location shared by several Aether scenes."""

    slug         = models.SlugField(max_length=120, unique=True)
    name         = models.CharField(max_length=120)
    description  = models.TextField(blank=True)
    founded_year = models.IntegerField(null=True, blank=True,
                       help_text="In-fiction founding year; can be negative.")
    population_target = models.PositiveIntegerField(default=0,
                       help_text="Designer's intended Agent count; informational only.")
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TownCell(models.Model):
    """One hex cell of a Town's 2D world map (axial coords).

    Optionally pinned to one `aether.World` — that's the small scene
    you visit when you walk into this cell. Cells without a world are
    "wilderness" you can place a scene into later.

    Six neighbours of (q, r):
        (q+1, r), (q-1, r), (q, r+1), (q, r-1),
        (q+1, r-1), (q-1, r+1)
    """

    HEX_NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]

    town  = models.ForeignKey(Town, on_delete=models.CASCADE, related_name='cells')
    q     = models.IntegerField()
    r     = models.IntegerField()
    label = models.CharField(max_length=80, blank=True,
                help_text="Optional name (e.g. 'docks', 'temple square').")
    world = models.ForeignKey('aether.World', on_delete=models.SET_NULL,
                null=True, blank=True, related_name='+')

    class Meta:
        unique_together = [('town', 'q', 'r')]
        indexes = [models.Index(fields=['town', 'q', 'r'])]
        ordering = ['town', 'q', 'r']

    def __str__(self):
        return f'{self.town.slug}[{self.q},{self.r}]' + (
            f' = {self.world.slug}' if self.world_id else ''
        )

    def neighbour_coords(self):
        return [(self.q + dq, self.r + dr) for dq, dr in self.HEX_NEIGHBOURS]


class Agent(models.Model):
    """One persistent NPC. Reusable across Aether scenes.

    Designed for a 10M-row population: every column is fixed-width or
    bounded text; the only variable-size field is `bio_json` and it is
    capped by `Agent.clean()`.
    """

    slug          = models.SlugField(max_length=80, unique=True)
    name          = models.CharField(max_length=80)
    family_name   = models.CharField(max_length=80, blank=True)
    gender        = models.CharField(max_length=2, choices=GENDER_CHOICES, default='?')
    birthdate     = models.DateField(null=True, blank=True)
    town          = models.ForeignKey(Town, on_delete=models.PROTECT,
                       related_name='residents')
    origin_world  = models.ForeignKey('aether.World', on_delete=models.SET_NULL,
                       null=True, blank=True, related_name='+',
                       help_text="The Aether scene the character is associated with.")
    current_cell  = models.ForeignKey(TownCell, on_delete=models.SET_NULL,
                       null=True, blank=True, related_name='visitors')
    face_seed     = models.PositiveIntegerField(default=0,
                       help_text="Face Forge replay seed. 0 = unset.")
    bio_json      = models.JSONField(default=default_bio)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'family_name']
        indexes = [
            models.Index(fields=['town', 'name']),
            models.Index(fields=['origin_world']),
        ]

    def __str__(self):
        if self.family_name:
            return f'{self.name} {self.family_name}'
        return self.name

    def display_name(self):
        return str(self)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f'{self.name}-{self.family_name}'.strip('-')) or 'agent'
            candidate = base[:80]
            n = 2
            while Agent.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                suffix = f'-{n}'
                candidate = (base[:80 - len(suffix)] + suffix)
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def clean(self):
        # Enforce the byte budget on bio_json. Cheaper than enforcing on
        # bulk insert, but we accept the trade — bulk_create paths must
        # call full_clean explicitly.
        size = self.bio_size_bytes()
        if size > BIO_BUDGET_BYTES:
            raise ValidationError(
                {'bio_json': f'bio_json is {size} bytes (cap {BIO_BUDGET_BYTES}).'}
            )
        backstory = (self.bio_json or {}).get('backstory') or ''
        if len(backstory) > BACKSTORY_MAX:
            raise ValidationError(
                {'bio_json': f'backstory is {len(backstory)} chars (cap {BACKSTORY_MAX}).'}
            )
        traits = (self.bio_json or {}).get('personality') or []
        if isinstance(traits, list) and len(traits) > PERSONALITY_MAX:
            raise ValidationError(
                {'bio_json': f'personality has {len(traits)} tags (cap {PERSONALITY_MAX}).'}
            )

    def bio_size_bytes(self) -> int:
        """Serialised size of bio_json — the only variable field."""
        try:
            return len(json.dumps(self.bio_json or {}, ensure_ascii=False)
                       .encode('utf-8'))
        except (TypeError, ValueError):
            return 0

    def estimated_row_bytes(self) -> int:
        """Rough estimate: stable columns (~200 B for slugs/timestamps/FKs)
        plus the bio JSON. Real on-disk size depends on SQLite/PostgreSQL
        page packing; this is for budget enforcement, not accounting."""
        fixed = 0
        fixed += len(self.slug.encode('utf-8')) if self.slug else 0
        fixed += len(self.name.encode('utf-8')) if self.name else 0
        fixed += len(self.family_name.encode('utf-8')) if self.family_name else 0
        fixed += 64  # timestamps, ints, FK ids — generous estimate
        return fixed + self.bio_size_bytes()


class AgentRelation(models.Model):
    """Directed relationship between two Agents.

    Stored separately so a popular Agent's row stays bounded.
    """

    KIND_CHOICES = [
        ('friend',    'Friend'),
        ('family',    'Family'),
        ('coworker',  'Coworker'),
        ('rival',     'Rival'),
        ('mentor',    'Mentor'),
        ('partner',   'Partner'),
        ('neighbour', 'Neighbour'),
    ]

    src      = models.ForeignKey(Agent, on_delete=models.CASCADE,
                  related_name='outgoing_relations')
    dst      = models.ForeignKey(Agent, on_delete=models.CASCADE,
                  related_name='incoming_relations')
    kind     = models.CharField(max_length=16, choices=KIND_CHOICES)
    since    = models.DateField(null=True, blank=True)
    notes    = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [('src', 'dst', 'kind')]
        indexes = [
            models.Index(fields=['src', 'kind']),
            models.Index(fields=['dst', 'kind']),
        ]

    def __str__(self):
        return f'{self.src} → {self.dst} ({self.kind})'

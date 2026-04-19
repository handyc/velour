from django.db import models


class Building(models.Model):
    """A physical building that holds one or more floors. Most users
    will only ever have a couple of these — "Home", maybe "Office" —
    but making it a first-class model means the stacked-floors view
    has a container to render into and address/location data has
    somewhere sensible to live."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=240, blank=True)
    notes = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Floor(models.Model):
    """A storey within a Building. `level` is an integer so basements
    can be -1, -2 etc. The unique (building, level) constraint means
    you can't accidentally create two "floor 2"s."""

    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name='floors',
    )
    level = models.IntegerField(
        help_text="Storey number: 0 = ground, 1 = first, -1 = basement.",
    )
    name = models.CharField(
        max_length=80, blank=True,
        help_text="Optional human name, e.g. 'Attic', 'Ground floor'.",
    )
    notes = models.TextField(blank=True)
    # Height matters when the Aether export lands — it stacks floors
    # vertically in Z. Defaulting to 280 cm matches a typical Dutch
    # ceiling; users can override per floor.
    height_cm = models.PositiveIntegerField(default=280)

    class Meta:
        # Top-down order: highest floor first in a list, so an attic
        # sits above the ground floor visually.
        ordering = ['building', '-level']
        unique_together = [('building', 'level')]

    def __str__(self):
        return f"{self.building.name} — {self.display_name}"

    @property
    def display_name(self):
        if self.name:
            return self.name
        if self.level == 0:
            return "Ground floor"
        if self.level < 0:
            return f"Basement {abs(self.level)}"
        return f"Floor {self.level}"


class Room(models.Model):
    """A room in the physical lab. Coordinates are in centimetres with
    (0, 0) at the top-left (SVG convention).

    north_direction lets the on-screen layout differ from the usual
    “north is up” convention — the lab here has the entry on its east
    wall but the door sits at the bottom of the screen, so north_direction
    is 'right' and the SVG edge labels get re-mapped accordingly.
    """

    NORTH_UP    = 'up'
    NORTH_RIGHT = 'right'
    NORTH_DOWN  = 'down'
    NORTH_LEFT  = 'left'
    NORTH_CHOICES = [
        (NORTH_UP,    'north is up (top of screen)'),
        (NORTH_RIGHT, 'north is right'),
        (NORTH_DOWN,  'north is down (bottom of screen)'),
        (NORTH_LEFT,  'north is left'),
    ]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    floor = models.ForeignKey(
        Floor, on_delete=models.PROTECT, related_name='rooms',
        null=True, blank=True,
        help_text="Which storey this room sits on. Optional for rooms "
                  "imported before multi-floor support landed.",
    )
    width_cm = models.PositiveIntegerField(help_text="X-axis extent in cm.")
    length_cm = models.PositiveIntegerField(help_text="Y-axis extent in cm.")
    notes = models.TextField(blank=True)

    north_direction = models.CharField(
        max_length=8, choices=NORTH_CHOICES, default=NORTH_UP,
        help_text="Which edge of the SVG points to real-world north.",
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_city = models.CharField(max_length=120, blank=True)
    location_detected_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Feature(models.Model):
    """Fixed architectural features inside a room — doors, windows,
    outlets, vents. Rectangular footprint in cm."""

    KIND_CHOICES = [
        ('door',     'Door'),
        ('window',   'Window'),
        ('outlet',   'Power outlet'),
        ('vent',     'Vent'),
        ('radiator', 'Radiator'),
        ('pillar',   'Pillar / column'),
        ('sink',     'Sink'),
        ('ethernet', 'Ethernet port'),
        ('other',    'Other'),
    ]

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name='features',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    label = models.CharField(max_length=80, blank=True)
    x_cm = models.PositiveIntegerField()
    y_cm = models.PositiveIntegerField()
    width_cm = models.PositiveIntegerField()
    depth_cm = models.PositiveIntegerField()
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['kind', 'label']

    def __str__(self):
        return f"{self.get_kind_display()} {self.label}".strip()


class FurniturePiece(models.Model):
    """A catalog entry — a piece of furniture or equipment that can be
    placed in any room. Footprint is the top-down projection."""

    KIND_CHOICES = [
        ('desk',       'Desk / workbench'),
        ('chair',      'Chair'),
        ('shelf',      'Shelf / bookshelf'),
        ('cabinet',    'Cabinet'),
        ('rack',       'Server / equipment rack'),
        ('aquarium',   'Aquarium / tank'),
        ('lightbox',   'Grow light / lightbox'),
        ('breadboard', 'Breadboard station'),
        ('storage',    'Storage tote / bin'),
        ('other',      'Other'),
    ]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default='other')
    width_cm = models.PositiveIntegerField()
    depth_cm = models.PositiveIntegerField()
    height_cm = models.PositiveIntegerField(default=0)
    heat_watts = models.PositiveIntegerField(
        default=0,
        help_text="Approx heat output in watts (for fire-safety spacing).",
    )
    needs_outlet = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['kind', 'name']

    def __str__(self):
        return self.name


class Placement(models.Model):
    """An instance of a FurniturePiece placed in a Room."""

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name='placements',
    )
    piece = models.ForeignKey(
        FurniturePiece, on_delete=models.PROTECT, related_name='placements',
    )
    label = models.CharField(max_length=120, blank=True)
    x_cm = models.PositiveIntegerField()
    y_cm = models.PositiveIntegerField()
    rotation_deg = models.PositiveSmallIntegerField(
        default=0, help_text="0 / 90 / 180 / 270",
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['room', 'label']

    def __str__(self):
        return f"{self.piece.name} in {self.room.name}"

    @property
    def footprint_cm(self):
        """Return (w, d) in cm, swapping for 90/270° rotations."""
        if self.rotation_deg in (90, 270):
            return (self.piece.depth_cm, self.piece.width_cm)
        return (self.piece.width_cm, self.piece.depth_cm)


class Layout(models.Model):
    """A named snapshot of a Room's Placement positions. Lets the user
    keep a "before" and A/B-compare arrangements, and lets the GA save
    the pre-evolve state automatically so an evolve can be undone."""

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name='layouts',
    )
    name = models.CharField(max_length=120)
    snapshot = models.JSONField(
        default=list,
        help_text=(
            'List of {placement_id, x_cm, y_cm, rotation_deg} recorded '
            'at save time.'
        ),
    )
    is_auto = models.BooleanField(
        default=False,
        help_text='True for auto-snapshots taken before destructive ops.',
    )
    score_total = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.room.slug})"


class Constraint(models.Model):
    """A fire-safety / organization / ergonomic rule that layouts
    should satisfy. Phase 1 stores them descriptively; Phase 2 plugs
    them into the Evolution Engine fitness function."""

    KIND_CHOICES = [
        ('egress',         'Egress clearance'),
        ('heat_spacing',   'Heat-source spacing'),
        ('outlet_near',    'Must be near outlet'),
        ('walkway',        'Walkway minimum width'),
        ('wall_clearance', 'Wall clearance'),
        ('other',          'Other'),
    ]

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name='constraints',
        null=True, blank=True,
        help_text="Leave blank for constraints that apply to all rooms.",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    description = models.CharField(max_length=240)
    value_json = models.JSONField(
        default=dict, blank=True,
        help_text='e.g. {"min_cm": 90} for a walkway rule.',
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['kind']

    def __str__(self):
        return f"{self.get_kind_display()}: {self.description}"

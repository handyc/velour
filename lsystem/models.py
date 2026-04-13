from django.db import models
from django.utils.text import slugify


class PlantSpecies(models.Model):
    """A reusable L-system plant definition with full parameter set."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)

    # L-system grammar
    axiom = models.CharField(max_length=500, default='F')
    # JSON list of rule dicts, e.g. [{"F": "FF+[+F-F]-[-F+F]"}]
    # Multiple entries = stochastic selection per iteration
    rules = models.JSONField(default=list)
    iterations = models.PositiveSmallIntegerField(default=4)

    # Geometry parameters
    angle = models.FloatField(default=22.5, help_text='Branch angle in degrees')
    length_factor = models.FloatField(default=0.65, help_text='Length reduction per depth')
    start_length = models.FloatField(default=0.8)
    trunk_taper = models.FloatField(default=0.7)
    trunk_radius = models.FloatField(default=0.06)

    # Appearance
    trunk_color = models.CharField(max_length=20, default='#5a4020')
    trunk_is_green = models.BooleanField(default=False)
    bark_stripes = models.BooleanField(default=False)
    leaf_color = models.CharField(max_length=20, default='#2a6818')
    leaf_color2 = models.CharField(max_length=20, default='#3a7828')
    leaf_size = models.FloatField(default=0.35)
    leaf_density = models.FloatField(default=0.6)
    LEAF_SHAPE_CHOICES = [
        ('sphere', 'Sphere'), ('cone', 'Cone'), ('star', 'Star'),
    ]
    leaf_shape = models.CharField(max_length=20, choices=LEAF_SHAPE_CHOICES,
                                  default='sphere')

    # Special features
    droop = models.FloatField(default=0.0, help_text='Branch droop per depth level')
    narrow = models.BooleanField(default=False, help_text='Constrain horizontal spread')
    fat_trunk = models.BooleanField(default=False, help_text='Wide baobab-style trunk')

    # Flowers
    has_flowers = models.BooleanField(default=False)
    flower_color = models.CharField(max_length=20, default='#ff80a0', blank=True)
    flower_density = models.FloatField(default=0.15)

    # Special growth modes
    has_fronds = models.BooleanField(default=False, help_text='Palm-style fronds at crown')
    has_coconuts = models.BooleanField(default=False)
    has_culms = models.BooleanField(default=False, help_text='Bamboo-style multiple stems')
    has_rosette = models.BooleanField(default=False, help_text='Succulent rosette pattern')
    is_ground_cover = models.BooleanField(default=False)

    # Metadata
    CATEGORY_CHOICES = [
        ('tree', 'Tree'), ('bush', 'Bush/Shrub'), ('flower', 'Flowering Plant'),
        ('grass', 'Grass/Fern'), ('succulent', 'Succulent/Cactus'),
        ('aquatic', 'Aquatic'), ('vine', 'Vine/Climber'), ('other', 'Other'),
    ]
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='tree')
    tags = models.CharField(max_length=500, blank=True, help_text='Comma-separated tags')
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'plant species'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug, n = base, 1
            while PlantSpecies.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def to_aether_props(self, scale=1.0, seed=42):
        """Convert to props dict suitable for the Aether l-system-plant script."""
        return {
            'species': '_custom',
            'axiom': self.axiom,
            'rules': self.rules,
            'iterations': self.iterations,
            'angle': self.angle,
            'lengthFactor': self.length_factor,
            'startLength': self.start_length,
            'trunkTaper': self.trunk_taper,
            'trunkRadius': self.trunk_radius,
            'trunk': self.trunk_color,
            'trunkIsGreen': self.trunk_is_green,
            'barkStripes': self.bark_stripes,
            'leaf': self.leaf_color,
            'leaf2': self.leaf_color2,
            'leafSize': self.leaf_size,
            'leafDensity': self.leaf_density,
            'leafShape': self.leaf_shape,
            'droop': self.droop,
            'narrow': self.narrow,
            'fatTrunk': self.fat_trunk,
            'flower': self.has_flowers,
            'flowerColor': self.flower_color,
            'flowerDensity': self.flower_density,
            'fronds': self.has_fronds,
            'coconuts': self.has_coconuts,
            'culms': self.has_culms,
            'rosette': self.has_rosette,
            'isGroundCover': self.is_ground_cover,
            'scale': scale,
            'seed': seed,
        }

    @classmethod
    def from_aether_props(cls, name, props):
        """Create a PlantSpecies from Aether entity script props."""
        return cls(
            name=name,
            axiom=props.get('axiom', 'F'),
            rules=props.get('rules', [{'F': 'FF+[+F-F-F]-[-F+F+F]'}]),
            iterations=props.get('iterations', 4),
            angle=props.get('angle', 22.5),
            length_factor=props.get('lengthFactor', 0.65),
            start_length=props.get('startLength', 0.8),
            trunk_taper=props.get('trunkTaper', 0.7),
            trunk_radius=props.get('trunkRadius', 0.06),
            trunk_color=props.get('trunk', '#5a4020'),
            trunk_is_green=props.get('trunkIsGreen', False),
            bark_stripes=props.get('barkStripes', False),
            leaf_color=props.get('leaf', '#2a6818'),
            leaf_color2=props.get('leaf2', '#3a7828'),
            leaf_size=props.get('leafSize', 0.35),
            leaf_density=props.get('leafDensity', 0.6),
            leaf_shape=props.get('leafShape', 'sphere'),
            droop=props.get('droop', 0.0),
            narrow=props.get('narrow', False),
            fat_trunk=props.get('fatTrunk', False),
            has_flowers=props.get('flower', False),
            flower_color=props.get('flowerColor', '#ff80a0'),
            flower_density=props.get('flowerDensity', 0.15),
            has_fronds=props.get('fronds', False),
            has_coconuts=props.get('coconuts', False),
            has_culms=props.get('culms', False),
            has_rosette=props.get('rosette', False),
            is_ground_cover=props.get('isGroundCover', False),
        )

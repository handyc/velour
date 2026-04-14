from django.db import models
from django.utils.text import slugify


class PlantSpecies(models.Model):
    """A reusable L-system definition — plants or architecture."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)

    # L-system grammar
    axiom = models.CharField(max_length=500, default='F')
    # JSON list of rule dicts, e.g. [{"F": "FF+[+F-F-F]-[-F+F+F]"}]
    # Multiple entries = stochastic selection per iteration
    rules = models.JSONField(default=list)
    iterations = models.PositiveSmallIntegerField(default=4)

    # Geometry parameters
    angle = models.FloatField(default=22.5, help_text='Branch angle in degrees')
    length_factor = models.FloatField(default=0.65, help_text='Length reduction per depth')
    start_length = models.FloatField(default=0.8)
    trunk_taper = models.FloatField(default=0.7)
    trunk_radius = models.FloatField(default=0.06)

    # Appearance (plants)
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

    # Special features (plants)
    droop = models.FloatField(default=0.0, help_text='Branch droop per depth level')
    narrow = models.BooleanField(default=False, help_text='Constrain horizontal spread')
    fat_trunk = models.BooleanField(default=False, help_text='Wide baobab-style trunk')

    # Flowers
    has_flowers = models.BooleanField(default=False)
    flower_color = models.CharField(max_length=20, default='#ff80a0', blank=True)
    flower_density = models.FloatField(default=0.15)

    # Special growth modes (plants)
    has_fronds = models.BooleanField(default=False, help_text='Palm-style fronds at crown')
    has_coconuts = models.BooleanField(default=False)
    has_culms = models.BooleanField(default=False, help_text='Bamboo-style multiple stems')
    has_rosette = models.BooleanField(default=False, help_text='Succulent rosette pattern')
    is_ground_cover = models.BooleanField(default=False)

    # ── Architecture mode ────────────────────────────────────
    # When category is building/tower/bridge/wall, the turtle draws
    # boxes instead of cylinders, windows instead of leaves, roofs at tips.
    wall_color = models.CharField(max_length=20, default='#a08870', blank=True)
    wall_color2 = models.CharField(max_length=20, default='#8a7860', blank=True,
                                   help_text='Secondary wall / accent color')
    roof_color = models.CharField(max_length=20, default='#6a3020', blank=True)
    window_color = models.CharField(max_length=20, default='#ffe880', blank=True)
    door_color = models.CharField(max_length=20, default='#5a3818', blank=True)
    wall_width = models.FloatField(default=1.0, help_text='Wall segment width')
    floor_height = models.FloatField(default=1.2, help_text='Height per floor/segment')
    has_windows = models.BooleanField(default=True)
    window_density = models.FloatField(default=0.6,
                                       help_text='Proportion of wall faces with windows')
    ROOF_STYLE_CHOICES = [
        ('flat', 'Flat'), ('gable', 'Gable'), ('hip', 'Hip'),
        ('dome', 'Dome'), ('spire', 'Spire'), ('none', 'None'),
    ]
    roof_style = models.CharField(max_length=20, choices=ROOF_STYLE_CHOICES,
                                  default='gable', blank=True)
    has_chimney = models.BooleanField(default=False)
    has_balcony = models.BooleanField(default=False)
    has_columns = models.BooleanField(default=False,
                                      help_text='Classical columns at entrance')
    ARCH_STYLE_CHOICES = [
        ('', 'Generic'), ('medieval', 'Medieval'), ('modern', 'Modern'),
        ('classical', 'Classical'), ('gothic', 'Gothic'),
        ('industrial', 'Industrial'), ('cottage', 'Cottage'),
        ('tower', 'Tower'),
    ]
    arch_style = models.CharField(max_length=20, choices=ARCH_STYLE_CHOICES,
                                  blank=True, default='')

    # Metadata
    CATEGORY_CHOICES = [
        ('tree', 'Tree'), ('bush', 'Bush/Shrub'), ('flower', 'Flowering Plant'),
        ('grass', 'Grass/Fern'), ('succulent', 'Succulent/Cactus'),
        ('aquatic', 'Aquatic'), ('vine', 'Vine/Climber'),
        ('building', 'Building'), ('tower', 'Tower'), ('bridge', 'Bridge'),
        ('wall', 'Wall/Fence'), ('other', 'Other'),
    ]
    ARCHITECTURE_CATEGORIES = {'building', 'tower', 'bridge', 'wall'}
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

    @property
    def is_architecture(self):
        return self.category in self.ARCHITECTURE_CATEGORIES

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
        """Convert to props dict suitable for Aether scripts."""
        props = {
            'species': '_custom',
            'axiom': self.axiom,
            'rules': self.rules,
            'iterations': self.iterations,
            'angle': self.angle,
            'lengthFactor': self.length_factor,
            'startLength': self.start_length,
            'trunkTaper': self.trunk_taper,
            'trunkRadius': self.trunk_radius,
            'scale': scale,
            'seed': seed,
            'isArchitecture': self.is_architecture,
        }
        if self.is_architecture:
            props.update({
                'wallColor': self.wall_color,
                'wallColor2': self.wall_color2,
                'roofColor': self.roof_color,
                'windowColor': self.window_color,
                'doorColor': self.door_color,
                'wallWidth': self.wall_width,
                'floorHeight': self.floor_height,
                'hasWindows': self.has_windows,
                'windowDensity': self.window_density,
                'roofStyle': self.roof_style,
                'hasChimney': self.has_chimney,
                'hasBalcony': self.has_balcony,
                'hasColumns': self.has_columns,
                'archStyle': self.arch_style,
            })
        else:
            props.update({
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
            })
        return props

    def to_building_props(self, scale=1.0, seed=42):
        """Translate an architecture species into props for Aether's
        `procedural-building` script, which actually knows how to render
        houses/towers/churches etc.

        The `l-system-plant` script ignores `isArchitecture`, so feeding
        architecture species through it produces plant-shaped geometry.
        Until a true L-system architecture renderer exists, we treat each
        architecture species as a curated *preset* for procedural-building:
        colors and intent come from the species; type/floors/dimensions
        are derived from arch_style and category.
        """
        import random as _r
        rng = _r.Random(seed)

        if self.category == 'tower':
            btype = 'tower'
        elif self.category == 'wall':
            # No native wall type; warehouse is the closest single-story form.
            btype = 'warehouse'
        elif self.arch_style == 'gothic':
            btype = 'church'
        elif self.arch_style == 'industrial':
            btype = 'factory'
        elif self.arch_style == 'modern':
            btype = 'skyscraper'
        else:
            # medieval / cottage / classical / generic — all "house"-shaped
            btype = 'house'

        if btype == 'tower':
            floors = rng.randint(4, 7)
        elif btype == 'skyscraper':
            floors = rng.randint(6, 14)
        elif btype == 'church':
            floors = 2
        elif btype == 'warehouse':
            floors = 1
        elif btype == 'factory':
            floors = rng.randint(1, 2)
        else:
            floors = rng.randint(1, 3)

        base_w = max(4.0, self.wall_width * 6 * scale)
        base_d = max(4.0, self.wall_width * 5 * scale)
        if btype in ('skyscraper', 'tower'):
            sq = max(base_w, base_d) * 0.7
            base_w = base_d = sq
        width = round(min(base_w, 22.0), 1)
        depth = round(min(base_d, 18.0), 1)

        return {
            'type':        btype,
            'floors':      floors,
            'width':       width,
            'depth':       depth,
            'floorHeight': 3.2,
            'color':       self.wall_color or '#b0a898',
            'trim':        self.wall_color2 or '#808080',
            'roof':        self.roof_color or '#6a4030',
            'windowColor': self.window_color or '#a8c8e0',
            'windowLit':   0.3,
        }

    @classmethod
    def from_aether_props(cls, name, props):
        """Create a PlantSpecies from Aether entity script props."""
        obj = cls(
            name=name,
            axiom=props.get('axiom', 'F'),
            rules=props.get('rules', [{'F': 'FF+[+F-F-F]-[-F+F+F]'}]),
            iterations=props.get('iterations', 4),
            angle=props.get('angle', 22.5),
            length_factor=props.get('lengthFactor', 0.65),
            start_length=props.get('startLength', 0.8),
            trunk_taper=props.get('trunkTaper', 0.7),
            trunk_radius=props.get('trunkRadius', 0.06),
        )
        if props.get('isArchitecture'):
            obj.category = 'building'
            obj.wall_color = props.get('wallColor', '#a08870')
            obj.wall_color2 = props.get('wallColor2', '#8a7860')
            obj.roof_color = props.get('roofColor', '#6a3020')
            obj.window_color = props.get('windowColor', '#ffe880')
            obj.door_color = props.get('doorColor', '#5a3818')
            obj.wall_width = props.get('wallWidth', 1.0)
            obj.floor_height = props.get('floorHeight', 1.2)
            obj.has_windows = props.get('hasWindows', True)
            obj.window_density = props.get('windowDensity', 0.6)
            obj.roof_style = props.get('roofStyle', 'gable')
            obj.has_chimney = props.get('hasChimney', False)
            obj.has_balcony = props.get('hasBalcony', False)
            obj.has_columns = props.get('hasColumns', False)
            obj.arch_style = props.get('archStyle', '')
        else:
            obj.trunk_color = props.get('trunk', '#5a4020')
            obj.trunk_is_green = props.get('trunkIsGreen', False)
            obj.bark_stripes = props.get('barkStripes', False)
            obj.leaf_color = props.get('leaf', '#2a6818')
            obj.leaf_color2 = props.get('leaf2', '#3a7828')
            obj.leaf_size = props.get('leafSize', 0.35)
            obj.leaf_density = props.get('leafDensity', 0.6)
            obj.leaf_shape = props.get('leafShape', 'sphere')
            obj.droop = props.get('droop', 0.0)
            obj.narrow = props.get('narrow', False)
            obj.fat_trunk = props.get('fatTrunk', False)
            obj.has_flowers = props.get('flower', False)
            obj.flower_color = props.get('flowerColor', '#ff80a0')
            obj.flower_density = props.get('flowerDensity', 0.15)
            obj.has_fronds = props.get('fronds', False)
            obj.has_coconuts = props.get('coconuts', False)
            obj.has_culms = props.get('culms', False)
            obj.has_rosette = props.get('rosette', False)
            obj.is_ground_cover = props.get('isGroundCover', False)
        return obj

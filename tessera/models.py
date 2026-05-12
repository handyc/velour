"""Tessera — seamless 4-edge-color square Wang tile generator.

Where the existing `tiles` app handles Wang tiles abstractly (palette
+ edge colors as set-theoretic labels), tessera is image-based: each
of the four edge "colors" is backed by a toroidally-tileable source
texture, and the 256 tiles in a complete 4-color set are produced by
inverse-distance blending those four sources together.

The key idea: when two tiles abut along a shared color, both samples
come from *the same pixel of the same source image* (because the
source images are toroidally wrapping and the IDW weights at the
boundary collapse onto the matching edge's source).  Seams therefore
cannot exist — they're a topological consequence of the construction,
not a property we have to chase by stitching.
"""

from django.db import models
from django.utils.text import slugify


class TessSet(models.Model):
    """Parameters for one generated 256-tile set.

    Output (the 4 source images and 256 tile PNGs) is derived from
    these parameters deterministically; the views regenerate on
    demand and cache to disk under MEDIA_ROOT/tessera/<slug>/.
    """

    METHOD_CHOICES = [
        ('fbm-tileable', 'fBm noise (toroidally tileable)'),
        ('hex-ca',       'Hex CA evolved (Velour-style)'),
        ('domain-warp',  'fBm + domain warp'),
    ]
    TOPOLOGY_CHOICES = [
        ('square', 'square — 4 edges, 4⁴ = 256 tiles'),
        ('hex',    "hex — 6 edges, 4⁶ = 4096 tiles"),
    ]
    BLEND_CHOICES = [
        ('idw',   'IDW blend — Tessera-style seamless math'),
        ('wedge', 'wedge cut — stained-glass aesthetic'),
    ]

    name       = models.CharField(max_length=80, unique=True)
    slug       = models.SlugField(max_length=80, unique=True)
    seed       = models.IntegerField(
        default=0,
        help_text='Master RNG seed; (seed, color_idx) keys each '
                  'source image so neighbouring colors diverge.')
    tile_px    = models.PositiveIntegerField(
        default=128,
        help_text='Output tile size in pixels (square).')
    method     = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default='fbm-tileable')
    topology   = models.CharField(
        max_length=8, choices=TOPOLOGY_CHOICES, default='square',
        help_text='Square (4 edges → 256 tiles) or hex (6 edges → '
                  '4096 tiles).')
    blend_method = models.CharField(
        max_length=8, choices=BLEND_CHOICES, default='idw',
        help_text='IDW blends the edge sources smoothly across the '
                  'interior; wedge slices each source into N triangles '
                  'around the centre.  Aesthetically very different.')
    palette    = models.JSONField(
        default=list,
        help_text='Four [r,g,b] RGB anchors, one per edge color. '
                  'If empty at save time, defaults to a four-hue '
                  'spread (warm / cool / verdant / amber).')
    blur_sigma = models.FloatField(
        default=0.0,
        help_text='Optional Gaussian blur on the composite tile, in '
                  'pixels.  0 disables.  Soft blurs hide micro-grain '
                  'mismatches between the corner-region IDW blends '
                  'in adjacent tiles.')
    blend_power = models.FloatField(
        default=2.0,
        help_text='Inverse-distance weighting power.  Higher → '
                  'sharper edge handover (tile interior reads more '
                  'as four quadrants); lower → mushier middle.  2.0 '
                  'is the classical Shepard default.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = slugify(self.name)[:80] or f'set-{self.pk or "new"}'
        if not self.palette:
            self.palette = [
                [220,  80,  40],   # 0  warm vermilion
                [ 60, 120, 210],   # 1  cool azure
                [ 80, 180,  90],   # 2  verdant
                [230, 200,  60],   # 3  amber
            ]
        super().save(*a, **kw)

    @property
    def tile_count(self):
        """4⁴=256 for square, 4⁶=4096 for hex."""
        return 4096 if self.topology == 'hex' else 256

    @property
    def edges_per_tile(self):
        return 6 if self.topology == 'hex' else 4

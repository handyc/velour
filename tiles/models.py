"""Tiles app — Wang tile sets and eventually germs of ideas.

Phase 1 (this commit): a registry of Wang tile sets and the tiles
inside them, with a simple SVG renderer. Each Tile has four edge
colors; a valid Wang tiling requires adjacent tiles to share the
same color on their shared edge.

Phase 2 (future): connect Tiles to Identity as a substrate for
"germs of ideas" — each tile gains a `concept` field, valid tilings
become chains of concepts, and Identity meditations can consume
tilings as source material. See project_tiles_app_backlog memory
note for the design sketch.

Wang tiles are named for Hao Wang (1961) and are famous as:
- A Turing-complete model of computation
- The domain of aperiodic tile sets (Jeandel-Rao 2015's 11-tile
  minimum)
- A substrate for procedural texturing and generative art
"""

from django.db import models
from django.utils.text import slugify


class TileSet(models.Model):
    """A collection of Wang tiles that can attempt to tile a plane.

    Each TileSet has a palette (the list of colors it uses on edges)
    and a collection of Tiles that use colors from that palette. The
    Phase 1 implementation treats palette as a free-form JSON list;
    future phases could enforce that each Tile's edge colors are
    drawn from the palette.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True,
        help_text='What this tile set is for — generative art, '
                  'procedural texturing, an aperiodic demo, etc.')
    palette = models.JSONField(default=list, blank=True,
        help_text='List of color names or hex codes used by this '
                  'tile set. Purely documentary for now; Phase 2 '
                  'will enforce it.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:120] or 'tileset'
            candidate = base
            n = 2
            while TileSet.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def tile_count(self):
        return self.tiles.count()


class Tile(models.Model):
    """One square Wang tile. Four edge colors — n/e/s/w.

    A valid placement in a tiling requires:
    - the `w` color of this tile to match the `e` color of the tile
      to its left (if any)
    - the `e` color to match the `w` color of the tile to its right
    - the `n` color to match the `s` color of the tile above
    - the `s` color to match the `n` color of the tile below

    Phase 2 will add a `concept` field (free-text "germ of an idea")
    so that each tile carries both an edge-color constraint AND a
    semantic payload that chains with its neighbors in valid tilings.
    """

    tileset = models.ForeignKey(TileSet, on_delete=models.CASCADE,
                                related_name='tiles')
    name = models.CharField(max_length=80, blank=True,
        help_text='Optional human label, e.g. "T1" or "corner-ne".')
    n_color = models.CharField(max_length=40,
        help_text='Top edge color (name or hex).')
    e_color = models.CharField(max_length=40,
        help_text='Right edge color.')
    s_color = models.CharField(max_length=40,
        help_text='Bottom edge color.')
    w_color = models.CharField(max_length=40,
        help_text='Left edge color.')
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tileset', 'sort_order', 'id']

    def __str__(self):
        return f'{self.tileset.slug}:{self.name or self.pk} [{self.n_color}/{self.e_color}/{self.s_color}/{self.w_color}]'

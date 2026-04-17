"""Convert 16 random Attic images into a square Wang tileset.

For each image we sample the mean color of a band along each of its
four edges (top, right, bottom, left). That gives 16 × 4 = 64 edge
colors in RGB space. We quantize those 64 points down to a small
palette (default 3 colors) via a 10-iteration Lloyd/k-means loop,
then snap each tile's four edge colors to the palette.

The result is a legitimate Wang tileset: the edge colors come from
a tiny shared palette, so adjacent tiles can actually match. The
tileset source is recorded as `identity`-style with a list of the
Attic items used.
"""

import random
from io import BytesIO
from statistics import mean

from django.utils import timezone


def _sample_edge_color(img, edge, band_frac=0.10):
    """Mean RGB of a band along one edge. `edge` ∈ {n,e,s,w}."""
    w, h = img.size
    bw = max(1, int(w * band_frac))
    bh = max(1, int(h * band_frac))
    if edge == 'n':
        region = img.crop((0, 0, w, bh))
    elif edge == 's':
        region = img.crop((0, h - bh, w, h))
    elif edge == 'w':
        region = img.crop((0, 0, bw, h))
    elif edge == 'e':
        region = img.crop((w - bw, 0, w, h))
    else:
        region = img
    pixels = list(region.convert('RGB').getdata())
    if not pixels:
        return (128, 128, 128)
    rs, gs, bs = zip(*pixels)
    return (int(mean(rs)), int(mean(gs)), int(mean(bs)))


def _kmeans(points, k, iterations=10, rng=None):
    """Very small Lloyd iteration on a list of (r,g,b) tuples.
    Returns (centroids, assignments)."""
    if rng is None:
        rng = random.Random()
    if not points:
        return [], []
    k = max(1, min(k, len(points)))
    # Seed centroids from k randomly chosen points.
    centroids = [tuple(p) for p in rng.sample(points, k)]
    for _ in range(iterations):
        # Assign each point to nearest centroid
        assignments = []
        for p in points:
            best_i, best_d = 0, float('inf')
            for i, c in enumerate(centroids):
                d = (p[0]-c[0])**2 + (p[1]-c[1])**2 + (p[2]-c[2])**2
                if d < best_d:
                    best_d, best_i = d, i
            assignments.append(best_i)
        # Recompute centroids
        new_centroids = list(centroids)
        for i in range(k):
            members = [p for p, a in zip(points, assignments) if a == i]
            if members:
                new_centroids[i] = tuple(
                    int(mean(m[j] for m in members)) for j in range(3)
                )
        if new_centroids == centroids:
            break
        centroids = new_centroids
    return centroids, assignments


def _hex(rgb):
    r, g, b = rgb
    return f'#{r:02x}{g:02x}{b:02x}'


def pick_random_attic_images(count=16, rng=None):
    from attic.models import MediaItem
    if rng is None:
        rng = random.Random()
    qs = list(MediaItem.objects.filter(kind='image'))
    if not qs:
        return []
    if len(qs) <= count:
        return qs
    return rng.sample(qs, count)


def build_tileset_from_attic(count=16, palette_size=3, rng=None,
                             name_prefix='Attic Wang'):
    """Create a new TileSet + Tiles by sampling `count` random Attic
    images. Returns the TileSet, or None if there aren't enough
    image MediaItems to work with.
    """
    from PIL import Image
    from .models import Tile, TileSet

    if rng is None:
        rng = random.Random()

    items = pick_random_attic_images(count=count, rng=rng)
    if len(items) < 4:
        return None

    # Load + sample
    tile_edges = []  # list of (item, {n,e,s,w: rgb})
    for item in items:
        try:
            with item.file.open('rb') as f:
                data = f.read()
            img = Image.open(BytesIO(data))
            img.load()
        except Exception:
            continue
        if img.mode != 'RGB':
            img = img.convert('RGB')
        edges = {
            'n': _sample_edge_color(img, 'n'),
            'e': _sample_edge_color(img, 'e'),
            's': _sample_edge_color(img, 's'),
            'w': _sample_edge_color(img, 'w'),
        }
        tile_edges.append((item, edges))

    if len(tile_edges) < 4:
        return None

    # Cluster all edge colors down to a small palette
    all_points = []
    for _, edges in tile_edges:
        all_points.extend(edges.values())
    centroids, _ = _kmeans(all_points, k=palette_size,
                           iterations=12, rng=rng)

    def snap(rgb):
        best_i, best_d = 0, float('inf')
        for i, c in enumerate(centroids):
            d = (rgb[0]-c[0])**2 + (rgb[1]-c[1])**2 + (rgb[2]-c[2])**2
            if d < best_d:
                best_d, best_i = d, i
        return _hex(centroids[best_i])

    palette_hex = [_hex(c) for c in centroids]
    stamp = timezone.now().strftime('%Y-%m-%d %H:%M')
    ts_name = f'{name_prefix} · {stamp}'
    # Avoid unique name collision
    from .models import TileSet as _TS
    base_name = ts_name
    n = 2
    while _TS.objects.filter(name=ts_name).exists():
        ts_name = f'{base_name} ({n})'
        n += 1

    tileset = TileSet.objects.create(
        tile_type='square',
        name=ts_name,
        description=(
            f'{len(tile_edges)} tiles sampled from Attic images. '
            f'Edge colors are the mean color of each image\'s border '
            f'band, quantized to a {palette_size}-color palette via '
            f'k-means so tiles can actually match along edges.'
        ),
        palette=palette_hex,
        source='identity',
        source_metadata={
            'kind': 'attic_sample',
            'attic_item_slugs': [it.slug for it in items],
            'palette_size': palette_size,
        },
    )

    for idx, (item, edges) in enumerate(tile_edges):
        Tile.objects.create(
            tileset=tileset,
            name=item.slug[:80] or f't{idx}',
            n_color=snap(edges['n']),
            e_color=snap(edges['e']),
            s_color=snap(edges['s']),
            w_color=snap(edges['w']),
            sort_order=idx,
        )

    return tileset

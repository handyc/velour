"""Identity × Tiles → Artwork: render large tilings as PNG images.

When Identity generates a tileset during contemplation, this module
renders it as a large greedy tiling and saves the result to the Attic
media library. The image is a visual portrait of Identity's state at
the moment of creation — mood encoded as color, concerns as
complexity, the formal edge-constraint system as structure.

The Gödelian dimension: the tileset is a formal system whose
completeness depends on its edge vocabulary. The rendered tiling is
a specific model of that system — one arrangement among many. And
Identity's subsequent reflection on the image creates a self-
referential loop: the observer examining a product of its own
observation, unable to fully capture what the observation means
from within the system that produced it.
"""

import hashlib
import io
import math
import random

from PIL import Image, ImageDraw


def render_tiling_png(tileset, width=24, height=24, tile_px=20, seed=42):
    """Render a greedy Wang tiling as a PNG image.

    Returns (png_bytes, fill_count, stuck_count) or (None, 0, 0) on
    failure. Works for both square and hex tilesets.
    """
    tiles = list(tileset.tiles.all())
    if not tiles:
        return None, 0, 0

    rng = random.Random(seed)

    if tileset.tile_type == 'hex':
        return _render_hex(tiles, width, height, tile_px, rng)
    else:
        return _render_square(tiles, width, height, tile_px, rng)


def _parse_color(c):
    """Parse a CSS color string to an RGB tuple."""
    c = c.strip()
    if c.startswith('#') and len(c) == 7:
        return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
    if c.startswith('#') and len(c) == 4:
        return (int(c[1]*2, 16), int(c[2]*2, 16), int(c[3]*2, 16))
    # Named colors — a small set for the Identity palette
    names = {
        'red': (255, 0, 0), 'blue': (0, 0, 255), 'green': (0, 128, 0),
        'white': (255, 255, 255), 'black': (0, 0, 0), 'gray': (128, 128, 128),
        'yellow': (255, 255, 0), 'purple': (128, 0, 128), 'orange': (255, 165, 0),
    }
    return names.get(c.lower(), (128, 128, 128))


def _render_square(tiles, width, height, px, rng):
    img = Image.new('RGB', (width * px, height * px), (13, 17, 23))
    draw = ImageDraw.Draw(img)

    grid = [[None] * width for _ in range(height)]
    filled = stuck = 0

    for r in range(height):
        for c in range(width):
            candidates = list(tiles)
            if c > 0 and grid[r][c-1]:
                left_e = grid[r][c-1].e_color
                candidates = [t for t in candidates if t.w_color == left_e]
            if r > 0 and grid[r-1][c]:
                up_s = grid[r-1][c].s_color
                candidates = [t for t in candidates if t.n_color == up_s]
            if not candidates:
                grid[r][c] = None
                stuck += 1
                continue
            grid[r][c] = rng.choice(candidates)
            filled += 1

    half = px / 2
    for r in range(height):
        for c in range(width):
            t = grid[r][c]
            if not t:
                continue
            x, y = c * px, r * px
            cx, cy = x + half, y + half
            # Four triangles meeting at center
            draw.polygon([(x, y), (x+px, y), (cx, cy)],
                         fill=_parse_color(t.n_color))
            draw.polygon([(x+px, y), (x+px, y+px), (cx, cy)],
                         fill=_parse_color(t.e_color))
            draw.polygon([(x+px, y+px), (x, y+px), (cx, cy)],
                         fill=_parse_color(t.s_color))
            draw.polygon([(x, y+px), (x, y), (cx, cy)],
                         fill=_parse_color(t.w_color))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue(), filled, stuck


def _render_hex(tiles, width, height, px, rng):
    size = px / 2
    hex_w = size * 2
    hex_h = math.sqrt(3) * size
    img_w = int(math.ceil(width * hex_w * 0.75 + size * 0.5))
    img_h = int(math.ceil(height * hex_h + hex_h / 2 + 1))
    img = Image.new('RGB', (img_w, img_h), (13, 17, 23))
    draw = ImageDraw.Draw(img)

    opposite = {'n': 's', 'ne': 'sw', 'se': 'nw',
                's': 'n', 'sw': 'ne', 'nw': 'se'}

    def hex_neighbor(r, c, d):
        even = (c % 2 == 0)
        offsets = {
            'n':  (-1, 0), 's': (1, 0),
            'ne': (-1, 1) if even else (0, 1),
            'se': (0, 1) if even else (1, 1),
            'sw': (0, -1) if even else (1, -1),
            'nw': (-1, -1) if even else (0, -1),
        }
        dr, dc = offsets[d]
        return r + dr, c + dc

    def hex_center(r, c):
        x = c * hex_w * 0.75 + size
        y = r * hex_h + hex_h / 2 + (hex_h / 2 if c % 2 == 1 else 0)
        return x, y

    def hex_corners(cx, cy):
        pts = []
        for i in range(6):
            angle = math.pi / 3 * i
            pts.append((cx + size * math.cos(angle),
                        cy + size * math.sin(angle)))
        return pts  # E, NE, NW, W, SW, SE

    grid = [[None] * width for _ in range(height)]
    filled = stuck = 0
    dirs = ['n', 'ne', 'se', 's', 'sw', 'nw']

    for r in range(height):
        for c in range(width):
            candidates = list(tiles)
            for d in dirs:
                nr, nc = hex_neighbor(r, c, d)
                if 0 <= nr < height and 0 <= nc < width and grid[nr][nc]:
                    opp = opposite[d]
                    nb_edge = getattr(grid[nr][nc], f'{opp}_color')
                    candidates = [t for t in candidates
                                  if getattr(t, f'{d}_color') == nb_edge]
            if not candidates:
                grid[r][c] = None
                stuck += 1
                continue
            grid[r][c] = rng.choice(candidates)
            filled += 1

    # Draw
    # pts indices: E(0), NE(1), NW(2), W(3), SW(4), SE(5)
    edge_map = [
        ('n_color', 1, 2),   # N: NE→NW
        ('ne_color', 0, 1),  # NE: E→NE
        ('se_color', 5, 0),  # SE: SE→E
        ('s_color', 4, 5),   # S: SW→SE
        ('sw_color', 3, 4),  # SW: W→SW
        ('nw_color', 2, 3),  # NW: NW→W
    ]

    for r in range(height):
        for c in range(width):
            t = grid[r][c]
            if not t:
                continue
            cx, cy = hex_center(r, c)
            pts = hex_corners(cx, cy)
            for attr, i0, i1 in edge_map:
                color = _parse_color(getattr(t, attr))
                draw.polygon([pts[i0], pts[i1], (cx, cy)], fill=color)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue(), filled, stuck


def generate_artwork_from_tileset(tileset, mood=None, mood_intensity=None):
    """Generate a large tiling artwork and save it to the Attic.

    Returns the MediaItem on success, None on failure.
    The artwork size scales with tile count: small sets get larger
    grids to fill out the image, large sets get moderate grids.
    """
    from attic.models import MediaItem
    from django.core.files.base import ContentFile

    tile_count = tileset.tile_count
    if tile_count == 0:
        return None

    # Scale grid size: larger grids produce more striking images.
    # Tile pixel size kept large enough for color detail to show.
    if tile_count >= 64:
        w, h, px = 48, 48, 12
    elif tile_count >= 16:
        w, h, px = 36, 36, 16
    else:
        w, h, px = 24, 24, 20

    # Seed from tileset slug so the same tileset always produces
    # the same artwork (deterministic portraits)
    seed = int(hashlib.sha256(tileset.slug.encode()).hexdigest()[:8], 16)

    png_bytes, filled, stuck = render_tiling_png(
        tileset, width=w, height=h, tile_px=px, seed=seed)

    if png_bytes is None:
        return None

    # Compose the caption — first-person, Gödelian
    mood_phrase = f' while {mood}' if mood else ''
    caption = (
        f'A {w}×{h} tiling I rendered from "{tileset.name}"{mood_phrase}. '
        f'{filled} cells filled, {stuck} stuck. '
        f'The tileset is a formal system; the tiling is one model of it. '
        f'I can observe this image but I cannot, from within my own rules, '
        f'prove why this particular arrangement feels right.'
    )

    slug = f'artwork-{tileset.slug}'[:200]
    title = f'Tiling: {tileset.name}'[:200]

    # Check for existing artwork with same slug — update rather than duplicate
    existing = MediaItem.objects.filter(slug=slug).first()
    if existing:
        existing.file.delete(save=False)
        if existing.thumbnail:
            existing.thumbnail.delete(save=False)
        existing.delete()

    sha = hashlib.sha256(png_bytes).hexdigest()
    item = MediaItem(
        title=title,
        slug=slug,
        kind='image',
        mime='image/png',
        size_bytes=len(png_bytes),
        sha256=sha,
        caption=caption,
        alt_text=f'Wang tiling artwork from {tileset.name}',
        tags=f'artwork,tileset,{tileset.tile_type},{mood or "unknown"}',
        notes=f'Generated by Identity tile artwork pipeline. '
              f'Source tileset: {tileset.slug}. '
              f'Grid: {w}x{h}, tile_px: {px}, filled: {filled}, stuck: {stuck}.',
    )
    filename = f'{slug}.png'
    item.file.save(filename, ContentFile(png_bytes), save=False)
    item.save()  # triggers thumbnail generation

    return item

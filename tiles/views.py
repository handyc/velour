import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Tile, TileSet


@login_required
def tileset_list(request):
    tilesets = TileSet.objects.prefetch_related('tiles').all()
    return render(request, 'tiles/list.html', {
        'tilesets':    tilesets,
        'total_count': tilesets.count(),
        'total_tiles': Tile.objects.count(),
    })


@login_required
def tileset_detail(request, slug):
    tileset = get_object_or_404(TileSet, slug=slug)
    tiles = list(tileset.tiles.all())
    # Also compute a small greedy tiling attempt for the detail view
    greedy = _greedy_tile_grid(tiles, width=6, height=4)

    # Ask Identity for a short philosophical commentary on this
    # tile set. Silently swallow any failure — the tiles page
    # should still work if the identity app is broken or missing.
    identity_reflection = ''
    try:
        from identity.tiles_reflection import reflect_on_tileset
        identity_reflection = reflect_on_tileset(tileset)
    except Exception:
        pass

    # Check if there's a rendered artwork in the Attic
    artwork = None
    try:
        from attic.models import MediaItem
        artwork = MediaItem.objects.filter(slug=f'artwork-{tileset.slug}').first()
    except Exception:
        pass

    return render(request, 'tiles/detail.html', {
        'tileset':            tileset,
        'tiles':              tiles,
        'greedy':             greedy,
        'identity_reflection': identity_reflection,
        'artwork':            artwork,
    })


@login_required
def tileset_add(request):
    tileset = TileSet()
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        notes = request.POST.get('notes', '').strip()
        palette_raw = request.POST.get('palette', '').strip()
        palette = [p.strip() for p in palette_raw.split(',') if p.strip()]
        tile_type = request.POST.get('tile_type', 'square')
        if not name:
            messages.error(request, 'Name is required.')
        else:
            tileset.name = name
            tileset.tile_type = tile_type if tile_type in ('square', 'hex') else 'square'
            tileset.description = description
            tileset.notes = notes
            tileset.palette = palette
            tileset.save()
            messages.success(request, f'Added tile set "{tileset.name}".')
            return redirect('tiles:detail', slug=tileset.slug)
    return render(request, 'tiles/form.html', {
        'tileset': tileset, 'action': 'Add',
    })


@login_required
@require_POST
def tileset_delete(request, slug):
    tileset = get_object_or_404(TileSet, slug=slug)
    name = tileset.name
    tileset.delete()
    messages.success(request, f'Removed "{name}".')
    return redirect('tiles:list')


@login_required
def tileset_generate(request, slug):
    tileset = get_object_or_404(TileSet, slug=slug)
    tiles = list(tileset.tiles.all())
    if tileset.tile_type == 'hex':
        tiles_json = json.dumps([
            {'id': t.pk, 'name': t.name,
             'n': t.n_color, 'ne': t.ne_color, 'se': t.se_color,
             's': t.s_color, 'sw': t.sw_color, 'nw': t.nw_color}
            for t in tiles
        ])
    else:
        tiles_json = json.dumps([
            {'id': t.pk, 'name': t.name, 'n': t.n_color, 'e': t.e_color,
             's': t.s_color, 'w': t.w_color}
            for t in tiles
        ])
    return render(request, 'tiles/generate.html', {
        'tileset':    tileset,
        'tiles_json': tiles_json,
        'tile_type':  tileset.tile_type,
    })


@login_required
@require_POST
def tileset_save_generated(request, slug):
    """Save a generated tiling as a new tileset.

    Receives the unique tiles from the JS grid and creates a new TileSet
    with those tiles. The new set is named after the source + dimensions.
    """
    source = get_object_or_404(TileSet, slug=slug)
    grid_w = request.POST.get('grid_w', '16')
    grid_h = request.POST.get('grid_h', '16')

    try:
        tiles_data = json.loads(request.POST.get('grid_json', '[]'))
    except (json.JSONDecodeError, TypeError):
        messages.error(request, 'Invalid grid data.')
        return redirect('tiles:generate', slug=slug)

    if not tiles_data:
        messages.error(request, 'No tiles in the generated grid.')
        return redirect('tiles:generate', slug=slug)

    from django.utils import timezone
    now = timezone.now()
    name = f'{source.name} ({grid_w}×{grid_h} blocks {now:%H:%M:%S})'
    ts = TileSet(
        name=name,
        description=f'Meta-tiles derived from {source.name}: each tile represents a block of the original tiling.',
        palette=source.palette,
        source='operator',
        notes=f'Derived from tileset "{source.slug}".',
    )
    ts.save()

    for i, td in enumerate(tiles_data):
        Tile.objects.create(
            tileset=ts,
            name=f'T{i+1}',
            n_color=td.get('n', ''),
            e_color=td.get('e', ''),
            s_color=td.get('s', ''),
            w_color=td.get('w', ''),
            sort_order=i,
        )

    messages.success(request, f'Created "{ts.name}" with {len(tiles_data)} unique tiles.')
    return redirect('tiles:detail', slug=ts.slug)


@login_required
@require_POST
def tileset_generate_complete_hex(request, slug):
    """Generate all 64 tiles for a complete 2-color hex Wang tileset."""
    tileset = get_object_or_404(TileSet, slug=slug)
    if tileset.tile_type != 'hex':
        messages.error(request, 'Only hex tilesets can generate a complete set.')
        return redirect('tiles:detail', slug=slug)

    palette = tileset.palette
    if len(palette) < 2:
        messages.error(request, 'Need at least 2 colors in the palette.')
        return redirect('tiles:detail', slug=slug)

    c0, c1 = palette[0], palette[1]
    colors = [c0, c1]

    # Delete existing tiles to regenerate
    tileset.tiles.all().delete()

    # Generate all 2^6 = 64 combinations
    count = 0
    for bits in range(64):
        n  = colors[(bits >> 5) & 1]
        ne = colors[(bits >> 4) & 1]
        se = colors[(bits >> 3) & 1]
        s  = colors[(bits >> 2) & 1]
        sw = colors[(bits >> 1) & 1]
        nw = colors[bits & 1]
        Tile.objects.create(
            tileset=tileset,
            name=f'H{count+1}',
            n_color=n, ne_color=ne, se_color=se,
            s_color=s, sw_color=sw, nw_color=nw,
            sort_order=count,
        )
        count += 1

    messages.success(request, f'Generated {count} tiles (complete 2-color hex set).')
    return redirect('tiles:detail', slug=slug)


@login_required
@require_POST
def tileset_render_artwork(request, slug):
    """Render a tileset as a PNG artwork and save to Attic."""
    tileset = get_object_or_404(TileSet, slug=slug)
    try:
        from identity.tile_artwork import generate_artwork_from_tileset
        from identity.models import Identity
        identity = Identity.get_self()
        item = generate_artwork_from_tileset(
            tileset, mood=identity.mood,
            mood_intensity=identity.mood_intensity)
        if item:
            messages.success(request,
                f'Rendered artwork "{item.title}" ({item.size_bytes} bytes).')
        else:
            messages.error(request, 'No tiles to render.')
    except Exception as e:
        messages.error(request, f'Artwork render failed: {e}')
    return redirect('tiles:detail', slug=slug)


def _greedy_tile_grid(tiles, width=6, height=4):
    """Attempt a greedy Wang tiling from the top-left. Returns a 2D
    list (rows of tile dicts or None). Does NOT guarantee a valid
    tiling — greedy search can paint itself into a corner. That's
    fine for a Phase 1 demo; the whole point is to show that some
    tile sets tile cleanly and others don't."""
    if not tiles:
        return []

    import random
    rng = random.Random(42)

    grid = [[None for _ in range(width)] for _ in range(height)]

    for r in range(height):
        for c in range(width):
            candidates = list(tiles)
            # Constraint: west edge must match east edge of left neighbor
            if c > 0 and grid[r][c - 1] is not None:
                left = grid[r][c - 1]
                candidates = [t for t in candidates if t.w_color == left.e_color]
            # Constraint: north edge must match south edge of upper neighbor
            if r > 0 and grid[r - 1][c] is not None:
                up = grid[r - 1][c]
                candidates = [t for t in candidates if t.n_color == up.s_color]
            if not candidates:
                grid[r][c] = None
                continue
            grid[r][c] = rng.choice(candidates)

    return grid

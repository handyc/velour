from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Tile, TileSet


@login_required
def tileset_list(request):
    tilesets = TileSet.objects.all()
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

    return render(request, 'tiles/detail.html', {
        'tileset':            tileset,
        'tiles':              tiles,
        'greedy':             greedy,
        'identity_reflection': identity_reflection,
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
        if not name:
            messages.error(request, 'Name is required.')
        else:
            tileset.name = name
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

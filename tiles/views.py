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
def tileset_from_attic(request):
    """Pick 16 random Attic images and build a Wang tileset from them."""
    from .from_attic import build_tileset_from_attic

    try:
        count = int(request.POST.get('count', 16))
    except (TypeError, ValueError):
        count = 16
    count = max(4, min(64, count))

    try:
        palette_size = int(request.POST.get('palette_size', 3))
    except (TypeError, ValueError):
        palette_size = 3
    palette_size = max(2, min(6, palette_size))

    tileset = build_tileset_from_attic(
        count=count, palette_size=palette_size,
    )
    if tileset is None:
        messages.error(request, 'Not enough image items in Attic to build a tileset.')
        return redirect('tiles:list')
    messages.success(
        request,
        f'Built "{tileset.name}" from {tileset.tile_count} Attic images '
        f'(palette of {palette_size}).',
    )
    return redirect('tiles:detail', slug=tileset.slug)


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


# ── CA-Wang runner ───────────────────────────────────────────────────
#
# Each tile in the TileSet can carry its own K=4 hex CA RuleSet. The
# runner assembles a Wang tiling (greedy; supports both square 4-edge
# and hex 6-edge tilesets), embeds each placed tile's rule + initial
# grid, and ships a small JS engine that steps every tile in lockstep.
# The coupling-mode query param picks how boundaries behave:
#   * decoupled — each tile's edge cells see colour 0 across the
#     border (every tile is its own independent universe).
#   * coupled   — boundary cells of adjacent tiles share state, so
#     the assembled lattice runs as a single big CA whose rule
#     changes per tile-region.

import base64
import random as _rng

CA_TILES_DEFAULT_W_SQUARE = 4
CA_TILES_DEFAULT_H_SQUARE = 4
CA_TILES_DEFAULT_W_HEX = 16
CA_TILES_DEFAULT_H_HEX = 16
CA_TILES_MAX = 16
CA_VALID_CELLS = (8, 12, 16, 24, 32)
CA_DEFAULT_CELLS = 16

# Speciation defaults — same shape as the tournament's init mutation,
# small enough to keep the children family-resemblance close to the
# parent while big enough that each variant is visibly distinct.
SPECIATE_DEFAULT_RATE = 0.01
SPECIATE_MAX_COUNT = 256


def _packed_for(rs):
    """Materialise an automaton.RuleSet into a 4,096-byte K=4 packed
    blob, base64-encoded for transport in the page."""
    from automaton.packed import PackedRuleset
    explicit = [
        {'s': er.self_color,
         'n': [er.n0_color, er.n1_color, er.n2_color, er.n3_color,
               er.n4_color, er.n5_color],
         'r': er.result_color}
        for er in rs.exact_rules.all().order_by('priority')
    ]
    packed = PackedRuleset.from_explicit(explicit, n_colors=4)
    return base64.b64encode(bytes(packed.data)).decode('ascii')


def _packed_initial_grid(initial_grid, cells):
    """Encode an optional ``cells × cells`` init grid as base64.

    Empty or shape-mismatched inputs return '' so the JS falls back to
    random at render time. The rule itself is grid-agnostic — only the
    initial state needs to match the chosen ``cells`` value.
    """
    if not initial_grid:
        return ''
    if len(initial_grid) != cells:
        return ''
    flat = bytearray(cells * cells)
    for r in range(cells):
        row = initial_grid[r] if r < len(initial_grid) else []
        if len(row) != cells:
            return ''
        for c in range(cells):
            flat[r * cells + c] = int(row[c]) & 3
    return base64.b64encode(bytes(flat)).decode('ascii')


def _greedy_hex_tile_grid(tiles, width=4, height=4):
    """Greedy hex Wang assembly with 6-edge matching.

    Flat-top hex outer lattice, offset-column convention (matches the
    inner CA neighbour order used by s3lab / automaton / firmware).
    For each cell (c, r) we look at every already-placed neighbour
    among {N, NW, NE, S, SW, SE} and keep only candidate tiles whose
    matching edge agrees. Greedy can paint into a corner — empty
    cells signal "no valid placement." Same grid_layout shape as the
    square version: ``grid[r][c]`` is a Tile or None.
    """
    if not tiles:
        return []
    rng = _rng.Random(42)

    grid = [[None for _ in range(width)] for _ in range(height)]

    def neighbours(c, r):
        """Yield (other_c, other_r, my_edge_attr, their_edge_attr) for
        every neighbour of (c, r). Match flat-top column-offset
        convention: even columns sit one half-row above their odd
        siblings."""
        even = (c % 2) == 0
        return [
            (c,   r - 1,                  'n_color',  's_color'),    # N
            (c+1, r - 1 if even else r,   'ne_color', 'sw_color'),   # NE
            (c+1, r if even else r + 1,   'se_color', 'nw_color'),   # SE
            (c,   r + 1,                  's_color',  'n_color'),    # S
            (c-1, r if even else r + 1,   'sw_color', 'ne_color'),   # SW
            (c-1, r - 1 if even else r,   'nw_color', 'se_color'),   # NW
        ]

    for r in range(height):
        for c in range(width):
            candidates = list(tiles)
            for nc, nr, my_attr, their_attr in neighbours(c, r):
                if 0 <= nr < height and 0 <= nc < width:
                    placed = grid[nr][nc]
                    if placed is not None:
                        target = getattr(placed, their_attr) or ''
                        candidates = [
                            t for t in candidates
                            if (getattr(t, my_attr) or '') == target
                        ]
            if not candidates:
                grid[r][c] = None
                continue
            grid[r][c] = rng.choice(candidates)

    return grid


@login_required
def tile_bindings(request, slug):
    """In-page UI to attach an automaton.RuleSet to each Tile.

    The CA-runner needs ``Tile.ca_ruleset`` set to bring tiles to
    life; rather than make the operator dig through the admin, this
    view shows a per-tile dropdown of every K=4 RuleSet and saves
    them in one form.
    """
    tileset = get_object_or_404(TileSet, slug=slug)
    tiles_qs = list(tileset.tiles.all())

    from automaton.models import RuleSet
    rulesets = list(
        RuleSet.objects.filter(n_colors=4).order_by('-created_at')
    )

    if request.method == 'POST':
        from automaton.models import RuleSet as _RS
        valid_pks = set(_RS.objects.filter(n_colors=4).values_list('pk', flat=True))
        n_changed = 0
        for t in tiles_qs:
            raw = request.POST.get(f'tile_{t.pk}_ruleset', '').strip()
            new_pk = None
            if raw and raw != 'none':
                try:
                    pk = int(raw)
                    if pk in valid_pks:
                        new_pk = pk
                except ValueError:
                    pass
            if t.ca_ruleset_id != new_pk:
                t.ca_ruleset_id = new_pk
                t.save(update_fields=['ca_ruleset'])
                n_changed += 1
        if n_changed:
            messages.success(
                request,
                f'Updated CA bindings for {n_changed} tile{"s" if n_changed != 1 else ""}.',
            )
        else:
            messages.info(request, 'No binding changes.')
        return redirect('tiles:bindings', slug=tileset.slug)

    n_bound = sum(1 for t in tiles_qs if t.ca_ruleset_id is not None)
    return render(request, 'tiles/bindings.html', {
        'tileset':       tileset,
        'tiles':         tiles_qs,
        'rulesets':      rulesets,
        'n_bound':       n_bound,
        'speciate_rate': SPECIATE_DEFAULT_RATE,
    })


def _ruleset_to_packed(rs):
    """Materialise an automaton.RuleSet's ExactRules into a PackedRuleset."""
    from automaton.packed import PackedRuleset
    explicit = [
        {'s': er.self_color,
         'n': [er.n0_color, er.n1_color, er.n2_color, er.n3_color,
               er.n4_color, er.n5_color],
         'r': er.result_color}
        for er in rs.exact_rules.all().order_by('priority')
    ]
    return PackedRuleset.from_explicit(explicit, n_colors=4)


def _persist_packed_as_ruleset(packed, name, palette, source_metadata):
    """Save a PackedRuleset blob as a new automaton.RuleSet + ExactRule
    rows. Returns the created RuleSet."""
    from automaton.models import ExactRule, RuleSet as _RS
    from django.db import transaction
    explicit = packed.to_explicit(skip_identity=True)
    with transaction.atomic():
        rs = _RS.objects.create(
            name=name,
            description=source_metadata.get('description', ''),
            n_colors=4,
            source='operator',
            palette=palette,
            source_metadata=source_metadata,
        )
        ExactRule.objects.bulk_create([
            ExactRule(
                ruleset=rs,
                self_color=er['s'],
                n0_color=er['n'][0], n1_color=er['n'][1],
                n2_color=er['n'][2], n3_color=er['n'][3],
                n4_color=er['n'][4], n5_color=er['n'][5],
                result_color=er['r'],
                priority=i,
            )
            for i, er in enumerate(explicit)
        ])
    return rs


@login_required
def tile_speciate(request, slug):
    """Bulk-speciate a seed RuleSet into N variants and bind them
    one-per-tile to this TileSet's tiles.

    Each variant = the seed's 4,096-byte packed genome with a small
    fraction of its 16,384 lookup entries randomly reassigned. A
    mutation rate of 0.01 flips ~164 entries — the family resemblance
    is obvious, the visual differences are visible. The result is a
    population of cousins one mutation step away from a single
    ancestor, which is exactly what you want filling a Wang lattice
    so neighbouring tiles look related but not identical.
    """
    tileset = get_object_or_404(TileSet, slug=slug)
    tiles_qs = list(tileset.tiles.all())

    from automaton.models import RuleSet as _RS
    rulesets = list(_RS.objects.filter(n_colors=4).order_by('-created_at'))

    if request.method == 'POST':
        seed_pk_raw = request.POST.get('seed_pk', '').strip()
        try:
            seed_pk = int(seed_pk_raw)
            seed = _RS.objects.get(pk=seed_pk, n_colors=4)
        except (ValueError, _RS.DoesNotExist):
            messages.error(request, 'Pick a valid K=4 seed RuleSet.')
            return redirect('tiles:speciate', slug=tileset.slug)

        try:
            count = int(request.POST.get('count', len(tiles_qs)))
        except ValueError:
            count = len(tiles_qs)
        count = max(1, min(SPECIATE_MAX_COUNT, count))

        try:
            rate = float(request.POST.get('rate', SPECIATE_DEFAULT_RATE))
        except ValueError:
            rate = SPECIATE_DEFAULT_RATE
        rate = max(0.0, min(1.0, rate))

        try:
            rng_seed = int(request.POST.get('rng_seed', 0))
        except ValueError:
            rng_seed = 0

        replace = request.POST.get('replace_existing') == '1'
        bind_to_tiles = request.POST.get('bind_to_tiles', '1') == '1'

        rng = _rng.Random(rng_seed)
        seed_packed = _ruleset_to_packed(seed)
        seed_palette = list(seed.palette) if seed.palette else []

        new_rulesets = []
        for i in range(count):
            child = seed_packed.mutate(rate=rate, rng=rng)
            child_name = f'{seed.name} spec-{i+1:03d}'
            # Defend against a collision (e.g. if the user re-runs).
            while _RS.objects.filter(name=child_name).exists():
                child_name = f'{seed.name} spec-{i+1:03d}-{_rng.Random().randrange(1000):03d}'
            rs = _persist_packed_as_ruleset(
                packed=child,
                name=child_name,
                palette=seed_palette,
                source_metadata={
                    'origin':         'speciation',
                    'parent_pk':      seed.pk,
                    'parent_slug':    seed.slug,
                    'parent_name':    seed.name,
                    'mutation_rate':  rate,
                    'spec_index':     i + 1,
                    'rng_seed':       rng_seed,
                    'description':    f'Speciated from {seed.name} '
                                      f'(rate={rate}, index {i+1}/{count}).',
                },
            )
            new_rulesets.append(rs)

        if bind_to_tiles and tiles_qs:
            n_bound = 0
            for i, tile in enumerate(tiles_qs):
                if i >= len(new_rulesets):
                    break
                if not replace and tile.ca_ruleset_id is not None:
                    continue
                tile.ca_ruleset = new_rulesets[i]
                tile.save(update_fields=['ca_ruleset'])
                n_bound += 1
            messages.success(
                request,
                f'Speciated {len(new_rulesets)} variants from "{seed.name}" '
                f'(rate={rate}); bound {n_bound} to tiles.',
            )
        else:
            messages.success(
                request,
                f'Speciated {len(new_rulesets)} variants from "{seed.name}" '
                f'(rate={rate}). Not bound to tiles.',
            )

        return redirect('tiles:bindings', slug=tileset.slug)

    return render(request, 'tiles/speciate.html', {
        'tileset':       tileset,
        'tile_count':    len(tiles_qs),
        'rulesets':      rulesets,
        'default_count': len(tiles_qs),
        'default_rate':  SPECIATE_DEFAULT_RATE,
    })


def _palette_for(tile, ts):
    """Pick a palette for one tile: prefer the tile's CA-RuleSet
    palette, fall back to the TileSet's documentary palette, fall back
    to a sensible 4-colour default. Always returns 4 hex strings."""
    pal = []
    if tile.ca_ruleset and tile.ca_ruleset.palette:
        pal = list(tile.ca_ruleset.palette)
    elif ts.palette:
        pal = list(ts.palette)
    while len(pal) < 4:
        pal.append(['#0d1117', '#58a6ff', '#f85149', '#2ea043'][len(pal)])
    return pal[:4]


@login_required
def ca_runner(request, slug):
    """Render the live CA-Wang tiling for this TileSet."""
    tileset = get_object_or_404(TileSet, slug=slug)
    is_hex = tileset.tile_type == 'hex'

    tiles = list(tileset.tiles.all())
    if is_hex:
        default_w, default_h = CA_TILES_DEFAULT_W_HEX, CA_TILES_DEFAULT_H_HEX
    else:
        default_w, default_h = CA_TILES_DEFAULT_W_SQUARE, CA_TILES_DEFAULT_H_SQUARE
    try:
        w = int(request.GET.get('w', default_w))
        h = int(request.GET.get('h', default_h))
    except ValueError:
        w, h = default_w, default_h
    w = max(1, min(CA_TILES_MAX, w))
    h = max(1, min(CA_TILES_MAX, h))

    try:
        cells = int(request.GET.get('cells', CA_DEFAULT_CELLS))
    except ValueError:
        cells = CA_DEFAULT_CELLS
    if cells not in CA_VALID_CELLS:
        cells = CA_DEFAULT_CELLS

    coupling = request.GET.get('coupling') or 'decoupled'
    if coupling not in ('decoupled', 'coupled'):
        coupling = 'decoupled'

    if is_hex:
        grid_layout = _greedy_hex_tile_grid(tiles, width=w, height=h)
    else:
        grid_layout = _greedy_tile_grid(tiles, width=w, height=h)

    # One payload per distinct tile id — duplicates in the layout
    # share the same rule + initial state on the JS side.
    tile_payload = {}
    layout_ids = []
    for row in grid_layout:
        layout_row = []
        for placed in row:
            if placed is None:
                layout_row.append(None)
                continue
            tid = placed.id
            if tid not in tile_payload:
                base = {
                    'name':    placed.name or f't{tid}',
                    'palette': _palette_for(placed, tileset),
                    # All edge colours; templates only use the
                    # ones that exist for the tileset's tile_type.
                    'n_color':  placed.n_color,
                    'e_color':  placed.e_color,
                    's_color':  placed.s_color,
                    'w_color':  placed.w_color,
                    'ne_color': placed.ne_color,
                    'se_color': placed.se_color,
                    'sw_color': placed.sw_color,
                    'nw_color': placed.nw_color,
                }
                if placed.ca_ruleset:
                    base.update({
                        'has_ca':   True,
                        'rule_b64': _packed_for(placed.ca_ruleset),
                        'init_b64': _packed_initial_grid(placed.ca_initial_grid, cells),
                    })
                else:
                    base['has_ca'] = False
                tile_payload[tid] = base
            layout_row.append(tid)
        layout_ids.append(layout_row)

    n_ca_tiles = sum(1 for t in tiles if t.ca_ruleset_id is not None)

    return render(request, 'tiles/ca_runner.html', {
        'tileset':       tileset,
        'tile_type':     tileset.tile_type,
        'is_hex':        is_hex,
        'w':             w,
        'h':             h,
        'coupling':      coupling,
        'tile_grid_w':   cells,
        'tile_grid_h':   cells,
        'cells':         cells,
        'cells_choices': CA_VALID_CELLS,
        'tile_payload':  tile_payload,
        'layout_ids':    layout_ids,
        'n_ca_tiles':    n_ca_tiles,
        'has_layout':    any(any(c is not None for c in row) for row in grid_layout),
    })

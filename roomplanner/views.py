import json
import socket
import urllib.request
import urllib.error

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone as djtz
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .evolution import apply_result, evolve
from .fitness import score_room
from .models import (
    Constraint, Feature, FurniturePiece, Placement, Room,
)


FEATURE_COLORS = {
    'door':     '#f0883e',
    'window':   '#58a6ff',
    'outlet':   '#f85149',
    'vent':     '#a5a5a5',
    'radiator': '#db6d28',
    'pillar':   '#6e7681',
    'sink':     '#58a6ff',
    'ethernet': '#3fb950',
    'other':    '#8b949e',
}

PIECE_COLORS = {
    'desk':       '#30363d',
    'chair':      '#21262d',
    'shelf':      '#484f58',
    'cabinet':    '#484f58',
    'rack':       '#6e7681',
    'aquarium':   '#1f6feb',
    'lightbox':   '#d29922',
    'breadboard': '#238636',
    'storage':    '#3d444d',
    'other':      '#30363d',
}


def _placement_color(placement):
    return PIECE_COLORS.get(placement.piece.kind, '#30363d')


def _feature_color(feature):
    return FEATURE_COLORS.get(feature.kind, '#8b949e')


# ---------------------------------------------------------------- pages


def index(request):
    rooms = list(Room.objects.all())
    pieces_count = FurniturePiece.objects.count()
    return render(request, 'roomplanner/index.html', {
        'rooms':        rooms,
        'pieces_count': pieces_count,
    })


def room_detail(request, slug):
    room = get_object_or_404(Room, slug=slug)
    features = list(room.features.all())
    placements = list(room.placements.select_related('piece').all())
    constraints = list(room.constraints.filter(active=True))

    feature_items = [{
        'id':     f.id,
        'kind':   f.kind,
        'label':  f.label or f.get_kind_display(),
        'x':     f.x_cm,
        'y':     f.y_cm,
        'w':     f.width_cm,
        'h':     f.depth_cm,
        'fill':  _feature_color(f),
    } for f in features]

    placement_items = []
    for p in placements:
        w_cm, d_cm = p.footprint_cm
        placement_items.append({
            'id':        p.id,
            'piece_id':  p.piece_id,
            'label':     p.label or p.piece.name,
            'x':         p.x_cm,
            'y':         p.y_cm,
            'rot':       p.rotation_deg,
            'w':         w_cm,
            'h':         d_cm,
            'fill':      _placement_color(p),
        })

    # Catalog dropdown for "Add from catalog"
    catalog = list(FurniturePiece.objects.all().values(
        'id', 'slug', 'name', 'kind',
        'width_cm', 'depth_cm', 'height_cm',
        'heat_watts', 'needs_outlet',
    ))

    # Map the room's north direction onto each SVG edge (top/right/bottom/left).
    edge_labels = _edge_labels(room.north_direction)

    return render(request, 'roomplanner/room_detail.html', {
        'room':         room,
        'features':     feature_items,
        'placements':   placement_items,
        'catalog':      catalog,
        'constraints':  constraints,
        'feature_kinds':    Feature.KIND_CHOICES,
        'piece_kinds':      FurniturePiece.KIND_CHOICES,
        'north_choices':    Room.NORTH_CHOICES,
        'edge_labels':      edge_labels,
    })


def _edge_labels(north_direction):
    """Return {top: 'N', right: 'E', bottom: 'S', left: 'W'} rotated for
    the room's north_direction choice."""
    cycle = ['N', 'E', 'S', 'W']
    shifts = {
        Room.NORTH_UP:    0,  # N=top, E=right, S=bottom, W=left
        Room.NORTH_RIGHT: 3,  # N=right, E=bottom, S=left, W=top
        Room.NORTH_DOWN:  2,
        Room.NORTH_LEFT:  1,
    }
    s = shifts.get(north_direction, 0)
    # positions in clockwise order: top, right, bottom, left
    return {
        'top':    cycle[(0 + s) % 4],
        'right':  cycle[(1 + s) % 4],
        'bottom': cycle[(2 + s) % 4],
        'left':   cycle[(3 + s) % 4],
    }


def catalog(request):
    pieces = list(FurniturePiece.objects.all())
    return render(request, 'roomplanner/catalog.html', {'pieces': pieces})


# ---------------------------------------------------------------- API


def _json(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except ValueError:
        return {}


def _as_int(v, default=0, min_=0, max_=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if min_ is not None and n < min_:
        n = min_
    if max_ is not None and n > max_:
        n = max_
    return n


def _clamp_position(room, x, y, w, h):
    """Keep an item with footprint (w, h) inside the room, allowing its
    bottom-right to touch the far wall."""
    max_x = max(0, room.width_cm - w)
    max_y = max(0, room.length_cm - h)
    return (max(0, min(x, max_x)), max(0, min(y, max_y)))


@login_required
@require_POST
def api_placement_update(request, slug, pk):
    room = get_object_or_404(Room, slug=slug)
    p = get_object_or_404(Placement, pk=pk, room=room)
    data = _json(request)

    if 'x_cm' in data or 'y_cm' in data:
        w, h = p.footprint_cm
        # new rotation wins for footprint calc if supplied simultaneously
        new_rot = _as_int(data.get('rotation_deg', p.rotation_deg),
                          default=p.rotation_deg) % 360
        if new_rot in (90, 270):
            w, h = p.piece.depth_cm, p.piece.width_cm
        else:
            w, h = p.piece.width_cm, p.piece.depth_cm
        x, y = _clamp_position(
            room,
            _as_int(data.get('x_cm', p.x_cm), default=p.x_cm),
            _as_int(data.get('y_cm', p.y_cm), default=p.y_cm),
            w, h,
        )
        p.x_cm, p.y_cm = x, y

    if 'rotation_deg' in data:
        rot = _as_int(data['rotation_deg'], default=0) % 360
        # snap to 0/90/180/270
        p.rotation_deg = min([0, 90, 180, 270], key=lambda v: abs(v - rot))

    if 'label' in data:
        p.label = str(data['label'])[:120]

    p.save()
    w_cm, d_cm = p.footprint_cm
    return JsonResponse({
        'ok':    True,
        'id':    p.id,
        'x':     p.x_cm, 'y': p.y_cm,
        'w':     w_cm, 'h': d_cm,
        'rot':   p.rotation_deg,
        'label': p.label or p.piece.name,
    })


@login_required
@require_POST
def api_placement_delete(request, slug, pk):
    room = get_object_or_404(Room, slug=slug)
    p = get_object_or_404(Placement, pk=pk, room=room)
    p.delete()
    return JsonResponse({'ok': True, 'id': pk})


@login_required
@require_POST
def api_placement_add(request, slug):
    room = get_object_or_404(Room, slug=slug)
    data = _json(request)

    piece_id = data.get('piece_id')
    piece = get_object_or_404(FurniturePiece, pk=piece_id)

    rot = _as_int(data.get('rotation_deg', 0)) % 360
    w = piece.depth_cm if rot in (90, 270) else piece.width_cm
    h = piece.width_cm if rot in (90, 270) else piece.depth_cm

    # Default to room centre if caller didn't specify
    x = _as_int(data.get('x_cm', max(0, (room.width_cm - w) // 2)))
    y = _as_int(data.get('y_cm', max(0, (room.length_cm - h) // 2)))
    x, y = _clamp_position(room, x, y, w, h)

    p = Placement.objects.create(
        room=room, piece=piece,
        label=str(data.get('label', ''))[:120],
        x_cm=x, y_cm=y, rotation_deg=rot,
    )
    return JsonResponse({
        'ok':       True,
        'id':       p.id,
        'piece_id': piece.id,
        'x':        p.x_cm, 'y': p.y_cm,
        'w':        w, 'h': h,
        'rot':      p.rotation_deg,
        'label':    p.label or p.piece.name,
        'fill':     _placement_color(p),
    })


@login_required
@require_POST
def api_feature_update(request, slug, pk):
    room = get_object_or_404(Room, slug=slug)
    f = get_object_or_404(Feature, pk=pk, room=room)
    data = _json(request)

    if 'width_cm' in data:
        f.width_cm = _as_int(data['width_cm'], default=f.width_cm, min_=1)
    if 'depth_cm' in data:
        f.depth_cm = _as_int(data['depth_cm'], default=f.depth_cm, min_=1)

    if 'x_cm' in data or 'y_cm' in data:
        x, y = _clamp_position(
            room,
            _as_int(data.get('x_cm', f.x_cm), default=f.x_cm),
            _as_int(data.get('y_cm', f.y_cm), default=f.y_cm),
            f.width_cm, f.depth_cm,
        )
        f.x_cm, f.y_cm = x, y

    if 'label' in data:
        f.label = str(data['label'])[:80]

    f.save()
    return JsonResponse({
        'ok':    True,
        'id':    f.id,
        'x':     f.x_cm, 'y': f.y_cm,
        'w':     f.width_cm, 'h': f.depth_cm,
        'label': f.label or f.get_kind_display(),
    })


@login_required
@require_POST
def api_feature_delete(request, slug, pk):
    room = get_object_or_404(Room, slug=slug)
    f = get_object_or_404(Feature, pk=pk, room=room)
    f.delete()
    return JsonResponse({'ok': True, 'id': pk})


@login_required
@require_POST
def api_feature_add(request, slug):
    room = get_object_or_404(Room, slug=slug)
    data = _json(request)

    kind = data.get('kind', 'other')
    valid_kinds = {k for k, _ in Feature.KIND_CHOICES}
    if kind not in valid_kinds:
        kind = 'other'

    w = _as_int(data.get('width_cm', 30), default=30, min_=1)
    h = _as_int(data.get('depth_cm', 10), default=10, min_=1)
    x = _as_int(data.get('x_cm', max(0, (room.width_cm - w) // 2)))
    y = _as_int(data.get('y_cm', max(0, (room.length_cm - h) // 2)))
    x, y = _clamp_position(room, x, y, w, h)

    f = Feature.objects.create(
        room=room, kind=kind,
        label=str(data.get('label', ''))[:80],
        x_cm=x, y_cm=y, width_cm=w, depth_cm=h,
    )
    return JsonResponse({
        'ok':    True,
        'id':    f.id,
        'kind':  f.kind,
        'x':     f.x_cm, 'y': f.y_cm,
        'w':     f.width_cm, 'h': f.depth_cm,
        'label': f.label or f.get_kind_display(),
        'fill':  _feature_color(f),
    })


@login_required
@require_POST
def api_piece_add(request):
    """Create a new FurniturePiece (catalog entry). Idempotent on slug."""
    data = _json(request)

    name = str(data.get('name', '')).strip()
    if not name:
        return JsonResponse({'ok': False, 'error': 'name required'}, status=400)

    kind = data.get('kind', 'other')
    valid_kinds = {k for k, _ in FurniturePiece.KIND_CHOICES}
    if kind not in valid_kinds:
        kind = 'other'

    base_slug = slugify(name) or 'piece'
    # Avoid collisions — append -2, -3... if needed
    slug = base_slug
    i = 2
    while FurniturePiece.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{i}"
        i += 1

    piece = FurniturePiece.objects.create(
        slug=slug,
        name=name[:120],
        kind=kind,
        width_cm=_as_int(data.get('width_cm', 60), default=60, min_=1),
        depth_cm=_as_int(data.get('depth_cm', 40), default=40, min_=1),
        height_cm=_as_int(data.get('height_cm', 0), default=0),
        heat_watts=_as_int(data.get('heat_watts', 0), default=0),
        needs_outlet=bool(data.get('needs_outlet', False)),
        notes=str(data.get('notes', ''))[:500],
    )
    return JsonResponse({
        'ok':            True,
        'id':            piece.id,
        'slug':          piece.slug,
        'name':          piece.name,
        'kind':          piece.kind,
        'width_cm':      piece.width_cm,
        'depth_cm':      piece.depth_cm,
        'height_cm':     piece.height_cm,
        'heat_watts':    piece.heat_watts,
        'needs_outlet':  piece.needs_outlet,
    })


@login_required
@require_POST
def api_room_update(request, slug):
    """Update per-room settings: north_direction, name, notes,
    latitude, longitude. Dimensions stay admin-only for now."""
    room = get_object_or_404(Room, slug=slug)
    data = _json(request)

    if 'north_direction' in data:
        valid = {k for k, _ in Room.NORTH_CHOICES}
        nd = data['north_direction']
        if nd in valid:
            room.north_direction = nd

    if 'name' in data:
        room.name = str(data['name'])[:120]

    if 'notes' in data:
        room.notes = str(data['notes'])[:2000]

    if 'latitude' in data:
        try:   room.latitude = float(data['latitude'])
        except (TypeError, ValueError):  pass
    if 'longitude' in data:
        try:   room.longitude = float(data['longitude'])
        except (TypeError, ValueError):  pass

    if 'location_city' in data:
        room.location_city = str(data['location_city'])[:120]

    room.save()
    return JsonResponse({
        'ok':              True,
        'north_direction': room.north_direction,
        'edge_labels':     _edge_labels(room.north_direction),
        'latitude':        room.latitude,
        'longitude':       room.longitude,
        'location_city':   room.location_city,
    })


@login_required
@require_POST
def api_room_locate(request, slug):
    """Hit ip-api.com from the server side to geolocate the lab's
    public IP, and store the result on the room."""
    room = get_object_or_404(Room, slug=slug)

    url = 'http://ip-api.com/json/?fields=status,message,country,city,lat,lon,query'
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'velour-roomplanner/1.0',
        })
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = resp.read().decode('utf-8')
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        return JsonResponse({
            'ok':    False,
            'error': f'geolocation request failed: {exc}',
        }, status=502)

    try:
        payload = json.loads(body)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'bad geolocation response'},
                            status=502)

    if payload.get('status') != 'success':
        return JsonResponse({
            'ok':    False,
            'error': payload.get('message') or 'geolocation unsuccessful',
        }, status=502)

    room.latitude  = payload.get('lat')
    room.longitude = payload.get('lon')
    city   = payload.get('city') or ''
    country = payload.get('country') or ''
    room.location_city = (
        f"{city}, {country}".strip(', ')[:120] if (city or country) else ''
    )
    room.location_detected_at = djtz.now()
    room.save(update_fields=[
        'latitude', 'longitude', 'location_city', 'location_detected_at',
    ])

    return JsonResponse({
        'ok':                  True,
        'latitude':            room.latitude,
        'longitude':           room.longitude,
        'location_city':       room.location_city,
        'public_ip':           payload.get('query'),
        'detected_at':         room.location_detected_at.isoformat(),
    })


def api_room_score(request, slug):
    """Score the room's current layout against its active constraints.
    GET so the UI can call it freely on button-press."""
    room = get_object_or_404(Room, slug=slug)
    return JsonResponse(score_room(room))


@login_required
@require_POST
def api_room_evolve(request, slug):
    """Run a small GA search and persist the best candidate. Returns
    the changes list + fresh score so the editor can patch placements
    in place."""
    room = get_object_or_404(Room, slug=slug)
    data = _json(request)

    generations = _as_int(data.get('generations', 30),
                          default=30, min_=1, max_=1000)
    population  = _as_int(data.get('population', 20),
                          default=20, min_=4, max_=200)
    seed = data.get('seed')
    if seed is not None:
        try:    seed = int(seed)
        except (TypeError, ValueError):  seed = None

    result = evolve(room, generations=generations,
                    population=population, seed=seed)
    touched = apply_result(room, result)

    # History is small (one entry per generation); trimming down to at
    # most 60 points keeps the sparkline readable.
    hist = result.history
    if len(hist) > 60:
        step = max(1, len(hist) // 60)
        hist = [hist[i] for i in range(0, len(hist), step)]

    return JsonResponse({
        'ok':             True,
        'initial_score':  result.initial_score,
        'best_score':     result.best_score,
        'improvement':    result.improvement,
        'generations':    result.generations,
        'population':     result.population,
        'history':        hist,
        'placements':     list(touched.values()),
        'score':          score_room(room),
    })


@login_required
@require_POST
def api_piece_delete(request, piece_id):
    """Remove a catalog piece. PROTECT FK means this fails if placements
    still exist that use it — caller should delete placements first."""
    piece = get_object_or_404(FurniturePiece, pk=piece_id)
    if piece.placements.exists():
        return JsonResponse({
            'ok': False,
            'error': f'piece is still placed in {piece.placements.count()} room(s)',
        }, status=400)
    pk = piece.id
    piece.delete()
    return JsonResponse({'ok': True, 'id': pk})

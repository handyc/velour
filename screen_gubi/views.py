from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import gubify as G
from .models import GubiWorld


MOOD_TO_SOUNDSCAPE = {
    'calm':    'forest',
    'bright':  'beach',
    'stormy':  'rainy',
    'playful': 'cafe',
    'solemn':  'night',
    'wild':    'city-street',
}

# Gubi mood → Legolith biome. Each mood picks a biome whose palette
# matches the feel; the remaining biomes aren't wasted — we fall through
# to a hash if mood isn't recognised.
MOOD_TO_BIOME = {
    'calm':    'meadow',
    'bright':  'plains',
    'stormy':  'harbor',
    'playful': 'town',
    'solemn':  'dusk',
    'wild':    'forest',
}


def _clip(lo, hi, x):
    return max(lo, min(hi, x))


def _byte_to_unit(b):
    return (b & 0xFF) / 255.0


def build_aether_world(gubi_world):
    """Create and save an aether.World seeded from a GubiWorld.

    Runs the full Legolith → Aether pipeline so the result has real
    visible geometry (brick-built buildings, trees, people, etc.). Every
    major Gubi knob feeds a Legolith parameter: mood picks the biome,
    seed drives reproducibility, n_trees comes straight from Gubi, the
    rng_stream bytes set the other object counts, and booleans toggle
    studs/flight. After Legolith builds the world we overlay Gubi's
    sky/ground/fog colors, ambient light, gravity, soundscape, and
    spawn point so the environment reflects the input screen too.
    """
    from aether.legoworld import build_legoworld_in_aether

    vars_ = gubi_world.gubified()
    shared = vars_['regions']['shared']
    lsys = vars_['regions']['lsystem']
    rng = shared['rng_stream']
    booleans = shared['booleans']

    biome = MOOD_TO_BIOME.get(
        shared['mood'],
        ['meadow', 'plains', 'forest', 'town', 'dusk', 'harbor',
         'autumn', 'desert', 'snow', 'island'][shared['seed'] % 10],
    )

    counts = dict(
        n_buildings = 2 + (rng[3] % 6),
        n_trees     = max(1, lsys['n_trees']),
        n_flowers   = rng[4] % 10,
        n_people    = rng[5] % 5,
        n_hills     = 1 + (rng[6] % 3),
        n_lamps     = rng[7] % 4,
        n_rocks     = rng[8] % 5,
    )

    world, stats = build_legoworld_in_aether(
        name=gubi_world.title or 'Gubi world',
        biome=biome,
        seed=shared['seed'],
        show_studs=bool(booleans[4]),
        hdri_asset='',
        **counts,
    )

    # Overlay Gubi-specific environment on top of the Legolith defaults
    # so the sky/fog/ground pick up the Gubi input's character.
    tags = [t for t in shared['tags'] if t]
    desc_lines = [
        f'Grown from the Gubi world "{gubi_world.title}" '
        f'(mood: {shared["mood"]}, seed: {shared["seed"]}).',
    ]
    if shared['title_hint']:
        desc_lines.append(f'Hint: {shared["title_hint"]}')
    if tags:
        desc_lines.append('Tags: ' + ', '.join(tags))
    desc_lines.append(
        f'{counts["n_buildings"]} buildings · {counts["n_trees"]} trees · '
        f'{counts["n_flowers"]} flowers · {counts["n_people"]} people · '
        f'{counts["n_hills"]} hills · {counts["n_lamps"]} lamps · '
        f'{counts["n_rocks"]} rocks on a {biome} baseplate '
        f'({stats["bricks"]} bricks).'
    )
    desc_lines.append(
        f'L-system axiom \'{lsys["axiom"]}\', {lsys["iterations"]} iters, '
        f'branch angle {lsys["branch_angle"]:.1f}°.'
    )

    world.title = f'{gubi_world.title} · Aether'[:200]
    world.description = '\n'.join(desc_lines)
    world.sky_color = lsys['sky_top']
    world.ground_color = lsys['ground_color']
    world.fog_color = lsys['sky_bottom']
    world.fog_near = lsys['fog_near']
    world.fog_far = lsys['fog_far']
    world.ambient_light = _clip(
        0.15, 0.85, 0.25 + _byte_to_unit(rng[0]) * 0.6)
    world.ambient_volume = _clip(
        0.1, 0.8, 0.2 + _byte_to_unit(rng[1]) * 0.6)
    world.gravity = -3.0 - _byte_to_unit(rng[2]) * 9.0
    world.allow_flight = bool(booleans[1])
    world.soundscape = MOOD_TO_SOUNDSCAPE.get(shared['mood'], 'forest')
    # Spawn at the first tree position if it'd keep the player on the
    # baseplate; otherwise keep Legolith's safe default (edge of plate).
    positions = lsys['tree_positions'][:lsys['n_trees']]
    if positions:
        px, pz = positions[0]
        # Baseplate is ~12.8m (32 studs × 0.4), so 6.4m each side. Clamp.
        if abs(px) < 6.0 and abs(pz) < 6.0:
            world.spawn_x = float(px)
            world.spawn_z = float(pz)
    world.save()
    return world


SORTS = {
    'updated':  '-updated_at',
    'created':  '-created_at',
    'title':    'title',
    '-title':   '-title',
}


@login_required
def index(request):
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'updated')
    order = SORTS.get(sort, '-updated_at')

    worlds = GubiWorld.objects.all()
    if q:
        worlds = worlds.filter(Q(title__icontains=q) | Q(text__icontains=q))
    worlds = worlds.order_by(order)

    return render(request, 'screen_gubi/index.html', {
        'worlds': worlds,
        'q': q,
        'sort': sort,
    })


@login_required
def detail(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    vars_ = world.gubified()
    scene = G.lsystem_scene(vars_)
    return render(request, 'screen_gubi/detail.html', {
        'world': world,
        'shared': vars_['regions']['shared'],
        'scene': scene,
    })


@login_required
def scene_json(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    return JsonResponse(world.scene())


@login_required
def new(request):
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip() or 'Untitled world'
        text = request.POST.get('text') or ''
        world = GubiWorld(title=title, text=text)
        world.save()
        return redirect('screen_gubi:detail', slug=world.slug)
    # blank 80x25 screen (spaces)
    blank = '\n'.join([' ' * 80] * 25)
    return render(request, 'screen_gubi/edit.html', {
        'world': None,
        'text': blank,
        'title': '',
        'is_new': True,
    })


@login_required
def edit(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    if request.method == 'POST':
        world.title = (request.POST.get('title') or world.title).strip() or world.title
        world.text = request.POST.get('text') or ''
        world.save()
        return redirect('screen_gubi:detail', slug=world.slug)
    return render(request, 'screen_gubi/edit.html', {
        'world': world,
        'text': world.text,
        'title': world.title,
        'is_new': False,
    })


@login_required
@require_POST
def export_aether(request, slug):
    gubi_world = get_object_or_404(GubiWorld, slug=slug)
    world = build_aether_world(gubi_world)
    messages.success(
        request,
        f'Exported "{gubi_world.title}" to Aether as "{world.title}".',
    )
    return redirect('aether:world_detail', slug=world.slug)


@login_required
def delete(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    if request.method == 'POST':
        world.delete()
        return redirect('screen_gubi:index')
    return redirect('screen_gubi:detail', slug=slug)

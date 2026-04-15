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


def _clip(lo, hi, x):
    return max(lo, min(hi, x))


def _byte_to_unit(b):
    return (b & 0xFF) / 255.0


def build_aether_world(gubi_world):
    """Create and save an aether.World seeded from a GubiWorld.

    Consumes the full Gubi schema: mood → soundscape, sky/ground/fog
    colors → environment, rng_stream bytes → ambient light / volume /
    gravity, booleans → flight + skybox style, first tree position →
    player spawn, title_hint + tags + axiom summary → description.
    """
    from aether.models import World as AetherWorld

    vars_ = gubi_world.gubified()
    shared = vars_['regions']['shared']
    lsys = vars_['regions']['lsystem']
    rng = shared['rng_stream']
    booleans = shared['booleans']

    tags = [t for t in shared['tags'] if t]
    description_parts = [
        f'Grown from the Gubi world "{gubi_world.title}".',
        f"Mood: {shared['mood']}. Seed: {shared['seed']}.",
    ]
    if shared['title_hint']:
        description_parts.append(f"Hint: {shared['title_hint']}")
    if tags:
        description_parts.append('Tags: ' + ', '.join(tags))
    description_parts.append(
        f"{lsys['n_trees']} procedural trees, axiom '{lsys['axiom']}', "
        f"{lsys['iterations']} iterations, branch angle "
        f"{lsys['branch_angle']:.1f}°."
    )

    skybox = 'gradient' if booleans[0] else 'color'
    ambient_light = _clip(0.15, 0.85, 0.25 + _byte_to_unit(rng[0]) * 0.6)
    ambient_volume = _clip(0.1, 0.8, 0.2 + _byte_to_unit(rng[1]) * 0.6)
    gravity = -3.0 - _byte_to_unit(rng[2]) * 9.0
    scales = lsys['tree_scales'][:lsys['n_trees']] or [1.0]
    avg_scale = sum(scales) / len(scales)
    ground_size = _clip(40.0, 240.0, 60.0 + avg_scale * 60.0)

    positions = lsys['tree_positions'][:lsys['n_trees']]
    spawn_x, spawn_z = positions[0] if positions else (0.0, 0.0)

    world = AetherWorld(
        title=f'{gubi_world.title} · Aether'[:200],
        description='\n'.join(description_parts),
        skybox=skybox,
        sky_color=lsys['sky_top'],
        ground_color=lsys['ground_color'],
        fog_color=lsys['sky_bottom'],
        fog_near=lsys['fog_near'],
        fog_far=lsys['fog_far'],
        ground_size=ground_size,
        ambient_light=ambient_light,
        soundscape=MOOD_TO_SOUNDSCAPE.get(shared['mood'], 'forest'),
        ambient_volume=ambient_volume,
        gravity=gravity,
        allow_flight=bool(booleans[1]),
        spawn_x=float(spawn_x),
        spawn_y=1.6,
        spawn_z=float(spawn_z),
        published=False,
    )
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

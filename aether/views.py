import colorsys
import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import (
    Asset, Entity, EntityScript, LibraryObject, ObjectCategory,
    Portal, SavedFace, Script, World, WorldPreset,
)


SORT_OPTIONS = [
    ('featured_first', 'Featured first',   ('-featured', '-updated_at')),
    ('featured_last',  'Featured last',    ('featured', '-updated_at')),
    ('newest',         'Newest first',     ('-created_at',)),
    ('oldest',         'Oldest first',     ('created_at',)),
]


@login_required
def world_list(request):
    sort_key = request.GET.get('sort', 'featured_first')
    order = next(
        (o for k, _, o in SORT_OPTIONS if k == sort_key),
        SORT_OPTIONS[0][2],
    )
    if sort_key not in {k for k, _, _ in SORT_OPTIONS}:
        sort_key = 'featured_first'
    if request.user.is_staff:
        worlds = World.objects.all().order_by(*order)
    else:
        worlds = World.objects.filter(published=True).order_by(*order)
    return render(request, 'aether/list.html', {
        'worlds': worlds,
        'sort_options': [(k, label) for k, label, _ in SORT_OPTIONS],
        'current_sort': sort_key,
    })


@login_required
def world_enter(request, slug):
    """The immersive 3D view — the main experience."""
    world = get_object_or_404(World, slug=slug)
    if not world.published and not request.user.is_staff:
        return redirect('aether:world_list')
    entities = world.entities.filter(visible=True).select_related('asset')
    portals = world.portals_out.select_related('to_world')
    return render(request, 'aether/enter.html', {
        'world': world,
        'entities': entities,
        'portals': portals,
    })


@login_required
def world_detail(request, slug):
    """Editor / detail view for a world."""
    world = get_object_or_404(World, slug=slug)
    entities = world.entities.select_related('asset')
    assets = world.assets.all()
    portals = world.portals_out.select_related('to_world')
    return render(request, 'aether/detail.html', {
        'world': world,
        'entities': entities,
        'assets': assets,
        'portals': portals,
    })


@login_required
def world_random(request):
    """Redirect to a random published world. If ``exclude`` query param is
    given, that world's slug is skipped so a repeat pick is avoided."""
    exclude = request.GET.get('exclude', '')
    qs = World.objects.filter(published=True).exclude(slug=exclude)
    w = qs.order_by('?').first() or World.objects.filter(published=True).first()
    if not w:
        messages.warning(request, 'No published worlds available.')
        return redirect('aether:world_list')
    return redirect('aether:world_enter', slug=w.slug)


@login_required
def world_add(request):
    if request.method == 'POST':
        world = World(
            title=request.POST.get('title', 'Untitled World'),
            description=request.POST.get('description', ''),
            skybox=request.POST.get('skybox', 'procedural'),
            sky_color=request.POST.get('sky_color', '#87CEEB'),
            ground_color=request.POST.get('ground_color', '#3d5c3a'),
            hdri_asset=request.POST.get('hdri_asset', ''),
            ambient_audio_url=request.POST.get('ambient_audio_url', ''),
            ambient_volume=float(request.POST.get('ambient_volume', 0.4)),
            soundscape=request.POST.get('soundscape', ''),
        )
        if request.FILES.get('ambient_audio'):
            world.ambient_audio = request.FILES['ambient_audio']
        world.save()
        return redirect('aether:world_detail', slug=world.slug)
    presets = WorldPreset.objects.all()
    return render(request, 'aether/world_form.html', {'presets': presets})


@login_required
def world_edit(request, slug):
    world = get_object_or_404(World, slug=slug)
    if request.method == 'POST':
        world.title = request.POST.get('title', world.title)
        world.description = request.POST.get('description', '')
        world.skybox = request.POST.get('skybox', world.skybox)
        world.sky_color = request.POST.get('sky_color', world.sky_color)
        world.ground_color = request.POST.get('ground_color', world.ground_color)
        world.ground_size = float(request.POST.get('ground_size', world.ground_size))
        world.ambient_light = float(request.POST.get('ambient_light', world.ambient_light))
        world.fog_near = float(request.POST.get('fog_near', world.fog_near))
        world.fog_far = float(request.POST.get('fog_far', world.fog_far))
        world.fog_color = request.POST.get('fog_color', world.fog_color)
        world.gravity = float(request.POST.get('gravity', world.gravity))
        world.allow_flight = request.POST.get('allow_flight') == 'on'
        world.spawn_x = float(request.POST.get('spawn_x', world.spawn_x))
        world.spawn_y = float(request.POST.get('spawn_y', world.spawn_y))
        world.spawn_z = float(request.POST.get('spawn_z', world.spawn_z))
        world.hdri_asset = request.POST.get('hdri_asset', '')
        world.ambient_audio_url = request.POST.get('ambient_audio_url', '')
        world.ambient_volume = float(request.POST.get('ambient_volume', world.ambient_volume))
        world.soundscape = request.POST.get('soundscape', '')
        if request.FILES.get('ambient_audio'):
            world.ambient_audio = request.FILES['ambient_audio']
        if request.POST.get('clear_ambient_audio'):
            world.ambient_audio = ''
        world.published = request.POST.get('published') == 'on'
        world.featured = request.POST.get('featured') == 'on'
        world.save()
        return redirect('aether:world_detail', slug=world.slug)
    presets = WorldPreset.objects.all()
    return render(request, 'aether/world_form.html', {'world': world, 'presets': presets})


@login_required
def preset_json(request, slug):
    """Return preset data as JSON for form auto-fill."""
    p = get_object_or_404(WorldPreset, slug=slug)
    return JsonResponse({
        'skybox': p.skybox,
        'hdriAsset': p.hdri_asset,
        'skyColor': p.sky_color,
        'groundColor': p.ground_color,
        'fogColor': p.fog_color,
        'fogNear': p.fog_near,
        'fogFar': p.fog_far,
        'ambientLight': p.ambient_light,
        'ambientAudioUrl': p.ambient_audio_url,
        'ambientVolume': p.ambient_volume,
        'soundscape': p.slug,
    })


@login_required
def world_delete(request, slug):
    world = get_object_or_404(World, slug=slug)
    if request.method == 'POST':
        world.delete()
        return redirect('aether:world_list')
    return render(request, 'aether/confirm_delete.html', {'world': world})


@login_required
def entity_add(request, slug):
    world = get_object_or_404(World, slug=slug)
    if request.method == 'POST':
        asset = None
        asset_id = request.POST.get('asset')
        if asset_id:
            asset = Asset.objects.filter(pk=asset_id, world=world).first()
        entity = Entity(
            world=world,
            name=request.POST.get('name', ''),
            asset=asset,
            primitive=request.POST.get('primitive', 'box'),
            primitive_color=request.POST.get('primitive_color', '#808080'),
            pos_x=float(request.POST.get('pos_x', 0)),
            pos_y=float(request.POST.get('pos_y', 0)),
            pos_z=float(request.POST.get('pos_z', -5)),
            rot_x=float(request.POST.get('rot_x', 0)),
            rot_y=float(request.POST.get('rot_y', 0)),
            rot_z=float(request.POST.get('rot_z', 0)),
            scale_x=float(request.POST.get('scale_x', 1)),
            scale_y=float(request.POST.get('scale_y', 1)),
            scale_z=float(request.POST.get('scale_z', 1)),
            behavior=request.POST.get('behavior', 'static'),
        )
        entity.save()
        return redirect('aether:world_detail', slug=world.slug)
    return render(request, 'aether/entity_form.html', {
        'world': world,
        'assets': world.assets.all(),
    })


@login_required
def asset_add(request, slug):
    world = get_object_or_404(World, slug=slug)
    if request.method == 'POST' and request.FILES.get('file'):
        asset = Asset(
            world=world,
            name=request.POST.get('name', 'Unnamed'),
            asset_type=request.POST.get('asset_type', 'model'),
            file=request.FILES['file'],
        )
        asset.save()
        return redirect('aether:world_detail', slug=world.slug)
    return render(request, 'aether/asset_form.html', {'world': world})


@login_required
def world_scene_json(request, slug):
    """JSON endpoint: the full scene graph for the three.js renderer."""
    import hashlib
    from django.db.models import F
    from django.utils import timezone
    from grammar_engine.models import Language

    world = get_object_or_404(World, slug=slug)
    entities = world.entities.filter(visible=True).select_related('asset', 'face')
    portals = world.portals_out.select_related('to_world')

    # Prefetch scripts for all entities
    entity_scripts = {}
    npc_entity_ids = set()
    for es in EntityScript.objects.filter(
        entity__world=world, enabled=True
    ).select_related('script'):
        entity_scripts.setdefault(es.entity_id, []).append({
            'event': es.script.event,
            'code': es.script.code,
            'props': es.props or {},
        })
        if es.script.slug.startswith('humanoid-builder'):
            npc_entity_ids.add(es.entity_id)

    # Resolve NPC languages. Three-tier:
    #   1. Entity has explicit language_slug — use that.
    #   2. Otherwise inherit from the planet (5% chance of diversity:
    #      one of the other languages picked weighted by use_count).
    #   3. If the slug is missing from the Language table, fall back
    #      to the most-popular surviving language.
    #   4. If neither entity nor planet has any slug, NPC stays silent.
    planet_id = (request.GET.get('planet') or '').strip()
    planet_lang = ''
    planet_seed = 0
    if planet_id.isdigit():
        from bridge.models import Planet
        planet = Planet.objects.filter(pk=int(planet_id)).first()
        if planet:
            planet_lang = planet.primary_language_slug or ''
            planet_seed = planet.id

    # Build alt-language pool weighted by use_count for diversity rolls.
    lang_rows = list(Language.objects.values_list('slug', 'use_count'))
    lang_index = {s: c for s, c in lang_rows}
    most_popular = (max(lang_rows, key=lambda r: r[1])[0]
                    if lang_rows else '')

    def diversity_pick(entity_id, exclude_slug):
        pool = [(s, c) for s, c in lang_rows if s != exclude_slug]
        if not pool:
            return exclude_slug
        weights = [max(1, c + 1) for _, c in pool]
        total = sum(weights)
        h = int(hashlib.md5(
            f'npc-alt:{entity_id}:{planet_seed}'.encode()
        ).hexdigest(), 16)
        pick = (h % 1_000_000) / 1_000_000 * total
        acc = 0.0
        for (slug, _), w in zip(pool, weights):
            acc += w
            if pick <= acc:
                return slug
        return pool[-1][0]

    npc_languages = {}   # entity_id -> resolved slug (may be '')
    for e in entities:
        if e.pk not in npc_entity_ids:
            continue
        chosen = (e.language_slug or '').strip()
        if not chosen and planet_lang:
            # 5% diversity roll, deterministic per entity+planet.
            roll_seed = f'npc-roll:{e.pk}:{planet_seed}'
            roll = (int(hashlib.md5(roll_seed.encode()).hexdigest(), 16)
                    % 10_000) / 10_000
            chosen = (diversity_pick(e.pk, planet_lang)
                      if roll < 0.05 else planet_lang)
        if chosen and chosen not in lang_index:
            chosen = most_popular
        npc_languages[e.pk] = chosen or ''

    # Preload spec dicts for every language actually used; bump usage.
    used_slugs = sorted({s for s in npc_languages.values() if s})
    languages_payload = {}
    for lang in Language.objects.filter(slug__in=used_slugs):
        languages_payload[lang.slug] = {
            'name': lang.name,
            'seed': lang.seed,
            'spec': lang.spec or {},
        }
    if used_slugs:
        Language.objects.filter(slug__in=used_slugs).update(
            use_count=F('use_count') + 1, last_used=timezone.now(),
        )

    scene = {
        'title': world.title,
        'environment': {
            'skybox': world.skybox,
            'skyColor': world.sky_color,
            'groundColor': world.ground_color,
            'groundSize': world.ground_size,
            'ambientLight': world.ambient_light,
            'fogNear': world.fog_near,
            'fogFar': world.fog_far,
            'fogColor': world.fog_color,
            'gravity': world.gravity,
            'allowFlight': world.allow_flight,
            'hdriAsset': world.hdri_asset or '',
            'ambientAudio': world.audio_src(),
            'ambientVolume': world.ambient_volume,
            'soundscape': world.soundscape or '',
        },
        'spawn': {
            'x': world.spawn_x,
            'y': world.spawn_y,
            'z': world.spawn_z,
        },
        'entities': [
            {
                'id': e.pk,
                'name': e.name,
                'asset': e.asset.file.url if e.asset and e.asset.file else None,
                'assetType': e.asset.asset_type if e.asset else None,
                'primitive': e.primitive or None,
                'primitiveColor': e.primitive_color,
                'position': [e.pos_x, e.pos_y, e.pos_z],
                'rotation': [e.rot_x, e.rot_y, e.rot_z],
                'scale': [e.scale_x, e.scale_y, e.scale_z],
                'behavior': e.behavior,
                'behaviorSpeed': e.behavior_speed,
                'castShadow': e.cast_shadow,
                'receiveShadow': e.receive_shadow,
                'faceGenome': e.face.genome if e.face_id else None,
                'scripts': entity_scripts.get(e.pk, []),
                'languageSlug': npc_languages.get(e.pk, ''),
                'isNpc': e.pk in npc_entity_ids,
            }
            for e in entities
        ],
        'languages': languages_payload,
        'planet': {
            'id': int(planet_id) if planet_id.isdigit() else None,
            'languageSlug': planet_lang,
        },
        'portals': [
            {
                'label': p.label or p.to_world.title,
                'targetSlug': p.to_world.slug,
                'targetUrl': f'/aether/{p.to_world.slug}/enter/',
                'position': [p.pos_x, p.pos_y, p.pos_z],
                'width': p.width,
                'height': p.height,
            }
            for p in portals
        ],
    }
    return JsonResponse(scene)


# -----------------------------------------------------------------------
# Object Library
# -----------------------------------------------------------------------

@login_required
def library_list(request):
    """Browse the object library with search and category filtering."""
    q = request.GET.get('q', '').strip()
    cat_slug = request.GET.get('cat', '')
    source = request.GET.get('source', '')
    page = int(request.GET.get('page', 1))
    per_page = 48

    objects = LibraryObject.objects.all()
    if q:
        objects = objects.filter(Q(name__icontains=q) | Q(tags__icontains=q))
    if cat_slug:
        objects = objects.filter(category__slug=cat_slug)
    if source:
        objects = objects.filter(source=source)

    total = objects.count()
    objects = objects[(page - 1) * per_page:page * per_page]
    categories = ObjectCategory.objects.filter(parent__isnull=True)

    return render(request, 'aether/library.html', {
        'objects': objects,
        'categories': categories,
        'q': q,
        'cat_slug': cat_slug,
        'source': source,
        'page': page,
        'total': total,
        'has_next': page * per_page < total,
    })


@login_required
def library_json(request):
    """JSON search endpoint for the library (used by in-world object picker)."""
    q = request.GET.get('q', '').strip()
    cat = request.GET.get('cat', '')
    count = min(int(request.GET.get('count', 24)), 100)

    objects = LibraryObject.objects.all()
    if q:
        objects = objects.filter(Q(name__icontains=q) | Q(tags__icontains=q))
    if cat:
        objects = objects.filter(category__slug=cat)
    objects = objects[:count]

    return JsonResponse({'results': [
        {
            'id': obj.pk,
            'name': obj.name,
            'slug': obj.slug,
            'source': obj.source,
            'thumbnail': obj.thumbnail,
            'license': obj.license,
            'author': obj.author,
            'tags': obj.tag_list,
            'downloaded': obj.downloaded,
            'fileUrl': obj.file.url if obj.file else None,
        }
        for obj in objects
    ]})


@login_required
def library_place(request, slug):
    """Place a LibraryObject into a world: download if needed, create Asset + Entity."""
    world = get_object_or_404(World, slug=slug)
    if request.method != 'POST':
        return redirect('aether:world_detail', slug=world.slug)

    obj = get_object_or_404(LibraryObject, pk=request.POST.get('library_object'))

    # Lazy download: if the file hasn't been fetched yet, download it now
    if not obj.downloaded and obj.source_url:
        _download_library_file(obj)

    # Create an Asset in this world from the library object's file
    asset = None
    if obj.file:
        from django.core.files.base import ContentFile
        content = obj.file.read()
        obj.file.seek(0)
        asset = Asset(
            world=world,
            name=obj.name,
            asset_type='model',
        )
        fname = obj.file.name.split('/')[-1]
        asset.file.save(fname, ContentFile(content), save=False)
        asset.save()

    # Create the Entity referencing the new asset
    entity = Entity(
        world=world,
        name=obj.name,
        asset=asset,
        primitive='' if asset else 'box',
        pos_x=float(request.POST.get('pos_x', 0)),
        pos_y=float(request.POST.get('pos_y', 0)),
        pos_z=float(request.POST.get('pos_z', -5)),
    )
    entity.save()

    # Track usage
    LibraryObject.objects.filter(pk=obj.pk).update(use_count=obj.use_count + 1)

    return redirect('aether:world_detail', slug=world.slug)


def _download_library_file(obj):
    """Download the remote file for a LibraryObject and save it locally."""
    import urllib.request
    from django.core.files.base import ContentFile

    try:
        req = urllib.request.Request(obj.source_url, headers={
            'User-Agent': 'Velour/1.0 (Aether ObjectLibrary)',
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(50 * 1024 * 1024)  # cap at 50MB
        ext = obj.source_url.split('.')[-1].split('?')[0][:10]
        if ext not in ('glb', 'gltf', 'zip'):
            ext = 'glb'
        fname = f'{obj.slug}.{ext}'
        obj.file.save(fname, ContentFile(data), save=False)
        obj.file_size = len(data)
        obj.downloaded = True
        obj.save()
    except Exception:
        pass  # file stays NULL; entity gets created without asset


# -----------------------------------------------------------------------
# Script management
# -----------------------------------------------------------------------

@login_required
def script_list(request):
    """Browse and manage behavior scripts."""
    scripts = Script.objects.all()
    return render(request, 'aether/scripts.html', {'scripts': scripts})


@login_required
def script_add(request):
    if request.method == 'POST':
        script = Script(
            name=request.POST.get('name', 'Untitled Script'),
            description=request.POST.get('description', ''),
            code=request.POST.get('code', ''),
            event=request.POST.get('event', 'update'),
        )
        script.save()
        return redirect('aether:script_list')
    return render(request, 'aether/script_form.html', {})


@login_required
def script_edit(request, slug):
    script = get_object_or_404(Script, slug=slug)
    if request.method == 'POST':
        script.name = request.POST.get('name', script.name)
        script.description = request.POST.get('description', '')
        script.code = request.POST.get('code', script.code)
        script.event = request.POST.get('event', script.event)
        script.save()
        return redirect('aether:script_list')
    return render(request, 'aether/script_form.html', {'script': script})


@login_required
def entity_script_add(request, slug, entity_pk):
    """Attach a script to an entity."""
    world = get_object_or_404(World, slug=slug)
    entity = get_object_or_404(Entity, pk=entity_pk, world=world)
    if request.method == 'POST':
        script = get_object_or_404(Script, pk=request.POST.get('script'))
        props_str = request.POST.get('props', '{}')
        try:
            props = json.loads(props_str)
        except (json.JSONDecodeError, ValueError):
            props = {}
        EntityScript.objects.create(
            entity=entity, script=script, props=props,
        )
        return redirect('aether:world_detail', slug=world.slug)
    scripts = Script.objects.all()
    return render(request, 'aether/entity_script_form.html', {
        'world': world,
        'entity': entity,
        'scripts': scripts,
    })


# ---------------------------------------------------------------------------
# Random world generator
# ---------------------------------------------------------------------------

# Palette of options the generator picks from
_THEMES = [
    {'name': 'Forest Clearing', 'sky': '#88b8e8', 'ground': '#3a5020',
     'fog': '#c0d0e0', 'soundscape': 'forest', 'trees': True, 'flowers': True},
    {'name': 'Desert Oasis', 'sky': '#e0c898', 'ground': '#c8a868',
     'fog': '#e8d8c0', 'soundscape': 'desert', 'trees': False, 'flowers': False},
    {'name': 'Night City', 'sky': '#0a0a18', 'ground': '#1a1a24',
     'fog': '#141420', 'soundscape': 'city', 'trees': False, 'flowers': False},
    {'name': 'Seaside', 'sky': '#70a8d8', 'ground': '#c8b888',
     'fog': '#b0c8e0', 'soundscape': 'ocean', 'trees': True, 'flowers': True},
    {'name': 'Mountain Top', 'sky': '#90a8c8', 'ground': '#686058',
     'fog': '#a0a8b8', 'soundscape': 'wind', 'trees': False, 'flowers': False},
    {'name': 'Garden Party', 'sky': '#a0c8e8', 'ground': '#3a6828',
     'fog': '#c8d8e8', 'soundscape': 'birds', 'trees': True, 'flowers': True},
    {'name': 'Cave', 'sky': '#080808', 'ground': '#282020',
     'fog': '#181418', 'soundscape': 'cave', 'trees': False, 'flowers': False},
    {'name': 'Snow Field', 'sky': '#c0c8d8', 'ground': '#e0e0e8',
     'fog': '#d0d4e0', 'soundscape': 'wind', 'trees': True, 'flowers': False},
    {'name': 'Town Square', 'sky': '#90b8e0', 'ground': '#807868',
     'fog': '#c8d4e0', 'soundscape': 'town', 'trees': True, 'flowers': True},
    {'name': 'Space Station', 'sky': '#000008', 'ground': '#202028',
     'fog': '#08080c', 'soundscape': '', 'trees': False, 'flowers': False},
]

_SKYBOXES = ['color', 'gradient', 'hdri', 'procedural']
_HDRIS = ['kloofendal_48d_partly_cloudy', '']

_FURNITURE = [
    ('Bench', 'box', '#5c4828', 1.8, 0.06, 0.45),
    ('Table', 'box', '#484038', 1.2, 0.04, 0.8),
    ('Pillar', 'cylinder', '#808888', 0.2, 2.0, 0.2),
    ('Crate', 'box', '#5a4828', 0.6, 0.6, 0.6),
    ('Barrel', 'cylinder', '#5a3820', 0.3, 0.7, 0.3),
    ('Lamp Post', 'cylinder', '#2a2a2a', 0.06, 4.0, 0.06),
    ('Boulder', 'sphere', '#686060', 0.8, 0.6, 0.8),
    ('Planter', 'box', '#504838', 0.8, 0.4, 0.8),
    ('Wall Segment', 'box', '#505058', 3.0, 2.5, 0.2),
    ('Arch', 'torus', '#707078', 1.5, 0.5, 1.5),
]

_NPC_NAMES = [
    'Ash', 'Blake', 'Cedar', 'Drew', 'Ellis', 'Fern', 'Gray', 'Haven',
    'Iris', 'Jade', 'Kit', 'Lark', 'Moss', 'Nova', 'Oak', 'Pine',
    'Quinn', 'Reed', 'Sky', 'Thorn', 'Vale', 'Wren', 'Yew', 'Zara',
]

_REACTIONS = ['flee', 'approach', 'follow', 'notice', 'ignore',
              'shy', 'curious', 'wave', 'mimic', 'startle']

_SKINS = ['#c89870', '#704020', '#a87040', '#d4a470', '#e8c898',
           '#f0d4b0', '#8b5030', '#b88050', '#d0ac80', '#b06038']
_SHIRTS = ['#f0e8e0', '#2a4060', '#6a3838', '#385838', '#483858',
            '#684038', '#364050', '#584830', '#385058', '#5a4440']
_PANTS = ['#1c1c28', '#282830', '#323240', '#1e1e30', '#2a2a38']
_SHOES = ['#181818', '#3a2418', '#1a1a1a', '#3e2c1e', '#242424']
_HAIRS = ['#1a1008', '#080808', '#301a0e', '#b89040', '#4a2818',
           '#7a3c10', '#201008']
_EYES = ['#3a2818', '#1e4a1e', '#3868a8', '#4a7a4a', '#5a3418',
          '#284050', '#386888']
_FLOWERS = ['#cc3040', '#e0a020', '#8040b0', '#e06080', '#40a0c0',
             '#f0c040', '#60b060', '#c060c0']


@login_required
@require_POST
def generate_random_world(request):
    """Generate a random world from template options."""
    theme = random.choice(_THEMES)
    skybox = random.choice(_SKYBOXES)
    n_npcs = random.randint(2, 6)
    n_furniture = random.randint(2, 10)
    n_trees = random.randint(2, 6) if theme['trees'] else 0
    n_flowers = random.randint(0, 4) if theme['flowers'] else 0
    ground_size = random.choice([30, 40, 50, 60])

    adjectives = ['Quiet', 'Hidden', 'Ancient', 'Twilight', 'Wandering',
                  'Silver', 'Crystal', 'Misty', 'Golden', 'Hollow']
    nouns = ['Glade', 'Crossing', 'Haven', 'Outpost', 'Passage',
             'Landing', 'Terrace', 'Hollow', 'Summit', 'Alcove']
    title = f'{random.choice(adjectives)} {theme["name"]} {random.choice(nouns)}'

    world = World.objects.create(
        title=title,
        description=f'Randomly generated world. Theme: {theme["name"]}. '
                    f'{n_npcs} NPCs, {n_furniture} objects.',
        skybox=skybox,
        hdri_asset=random.choice(_HDRIS) if skybox == 'hdri' else '',
        sky_color=theme['sky'],
        ground_color=theme['ground'],
        ground_size=ground_size,
        ambient_light=round(random.uniform(0.3, 0.65), 2),
        fog_near=round(random.uniform(25, 50), 1),
        fog_far=round(random.uniform(80, 150), 1),
        fog_color=theme['fog'],
        gravity=-9.81,
        spawn_x=0, spawn_y=1.6, spawn_z=round(ground_size * 0.2, 1),
        soundscape=theme['soundscape'],
        ambient_volume=round(random.uniform(0.1, 0.3), 2),
        published=True, featured=False,
    )

    entities = []
    half = ground_size * 0.35

    def ent(name, prim, color, x, y, z, sx=1, sy=1, sz=1, **kw):
        entities.append(Entity(
            world=world, name=name, primitive=prim, primitive_color=color,
            pos_x=x, pos_y=y, pos_z=z,
            scale_x=sx, scale_y=sy, scale_z=sz,
            cast_shadow=kw.get('shadow', True),
            receive_shadow=kw.get('shadow', True),
            behavior='static',
        ))

    # Ground
    ent('Ground', 'box', theme['ground'], 0, -0.05, 0,
        ground_size, 0.1, ground_size, shadow=False)

    # Trees
    for i in range(n_trees):
        tx = random.uniform(-half, half)
        tz = random.uniform(-half, half)
        h = random.uniform(2.5, 5.0)
        ent(f'Trunk {i}', 'cylinder', '#5a4020', tx, h/2, tz, 0.3, h, 0.3)
        cr = random.uniform(1.5, 3.5)
        ent(f'Canopy {i}', 'sphere',
            random.choice(['#2a5818', '#3a6828', '#1a4810', '#4a7838']),
            tx, h + cr*0.4, tz, cr, cr*0.7, cr)

    # Flowers
    for i in range(n_flowers):
        fx = random.uniform(-half*0.6, half*0.6)
        fz = random.uniform(-half*0.6, half*0.6)
        for j in range(random.randint(2, 5)):
            ent(f'Flower {i}-{j}', 'sphere', random.choice(_FLOWERS),
                fx + (j-2)*0.15, 0.15 + random.random()*0.1,
                fz + random.uniform(-0.1, 0.1),
                0.08, 0.08, 0.08, shadow=False)

    # Furniture / architecture
    for i in range(n_furniture):
        fname, fprim, fcolor, fsx, fsy, fsz = random.choice(_FURNITURE)
        fx = random.uniform(-half*0.7, half*0.7)
        fz = random.uniform(-half*0.7, half*0.7)
        ent(f'{fname} {i}', fprim, fcolor, fx, fsy/2, fz, fsx, fsy, fsz)
        # Lamp bulb on top of lamp posts
        if 'Lamp' in fname:
            ent(f'LampBulb {i}', 'sphere', '#ffe880',
                fx, fsy + 0.1, fz, 0.12, 0.12, 0.12, shadow=False)

    Entity.objects.bulk_create(entities)

    # --- Buildings: mix procedural + L-system architecture ---
    # L-system architecture species now render via the l-system-building
    # script, which actually runs the species grammar (axiom/rules/iter/
    # angle) to grow recursive box-based geometry. Random procedural
    # buildings still use the procedural-building script for variety.
    building_script = Script.objects.filter(slug='procedural-building').first()
    lsys_building_script = Script.objects.filter(slug='l-system-building').first()

    lsystem_buildings = []
    try:
        from lsystem.models import PlantSpecies
        lsystem_buildings = list(
            PlantSpecies.objects.filter(
                category__in=PlantSpecies.ARCHITECTURE_CATEGORIES
            )
        )
    except Exception:
        pass

    n_buildings = random.randint(2, 5)
    for i in range(n_buildings):
        bx = round(random.uniform(-half*0.8, half*0.8), 1)
        bz = round(random.uniform(-half*0.8, half*0.8), 1)
        brot = round(random.uniform(-30, 30), 1)

        # 50/50 split between grown L-system architecture and random
        # procedural buildings (fall back to procedural if no species
        # or renderer is available).
        use_lsystem = (lsystem_buildings and lsys_building_script
                       and random.random() < 0.5)

        if use_lsystem:
            preset = random.choice(lsystem_buildings)
            props = preset.to_aether_props(
                scale=round(random.uniform(0.8, 1.4), 2),
                seed=random.randint(1, 9999),
            )
            e = Entity.objects.create(
                world=world, name=f'L-Building {i}: {preset.name}',
                primitive='box', primitive_color='#000000',
                pos_x=bx, pos_y=0, pos_z=bz, rot_y=brot,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(
                entity=e, script=lsys_building_script, props=props)

        elif building_script:
            _BTYPES = ['house', 'shop', 'skyscraper', 'factory', 'warehouse',
                       'church', 'tower']
            _BCOLORS = ['#c8b8a0', '#d0c0a8', '#b0a890', '#909088', '#607080',
                         '#506878', '#e0d0b8', '#808878']
            btype = random.choice(_BTYPES)
            floors = {'house': random.randint(1, 3),
                      'shop': random.randint(1, 2),
                      'skyscraper': random.randint(8, 25),
                      'factory': random.randint(1, 3),
                      'warehouse': random.randint(1, 2),
                      'church': random.randint(2, 4),
                      'tower': random.randint(3, 6)}[btype]
            w = random.uniform(5, 14)
            d = random.uniform(5, 10)
            e = Entity.objects.create(
                world=world, name=f'Building {i}', primitive='box',
                primitive_color='#000000',
                pos_x=bx, pos_y=0, pos_z=bz, rot_y=brot,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(entity=e, script=building_script, props={
                'type': btype, 'floors': floors,
                'width': round(w, 1), 'depth': round(d, 1),
                'color': random.choice(_BCOLORS),
                'trim': '#%02x%02x%02x' % tuple(random.randint(60, 130) for _ in range(3)),
                'roof': '#%02x%02x%02x' % tuple(random.randint(50, 100) for _ in range(3)),
            })

    # --- L-system plants ---
    plant_script = Script.objects.filter(slug='l-system-plant').first()
    if plant_script:
        _SPECIES = ['oak', 'pine', 'birch', 'palm', 'bush', 'willow', 'cactus',
                    'maple', 'cherry', 'bamboo', 'fern', 'succulent', 'cypress',
                    'baobab', 'vine']
        n_plants = random.randint(3, 10)
        for i in range(n_plants):
            species = random.choice(_SPECIES)
            e = Entity.objects.create(
                world=world, name=f'Plant {i}', primitive='box',
                primitive_color='#000000',
                pos_x=round(random.uniform(-half*0.9, half*0.9), 1),
                pos_y=0,
                pos_z=round(random.uniform(-half*0.9, half*0.9), 1),
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(entity=e, script=plant_script, props={
                'species': species,
                'scale': round(random.uniform(0.6, 1.5), 2),
            })

    # --- Animals (light population) ---
    animal_script = Script.objects.filter(slug='animal-builder').first()
    animal_anim = Script.objects.filter(slug='animal-animate').first()
    if animal_script and animal_anim:
        _TINY = ['gnat', 'midge', 'fruit_fly']
        _INSECT = ['bee', 'butterfly', 'beetle', 'dragonfly', 'ladybug']
        _PET = ['mouse', 'rabbit', 'cat', 'frog', 'turtle']
        _LARGE = ['horse', 'cow', 'deer', 'dog']
        # 2-6 animals total, weighted toward smaller
        n_animals = random.randint(1, 3)
        for i in range(n_animals):
            r = random.random()
            if r < 0.3:
                sp = random.choice(_INSECT)
                ascale = round(random.uniform(0.8, 1.5), 2)
            elif r < 0.55:
                sp = random.choice(_PET)
                ascale = round(random.uniform(0.7, 1.2), 2)
            elif r < 0.75:
                sp = random.choice(_LARGE)
                ascale = round(random.uniform(0.8, 1.1), 2)
            else:
                sp = random.choice(_TINY)
                ascale = round(random.uniform(0.8, 1.5), 2)
            e = Entity.objects.create(
                world=world, name=f'Animal {i}', primitive='box',
                primitive_color='#000000',
                pos_x=round(random.uniform(-half*0.7, half*0.7), 1),
                pos_y=0,
                pos_z=round(random.uniform(-half*0.7, half*0.7), 1),
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(entity=e, script=animal_script, props={
                'species': sp, 'animalScale': ascale,
                'seed': random.randint(1, 9999),
            })
            EntityScript.objects.create(entity=e, script=animal_anim, props={
                'bounds': round(half * 0.6, 1),
                'speed': round(random.uniform(0.2, 0.8), 2),
            })

    # --- NPCs ---
    # Find the best available scripts (prefer V6 > V5 > V4 etc.)
    motion_lib = Script.objects.filter(slug='motion-quality-library').first()
    lod_mgr = Script.objects.filter(slug='npc-lod-manager').first()
    builder = (Script.objects.filter(slug__startswith='humanoid-builder')
               .order_by('-slug').first())
    react = Script.objects.filter(slug='plaza-react-v5').first()
    face_animator = Script.objects.filter(slug='face-animator').first()
    idle = (Script.objects.filter(slug__in=[
                'studio-idle-v4', 'garden-idle-v3', 'gallery-idle-v2'])
            .order_by('-slug').first())

    if builder:
        names = random.sample(_NPC_NAMES, min(n_npcs, len(_NPC_NAMES)))
        # Pull a random sample of SavedFace rows as avatar bindings.
        face_pool = list(SavedFace.objects.order_by('?').values_list('pk', flat=True)[:n_npcs])
        npc_ents = []
        for i, name in enumerate(names):
            x = random.uniform(-half*0.5, half*0.5)
            z = random.uniform(-half*0.5, half*0.5)
            ry = random.uniform(-180, 180)
            face_id = face_pool[i] if i < len(face_pool) else None
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
                face_id=face_id,
            )
            npc_ents.append(e)

        attachments = []
        for i, e in enumerate(npc_ents):
            # Motion library first (injects M utilities for ballet-quality movement)
            if motion_lib:
                attachments.append(EntityScript(entity=e, script=motion_lib, props={}))
            attachments.append(EntityScript(entity=e, script=builder, props={
                'skin': random.choice(_SKINS),
                'shirt': random.choice(_SHIRTS),
                'pants': random.choice(_PANTS),
                'shoes': random.choice(_SHOES),
                'hair': random.choice(_HAIRS),
                'eyes': random.choice(_EYES),
                'shoulderW': round(random.uniform(0.83, 1.08), 2),
                'hipW': round(random.uniform(0.88, 1.04), 2),
                'heightScale': round(random.uniform(0.91, 1.04), 2),
                'jawW': round(random.uniform(0.85, 1.1), 2),
                'cheekFull': round(random.uniform(0.9, 1.12), 2),
                'foreheadH': round(random.uniform(0.94, 1.05), 2),
            }))
            if lod_mgr:
                attachments.append(EntityScript(entity=e, script=lod_mgr, props={}))
            if face_animator:
                attachments.append(EntityScript(entity=e, script=face_animator, props={}))
            reaction = random.choice(_REACTIONS)
            if react:
                attachments.append(EntityScript(entity=e, script=react, props={
                    'reaction': reaction,
                    'bounds': [-half*0.8, -half*0.8, half*0.8, half*0.8],
                    'speed': round(random.uniform(0.4, 1.0), 2),
                }))
            elif idle:
                attachments.append(EntityScript(entity=e, script=idle, props={
                    'seated': False,
                }))
        EntityScript.objects.bulk_create(attachments)

    total = Entity.objects.filter(world=world).count()
    messages.success(
        request,
        f'Generated and saved: "{title}" — {total} entities.',
    )
    return redirect('aether:world_enter', slug=world.slug)


# ---------------------------------------------------------------------------
# World merge
# ---------------------------------------------------------------------------

def _copy_world_entities(src_world, dest_world, off_x=0.0, off_z=0.0):
    """Copy all assets, entities (with scripts), and portals from src_world
    into dest_world with a position offset. Returns count of entities copied."""
    asset_map = {}
    for a in src_world.assets.all():
        old_pk = a.pk
        a.pk = None
        a.slug = ''
        a.world = dest_world
        a.save()
        asset_map[old_pk] = a

    copied = 0
    for e in src_world.entities.all():
        old_pk = e.pk
        old_scripts = list(EntityScript.objects.filter(
            entity_id=old_pk, enabled=True,
        ).select_related('script'))

        e.pk = None
        e.world = dest_world
        e.pos_x += off_x
        e.pos_z += off_z
        if e.asset_id and e.asset_id in asset_map:
            e.asset = asset_map[e.asset_id]
        elif e.asset_id:
            e.asset = None
        e.save()
        copied += 1

        for es in old_scripts:
            EntityScript.objects.create(
                entity=e, script=es.script,
                props=es.props, sort_order=es.sort_order,
            )

    for p in src_world.portals_out.all():
        Portal.objects.create(
            from_world=dest_world, to_world=p.to_world,
            label=p.label,
            pos_x=p.pos_x + off_x, pos_y=p.pos_y,
            pos_z=p.pos_z + off_z,
            width=p.width, height=p.height,
        )
    return copied


@login_required
def world_merge(request):
    """Create a new world by merging two existing worlds. The 'base' world
    provides environment settings (sky, fog, ground, audio, spawn). Entities,
    assets, portals, and scripts from both worlds are copied into the new world.
    Neither original world is modified.
    """
    worlds = World.objects.all()

    if request.method == 'POST':
        base = get_object_or_404(World, pk=request.POST.get('base'))
        source = get_object_or_404(World, pk=request.POST.get('source'))

        if base.pk == source.pk:
            messages.error(request, 'Cannot merge a world with itself.')
            return redirect('aether:world_merge')

        off_x = float(request.POST.get('offset_x', 0))
        off_z = float(request.POST.get('offset_z', 0))

        # Create new world with base's environment settings
        merged = World(
            title=f'{base.title} + {source.title}',
            description=f'Merged from "{base.title}" and "{source.title}".',
            skybox=base.skybox,
            hdri_asset=base.hdri_asset,
            sky_color=base.sky_color,
            ground_color=base.ground_color,
            ground_size=max(base.ground_size, source.ground_size),
            ambient_light=base.ambient_light,
            fog_near=base.fog_near,
            fog_far=max(base.fog_far, source.fog_far),
            fog_color=base.fog_color,
            gravity=base.gravity,
            spawn_x=base.spawn_x, spawn_y=base.spawn_y, spawn_z=base.spawn_z,
            soundscape=base.soundscape,
            ambient_volume=base.ambient_volume,
            published=True, featured=False,
        )
        merged.save()

        _copy_world_entities(base, merged, 0.0, 0.0)
        _copy_world_entities(source, merged, off_x, off_z)

        total = Entity.objects.filter(world=merged).count()
        messages.success(request,
            f'Created "{merged.title}" — {total} total entities.')
        return redirect('aether:world_detail', slug=merged.slug)

    return render(request, 'aether/merge.html', {'worlds': worlds})


# ---------------------------------------------------------------------------
# Legoworld — Aether scene built from a Legolith brick payload
# ---------------------------------------------------------------------------

@login_required
def legoworld_generate(request):
    """GET: form to pick biome/seed/counts. POST: build + redirect to enter."""
    from .legoworld import (
        BIOMES as LEGO_BIOMES, DEFAULT_SCALE, HDRI_OPTIONS,
        HDRI_SLUGS as LEGO_HDRI_SLUGS, build_legoworld_in_aether,
    )

    if request.method == 'POST':
        def _int(name, default, lo=0, hi=16):
            try:
                return max(lo, min(hi, int(request.POST.get(name, default))))
            except (TypeError, ValueError):
                return default

        seed_raw = (request.POST.get('seed') or '').strip()
        try:
            seed = int(seed_raw) if seed_raw else random.randint(1, 99999)
        except ValueError:
            seed = random.randint(1, 99999)

        name = (request.POST.get('name') or 'meadow').strip()[:60] or 'meadow'
        biome = request.POST.get('biome', 'plains')
        if biome not in LEGO_BIOMES:
            biome = 'plains'

        classic = request.POST.get('classic') == '1' or request.GET.get('classic') == '1'
        if classic:
            hdri_asset = ''
        else:
            hdri_asset = (request.POST.get('hdri_asset') or '').strip()
            if hdri_asset == '__random__':
                hdri_asset = random.choice(LEGO_HDRI_SLUGS) if LEGO_HDRI_SLUGS else ''
            elif hdri_asset and hdri_asset not in LEGO_HDRI_SLUGS:
                hdri_asset = ''

        # Parse library picks: each "lib_<slug>" input holds a count.
        library_placements = []
        for key, val in request.POST.items():
            if not key.startswith('lib_'):
                continue
            slug = key[4:]
            try:
                count = max(0, min(32, int(val or 0)))
            except (TypeError, ValueError):
                count = 0
            if count:
                library_placements.append((slug, count))

        try:
            world, stats = build_legoworld_in_aether(
                name=name, biome=biome, seed=seed,
                n_buildings=_int('n_buildings', 4),
                n_trees=_int('n_trees', 6),
                n_flowers=_int('n_flowers', 4),
                n_people=_int('n_people', 2),
                n_hills=_int('n_hills', 0, hi=4),
                n_lamps=_int('n_lamps', 2, hi=8),
                n_rocks=_int('n_rocks', 2, hi=8),
                scale=DEFAULT_SCALE,
                library_placements=library_placements,
                hdri_asset=hdri_asset,
            )
        except RuntimeError as exc:
            messages.error(request, str(exc))
            return redirect('aether:generate_legoworld')

        messages.success(
            request,
            f'Built "{world.title}" — {stats["bricks"]} bricks, '
            f'~{stats["studs_estimate"]} studs.',
        )
        return redirect('aether:world_enter', slug=world.slug)

    from legolith.models import LegoModel
    classic = request.GET.get('classic') == '1'
    return render(request, 'aether/legoworld_form.html', {
        'biomes': sorted(LEGO_BIOMES.keys()),
        'library_models': LegoModel.objects.order_by('kind', 'name'),
        'hdri_options': [] if classic else HDRI_OPTIONS,
        'classic': classic,
    })


@login_required
@require_POST
def megalegoworld_generate(request):
    """Build a 4x4 matrix of Legoworlds stitched into a single Aether world."""
    from .legoworld import DEFAULT_SCALE, build_megalegoworld_in_aether

    seed = random.randint(1, 99999)
    name = (request.POST.get('name') or 'mega').strip()[:50] or 'mega'
    classic = request.POST.get('classic') == '1'

    try:
        world, stats = build_megalegoworld_in_aether(
            name=name, seed=seed, grid=4,
            scale=DEFAULT_SCALE,
            hdri_asset='' if classic else None,
        )
    except RuntimeError as exc:
        messages.error(request, str(exc))
        return redirect('aether:world_list')

    messages.success(
        request,
        f'Built "{world.title}" — {stats["tiles"]} tiles, '
        f'{stats["bricks"]} bricks (+{stats.get("library_placements", 0)} '
        f'from library), ~{stats["studs_estimate"]} studs.',
    )
    return redirect('aether:world_enter', slug=world.slug)


@login_required
@require_POST
def generate_megacity(request):
    """Build a 4x4 matrix of cafe districts merged into one Aether world."""
    from django.core.management import call_command
    from aether.management.commands.seed_megacity import Command as MegaCity
    cmd = MegaCity()
    try:
        call_command(cmd)
        world = getattr(cmd, '_world', None)
    except Exception as exc:
        messages.error(request, f'MegaCity seed failed: {exc}')
        return redirect('aether:world_list')

    if world is None:
        messages.error(request, 'MegaCity seed produced no world.')
        return redirect('aether:world_list')

    messages.success(request, f'Built "{world.title}" — 16 cafe cells, 48 NPCs.')
    return redirect('aether:world_enter', slug=world.slug)


# ---------------------------------------------------------------------------
# Boogaloo — random merge of two random worlds into a new world
# ---------------------------------------------------------------------------

@login_required
@require_POST
def boogaloo(request):
    """Pick two random existing worlds, create a new world with one's
    environment settings, copy entities from both with random offsets,
    and enter the result."""
    all_worlds = list(World.objects.all())
    if len(all_worlds) < 2:
        messages.error(request, 'Need at least 2 existing worlds for a Boogaloo.')
        return redirect('aether:world_list')

    base_src, donor_src = random.sample(all_worlds, 2)

    # New world gets the base's environment
    adjectives = ['Electric', 'Neon', 'Wild', 'Funky', 'Cosmic',
                  'Fever', 'Turbo', 'Mega', 'Ultra', 'Hyper']
    title = f'{random.choice(adjectives)} Boogaloo'

    ground_size = max(base_src.ground_size, donor_src.ground_size)

    world = World.objects.create(
        title=title,
        description=f'Boogaloo: {base_src.title} + {donor_src.title}',
        skybox=base_src.skybox,
        sky_color=base_src.sky_color,
        ground_color=base_src.ground_color,
        ground_size=ground_size,
        ambient_light=base_src.ambient_light,
        fog_near=base_src.fog_near,
        fog_far=max(base_src.fog_far, donor_src.fog_far),
        fog_color=base_src.fog_color,
        hdri_asset=base_src.hdri_asset,
        gravity=base_src.gravity,
        allow_flight=base_src.allow_flight or donor_src.allow_flight,
        spawn_x=0, spawn_y=1.6, spawn_z=round(ground_size * 0.15, 1),
        soundscape=base_src.soundscape or donor_src.soundscape,
        ambient_audio_url=base_src.ambient_audio_url or donor_src.ambient_audio_url,
        ambient_volume=base_src.ambient_volume,
        published=True, featured=False,
    )

    half = ground_size * 0.3
    donor_off_x = random.uniform(-half, half)
    donor_off_z = random.uniform(-half, half)

    _copy_world_entities(base_src, world, 0, 0)
    _copy_world_entities(donor_src, world, donor_off_x, donor_off_z)

    total = Entity.objects.filter(world=world).count()
    messages.success(request,
        f'Boogaloo! "{base_src.title}" + "{donor_src.title}" → '
        f'"{title}" — {total} entities.')
    return redirect('aether:world_enter', slug=world.slug)


# ---------------------------------------------------------------------------
# Reduce — thin out a world for performance
# ---------------------------------------------------------------------------

@login_required
@require_POST
def world_reduce(request, slug):
    """Create a lighter copy of a world by removing ~50% of non-essential
    entities. Keeps ground, spawn-area entities, and scripted NPCs;
    randomly culls static decoration (furniture, plants, etc.).
    Original world is preserved."""
    src = get_object_or_404(World, slug=slug)

    reduced = World(
        title=f'{src.title} (Reduced)',
        description=f'Lighter version of "{src.title}".',
        skybox=src.skybox, hdri_asset=src.hdri_asset,
        sky_color=src.sky_color, ground_color=src.ground_color,
        ground_size=src.ground_size, ambient_light=src.ambient_light,
        fog_near=src.fog_near, fog_far=src.fog_far, fog_color=src.fog_color,
        gravity=src.gravity,
        spawn_x=src.spawn_x, spawn_y=src.spawn_y, spawn_z=src.spawn_z,
        soundscape=src.soundscape, ambient_volume=src.ambient_volume,
        published=True, featured=False,
    )
    reduced.save()

    # Copy assets
    asset_map = {}
    for a in src.assets.all():
        old_pk = a.pk
        a.pk = None
        a.slug = ''
        a.world = reduced
        a.save()
        asset_map[old_pk] = a

    src_entities = list(src.entities.all())
    original_count = len(src_entities)
    kept = 0

    for e in src_entities:
        # Always keep: ground planes, scripted entities (NPCs, buildings, plants)
        is_ground = 'ground' in e.name.lower()
        is_road = 'road' in e.name.lower() or 'sidewalk' in e.name.lower()
        is_scripted = e.behavior == 'scripted'

        keep = is_ground or is_road or is_scripted or random.random() > 0.5

        if not keep:
            continue

        old_pk = e.pk
        old_scripts = list(EntityScript.objects.filter(
            entity_id=old_pk, enabled=True,
        ).select_related('script'))

        e.pk = None
        e.world = reduced
        if e.asset_id and e.asset_id in asset_map:
            e.asset = asset_map[e.asset_id]
        elif e.asset_id:
            e.asset = None
        e.save()
        kept += 1

        for es in old_scripts:
            EntityScript.objects.create(
                entity=e, script=es.script,
                props=es.props, sort_order=es.sort_order,
            )

    # Copy portals
    for p in src.portals_out.all():
        Portal.objects.create(
            from_world=reduced, to_world=p.to_world,
            label=p.label,
            pos_x=p.pos_x, pos_y=p.pos_y, pos_z=p.pos_z,
            width=p.width, height=p.height,
        )

    messages.success(request,
        f'Reduced "{src.title}" → "{reduced.title}" '
        f'({kept}/{original_count} entities kept).')
    return redirect('aether:world_detail', slug=reduced.slug)


# ---------------------------------------------------------------------------
# Mutate — clone a world with randomly varied environment + NPC palettes
# ---------------------------------------------------------------------------

_MUTATE_HDRI_POOL = [
    'brown_photostudio_02', 'kloofendal_48d_partly_cloudy', 'forest_slope',
    'potsdamer_platz', 'snowy_park_01',
]


def _hue_shift(hex_color, dh, ds=0.0, dv=0.0):
    """Rotate a hex color's hue by ``dh`` (0..1), optionally nudging S/V."""
    try:
        c = hex_color.lstrip('#')
        if len(c) != 6:
            return hex_color
        r, g, b = int(c[0:2], 16)/255, int(c[2:4], 16)/255, int(c[4:6], 16)/255
    except (ValueError, AttributeError):
        return hex_color
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + dh) % 1.0
    s = max(0.0, min(1.0, s + ds))
    v = max(0.0, min(1.0, v + dv))
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return '#{:02x}{:02x}{:02x}'.format(
        int(nr * 255), int(ng * 255), int(nb * 255))


@login_required
@require_POST
def world_mutate(request, slug):
    """Clone a world with random environmental + NPC-palette variation.

    Preserves: entities, scripts, portals, assets, spawn location.
    Varies: sky/ground/fog colors (hue shift), fog distances, ambient
    light and audio volume, occasional HDRI swap, occasional gravity
    quirk, and individual NPC outfit/hair colors on humanoid-builder
    scripts (shuffled hue).
    """
    src = get_object_or_404(World, slug=slug)

    # -- Environment mutation --
    sky = _hue_shift(src.sky_color,
                     random.uniform(-0.25, 0.25),
                     random.uniform(-0.08, 0.08),
                     random.uniform(-0.05, 0.05))
    ground = _hue_shift(src.ground_color,
                        random.uniform(-0.2, 0.2),
                        random.uniform(-0.05, 0.05),
                        random.uniform(-0.1, 0.1))
    fog = _hue_shift(src.fog_color,
                     random.uniform(-0.3, 0.3),
                     random.uniform(-0.1, 0.1),
                     random.uniform(-0.08, 0.08))
    fog_near = max(2.0, src.fog_near * random.uniform(0.75, 1.3))
    fog_far = max(fog_near + 5.0, src.fog_far * random.uniform(0.8, 1.25))
    ambient = max(0.08, min(0.85, src.ambient_light + random.uniform(-0.12, 0.12)))
    vol = max(0.0, min(1.0, src.ambient_volume + random.uniform(-0.2, 0.2)))

    # Rare: swap HDRI to another cafe-friendly one (25% chance if src uses HDRI).
    hdri = src.hdri_asset
    if src.skybox == 'hdri' and random.random() < 0.25:
        pool = [h for h in _MUTATE_HDRI_POOL if h != src.hdri_asset]
        if pool:
            hdri = random.choice(pool)

    # Very rare: gravity quirk (10% chance).
    gravity = src.gravity
    if random.random() < 0.10:
        gravity = random.choice([src.gravity * 0.5, src.gravity * 1.5,
                                 src.gravity * -1])

    mutated = World(
        title=f'{src.title} (Mutated)',
        description=f'Mutated clone of "{src.title}".',
        skybox=src.skybox, hdri_asset=hdri,
        sky_color=sky, ground_color=ground,
        ground_size=src.ground_size, ambient_light=round(ambient, 2),
        fog_near=round(fog_near, 1), fog_far=round(fog_far, 1),
        fog_color=fog, gravity=round(gravity, 2),
        allow_flight=src.allow_flight,
        spawn_x=src.spawn_x, spawn_y=src.spawn_y, spawn_z=src.spawn_z,
        soundscape=src.soundscape, ambient_volume=round(vol, 2),
        ambient_audio_url=src.ambient_audio_url,
        published=True, featured=False,
    )
    mutated.save()

    copied = _copy_world_entities(src, mutated, 0, 0)

    # -- NPC outfit mutation --
    # Walk humanoid-builder EntityScripts in the new world and hue-shift
    # every color prop. Each NPC gets its own shift so a crowd stays
    # varied rather than collectively recoloured.
    color_keys = ('skin', 'shirt', 'pants', 'shoes', 'hair', 'eyes')
    hb_scripts = EntityScript.objects.filter(
        entity__world=mutated,
        script__slug__startswith='humanoid-builder',
    )
    shifted = 0
    for es in hb_scripts:
        props = dict(es.props or {})
        shift = random.uniform(-0.18, 0.18)
        for k in color_keys:
            if isinstance(props.get(k), str) and props[k].startswith('#'):
                # Skin shifts less so people don't turn green; hair can drift.
                dh = shift * (0.25 if k == 'skin' else 1.0)
                props[k] = _hue_shift(props[k], dh)
        es.props = props
        es.save(update_fields=['props'])
        shifted += 1

    messages.success(request,
        f'Mutated "{src.title}" → "{mutated.title}" '
        f'({copied} entities, {shifted} NPC palettes rerolled).')
    return redirect('aether:world_detail', slug=mutated.slug)


# -----------------------------------------------------------------------
# Face Forge — procedurally bred kawaii faces
# -----------------------------------------------------------------------

@login_required
def face_forge(request):
    """The breeding/forge page. All generation + animation is client-side."""
    count = SavedFace.objects.count()
    return render(request, 'aether/face_forge.html', {'saved_count': count})


@login_required
@require_POST
def face_save(request):
    """Persist a face genome submitted by the forge JS."""
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'bad json'}, status=400)
    genome = payload.get('genome')
    name = (payload.get('name') or '').strip()
    if not isinstance(genome, dict):
        return JsonResponse({'ok': False, 'error': 'missing genome'}, status=400)
    if not name:
        # Autoname from traits so the library stays browsable.
        traits = genome.get('traits') or {}
        seed = genome.get('seed') or random.randint(1, 9_999_999)
        name = f"Face {seed % 100000:05d}"
        if traits.get('hat_kind'):
            name += f" ({traits['hat_kind']})"
    face = SavedFace.objects.create(
        name=name[:120],
        genome=genome,
        lineage=int(payload.get('lineage') or 0),
    )
    return JsonResponse({
        'ok': True,
        'id': face.pk, 'slug': face.slug, 'name': face.name,
    })


@login_required
def face_library(request):
    faces = SavedFace.objects.all()
    return render(request, 'aether/face_library.html', {'faces': faces})


@login_required
def face_library_json(request):
    faces = SavedFace.objects.all().values(
        'pk', 'name', 'slug', 'genome', 'lineage', 'favorite', 'created_at',
    )
    return JsonResponse({'faces': list(faces)}, safe=False)


@login_required
@require_POST
def face_delete(request, slug):
    face = get_object_or_404(SavedFace, slug=slug)
    face.delete()
    return redirect('aether:face_library')


@login_required
@require_POST
def face_favorite(request, slug):
    face = get_object_or_404(SavedFace, slug=slug)
    face.favorite = not face.favorite
    face.save()
    return redirect('aether:face_library')

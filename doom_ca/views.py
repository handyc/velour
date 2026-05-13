"""doom_ca views — list, create, play, delete."""

from __future__ import annotations
import json

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from spoeqi.models import Pact, COMPONENTS

from .models import GameSession


def index(request):
    sessions = GameSession.objects.select_related('pact').all()[:200]
    pacts_exist = Pact.objects.exists()
    return render(request, 'doom_ca/index.html', {
        'sessions':    sessions,
        'pacts_exist': pacts_exist,
    })


def create(request):
    pacts = Pact.objects.all().order_by('-created_at')[:200]
    errors = []
    valid_modes = {k for k, _ in GameSession.WORLD_MODE_CHOICES}
    form = {
        'name': '', 'pact_slug': '', 'component': '0',
        'world_mode': 'overlay',
        'monster_count': '8', 'wall_threshold': '2',
        'pure_mode': '',
        'health_pack_count': '3',
        'ammo_pack_count':   '3',
        'door_count':        '1',
        'notes': '',
    }

    if request.method == 'POST':
        form.update({k: request.POST.get(k, form.get(k, '')) for k in form})
        if not form['name'].strip():
            errors.append('A name is required.')
        try:
            component = int(form['component'])
        except ValueError:
            component = 0
        if not (0 <= component < COMPONENTS):
            errors.append(f'component must be 0..{COMPONENTS - 1}')
        try:
            monster_count = max(0, min(64, int(form['monster_count'])))
        except ValueError:
            monster_count = 8
        try:
            wall_threshold = max(1, min(3, int(form['wall_threshold'])))
        except ValueError:
            wall_threshold = 2
        try:
            health_pack_count = max(0, min(12, int(form['health_pack_count'])))
        except ValueError:
            health_pack_count = 3
        try:
            ammo_pack_count   = max(0, min(12, int(form['ammo_pack_count'])))
        except ValueError:
            ammo_pack_count = 3
        try:
            door_count        = max(0, min(1, int(form['door_count'])))
        except ValueError:
            door_count = 1
        world_mode = form['world_mode'] if form['world_mode'] in valid_modes else 'overlay'
        pure_mode = bool(form['pure_mode'])
        pact = Pact.objects.filter(slug=form['pact_slug']).first()
        if pact is None:
            errors.append('Pick an existing spoeqi pact.')

        if not errors:
            session = GameSession(
                name=form['name'].strip(),
                pact=pact,
                component=component,
                world_mode=world_mode,
                monster_count=monster_count,
                wall_threshold=wall_threshold,
                pure_mode=pure_mode,
                health_pack_count=health_pack_count,
                ammo_pack_count=ammo_pack_count,
                door_count=door_count,
                notes=form['notes'].strip(),
                created_by=request.user if request.user.is_authenticated else None,
            )
            session.save()
            messages.success(request, f'Game "{session.name}" ready.')
            return redirect('doom_ca:play', slug=session.slug)

    return render(request, 'doom_ca/new.html', {
        'pacts':      pacts,
        'form':       form,
        'errors':     errors,
        'components': COMPONENTS,
        'world_mode_choices': GameSession.WORLD_MODE_CHOICES,
    })


def play(request, slug):
    session = get_object_or_404(
        GameSession.objects.select_related('pact'), slug=slug)
    pact = session.pact
    payload = {
        'session_slug':   session.slug,
        'session_name':   session.name,
        'pact_slug':      pact.slug,
        'pact_name':      pact.name,
        'component':      session.component,
        'world_mode':     session.world_mode,
        'pure_mode':      session.pure_mode,
        'monster_count':  session.monster_count,
        'wall_threshold': session.wall_threshold,
        'health_pack_count': session.health_pack_count,
        'ammo_pack_count':   session.ammo_pack_count,
        'door_count':        session.door_count,
        'component_grid': pact.component_grid,
        'rules_hex':      pact.rules_hex,
        'seed_hex':       pact.seed_hex,
        'palette':        pact.palette,
        'components':     COMPONENTS,
        # The tap URL template — JS replaces the placeholders for
        # specific component / generation / n_bytes requests.
        'tap_url_template': (
            f'/spoeqi/{pact.slug}/tap/{{component}}/{{gen}}/{{n}}/'
        ),
    }
    return render(request, 'doom_ca/play.html', {
        'session': session,
        'pact':    pact,
        'payload': json.dumps(payload),
    })


@require_POST
def delete(request, slug):
    session = get_object_or_404(GameSession, slug=slug)
    name = session.name
    session.delete()
    messages.info(request, f'Game "{name}" deleted.')
    return redirect('doom_ca:index')


@ensure_csrf_cookie
def evolve(request):
    """Browser-side GA over doom_ca pact configurations.  The page
    embeds engine.js + the GA loop; the server only ships the page +
    handles materialisation of selected winners.  ensure_csrf_cookie
    so the materialise fetch() can read the cookie.
    """
    return render(request, 'doom_ca/evolve.html', {
        'world_mode_choices': GameSession.WORLD_MODE_CHOICES,
        'components': COMPONENTS,
    })


@require_POST
def materialize_agent(request):
    """Create a real Pact + GameSession from a gene posted as JSON.
    Called when the user clicks 'materialize' on a winning agent in
    the evolve page.  All other agents stay in the browser only —
    that's how we keep the DB from bloating with thousands of pacts.
    """
    from django.http import JsonResponse
    from django.utils import timezone
    import json as _json

    try:
        gene = _json.loads(request.body.decode())
    except (ValueError, TypeError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    rule_hex = gene.get('rule_hex') or ''
    if len(rule_hex) != 32768:
        return JsonResponse({'ok': False,
            'error': 'rule_hex must be 32768 chars (16384 bytes)'}, status=400)
    try:
        rule_bytes = bytes.fromhex(rule_hex)
        if any(b > 3 for b in rule_bytes):
            raise ValueError('rule bytes must be in 0..3')
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    seed_byte    = int(gene.get('seed_byte', 0)) & 0xFF
    world_mode   = gene.get('world_mode', 'overlay')
    component_grid  = int(gene.get('component_grid', 16))
    monster_count   = max(0, min(64, int(gene.get('monster_count', 8))))
    wall_threshold  = max(1, min(3, int(gene.get('wall_threshold', 2))))
    pure_mode    = bool(gene.get('pure_mode', False))
    health_pack_count = max(0, min(12, int(gene.get('health_pack_count', 3))))
    ammo_pack_count   = max(0, min(12, int(gene.get('ammo_pack_count',   3))))
    door_count        = max(0, min(1,  int(gene.get('door_count',        1))))
    base_name    = (gene.get('name') or 'evolved-pact').strip()[:60]

    # Validate the optional palette: 4 × [r, g, b], each 0..255
    palette = None
    pal_in = gene.get('palette')
    if isinstance(pal_in, list) and len(pal_in) == 4:
        try:
            palette = [[int(c[0]) & 0xFF, int(c[1]) & 0xFF, int(c[2]) & 0xFF]
                       for c in pal_in if isinstance(c, list) and len(c) == 3]
            if len(palette) != 4:
                palette = None
        except (TypeError, ValueError):
            palette = None

    valid_modes = {k for k, _ in GameSession.WORLD_MODE_CHOICES}
    if world_mode not in valid_modes:
        world_mode = 'overlay'

    # Unique names
    pact_name = f'{base_name}-pact'
    n = 2
    while Pact.objects.filter(name=pact_name).exists():
        pact_name = f'{base_name}-pact-{n}'; n += 1
    game_name = f'{base_name}-game'
    n = 2
    while GameSession.objects.filter(name=game_name).exists():
        game_name = f'{base_name}-game-{n}'; n += 1

    pact = Pact(
        name=pact_name,
        # All 64 components share the seed byte (we only use component 0).
        seed_matrix=bytes([seed_byte] * COMPONENTS),
        rule_snapshot=rule_bytes,
        rule_diversity='shared',
        component_grid=component_grid,
        clock_model='synced',
        launch_time=timezone.now(),
        notes='Materialised from doom_ca evolve.',
        created_by=request.user if request.user.is_authenticated else None,
    )
    if palette is not None:
        pact.palette = palette
    pact.save()

    session = GameSession(
        name=game_name, pact=pact, component=0,
        world_mode=world_mode, monster_count=monster_count,
        wall_threshold=wall_threshold, pure_mode=pure_mode,
        health_pack_count=health_pack_count,
        ammo_pack_count=ammo_pack_count,
        door_count=door_count,
        notes=f'Evolved gene (fitness shown in evolve page).',
        created_by=request.user if request.user.is_authenticated else None,
    )
    session.save()

    return JsonResponse({
        'ok': True,
        'play_url':     f'/doom-ca/{session.slug}/',
        'pact_slug':    pact.slug,
        'session_slug': session.slug,
        'pact_name':    pact.name,
        'session_name': session.name,
    })

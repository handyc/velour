"""doom_ca views — list, create, play, delete."""

from __future__ import annotations
import json

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
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
        world_mode = form['world_mode'] if form['world_mode'] in valid_modes else 'overlay'
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
        'monster_count':  session.monster_count,
        'wall_threshold': session.wall_threshold,
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

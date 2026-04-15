"""Bridge — the spacefleet commander's workspace.

The main view renders the bridge UI. Everything below that is
plumbing for warp jumps: the /warp/ endpoint creates a new Planet
row and returns its features so the client can render it; /library/
lists every planet ever discovered.
"""

import hashlib
import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Planet
from .planets import generate_planet


SHIP_NAMES = [
    'ISS Perseus', 'ISS Meridian', 'ISS Carina', 'ISS Halcyon',
    'ISS Ardent', 'ISS Tanager', 'ISS Kestrel', 'ISS Solstice',
    'ISS Orpheus', 'ISS Cygnet', 'ISS Nephele', 'ISS Anvil',
]

SECTORS = [
    'Hyades 4-Γ', 'Orion Spur, grid 081',
    'Cygnus Arm, grid 214', 'Serpens Ridge, grid 066',
    'Kuiper Fringe, grid 003', 'Beta Pictoris lane',
    'Gliese-581 approach', 'Trappist transit',
]

DESTINATIONS = [
    ('Vesta Drydock', '04d 11h 22m'),
    ('Europa Relay',  '01d 07h 40m'),
    ('Titan Anchorage', '02d 18h 03m'),
    ('Ceres Waypoint-B', '00d 19h 55m'),
    ('Proxima Outpost', '128d 02h 11m'),
    ('Ross-128 Station', '201d 14h 07m'),
]


def _pick(seed, options):
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return options[h % len(options)]


def _home_planet(seed):
    """Deterministic starting planet — each commander has their own
    home orbit, but it stays consistent across reloads."""
    h = int(hashlib.md5(('home:' + seed).encode()).hexdigest(), 16)
    return generate_planet(seed=h % (2**31))


@login_required
def home(request):
    seed = request.user.username or 'commander'
    rng = random.Random(seed)

    ship = _pick(seed + ':ship', SHIP_NAMES)
    sector = _pick(seed + ':sector', SECTORS)
    dest, eta = _pick(seed + ':dest', DESTINATIONS)

    home = _home_planet(seed)
    context = {
        'ship_name':   ship,
        'sector':      sector,
        'heading':     rng.randint(0, 359),
        'speed_c':     round(rng.uniform(0.08, 0.42), 3),
        'destination': dest,
        'eta':         eta,
        'fuel':        rng.randint(62, 94),
        'hull':        rng.randint(78, 99),
        'shields':     rng.randint(55, 100),
        'commander':   request.user.username,
        'home_planet': home,
        # JSON-serialized for direct embedding in the three.js bootstrap.
        # Marked safe in the template; values come from generate_planet()
        # which only yields plain dicts/lists/strings/numbers.
        'home_planet_json': json.dumps(home),
        'library_count': Planet.objects.count(),
    }
    return render(request, 'bridge/home.html', context)


@login_required
@require_POST
def warp(request):
    """Generate + persist a new random planet, return its features."""
    features = generate_planet()
    planet = Planet.objects.create(
        name=features['name'],
        seed=features['seed'],
        ptype=features['type'],
        features=features,
    )
    return JsonResponse({
        'id':      planet.id,
        'planet':  features,
        'library': Planet.objects.count(),
    })


@login_required
def beam_down(request):
    """Land on a random Aether world.

    The bridge is an instruments UI; Aether is where actual 3D surface
    exploration happens. Beam Down bridges the two — pick a random
    World and redirect to its enter view. If there are no worlds yet,
    nudge the user toward the Aether list so they can generate one.
    """
    from aether.models import World   # lazy: avoid circular at import time
    world = World.objects.order_by('?').first()
    if world is None:
        messages.info(
            request,
            'No Aether worlds to beam down to yet — generate one first.',
        )
        return redirect('aether:world_list')
    return redirect(reverse('aether:world_enter', args=[world.slug]))


@login_required
def library(request):
    """List every planet ever discovered — the warp atlas."""
    planets = Planet.objects.all()[:500]
    # pre-compute a handful of summary fields for the template
    annotated = []
    for p in planets:
        f = p.features
        annotated.append({
            'obj':         p,
            'color':       f.get('color', '#888'),
            'has_ring':    bool(f.get('ring')),
            'ring_color':  (f.get('ring') or {}).get('color', ''),
            'moon_count':  len(f.get('moons', [])),
            'sat_count':   len(f.get('satellites', [])),
            'atm':         bool(f.get('atmosphere')),
        })
    return render(request, 'bridge/library.html', {
        'planets': annotated,
        'total':   Planet.objects.count(),
    })

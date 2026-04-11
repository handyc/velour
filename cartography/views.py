from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import MapPrefs, Place, SCALE_CHOICES


@login_required
def cartography_home(request):
    """The default landing — Earth scale, centered at the configured
    default location (Leiden out of the box). Renders the Leaflet
    container; the JS does the heavy lifting."""
    prefs = MapPrefs.load()
    earth_places = Place.objects.filter(scale='earth')
    return render(request, 'cartography/earth.html', {
        'prefs': prefs,
        'places': earth_places,
        'scale': 'earth',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def cartography_mars(request):
    places = Place.objects.filter(scale='mars')
    return render(request, 'cartography/mars.html', {
        'places': places,
        'scale': 'mars',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def cartography_moon(request):
    places = Place.objects.filter(scale='moon')
    return render(request, 'cartography/moon.html', {
        'places': places,
        'scale': 'moon',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def cartography_sky(request):
    places = Place.objects.filter(scale='sky')
    return render(request, 'cartography/sky.html', {
        'places': places,
        'scale': 'sky',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def cartography_solar(request):
    places = Place.objects.filter(scale='solar_system')
    return render(request, 'cartography/solar.html', {
        'places': places,
        'scale': 'solar_system',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def places_json(request):
    """JSON list of saved places, optionally filtered by scale.

    The Leaflet templates fetch this on load to populate markers.
    Returns minimal fields — name, slug, lat, lon, zoom, color.
    """
    scale = request.GET.get('scale', '')
    qs = Place.objects.all()
    if scale:
        qs = qs.filter(scale=scale)
    return JsonResponse({
        'places': [
            {
                'slug':  p.slug,
                'name':  p.name,
                'scale': p.scale,
                'lat':   p.lat,
                'lon':   p.lon,
                'zoom':  p.zoom,
                'color': p.color,
                'notes': p.notes,
            }
            for p in qs
        ],
    })


# --- Place CRUD ---------------------------------------------------------

_PLACE_TEXT_FIELDS = ('name', 'notes', 'color')


def _apply_place_post(p, post):
    for f in _PLACE_TEXT_FIELDS:
        setattr(p, f, post.get(f, '').strip())
    p.scale = post.get('scale', 'earth')
    try:
        p.lat = float(post.get('lat', '0'))
    except ValueError:
        p.lat = 0.0
    try:
        p.lon = float(post.get('lon', '0'))
    except ValueError:
        p.lon = 0.0
    try:
        p.zoom = int(post.get('zoom', '10'))
    except ValueError:
        p.zoom = 10


@login_required
def place_list(request):
    qs = Place.objects.all()
    return render(request, 'cartography/place_list.html', {
        'places': qs,
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def place_add(request):
    p = Place()
    initial_scale = request.GET.get('scale', 'earth')
    p.scale = initial_scale
    if request.method == 'POST':
        _apply_place_post(p, request.POST)
        if not p.name:
            messages.error(request, 'Name is required.')
        else:
            p.save()
            messages.success(request, f'Saved place "{p.name}".')
            # Send the user back to the matching scale view.
            scale_url_map = {
                'earth':        'cartography:home',
                'mars':         'cartography:mars',
                'moon':         'cartography:moon',
                'sky':          'cartography:sky',
                'solar_system': 'cartography:solar',
            }
            return redirect(scale_url_map.get(p.scale, 'cartography:home'))
    return render(request, 'cartography/place_form.html', {
        'place': p,
        'action': 'New',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
def place_edit(request, slug):
    p = get_object_or_404(Place, slug=slug)
    if request.method == 'POST':
        _apply_place_post(p, request.POST)
        if not p.name:
            messages.error(request, 'Name is required.')
        else:
            p.save()
            messages.success(request, f'Updated "{p.name}".')
            return redirect('cartography:place_list')
    return render(request, 'cartography/place_form.html', {
        'place': p,
        'action': 'Edit',
        'scale_choices': SCALE_CHOICES,
    })


@login_required
@require_POST
def place_delete(request, slug):
    p = get_object_or_404(Place, slug=slug)
    name = p.name
    p.delete()
    messages.success(request, f'Removed "{name}".')
    return redirect('cartography:place_list')

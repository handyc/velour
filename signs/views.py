"""signs views — list, detail, viewer, frames JSON.

Viewer is a single Three.js page that fetches frames.json for the
chosen Sign and plays back the 30-cylinder rotations directly,
matching the signtest.html data model.
"""

from __future__ import annotations
import json
import random

from django.core.paginator import Paginator
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Language, Variety, Sign
from . import similarity


PAGE_SIZE = 50


def index(request):
    languages = Language.objects.prefetch_related('varieties').order_by('name')

    qs = (Sign.objects.select_related('lemma', 'variety', 'variety__language')
                      .order_by('lemma__gloss',
                                'variety__language__name',
                                'variety__name'))

    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(lemma__gloss__icontains=q)

    v_slug = (request.GET.get('v') or '').strip()
    chosen_variety = None
    if v_slug:
        chosen_variety = Variety.objects.filter(slug=v_slug).first()
        if chosen_variety:
            qs = qs.filter(variety=chosen_variety)

    total = qs.count()
    paginator = Paginator(qs, PAGE_SIZE)
    page_num = max(1, int(request.GET.get('page') or 1))
    page = paginator.get_page(page_num)

    varieties = Variety.objects.select_related('language').order_by(
        'language__name', 'name')

    return render(request, 'signs/index.html', {
        'languages':       languages,
        'varieties':       varieties,
        'page':            page,
        'total':           total,
        'q':               q,
        'chosen_variety':  chosen_variety,
        'page_size':       PAGE_SIZE,
    })


def random_sign(request):
    """Redirect to the viewer of a random Sign. Respects the ``?v=``
    variety filter if present."""
    qs = Sign.objects.all()
    v_slug = (request.GET.get('v') or '').strip()
    if v_slug:
        qs = qs.filter(variety__slug=v_slug)
    n = qs.count()
    if n == 0:
        raise Http404('no signs available')
    pick = qs[random.randrange(n)]
    return redirect(reverse('signs:viewer', args=[pick.slug]))


def detail(request, slug):
    sign = get_object_or_404(
        Sign.objects.select_related('lemma', 'variety',
                                    'variety__language', 'source'),
        slug=slug)
    neighbors = _nearest_neighbors(sign, n=10)
    return render(request, 'signs/detail.html', {
        'sign':      sign,
        'frames':    sign.frames.order_by('index'),
        'neighbors': neighbors,
    })


def _nearest_neighbors(sign: Sign, *, n: int = 10):
    """Return up to ``n`` Signs nearest to ``sign`` by signature
    distance, restricted to the same Variety. Each entry is
    ``(neighbor_sign, distance)``. Empty if ``sign`` has no
    signature yet."""
    if not sign.signature:
        return []
    candidates = (Sign.objects.filter(variety=sign.variety)
                              .exclude(pk=sign.pk)
                              .exclude(signature__isnull=True)
                              .select_related('lemma', 'variety')
                              .only('id', 'slug', 'signature',
                                    'lemma__gloss', 'variety__name'))
    ranked = similarity.nearest(
        sign.signature,
        ((s.id, s.signature) for s in candidates),
        n=n)
    by_id = {s.id: s for s in Sign.objects.filter(
        pk__in=[sid for sid, _ in ranked]
    ).select_related('lemma', 'variety')}
    return [(by_id[sid], d) for sid, d in ranked if sid in by_id]


def viewer(request, slug):
    sign = get_object_or_404(
        Sign.objects.select_related('lemma', 'variety',
                                    'variety__language'),
        slug=slug)
    return render(request, 'signs/viewer.html', {
        'sign': sign,
    })


def frames_json(request, slug):
    """JSON frame array in the signtest viewer's native shape.

    Output:
        {
          "name":   "<lemma gloss>",
          "fps":    <int>,
          "frames": [
            { "pose": [[rx,ry,rz], ...30...],
              "duration": <ms>,
              "wrist_l": [rx,ry,rz], "wrist_r": [rx,ry,rz],
              "palm_l":  [x,y,z],    "palm_r":  [x,y,z] },
            ...
          ]
        }
    """
    sign = get_object_or_404(Sign, slug=slug)
    frames = []
    for f in sign.frames.order_by('index'):
        frames.append({
            'pose':     f.cylinder_rotations,
            'duration': f.duration_ms,
            'wrist_l':  f.wrist_l_rot or [0, 0, 0],
            'wrist_r':  f.wrist_r_rot or [0, 0, 0],
            'palm_l':   f.palm_l_pos  or [],
            'palm_r':   f.palm_r_pos  or [],
        })
    return JsonResponse({
        'name':   sign.lemma.gloss,
        'fps':    sign.fps,
        'frames': frames,
    })

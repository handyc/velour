"""signs views — list, detail, viewer, frames JSON.

Viewer is a single Three.js page that fetches frames.json for the
chosen Sign and plays back the 30-cylinder rotations directly,
matching the signtest.html data model.
"""

from __future__ import annotations
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import Language, Sign


def index(request):
    languages = Language.objects.prefetch_related('varieties').order_by('name')
    signs = (Sign.objects.select_related('lemma', 'variety', 'variety__language')
                          .order_by('variety__language__name',
                                    'variety__name',
                                    'lemma__gloss'))
    return render(request, 'signs/index.html', {
        'languages': languages,
        'signs':     signs,
    })


def detail(request, slug):
    sign = get_object_or_404(
        Sign.objects.select_related('lemma', 'variety',
                                    'variety__language', 'source'),
        slug=slug)
    return render(request, 'signs/detail.html', {
        'sign':   sign,
        'frames': sign.frames.order_by('index'),
    })


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

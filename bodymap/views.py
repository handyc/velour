"""Bodymap — list, diagram, and the firmware-facing segment-report API.

The API auth pattern mirrors `nodes.views.api_report`: Authorization:
Bearer <node.api_token>. The endpoint is idempotent on (node) — a node
calling it twice updates its existing Segment row rather than creating
a new one. If the row is `operator_locked`, the API silently succeeds
with a `locked: true` flag so the firmware doesn't retry in a loop.
"""

import hmac
import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from experiments.models import Experiment
from nodes.models import Node

from .models import Segment


def _extract_bearer(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    return None


_VALID_ROLES = {r for r, _ in Segment.ROLE_CHOICES}


@login_required
def bodymap_list(request):
    """Table of every Node that has a Segment row. Unassigned wearables
    (no Segment yet) are listed separately so operators can see which
    devices still need to go through clustering."""
    segments = (Segment.objects
                .select_related('node', 'node__hardware_profile', 'experiment')
                .all())

    # Nodes that look bodymap-like (attached to an Experiment whose
    # slug contains "bodymap", or hardware_profile name mentions it)
    # but have no Segment yet — surface these so operators notice.
    assigned_node_ids = {s.node_id for s in segments}
    orphans = (Node.objects
               .select_related('hardware_profile', 'experiment')
               .filter(experiment__slug__icontains='bodymap')
               .exclude(pk__in=assigned_node_ids))

    return render(request, 'bodymap/list.html', {
        'segments': segments,
        'orphans':  list(orphans),
    })


@login_required
def bodymap_diagram(request, experiment_slug):
    """SVG body silhouette for a specific bodymap fleet (Experiment)."""
    experiment = get_object_or_404(Experiment, slug=experiment_slug)
    segments = (Segment.objects
                .select_related('node')
                .filter(experiment=experiment))
    by_role = {s.role: s for s in segments}
    return render(request, 'bodymap/diagram.html', {
        'experiment': experiment,
        'segments':   segments,
        'by_role':    by_role,
        'role_choices': Segment.ROLE_CHOICES,
    })


@csrf_exempt
@require_POST
def api_report_segment(request):
    """Firmware reports its clustered role assignment.

    POST /bodymap/api/segment/
    Headers: Authorization: Bearer <node.api_token>
    Body (JSON):
      {
        "slug":       "bodymap-aabbcc",   // required — identifies the node
        "role":       "forearm_l",        // required — one of ROLE_CHOICES
        "confidence": 0.87                // optional, default 0.0
      }

    Returns 200 on success:
      {"ok": true, "role": "forearm_l", "locked": false}

    When the Segment is operator_locked, the server ignores the role
    change but still returns 200 with {"locked": true, "role": <current>}
    so the firmware can stop retrying.
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        return JsonResponse({'error': f'invalid JSON: {e}'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'error': 'JSON body must be an object'}, status=400)

    slug = str(payload.get('slug', '')).strip()
    if not slug:
        return JsonResponse({'error': 'slug is required'}, status=400)

    try:
        node = Node.objects.select_related('experiment').get(slug=slug)
    except Node.DoesNotExist:
        raise Http404('unknown node')

    if not node.enabled:
        return JsonResponse({'error': 'node disabled'}, status=403)

    client_token = _extract_bearer(request)
    if not client_token or not hmac.compare_digest(node.api_token, client_token):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    role = str(payload.get('role', '')).strip()
    if role not in _VALID_ROLES:
        return JsonResponse(
            {'error': f'invalid role: {role!r}'}, status=400,
        )

    confidence_raw = payload.get('confidence', 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'confidence must be a number'}, status=400)
    # Clamp to [0, 1] so bad firmware can't write garbage.
    confidence = max(0.0, min(1.0, confidence))

    segment, _created = Segment.objects.get_or_create(
        node=node,
        defaults={
            'experiment': node.experiment,
            'role':       role,
            'confidence': confidence,
        },
    )

    if segment.operator_locked:
        return JsonResponse({
            'ok':     True,
            'locked': True,
            'role':   segment.role,
        })

    changed = False
    if segment.role != role:
        segment.role = role
        changed = True
    if abs(segment.confidence - confidence) > 1e-6:
        segment.confidence = confidence
        changed = True
    # Keep experiment in sync with the node's current Experiment so
    # moving a node between fleets (via admin) propagates here.
    if segment.experiment_id != node.experiment_id:
        segment.experiment = node.experiment
        changed = True
    if changed or _created:
        segment.save()

    return JsonResponse({
        'ok':     True,
        'locked': False,
        'role':   segment.role,
    })

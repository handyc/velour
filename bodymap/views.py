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
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from experiments.models import Experiment
from nodes.models import Node

from .models import NodeSensorConfig, Segment


def _extract_bearer(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    return None


_VALID_ROLES = {r for r, _ in Segment.ROLE_CHOICES}


_CHANNEL_KINDS = {
    'digital':         ('pin', 'pull', 'active_low'),
    'analog':          ('pin', 'scale', 'offset', 'avg'),
    'attiny_i2c':      ('addr', 'bytes', 'scale', 'offset'),
    'attiny_pwm':      ('pin', 'timeout_us'),
    'attiny_softuart': ('pin', 'baud'),
}


def _normalise_channel(kind, raw):
    """Pick out the keys relevant to `kind`, coerce them to the right
    types, drop blanks. Silent on unknown fields — the form hides them
    already, but keep behaviour tolerant so a stale POST doesn't 500."""
    entry = {'channel': str(raw.get('channel', '')).strip(),
             'kind':    kind}
    for field in _CHANNEL_KINDS[kind]:
        val = raw.get(field, '')
        if val == '' or val is None:
            continue
        if field in ('pin', 'addr', 'bytes', 'avg', 'timeout_us', 'baud'):
            try:
                entry[field] = int(val)
            except (TypeError, ValueError):
                continue
        elif field in ('scale', 'offset'):
            try:
                entry[field] = float(val)
            except (TypeError, ValueError):
                continue
        elif field == 'active_low':
            entry[field] = str(val).lower() in ('1', 'true', 'on', 'yes')
        elif field == 'pull':
            v = str(val).strip().lower()
            if v in ('up', 'down'):
                entry[field] = v
        else:
            entry[field] = val
    return entry


@login_required
def bodymap_node_config(request, slug):
    """Structured editor for NodeSensorConfig.channels.

    GET renders one row per existing channel, plus empty-row scaffolding
    the page's JS clones when the operator clicks "Add channel". POST
    walks the form data by row index, validates each row against its
    declared kind, and overwrites NodeSensorConfig.channels as a whole
    (no partial updates — the form is the source of truth).
    """
    node = get_object_or_404(Node, slug=slug)
    cfg, _ = NodeSensorConfig.objects.get_or_create(node=node)

    if request.method == 'POST':
        kinds = request.POST.getlist('kind')
        names = request.POST.getlist('channel')
        pins  = request.POST.getlist('pin')
        pulls = request.POST.getlist('pull')
        alows = request.POST.getlist('active_low')
        scales  = request.POST.getlist('scale')
        offsets = request.POST.getlist('offset')
        avgs    = request.POST.getlist('avg')
        addrs   = request.POST.getlist('addr')
        bytes_  = request.POST.getlist('bytes')
        touts   = request.POST.getlist('timeout_us')
        bauds   = request.POST.getlist('baud')

        rows = []
        seen_names = set()
        errors = []
        for i, kind in enumerate(kinds):
            if kind not in _CHANNEL_KINDS:
                continue
            raw = {
                'channel':    names[i] if i < len(names) else '',
                'pin':        pins[i] if i < len(pins) else '',
                'pull':       pulls[i] if i < len(pulls) else '',
                # active_low is rendered as a <select> in the template
                # (values "0"/"1") so every row submits a value — this
                # keeps the getlist() indexes aligned across rows.
                'active_low': alows[i] if i < len(alows) else '',
                'scale':      scales[i] if i < len(scales) else '',
                'offset':     offsets[i] if i < len(offsets) else '',
                'avg':        avgs[i] if i < len(avgs) else '',
                'addr':       addrs[i] if i < len(addrs) else '',
                'bytes':      bytes_[i] if i < len(bytes_) else '',
                'timeout_us': touts[i] if i < len(touts) else '',
                'baud':       bauds[i] if i < len(bauds) else '',
            }
            entry = _normalise_channel(kind, raw)
            if not entry['channel']:
                errors.append(f'Row {i + 1}: channel name is required.')
                continue
            if entry['channel'] in seen_names:
                errors.append(
                    f'Row {i + 1}: duplicate channel name '
                    f'{entry["channel"]!r}.',
                )
                continue
            seen_names.add(entry['channel'])
            rows.append(entry)

        if not errors:
            cfg.channels = rows
            cfg.notes = request.POST.get('notes', '').strip()
            cfg.save()
            url = reverse('bodymap:node_config', kwargs={'slug': node.slug})
            return redirect(f'{url}?saved=1')

        # Errors: re-render with the submitted rows preserved so the
        # operator doesn't lose their edits.
        return render(request, 'bodymap/config_wizard.html', {
            'node':     node,
            'cfg':      cfg,
            'channels': rows,
            'kinds':    _CHANNEL_KINDS,
            'errors':   errors,
        })

    return render(request, 'bodymap/config_wizard.html', {
        'node':     node,
        'cfg':      cfg,
        'channels': cfg.channels or [],
        'kinds':    _CHANNEL_KINDS,
        'saved':    request.GET.get('saved') == '1',
    })


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


def api_node_config(request, slug):
    """Firmware fetches its per-node sensor channel list.

    GET /bodymap/api/config/<slug>/
    Headers: Authorization: Bearer <node.api_token>

    Returns 200:
      {
        "slug":     "bodymap-aabbcc",
        "channels": [ {...}, {...} ],
        "version":  "2026-04-18T11:13:02"   // updated_at ISO, for cache invalidation
      }

    When the node has no NodeSensorConfig row yet, returns an empty list
    so the firmware can proceed with just the built-in heartbeat/mesh
    channels. That matches the "one firmware everywhere" property —
    new hardware boots fine even if the operator hasn't filled in a
    config yet.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)

    try:
        node = Node.objects.select_related('bodymap_sensor_config').get(slug=slug)
    except Node.DoesNotExist:
        raise Http404('unknown node')

    if not node.enabled:
        return JsonResponse({'error': 'node disabled'}, status=403)

    client_token = _extract_bearer(request)
    if not client_token or not hmac.compare_digest(node.api_token, client_token):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        cfg = node.bodymap_sensor_config
        channels = cfg.channels or []
        version = cfg.updated_at.isoformat()
    except NodeSensorConfig.DoesNotExist:
        channels = []
        version = ''

    return JsonResponse({
        'slug':     node.slug,
        'channels': channels,
        'version':  version,
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

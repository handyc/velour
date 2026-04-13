import hashlib
import hmac
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from experiments.models import Experiment

from .models import Firmware, HardwareProfile, Node, SensorReading


# --- field helpers --------------------------------------------------

_NODE_TEXT_FIELDS = ('nickname', 'slug', 'mac_address', 'hostname',
                     'firmware_version', 'notes')


def _apply_node_post(node, post):
    for f in _NODE_TEXT_FIELDS:
        setattr(node, f, post.get(f, '').strip())
    node.power_mode = post.get('power_mode', 'unknown')
    node.enabled = bool(post.get('enabled'))

    hp_id = post.get('hardware_profile', '').strip()
    node.hardware_profile = HardwareProfile.objects.filter(pk=hp_id).first() if hp_id else None

    exp_id = post.get('experiment', '').strip()
    node.experiment = Experiment.objects.filter(pk=exp_id).first() if exp_id else None

    last_ip = post.get('last_ip', '').strip()
    node.last_ip = last_ip or None


# --- node views ----------------------------------------------------


def _node_status(age_seconds, enabled, is_dormant_expected):
    """Classify a node as online/stale/offline/dormant/unknown.

    Thresholds are fixed:
      < 5 min   → online  (green)
      5-30 min  → stale   (yellow)
      > 30 min  → offline (red), or dormant (gray) if power mode is
                  solar/battery/on_demand
      never     → unknown (blue dashed)
      disabled  → unknown + disabled
    """
    if not enabled:
        return 'disabled unknown'
    if age_seconds is None:
        return 'unknown'
    if age_seconds < 300:
        return 'online'
    if age_seconds < 1800:
        return 'stale'
    return 'dormant' if is_dormant_expected else 'offline'


def fleet_json(request):
    """Live fleet status for the JS poller on the list page."""
    from django.utils import timezone as tz
    nodes = Node.objects.select_related('hardware_profile').all()
    now = tz.now()
    data = {}
    for n in nodes:
        if n.last_seen_at:
            age = (now - n.last_seen_at).total_seconds()
            if age < 60:
                ago = f'{int(age)}s ago'
            elif age < 3600:
                ago = f'{int(age // 60)}m ago'
            else:
                ago = f'{int(age // 3600)}h ago'
        else:
            age = None
            ago = 'never'
        data[n.slug] = {
            'ago': ago,
            'ip': n.last_ip or '',
            'fw': n.firmware_version or '',
            'status': _node_status(age, n.enabled, n.is_dormant_expected),
        }
    return JsonResponse(data)


@login_required
def node_list(request):
    """Fleet grid. Supports filters by hardware profile, experiment,
    power mode, and enabled flag via query params."""
    qs = Node.objects.select_related('hardware_profile', 'experiment').all()

    hp_filter = request.GET.get('hardware', '').strip()
    if hp_filter:
        qs = qs.filter(hardware_profile__pk=hp_filter)

    exp_filter = request.GET.get('experiment', '').strip()
    if exp_filter:
        qs = qs.filter(experiment__pk=exp_filter)

    pm_filter = request.GET.get('power_mode', '').strip()
    if pm_filter:
        qs = qs.filter(power_mode=pm_filter)

    if request.GET.get('enabled_only'):
        qs = qs.filter(enabled=True)

    from django.utils import timezone as tz
    now = tz.now()
    nodes = list(qs)
    for n in nodes:
        age = (now - n.last_seen_at).total_seconds() if n.last_seen_at else None
        n.fleet_status = _node_status(age, n.enabled, n.is_dormant_expected)

    return render(request, 'nodes/list.html', {
        'nodes': nodes,
        'hardware_profiles': HardwareProfile.objects.all(),
        'experiments': Experiment.objects.all(),
        'power_choices': Node.POWER_CHOICES,
        'hp_filter': hp_filter,
        'exp_filter': exp_filter,
        'pm_filter': pm_filter,
        'enabled_only': bool(request.GET.get('enabled_only')),
        'node_count': len(nodes),
        'total_count': Node.objects.count(),
    })


@login_required
def node_add(request):
    node = Node()
    if request.method == 'POST':
        _apply_node_post(node, request.POST)
        if not node.nickname:
            messages.error(request, 'Nickname is required.')
        else:
            try:
                node.save()
                messages.success(request, f'Added node "{node.nickname}" ({node.slug}).')
                return redirect('nodes:detail', slug=node.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'nodes/form.html', {
        'node': node,
        'action': 'Add',
        'hardware_profiles': HardwareProfile.objects.all(),
        'experiments': Experiment.objects.all(),
        'power_choices': Node.POWER_CHOICES,
    })


@login_required
def node_edit(request, slug):
    node = get_object_or_404(Node, slug=slug)
    if request.method == 'POST':
        _apply_node_post(node, request.POST)
        if not node.nickname:
            messages.error(request, 'Nickname is required.')
        else:
            try:
                node.save()
                messages.success(request, f'Updated "{node.nickname}".')
                return redirect('nodes:detail', slug=node.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'nodes/form.html', {
        'node': node,
        'action': 'Edit',
        'hardware_profiles': HardwareProfile.objects.all(),
        'experiments': Experiment.objects.all(),
        'power_choices': Node.POWER_CHOICES,
    })


@login_required
@require_POST
def node_delete(request, slug):
    node = get_object_or_404(Node, slug=slug)
    nickname = node.nickname
    node.delete()
    messages.success(request, f'Removed "{nickname}".')
    return redirect('nodes:list')


@login_required
def node_detail(request, slug):
    node = get_object_or_404(Node, slug=slug)

    # Latest reading per channel, plus count of readings per channel.
    # This is N+1-queries-safe because the result set is capped at the
    # number of distinct channels, which is small in practice.
    channel_names = list(
        SensorReading.objects
        .filter(node=node)
        .values_list('channel', flat=True)
        .distinct()
    )
    channel_summary = []
    for channel in sorted(channel_names):
        latest = (SensorReading.objects
                  .filter(node=node, channel=channel)
                  .order_by('-received_at')
                  .first())
        count = SensorReading.objects.filter(node=node, channel=channel).count()
        channel_summary.append({
            'channel': channel,
            'latest_value': latest.value if latest else None,
            'latest_at':    latest.received_at if latest else None,
            'count':        count,
        })

    recent_readings = (SensorReading.objects
                       .filter(node=node)
                       .order_by('-received_at')[:25])

    return render(request, 'nodes/detail.html', {
        'node': node,
        'channel_summary': channel_summary,
        'recent_readings': recent_readings,
        'total_reading_count': SensorReading.objects.filter(node=node).count(),
    })


@login_required
@require_POST
def node_rotate_token(request, slug):
    """Generate a fresh API token for this node (invalidating the old one)."""
    from .models import _generate_api_token
    node = get_object_or_404(Node, slug=slug)
    node.api_token = _generate_api_token()
    node.save(update_fields=['api_token'])
    messages.success(request, f'Rotated API token for "{node.nickname}".')
    return redirect('nodes:detail', slug=slug)


@login_required
def node_live_json(request, slug):
    """Live readings JSON for the node detail page poller.

    Returns the most-recent value per *currently active* channel, plus
    a small rolling window of recent values per channel for inline
    sparklines. A channel is considered active if it has at least one
    reading in the last LIVE_WINDOW_SECONDS (default 5 minutes); this
    keeps historical channels (e.g., test channels from earlier
    sketch versions) from cluttering the live display once the node
    has stopped reporting them.

    The JS on the detail page polls this every few seconds and updates
    a stable set of card elements in place — the card DOM is created
    once and the values + sparklines mutate, no replacement.
    """
    from datetime import timedelta

    node = get_object_or_404(Node, slug=slug)
    history_n = 30
    LIVE_WINDOW_SECONDS = 300

    cutoff = timezone.now() - timedelta(seconds=LIVE_WINDOW_SECONDS)

    active_channels = list(
        SensorReading.objects
        .filter(node=node, received_at__gte=cutoff)
        .values_list('channel', flat=True)
        .distinct()
    )

    channels = []
    for ch in sorted(active_channels):
        latest = (SensorReading.objects
                  .filter(node=node, channel=ch)
                  .order_by('-received_at')
                  .first())
        history_qs = (SensorReading.objects
                      .filter(node=node, channel=ch)
                      .order_by('-received_at')[:history_n])
        history = list(history_qs)
        history.reverse()
        channels.append({
            'channel':      ch,
            'latest_value': latest.value if latest else None,
            'latest_at':    latest.received_at.isoformat() if latest else None,
            'history':      [r.value for r in history],
            'history_at':   [r.received_at.isoformat() for r in history],
        })

    return JsonResponse({
        'node':            node.slug,
        'nickname':        node.nickname,
        'last_seen_at':    node.last_seen_at.isoformat() if node.last_seen_at else None,
        'last_ip':         node.last_ip,
        'firmware':        node.firmware_version,
        'live_window_sec': LIVE_WINDOW_SECONDS,
        'channels':        channels,
    })


# --- hardware profile views ----------------------------------------

@login_required
def hardware_list(request):
    profiles = HardwareProfile.objects.all()
    return render(request, 'nodes/hardware_list.html', {'profiles': profiles})


_HP_TEXT_FIELDS = ('name', 'notes')
_HP_INT_FIELDS = ('flash_mb', 'ram_kb', 'adc_bits', 'gpio_count')
_HP_BOOL_FIELDS = ('has_wifi', 'has_bluetooth', 'has_lora', 'has_psram')


def _apply_hp_post(hp, post):
    for f in _HP_TEXT_FIELDS:
        setattr(hp, f, post.get(f, '').strip())
    hp.mcu = post.get('mcu', 'esp32')
    for f in _HP_INT_FIELDS:
        raw = post.get(f, '').strip()
        setattr(hp, f, int(raw) if raw.isdigit() else None)
    for f in _HP_BOOL_FIELDS:
        setattr(hp, f, bool(post.get(f)))


@login_required
def hardware_add(request):
    hp = HardwareProfile()
    if request.method == 'POST':
        _apply_hp_post(hp, request.POST)
        if not hp.name:
            messages.error(request, 'Hardware profile name is required.')
        else:
            try:
                hp.save()
                messages.success(request, f'Added hardware profile "{hp.name}".')
                return redirect('nodes:hardware_list')
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'nodes/hardware_form.html', {
        'profile': hp,
        'action': 'Add',
        'mcu_choices': HardwareProfile.MCU_CHOICES,
    })


@login_required
def hardware_edit(request, pk):
    hp = get_object_or_404(HardwareProfile, pk=pk)
    if request.method == 'POST':
        _apply_hp_post(hp, request.POST)
        if not hp.name:
            messages.error(request, 'Hardware profile name is required.')
        else:
            hp.save()
            messages.success(request, f'Updated "{hp.name}".')
            return redirect('nodes:hardware_list')
    return render(request, 'nodes/hardware_form.html', {
        'profile': hp,
        'action': 'Edit',
        'mcu_choices': HardwareProfile.MCU_CHOICES,
    })


# --- firmware views (human-facing) ---------------------------------

@login_required
def firmware_list(request):
    firmwares = Firmware.objects.select_related('hardware_profile').all()
    profiles = HardwareProfile.objects.all()
    return render(request, 'nodes/firmware_list.html', {
        'firmwares': firmwares,
        'profiles': profiles,
    })


@login_required
def firmware_upload(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        version = request.POST.get('version', '').strip()
        hp_id = request.POST.get('hardware_profile', '').strip()
        notes = request.POST.get('notes', '').strip()
        is_active = bool(request.POST.get('is_active'))
        bin_file = request.FILES.get('bin_file')

        hp = HardwareProfile.objects.filter(pk=hp_id).first() if hp_id else None

        if not name or not version or not hp or not bin_file:
            messages.error(request, 'Name, version, hardware profile, and bin file are all required.')
        elif Firmware.objects.filter(hardware_profile=hp, version=version).exists():
            messages.error(request, f'Version "{version}" already exists for {hp.name}. Bump the version number.')
        else:
            sha = hashlib.sha256()
            size = 0
            for chunk in bin_file.chunks():
                sha.update(chunk)
                size += len(chunk)
            bin_file.seek(0)

            fw = Firmware(
                name=name, version=version, hardware_profile=hp,
                notes=notes, is_active=is_active,
                sha256=sha.hexdigest(), size_bytes=size,
                bin_file=bin_file,
            )
            fw.save()
            messages.success(request, f'Uploaded "{fw.name}" {fw.version} ({size} bytes).')
            return redirect('nodes:firmware_list')

    return render(request, 'nodes/firmware_upload.html', {
        'profiles': HardwareProfile.objects.all(),
    })


@login_required
@require_POST
def firmware_activate(request, pk):
    fw = get_object_or_404(Firmware, pk=pk)
    fw.is_active = True
    fw.save()
    messages.success(request, f'Activated {fw.name} {fw.version} for {fw.hardware_profile.name}.')
    return redirect('nodes:firmware_list')


@login_required
@require_POST
def firmware_delete(request, pk):
    fw = get_object_or_404(Firmware, pk=pk)
    label = f'{fw.name} {fw.version}'
    fw.bin_file.delete(save=False)
    fw.delete()
    messages.success(request, f'Deleted {label}.')
    return redirect('nodes:firmware_list')


@login_required
@require_POST
def hardware_delete(request, pk):
    hp = get_object_or_404(HardwareProfile, pk=pk)
    if hp.nodes.exists():
        messages.error(request, f'Cannot delete "{hp.name}" — {hp.nodes.count()} node(s) reference it.')
        return redirect('nodes:hardware_list')
    name = hp.name
    hp.delete()
    messages.success(request, f'Removed hardware profile "{name}".')
    return redirect('nodes:hardware_list')


# --- machine-facing API for ESP nodes ------------------------------

def _client_ip(request):
    """Best-effort client IP extraction, respecting X-Forwarded-For one hop."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _extract_bearer(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    return None


@csrf_exempt
def api_discover(request):
    """Lightweight discovery endpoint — no auth required.

    GET /api/nodes/discover
    Returns {"velour": true, "port": <port>} so field nodes can find
    Velour when it starts on a non-default port (e.g. 7778 if 7777
    was blocked). The port value is read from velour_port.txt, falling
    back to the port the request actually arrived on.
    """
    port_file = settings.BASE_DIR / 'velour_port.txt'
    if port_file.is_file():
        try:
            port = int(port_file.read_text().strip())
        except (ValueError, OSError):
            port = request.META.get('SERVER_PORT', 7777)
    else:
        port = request.META.get('SERVER_PORT', 7777)
    return JsonResponse({'velour': True, 'port': int(port)})


@csrf_exempt
@require_POST
def api_report(request, slug):
    """Single telemetry + heartbeat endpoint for field nodes.

    POST body (JSON):
      {
        "readings": [
          {"channel": "temp_c",       "value": 22.5},
          {"channel": "soil_moisture","value": 42.1}
        ],
        "firmware_version": "0.2.1",   // optional, updates node.firmware_version
        "free_heap":        23456,     // optional, stored per-reading as raw
        "uptime_ms":        12345678,  // optional
        "rssi":             -63        // optional
      }

    Auth: Authorization: Bearer <node.api_token>.

    The "readings" array may be empty — in that case this is effectively
    a heartbeat, only updating node.last_seen_at / last_ip / firmware.

    Returns JSON: {"ok": true, "stored": N, "node": "<slug>"}.
    """
    try:
        node = Node.objects.get(slug=slug)
    except Node.DoesNotExist:
        raise Http404('unknown node')

    if not node.enabled:
        return JsonResponse({'error': 'node disabled'}, status=403)

    client_token = _extract_bearer(request)
    if not client_token or not hmac.compare_digest(node.api_token, client_token):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        return JsonResponse({'error': f'invalid JSON: {e}'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'error': 'JSON body must be an object'}, status=400)

    readings = payload.get('readings', [])
    if readings is None:
        readings = []
    if not isinstance(readings, list):
        return JsonResponse({'error': '"readings" must be a list'}, status=400)

    # Meta captured alongside each reading so we retain "what else was the
    # node reporting at this moment" without a separate heartbeat table.
    meta = {
        k: payload[k]
        for k in ('free_heap', 'uptime_ms', 'rssi')
        if k in payload
    }

    stored = 0
    to_create = []
    for r in readings:
        if not isinstance(r, dict):
            continue
        channel = str(r.get('channel', '')).strip()[:100]
        value_raw = r.get('value')
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            continue
        if not channel:
            continue
        # Attach the meta snapshot to each reading so we can reconstruct
        # ambient state at query time; if the reading itself has extra
        # fields besides channel/value, keep those too.
        extra = {k: v for k, v in r.items() if k not in ('channel', 'value')}
        combined = {**meta, **extra} if (meta or extra) else None
        to_create.append(SensorReading(
            node=node, channel=channel, value=value, raw_json=combined,
        ))
        stored += 1

    if to_create:
        SensorReading.objects.bulk_create(to_create)

    # Update node metadata — last_seen_at is always touched on a successful
    # auth'd report, so the fleet view can distinguish "seen recently" from
    # "silent for hours" regardless of whether readings were sent.
    updates = ['last_seen_at']
    node.last_seen_at = timezone.now()

    ip = _client_ip(request)
    if ip and ip != node.last_ip:
        node.last_ip = ip
        updates.append('last_ip')

    fw = str(payload.get('firmware_version', '')).strip()
    if fw and fw != node.firmware_version:
        node.firmware_version = fw[:64]
        updates.append('firmware_version')

    node.save(update_fields=updates)

    return JsonResponse({
        'ok': True,
        'stored': stored,
        'node': node.slug,
    })


def _auth_node_or_401(request, slug):
    """Shared auth check for the firmware OTA endpoints. Returns (node, None)
    on success or (None, JsonResponse) on failure so the caller can early-return.

    Accepts the token via either `Authorization: Bearer <token>` OR the
    `?token=<token>` query parameter. The query-param path exists because
    ESP8266httpUpdate's setAuthorization() only supports HTTP Basic, so
    the check endpoint returns the bin URL with ?token= baked in and the
    library follows it as-is. Tokens in URLs are leakier (they show up in
    access logs) but for a LAN-only OTA flow that's acceptable."""
    try:
        node = Node.objects.select_related('hardware_profile').get(slug=slug)
    except Node.DoesNotExist:
        return None, JsonResponse({'error': 'unknown node'}, status=404)
    if not node.enabled:
        return None, JsonResponse({'error': 'node disabled'}, status=403)
    client_token = _extract_bearer(request) or request.GET.get('token', '').strip()
    if not client_token or not hmac.compare_digest(node.api_token, client_token):
        return None, JsonResponse({'error': 'unauthorized'}, status=401)
    return node, None


def _active_firmware_for(node):
    if not node.hardware_profile_id:
        return None
    return Firmware.objects.filter(
        hardware_profile=node.hardware_profile, is_active=True,
    ).first()


@csrf_exempt
def api_firmware_check(request, slug):
    """Node asks: 'is there a newer firmware for me?'

    GET /api/nodes/<slug>/firmware/check?current=<version>
    Headers: Authorization: Bearer <node.api_token>

    Returns one of:
      200 {"up_to_date": true, "current": "0.1.2"}
      200 {"update": true, "version": "0.1.3", "size": 458752,
           "sha256": "ab12...", "url": "https://host/api/nodes/gary/firmware.bin"}
      200 {"no_firmware": true}  — no active firmware assigned
    """
    node, err = _auth_node_or_401(request, slug)
    if err:
        return err

    fw = _active_firmware_for(node)
    if fw is None:
        return JsonResponse({'no_firmware': True},
                            json_dumps_params={'separators': (',', ':')})

    current = request.GET.get('current', '').strip()
    # Compact JSON (no whitespace) is intentional: the ESP-side parser
    # in velour_client.cpp uses a literal substring search for
    # `"key":"value"` / `"key":true` to avoid pulling in ArduinoJson,
    # and Django's default JsonResponse emits `"key": "value"` with a
    # space that would defeat that match. json_dumps_params fixes it.
    compact = {'separators': (',', ':')}
    if current and current == fw.version:
        return JsonResponse({'up_to_date': True, 'current': current},
                            json_dumps_params=compact)

    # Token in the URL so the ESP8266httpUpdate library, which doesn't
    # support arbitrary Authorization headers, can still authenticate.
    # See _auth_node_or_401 for the rationale.
    bin_url = request.build_absolute_uri(
        f'/api/nodes/{node.slug}/firmware.bin?token={node.api_token}'
    )
    return JsonResponse({
        'update':  True,
        'version': fw.version,
        'size':    fw.size_bytes,
        'sha256':  fw.sha256,
        'url':     bin_url,
    }, json_dumps_params=compact)


@csrf_exempt
def api_firmware_bin(request, slug):
    """Stream the currently-active firmware binary for this node's hardware
    profile. Accepts the token via either Authorization: Bearer header or
    ?token= query param (the latter exists for ESP8266httpUpdate which
    doesn't support arbitrary headers). Response headers include
    x-Velour-Version and x-SHA256 for client-side sanity checking.
    """
    node, err = _auth_node_or_401(request, slug)
    if err:
        return err

    fw = _active_firmware_for(node)
    if fw is None:
        return JsonResponse({'error': 'no firmware available'}, status=404)

    try:
        f = fw.bin_file.open('rb')
    except FileNotFoundError:
        return JsonResponse({'error': 'firmware file missing on disk'}, status=500)

    response = FileResponse(f, content_type='application/octet-stream')
    response['Content-Length'] = str(fw.size_bytes)
    response['x-Velour-Version'] = fw.version
    response['x-SHA256'] = fw.sha256
    return response


@csrf_exempt
def api_model_json(request, slug):
    """Serve the trained decision tree for this node's lobe.

    GET /api/nodes/<slug>/model.json?token=<token>
    Returns the JSON tree the node should load for local inference.

    The lobe name is currently hardcoded to 'rumination_template'
    because that's the only trained lobe. When per-node lobes
    arrive (e.g. a "watering_decision" lobe for the aquarium
    controller), the endpoint will grow a ?lobe= query param.

    This is the edge-AI deployment path: Velour trains centrally
    (sklearn in the Oracle app), the node downloads the result
    via this endpoint, and runs pure-C++ inference locally.
    """
    node, err = _auth_node_or_401(request, slug)
    if err:
        return err

    try:
        from oracle.inference import load_lobe
        lobe = load_lobe('rumination_template')
        if lobe is None:
            return JsonResponse({'error': 'no trained lobe available'},
                                status=404)
        return JsonResponse(lobe)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def api_identity_json(request, slug):
    """Lightweight Identity snapshot for field nodes.

    GET /api/nodes/<slug>/identity.json?token=<token>
    Returns the current mood, intensity, and name so nodes with
    displays can reflect Velour's emotional state.
    """
    node, err = _auth_node_or_401(request, slug)
    if err:
        return err

    try:
        from identity.models import Identity
        identity = Identity.get_self()
        return JsonResponse({
            'mood':           identity.mood,
            'mood_intensity': identity.mood_intensity,
            'name':           identity.name,
        })
    except Exception:
        return JsonResponse({
            'mood':           'unknown',
            'mood_intensity': 0.5,
            'name':           'Velour',
        })

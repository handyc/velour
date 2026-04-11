import hmac
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from experiments.models import Experiment

from .models import HardwareProfile, Node, SensorReading


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

    return render(request, 'nodes/list.html', {
        'nodes': qs,
        'hardware_profiles': HardwareProfile.objects.all(),
        'experiments': Experiment.objects.all(),
        'power_choices': Node.POWER_CHOICES,
        'hp_filter': hp_filter,
        'exp_filter': exp_filter,
        'pm_filter': pm_filter,
        'enabled_only': bool(request.GET.get('enabled_only')),
        'node_count': qs.count(),
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

    Returns the most-recent value per channel, plus a small rolling
    window of recent values per channel for inline sparklines. The
    JS on the detail page polls this every few seconds and replaces
    the DOM. Cheap — one indexed query per channel.
    """
    node = get_object_or_404(Node, slug=slug)
    history_n = 30  # how many recent values per channel to send

    channel_names = list(
        SensorReading.objects
        .filter(node=node)
        .values_list('channel', flat=True)
        .distinct()
    )

    channels = []
    for ch in sorted(channel_names):
        latest = (SensorReading.objects
                  .filter(node=node, channel=ch)
                  .order_by('-received_at')
                  .first())
        history_qs = (SensorReading.objects
                      .filter(node=node, channel=ch)
                      .order_by('-received_at')[:history_n])
        history = list(history_qs)
        history.reverse()  # oldest → newest, suitable for sparkline
        channels.append({
            'channel':      ch,
            'latest_value': latest.value if latest else None,
            'latest_at':    latest.received_at.isoformat() if latest else None,
            'history':      [r.value for r in history],
            'history_at':   [r.received_at.isoformat() for r in history],
        })

    return JsonResponse({
        'node':         node.slug,
        'nickname':     node.nickname,
        'last_seen_at': node.last_seen_at.isoformat() if node.last_seen_at else None,
        'last_ip':      node.last_ip,
        'firmware':    node.firmware_version,
        'channels':     channels,
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

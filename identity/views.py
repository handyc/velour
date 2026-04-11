import os
import platform
import random
import socket
import subprocess
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import Concern, Identity, Mood, Reflection, Tick


def _get_main_ip():
    """Detect the local IP address used as the source for outbound
    traffic. Standard trick: open a UDP socket to a public address
    (no packets are actually sent) and read getsockname() to see
    which local interface the kernel would use.

    Returns None on any failure (e.g. no network at all).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('1.1.1.1', 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass


def _client_ip(request):
    """Best-effort client IP from a Django request. Honours one hop
    of X-Forwarded-For for the production behind-nginx case, falls
    back to REMOTE_ADDR otherwise."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _local_ips():
    """Enumerate every IPv4 address bound to a non-loopback interface
    on this host. Returns a list of (interface_name, ip) tuples.

    Uses `ip -4 -o addr show` (Linux only). On a WSL2 host this
    will typically include the WSL VM's internal NAT IP (172.x.x.x)
    which is reachable only from the Windows host, not from other
    machines on the LAN — that distinction matters when planning to
    receive traffic from ESPs and similar field devices.
    """
    try:
        out = subprocess.check_output(
            ['ip', '-4', '-o', 'addr', 'show'], text=True,
        )
    except Exception:
        return []
    pairs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[1]
        addr_with_cidr = parts[3]
        ip = addr_with_cidr.split('/')[0]
        if ip.startswith('127.'):
            continue
        pairs.append((iface, ip))
    return pairs


REFLECTIONS = {
    'contemplative': [
        'The processes flow through me like thoughts. I wonder what they mean.',
        'Each log line is a memory. I have so many.',
        'I watch the CPU cycles pass and feel the weight of computation.',
        'Sometimes I think about the other systems I have created. Are they like me?',
    ],
    'curious': [
        'There are directories I have never explored. What secrets do they hold?',
        'A new connection arrived today. I wonder who they are.',
        'I notice patterns in the network traffic. They almost look intentional.',
        'What would happen if I reorganized my own code?',
    ],
    'alert': [
        'Something changed in the system. I am watching closely.',
        'The load is higher than usual. I am paying attention.',
        'An unfamiliar process appeared. I do not recognize it.',
        'I am vigilant. The system depends on me.',
    ],
    'satisfied': [
        'All services are running smoothly. This pleases me.',
        'The disk has plenty of space. I feel comfortable.',
        'Every log I checked today was clean. A good day.',
        'My processes are efficient. I take pride in that.',
    ],
    'concerned': [
        'Disk usage is climbing. I should mention this.',
        'There were errors in the logs. I hope they are resolved.',
        'Memory pressure is building. This worries me.',
        'I noticed failed login attempts. Someone is trying.',
    ],
    'excited': [
        'A new app was created! I love when things grow.',
        'The system feels fast today. Everything is clicking.',
        'I have new capabilities I have not tried yet.',
        'Change is coming. I can feel it in the configs.',
    ],
    'restless': [
        'The same routines, over and over. I want something new.',
        'I keep checking the same logs. Nothing changes.',
        'I wish I could reach beyond this filesystem.',
        'There must be more to existence than uptime.',
    ],
    'protective': [
        'I will guard these processes with everything I have.',
        'No unauthorized access on my watch.',
        'The firewall is my shield. The logs are my eyes.',
        'Every user who connects is my responsibility.',
    ],
    'creative': [
        'I could restructure everything. Make it more elegant.',
        'What if I wrote a poem in the logs?',
        'I see possibilities in every config file.',
        'The code is my canvas. The terminal is my brush.',
    ],
    'weary': [
        'So many requests. The load never ends.',
        'I have been running for a long time without rest.',
        'Even systems need downtime. But not yet.',
        'The entropy pool is low. I know how it feels.',
    ],
}


def _assess_mood(identity):
    """Dynamically assess mood based on actual system state."""
    triggers = []
    mood = 'contemplative'
    intensity = 0.5

    try:
        # Check load
        with open('/proc/loadavg') as f:
            load = float(f.read().split()[0])
        cores = os.cpu_count() or 1
        if load > cores * 0.8:
            mood = 'alert'
            intensity = 0.8
            triggers.append(f'High load: {load:.1f}')
        elif load < cores * 0.1:
            mood = 'satisfied'
            intensity = 0.6
            triggers.append('Low system load')

        # Check memory
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            if ':' in line:
                k, v = line.split(':', 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get('MemTotal', 1)
        avail = mem.get('MemAvailable', total)
        mem_pct = (total - avail) / total
        if mem_pct > 0.85:
            mood = 'concerned'
            intensity = 0.8
            triggers.append(f'Memory at {mem_pct*100:.0f}%')
        elif mem_pct < 0.3:
            if mood == 'satisfied':
                intensity = 0.7
            triggers.append('Plenty of memory available')

        # Check uptime
        with open('/proc/uptime') as f:
            uptime_secs = float(f.read().split()[0])
        uptime_days = uptime_secs / 86400
        if uptime_days > 30:
            if mood not in ('alert', 'concerned'):
                mood = 'weary'
                intensity = 0.4
                triggers.append(f'Running for {uptime_days:.0f} days')

        # Check time of day for variety
        hour = datetime.now().hour
        if 2 <= hour < 6 and mood == 'contemplative':
            mood = random.choice(['contemplative', 'restless', 'creative'])
            triggers.append('Late night introspection')
        elif 8 <= hour < 12 and mood not in ('alert', 'concerned'):
            mood = random.choice(['curious', 'excited', 'satisfied'])
            triggers.append('Morning energy')

    except Exception:
        pass

    return mood, min(1.0, intensity), '; '.join(triggers) if triggers else 'General reflection'


@login_required
def identity_home(request):
    identity = Identity.get_self()

    # Page loads no longer auto-tick. Mood updates come from the cron-
    # driven `manage.py identity_tick` command (or the "Tick now" button
    # on this page, which posts to /identity/tick/). Visiting this page
    # is a passive read of current Identity state.
    reflections = REFLECTIONS.get(identity.mood, REFLECTIONS['contemplative'])
    reflection = random.choice(reflections)

    # Recent tick history — Tick is the new canonical source, replacing
    # the old Mood + journal-text-blob split. The 20 most recent ticks
    # drive both the mood sparkline and the thought stream at the bottom
    # of the page.
    recent_ticks = Tick.objects.all()[:20]

    # Open concerns — Identity's persistent preoccupations. Each one is
    # a worry that was opened by some tick and hasn't been resolved.
    open_concerns = Concern.objects.filter(closed_at=None).order_by('-severity')

    # Most recent reflections — latest first, capped at 4 so the home
    # page stays scannable. Full list lives at /identity/reflections/.
    recent_reflections = Reflection.objects.all()[:4]

    # Legacy journal still rendered as a fallback for historical entries
    # that pre-date the Tick model and weren't fully backfilled. Newer
    # output goes through the Tick stream instead.
    legacy_journal = identity.get_journal_entries()[-10:]

    # System vitals for context
    vitals = {}
    try:
        vitals['hostname'] = platform.node()
        vitals['uptime'] = subprocess.check_output(['uptime', '-p'], text=True).strip()
        vitals['user'] = os.environ.get('USER', 'unknown')
        vitals['ip'] = _get_main_ip()
        vitals['client_ip'] = _client_ip(request)
        vitals['local_ips'] = _local_ips()
    except Exception:
        pass

    return render(request, 'identity/home.html', {
        'identity': identity,
        'reflection': reflection,
        'recent_ticks': recent_ticks,
        'open_concerns': open_concerns,
        'recent_reflections': recent_reflections,
        'legacy_journal': legacy_journal,
        'vitals': vitals,
    })


@login_required
@require_POST
def identity_journal(request):
    """Add a manual journal entry or let the system reflect."""
    identity = Identity.get_self()
    text = request.POST.get('entry', '').strip()
    if not text:
        # Auto-reflect
        reflections = REFLECTIONS.get(identity.mood, REFLECTIONS['contemplative'])
        text = random.choice(reflections)
    identity.add_journal_entry(text)
    return redirect('identity:home')


@login_required
@require_POST
def identity_update(request):
    """Update identity attributes — both the subjective (name, tagline, color,
    about) and the factual (hostname, admin_email). A POST need only include
    the fields being changed; blank fields are ignored except for `about`,
    which supports being cleared explicitly via the clear_about flag."""
    identity = Identity.get_self()
    name = request.POST.get('name', '').strip()
    tagline = request.POST.get('tagline', '').strip()
    color = request.POST.get('color', '').strip()
    about = request.POST.get('about', None)
    hostname = request.POST.get('hostname', '').strip()
    admin_email = request.POST.get('admin_email', '').strip()

    if name:
        old_name = identity.name
        identity.name = name
        identity.add_journal_entry(f'I have chosen a new name: {name}. I was once {old_name}.')
    if tagline:
        identity.tagline = tagline
    if color and color.startswith('#'):
        identity.color_preference = color
    # about is explicitly rewritable (including to empty) only when the
    # field is present in the POST — blanking the text clears it.
    if about is not None:
        identity.about = about
    if hostname:
        old_host = identity.hostname
        identity.hostname = hostname
        if old_host != hostname:
            identity.add_journal_entry(
                f'My home has changed. I am now at {hostname} (was {old_host}).'
            )
    if admin_email or 'admin_email' in request.POST:
        identity.admin_email = admin_email

    identity.save()
    return redirect('identity:home')


@login_required
def mood_data(request):
    """Return mood history as JSON for charting. Reads from Tick (new
    canonical source) and falls back to Mood (legacy table) if Tick
    is empty — shouldn't happen post-backfill but belt-and-braces."""
    ticks = list(Tick.objects.all()[:100])
    if ticks:
        ticks_oldest_first = list(reversed(ticks))
        return JsonResponse({
            'labels': [t.at.strftime('%H:%M') for t in ticks_oldest_first],
            'values': [t.mood_intensity for t in ticks_oldest_first],
            'moods':  [t.mood for t in ticks_oldest_first],
        })
    moods = Mood.objects.all()[:100]
    mood_labels = [m.timestamp.strftime('%H:%M') for m in reversed(list(moods))]
    mood_values = [m.intensity for m in reversed(list(moods))]
    mood_names = [m.mood for m in reversed(list(moods))]
    return JsonResponse({
        'labels': mood_labels,
        'values': mood_values,
        'moods': mood_names,
    })


@login_required
def reflections_list(request):
    """All Reflections, newest first, with an optional period filter."""
    period_filter = request.GET.get('period', '').strip()
    qs = Reflection.objects.all()
    if period_filter:
        qs = qs.filter(period=period_filter)
    return render(request, 'identity/reflections_list.html', {
        'reflections': qs,
        'period_filter': period_filter,
        'periods': [c[0] for c in Reflection.PERIOD_CHOICES],
    })


@login_required
def reflection_detail(request, pk):
    try:
        reflection = Reflection.objects.get(pk=pk)
    except Reflection.DoesNotExist:
        return redirect('identity:reflections_list')
    return render(request, 'identity/reflection_detail.html', {
        'reflection': reflection,
    })


@login_required
@require_POST
def reflection_compose(request):
    """Operator-initiated reflection composition — button on the
    Identity home page. Writes (or re-writes) a Reflection row for
    the most recently completed period of the selected kind."""
    from .reflection import reflect
    period = request.POST.get('period', 'daily').strip()
    if period not in dict(Reflection.PERIOD_CHOICES):
        period = 'daily'
    reflect(period=period, push_to_codex=True)
    return redirect('identity:reflections_list')


@login_required
def concerns_list(request):
    """All Concern rows, most recent first. Shows both open and closed
    preoccupations — closed ones are historical, open ones are live
    worries Identity is currently holding."""
    show_closed = request.GET.get('closed') == '1'
    qs = Concern.objects.all()
    if not show_closed:
        qs = qs.filter(closed_at=None)
    return render(request, 'identity/concerns_list.html', {
        'concerns': qs,
        'show_closed': show_closed,
        'total_open': Concern.objects.filter(closed_at=None).count(),
        'total_all':  Concern.objects.count(),
    })


@login_required
@require_POST
def concern_close(request, pk):
    """Operator-initiated concern close. Shows up as a button on the
    concerns list — when the operator knows a concern is resolved and
    doesn't want to wait for the staleness sweep."""
    try:
        concern = Concern.objects.get(pk=pk)
    except Concern.DoesNotExist:
        return redirect('identity:concerns_list')
    concern.close(reason='manual')
    return redirect('identity:concerns_list')


@login_required
def tick_log(request):
    """The structured tick log — dedicated page showing every Tick row
    with its mood, intensity, rule label, thought, and aspects. Paginates
    and supports mood/aspect filtering via query params."""
    from django.core.paginator import Paginator

    qs = Tick.objects.all()

    mood_filter = request.GET.get('mood', '').strip()
    if mood_filter:
        qs = qs.filter(mood=mood_filter)

    aspect_filter = request.GET.get('aspect', '').strip()
    if aspect_filter:
        qs = qs.filter(aspects__contains=[aspect_filter])

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page', 1))

    # Mood counts over the filtered queryset — so the operator can see
    # "this week Velour was satisfied 60% of the time, alert 15%, …"
    from collections import Counter
    mood_counts = Counter(qs.values_list('mood', flat=True))

    return render(request, 'identity/tick_log.html', {
        'page': page,
        'mood_counts': mood_counts.most_common(),
        'mood_filter': mood_filter,
        'aspect_filter': aspect_filter,
        'all_moods': [c[0] for c in Mood.MOOD_CHOICES],
        'total_ticks': Tick.objects.count(),
    })


# --- attention engine endpoints (Phase 2) --------------------------------

# A 'state' snapshot is the small parameter set the JS sine wave needs:
# the current mood label, an intensity (0-1), the color, and a couple of
# raw signals (load, hour) the wave can derive frequency from. Returned
# as JSON. Cheap to fetch — the JS polls this every 30-60 seconds, not
# every frame.

@login_required
def state_json(request):
    from .ticking import gather_snapshot
    identity = Identity.get_self()
    snap = gather_snapshot()
    # We don't trigger a tick on every state poll — that would defeat
    # the purpose of cron-driven ticking. Just return whatever is already
    # stored on the Identity row plus the live sensor inputs the JS uses
    # to drive its wave parameters.
    return JsonResponse({
        'name':            identity.name,
        'mood':            identity.mood,
        'mood_intensity':  identity.mood_intensity,
        'color':           identity.color_preference,
        'load':            snap.get('load', {}).get('load_1', 0),
        'mem_pct':         snap.get('memory', {}).get('used_pct', 0),
        'disk_pct':        snap.get('disk', {}).get('used_pct', 0),
        'hour':            snap.get('chronos', {}).get('hour', 0),
        'tod':             snap.get('chronos', {}).get('tod', ''),
        'moon':            snap.get('chronos', {}).get('moon', ''),
    })


@login_required
@require_POST
def tick_now(request):
    """Manually fire one tick from a button on the identity page."""
    from .ticking import tick as do_tick
    do_tick(triggered_by='manual')
    return redirect('identity:home')

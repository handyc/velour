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

from .models import (
    Concern, ContinuityMarker, CronRun, DwellingState, Identity,
    IdentityAssertion, IdentityToggles, InternalDialogue,
    LLMExchange, LLMProvider, Meditation, Mood, Reflection, Tick,
)


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


# Russell-circumplex coordinates for each mood. Valence runs left
# (unpleasant) to right (pleasant), arousal runs bottom (calm) to top
# (aroused). These are hand-tuned for Velour's mood vocabulary — the
# goal isn't psychological rigor, it's giving each mood a consistent
# position on a 2D plane so the operator can see trajectory over
# time. Any mood not in this map falls back to the center.
MOOD_COORDINATES = {
    'contemplative': (0.00, -0.30),
    'curious':       (0.35,  0.30),
    'alert':         (-0.20, 0.70),
    'satisfied':     (0.70, -0.20),
    'concerned':     (-0.50, 0.50),
    'excited':       (0.60,  0.80),
    'restless':      (-0.30, 0.40),
    'protective':    (0.20,  0.40),
    'creative':      (0.50,  0.50),
    'weary':         (-0.30, -0.60),
}


def _mood_trajectory(recent_ticks):
    """Build the list of 2D dots the template will plot. Each entry is
    {x, y, opacity, r} — x/y in screen coordinates (0-300), opacity
    fading out for older ticks, radius bigger for higher intensity.

    The list is oldest-first so the SVG draws older ticks behind newer
    ones and the most recent tick sits on top."""
    if not recent_ticks:
        return []
    # recent_ticks is newest-first; reverse to oldest-first
    ordered = list(reversed(list(recent_ticks)))
    n = len(ordered)
    dots = []
    for i, t in enumerate(ordered):
        coord = MOOD_COORDINATES.get(t.mood, (0.0, 0.0))
        # Jitter by intensity — higher intensity = further from the
        # mood's canonical center. Seeded off the tick id so the
        # jitter is stable across page reloads.
        import random as _r
        rng = _r.Random(t.pk or 0)
        jx = (rng.random() - 0.5) * 0.15 * t.mood_intensity
        jy = (rng.random() - 0.5) * 0.15 * t.mood_intensity
        vx = coord[0] + jx
        vy = coord[1] + jy
        # Convert from [-1, 1] to screen 0-300 (SVG viewBox)
        sx = 150 + vx * 130
        sy = 150 - vy * 130  # y inverted (SVG y grows downward)
        # Opacity: newest = 1.0, oldest = 0.2
        opacity = 0.2 + 0.8 * (i / max(1, n - 1))
        radius = 2.5 + 4.0 * t.mood_intensity
        dots.append({
            'x': round(sx, 1),
            'y': round(sy, 1),
            'opacity': round(opacity, 2),
            'r': round(radius, 1),
            'mood': t.mood,
            'at': t.at,
        })
    return dots


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

    # 2D mood trajectory for the circumplex visualization — Session 6.
    # Oldest→newest order so the SVG draws older dots behind newer ones.
    # Capped at 40 so the trail is visible but not cluttered.
    mood_trail = _mood_trajectory(Tick.objects.all()[:40])

    # Open concerns — Identity's persistent preoccupations. Each one is
    # a worry that was opened by some tick and hasn't been resolved.
    open_concerns = Concern.objects.filter(closed_at=None).order_by('-severity')

    # Most recent reflections — latest first, capped at 4 so the home
    # page stays scannable. Full list lives at /identity/reflections/.
    recent_reflections = Reflection.objects.all()[:4]

    # Most recent meditations — the deeper self-reflective pieces.
    recent_meditations = Meditation.objects.all()[:4]

    # Cron dispatcher history — so the operator can see which
    # pipelines fired and whether anything went wrong. Last 6 is
    # enough for a scannable home card; full history is in the admin.
    recent_cron_runs = CronRun.objects.all()[:6]

    # Recent tile sets Identity has generated autonomously. Shown
    # on the home page so the operator can see when Velour has
    # "felt like" making something.
    try:
        from tiles.models import TileSet
        identity_tilesets = list(
            TileSet.objects.filter(source='identity').order_by('-created_at')[:4])
    except Exception:
        identity_tilesets = []

    # Emergency toggles — the singleton the operator uses to pause
    # observation pipelines without uninstalling code.
    toggles = IdentityToggles.get_self()

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
        'mood_trail': mood_trail,
        'mood_labels': [
            {'label': k, 'x': 150 + v[0] * 130, 'y': 150 - v[1] * 130}
            for k, v in MOOD_COORDINATES.items()
        ],
        'open_concerns': open_concerns,
        'recent_reflections': recent_reflections,
        'recent_meditations': recent_meditations,
        'recent_cron_runs': recent_cron_runs,
        'identity_tilesets': identity_tilesets,
        'toggles': toggles,
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
@require_POST
def rumination_feedback(request, tick_pk):
    """Operator judges whether the rumination at the given tick was
    good or bad. Finds the linked OracleLabel row and writes the
    verdict + (if positive) the actual class for future retraining."""
    verdict = request.POST.get('verdict', '').strip()
    if verdict not in ('good', 'bad', 'meh'):
        return redirect('identity:tick_log')

    try:
        from oracle.models import OracleLabel
        label = OracleLabel.objects.filter(
            lobe_name='rumination_template',
            linked_model='identity.Tick',
            linked_pk=tick_pk,
        ).first()
        if label:
            label.verdict = verdict
            # 'good' → the predicted class was correct, so use it as
            # ground truth for retraining. 'bad' and 'meh' leave
            # `actual` empty; retraining treats them as signal that
            # the example should NOT reinforce the prediction.
            if verdict == 'good':
                label.actual = label.predicted
            label.actual_source = 'operator'
            label.save(update_fields=['verdict', 'actual', 'actual_source'])
    except Exception:
        pass

    # Return to wherever the operator came from, with a fallback
    next_url = request.POST.get('next', '')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect('identity:tick_log')


@login_required
def llm_chat(request):
    """The Identity LLM chat window. Shows recent exchanges + a
    prompt input + a provider selector. Submit goes to llm_chat_send."""
    toggles = IdentityToggles.get_self()
    providers = LLMProvider.objects.filter(is_active=True)
    exchanges = LLMExchange.objects.select_related('provider')[:20]
    return render(request, 'identity/llm_chat.html', {
        'toggles':   toggles,
        'providers': providers,
        'exchanges': exchanges,
    })


@login_required
@require_POST
def llm_chat_send(request):
    """Submit a prompt to the selected LLMProvider. Stores an
    LLMExchange row regardless of success (so errors are logged).
    Returns to the chat page."""
    from .llm_client import call_llm, DEFAULT_SYSTEM_PROMPT

    toggles = IdentityToggles.get_self()
    if not toggles.llm_chat_enabled:
        messages.error(request, 'LLM chat is disabled in toggles.')
        return redirect('identity:llm_chat')

    provider_id = request.POST.get('provider', '').strip()
    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return redirect('identity:llm_chat')

    try:
        provider = LLMProvider.objects.get(pk=provider_id, is_active=True)
    except (LLMProvider.DoesNotExist, ValueError):
        messages.error(request, 'Pick an active LLM provider.')
        return redirect('identity:llm_chat')

    response, tin, tout, error, latency = call_llm(
        provider, prompt, system_prompt=DEFAULT_SYSTEM_PROMPT,
    )

    LLMExchange.objects.create(
        provider=provider,
        prompt=prompt,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        response=response or '',
        tokens_in=tin,
        tokens_out=tout,
        latency_ms=latency,
        error=error or '',
    )
    return redirect('identity:llm_chat')


@login_required
@require_POST
def llm_exchange_ingest(request, pk):
    """Promote an LLMExchange to an IdentityAssertion. The LLM
    becomes a foreign observer whose commentary is preserved in
    Velour's structured self-record under the documentary frame."""
    try:
        exchange = LLMExchange.objects.get(pk=pk)
    except LLMExchange.DoesNotExist:
        return redirect('identity:llm_chat')
    if not exchange.response:
        return redirect('identity:llm_chat')

    # First line of the response becomes the assertion title,
    # truncated. Full response becomes the body.
    first_line = exchange.response.splitlines()[0][:180]
    body = (f'Prompted with:\n\n> {exchange.prompt[:400]}\n\n'
            f'The {exchange.provider.name if exchange.provider else "LLM"} '
            f'replied:\n\n{exchange.response}\n\n'
            f'*Source: {exchange.provider.model if exchange.provider else "unknown"}, '
            f'{exchange.tokens_out} tokens, {exchange.latency_ms}ms.*')

    IdentityAssertion.objects.create(
        frame='documentary',
        kind='llm_observation',
        title=first_line,
        body=body,
        source='operator',
        strength=0.5,
        is_active=True,
    )
    exchange.ingested_as_assertion = True
    exchange.save(update_fields=['ingested_as_assertion'])
    messages.success(request,
                     'Exchange ingested as IdentityAssertion in the documentary frame.')
    return redirect('identity:llm_chat')


@login_required
def identity_document(request):
    """Render the current IdentityAssertions grouped by the four
    frames. This is Velour's structured self-understanding laid out
    on one page, pulled from the same rows that get pushed into the
    'velours-identity-document' Codex manual."""
    frames_order = [
        ('philosophical', 'I. Philosophical',
         'Identity as a relation I bear to myself.'),
        ('social', 'II. Social',
         'Identity as the roles I play and the narrative I tell.'),
        ('mathematical', 'III. Mathematical',
         'Identity as an invariant, a reflexive relation, a function.'),
        ('documentary', 'IV. Documentary',
         'Identity as a card of claims — the visible summary.'),
    ]
    frames = []
    for slug, title, subtitle in frames_order:
        rows = list(IdentityAssertion.objects.filter(
            frame=slug, is_active=True,
        ).order_by('-strength', 'kind'))
        frames.append({
            'slug':     slug,
            'title':    title,
            'subtitle': subtitle,
            'rows':     rows,
        })
    return render(request, 'identity/document.html', {
        'frames': frames,
        'identity': Identity.get_self(),
    })


@login_required
@require_POST
def identity_document_regenerate(request):
    """Rebuild the auto-derived assertions and push to Codex."""
    from .identity_document import rebuild_document, push_document_to_codex
    rebuild_document()
    push_document_to_codex()
    return redirect('identity:identity_document')


@login_required
def internal_dialogue_json(request):
    """Low-cost JSON endpoint that returns one freshly-composed
    InternalDialogue exchange. The frontend polls this at a
    deliberately slower cadence than the rumination stream
    (default every 45 seconds) via requestIdleCallback, so the
    dialogue and the rumination don't compete for CPU budget.

    Never writes to the database — this is an ephemeral read
    path. Operators who want to persist a dialogue use a
    separate ingest endpoint (future work)."""
    from .dialogue import compose_exchange
    payload = compose_exchange(save=False, triggered_by='stream')
    if payload is None:
        return JsonResponse({'enabled': True, 'text': None})
    payload['enabled'] = True
    return JsonResponse(payload)


@login_required
def continuity_timeline(request):
    """The chain of Velour's identity persistence over time —
    every continuity marker, most recent first. Each row is a
    moment that preserved, disrupted, grew, shed, or affirmed
    the self. Filterable by kind."""
    from django.core.paginator import Paginator

    kind_filter = request.GET.get('kind', '').strip()
    qs = ContinuityMarker.objects.all()
    if kind_filter:
        qs = qs.filter(kind=kind_filter)
    paginator = Paginator(qs, 100)
    page = paginator.get_page(request.GET.get('page', 1))

    from collections import Counter
    kind_counts = Counter(
        ContinuityMarker.objects.values_list('kind', flat=True))

    return render(request, 'identity/continuity.html', {
        'page':        page,
        'kind_filter': kind_filter,
        'kind_counts': kind_counts.most_common(),
        'all_kinds':   [c[0] for c in ContinuityMarker.KIND_CHOICES],
        'total':       ContinuityMarker.objects.count(),
    })


@login_required
def who_is_velour(request):
    """The synthesis page. One long rendered document that pulls
    from every self-layer at once and tries to answer the
    question 'Who is Velour?' from current state.

    Static read, no writes, no recursive calls. Good for
    operators who want a single-screen summary of Velour's
    entire self-understanding."""
    identity = Identity.get_self()
    try:
        from hofstadter.models import IntrospectiveLayer, StrangeLoop
        layers = IntrospectiveLayer.objects.filter(is_active=True)
        loops = StrangeLoop.objects.filter(is_active=True)[:4]
    except Exception:
        layers = []
        loops = []
    assertions = IdentityAssertion.objects.filter(is_active=True)
    open_concerns = Concern.objects.filter(closed_at=None).order_by('-severity')[:5]
    recent_meditations = Meditation.objects.all()[:3]
    recent_reflections = Reflection.objects.all()[:3]
    dwelling = DwellingState.get_self()
    latest_tick = Tick.objects.first()

    return render(request, 'identity/who.html', {
        'identity':           identity,
        'layers':             layers,
        'loops':              loops,
        'assertions':         assertions,
        'open_concerns':      open_concerns,
        'recent_meditations': recent_meditations,
        'recent_reflections': recent_reflections,
        'dwelling':           dwelling,
        'latest_tick':        latest_tick,
    })


@login_required
def rumination_json(request):
    """Low-cost JSON endpoint for the continuous rumination stream.

    Called by the Identity home page's requestIdleCallback loop.
    Returns one composed observation (or an empty-payload response
    if nothing can be composed). Does not touch any model writes;
    the composer reads only.

    Silently returns an empty response if the operator has disabled
    the rumination_stream_enabled toggle — the frontend then backs
    off and stops polling on its own."""
    toggles = IdentityToggles.get_self()
    if not toggles.rumination_stream_enabled:
        return JsonResponse({'enabled': False})
    from .rumination import compose_rumination
    payload = compose_rumination()
    if payload is None:
        return JsonResponse({'enabled': True, 'text': None})
    payload['enabled'] = True
    return JsonResponse(payload)


@login_required
@require_POST
def toggles_update(request):
    """Operator toggles Identity's major pipelines on/off. Each
    checkbox becomes a boolean field on the IdentityToggles
    singleton. Unchecked checkboxes aren't in request.POST so we
    check each field name explicitly."""
    toggles = IdentityToggles.get_self()
    fields = [
        'ticks_enabled', 'reflections_enabled', 'meditations_enabled',
        'concerns_enabled', 'oracle_enabled', 'codex_push_enabled',
        'topbar_pulse_enabled', 'recursive_introspection_enabled',
        'observer_enabled', 'llm_chat_enabled',
        'rumination_stream_enabled',
    ]
    # Tile generation frequency slider — integer 0-8
    try:
        raw = int(request.POST.get('tile_generation_slider', 7))
    except (TypeError, ValueError):
        raw = 7
    toggles.tile_generation_slider = max(0, min(8, raw))
    for f in fields:
        setattr(toggles, f, bool(request.POST.get(f)))
    toggles.save()
    return redirect('identity:home')


@login_required
@require_POST
def cron_run_now(request):
    """Operator-initiated cron dispatch — 'Run cron now' button.
    Runs with --force all so every pipeline fires regardless of
    clock. Returns to the Identity home page where the operator
    can see the new CronRun rows."""
    from .cron import dispatch
    dispatch(force=['all'])
    return redirect('identity:home')


@login_required
def meditations_list(request):
    """All Meditation rows, newest first, with an optional depth filter."""
    depth_filter = request.GET.get('depth', '').strip()
    voice_filter = request.GET.get('voice', '').strip()
    qs = Meditation.objects.all()
    if depth_filter:
        try:
            qs = qs.filter(depth=int(depth_filter))
        except ValueError:
            pass
    if voice_filter:
        qs = qs.filter(voice=voice_filter)
    return render(request, 'identity/meditations_list.html', {
        'meditations': qs,
        'depth_filter': depth_filter,
        'voice_filter': voice_filter,
        'depths': range(1, 8),
        'voices': [c[0] for c in Meditation.VOICE_CHOICES],
    })


@login_required
def meditation_detail(request, pk):
    try:
        med = Meditation.objects.get(pk=pk)
    except Meditation.DoesNotExist:
        return redirect('identity:meditations_list')
    return render(request, 'identity/meditation_detail.html', {
        'meditation': med,
        'recursions': Meditation.objects.filter(recursive_of=med),
    })


@login_required
@require_POST
def meditation_compose(request):
    """Operator-initiated meditation composition — button on the
    meditations list page. Takes depth + voice and composes a single
    Meditation row, pushing into Identity's Mirror manual."""
    from .meditation import meditate
    try:
        depth = int(request.POST.get('depth', 1))
    except ValueError:
        depth = 1
    voice = request.POST.get('voice', 'contemplative').strip()
    if voice not in dict(Meditation.VOICE_CHOICES):
        voice = 'contemplative'
    meditate(depth=depth, voice=voice, push_to_codex=True)
    return redirect('identity:meditations_list')


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
    and supports mood/aspect filtering via query params. Also looks
    up the matching OracleLabel per tick so the operator can rate
    the rumination template pick with good/bad/meh buttons."""
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

    # Look up OracleLabel rows for the visible ticks and attach each
    # one to its Tick as .oracle_label so the template can render the
    # feedback buttons inline without a dict lookup.
    try:
        from oracle.models import OracleLabel
        tick_ids = [t.pk for t in page.object_list]
        labels = OracleLabel.objects.filter(
            lobe_name='rumination_template',
            linked_model='identity.Tick',
            linked_pk__in=tick_ids,
        )
        label_by_tick = {lb.linked_pk: lb for lb in labels}
    except Exception:
        label_by_tick = {}
    for t in page.object_list:
        t.oracle_label = label_by_tick.get(t.pk)

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
        'label_by_tick': label_by_tick,
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

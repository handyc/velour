from django.http import Http404, HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .compile import EXAMPLES, compile_c


# Registered sublabs. Add a new entry here when you drop a new
# sublab module under static/s3lab/js/sublabs/.
#
#   slug      URL segment after /s3lab/
#   module    filename (without extension) under static/s3lab/js/sublabs/
#   template  Django template path for the body partial — included
#             from index.html via {% include active_sublab.template %}
#   name      label shown on the tab strip
#   blurb     one-line hover hint; appears as the tab `title`
SUBLABS = [
    {
        'slug':     'classic',
        'module':   'classic',
        'template': 's3lab/sublabs/classic_body.html',
        'name':     'Classic',
        'blurb':    'The original /s3lab/ bench: hunt + GPIO + TFT + '
                    'timing diagram. The base frame the other sublabs '
                    'extend.',
    },
    {
        'slug':     'filmstrip',
        'module':   'filmstrip',
        'template': 's3lab/sublabs/filmstrip_body.html',
        'name':     'Filmstrip',
        'blurb':    'A scrolling strip of recent CA refinements. Each '
                    'frame is one past genome; on every refine the '
                    'strip shifts left and a new live tile appears.',
    },
    {
        'slug':     'cellular',
        'module':   'cellular',
        'template': 's3lab/sublabs/cellular_body.html',
        'name':     'Cellular',
        'blurb':    'Tiles-are-population spatial GA on a pointy-top '
                    'hex tiling. 256 cells, 6-neighbour tournament '
                    'selection. Watch good rules sweep regions.',
    },
    {
        'slug':     'stratum',
        'module':   'stratum',
        'template': 's3lab/sublabs/stratum_body.html',
        'name':     'Stratum',
        'blurb':    'Two-layer hex CA: 64-entry library of K=64 HexNN '
                    'rules + a 16×16 meta-CA whose states index the '
                    'library. The elite library entry drives the meta-CA. '
                    'One rule playing two scales of itself.',
    },
    # Future sublabs land here. Keep entries small.
]
SUBLABS_BY_SLUG = {s['slug']: s for s in SUBLABS}
DEFAULT_SUBLAB = 'classic'


def _render_sublab(request, sublab_slug):
    active = SUBLABS_BY_SLUG.get(sublab_slug)
    if not active:
        raise Http404(f'unknown s3lab sublab: {sublab_slug!r}')
    return render(request, 's3lab/index.html', {
        'sublabs':       SUBLABS,
        'active_sublab': active,
    })


@ensure_csrf_cookie
@login_required
def index(request):
    """Default S3 Lab view — Classic sublab.

    All compute (engine, GA, render, GPIO) runs in the browser. The
    Django side just serves the page + static assets and tracks which
    sublab module to load. The ``ensure_csrf_cookie`` decorator makes
    the "→ Automaton" export button work — without it Django never
    writes the csrftoken cookie on this page (no form), so the
    JS-side X-CSRFToken header is empty and the POST to
    /automaton/import-from-s3lab/ 403s.
    """
    return _render_sublab(request, DEFAULT_SUBLAB)


@ensure_csrf_cookie
@login_required
def sublab(request, slug):
    """Named sublab — same chrome as /s3lab/, different module."""
    return _render_sublab(request, slug)


# ── Phase 1: compile-on-Velour for the ESP32-S3 supermini ─────────

@ensure_csrf_cookie
@login_required
def compile_page(request):
    """C-source editor that compiles to a Xtensa LX7 relocatable ELF
    via the vendored xcc700 binary. The compile itself happens via
    the compile_run view so the editor stays put on errors."""
    return render(request, 's3lab/compile.html', {
        'examples': EXAMPLES,
    })


@login_required
@require_POST
def compile_run(request):
    """Compile C source POSTed in ``source`` and return:

      * On success with ``download=1`` (default): the ELF as a binary
        download (Content-Type application/octet-stream).
      * On success with ``download=0``: JSON {ok, build_log, elf_b64,
        elapsed_ms, elf_bytes}.
      * On failure: JSON {ok: false, error, build_log, elapsed_ms}
        with status 200 (the editor expects to display it inline).
    """
    import base64

    source = request.POST.get('source', '')
    name = request.POST.get('name', 'a.elf').strip() or 'a.elf'
    download = request.POST.get('download', '1') != '0'

    result = compile_c(source)

    if not result.ok:
        return JsonResponse({
            'ok': False,
            'error': result.error,
            'build_log': result.build_log,
            'elapsed_ms': result.elapsed_ms,
        })

    if download:
        # Inline download — the page's <form target="_blank"> picks this up.
        if not name.endswith('.elf'):
            name = name + '.elf'
        resp = HttpResponse(result.elf, content_type='application/octet-stream')
        resp['Content-Disposition'] = f'attachment; filename="{name}"'
        resp['X-Xcc700-Build-Log'] = result.build_log.replace('\n', ' | ')
        resp['X-Xcc700-Elapsed-Ms'] = str(result.elapsed_ms)
        resp['X-Xcc700-Elf-Bytes'] = str(result.elf_bytes)
        return resp

    return JsonResponse({
        'ok': True,
        'build_log': result.build_log,
        'elf_b64': base64.b64encode(result.elf).decode('ascii'),
        'elf_bytes': result.elf_bytes,
        'source_bytes': result.source_bytes,
        'elapsed_ms': result.elapsed_ms,
    })


@login_required
@require_POST
def compile_push(request):
    """Compile + push the resulting ELF to a hexca device on the LAN.
    Optionally chain a /run-elf?slot=NAME to install it as a slot
    on the next CA tick.

    POST args:
      source       — C source (same as compile_run)
      device_url   — base URL of the device (default http://hexca.local)
      slot         — optional: step | render | gpio | fitness. If set,
                     after a successful /load-elf the proxy also POSTs
                     /run-elf?slot=<slot>.

    Returns JSON {ok, compile, push, run} — ``run`` is null if no
    slot was requested or if push failed.
    """
    import time
    import urllib.error
    import urllib.request

    source = request.POST.get('source', '')
    device_url = (request.POST.get('device_url') or
                  'http://hexca.local').rstrip('/')
    slot = (request.POST.get('slot') or '').strip()
    if slot and slot not in ('step', 'render', 'gpio', 'fitness'):
        return JsonResponse({'ok': False,
            'error': 'slot must be empty, step, render, gpio, or fitness'})

    result = compile_c(source)
    compile_payload = {
        'ok': result.ok,
        'error': result.error,
        'build_log': result.build_log,
        'elf_bytes': result.elf_bytes,
        'elapsed_ms': result.elapsed_ms,
    }
    if not result.ok:
        return JsonResponse({
            'ok': False,
            'compile': compile_payload,
            'push': None,
            'run': None,
        })

    push_target = f'{device_url}/load-elf'
    req = urllib.request.Request(
        push_target, data=result.elf, method='POST',
        headers={'Content-Type': 'application/octet-stream'},
    )
    push_t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            body = resp.read(4096).decode('utf-8', errors='replace')
            status = resp.status
            push_ok = 200 <= status < 300
    except urllib.error.HTTPError as e:
        body = e.read(4096).decode('utf-8', errors='replace')
        status = e.code
        push_ok = False
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        body = f'{type(e).__name__}: {e}'
        status = 0
        push_ok = False
    push_elapsed_ms = int((time.monotonic() - push_t0) * 1000)
    push_payload = {
        'ok': push_ok, 'target': push_target, 'status': status,
        'body': body, 'elapsed_ms': push_elapsed_ms,
    }

    run_payload = None
    if push_ok and slot:
        run_target = f'{device_url}/run-elf'
        run_req = urllib.request.Request(
            run_target, data=f'slot={slot}'.encode(), method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        run_t0 = time.monotonic()
        try:
            with urllib.request.urlopen(run_req, timeout=8.0) as resp:
                rbody = resp.read(2048).decode('utf-8', errors='replace')
                rstatus = resp.status
                run_ok = 200 <= rstatus < 300
        except urllib.error.HTTPError as e:
            rbody = e.read(2048).decode('utf-8', errors='replace')
            rstatus = e.code
            run_ok = False
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            rbody = f'{type(e).__name__}: {e}'
            rstatus = 0
            run_ok = False
        run_payload = {
            'ok': run_ok, 'slot': slot, 'target': run_target,
            'status': rstatus, 'body': rbody,
            'elapsed_ms': int((time.monotonic() - run_t0) * 1000),
        }

    overall_ok = push_ok and (run_payload is None or run_payload['ok'])
    return JsonResponse({
        'ok': overall_ok,
        'compile': compile_payload,
        'push': push_payload,
        'run': run_payload,
    })


# ── Phase 5: device dashboard + proxied actions ───────────────────────

@ensure_csrf_cookie
@login_required
def device_page(request):
    """Live status page for the supermini fork. Polls /info on the
    device every couple of seconds via the Velour-side proxy below
    (so the browser doesn't have to talk to hexca.local directly +
    avoids CORS)."""
    return render(request, 's3lab/device.html', {})


def _device_url(request) -> str:
    raw = (request.POST.get('device_url') or
           request.GET.get('device_url') or
           'http://hexca.local').rstrip('/')
    return raw


@login_required
def device_info(request):
    """GET-only proxy for hexca.local/info. Returns the device's JSON
    verbatim, or a structured error if the device is unreachable."""
    import time
    import urllib.error
    import urllib.request

    target = f'{_device_url(request)}/info'
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(target, timeout=4.0) as resp:
            body = resp.read(8192).decode('utf-8', errors='replace')
            status = resp.status
    except urllib.error.HTTPError as e:
        return JsonResponse({
            'ok': False, 'target': target, 'status': e.code,
            'body': e.read(2048).decode('utf-8', errors='replace'),
            'elapsed_ms': int((time.monotonic() - t0) * 1000),
        })
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return JsonResponse({
            'ok': False, 'target': target, 'status': 0,
            'body': f'{type(e).__name__}: {e}',
            'elapsed_ms': int((time.monotonic() - t0) * 1000),
        })

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    try:
        import json as _json
        info = _json.loads(body)
    except Exception:
        info = None
    return JsonResponse({
        'ok': 200 <= status < 300,
        'target': target,
        'status': status,
        'info': info,
        'body': body if info is None else '',
        'elapsed_ms': elapsed_ms,
    })


@login_required
@require_POST
def device_action(request):
    """Server-side proxy for the device's POST endpoints.

    POST args:
      device_url  — base URL (default http://hexca.local)
      action      — one of: reset-slots, rehunt, run-elf
      slot        — only used when action=run-elf

    Returns JSON {ok, target, status, body, elapsed_ms}.
    """
    import time
    import urllib.error
    import urllib.request

    action = (request.POST.get('action') or '').strip()
    if action not in ('reset-slots', 'rehunt', 'run-elf'):
        return JsonResponse({'ok': False, 'error':
            'action must be reset-slots, rehunt, or run-elf'})

    target = f'{_device_url(request)}/{action}'
    body_data = b''
    if action == 'run-elf':
        slot = (request.POST.get('slot') or 'step').strip()
        if slot not in ('step', 'render', 'gpio', 'fitness'):
            return JsonResponse({'ok': False, 'error':
                'slot must be step, render, gpio, or fitness'})
        body_data = f'slot={slot}'.encode()
        target = f'{_device_url(request)}/run-elf'
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    else:
        headers = {}

    req = urllib.request.Request(target, data=body_data, method='POST',
                                 headers=headers)
    # /rehunt blocks 10-30 s; give it a generous timeout.
    timeout_s = 60.0 if action == 'rehunt' else 10.0
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read(4096).decode('utf-8', errors='replace')
            status = resp.status
            ok = 200 <= status < 300
    except urllib.error.HTTPError as e:
        body = e.read(4096).decode('utf-8', errors='replace')
        status = e.code
        ok = False
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        body = f'{type(e).__name__}: {e}'
        status = 0
        ok = False
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    return JsonResponse({
        'ok': ok, 'target': target, 'status': status,
        'body': body, 'elapsed_ms': elapsed_ms,
    })

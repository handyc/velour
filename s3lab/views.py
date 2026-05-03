from django.http import Http404, HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .compile import EXAMPLES, compile_c
from .models import SlotPatch


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
    {
        'slug':     'strateta',
        'module':   'strateta',
        'template': 's3lab/sublabs/strateta_body.html',
        'name':     'Strateta',
        'blurb':    'K=256 sibling of Stratum. 16×16 library of K=256 '
                    'HexNN rules — image upload fills 256 palettes from '
                    'a 256×256-pixel mosaic. Two refine modes: '
                    'edge-of-chaos or pixel-faithful to the source.',
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


@login_required
def gallery(request):
    """Sublab directory page: every sublab as a card with a live K=4
    hex-CA preview that animates using one Taxon rule assigned to that
    card. Lets a visitor sniff the bench before clicking through."""
    # One rule per sublab, picked so each card gets a different
    # genome — preferring class 4 when available, since those make
    # the most visually interesting thumbnails. If we run out of
    # class-4s, fall back to anything.
    cards = []
    try:
        from taxon.models import Rule
        # `cls(latest_classification=4) ORDER BY random()` would be ideal
        # but cross-DB. Pull a small pool and shuffle in Python.
        pool = list(
            Rule.objects.filter(kind='hex_k4_packed')
            .order_by('-created_at')[:200]
        )
        # Prefer class-4 rules; otherwise just use what we have.
        c4 = [r for r in pool
              if r.latest_classification
              and r.latest_classification.wolfram_class == 4]
        chosen_pool = c4 if len(c4) >= len(SUBLABS) else pool
        import random
        random.shuffle(chosen_pool)
    except Exception:
        chosen_pool = []

    try:
        from taxon.classifier import class_color
    except Exception:
        def class_color(n): return '#586069'

    for i, sub in enumerate(SUBLABS):
        rule = chosen_pool[i % len(chosen_pool)] if chosen_pool else None
        c = rule.latest_classification if rule else None
        n = c.wolfram_class if c else None
        cards.append({
            'sub':      sub,
            'rule':     rule,
            'genome_hex': bytes(rule.genome).hex() if rule else '',
            'palette':  rule.palette_hex if rule else [],
            'class_n':  n,
            'class_color': class_color(n) if n else '#30363d',
        })
    return render(request, 's3lab/gallery.html', {
        'cards':   cards,
        'sublabs': SUBLABS,
    })


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

    # Persist the patch + push into the SlotPatch library so it shows
    # up at /s3lab/slots/. sha1(elf) is the identity — re-pushes of
    # the same blob just bump push_count + success_count.
    try:
        patch = SlotPatch.upsert(
            source_text=source,
            elf_blob=result.elf,
            build_time_ms=result.elapsed_ms,
            slot=slot or '',
            name=request.POST.get('name', '').strip(),
            user=request.user if request.user.is_authenticated else None,
            last_pushed_to=device_url,
            push_succeeded=push_ok,
        )
        patch_slug = patch.slug
    except Exception:
        patch_slug = None

    return JsonResponse({
        'ok': overall_ok,
        'compile': compile_payload,
        'push': push_payload,
        'run': run_payload,
        'patch_slug': patch_slug,
    })


# ── Phase 6: SlotPatch library ────────────────────────────────────────

@login_required
def slots_list(request):
    from django.db.models import Q
    qs = SlotPatch.objects.all()
    slot = (request.GET.get('slot', '') or '').strip()
    if slot:
        qs = qs.filter(slot=slot)
    q = (request.GET.get('q', '') or '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(slug__icontains=q) |
            Q(elf_sha1__istartswith=q) | Q(notes__icontains=q) |
            Q(last_pushed_to__icontains=q)
        )
    sort = request.GET.get('sort', 'newest')
    if sort == 'oldest':
        qs = qs.order_by('created_at')
    elif sort == 'pushcount':
        qs = qs.order_by('-push_count')
    else:
        qs = qs.order_by('-created_at')
    return render(request, 's3lab/slots_list.html', {
        'patches': qs[:200],
        'total': qs.count(),
        'q': q,
        'sort': sort,
        'active_slot': slot,
        'slots': ['step', 'render', 'gpio', 'fitness'],
    })


@login_required
def slot_detail(request, slug: str):
    patch = get_object_or_404(SlotPatch, slug=slug)
    return render(request, 's3lab/slot_detail.html', {
        'patch': patch,
    })


@login_required
def slot_download(request, slug: str):
    patch = get_object_or_404(SlotPatch, slug=slug)
    resp = HttpResponse(bytes(patch.elf_blob),
                        content_type='application/octet-stream')
    resp['Content-Disposition'] = f'attachment; filename="{patch.slug}.elf"'
    return resp


@login_required
@require_POST
def slot_repush(request, slug: str):
    """Re-push a stored ELF to a device, optionally chaining /run-elf?slot=NAME."""
    import time
    import urllib.error
    import urllib.request

    patch = get_object_or_404(SlotPatch, slug=slug)
    device_url = (request.POST.get('device_url') or
                  patch.last_pushed_to or
                  'http://hexca.local').rstrip('/')
    slot = (request.POST.get('slot') or patch.slot or '').strip()
    if slot and slot not in ('step', 'render', 'gpio', 'fitness'):
        return JsonResponse({'ok': False, 'error':
            'slot must be empty, step, render, gpio, or fitness'})

    push_target = f'{device_url}/load-elf'
    elf = bytes(patch.elf_blob)
    req = urllib.request.Request(
        push_target, data=elf, method='POST',
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
    push_payload = {
        'ok': push_ok, 'target': push_target, 'status': status,
        'body': body, 'elapsed_ms': int((time.monotonic() - push_t0) * 1000),
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

    # Bump push history on the patch.
    patch.push_count += 1
    if push_ok:
        patch.success_count += 1
    patch.last_pushed_to = device_url
    from django.utils import timezone
    patch.last_push_at = timezone.now()
    patch.save()

    return JsonResponse({
        'ok': push_ok and (run_payload is None or run_payload['ok']),
        'push': push_payload,
        'run': run_payload,
    })


@ensure_csrf_cookie
@login_required
def cellular_tft(request):
    """Pixel-faithful 80x160 (rot 3 → 160x80) preview of the
    isolation/artifacts/cellular/esp32_s3/ firmware."""
    return render(request, 's3lab/cellular_tft.html', {})


# ── Cellular sublab → Tiles + Zoetrope cross-app integrations ────────

def _hex_to_bytes(hex_str: str, expected_len: int) -> bytes:
    """Strict hex decoder. Raises ValueError on bad input + length."""
    s = (hex_str or '').strip()
    try:
        b = bytes.fromhex(s)
    except ValueError as e:
        raise ValueError(f'bad hex: {e}')
    if len(b) != expected_len:
        raise ValueError(f'expected {expected_len} bytes, got {len(b)}')
    return b


@login_required
@require_POST
def cellular_to_tiles(request):
    """Cellular sublab → Tiles. Take the elite cell's genome + palette,
    materialise a hex TileSet that all share a fresh automaton.RuleSet
    (one rule, multiple tiles with different initial grids), with
    per-tile edge colours derived from the palette.

    POST args:
      genome_hex   — 8192 hex chars (4096-byte K=4 packed genome)
      palette_hex  — 8 hex chars (4-byte ANSI-256 palette)
      name         — optional human label
      n_tiles      — int, default 12

    Returns JSON {ok, tileset_slug, tileset_url, ruleset_slug, n_tiles}.
    """
    import random
    from automaton.packed import PackedRuleset, ansi256_to_hex
    from tiles.models import Tile, TileSet

    try:
        genome = _hex_to_bytes(request.POST.get('genome_hex', ''), 4096)
        palette = _hex_to_bytes(request.POST.get('palette_hex', ''), 4)
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)})

    name = (request.POST.get('name', '') or 'cellular elite').strip()[:120]
    try:
        n_tiles = max(1, min(48, int(request.POST.get('n_tiles', 12))))
    except ValueError:
        n_tiles = 12

    palette_css = [ansi256_to_hex(idx) for idx in palette]

    # Step 1: create an automaton.RuleSet from the genome (reusing the
    # exact import path automaton already supports, so the rule shows
    # up in /automaton/ with a runnable Simulation too).
    from automaton.models import ExactRule
    from automaton.models import RuleSet as AutomatonRuleSet
    from django.utils.crypto import get_random_string
    from django.db import transaction

    packed = PackedRuleset(n_colors=4, data=genome)
    explicit = packed.to_explicit(skip_identity=True)
    base_name = f'{name} ({get_random_string(4).lower()})'
    while AutomatonRuleSet.objects.filter(name=base_name).exists():
        base_name = f'{name} ({get_random_string(4).lower()})'

    with transaction.atomic():
        rs = AutomatonRuleSet.objects.create(
            name=base_name,
            description=(f'Imported from s3lab Cellular elite. '
                         f'{len(explicit)} non-identity patterns.'),
            n_colors=4, source='operator',
            palette=palette_css,
            source_metadata={
                'origin': 'imported', 'source': 's3lab-cellular',
                'palette_ansi256': list(palette),
                'palette_css': palette_css,
            },
        )
        ExactRule.objects.bulk_create([
            ExactRule(
                ruleset=rs,
                self_color=er['s'],
                n0_color=er['n'][0], n1_color=er['n'][1],
                n2_color=er['n'][2], n3_color=er['n'][3],
                n4_color=er['n'][4], n5_color=er['n'][5],
                result_color=er['r'],
                priority=i,
            ) for i, er in enumerate(explicit)
        ])

        # Step 2: create the TileSet. Hex tiles, 6 edge colours each.
        # We assign edges by sampling the palette so adjacent tiles
        # have a non-trivial chance of matching.
        ts_name = name
        n = 2
        while TileSet.objects.filter(name=ts_name).exists():
            ts_name = f'{name} {n}'; n += 1
        ts = TileSet.objects.create(
            name=ts_name,
            description=(f'Generated from s3lab Cellular elite. '
                         f'{n_tiles} tiles share one CA rule (RuleSet '
                         f'"{rs.slug}"); each tile has a different '
                         f'random initial grid. Edge colours sampled '
                         f'from the genome palette.'),
            tile_type='hex',
            palette=palette_css,
            source='operator',
            source_metadata={
                'origin': 's3lab-cellular',
                'ruleset_slug': rs.slug,
                'palette_ansi256': list(palette),
            },
        )

        rng = random.Random(0)  # deterministic edge-colour sampling
        for i in range(n_tiles):
            init = [[rng.randrange(4) for _ in range(16)] for _ in range(16)]
            edges = {k: palette_css[rng.randrange(4)]
                     for k in ('n_color', 'ne_color', 'se_color',
                               's_color', 'sw_color', 'nw_color')}
            Tile.objects.create(
                tileset=ts,
                name=f'T{i}',
                ca_ruleset=rs,
                ca_initial_grid=init,
                sort_order=i,
                **edges,
            )

    return JsonResponse({
        'ok': True,
        'tileset_slug': ts.slug,
        'tileset_url': f'/tiles/{ts.slug}/',
        'ruleset_slug': rs.slug,
        'ruleset_url': f'/automaton/{rs.slug}/',
        'n_tiles': n_tiles,
    })


@login_required
@require_POST
def cellular_to_zoetrope(request):
    """Cellular sublab → Zoetrope. Run the cellular Python kernel
    server-side for ``rounds`` rounds, render a frame every ``stride``
    rounds via PIL, save each as an Attic MediaItem, build a Reel and
    render it to mp4.

    POST args:
      rounds       — int 30..2000, default 200
      stride       — int 1..50, render every Nth round, default 5
      seed         — int, 0 = random
      fps          — int 4..60, default 10
      title        — str, optional

    Returns JSON {ok, reel_slug, reel_url, frames, render_status}.
    """
    import io
    import sys
    import time
    from pathlib import Path
    from django.core.files.base import ContentFile
    from django.utils.crypto import get_random_string
    from PIL import Image

    rounds = max(30, min(2000, int(request.POST.get('rounds', 200))))
    stride = max(1, min(50, int(request.POST.get('stride', 5))))
    seed   = int(request.POST.get('seed', 0))
    fps    = max(4, min(60, int(request.POST.get('fps', 10))))
    title  = (request.POST.get('title', '') or
              f'Cellular {time.strftime("%Y-%m-%d %H:%M")}').strip()[:200]

    # Import the canonical Python kernel from isolation/artifacts so
    # the same source of truth runs server-side.
    cell_dir = Path(__file__).resolve().parent.parent / \
               'isolation/artifacts/cellular/python'
    if str(cell_dir) not in sys.path:
        sys.path.insert(0, str(cell_dir))
    import cellular as kernel        # type: ignore

    # ANSI-256 → RGB lookup. Inline since we can't use kernel's
    # ANSI-only render — we want PNG frames.
    def ansi_to_rgb(idx: int) -> tuple[int, int, int]:
        if idx < 16:
            std = [(0,0,0),(128,0,0),(0,128,0),(128,128,0),
                   (0,0,128),(128,0,128),(0,128,128),(192,192,192),
                   (128,128,128),(255,0,0),(0,255,0),(255,255,0),
                   (0,0,255),(255,0,255),(0,255,255),(255,255,255)]
            return std[idx]
        if idx < 232:
            lvl = (0, 95, 135, 175, 215, 255)
            i = idx - 16
            return (lvl[i // 36], lvl[(i % 36) // 6], lvl[i % 6])
        v = min(255, 8 + (idx - 232) * 10)
        return (v, v, v)

    def render_frame(round_no: int) -> bytes:
        """Render the population to a PNG. Each cell = 32x32 px, with
        a 1-px black border between tiles. 16x16 cells → 528x528 image."""
        TILE = 32
        GAP = 1
        W = kernel.GRID_COLS * TILE + (kernel.GRID_COLS + 1) * GAP
        H = kernel.GRID_ROWS * TILE + (kernel.GRID_ROWS + 1) * GAP
        img = Image.new('RGB', (W, H), (13, 17, 23))
        px = img.load()
        for r in range(kernel.GRID_ROWS):
            for c in range(kernel.GRID_COLS):
                cell = kernel.pop[r * kernel.GRID_COLS + c]
                ansi = kernel.dominant_palette_idx(cell)
                rgb = ansi_to_rgb(ansi)
                x0 = c * TILE + (c + 1) * GAP
                y0 = r * TILE + (r + 1) * GAP
                for dy in range(TILE):
                    for dx in range(TILE):
                        px[x0 + dx, y0 + dy] = rgb
        # Hairline label band along bottom — round number in white.
        # Skip drawing text (no font deps); just record metadata.
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        return buf.getvalue()

    # Run the kernel + capture frames.
    if seed == 0:
        seed = int(time.time()) & 0xFFFFFFFF
    kernel.bootstrap_pop(seed)
    kernel._g_rounds = 0
    kernel._last_winner = -1
    kernel._last_loser = -1

    from attic.models import MediaItem
    from zoetrope.models import Reel

    frame_pks: list[int] = []
    tag = f'cellular-{seed:08x}'

    t0 = time.monotonic()
    for round_no in range(rounds):
        kernel.tick_all()
        kernel.run_round(0.005)
        if (kernel._g_rounds % stride) == 0:
            png = render_frame(kernel._g_rounds)
            mi = MediaItem(
                title=f'cellular {seed:08x} round {kernel._g_rounds:04d}',
                tags=tag,
                caption=(f'Cellular sublab population, round '
                         f'{kernel._g_rounds}/{rounds} (seed {seed:#x}).'),
            )
            fname = f'{tag}-{kernel._g_rounds:04d}.png'
            mi.file.save(fname, ContentFile(png), save=False)
            mi.save()
            frame_pks.append(mi.pk)
    capture_elapsed = time.monotonic() - t0

    if not frame_pks:
        return JsonResponse({'ok': False,
            'error': 'no frames captured (rounds < stride?)'})

    # Build + render the Reel.
    base_slug = title
    reel = Reel(
        title=title,
        tag_filter=tag,
        selection_mode='recent',
        image_count=len(frame_pks),
        fps=fps,
        duration_seconds=max(1.0, len(frame_pks) / fps),
        width=528, height=528,
        speech_sample_count=0,
        speech_volume=0.0,
        frame_order=frame_pks,
    )
    # Slug uniqueness
    n = 2
    from django.utils.text import slugify
    base = slugify(title) or 'cellular'
    cand = base
    while Reel.objects.filter(slug=cand).exists():
        cand = f'{base}-{n}'; n += 1
    reel.slug = cand
    reel.save()

    render_status = 'pending'
    render_err = ''
    try:
        reel.render()
        render_status = reel.status
    except Exception as e:
        render_err = str(e)
        render_status = 'error'

    return JsonResponse({
        'ok': render_status == 'ready',
        'reel_slug': reel.slug,
        'reel_url': f'/zoetrope/{reel.slug}/',
        'frames': len(frame_pks),
        'capture_elapsed_s': round(capture_elapsed, 1),
        'render_status': render_status,
        'render_err': render_err,
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

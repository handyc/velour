"""Ouroboros views — present the discovered class-4 fixed-point
quines, their lineages, and their chain dynamics.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from typing import Optional

from django.contrib.auth.decorators import login_required
from django.http import (Http404, HttpResponse, JsonResponse)
from django.shortcuts import get_object_or_404, render
from django.utils.cache import patch_response_headers
from django.views.decorators.cache import cache_page


# ─── Helpers ─────────────────────────────────────────────────────────

QUINE_SLUG = 'class4_quine'

# Default palette for rendering a 16,384-byte LUT as a 128×128 image.
# Same hues as spoeqi's DEFAULT_PALETTE, kept here so we don't depend
# on view-side state.
_PALETTE_RGB = [
    (220,  80,  40),   # 0  vermilion
    ( 60, 120, 210),   # 1  azure
    ( 80, 180,  90),   # 2  verdant
    (230, 200,  60),   # 3  amber
]


def _quine_qs():
    from caformer.models import ComponentChampion
    return ComponentChampion.objects.filter(component_slug=QUINE_SLUG)


def _quine_meta(c) -> dict:
    try:
        return json.loads(c.notes or '{}') or {}
    except (ValueError, TypeError):
        return {}


def _short_sha(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()[:8]


def _walk_chain_levels(seed_bytes: bytes, depth: int) -> list[dict]:
    """Walk the metachain and emit per-level metrics.  Stops at cycle
    detection."""
    from spoeqi.metachain import (
        classify_rule, probe_activity, sr_arbitrary_sigma,
        self_reproduce_score, hex_ca_step)
    import numpy as np

    rule_arr = np.frombuffer(seed_bytes, dtype=np.uint8).copy() & 3
    out: list[dict] = []
    seen: dict[bytes, int] = {}
    current = rule_arr
    for level in range(depth):
        cur_bytes = bytes(current.tobytes())
        cls, c4 = classify_rule(cur_bytes, probe_ticks=16)
        act = probe_activity(cur_bytes, ticks=12)
        sr_s = self_reproduce_score(cur_bytes, ticks=16)
        sr_a = sr_arbitrary_sigma(cur_bytes, ticks=16)
        ok = (cls == 4 and 0.05 <= act <= 0.85 and sr_a >= 0.85)
        out.append({
            'level':       level,
            'sha':         hashlib.sha1(cur_bytes).hexdigest()[:8],
            'class':       cls,
            'c4':          float(c4),
            'act':         float(act),
            'sr_strict':   float(sr_s),
            'sr_arbsigma': float(sr_a),
            'ok':          ok,
        })

        # Next
        state = current.reshape(128, 128).copy()
        for _ in range(16):
            state = hex_ca_step(state, current)
        nxt = state.flatten() & 3
        nb = bytes(nxt.tobytes())
        if nb == cur_bytes:
            out.append({'level':       level + 1,
                        'sha':         out[-1]['sha'],
                        'class':       out[-1]['class'],
                        'c4':          out[-1]['c4'],
                        'act':         out[-1]['act'],
                        'sr_strict':   out[-1]['sr_strict'],
                        'sr_arbsigma': out[-1]['sr_arbsigma'],
                        'ok':          out[-1]['ok'],
                        'note':        'fixed point — chain stable here'})
            break
        if nb in seen:
            out.append({'level': level + 1,
                        'sha':   hashlib.sha1(nb).hexdigest()[:8],
                        'class': None, 'c4': None, 'act': None,
                        'sr_strict': None, 'sr_arbsigma': None,
                        'ok':    False,
                        'note':  f'cycle entry — returns to L{seen[nb]} '
                                 f'(period {level + 1 - seen[nb]})'})
            break
        seen[nb] = level + 1
        current = nxt
    return out


def _lineage_graph() -> dict:
    """Return ``{pk: {'parent': str|None, 'children': [pk,…]}}``.

    Parent is inferred from the ``notes`` JSON ``ga_parent`` field
    (short sha8) plus the ``origin`` string for deep-chain-ga rows.
    """
    by_pk: dict[int, dict] = {}
    by_sha: dict[str, int] = {}
    for c in _quine_qs().order_by('pk'):
        sha = _short_sha(bytes(c.rules_blob))
        m = _quine_meta(c)
        by_pk[c.pk] = {
            'pk':       c.pk,
            'sha':      sha,
            'parent':   m.get('ga_parent') or '',
            'origin':   m.get('origin', '?'),
            'fitness':  c.fitness,
            'run_len':  m.get('class4_run_length', 0),
            'ga_runlen': m.get('ga_run_length'),
            'children': [],
        }
        by_sha[sha] = c.pk
    # Resolve parent shas to pks
    for pk, node in by_pk.items():
        psha = node['parent']
        if psha and psha in by_sha:
            node['parent_pk'] = by_sha[psha]
            by_pk[by_sha[psha]]['children'].append(pk)
        else:
            node['parent_pk'] = None
    return by_pk


# ─── Index ────────────────────────────────────────────────────────────

@login_required
def index(request):
    """Catalogue of every saved class-4 quine, paginated.

    Hashing every LUT to produce sha8 is ~1 ms/row, so without paging
    the catalogue page was doing ~2 s of hashing alone after the L0
    search dumped 1.7k rows.  Filter + paginate before hydration."""
    from django.core.paginator import Paginator
    from caformer.models import ComponentChampion

    SORTS = {
        'fitness':    '-fitness',
        'created':    '-created_at',
        'pk_asc':     'pk',
        'pk_desc':    '-pk',
    }
    sort_key = request.GET.get('sort') or 'fitness'
    order_by = SORTS.get(sort_key, '-fitness')

    qs = _quine_qs().only('pk', 'fitness', 'run_label', 'created_at',
                                'notes', 'rules_blob').order_by(order_by)

    f_origin    = (request.GET.get('origin') or '').strip()
    f_run_label = (request.GET.get('run_label') or '').strip()
    f_sha       = (request.GET.get('sha') or '').strip().lower()
    f_name      = (request.GET.get('name') or '').strip()
    try:
        f_min_runlen = int(request.GET.get('min_runlen') or 0)
    except ValueError:
        f_min_runlen = 0

    if f_run_label:
        qs = qs.filter(run_label=f_run_label)
    if f_origin:
        # `origin` is a notes-JSON field, no direct index — best-effort
        # substring match via Postgres-compatible CharField filter.
        qs = qs.filter(notes__icontains=f'"origin": "{f_origin}"')
    if f_name:
        # display_name is a notes-JSON field too; same trick.
        qs = qs.filter(notes__icontains=f'"display_name": ')
        qs = qs.filter(notes__icontains=f_name)
    if f_sha:
        # sha8 is computed from rules_blob; no DB-side index.  Apply
        # AFTER pagination would be wrong (we'd skip rows), so fall back
        # to a Python-side filter that walks the whole queryset.  Cheap
        # enough as long as the filter narrows down to a known prefix.
        pass  # filtered post-hydration below

    total_unfiltered = _quine_qs().count()

    # Distinct run_labels + origins for the filter dropdowns — cheap
    # because both are short fields.
    run_labels = list(
        ComponentChampion.objects
          .filter(component_slug=QUINE_SLUG)
          .exclude(run_label='')
          .values_list('run_label', flat=True)
          .distinct()
          .order_by('run_label'))

    # Always look up the featured quine directly — independent of page.
    featured_pk = 122
    feat_obj = _quine_qs().filter(pk=featured_pk).first()
    featured = None
    if feat_obj is not None:
        m = _quine_meta(feat_obj)
        featured = {
            'pk':       feat_obj.pk,
            'sha':      _short_sha(bytes(feat_obj.rules_blob)),
            'fitness':  feat_obj.fitness,
            'class4_run_length': m.get('class4_run_length', 0),
            'origin':   m.get('origin', '?'),
        }

    paginator = Paginator(qs, 50)
    try:
        page_num = max(1, int(request.GET.get('page') or 1))
    except ValueError:
        page_num = 1
    page = paginator.get_page(page_num)

    quines = []
    for c in page.object_list:
        m = _quine_meta(c)
        if f_min_runlen and (m.get('class4_run_length', 0) or 0) < f_min_runlen:
            continue
        sha8 = _short_sha(bytes(c.rules_blob))
        if f_sha and not sha8.startswith(f_sha):
            continue
        quines.append({
            'pk':       c.pk,
            'sha':      sha8,
            'fitness':  c.fitness,
            'origin':   m.get('origin', '?'),
            'run_label': c.run_label or '',
            'class4_run_length': m.get('class4_run_length', 0),
            'ga_run_length':     m.get('ga_run_length'),
            'created':  c.created_at,
            'display_name': m.get('display_name') or '',
        })

    # Build a query string for pagination links that preserves filters.
    keep = []
    for k in ('sort', 'origin', 'run_label', 'sha', 'min_runlen', 'name'):
        v = request.GET.get(k)
        if v:
            keep.append(f'{k}={v}')
    qs_keep = ('&' + '&'.join(keep)) if keep else ''

    return render(request, 'ouroboros/index.html', {
        'quines':           quines,
        'featured':         featured,
        'total':            paginator.count,
        'total_unfiltered': total_unfiltered,
        'page':             page,
        'page_size':        50,
        'run_labels':       run_labels,
        'sort':             sort_key,
        'filters': {
            'origin':     f_origin,
            'run_label':  f_run_label,
            'sha':        f_sha,
            'min_runlen': f_min_runlen,
            'name':       f_name,
        },
        'qs_keep':          qs_keep,
    })


# ─── Detail ──────────────────────────────────────────────────────────

@login_required
def detail(request, pk: int):
    """Showcase one quine — lineage, chain, ruleset, per-level stats."""
    c = get_object_or_404(_quine_qs(), pk=pk)
    seed = bytes(c.rules_blob)
    sha = _short_sha(seed)
    meta = _quine_meta(c)

    # Lineage
    graph = _lineage_graph()
    node = graph.get(pk, {})
    parent_pk = node.get('parent_pk')
    children = node.get('children', [])
    parent = graph.get(parent_pk) if parent_pk else None
    child_nodes = [graph[cp] for cp in children if cp in graph]

    # Ancestry chain — walk back to a root
    ancestry = []
    cur = pk
    visited = set()
    while cur and cur not in visited:
        visited.add(cur)
        ancestry.append(graph[cur])
        cur = graph[cur].get('parent_pk')
    ancestry.reverse()

    # Chain walk (limited depth for the detail page; deeper walks are
    # available via the API endpoint).
    walk_depth = int(request.GET.get('depth', 200))
    walk_depth = max(20, min(2000, walk_depth))
    levels = _walk_chain_levels(seed, walk_depth)

    # Summary stats from the walk
    streak = 0
    streak_start = None
    best_streak = 0
    best_start = None
    for i, lvl in enumerate(levels):
        if lvl['ok']:
            if streak == 0:
                streak_start = i
            streak += 1
            if streak > best_streak:
                best_streak = streak
                best_start = streak_start
        else:
            streak = 0

    fixed_point_level = None
    cycle_period = None
    for lvl in levels:
        if lvl.get('note', '').startswith('fixed point'):
            fixed_point_level = lvl['level']
            cycle_period = 1
            break
        if lvl.get('note', '').startswith('cycle'):
            fixed_point_level = lvl['level']
            # parse period from the note text
            import re
            mtch = re.search(r'period (\d+)', lvl['note'])
            if mtch:
                cycle_period = int(mtch.group(1))
            break

    fp_is_class4 = False
    if fixed_point_level is not None and fixed_point_level - 1 < len(levels):
        fp_lvl = levels[fixed_point_level - 1] if cycle_period == 1 else None
        if fp_lvl:
            fp_is_class4 = bool(fp_lvl['ok'])

    # Is this the breakthrough?
    is_featured = (pk == 122)

    return render(request, 'ouroboros/detail.html', {
        'champion':            c,
        'pk':                  pk,
        'sha':                 sha,
        'meta':                meta,
        'display_name':        meta.get('display_name') or '',
        'user_note':           meta.get('user_note') or '',
        'parent':              parent,
        'children_nodes':      child_nodes,
        'ancestry':            ancestry,
        'levels':              levels,
        'walk_depth':          walk_depth,
        'best_streak':         best_streak,
        'best_start':          best_start,
        'fixed_point_level':   fixed_point_level,
        'cycle_period':        cycle_period,
        'fp_is_class4':        fp_is_class4,
        'is_featured':         is_featured,
    })


# ─── Annotate (name + note) ──────────────────────────────────────────

@login_required
def annotate(request, pk: int):
    """POST endpoint: save a human-readable name + free-form note for
    a quine.  Stored in the ComponentChampion.notes JSON blob under
    keys ``display_name`` and ``user_note`` — no schema migration."""
    from django.http import HttpResponseRedirect
    from django.urls import reverse
    if request.method != 'POST':
        return HttpResponseRedirect(reverse('ouroboros:detail',
                                                args=[pk]))
    c = get_object_or_404(_quine_qs(), pk=pk)
    meta = _quine_meta(c)
    if 'display_name' in request.POST:
        name = (request.POST.get('display_name') or '').strip()[:120]
        if name:
            meta['display_name'] = name
        else:
            meta.pop('display_name', None)
    if 'user_note' in request.POST:
        note = (request.POST.get('user_note') or '').strip()[:4000]
        if note:
            meta['user_note'] = note
        else:
            meta.pop('user_note', None)
    c.notes = json.dumps(meta)
    c.save(update_fields=['notes'])
    return HttpResponseRedirect(reverse('ouroboros:detail', args=[pk]))


# ─── Ruleset image ────────────────────────────────────────────────────

@login_required
def ruleset_png(request, pk: int):
    """Render the 16,384-byte LUT as a 128×128 PNG image.

    Each pixel = one LUT entry's output cell (0-3 mapped to the
    default palette).  The whole rule is therefore visible as its
    own initial-condition image — the foundation of the metachain.
    """
    from PIL import Image
    c = get_object_or_404(_quine_qs(), pk=pk)
    seed = bytes(c.rules_blob)
    arr = bytes(b & 3 for b in seed)
    img = Image.new('RGB', (128, 128))
    px = img.load()
    for i, v in enumerate(arr):
        r, g, b = _PALETTE_RGB[v]
        px[i % 128, i // 128] = (r, g, b)

    # Optional upscale
    try:
        scale = max(1, min(8, int(request.GET.get('scale', 4))))
    except (TypeError, ValueError):
        scale = 4
    if scale != 1:
        img = img.resize((128 * scale, 128 * scale), Image.NEAREST)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    resp = HttpResponse(buf.getvalue(), content_type='image/png')
    patch_response_headers(resp, cache_timeout=3600)
    return resp


@login_required
def packed_png(request, pk: int):
    """Render the rule as a 64×64 'packed' image — 4 cells per byte.

    The 16,384 K=4 cells (2 bits each) pack 4-per-byte into 4096 bytes,
    which lays out exactly as a 64×64 grid of 8-bit values.  That's the
    same byte-stream you'd write to disk as the .HXC4 payload, just
    rendered as a 256-colour image instead of a 4-colour one.

    ?palette=gray (default) — monochrome
    ?palette=heat            — viridis-ish
    ?palette=hsv             — full hue circle
    ?scale=N (default 6)     — nearest-neighbour upscale factor
    """
    from PIL import Image
    c = get_object_or_404(_quine_qs(), pk=pk)
    seed = bytes(c.rules_blob)
    if len(seed) != 16384:
        return HttpResponse(
            f'expected 16,384-byte LUT; got {len(seed)} B', status=400)

    # Pack 4 cells into 1 byte (each cell = 2 bits).  Little-endian
    # within the byte so byte order matches the natural memory layout
    # of e.g. a uint8 array reshape((64, 64, 4)).
    packed = bytearray(4096)
    for i in range(4096):
        a = seed[i * 4]     & 3
        b = seed[i * 4 + 1] & 3
        c_ = seed[i * 4 + 2] & 3
        d = seed[i * 4 + 3] & 3
        packed[i] = a | (b << 2) | (c_ << 4) | (d << 6)

    pal_mode = (request.GET.get('palette') or 'gray').lower()
    img = Image.new('P', (64, 64))
    img.putdata(list(packed))
    palette = []
    if pal_mode == 'heat':
        # Cheap viridis-ish ramp: deep purple → green → yellow.
        for k in range(256):
            t = k / 255.0
            r = int(255 * max(0.0, min(1.0, 1.5 * t - 0.4)))
            g = int(255 * max(0.0, min(1.0, 1.5 - abs(2 * t - 1.0))))
            b = int(255 * max(0.0, min(1.0, 1.0 - 1.5 * t)))
            palette.extend((r, g, b))
    elif pal_mode == 'hsv':
        import colorsys
        for k in range(256):
            r, g, b = colorsys.hsv_to_rgb(k / 256.0, 0.85, 0.95)
            palette.extend((int(r * 255), int(g * 255), int(b * 255)))
    else:
        for k in range(256):
            palette.extend((k, k, k))
    img.putpalette(palette)

    try:
        scale = max(1, min(16, int(request.GET.get('scale', 6))))
    except (TypeError, ValueError):
        scale = 6
    if scale != 1:
        img = img.resize((64 * scale, 64 * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    resp = HttpResponse(buf.getvalue(), content_type='image/png')
    patch_response_headers(resp, cache_timeout=3600)
    return resp


@login_required
def chain_level_png(request, pk: int, level: int):
    """Render one chain level's LUT-as-image.  Level 0 is the seed
    itself; higher levels are the chain's iterated output."""
    from PIL import Image
    from spoeqi.metachain import hex_ca_step
    import numpy as np

    c = get_object_or_404(_quine_qs(), pk=pk)
    seed = bytes(c.rules_blob)
    current = np.frombuffer(seed, dtype=np.uint8).copy() & 3
    for _ in range(level):
        state = current.reshape(128, 128).copy()
        for _ in range(16):
            state = hex_ca_step(state, current)
        current = state.flatten() & 3
    arr = bytes(current.tolist())
    img = Image.new('RGB', (128, 128))
    px = img.load()
    for i, v in enumerate(arr):
        r, g, b = _PALETTE_RGB[v]
        px[i % 128, i // 128] = (r, g, b)
    try:
        scale = max(1, min(8, int(request.GET.get('scale', 4))))
    except (TypeError, ValueError):
        scale = 4
    if scale != 1:
        img = img.resize((128 * scale, 128 * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    resp = HttpResponse(buf.getvalue(), content_type='image/png')
    patch_response_headers(resp, cache_timeout=3600)
    return resp


# ─── Walk JSON (for interactive client-side viz) ──────────────────────

@login_required
def walk_json(request, pk: int):
    """JSON dump of per-level metrics for client-side rendering."""
    c = get_object_or_404(_quine_qs(), pk=pk)
    seed = bytes(c.rules_blob)
    try:
        depth = max(20, min(2000, int(request.GET.get('depth', 200))))
    except (TypeError, ValueError):
        depth = 200
    levels = _walk_chain_levels(seed, depth)
    return JsonResponse({
        'pk':        pk,
        'sha':       _short_sha(seed),
        'depth':     depth,
        'levels':    levels,
    })


# ─── Seed download ────────────────────────────────────────────────────

@login_required
def seed_bytes(request, pk: int):
    """Raw 16,384-byte LUT — same format as spoeqi quine_seed_bytes."""
    c = get_object_or_404(_quine_qs(), pk=pk)
    resp = HttpResponse(bytes(c.rules_blob),
                            content_type='application/octet-stream')
    resp['Content-Disposition'] = (
        f'attachment; filename="quine-{pk}-seed.bin"')
    return resp


# ─── Search-for-more-like-#122 ────────────────────────────────────────
#
# #122 is the canonical Ouroboros: a partial quine (sr ≈ 0.73) whose
# 16-tick metachain stayed class-4 for 1919 levels with 131 distinct
# orbit states before settling into a self-mapping fixed point.  Other
# rules in the catalogue with similar properties — ga_run_length ≥ 500
# and ga_distinct_levels ≥ 50 — qualify as "ouroboros-class" and
# deserve the same showcase treatment.
#
# This page lets the user launch deep_chain_search (the same GA that
# discovered #122) in the background and watch progress live.  New
# champions automatically appear in the index.

OUROBOROS_RUNLEN_THRESHOLD   = 500
OUROBOROS_DISTINCT_THRESHOLD = 50


def is_ouroboros_class(meta: dict) -> bool:
    """Heuristic: ``ga_run_length`` ≥ 500 indicates the metachain
    stayed class-4 for many levels; ``ga_distinct_levels`` ≥ 50 means
    the orbit before convergence is rich (not a trivial short cycle).
    Either condition alone qualifies — #122 hits both.
    """
    rl = int(meta.get('ga_run_length') or 0)
    dl = int(meta.get('ga_distinct_levels') or 0)
    return rl >= OUROBOROS_RUNLEN_THRESHOLD or dl >= OUROBOROS_DISTINCT_THRESHOLD


def _search_log_dir():
    """Where deep_chain_search subprocesses write progress logs."""
    from django.conf import settings
    p = settings.BASE_DIR / '.artifacts' / 'ouroboros_search'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _active_search_pid() -> Optional[int]:
    """Return the PID of a running search subprocess, if any.  Reads
    the pidfile written by the launcher and verifies the process is
    still alive via /proc."""
    import os
    pidfile = _search_log_dir() / 'current.pid'
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text().strip())
    except (ValueError, OSError):
        return None
    if os.path.exists(f'/proc/{pid}'):
        return pid
    # Stale pidfile — clean up
    try:
        pidfile.unlink()
    except OSError:
        pass
    return None


@login_required
def search(request):
    """Form to launch a deep-chain GA search + status of any running one."""
    import os
    from django.contrib import messages
    from django.shortcuts import redirect

    if request.method == 'POST':
        active = _active_search_pid()
        if active:
            messages.warning(request,
                f'A search is already running (PID {active}).  Wait for it '
                f'to finish or stop it on the status page.')
            return redirect('ouroboros:search')

        def _ci(name, d, lo, hi):
            try: return max(lo, min(hi, int(request.POST.get(name, d))))
            except (TypeError, ValueError): return d
        mu      = _ci('mu',      4,   1,  16)
        lam     = _ci('lam',     6,   1,  32)
        gens    = _ci('gens',    30,  1, 500)
        target  = _ci('target',  64,  8, 1024)
        max_dep = _ci('max',     1024, 32, 16384)
        save_rl = _ci('save_runlen', OUROBOROS_RUNLEN_THRESHOLD, 50, 8000)

        import subprocess, sys
        from django.conf import settings

        log_dir = _search_log_dir()
        ts = time.strftime('%Y-%m-%d-%H%M%S')
        logfile = log_dir / f'search-{ts}.log'
        pidfile = log_dir / 'current.pid'
        latest_link = log_dir / 'latest.log'

        cmd = [sys.executable,
                str(settings.BASE_DIR / 'manage.py'),
                'deep_chain_search',
                '--mu', str(mu), '--lam', str(lam),
                '--gens', str(gens),
                '--target', str(target), '--max', str(max_dep),
                '--metric', 'arbsigma',
                '--save-runlen', str(save_rl)]
        with logfile.open('w') as f:
            f.write(f'# command: {" ".join(cmd)}\n')
            f.write(f'# started: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.flush()
            # Use PYTHONUNBUFFERED so Django's stdout flushes line-by-line
            env = dict(os.environ, PYTHONUNBUFFERED='1')
            proc = subprocess.Popen(
                cmd, stdout=f, stderr=subprocess.STDOUT,
                cwd=settings.BASE_DIR, env=env, start_new_session=True)
        pidfile.write_text(str(proc.pid))
        # Symlink latest.log → this log so the status tail always finds it.
        try:
            if latest_link.exists() or latest_link.is_symlink():
                latest_link.unlink()
            latest_link.symlink_to(logfile.name)
        except OSError:
            pass
        messages.success(request,
            f'Launched deep_chain_search (PID {proc.pid}): '
            f'μ={mu}+λ={lam}, gens={gens}, target {target}→{max_dep}, '
            f'save when run_length ≥ {save_rl}.')
        return redirect('ouroboros:search')

    # GET — render status + form
    active_pid = _active_search_pid()
    latest_log = _search_log_dir() / 'latest.log'
    log_tail = ''
    if latest_log.exists():
        try:
            txt = latest_log.read_text(errors='replace')
            lines = txt.splitlines()
            log_tail = '\n'.join(lines[-80:])
        except OSError:
            log_tail = ''

    # Count ouroboros-class rules already in the catalogue.
    from caformer.models import ComponentChampion
    ouro_rules: list = []
    for c in (ComponentChampion.objects
              .filter(component_slug=QUINE_SLUG)
              .only('pk', 'fitness', 'notes', 'rules_blob')
              .order_by('-pk')):
        m = _quine_meta(c)
        if is_ouroboros_class(m):
            ouro_rules.append({
                'pk':              c.pk,
                'sha':             _short_sha(bytes(c.rules_blob))
                                       if c.rules_blob else '',
                'fitness':         c.fitness or 0.0,
                'ga_run_length':   m.get('ga_run_length') or 0,
                'ga_distinct_levels': m.get('ga_distinct_levels') or 0,
                'arbsigma':        float(m.get('arbsigma') or 0.0),
                'display_name':    m.get('display_name') or '',
            })
    ouro_rules.sort(key=lambda r: -r['ga_run_length'])

    return render(request, 'ouroboros/search.html', {
        'active_pid':  active_pid,
        'log_tail':    log_tail,
        'ouro_rules':  ouro_rules,
        'thresholds': {
            'run_length':       OUROBOROS_RUNLEN_THRESHOLD,
            'distinct_levels':  OUROBOROS_DISTINCT_THRESHOLD,
        },
    })


@login_required
def search_stop(request):
    """Send SIGTERM to the running search subprocess."""
    import os, signal
    from django.contrib import messages
    from django.shortcuts import redirect

    pid = _active_search_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            messages.success(request, f'sent SIGTERM to PID {pid}')
        except OSError as e:
            messages.warning(request, f'failed to signal PID {pid}: {e}')
    else:
        messages.warning(request, 'no active search to stop')
    return redirect('ouroboros:search')


# ─── Cross-app handoffs ──────────────────────────────────────────────


def _default_palette_ansi() -> bytes:
    """4-byte ANSI-256 palette used when handing a quine off to apps
    that need one but don't have a saved palette themselves.  Matches
    the colours used in ouroboros's ruleset PNGs (vermilion/azure/
    verdant/amber)."""
    return bytes([196, 27, 35, 220])


@login_required
def to_taxon(request, pk: int):
    """Catalogue this ouroboros quine in Taxon as a hex_k4_lut Rule
    and redirect to its rule detail page in Taxon.  Idempotent on
    sha1 — re-clicking the same quine just reopens the existing rule
    and refreshes its classification."""
    from taxon.importers import upsert_hex_lut
    from taxon.models import Classification
    from spoeqi.metachain import (
        classify_rule, probe_activity, sr_arbitrary_sigma,
        self_reproduce_score, walk_chain)
    from django.shortcuts import redirect

    c = get_object_or_404(_quine_qs(), pk=pk)
    lut = bytes(c.rules_blob)
    meta = _quine_meta(c)
    name = meta.get('display_name') or f'ouroboros quine #{c.pk}'
    sref_bits = [f'ouroboros={c.pk}', f'sha={_short_sha(lut)}']
    if meta.get('origin'):
        sref_bits.append(f'origin={meta["origin"]}')
    rule = upsert_hex_lut(
        lut, _default_palette_ansi(),
        name=name, source='ouroboros',
        source_ref='; '.join(sref_bits),
    )

    # Classify the rule using the live metrics so the Taxon detail
    # shows it with the right Wolfram class + quine tags from the start.
    cls, c4 = classify_rule(lut, probe_ticks=16)
    act = probe_activity(lut, ticks=12)
    sr_strict = self_reproduce_score(lut, ticks=16)
    sr_arbs = sr_arbitrary_sigma(lut, ticks=16)
    sub_chain = walk_chain(lut, depth=20)
    Classification.objects.create(
        rule=rule, wolfram_class=int(cls),
        confidence=float(c4),
        basis_json={'c4': c4, 'activity': act,
                     'probe_ticks': 16, 'probe_size': 128,
                     'source': 'ouroboros->taxon'},
        is_quine=bool(sr_strict >= 0.30 or sr_arbs >= 0.85),
        sr_strict=float(sr_strict),
        sr_arbsigma=float(sr_arbs),
        nest_depth=int(sub_chain.get('class4_run_length', 0)),
        quine_origin=f'ouroboros #{c.pk}',
    )
    return redirect('taxon:rule_detail', slug=rule.slug)


@login_required
def to_automaton(request, pk: int):
    """Send this ouroboros quine to the Automaton as a runnable RuleSet
    + Simulation.  Packs the 16,384-byte LUT into HXC4 format
    (4-byte magic + 4-byte palette + 4,096-byte packed K=4 genome) and
    creates a RuleSet via the same code path as automaton's
    import-from-s3lab.  Idempotent on the packed sha1.
    """
    import random
    from django.contrib.auth.decorators import login_required as _li  # noqa
    from django.db import transaction
    from django.shortcuts import redirect
    from django.urls import reverse

    from automaton.models import RuleSet, ExactRule, Simulation
    from automaton.packed import (
        PackedRuleset, parse_genome_bin, encode_genome_bin,
        ansi256_to_hex,
    )
    from spoeqi.metachain import pack_k4_stream

    c = get_object_or_404(_quine_qs(), pk=pk)
    lut = bytes(c.rules_blob)
    if len(lut) != 16384:
        return HttpResponse(f'expected 16,384-byte LUT, got {len(lut)}',
                              status=400)
    packed_bytes = pack_k4_stream(lut)
    if len(packed_bytes) != 4096:
        return HttpResponse(
            f'packed K=4 stream is {len(packed_bytes)}B, expected 4096',
            status=500)
    palette_ansi = _default_palette_ansi()
    ruleset_obj = PackedRuleset(n_colors=4, data=packed_bytes)
    blob = encode_genome_bin(palette_ansi, ruleset_obj)
    _palette, packed = parse_genome_bin(blob)            # round-trip sanity
    blob_sha1 = hashlib.sha1(packed.data).hexdigest()

    existing = RuleSet.objects.filter(
        source_metadata__blob_sha1=blob_sha1).first()
    if existing:
        sim = existing.simulations.order_by('-created_at').first()
        if sim:
            return redirect('automaton:run', slug=sim.slug)
        return redirect('automaton:home')

    meta = _quine_meta(c)
    name = meta.get('display_name') or f'ouroboros #{c.pk}'
    palette_css = [ansi256_to_hex(idx) for idx in palette_ansi]
    explicit = packed.to_explicit(skip_identity=True)
    n_explicit = len(explicit)
    with transaction.atomic():
        ruleset = RuleSet.objects.create(
            name=name,
            description=(
                f'Sent from ouroboros (#{c.pk}, sha {blob_sha1[:10]}…). '
                f'{n_explicit} non-identity 7-tuples out of '
                f'{4**7:,}.'),
            n_colors=4,
            source='operator',
            palette=palette_css,
            source_metadata={
                'origin':           'imported',
                'source':           'ouroboros',
                'source_ref':       f'ouroboros={c.pk}',
                'blob_sha1':        blob_sha1,
                'palette_hex':      palette_ansi.hex(),
                'palette_ansi256':  list(palette_ansi),
                'palette_css':      palette_css,
                'n_explicit':       n_explicit,
            },
        )
        ExactRule.objects.bulk_create([
            ExactRule(
                ruleset=ruleset,
                self_color=er['s'],
                n0_color=er['n'][0], n1_color=er['n'][1],
                n2_color=er['n'][2], n3_color=er['n'][3],
                n4_color=er['n'][4], n5_color=er['n'][5],
                result_color=er['r'],
                priority=i,
            )
            for i, er in enumerate(explicit)
        ])
        sim_w, sim_h = 16, 16
        grid = [[random.randint(0, 3) for _ in range(sim_w)]
                for _ in range(sim_h)]
        sim = Simulation.objects.create(
            name=name, ruleset=ruleset,
            width=sim_w, height=sim_h,
            palette=palette_css, grid_state=grid,
        )
    return redirect('automaton:run', slug=sim.slug)


@login_required
def search_tail(request):
    """JSON endpoint for the status page to poll the latest log tail."""
    latest_log = _search_log_dir() / 'latest.log'
    txt = ''
    if latest_log.exists():
        try:
            data = latest_log.read_text(errors='replace')
            txt = '\n'.join(data.splitlines()[-120:])
        except OSError:
            txt = ''
    return JsonResponse({
        'active_pid': _active_search_pid(),
        'log_tail':   txt,
    })

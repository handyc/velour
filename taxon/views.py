from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import (
    HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from automaton.packed import (
    PackedRuleset, ansi256_to_hex, encode_genome_bin,
)

from . import exporters, importers
from .classifier import class_color, class_label, classify
from .engine import simulate
from .metrics import META as METRIC_META, list_metrics, run_all
from .models import (
    Agent, AutoSearch,
    Classification, EvolutionRun, MetricRun, Rule, WOLFRAM_CLASSES,
)


def _classification_summary():
    """Counts per Wolfram class across the latest classification per rule."""
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for rule in Rule.objects.all():
        c = rule.latest_classification
        if c:
            counts[c.wolfram_class] = counts.get(c.wolfram_class, 0) + 1
    return [
        {'n': n, 'label': class_label(n), 'count': counts.get(n, 0),
         'color': class_color(n)}
        for n in (1, 2, 3, 4)
    ]


def _rule_card(rule: Rule) -> dict:
    c = rule.latest_classification
    palette = rule.palette_hex
    return {
        'rule': rule,
        'palette': palette,
        'class_n': c.wolfram_class if c else None,
        'class_label': class_label(c.wolfram_class) if c else '—',
        'class_color': class_color(c.wolfram_class) if c else '#444',
        'class_conf': c.confidence if c else 0.0,
        'class_basis': c.basis_json if c else {},
    }


@login_required
def index(request):
    cards = [_rule_card(r) for r in
             Rule.objects.all().prefetch_related('classifications')[:24]]
    summary = _classification_summary()
    total = Rule.objects.count()
    classified = Classification.objects.values('rule').distinct().count()
    return render(request, 'taxon/index.html', {
        'cards': cards,
        'summary': summary,
        'total_rules': total,
        'classified': classified,
        'metrics': list_metrics(),
        'class_choices': [(n, lbl) for n, lbl in WOLFRAM_CLASSES],
    })


PAGE_SIZE = 60


def _paginate(request, qs):
    """Wrap a queryset in Django's Paginator using ?page= and our
    PAGE_SIZE. Returns (page_obj, querystring_for_page_links) where
    the querystring preserves all current GET params except `page`."""
    from django.core.paginator import Paginator
    paginator = Paginator(qs, PAGE_SIZE)
    page_num = request.GET.get('page', '1')
    try:
        page = paginator.page(int(page_num))
    except Exception:
        page = paginator.page(1)
    qd = request.GET.copy()
    qd.pop('page', None)
    qstr = qd.urlencode()
    qstr = (qstr + '&') if qstr else ''
    return page, qstr


@login_required
def library(request):
    from django.db.models import Q
    qs = Rule.objects.all()
    src = request.GET.get('source', '')
    if src:
        qs = qs.filter(source=src)
    q = (request.GET.get('q', '') or '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(slug__icontains=q) |
            Q(sha1__istartswith=q) | Q(source_ref__icontains=q)
        )
    sort = request.GET.get('sort', 'newest')
    if sort == 'oldest':
        qs = qs.order_by('created_at')
    elif sort == 'name':
        qs = qs.order_by('name', 'slug')
    else:
        qs = qs.order_by('-created_at')
    page, qstr = _paginate(request, qs.prefetch_related('classifications'))
    cards = [_rule_card(r) for r in page.object_list]
    sources = (Rule.objects.values('source')
               .annotate(c=Count('id')).order_by('-c'))
    return render(request, 'taxon/library.html', {
        'cards': cards,
        'sources': sources,
        'active_source': src,
        'q': q,
        'sort': sort,
        'total': page.paginator.count,
        'shown': len(cards),
        'page': page,
        'qstr': qstr,
    })


@login_required
def class_view(request, n: int):
    if n not in (1, 2, 3, 4):
        return HttpResponseBadRequest('class must be 1, 2, 3, or 4')
    # Latest-classification-per-rule with that wolfram_class. Single
    # SQL pass via Subquery — was N+1 (one query per rule × 500+ rules).
    from django.db.models import Subquery, OuterRef
    latest_per_rule = (Classification.objects
                       .filter(rule=OuterRef('pk'))
                       .order_by('-assigned_at'))
    sort = request.GET.get('sort', 'newest')
    src  = request.GET.get('source', '')
    qs = (Rule.objects
          .annotate(latest_class=Subquery(
              latest_per_rule.values('wolfram_class')[:1]))
          .filter(latest_class=n))
    if src:
        qs = qs.filter(source=src)
    if sort == 'oldest':
        qs = qs.order_by('created_at')
    elif sort == 'name':
        qs = qs.order_by('name', 'slug')
    else:
        qs = qs.order_by('-created_at')
    qs = qs.prefetch_related('classifications')
    page, qstr = _paginate(request, qs)
    cards = [_rule_card(r) for r in page.object_list]
    sources = (Rule.objects
               .annotate(latest_class=Subquery(latest_per_rule.values('wolfram_class')[:1]))
               .filter(latest_class=n)
               .values('source').annotate(c=Count('id')).order_by('-c'))
    return render(request, 'taxon/class.html', {
        'n': n,
        'label': class_label(n),
        'color': class_color(n),
        'cards': cards,
        'class_choices': [(c, lbl) for c, lbl in WOLFRAM_CLASSES],
        'page': page,
        'qstr': qstr,
        'sort': sort,
        'sources': sources,
        'active_source': src,
        'total': page.paginator.count,
        'shown': len(cards),
    })


@login_required
def metrics_view(request):
    """Metrics page — table of metric definitions plus a configurable
    scatter coloured by Wolfram class. ?x= and ?y= each pick one of
    the five metrics; defaults are langton_lambda × activity_rate.
    Each rule contributes its *latest* measurement of the chosen
    metrics; the most recent Classification colours the dot."""
    metrics_meta = {m['name']: m for m in list_metrics()}

    x_metric = request.GET.get('x', 'langton_lambda')
    y_metric = request.GET.get('y', 'activity_rate')
    if x_metric not in metrics_meta:
        x_metric = 'langton_lambda'
    if y_metric not in metrics_meta:
        y_metric = 'activity_rate'
    x_meta = metrics_meta[x_metric]
    y_meta = metrics_meta[y_metric]

    # One pass per axis. Order by computed_at so the dict ends up
    # holding the newest value per rule.
    needed = {x_metric, y_metric}
    latest = {}
    for mr in (MetricRun.objects
               .filter(metric__in=needed)
               .order_by('computed_at')
               .values('rule_id', 'metric', 'value')):
        latest.setdefault(mr['rule_id'], {})[mr['metric']] = mr['value']

    # Latest classification per rule.
    cls = {}
    for c in (Classification.objects
              .order_by('assigned_at')
              .values('rule_id', 'wolfram_class')):
        cls[c['rule_id']] = c['wolfram_class']

    # Map rule_id → slug so each dot can link to its detail page.
    slugs = dict(Rule.objects.values_list('id', 'slug'))

    # SVG plot geometry — fixed pixel area; the *data* domain comes
    # from each axis metric's range_hint.
    PLOT_X0, PLOT_X1 = 60, 620
    PLOT_Y0, PLOT_Y1 = 30, 480
    plot_w = PLOT_X1 - PLOT_X0
    plot_h = PLOT_Y1 - PLOT_Y0

    x_min, x_max = x_meta['range']
    y_min, y_max = y_meta['range']
    x_span = (x_max - x_min) or 1.0
    y_span = (y_max - y_min) or 1.0

    points = []
    for rid, vals in latest.items():
        xv = vals.get(x_metric)
        yv = vals.get(y_metric)
        if xv is None or yv is None:
            continue
        slug = slugs.get(rid)
        if slug is None:
            continue
        n = cls.get(rid)
        # Clamp to declared range; outliers pin to the edge rather than
        # exit the plot area.
        xc = max(x_min, min(x_max, float(xv)))
        yc = max(y_min, min(y_max, float(yv)))
        cx = PLOT_X0 + (xc - x_min) / x_span * plot_w
        cy = PLOT_Y1 - (yc - y_min) / y_span * plot_h
        points.append({
            'slug': slug,
            'xv':   xv, 'yv': yv,
            'class_n': n,
            'color':   class_color(n) if n else '#586069',
            'cx': round(cx, 1),
            'cy': round(cy, 1),
        })

    # Pre-bake five evenly-spaced ticks for each axis so the template
    # doesn't have to do arithmetic.
    def axis_ticks(lo, hi, plot_lo, plot_hi, axis):
        out = []
        for i in range(5):
            f = i / 4.0
            v = lo + f * (hi - lo)
            px = plot_lo + f * (plot_hi - plot_lo)
            # Format: drop trailing zeros, keep small floats readable.
            if abs(v) >= 10:
                lbl = f'{v:.0f}'
            elif abs(v - round(v)) < 1e-9:
                lbl = f'{v:.1f}'
            else:
                lbl = f'{v:.2f}'
            out.append({'pos': round(px, 1), 'label': lbl})
        return out

    x_ticks = axis_ticks(x_min, x_max, PLOT_X0, PLOT_X1, 'x')
    # Y axis ticks: visual top is y=1 (high value); we built [0..4]
    # bottom-up, so reverse positions for display.
    y_ticks_raw = axis_ticks(y_min, y_max, PLOT_Y0, PLOT_Y1, 'y')
    # Flip y so the highest data value is at the top of the plot.
    y_ticks = [{'pos': PLOT_Y0 + PLOT_Y1 - t['pos'], 'label': t['label']}
               for t in y_ticks_raw]

    # Per-class counts + pre-baked y-positions for the SVG legend. The
    # legend sits inside the plot area at top-right; rows are 20 px apart.
    LEGEND_X0, LEGEND_Y0, ROW_H = 490, 50, 20
    legend = []
    for i, n in enumerate((1, 2, 3, 4, None)):
        legend.append({
            'n': n,
            'label': class_label(n) if n else 'unclassified',
            'color': class_color(n) if n else '#586069',
            'count': sum(1 for p in points if p['class_n'] == n),
            'cy':   LEGEND_Y0 + i * ROW_H,
            'ty':   LEGEND_Y0 + i * ROW_H + 4,    # text baseline shim
        })
    legend_box = {
        'x': LEGEND_X0 - 10,
        'y': LEGEND_Y0 - 14,
        'w': 130,
        'h': len(legend) * ROW_H + 6,
    }

    return render(request, 'taxon/metrics.html', {
        'metrics': list_metrics(),
        'points': points,
        'legend': legend,
        'legend_box': legend_box,
        'total_points': len(points),
        'x_meta': x_meta, 'y_meta': y_meta,
        'x_metric': x_metric, 'y_metric': y_metric,
        'x_ticks': x_ticks, 'y_ticks': y_ticks,
    })


@login_required
def runs_view(request):
    """List of past evolution runs (browser-driven GA sessions saved
    via /taxon/evolve/save/). Newest first."""
    runs = (EvolutionRun.objects
            .select_related('seed_rule', 'best_rule')
            .order_by('-started_at')[:200])
    return render(request, 'taxon/runs.html', {
        'runs': runs,
        'total': EvolutionRun.objects.count(),
        'shown': len(runs),
    })


@login_required
def rule_detail(request, slug: str):
    rule = get_object_or_404(Rule, slug=slug)
    card = _rule_card(rule)

    # Latest metric per name, plus history.
    metrics_table = []
    for meta in list_metrics():
        run = rule.latest_metric(meta['name'])
        metrics_table.append({
            'meta': meta,
            'run': run,
            'value': run.value if run else None,
            'extra': run.extra_json if run else {},
        })

    # All classifications (history) + latest.
    classifications = list(rule.classifications.all()[:8])

    agents = list(rule.agents.all())
    return render(request, 'taxon/detail.html', {
        'rule': rule,
        'card': card,
        'metrics_table': metrics_table,
        'classifications': classifications,
        'genome_hex_preview': bytes(rule.genome).hex()[:96],
        'genome_hex_full': bytes(rule.genome).hex(),
        'palette_hex': rule.palette_hex,
        'class_choices': [(n, lbl) for n, lbl in WOLFRAM_CLASSES],
        'agents': agents,
    })


COMPARE_MAX = 6


@login_required
def compare_view(request):
    """Side-by-side hex-CA preview of N rules running in lockstep on the
    same seed. Slugs are passed via ?slugs=a,b,c (also accepted via
    repeated ?slug=a&slug=b for form-style submission). Restricted to
    K=4 packed-positional rules so a single browser-side engine handles
    the whole panel."""
    raw = request.GET.get('slugs', '')
    slugs = [s for s in raw.split(',') if s]
    slugs += request.GET.getlist('slug')
    seen = set()
    slugs = [s for s in slugs if not (s in seen or seen.add(s))][:COMPARE_MAX]

    rules_by_slug = {r.slug: r for r in Rule.objects.filter(slug__in=slugs)}
    panels = []
    skipped = []
    for s in slugs:
        rule = rules_by_slug.get(s)
        if rule is None:
            skipped.append({'slug': s, 'why': 'not found'})
            continue
        if rule.kind != 'hex_k4_packed':
            skipped.append({'slug': s, 'why': f'kind={rule.kind} (only K=4 packed)'})
            continue
        c = rule.latest_classification
        panels.append({
            'rule': rule,
            'palette_hex': rule.palette_hex,
            'genome_hex_full': bytes(rule.genome).hex(),
            'class_n': c.wolfram_class if c else None,
            'class_label': class_label(c.wolfram_class) if c else '—',
            'class_color': class_color(c.wolfram_class) if c else '#444',
        })
    return render(request, 'taxon/compare.html', {
        'panels': panels,
        'skipped': skipped,
        'compare_max': COMPARE_MAX,
        'slugs_csv': ','.join(p['rule'].slug for p in panels),
    })


@login_required
@require_POST
def rule_edit(request, slug: str):
    """Update a rule's display name + notes. Lets the user tag a rule
    with whatever it reminds them of ("snowfall17", "marching ants",
    "feels like Conway"). Doesn't touch genome / palette / sha1."""
    rule = get_object_or_404(Rule, slug=slug)
    name = (request.POST.get('name', '') or '').strip()[:120]
    notes = (request.POST.get('notes', '') or '').strip()
    rule.name = name
    rule.notes = notes
    rule.save(update_fields=['name', 'notes'])
    return redirect('taxon:rule_detail', slug=slug)


@login_required
def rule_preview_png(request, slug: str):
    """Tiny PNG thumbnail of the rule's CA after a brief simulation —
    drives the card thumbnails on /taxon/library/, /taxon/classes/, and
    /taxon/. Cached in Django's default cache for an hour. K=4 packed
    rules render in ~2 ms; K=256 HexNN rules in ~100 ms (one-time cost
    paid once per rule per cache TTL).
    """
    from io import BytesIO

    from django.core.cache import cache
    from django.utils.cache import patch_response_headers
    from PIL import Image

    rule = get_object_or_404(Rule, slug=slug)
    cache_key = f'taxon-preview-{rule.sha1}'
    cached = cache.get(cache_key)
    if cached is None:
        size = 16
        ticks = 24
        seed = 42
        if rule.kind == 'hex_k4_packed':
            packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
            traj, _hashes = simulate(packed, size, size, ticks, seed)
            grid = traj[-1]
            palette = list(bytes(rule.palette_ansi))[:4]
            from automaton.packed import ansi256_to_rgb
            pal_rgb = [ansi256_to_rgb(p) for p in palette]
        else:
            from .hexnn import HexNNRuleset, simulate as hexnn_simulate, unpack_hexnn
            from automaton.packed import ansi256_to_rgb
            K, keys, outs = unpack_hexnn(bytes(rule.genome))
            ruleset = HexNNRuleset(K, keys, outs)
            traj, _hashes = hexnn_simulate(ruleset, size, size, ticks, seed)
            grid = traj[-1]
            palette = list(bytes(rule.palette_ansi))[:K]
            pal_rgb = [ansi256_to_rgb(p) for p in palette]
        # Render to a 64×64 PIL Image, scale 4× per cell.
        scale = 4
        img = Image.new('RGB', (size * scale, size * scale))
        px = img.load()
        for y in range(size):
            for x in range(size):
                v = int(grid[y, x]) if hasattr(grid, 'shape') else grid[y * size + x]
                v = v % len(pal_rgb)
                r, g, b = pal_rgb[v]
                for dy in range(scale):
                    for dx in range(scale):
                        px[x * scale + dx, y * scale + dy] = (r, g, b)
        buf = BytesIO()
        img.save(buf, format='PNG', optimize=True)
        cached = buf.getvalue()
        cache.set(cache_key, cached, timeout=3600)
    resp = HttpResponse(cached, content_type='image/png')
    patch_response_headers(resp, cache_timeout=3600)
    return resp


@login_required
def rule_download(request, slug: str):
    """Emit the 4,104-byte HXC4 genome.bin for round-trip to s3lab/ESP."""
    rule = get_object_or_404(Rule, slug=slug)
    if rule.kind != 'hex_k4_packed':
        return HttpResponseBadRequest('only K=4 packed rules export to HXC4')
    packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
    blob = encode_genome_bin(bytes(rule.palette_ansi), packed)
    resp = HttpResponse(blob, content_type='application/octet-stream')
    resp['Content-Disposition'] = (
        f'attachment; filename="{rule.slug}.genome.bin"'
    )
    return resp


@login_required
@require_POST
def rule_classify(request, slug: str):
    """Re-run metrics + classifier for one rule.

    HXC4 K=4 packed rules use the existing K=4 simulator + metrics.
    HexNN K-dialable rules go through taxon.hexnn (different genome
    shape, different langton-λ definition); horizon + grid default
    smaller since K=256 simulation is per-step expensive.
    """
    from .models import KIND_HEX_NN
    rule = get_object_or_404(Rule, slug=slug)

    if rule.kind == KIND_HEX_NN:
        from .hexnn import HexNNRuleset, langton_lambda_hexnn, simulate as hexnn_simulate, unpack_hexnn
        from .metrics import REGISTRY
        horizon = int(request.POST.get('horizon', 40))
        grid    = int(request.POST.get('grid', 12))
        seed    = int(request.POST.get('seed', 42))
        K, keys, outs = unpack_hexnn(bytes(rule.genome))
        ruleset = HexNNRuleset(K, keys, outs)
        traj, hashes = hexnn_simulate(ruleset, grid, grid, horizon, seed)
        mvals: dict[str, float] = {}
        for name, fn in REGISTRY.items():
            if name == 'langton_lambda':
                val, extra = langton_lambda_hexnn(ruleset)
            else:
                val, extra = fn(traj, hashes, ruleset)
            MetricRun.objects.create(
                rule=rule, metric=name, value=val,
                grid_w=grid, grid_h=grid, horizon=horizon, seed=seed,
                extra_json=extra,
            )
            mvals[name] = val
        cls, conf, basis = classify(mvals, horizon=horizon, n_colors=K)
        Classification.objects.create(
            rule=rule, wolfram_class=cls, confidence=conf, basis_json=basis,
        )
        return redirect('taxon:rule_detail', slug=slug)

    horizon = int(request.POST.get('horizon', 120))
    grid    = int(request.POST.get('grid', 24))
    seed    = int(request.POST.get('seed', 42))
    packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
    traj, hashes = simulate(packed, grid, grid, horizon, seed)
    results = run_all(traj, hashes, packed)
    mvals = {}
    for name, (val, extra) in results.items():
        MetricRun.objects.create(
            rule=rule, metric=name, value=val,
            grid_w=grid, grid_h=grid, horizon=horizon, seed=seed,
            extra_json=extra,
        )
        mvals[name] = val
    cls, conf, basis = classify(mvals, horizon=horizon)
    Classification.objects.create(
        rule=rule, wolfram_class=cls, confidence=conf, basis_json=basis,
    )
    return redirect('taxon:rule_detail', slug=slug)


@login_required
@require_POST
def rule_delete(request, slug: str):
    rule = get_object_or_404(Rule, slug=slug)
    rule.delete()
    return redirect('taxon:library')


def _random_palette(K: int = 4) -> bytes:
    """Pick K distinct ANSI-256 indices, biased toward the 6×6×6 colour
    cube the way s3lab's invent_palette does (90% cube, 10% greys)."""
    import random as _random
    seen: set[int] = set()
    out = bytearray()
    while len(out) < K:
        if _random.random() < 0.9:
            idx = 16 + _random.randrange(216)
        else:
            idx = 232 + _random.randrange(24)
        if idx in seen:
            continue
        seen.add(idx)
        out.append(idx)
    return bytes(out)


def _unique_agent_slug(base: str) -> str:
    base = base[:96] or 'agent'
    candidate = base
    n = 2
    while Agent.objects.filter(slug=candidate).exists():
        candidate = f'{base[:92]}-{n}'
        n += 1
    return candidate


@login_required
@require_POST
def rule_reroll_palette(request, slug: str):
    """Create a new Agent (Ruleset + fresh random palette) and
    immediately promote it to the rule's default — so the visible
    palette swatches at the top of the detail page change right away.
    Previous Agents stay as alternates the user can flip back to via
    the Agents section. Genome is unchanged (Rule is sha1-addressed
    by its genome bytes). HexNN rules get K=256 fresh ANSI indices,
    K=4 packed get 4."""
    rule = get_object_or_404(Rule, slug=slug)
    K = max(2, int(rule.n_colors or 4))
    palette = _random_palette(K)
    n_existing = rule.agents.count()
    new_agent = Agent.objects.create(
        slug=_unique_agent_slug(f'{rule.slug}-agent-{n_existing + 1:03d}'),
        name=f'{rule.name or rule.slug} agent #{n_existing + 1}',
        rule=rule,
        palette_ansi=palette,
        is_default=True,
    )
    # Demote the previous default(s) and mirror the new palette into
    # the rule's denormalised default cache.
    Agent.objects.filter(rule=rule, is_default=True).exclude(pk=new_agent.pk).update(is_default=False)
    rule.palette_ansi = palette
    rule.save(update_fields=['palette_ansi'])
    return redirect('taxon:rule_detail', slug=slug)


@login_required
@require_POST
def agent_make_default(request, slug: str):
    """Promote this Agent to be its rule's default — its palette is
    mirrored into Rule.palette_ansi (drives downloads, device pushes,
    cards) and the previous default loses the flag."""
    agent = get_object_or_404(Agent, slug=slug)
    rule = agent.rule
    Agent.objects.filter(rule=rule, is_default=True).update(is_default=False)
    agent.is_default = True
    agent.save(update_fields=['is_default'])
    rule.palette_ansi = bytes(agent.palette_ansi)
    rule.save(update_fields=['palette_ansi'])
    return redirect('taxon:rule_detail', slug=rule.slug)


@login_required
@require_POST
def agent_delete(request, slug: str):
    """Remove an Agent. Refused if it's the rule's only Agent or the
    current default (promote another first)."""
    agent = get_object_or_404(Agent, slug=slug)
    rule_slug = agent.rule.slug
    siblings = agent.rule.agents.exclude(pk=agent.pk).count()
    if agent.is_default or siblings == 0:
        return HttpResponseBadRequest(
            'cannot delete the default agent or the only agent — '
            'promote another to default first'
        )
    agent.delete()
    return redirect('taxon:rule_detail', slug=rule_slug)


@login_required
@require_POST
def rule_to_automaton(request, slug: str):
    """Build an automaton.Simulation from this Taxon Rule and redirect
    to its run page. Idempotent on sha1 — re-running on the same rule
    re-uses the existing RuleSet and lands on its most recent Sim."""
    rule = get_object_or_404(Rule, slug=slug)
    try:
        sim = exporters.to_automaton(rule)
    except ValueError as e:
        return HttpResponseBadRequest(str(e))
    return redirect('automaton:run', slug=sim.slug)


@login_required
def rule_to_s3lab(request, slug: str):
    """Open this Taxon Rule in the s3lab Classic sublab. Bounces to
    /s3lab/?from_taxon=<slug>; the classic JS sublab fetches our
    genome.bin and applies it as the live genome."""
    rule = get_object_or_404(Rule, slug=slug)
    return redirect(f'/s3lab/?from_taxon={rule.slug}')


@login_required
@require_POST
def rule_to_device(request, slug: str):
    """Push this rule's HXC4 genome to a hexca supermini's /load-genome.

    Velour-side proxy avoids the browser's cross-origin block; default
    device URL is http://hexca.local. Returns JSON {ok, target, status,
    body, elapsed_ms}.
    """
    import time
    import urllib.error
    import urllib.request

    from automaton.packed import PackedRuleset, encode_genome_bin

    rule = get_object_or_404(Rule, slug=slug)
    if rule.kind != 'hex_k4_packed':
        return JsonResponse({'ok': False,
            'error': 'only K=4 packed rules can be pushed to a hexca device'})

    device_url = (request.POST.get('device_url') or
                  'http://hexca.local').rstrip('/')
    target = f'{device_url}/load-genome'
    packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
    blob = encode_genome_bin(bytes(rule.palette_ansi), packed)
    req = urllib.request.Request(
        target, data=blob, method='POST',
        headers={'Content-Type': 'application/octet-stream'},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
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


@login_required
def import_view(request):
    """Upload a HXC4 4104-byte K=4 genome OR a strateta-population
    JSON / .json.gz bundle. Format autodetected from the first bytes:
    HXC4 starts with 'HXC4' magic; gzip starts with 0x1F 0x8B; raw
    JSON starts with '{'.

    HXC4 → one Rule, classified inline.
    strateta-population-v1 → up to LIB_SIZE Rules (kind=hex_nn),
    classified at the smaller 12×12 × 40-tick budget the
    taxon_import_strateta command uses (K=256 simulation is heavier).
    """
    err = None
    summary = None
    if request.method == 'POST':
        f = request.FILES.get('hxc4')
        if not f:
            err = 'No file uploaded.'
        else:
            try:
                blob = f.read()
                # Format autodetect.
                fmt = _detect_upload_format(blob)
                if fmt == 'hxc4':
                    rule = importers.import_hxc4_blob(
                        blob,
                        name=request.POST.get('name', '') or f.name,
                        source=request.POST.get('source', 'manual') or 'manual',
                        source_ref=f.name,
                    )
                    packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
                    traj, hashes = simulate(packed, 24, 24, 120, 42)
                    results = run_all(traj, hashes, packed)
                    mvals = {}
                    for name, (val, extra) in results.items():
                        MetricRun.objects.create(
                            rule=rule, metric=name, value=val,
                            extra_json=extra,
                        )
                        mvals[name] = val
                    cls, conf, basis = classify(mvals)
                    Classification.objects.create(
                        rule=rule, wolfram_class=cls, confidence=conf,
                        basis_json=basis,
                    )
                    return redirect('taxon:rule_detail', slug=rule.slug)
                elif fmt == 'strateta-population':
                    summary = _import_strateta_population_blob(blob, f.name)
                else:
                    err = ('Unrecognised file. Expected a HXC4 4104-byte '
                           'genome.bin OR a strateta-population JSON / '
                           '.json.gz bundle.')
            except Exception as e:
                err = str(e)
    return render(request, 'taxon/import.html', {
        'err': err,
        'summary': summary,
        'source_choices': [
            ('manual', 'Manual upload'),
            ('s3lab', 'S3 Lab'),
            ('automaton', 'Automaton'),
            ('helix', 'Helix Hex Hunt'),
            ('stratum', 'S3 Lab Stratum'),
        ],
    })


def _detect_upload_format(blob: bytes) -> str:
    """Sniff first bytes — return 'hxc4', 'strateta-population', or
    'unknown'. HXC4 files start with the 'HXC4' tail magic; gzipped
    JSON starts with 0x1F 0x8B; raw JSON starts with '{' (after
    optional whitespace)."""
    if len(blob) >= 4 and blob[:4] == b'HXC4':
        return 'hxc4'
    if len(blob) >= 2 and blob[:2] == b'\x1f\x8b':
        return 'strateta-population'   # treat all gzipped uploads as JSON
    head = blob.lstrip()[:1]
    if head == b'{':
        return 'strateta-population'
    return 'unknown'


def _import_strateta_population_blob(blob: bytes, fname: str) -> dict:
    """Decode + import a strateta-population[.gz] blob; classify each
    new rule. Returns a dict with counts + class distribution suitable
    for the import.html summary box."""
    import gzip
    import json
    from collections import Counter

    from . import autosearch as _ignored  # noqa — keeps mark_orphans nearby
    from .hexnn import HexNNRuleset, langton_lambda_hexnn, simulate as hexnn_simulate, unpack_hexnn
    from .metrics import REGISTRY

    raw = blob
    if len(raw) >= 2 and raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode('utf-8'))
    if payload.get('format') != 'strateta-population-v1':
        raise ValueError(
            f'not a strateta-population-v1 file (got {payload.get("format")!r})')

    rules = importers.import_strateta_population(
        payload, source='strateta', source_ref=f'file={fname}')

    grid, horizon, seed = 12, 40, 42
    cls_counts: Counter[int] = Counter()
    for rule in rules:
        K, keys, outs = unpack_hexnn(bytes(rule.genome))
        ruleset = HexNNRuleset(K, keys, outs)
        traj, hashes = hexnn_simulate(ruleset, grid, grid, horizon, seed)
        mvals: dict[str, float] = {}
        for name, fn in REGISTRY.items():
            if name == 'langton_lambda':
                val, extra = langton_lambda_hexnn(ruleset)
            else:
                val, extra = fn(traj, hashes, ruleset)
            MetricRun.objects.create(
                rule=rule, metric=name, value=val,
                grid_w=grid, grid_h=grid, horizon=horizon, seed=seed,
                extra_json=extra,
            )
            mvals[name] = val
        cls, conf, basis = classify(mvals, horizon=horizon, n_colors=K)
        Classification.objects.create(
            rule=rule, wolfram_class=cls, confidence=conf, basis_json=basis,
        )
        cls_counts[cls] += 1

    return {
        'fmt':           'strateta-population-v1',
        'fname':         fname,
        'imported':      len(rules),
        'K':             payload.get('K'),
        'class_counts':  sorted(cls_counts.items()),
        'first_slug':    rules[0].slug if rules else None,
    }


@login_required
def evolve_view(request):
    """Browser-driven GA evolving toward a target Wolfram class.

    The actual evolution runs in JS for fast iteration; this view
    serves the UI plus a starting genome (random or seeded from an
    existing rule).
    """
    seed_slug = request.GET.get('seed')
    seed_rule = None
    if seed_slug:
        seed_rule = Rule.objects.filter(slug=seed_slug).first()

    if seed_rule:
        seed_hex = bytes(seed_rule.genome).hex()
        seed_palette = list(bytes(seed_rule.palette_ansi))
    else:
        seed_hex = ''  # JS will random-init
        seed_palette = [0, 9, 11, 13]

    return render(request, 'taxon/evolve.html', {
        'seed_rule': seed_rule,
        'seed_hex': seed_hex,
        'seed_palette_json': json.dumps(seed_palette),
        'target_classes': [(n, lbl) for n, lbl in WOLFRAM_CLASSES],
        'metrics': list_metrics(),
    })


@login_required
@require_POST
def evolve_save(request):
    """Receive an elite genome from the in-browser GA and store it."""
    genome_hex = request.POST.get('genome_hex', '').strip()
    palette_csv = request.POST.get('palette', '0,9,11,13')
    name = request.POST.get('name', '').strip() or 'evolved'
    target_class = request.POST.get('target_class', '')
    fitness = request.POST.get('fitness', '0')
    generations = request.POST.get('generations', '0')
    fitness_curve = request.POST.get('fitness_curve', '[]')

    try:
        genome = bytes.fromhex(genome_hex)
        if len(genome) != 4096:
            return HttpResponseBadRequest('genome must be 4096 bytes')
        palette = bytes(int(x) & 0xFF for x in palette_csv.split(','))[:4]
        if len(palette) < 4:
            palette = palette + bytes(4 - len(palette))
    except Exception as e:
        return HttpResponseBadRequest(f'bad genome/palette: {e}')

    rule = importers.upsert(
        genome, palette,
        name=name, source='evolve',
        source_ref=f'target_class={target_class}; gen={generations}; fit={fitness}',
    )

    # Classify it on save so the library card has a class immediately.
    packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
    traj, hashes = simulate(packed, 24, 24, 120, 42)
    results = run_all(traj, hashes, packed)
    mvals = {}
    for n, (val, extra) in results.items():
        MetricRun.objects.create(
            rule=rule, metric=n, value=val, extra_json=extra,
        )
        mvals[n] = val
    cls, conf, basis = classify(mvals)
    Classification.objects.create(
        rule=rule, wolfram_class=cls, confidence=conf, basis_json=basis,
    )

    # Log the EvolutionRun.
    try:
        curve = json.loads(fitness_curve)
    except Exception:
        curve = []
    er = EvolutionRun(
        slug=f'er-{rule.slug}',
        name=f'evolve → {name}',
        target_kind='class',
        target_class=int(target_class) if target_class.isdigit() else None,
        generations=int(generations) if str(generations).isdigit() else 0,
        best_rule=rule,
        best_fitness=float(fitness or 0),
        fitness_curve=curve[:200],
    )
    # Make the slug unique.
    base = er.slug
    n = 2
    while EvolutionRun.objects.filter(slug=er.slug).exists():
        er.slug = f'{base}-{n}'
        n += 1
    er.save()

    return JsonResponse({
        'ok': True,
        'slug': rule.slug,
        'detail_url': reverse('taxon:rule_detail', args=[rule.slug]),
    })


# ── AutoSearch: background hunt for target-class rules ─────────────

@login_required
def autosearch_view(request, slug: str = None):
    """Page that launches + monitors background searches.

    With no slug: shows the form + recent runs. With ?slug present
    (the autosearch_detail URL): same page, but pre-watches the named
    run via a data attribute so a refresh lands back on the same view.
    """
    from . import autosearch
    autosearch.mark_orphans()
    recent = AutoSearch.objects.all()[:20]
    watch = None
    if slug:
        watch = get_object_or_404(AutoSearch, slug=slug)
    return render(request, 'taxon/autosearch.html', {
        'wolfram_classes': WOLFRAM_CLASSES,
        'recent_searches': recent,
        'active_count': AutoSearch.objects
            .filter(status__in=(AutoSearch.STATUS_QUEUED,
                                 AutoSearch.STATUS_RUNNING))
            .count(),
        'watch_slug': watch.slug if watch else '',
    })


@login_required
@require_POST
def autosearch_start(request):
    """Create + launch a new search. Returns JSON with the slug so the
    page can pivot into polling it."""
    from . import autosearch as autosearch_mod

    def _int(name, default, lo=None, hi=None):
        try:
            v = int(request.POST.get(name, default))
        except (TypeError, ValueError):
            v = default
        if lo is not None and v < lo: v = lo
        if hi is not None and v > hi: v = hi
        return v

    def _float(name, default, lo=None, hi=None):
        try:
            v = float(request.POST.get(name, default))
        except (TypeError, ValueError):
            v = default
        if lo is not None and v < lo: v = lo
        if hi is not None and v > hi: v = hi
        return v

    target_class = _int('target_class', 4, 1, 4)
    seed_strategy = request.POST.get('seed_strategy', AutoSearch.SEED_HYBRID)
    if seed_strategy not in dict(AutoSearch.SEED_CHOICES):
        seed_strategy = AutoSearch.SEED_HYBRID

    search = AutoSearch.objects.create(
        slug=autosearch_mod.make_slug(target_class),
        name=request.POST.get('name', '').strip()[:120],
        target_class=target_class,
        target_min_confidence=_float('min_confidence', 0.6, 0.0, 1.0),
        seed_strategy=seed_strategy,
        mutation_rate=_float('mutation_rate', 0.005, 0.0, 0.1),
        grid=_int('grid', 24, 8, 64),
        horizon=_int('horizon', 120, 20, 600),
        seed=_int('seed', 42, 0, (1 << 31) - 1),
        max_seconds=_int('max_seconds', 300, 5, 7200),
        max_found=_int('max_found', 20, 1, 1000),
    )
    autosearch_mod.launch(search)
    return JsonResponse({
        'ok': True,
        'slug': search.slug,
        'status_url': reverse('taxon:autosearch_status', args=[search.slug]),
    })


@login_required
@require_POST
def autosearch_stop(request, slug: str):
    from . import autosearch as autosearch_mod
    search = get_object_or_404(AutoSearch, slug=slug)
    autosearch_mod.request_stop(search)
    return JsonResponse({'ok': True, 'slug': slug})


@login_required
def autosearch_list_json(request):
    """JSON list of recent AutoSearches — drives the live-update of
    the recent-searches table on /taxon/autosearch/."""
    from . import autosearch as autosearch_mod
    autosearch_mod.mark_orphans()
    rows = []
    for s in AutoSearch.objects.all()[:20]:
        rows.append({
            'slug':         s.slug,
            'target_class': s.target_class,
            'status':       s.status,
            'status_label': s.get_status_display(),
            'tried':        s.rules_tried,
            'kept':         s.rules_kept,
            'started_at':   s.started_at.isoformat() if s.started_at else None,
            'detail_url':   reverse('taxon:autosearch_detail', args=[s.slug]),
            'is_active':    s.is_active,
        })
    active_count = (AutoSearch.objects
        .filter(status__in=(AutoSearch.STATUS_QUEUED,
                             AutoSearch.STATUS_RUNNING))
        .count())
    return JsonResponse({'recent': rows, 'active_count': active_count})


@login_required
def autosearch_status(request, slug: str):
    """Polled by the browser every N seconds. Returns the search row's
    fields plus the most recent matched rules."""
    from . import autosearch as autosearch_mod
    autosearch_mod.mark_orphans()
    search = get_object_or_404(AutoSearch, slug=slug)
    recent = (Rule.objects
              .filter(source_ref__contains=f'autosearch={slug}')
              .order_by('-created_at')[:10])
    rules = []
    for r in recent:
        latest = r.classifications.order_by('-assigned_at').first()
        rules.append({
            'slug': r.slug,
            'name': r.name,
            'sha1': r.sha1[:10],
            'detail_url': reverse('taxon:rule_detail', args=[r.slug]),
            'class_n': latest.wolfram_class if latest else None,
            'class_label': class_label(latest.wolfram_class) if latest else '—',
            'class_color': class_color(latest.wolfram_class) if latest else '#888',
            'confidence': latest.confidence if latest else 0.0,
            'palette_hex': r.palette_hex,
        })
    rate = 0.0
    if search.last_heartbeat and search.started_at:
        secs = max(0.001, (search.last_heartbeat - search.started_at).total_seconds())
        rate = search.rules_tried / secs
    return JsonResponse({
        'slug': search.slug,
        'status': search.status,
        'status_label': search.get_status_display(),
        'is_active': search.is_active,
        'tried': search.rules_tried,
        'kept': search.rules_kept,
        'target_class': search.target_class,
        'target_class_label': class_label(search.target_class),
        'target_class_color': class_color(search.target_class),
        'rate_per_sec': rate,
        'last_log': search.last_log,
        'last_heartbeat': search.last_heartbeat.isoformat() if search.last_heartbeat else None,
        'started_at': search.started_at.isoformat() if search.started_at else None,
        'finished_at': search.finished_at.isoformat() if search.finished_at else None,
        'max_found': search.max_found,
        'max_seconds': search.max_seconds,
        'recent_rules': rules,
    })


# ---------------------------------------------------------------------------
# Wang-tile + CA buffer-band composition lab
# ---------------------------------------------------------------------------

@login_required
def wang_view(request):
    """Page that lets you pick a rule + parameters and run the experiment
    in the browser. Defaults pick a class-2 rule with a single-cell still
    life on color 1 — that's the easiest path to a successful run."""
    from .wang import MODES

    # Surface a few good starting points: rules that are quiescent on
    # zero AND have at least one single-cell still-life colour. Tagged
    # with their Wolfram class so the picker can sort.
    candidate_rules = []
    for cl in (Classification.objects
               .select_related('rule')
               .order_by('-confidence')):
        r = cl.rule
        if r.n_colors != 4:
            continue
        try:
            packed = PackedRuleset(n_colors=4, data=bytes(r.genome))
        except Exception:
            continue
        if packed.get(0, [0] * 6) != 0:
            continue
        stable = []
        for c in (1, 2, 3):
            if packed.get(c, [0] * 6) != c:
                continue
            ok = True
            for s in range(6):
                nbs = [0] * 6
                nbs[s] = c
                if packed.get(0, nbs) != 0:
                    ok = False
                    break
            if ok:
                stable.append(c)
        candidate_rules.append({
            'sha_short': r.sha1[:12],
            'slug': r.slug,
            'wolfram_class': cl.wolfram_class,
            'class_color': class_color(cl.wolfram_class),
            'confidence': cl.confidence,
            'stable_colors': stable,
            'palette': r.palette_hex,
        })

    # Sort: class-2 + stable colors first (most likely to give 'IDENTICAL'),
    # then class-4 (the user's research target, but harder), then the rest.
    def rank(c):
        cls = c['wolfram_class']
        has_stable = bool(c['stable_colors'])
        return (
            0 if (cls == 2 and has_stable) else
            1 if cls == 4 else
            2 if (cls == 2) else 3,
            -c['confidence'],
        )
    candidate_rules.sort(key=rank)
    candidate_rules = candidate_rules[:80]

    return render(request, 'taxon/wang.html', {
        'modes': MODES,
        'candidate_rules': candidate_rules,
    })


@login_required
@require_POST
def wang_run(request):
    """JSON endpoint — runs one experiment and returns trajectories.

    Request: POST JSON or form with sha (rule sha1 prefix), tile, buffer,
    steps, candidates, density, seed, stable_color (optional), mode.

    Response: full result dict from taxon.wang.run_experiment.
    """
    from .wang import Params, run_experiment

    if request.content_type == 'application/json':
        try:
            payload = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('bad JSON')
    else:
        payload = request.POST

    def _int(name, default):
        try:
            return int(payload.get(name, default))
        except (TypeError, ValueError):
            return default

    def _float(name, default):
        try:
            return float(payload.get(name, default))
        except (TypeError, ValueError):
            return default

    sha = (payload.get('sha') or '').strip()
    rule = Rule.objects.filter(sha1__startswith=sha).first() if sha else None
    if rule is None:
        return JsonResponse({'ok': False,
                             'reason': 'rule not found'}, status=404)
    packed = PackedRuleset(n_colors=rule.n_colors, data=bytes(rule.genome))

    sc_raw = (payload.get('stable_color') or '').strip() if isinstance(
        payload.get('stable_color'), str) else payload.get('stable_color')
    stable_color = None
    if sc_raw not in (None, '', 'null'):
        try:
            stable_color = int(sc_raw)
            if not (1 <= stable_color < rule.n_colors):
                stable_color = None
        except (TypeError, ValueError):
            stable_color = None

    mode = (payload.get('mode') or 'natural').strip()
    if mode not in ('natural', 'pin_outer', 'pin_all'):
        mode = 'natural'

    params = Params(
        size=_int('tile', 16),
        buffer=_int('buffer', 3),
        steps=_int('steps', 12),
        candidates=_int('candidates', 200),
        density=_float('density', 0.10),
        seed=_int('seed', 7),
        stable_color=stable_color,
        mode=mode,
    )

    try:
        res = run_experiment(packed, params)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)

    cl = (Classification.objects.filter(rule=rule)
          .order_by('-confidence').first())
    res['rule'] = {
        'sha_short': rule.sha1[:12],
        'slug': rule.slug,
        'wolfram_class': cl.wolfram_class if cl else None,
        'confidence': cl.confidence if cl else None,
        'palette': rule.palette_hex,
    }
    return JsonResponse(res)

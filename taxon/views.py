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
    cards = [_rule_card(r) for r in Rule.objects.all()[:24]]
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
    cards = [_rule_card(r) for r in qs[:300]]   # cap render cost
    sources = (Rule.objects.values('source')
               .annotate(c=Count('id')).order_by('-c'))
    return render(request, 'taxon/library.html', {
        'cards': cards,
        'sources': sources,
        'active_source': src,
        'q': q,
        'sort': sort,
        'total': qs.count(),
        'shown': len(cards),
    })


@login_required
def class_view(request, n: int):
    if n not in (1, 2, 3, 4):
        return HttpResponseBadRequest('class must be 1, 2, 3, or 4')
    # Latest-classification-per-rule with that wolfram_class.
    rule_ids = []
    for rule in Rule.objects.all():
        c = rule.latest_classification
        if c and c.wolfram_class == n:
            rule_ids.append(rule.id)
    rules = Rule.objects.filter(id__in=rule_ids)
    cards = [_rule_card(r) for r in rules]
    return render(request, 'taxon/class.html', {
        'n': n,
        'label': class_label(n),
        'color': class_color(n),
        'cards': cards,
        'class_choices': [(c, lbl) for c, lbl in WOLFRAM_CLASSES],
    })


@login_required
def metrics_view(request):
    return render(request, 'taxon/metrics.html', {
        'metrics': list_metrics(),
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

    return render(request, 'taxon/detail.html', {
        'rule': rule,
        'card': card,
        'metrics_table': metrics_table,
        'classifications': classifications,
        'genome_hex_preview': bytes(rule.genome).hex()[:96],
        'genome_hex_full': bytes(rule.genome).hex(),
        'palette_hex': rule.palette_hex,
        'class_choices': [(n, lbl) for n, lbl in WOLFRAM_CLASSES],
    })


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
    """Re-run metrics + classifier for one rule."""
    rule = get_object_or_404(Rule, slug=slug)
    horizon = int(request.POST.get('horizon', 120))
    grid = int(request.POST.get('grid', 24))
    seed = int(request.POST.get('seed', 42))

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
    err = None
    if request.method == 'POST':
        f = request.FILES.get('hxc4')
        if not f:
            err = 'No file uploaded.'
        else:
            try:
                blob = f.read()
                rule = importers.import_hxc4_blob(
                    blob,
                    name=request.POST.get('name', '') or f.name,
                    source=request.POST.get('source', 'manual') or 'manual',
                    source_ref=f.name,
                )
                # Auto-classify on upload.
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
            except Exception as e:
                err = str(e)
    return render(request, 'taxon/import.html', {
        'err': err,
        'source_choices': [
            ('manual', 'Manual upload'),
            ('s3lab', 'S3 Lab'),
            ('automaton', 'Automaton'),
            ('helix', 'Helix Hex Hunt'),
            ('stratum', 'S3 Lab Stratum'),
        ],
    })


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

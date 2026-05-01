"""Views for the Helix hex-CA hunt UI.

Three pages:
  /helix/hexhunt/                   list — corpora + recent runs
  /helix/hexhunt/runs/<slug>/       run detail — leaderboard + gen log
  /helix/hexhunt/rules/<slug>/      rule detail — replay player on a sample window
"""

from __future__ import annotations

import base64

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from helix.models import (
    AnnotationFeature, HuntCorpus, HuntRule, HuntRun,
    RuleFilterScan, SequenceRecord,
)

from . import engine
from .mapping import dna_to_board, BOARD_W, BOARD_H, WINDOW_SIZE


@login_required
def list_view(request):
    corpora = HuntCorpus.objects.all().order_by('-created_at')
    runs = HuntRun.objects.select_related('corpus', 'top_rule').order_by('-created_at')[:30]
    rules = HuntRule.objects.order_by('-created_at')[:30]
    scans = RuleFilterScan.objects.select_related('rule', 'record').order_by('-created_at')[:30]
    return render(request, 'helix/hexhunt/list.html', {
        'corpora': corpora,
        'runs': runs,
        'rules': rules,
        'scans': scans,
    })


@login_required
def run_detail(request, slug):
    run = get_object_or_404(
        HuntRun.objects.select_related('corpus', 'top_rule'), slug=slug,
    )
    # Reattach scoreboard rule slugs to HuntRule rows for linking.
    rule_map = {
        r.slug: r
        for r in HuntRule.objects.filter(
            slug__in=[row.get('rule_slug') for row in (run.scoreboard_json or [])
                      if row.get('rule_slug')]
        )
    }
    scoreboard_rows = []
    for row in (run.scoreboard_json or []):
        rule = rule_map.get(row.get('rule_slug'))
        scoreboard_rows.append({
            'rank':  row.get('rank'),
            'score': row.get('score'),
            'rule':  rule,
            'pos':   row.get('pos'),
            'neg':   row.get('neg'),
        })
    return render(request, 'helix/hexhunt/run_detail.html', {
        'run': run,
        'scoreboard_rows': scoreboard_rows,
    })


@login_required
def rule_detail(request, slug):
    rule = get_object_or_404(HuntRule, slug=slug)

    # Pick a sample window: prefer the corpus this rule was bred against.
    corpus_slug = (rule.provenance_json or {}).get('corpus')
    sample_window = None
    sample_label = ''
    if corpus_slug:
        corpus = HuntCorpus.objects.filter(slug=corpus_slug).first()
        if corpus:
            w = corpus.windows.select_related('record', 'feature').first()
            if w:
                sample_window = w
                sample_label = (
                    f'{w.record.accession or w.record.title} '
                    f'· {w.feature.feature_type if w.feature else "raw"} '
                    f'@ {w.start:,}'
                )

    # Records the user can scan against. Smaller records first so the
    # default selection is something that fits in an inline scan.
    records = list(SequenceRecord.objects.order_by('length_bp'))
    scans = list(rule.scans.select_related('record').order_by('-created_at')[:10])

    return render(request, 'helix/hexhunt/rule_detail.html', {
        'rule': rule,
        'sample_window': sample_window,
        'sample_label': sample_label,
        'records': records,
        'scans': scans,
        'inline_scan_max_windows': _INLINE_SCAN_MAX_WINDOWS,
    })


@login_required
@require_GET
def rule_replay(request, slug):
    """Return spacetime frames for a rule run on a chosen sample window.

    Query params:
        window=<HuntWindow pk>   pick any window from any corpus
        steps=<int>              cap at 256
    Falls back to the first window of the rule's bred-against corpus.
    """
    rule = get_object_or_404(HuntRule, slug=slug)
    try:
        steps = int(request.GET.get('steps', engine.TOTAL_STEPS))
    except ValueError:
        steps = engine.TOTAL_STEPS
    steps = max(1, min(256, steps))

    window_pk = request.GET.get('window')
    seq = None
    label = ''
    if window_pk:
        from helix.models import HuntWindow
        w = HuntWindow.objects.select_related('record').filter(pk=window_pk).first()
        if not w:
            raise Http404('window not found')
        seq = w.sequence()
        label = f'window {w.pk} · {w.record.accession or w.record.title}:{w.start}'
    else:
        corpus_slug = (rule.provenance_json or {}).get('corpus')
        if corpus_slug:
            corpus = HuntCorpus.objects.filter(slug=corpus_slug).first()
            if corpus:
                w = corpus.windows.select_related('record').first()
                if w:
                    seq = w.sequence()
                    label = f'window {w.pk} · {w.record.accession or w.record.title}:{w.start}'
    if seq is None:
        # Fallback — uniform-random window so the player still works.
        import random as _r
        seq = ''.join(_r.choices('ATGC', k=WINDOW_SIZE))
        label = 'random fallback window'

    board = dna_to_board(seq)
    rule_table = engine.unpack_rule(rule.packed())
    spacetime = engine.evolve(board, rule_table, steps=steps)
    score = engine.score(spacetime, 'gzip')
    # Pack each frame as a base64 string of bytes (one cell per byte —
    # frames are tiny, 256 bytes each, so the JSON wire stays small).
    frames = [
        base64.b64encode(frame.astype('uint8').tobytes()).decode('ascii')
        for frame in spacetime
    ]
    return JsonResponse({
        'rule_slug': rule.slug,
        'label':     label,
        'width':     BOARD_W,
        'height':    BOARD_H,
        'frames':    frames,
        'score':     score,
    })


# ── Filter scans (rule × whole record) ───────────────────────────────


# Bin count for the scan-detail histogram. 60 bins is enough resolution
# for visual edge-of-chaos band detection; more would just be noise.
_HIST_BINS = 60

# Maximum scan that can run inline through the rule_detail launch form
# without blocking the request too long.
_INLINE_SCAN_MAX_WINDOWS = 8000


@login_required
def scan_detail(request, slug):
    scan = get_object_or_404(
        RuleFilterScan.objects.select_related('rule', 'record'), slug=slug,
    )
    track = scan.track_json or []
    hist = _track_histogram(track, _HIST_BINS, scan.score_min, scan.score_max)
    top_windows = sorted(track, key=lambda r: -r[2])[:25]
    feat_qs = AnnotationFeature.objects.filter(
        record=scan.record,
    ).order_by('start')
    feature_summary = _scan_feature_overlap(track, list(feat_qs), scan.window_size)
    # Compact feature payload for the SVG lane — only the columns the
    # client actually paints, so a 20 k-feature record stays under
    # 1 MB of JSON. Lean array-of-arrays shape: [start, end, type_idx].
    type_index: dict = {}
    types_out: list = []
    feat_rows = []
    for f in feat_qs:
        ti = type_index.get(f.feature_type)
        if ti is None:
            ti = len(types_out)
            types_out.append(f.feature_type)
            type_index[f.feature_type] = ti
        feat_rows.append([f.start, f.end, ti])
    return render(request, 'helix/hexhunt/scan_detail.html', {
        'scan':            scan,
        'hist':            hist,
        'top_windows':     top_windows,
        'feature_summary': feature_summary,
        'feature_payload': {'types': types_out, 'rows': feat_rows},
    })


def _track_histogram(track, bins, lo, hi):
    """Return a per-bin count of windows. Front-end uses this for the
    score distribution sparkline."""
    if not track or hi <= lo:
        return [0] * bins
    span = hi - lo
    counts = [0] * bins
    for row in track:
        s = row[2]
        # Clamp into the histogram range — guards against floating-point
        # drift on the upper bound.
        idx = int((s - lo) / span * bins)
        if idx >= bins:
            idx = bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    return counts


def _scan_feature_overlap(track, feature_qs, window_size):
    """Bucket windows by the most specific feature_type they overlap.

    "Most specific" = shortest overlapping feature. The full-record
    ``source`` feature otherwise wins every window and drowns the
    biology we care about (CDS, gene, ncRNA, …).
    """
    if not track:
        return []
    feats = [
        {'start': f.start, 'end': f.end, 'length': f.end - f.start,
         'feature_type': f.feature_type}
        for f in feature_qs
    ]
    out: dict = {}
    for (a, b, score) in track:
        best_len = None
        best_type = ''
        for f in feats:
            if f['end'] <= a:
                continue
            if f['start'] >= b:
                break
            if f['end'] <= a or f['start'] >= b:
                continue
            if best_len is None or f['length'] < best_len:
                best_len = f['length']
                best_type = f['feature_type']
        while feats and feats[0]['end'] <= a:
            feats.pop(0)
        key = best_type or '(no feature)'
        agg = out.setdefault(key, {'n': 0, 'sum': 0.0, 'best': 0.0})
        agg['n'] += 1
        agg['sum'] += score
        agg['best'] = max(agg['best'], score)

    rows = []
    for key, agg in out.items():
        rows.append({
            'feature_type': key,
            'n':            agg['n'],
            'mean':         agg['sum'] / agg['n'],
            'best':         agg['best'],
        })
    rows.sort(key=lambda r: -r['mean'])
    return rows


@login_required
@require_GET
def scan_track_json(request, slug):
    """Return the raw track for a scan as JSON.

    Useful for the scan-detail SVG and for downstream tools (e.g. the
    Phase 2.5 overlay on /helix/<pk>/).
    """
    scan = get_object_or_404(RuleFilterScan, slug=slug)
    return JsonResponse({
        'slug':        scan.slug,
        'record_pk':   scan.record_id,
        'record_len':  scan.record.length_bp,
        'window_size': scan.window_size,
        'stride':      scan.stride,
        'scoring_fn':  scan.scoring_fn,
        'min':         scan.score_min,
        'max':         scan.score_max,
        'mean':        scan.score_mean,
        'track':       scan.track_json or [],
    })


@login_required
def launch_scan(request, slug):
    """POST handler — kick off a scan from the rule_detail page.

    Inline (synchronous) for small scans; for anything larger than
    ``_INLINE_SCAN_MAX_WINDOWS`` we refuse and ask the user to run
    the management command instead. We don't ship a background runner
    in Phase 2 — that's a Phase 3 concern.
    """
    if request.method != 'POST':
        raise Http404('use POST')
    rule = get_object_or_404(HuntRule, slug=slug)
    try:
        record_pk = int(request.POST['record_pk'])
        window = int(request.POST.get('window', 256))
        stride = int(request.POST.get('stride', 128))
        scoring_fn = request.POST.get('scoring_fn', 'edge')
    except (KeyError, ValueError):
        raise Http404('bad scan parameters')
    record = get_object_or_404(SequenceRecord, pk=record_pk)
    start = max(0, int(request.POST.get('start', 0) or 0))
    end_raw = int(request.POST.get('end', 0) or 0)
    end = end_raw if end_raw > 0 else record.length_bp
    end = min(end, record.length_bp)

    n_windows = max(0, (end - start - window) // stride + 1)
    if n_windows == 0:
        raise Http404('range too short for the chosen window')
    if n_windows > _INLINE_SCAN_MAX_WINDOWS:
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.error(
            request,
            f'Inline scan would be {n_windows:,} windows — over the '
            f'{_INLINE_SCAN_MAX_WINDOWS:,} cap. Run '
            f'`manage.py hexhunt_scan {rule.slug} {record.pk} '
            f'--window {window} --stride {stride} --start {start} --end {end}` '
            f'instead.'
        )
        return redirect('helix:hexhunt:rule_detail', slug=rule.slug)

    from .scan import scan_record
    rule_table = engine.unpack_rule(rule.packed())
    result = scan_record(
        record, rule_table,
        window_size=window, stride=stride,
        start=start, end=end, scoring_fn=scoring_fn,
    )
    scan = RuleFilterScan.objects.create(
        slug=RuleFilterScan.make_slug(),
        rule=rule, record=record,
        window_size=window, stride=stride, scoring_fn=scoring_fn,
        track_json=result.track,
        n_windows=result.n_windows,
        score_min=result.score_min,
        score_max=result.score_max,
        score_mean=result.score_mean,
    )
    from django.shortcuts import redirect
    return redirect('helix:hexhunt:scan_detail', slug=scan.slug)


# Inline tournament cap. Tournament cost ≈ pop × gens × windows × steps;
# we keep the inline ceiling well below "browser tab times out". Above
# this, the user should run the management command (which streams
# per-gen progress to stdout). Numbers picked empirically — 64×40×4
# finishes in 3-8 s on a laptop.
_INLINE_RUN_MAX_OPS = 64 * 50 * 6      # pop × gens × windows budget


@login_required
def launch_run(request):
    """POST handler — kick off a small inline hexhunt tournament.

    Mirrors ``launch_scan``: caps inline runs at a small budget; for
    bigger tournaments, surfaces the equivalent management command so
    the user can run it on the server side without a browser tab.
    """
    if request.method != 'POST':
        raise Http404('use POST')
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.db import transaction
    from django.utils import timezone as djtz
    from helix.hexhunt.tournament import TournamentParams, run_tournament

    corpus_slug = request.POST.get('corpus_slug', '').strip()
    if not corpus_slug:
        raise Http404('missing corpus_slug')
    corpus = get_object_or_404(HuntCorpus, slug=corpus_slug)

    try:
        pop     = max(8,    min(128,    int(request.POST.get('pop', 64))))
        gens    = max(5,    min(120,    int(request.POST.get('gens', 40))))
        windows = max(1,    min(12,     int(request.POST.get('windows', 4))))
        seed    = int(request.POST.get('seed', '0') or 0)
    except ValueError:
        raise Http404('bad run parameters')
    score    = request.POST.get('score', 'edge').strip() or 'edge'
    keep_top = max(1, min(20, int(request.POST.get('keep_top', 5) or 5)))
    mutation         = float(request.POST.get('mutation', 0.001) or 0.001)
    crossover        = float(request.POST.get('crossover', 0.20) or 0.20)
    survivors        = float(request.POST.get('survivors', 0.25) or 0.25)
    init_mutation    = float(request.POST.get('init_mutation_rate', 0.05) or 0.05)

    # Refuse big jobs inline — show the equivalent CLI invocation.
    cost = pop * gens * windows
    if cost > _INLINE_RUN_MAX_OPS:
        messages.error(
            request,
            f'Inline run budget is pop × gens × windows ≤ {_INLINE_RUN_MAX_OPS}; '
            f'requested {pop} × {gens} × {windows} = {cost}. Run '
            f'`venv/bin/python manage.py hexhunt_run {corpus.slug} '
            f'--pop {pop} --gens {gens} --windows {windows} '
            f'--score {score} --seed {seed}` from a shell instead.'
        )
        return redirect('helix:hexhunt:list')

    corpus_windows = list(corpus.windows.select_related('record').order_by('idx'))
    if not corpus_windows:
        messages.error(request, f'corpus {corpus.slug!r} has no windows.')
        return redirect('helix:hexhunt:list')
    seqs = [w.sequence() for w in corpus_windows]
    windows_used = min(windows, len(seqs))

    params = TournamentParams(
        population_size=pop,
        generations=gens,
        windows_per_gen=windows_used,
        mutation_rate=mutation,
        crossover_fraction=crossover,
        survivor_fraction=survivors,
        scoring_fn=score,
        steps=engine.TOTAL_STEPS,
        rng_seed=seed,
        init_mutation_rate=init_mutation,
    )

    params_dict = dict(params.__dict__)
    params_dict['mode'] = 'single'
    params_dict['source'] = 'inline-launch'

    run = HuntRun.objects.create(
        slug=HuntRun.make_slug(),
        corpus=corpus,
        params_json=params_dict,
        status='running',
        started_at=djtz.now(),
    )

    try:
        result = run_tournament(seqs, params)
    except Exception as exc:
        run.status = 'failed'
        run.notes = f'{type(exc).__name__}: {exc}'
        run.finished_at = djtz.now()
        run.save()
        messages.error(request, f'Hunt failed: {exc}')
        return redirect('helix:hexhunt:run_detail', slug=run.slug)

    keep = min(keep_top, len(result.final_population))
    with transaction.atomic():
        top_rule_obj = None
        scoreboard = []
        for rank in range(keep):
            pr = result.final_population[rank]
            score_val = result.final_scores[rank]
            provenance = {
                'origin':    'tournament_winner',
                'run_slug':  run.slug,
                'corpus':    corpus.slug,
                'rank':      rank + 1,
                'score':     score_val,
                'scoring':   params.scoring_fn,
            }
            rule = HuntRule.objects.create(
                slug=HuntRule.make_slug(),
                table=bytes(pr.data),
                name=f'{run.slug}#{rank+1:02d}',
                provenance_json=provenance,
            )
            scoreboard.append({
                'rank':      rank + 1,
                'score':     score_val,
                'rule_slug': rule.slug,
            })
            if rank == 0:
                top_rule_obj = rule
        run.top_rule = top_rule_obj
        run.scoreboard_json = scoreboard
        run.generation_log_json = [
            {'gen': g.gen, 'best': g.best, 'mean': g.mean,
             'elapsed_s': g.elapsed_s}
            for g in result.log
        ]
        run.status = 'done'
        run.finished_at = djtz.now()
        run.save()

    messages.success(
        request,
        f'Run {run.slug} done. Top score {scoreboard[0]["score"]:.4f} '
        f'across {keep} kept rules.'
    )
    return redirect('helix:hexhunt:run_detail', slug=run.slug)

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
    # Catch orphaned runners (e.g. process restarted mid-tournament)
    # before rendering, so a fresh page load doesn't show an
    # eternally-spinning "running" status.
    _maybe_mark_orphan(run, 'run')
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
    """Return spacetime frames for a rule run on a chosen initial board.

    Query params:
        init=dna|random         board source (default: dna)
        window=<HuntWindow pk>  for init=dna: pick any window from any corpus
        seed=<int>              for init=random: PRNG seed for board init;
                                also used as the per-window random fill seed
                                in dna_to_board (Ns / ambiguity codes)
        steps=<int>             cap at 256

    init=dna falls back to the first window of the rule's bred-against
    corpus when no window is specified, and to a uniform-random ATGC
    string of WINDOW_SIZE bases when no corpus is associated.
    """
    import numpy as np

    rule = get_object_or_404(HuntRule, slug=slug)
    try:
        steps = int(request.GET.get('steps', engine.TOTAL_STEPS))
    except ValueError:
        steps = engine.TOTAL_STEPS
    steps = max(1, min(256, steps))

    try:
        seed = int(request.GET.get('seed', 0)) & 0xFFFFFFFF
    except ValueError:
        seed = 0

    init_mode = (request.GET.get('init', 'dna') or 'dna').strip().lower()
    if init_mode not in ('dna', 'random'):
        init_mode = 'dna'

    label = ''
    if init_mode == 'random':
        rng = np.random.RandomState(seed)
        board = rng.randint(0, 4, size=(BOARD_H, BOARD_W), dtype=np.int8)
        label = f'random board · seed {seed}'
    else:
        window_pk = request.GET.get('window')
        seq = None
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
            import random as _r
            _r.seed(seed)
            seq = ''.join(_r.choices('ATGC', k=WINDOW_SIZE))
            label = 'random fallback window'
        board = dna_to_board(seq, seed=seed)

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
        'init':      init_mode,
        'seed':      seed,
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
    _maybe_mark_orphan(scan, 'scan')
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


def _scan_runner_thread(scan_pk: int, rule_pk: int, record_pk: int,
                         window: int, stride: int, start: int, end: int,
                         scoring_fn: str) -> None:
    """Background worker for an inline rule-as-filter scan. Updates
    the scan's n_windows + status as it sweeps the record so the
    progress.json poll endpoint can stream a live counter to the
    browser."""
    import sys
    import traceback
    from django.db import close_old_connections
    from .scan import scan_record

    try:
        from django.utils import timezone as djtz
        scan = RuleFilterScan.objects.get(pk=scan_pk)
        scan.last_heartbeat_at = djtz.now()
        scan.save(update_fields=['last_heartbeat_at'])
        rule = HuntRule.objects.get(pk=rule_pk)
        record = SequenceRecord.objects.get(pk=record_pk)
        rule_table = engine.unpack_rule(rule.packed())

        # Update n_windows + heartbeat on every progress callback.
        # progress_every is computed so we get ~30 updates over the
        # span of the scan; the heartbeat must beat well within the
        # stale threshold (_ORPHAN_THRESHOLD_SECONDS) at the slowest.
        progress_every = max(20, scan.total_windows // 30 or 20)

        def progress(i, n):
            scan.n_windows = i + 1
            scan.last_heartbeat_at = djtz.now()
            scan.save(update_fields=['n_windows', 'last_heartbeat_at'])

        result = scan_record(
            record, rule_table,
            window_size=window, stride=stride,
            start=start, end=end, scoring_fn=scoring_fn,
            on_progress=progress, progress_every=progress_every,
        )
        scan.track_json  = result.track
        scan.n_windows   = result.n_windows
        scan.score_min   = result.score_min
        scan.score_max   = result.score_max
        scan.score_mean  = result.score_mean
        scan.status      = 'done'
        scan.save()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        try:
            scan = RuleFilterScan.objects.get(pk=scan_pk)
            scan.status = 'failed'
            scan.notes  = f'{type(exc).__name__}: {exc}'
            scan.save(update_fields=['status', 'notes'])
        except Exception:
            traceback.print_exc(file=sys.stderr)
    finally:
        close_old_connections()


@login_required
def launch_scan(request, slug):
    """POST handler — kick off a scan in a daemon thread.

    Validates and persists the RuleFilterScan synchronously, then
    redirects to scan_detail and runs the scan in the background. The
    detail page polls scan_progress.json for live counters and reloads
    when status flips to done/failed. Inline cap caps the scan size to
    a few seconds of CPU; bigger scans need the management command.
    """
    if request.method != 'POST':
        raise Http404('use POST')
    import threading
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

    scan = RuleFilterScan.objects.create(
        slug=RuleFilterScan.make_slug(),
        rule=rule, record=record,
        window_size=window, stride=stride, scoring_fn=scoring_fn,
        total_windows=n_windows,
        n_windows=0,
        status='running',
    )

    t = threading.Thread(
        target=_scan_runner_thread,
        args=(scan.pk, rule.pk, record.pk, window, stride, start, end,
              scoring_fn),
        daemon=True,
    )
    t.start()

    from django.shortcuts import redirect
    return redirect('helix:hexhunt:scan_detail', slug=scan.slug)


@login_required
@require_GET
def scan_progress_json(request, slug):
    """Polled by scan_detail while status='running'."""
    scan = get_object_or_404(RuleFilterScan, slug=slug)
    _maybe_mark_orphan(scan, 'scan')
    return JsonResponse({
        'slug':              scan.slug,
        'status':            scan.status,
        'windows_done':      int(scan.n_windows),
        'windows_total':     int(scan.total_windows or scan.n_windows),
        'score_min':         scan.score_min,
        'score_max':         scan.score_max,
        'score_mean':        scan.score_mean,
        'notes':             scan.notes or '',
        'created_at':        scan.created_at.isoformat()        if scan.created_at        else None,
        'last_heartbeat_at': scan.last_heartbeat_at.isoformat() if scan.last_heartbeat_at else None,
    })


# Inline tournament cap. Tournament cost ≈ pop × gens × windows × steps;
# we keep the inline ceiling well below "browser tab times out". Above
# this, the user should run the management command (which streams
# per-gen progress to stdout). Numbers picked empirically — 64×40×4
# finishes in 3-8 s on a laptop.
_INLINE_RUN_MAX_OPS = 64 * 50 * 6      # pop × gens × windows budget


def _runner_thread(run_pk: int, corpus_pk: int, params, keep_top: int) -> None:
    """Background worker for an inline hexhunt tournament.

    Updates HuntRun.generation_log_json each generation so the
    /helix/hexhunt/runs/<slug>/progress.json poll endpoint can stream
    progress to the browser. On exit, persists the leaderboard +
    HuntRule rows the same way the management command does.
    """
    import sys
    import traceback
    from django.db import close_old_connections, transaction
    from django.utils import timezone as djtz
    from helix.hexhunt.tournament import run_tournament

    try:
        run    = HuntRun.objects.get(pk=run_pk)
        run.last_heartbeat_at = djtz.now()
        run.save(update_fields=['last_heartbeat_at'])
        corpus = HuntCorpus.objects.get(pk=corpus_pk)
        corpus_windows = list(
            corpus.windows.select_related('record').order_by('idx')
        )
        seqs = [w.sequence() for w in corpus_windows]

        # Per-gen progress: append to the log + bump the heartbeat. The
        # heartbeat is what protects us from runserver auto-reload (or
        # any other process death) — if it goes stale the progress
        # endpoint will mark the row failed instead of leaving it
        # forever in 'running'.
        gen_log: list = []
        def progress(g):
            gen_log.append({
                'gen': g.gen, 'best': g.best, 'mean': g.mean,
                'elapsed_s': g.elapsed_s,
            })
            run.generation_log_json = list(gen_log)
            run.last_heartbeat_at = djtz.now()
            run.save(update_fields=['generation_log_json', 'last_heartbeat_at'])

        result = run_tournament(seqs, params, on_generation=progress)

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
            run.generation_log_json = list(gen_log)
            run.status = 'done'
            run.finished_at = djtz.now()
            run.save()
    except Exception as exc:
        # Print to stderr so a `runserver` operator sees the trace —
        # daemon-thread exceptions are otherwise swallowed.
        traceback.print_exc(file=sys.stderr)
        try:
            run = HuntRun.objects.get(pk=run_pk)
            run.status = 'failed'
            run.notes = f'{type(exc).__name__}: {exc}'
            run.finished_at = djtz.now()
            run.save()
        except Exception:
            traceback.print_exc(file=sys.stderr)
    finally:
        close_old_connections()


@login_required
def launch_run(request):
    """POST handler — kick off a hexhunt tournament in a daemon thread.

    Validates params and creates the HuntRun row synchronously, then
    redirects to the run_detail page (302) and runs the tournament in
    the background. The detail page polls progress.json for live
    generation updates. Inline budget caps the run at a few seconds of
    CPU; bigger jobs need the management command.
    """
    if request.method != 'POST':
        raise Http404('use POST')
    import threading
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.utils import timezone as djtz
    from helix.hexhunt.tournament import TournamentParams

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

    corpus_windows = list(corpus.windows.all())
    if not corpus_windows:
        messages.error(request, f'corpus {corpus.slug!r} has no windows.')
        return redirect('helix:hexhunt:list')
    windows_used = min(windows, len(corpus_windows))

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

    t = threading.Thread(
        target=_runner_thread,
        args=(run.pk, corpus.pk, params, keep_top),
        daemon=True,
    )
    t.start()

    messages.success(
        request,
        f'Run {run.slug} launched ({pop} × {gens} × {windows_used} windows). '
        f'Live progress on this page; the leaderboard appears when it finishes.'
    )
    return redirect('helix:hexhunt:run_detail', slug=run.slug)


# If a status='running' row hasn't beaten the heartbeat in this many
# seconds, the runner thread is presumed dead (most likely the
# runserver process auto-reloaded on a code change). The progress
# endpoint flips the row to 'failed' on first observation so the UI
# can stop polling and show a useful error instead of spinning forever.
_ORPHAN_THRESHOLD_SECONDS = 120


def _maybe_mark_orphan(row, kind: str) -> bool:
    """If `row` is status='running' but its heartbeat is stale, mark
    it failed in place and return True. Caller should re-read row
    fields after this returns True."""
    from django.utils import timezone as djtz
    from datetime import timedelta
    if row.status != 'running':
        return False
    last = row.last_heartbeat_at or row.started_at or row.created_at
    if not last:
        return False
    if djtz.now() - last < timedelta(seconds=_ORPHAN_THRESHOLD_SECONDS):
        return False
    row.status = 'failed'
    row.notes = (row.notes + '\n' if row.notes else '') + (
        f'Marked failed by orphan check: no heartbeat in '
        f'{_ORPHAN_THRESHOLD_SECONDS}s. The runner thread likely died '
        f'(e.g. runserver auto-reload). Re-launch the {kind} to retry.'
    )
    if hasattr(row, 'finished_at') and row.finished_at is None:
        row.finished_at = djtz.now()
    update_fields = ['status', 'notes']
    if hasattr(row, 'finished_at'):
        update_fields.append('finished_at')
    row.save(update_fields=update_fields)
    return True


@login_required
@require_GET
def run_progress_json(request, slug):
    """Polled by the run_detail page while status='running'."""
    run = get_object_or_404(HuntRun, slug=slug)
    _maybe_mark_orphan(run, 'run')
    log = run.generation_log_json or []
    params = run.params_json or {}
    return JsonResponse({
        'slug':              run.slug,
        'status':            run.status,
        'gens_done':         len(log),
        'gens_total':        int(params.get('generations', 0) or 0),
        'log':               log,
        'scoreboard':        run.scoreboard_json or [],
        'notes':             run.notes or '',
        'started_at':        run.started_at.isoformat()        if run.started_at        else None,
        'finished_at':       run.finished_at.isoformat()       if run.finished_at       else None,
        'last_heartbeat_at': run.last_heartbeat_at.isoformat() if run.last_heartbeat_at else None,
    })

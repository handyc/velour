"""caframe views — index, sequence detail, on-the-fly frame/APNG render."""
from __future__ import annotations
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import render

from .models import Sequence
from . import render as r


@login_required
def index(request):
    """Catalog of saved sequences + a quick-roll demo seed."""
    sequences = list(Sequence.objects.all()[:24])
    # Eagerly compute a tiny preview thumbnail for each so the page is
    # informative on first visit even with zero sequences saved.
    sample_seeds = [
        ('alpha', 0xCAFEBEEF),
        ('beta',  0xDEADC0DE),
        ('gamma', 0xFACE1234),
        ('delta', 0xBADF00D),
    ]
    return render(request, 'caframe/index.html', {
        'sequences':    sequences,
        'sample_seeds': sample_seeds,
    })


@login_required
def sequence_detail(request, slug):
    seq = Sequence.objects.filter(slug=slug).first()
    if seq is None:
        raise Http404(f'unknown sequence {slug!r}')
    return render(request, 'caframe/detail.html', {
        'sequence': seq,
    })


def _palette_from_seq(seq: Sequence):
    raw = bytes(seq.palette_rgb)
    if len(raw) < 3 * seq.n_colors:
        return None     # fall back to default
    return [(raw[i*3], raw[i*3+1], raw[i*3+2]) for i in range(seq.n_colors)]


@login_required
def sequence_apng(request, slug):
    """Stream the APNG for a saved sequence — generated on the fly,
    no storage."""
    seq = Sequence.objects.filter(slug=slug).first()
    if seq is None:
        raise Http404(f'unknown sequence {slug!r}')
    cell_px = max(1, min(16, int(request.GET.get('cell_px', 6) or 6)))
    fps     = max(1, min(60, int(request.GET.get('fps', 8) or 8)))
    frames = list(r.iter_frames(
        rule_genome=bytes(seq.rule_genome), seed=seq.seed,
        w=seq.grid_w, h=seq.grid_h, n_frames=seq.n_frames,
        shape=seq.shape, n_colors=seq.n_colors))
    blob = r.grids_to_apng(frames, palette=_palette_from_seq(seq),
                              cell_px=cell_px, fps=fps)
    resp = HttpResponse(blob, content_type='image/apng')
    resp['Cache-Control'] = 'public, max-age=300'
    return resp


@login_required
def evolve_view(request):
    """Render the evolution UI."""
    return render(request, 'caframe/evolve.html', {})


@login_required
async def evolve_stream(request):
    """SSE-streamed (rule_seed, init_seed) GA against the
    consistency-and-edge composite. Each generation event includes
    best/mean/worst fitness; final 'end' event returns the winning
    genome the user can save as a Sequence."""
    import asyncio, json as _json, time
    from .ga import evolve_video, consistency_fitness, CaframeGenome
    from .render import consistency_score, edge_activity, iter_frames

    n_gen     = max(1, min(40, int(request.GET.get('n_gen',     8) or 8)))
    pop_size  = max(2, min(32, int(request.GET.get('pop_size', 12) or 12)))
    w         = max(8, min(64, int(request.GET.get('w',        32) or 32)))
    h         = max(8, min(64, int(request.GET.get('h',        32) or 32)))
    n_frames  = max(2, min(48, int(request.GET.get('n_frames', 16) or 16)))
    seed      = int(request.GET.get('seed', 0xCA1FA) or 0xCA1FA) & 0x7FFFFFFF

    async def stream():
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'n_gen': n_gen, 'pop_size': pop_size,
                'w': w, 'h': h, 'n_frames': n_frames, 'seed': seed,
                'total_evals': n_gen * pop_size,
            }) + '\n\n').encode()
            t0 = time.time()
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def _on_individual(gen_idx, ind_idx, score):
                loop.call_soon_threadsafe(q.put_nowait, ('ind', {
                    'gen': gen_idx, 'ind': ind_idx,
                    'score': float(score),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                }))

            def _on_generation(gen_idx, best, mean, worst):
                loop.call_soon_threadsafe(q.put_nowait, ('gen', {
                    'gen': gen_idx, 'best': float(best),
                    'mean': float(mean), 'worst': float(worst),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                }))

            async def _runner():
                g, score, history = await asyncio.to_thread(
                    evolve_video, n_gen=n_gen, pop_size=pop_size,
                    w=w, h=h, n_frames=n_frames, seed=seed,
                    on_individual=_on_individual,
                    on_generation=_on_generation)
                await q.put(('done', (g, score, history)))

            run_task = asyncio.create_task(_runner())
            winner, best, history = None, None, []
            try:
                while True:
                    kind, data = await q.get()
                    if kind == 'done':
                        winner, best, history = data
                        break
                    elif kind == 'ind':
                        yield ('event: individual\ndata: '
                                + _json.dumps(data) + '\n\n').encode()
                    else:
                        yield ('data: '
                                + _json.dumps(data) + '\n\n').encode()
            finally:
                if not run_task.done():
                    run_task.cancel()

            # Compute consistency / edge of the winner so the UI can
            # display them alongside the score.
            frames = await asyncio.to_thread(
                lambda: list(iter_frames(
                    rule_genome=__import__('caformer.primitives',
                        fromlist=['random_rule_table']).random_rule_table(
                            winner.rule_seed).tobytes(),
                    seed=winner.init_seed,
                    w=w, h=h, n_frames=n_frames, shape='hex')))
            cons = consistency_score(frames)
            edge = edge_activity(frames)

            yield ('event: end\ndata: ' + _json.dumps({
                'rule_seed':       winner.rule_seed,
                'init_seed':       winner.init_seed,
                'best_fitness':    float(best),
                'consistency':     float(cons),
                'edge_activity':   float(edge),
                'elapsed_ms':      int((time.time() - t0) * 1000),
                'apng_url':        (f'/caframe/quick.apng?seed={winner.init_seed}'
                                     f'&n_frames={n_frames}&w={w}&h={h}'),
            }) + '\n\n').encode()
        except asyncio.CancelledError:
            return

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


@login_required
def evolve_save(request):
    """POST: persist a (rule_seed, init_seed) tuple as a Sequence row."""
    if request.method != 'POST':
        return HttpResponse('POST only', status=405)
    from django.http import JsonResponse
    from caformer.primitives import random_rule_table
    rule_seed = int(request.POST.get('rule_seed', 0) or 0) & 0x7FFFFFFF
    init_seed = int(request.POST.get('init_seed', 0) or 0) & 0x7FFFFFFF
    slug      = (request.POST.get('slug') or
                  f'evolved-{rule_seed:08x}-{init_seed:08x}')[:80]
    name      = (request.POST.get('name') or
                  f'Evolved {rule_seed:x}/{init_seed:x}')[:120]
    notes     = (request.POST.get('notes') or '')[:2000]
    n_frames  = max(2, min(120, int(request.POST.get('n_frames', 32) or 32)))
    w         = max(8, min(96,  int(request.POST.get('w', 48) or 48)))
    h         = max(8, min(96,  int(request.POST.get('h', 48) or 48)))
    rule_blob = bytes(random_rule_table(rule_seed))
    seq, _ = Sequence.objects.update_or_create(
        slug=slug, defaults={
            'name': name, 'notes': notes,
            'shape': Sequence.SHAPE_HEX,
            'grid_w': w, 'grid_h': h,
            'n_colors': 4, 'n_frames': n_frames,
            'rule_genome': rule_blob, 'seed': init_seed,
            'source_app': 'caframe.evolve',
            'source_ref': f'rule={rule_seed:08x},init={init_seed:08x}',
        })
    return JsonResponse({'ok': True, 'slug': seq.slug,
        'detail_url': f'/caframe/{seq.slug}/'})


@login_required
def sequence_mp4(request, slug):
    """Stream an MP4 of a saved Sequence (gated on ffmpeg on PATH)."""
    from . import sources as src
    seq = Sequence.objects.filter(slug=slug).first()
    if seq is None:
        raise Http404(f'unknown sequence {slug!r}')
    cell_px = max(1, min(16, int(request.GET.get('cell_px', 6) or 6)))
    fps     = max(1, min(60, int(request.GET.get('fps', 12) or 12)))
    palette = _palette_from_seq(seq) or r.DEFAULT_PALETTE_RGB
    frames = list(r.iter_frames(
        rule_genome=bytes(seq.rule_genome), seed=seq.seed,
        w=seq.grid_w, h=seq.grid_h, n_frames=seq.n_frames,
        shape=seq.shape, n_colors=seq.n_colors))
    try:
        mp4 = src.frames_to_mp4(frames, palette=palette,
                                  cell_px=cell_px, fps=fps)
    except src.SourceUnavailable as e:
        return HttpResponse(f'MP4 unavailable: {e}', status=503,
                              content_type='text/plain')
    except Exception as e:
        return HttpResponse(f'MP4 encode failed: {e}', status=500,
                              content_type='text/plain')
    resp = HttpResponse(mp4, content_type='video/mp4')
    resp['Content-Disposition'] = f'inline; filename="{seq.slug}.mp4"'
    resp['Cache-Control'] = 'public, max-age=300'
    return resp


@login_required
def import_source(request):
    """POST: import a CA recipe from another app and save as a
    Sequence row. Form fields: source (taxon|caformer|loupe|spoeqi|
    escher), source_ref (slug of the source object), seed_init."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    from django.http import JsonResponse
    from . import sources as src
    source = (request.POST.get('source') or '').strip()
    ref    = (request.POST.get('source_ref') or '').strip()
    seed   = int(request.POST.get('seed_init', 0xCAFE) or 0xCAFE) & 0xFFFFFFFF
    n      = max(2, min(180, int(request.POST.get('n_frames', 40) or 40)))
    w      = max(8, min(128, int(request.POST.get('w', 48) or 48)))
    h      = max(8, min(128, int(request.POST.get('h', 48) or 48)))
    try:
        if   source == 'taxon':    rule, init, label = src.from_taxon(seed_init=seed, ref=ref or 'class-4')
        elif source == 'caformer': rule, init, label = src.from_caformer(ref, seed_init=seed)
        elif source == 'loupe':    rule, init, label = src.from_loupe_walk(ref, seed_init=seed)
        elif source == 'spoeqi':   rule, init, label = src.from_spoeqi(ref, seed_init=seed)
        elif source == 'metapact': rule, init, label = src.from_metapact(ref, seed_init=seed)
        elif source == 'escher':   rule, init, label = src.from_escher(ref, seed_init=seed)
        elif source == 'mandelhunt':
            pool = (request.POST.get('pool_dir') or '').strip() or None
            rule, init, label = src.from_mandelhunt(ref or 'best',
                                                          seed_init=seed,
                                                          pool_dir=pool)
        elif source == 'fractal':
            # ref selects which fractal ('mandelbrot', 'julia', …, or
            # 'random' to pick one).  Empty → 'random'.
            ws_raw = (request.POST.get('walk_seed') or '').strip()
            ws = int(ws_raw, 0) if ws_raw else None
            rule, init, label = src.from_fractal(ref or 'random',
                                                       seed_init=seed,
                                                       walk_seed=ws)
        else: return JsonResponse({'ok': False, 'error': f'unknown source {source!r}'})
    except src.SourceUnavailable as e:
        return JsonResponse({'ok': False, 'error': str(e)})
    # For fractal source, derive a slug that includes the picked
    # fractal name + walk_seed (parsed from the label, which always
    # says "fractal · <name> · walk_seed=0x…").  Each "random fractal"
    # click then yields a *new* Sequence instead of overwriting one row.
    slug_default = f'from-{source}-{ref or "auto"}-{init:08x}'
    if source == 'fractal':
        import re as _re
        m = _re.search(r'fractal · (\w+) · walk_seed=0x([0-9a-f]+)', label or '')
        if m:
            slug_default = f'fractal-{m.group(1)}-{m.group(2)}'
    slug = (request.POST.get('slug') or slug_default)[:80]
    name = (request.POST.get('name') or f'{label} (init {init:x})')[:120]
    seq, _ = Sequence.objects.update_or_create(
        slug=slug, defaults={
            'name':        name,
            'shape':       Sequence.SHAPE_HEX,
            'grid_w':      w, 'grid_h': h,
            'n_colors':    4, 'n_frames': n,
            'rule_genome': rule, 'seed': init,
            'source_app':  f'caframe.import.{source}',
            'source_ref':  label,
        })
    return JsonResponse({'ok': True, 'slug': seq.slug,
        'detail_url': f'/caframe/{seq.slug}/'})


@login_required
def quick_save(request):
    """POST: persist the current quick-roll knobs as a Sequence row."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    from django.http import JsonResponse
    seed   = int(request.POST.get('seed', 0xDEADBEEF) or 0xDEADBEEF) & 0xFFFFFFFF
    w      = max(8, min(128, int(request.POST.get('w', 48) or 48)))
    h      = max(8, min(128, int(request.POST.get('h', 48) or 48)))
    n      = max(2, min(180, int(request.POST.get('n_frames', 40) or 40)))
    shape  = request.POST.get('shape', 'hex')
    if shape == 'hex':
        from caformer.primitives import random_rule_table
        rule_genome = bytes(random_rule_table(seed ^ 0xCA1ED175))
    else:
        rule_genome = bytes((r._lcg_bytes(seed ^ 0x59118A11, 32) & 3))
    slug = (request.POST.get('slug') or
              f'quick-{shape}-{seed:08x}-{w}x{h}-{n}f')[:80]
    name = (request.POST.get('name') or f'Quick {shape} {seed:x}')[:120]
    seq, _ = Sequence.objects.update_or_create(
        slug=slug, defaults={
            'name':        name,
            'shape':       (Sequence.SHAPE_HEX if shape == 'hex'
                              else Sequence.SHAPE_SQUARE),
            'grid_w':      w, 'grid_h': h,
            'n_colors':    4, 'n_frames': n,
            'rule_genome': rule_genome, 'seed': seed,
            'source_app':  'caframe.quick_roll',
            'source_ref':  f'seed={seed:08x}',
        })
    return JsonResponse({'ok': True, 'slug': seq.slug,
        'detail_url': f'/caframe/{seq.slug}/'})


@login_required
def quick_apng(request):
    """Roll a one-off CA video from URL params — no DB write.

    GET params: seed, w, h, n_frames, cell_px, fps, shape
    """
    seed = int(request.GET.get('seed', 0xDEADBEEF) or 0xDEADBEEF) & 0xFFFFFFFF
    w    = max(8, min(128, int(request.GET.get('w', 48) or 48)))
    h    = max(8, min(128, int(request.GET.get('h', 48) or 48)))
    n    = max(2, min(180, int(request.GET.get('n_frames', 40) or 40)))
    cell_px = max(1, min(16, int(request.GET.get('cell_px', 6) or 6)))
    fps     = max(1, min(60, int(request.GET.get('fps', 8) or 8)))
    shape   = request.GET.get('shape', 'hex')
    # Derive a rule from the seed deterministically.
    if shape == 'hex':
        from caformer.primitives import random_rule_table
        rule_genome = bytes(random_rule_table(seed ^ 0xCA1ED175))
    else:
        # Square totalistic: 28-byte rule, modulo 4.
        rule_genome = bytes((r._lcg_bytes(seed ^ 0x59118A11, 32) & 3))
    frames = list(r.iter_frames(
        rule_genome=rule_genome, seed=seed, w=w, h=h, n_frames=n,
        shape=shape, n_colors=4))
    blob = r.grids_to_apng(frames, cell_px=cell_px, fps=fps)
    resp = HttpResponse(blob, content_type='image/apng')
    resp['Cache-Control'] = 'public, max-age=60'
    return resp

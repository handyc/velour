"""caformer/views.py — workshop pages for evolving an LLM out of CAs.

The app is *primarily a survey + design surface* at this stage; views
are intentionally thin.  Interactive demos arrive per-component as
each one becomes runnable.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import (Http404, HttpResponse, HttpResponseBadRequest,
                            StreamingHttpResponse)
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from . import components as cmp


@login_required
def index(request):
    return render(request, 'caformer/index.html', {
        'components':   cmp.COMPONENTS,
        'compositions': cmp.COMPOSITIONS,
    })


@login_required
def loopback_view(request):
    """Render the loopback viewer page: pick a TrainedModel + corpus +
    prompt, view the iteration trajectory and per-level Shakespeare
    scores. POST is handled by ``loopback_iterate`` over JSON so the
    page can re-run without reloading."""
    from .models import TrainedModel
    from .internalize import SHAKESPEARE_SONNETS
    return render(request, 'caformer/loopback.html', {
        'trained':            TrainedModel.objects.all()[:24],
        'shakespeare_excerpt': SHAKESPEARE_SONNETS[:400].decode(
            'utf-8', errors='replace'),
    })


@login_required
def loopback_iterate(request):
    """JSON endpoint: run the sliding-window feedback loop once.

    POST fields:
      ``model_slug``  TrainedModel slug, or '' for random rules
      ``corpus``      Probe corpus text (uses Shakespeare default if blank)
      ``prompt``      Starting prompt; defaults to first 32 corpus bytes
      ``n_iterations`` default 3 (cap 8)
      ``generate_len`` default 16 (cap 64)
      ``context_len``  default 32 (cap 128)
      ``n_blocks``     default 1 (cap 2)
      ``temperature``  default 0.8

    Returns JSON ``{trajectory: [{text, score, longest_matches}],
    avg_score: float, elapsed_ms: int, model: str}``.
    """
    from .ga import FULL_STACK_NAMES
    from .internalize import SHAKESPEARE_SONNETS
    from .loopback import (
        CorpusNgramIndex, iterate_genome, longest_match_at,
        make_genome_generator, multi_level_fitness,
        trained_model_to_genome,
    )
    from .primitives import default_norm_rule, random_rule_table
    import time as _time
    import numpy as np

    if request.method != 'POST':
        return _json_response({'error': 'POST required'})

    model_slug   = (request.POST.get('model_slug') or '').strip()
    corpus_text  = (request.POST.get('corpus') or '').strip()
    prompt_text  = (request.POST.get('prompt') or '').strip()
    n_iterations = _clamp_int(request.POST.get('n_iterations'), 3, 1, 8)
    generate_len = _clamp_int(request.POST.get('generate_len'), 16, 4, 64)
    context_len  = _clamp_int(request.POST.get('context_len'),  32, 8, 128)
    n_blocks     = _clamp_int(request.POST.get('n_blocks'),      1, 1, 2)
    try:
        temperature = max(0.0, min(5.0,
            float(request.POST.get('temperature') or 0.8)))
    except ValueError:
        temperature = 0.8

    corpus = (corpus_text.encode('utf-8') if corpus_text
              else SHAKESPEARE_SONNETS)
    corpus = corpus[:128 * 1024]   # cap probe corpus at 128 KB

    if model_slug:
        try:
            genome = trained_model_to_genome(model_slug)
        except Exception as exc:
            return _json_response({'error': f'no such model: {exc}'})
    else:
        seed = 0xCAB00B5
        genome = {n: random_rule_table(seed ^ (0x100 * (i + 1)))
                   for i, n in enumerate(FULL_STACK_NAMES)}
        genome['norm'] = default_norm_rule(seed ^ 0x8000)

    prompt = (prompt_text.encode('utf-8') if prompt_text
              else corpus[:32])
    index = CorpusNgramIndex(corpus, min_k=2, max_k=8)

    t0 = _time.time()
    gen_fn = make_genome_generator(
        genome, n_blocks=n_blocks, temperature=temperature)
    traj = iterate_genome(gen_fn, prompt, index,
                           n_iterations=n_iterations,
                           generate_len=generate_len,
                           context_len=context_len)
    elapsed_ms = int((_time.time() - t0) * 1000)

    # Weighted [1,2,3,...] mean = the "loop closure" fitness.
    weights = list(range(1, n_iterations + 1))
    weighted = (sum(w * s for w, s in zip(weights, traj.scores))
                 / max(1, sum(weights)))

    out_iters = []
    for it_idx, (b, score, lms) in enumerate(
            zip(traj.iterations, traj.scores, traj.longest_matches)):
        out_iters.append({
            'i':       it_idx,
            'text':    b.decode('latin-1', errors='replace'),
            'score':   round(float(score), 4),
            # Per-position longest-match length, useful for highlighting
            'lms':     lms,
        })
    return _json_response({
        'model':       model_slug or '(random)',
        'prompt':      prompt.decode('latin-1', errors='replace'),
        'trajectory':  out_iters,
        'avg_score':   round(float(traj.total_score), 4),
        'weighted_score': round(float(weighted), 4),
        'elapsed_ms':  elapsed_ms,
        'corpus_bytes': len(corpus),
        'config': {
            'n_iterations': n_iterations,
            'generate_len': generate_len,
            'context_len':  context_len,
            'n_blocks':     n_blocks,
            'temperature':  temperature,
        },
    })


@login_required
def internalize_view(request):
    """Internalise a text corpus directly into a CAformer with one of
    two CA-native, zero-training methods (n-gram bake or metachain
    seed). POST writes a TrainedModel and redirects to chat."""
    from .internalize import (
        SHAKESPEARE_SONNETS, save_ngram_baked_model,
        save_metachain_seeded_model,
    )
    from .models import TrainedModel
    from django.shortcuts import redirect
    from django.utils.text import slugify
    from django.contrib import messages

    msg = ''
    stats = None
    saved_slug = None
    if request.method == 'POST':
        method = (request.POST.get('method') or 'ngram').strip()
        name   = (request.POST.get('name')   or '').strip() or 'corpus-bake'
        slug   = slugify((request.POST.get('slug')
                           or f'{method}-{name}'))[:80]
        if not slug:
            slug = 'corpus-bake'
        corpus = (request.POST.get('corpus') or '').encode('utf-8')
        if not corpus.strip():
            corpus = SHAKESPEARE_SONNETS
        upload = request.FILES.get('upload')
        if upload is not None:
            try:
                corpus = upload.read()
            except Exception:
                corpus = SHAKESPEARE_SONNETS
        # Soft cap so we don't ingest a 100 MB upload by accident.
        corpus = corpus[:2 * 1024 * 1024]
        if method == 'metachain':
            depth = max(1, min(20, int(request.POST.get('depth') or 10)))
            ticks = max(1, min(64, int(request.POST.get('chain_ticks') or 20)))
            obj, stats = save_metachain_seeded_model(
                corpus, name=name, slug=slug,
                depth=depth, chain_ticks=ticks)
        else:
            ctx = max(1, min(7,
                              int(request.POST.get('context_bytes') or 7)))
            obj, stats = save_ngram_baked_model(
                corpus, name=name, slug=slug, context_bytes=ctx)
        saved_slug = obj.slug
        return redirect(
            f"{request.build_absolute_uri('/caformer/chat/')}?model={obj.slug}")
    return render(request, 'caformer/internalize.html', {
        'shakespeare_excerpt': SHAKESPEARE_SONNETS[:600].decode(
            'utf-8', errors='replace'),
        'recent': TrainedModel.objects.order_by('-id')[:12],
    })


@login_required
def diagram(request):
    """Pipeline-level diagram + a strip of compact per-component
    mechanism thumbnails that deep-link into the full mechanism
    diagrams on each component page."""
    from .models import TrainedModel
    trained = list(TrainedModel.objects.order_by('-final_fitness', '-created_at')
                                          .values_list('slug', flat=True))
    return render(request, 'caformer/diagram.html', {
        'components':    cmp.COMPONENTS,
        'trained_slugs': trained,
        'best_slug':     trained[0] if trained else '',
    })


@login_required
def component(request, slug):
    c = cmp.get(slug)
    if c is None:
        raise Http404(f'unknown component {slug!r}')
    from .models import TrainedModel
    trained = list(TrainedModel.objects.order_by('-final_fitness', '-created_at')
                                          .values_list('slug', flat=True))
    c_source = cmp.c_source_for_component(slug)
    return render(request, 'caformer/component.html', {
        'component':     c,
        'components':    cmp.COMPONENTS,
        'trained_slugs': trained,
        'best_slug':     trained[0] if trained else '',
        'c_source':      c_source,
    })


@login_required
def composition(request, slug):
    c = cmp.get_composition(slug)
    if c is None:
        raise Http404(f'unknown composition {slug!r}')
    # Resolve the contained primitives so the template can deep-link.
    contained_components = [cmp.get(s) for s in c.contains if cmp.get(s)]
    contained_compositions = [cmp.get_composition(s) for s in c.contains
                                if cmp.get_composition(s)]
    return render(request, 'caformer/composition.html', {
        'composition':            c,
        'compositions':           cmp.COMPOSITIONS,
        'contained_components':   contained_components,
        'contained_compositions': contained_compositions,
    })


# ──────────────────────────────────────────────────────────────────
# Default-Mode loop viewer.  Live page + Server-Sent Events stream
# of one DMN step per event.  No external LLM, no Pact, no spoeqi
# dependency — pure caformer CA stack.
# ──────────────────────────────────────────────────────────────────


@login_required
def dmn_view(request):
    """HTML page that opens an EventSource against `dmn_stream` and
    paints the substrate + observables as each step arrives."""
    return render(request, 'caformer/dmn.html', {
        'composition':  cmp.get_composition('default_mode_loop'),
    })


def _clamp_int(s, default, lo, hi):
    try:
        v = int(s)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@login_required
@require_GET
async def dmn_stream(request):
    """Server-Sent Events endpoint.  Yields one ``data: {...}\\n\\n``
    JSON event per DMN step; the browser's EventSource picks these
    up live.  Capped at 60 steps by default (safety net so a
    forgotten tab doesn't loop forever — bump via ?max_steps=N up
    to the absolute cap of 500).

    Async view: the CA work runs in a worker thread via
    ``asyncio.to_thread`` so the event loop stays free; if the
    client disconnects, the next ``await`` raises CancelledError and
    the loop exits cleanly — no more CLOSE-WAIT pile-up.
    """
    import asyncio
    import hashlib
    import numpy as np
    from .primitives import (
        hex_ca_step, lcg_bytes, random_rule_table)
    from .transformer import nano_gpt
    from .dmn import CADMNStep, dmn_observables

    # 128 cap lets a user opt into the LUT-as-grid bijection (4^7 =
    # 16,384 = 128²); default stays at 12 to keep the live view snappy.
    grid_side    = _clamp_int(request.GET.get('grid_side'),    12, 6, 128)
    vocab_size   = _clamp_int(request.GET.get('vocab_size'),   32, 4, 128)
    n_blocks     = _clamp_int(request.GET.get('n_blocks'),      1, 1, 4)
    # Default lowered 200 → 60: at the post-optimisation ~18 ms/step
    # that's ~1 s wall-clock for the whole loop, so a leaked tab self-
    # cleans within seconds.  Old default of 200 (× pre-fix 200 ms = 40 s)
    # was the leading cause of the CLOSE-WAIT pile-up that broke daphne.
    max_steps    = _clamp_int(request.GET.get('max_steps'),    60, 4, 500)
    starting_seed = _clamp_int(request.GET.get('starting_seed'),
                                0xDEFA001, 1, 2**31 - 1)
    window_tokens = _clamp_int(request.GET.get('window_tokens'), 4, 1, 8)

    rule = random_rule_table(starting_seed ^ 0xD3F)
    grid = (lcg_bytes(starting_seed, grid_side * grid_side) & 3
             ).reshape(grid_side, grid_side)

    def _step(g, history, seen, tick):
        """One full DMN step, run on a worker thread so the CA
        compute (numpy + Python) doesn't block daphne's event loop."""
        g = hex_ca_step(g, rule)
        gh = hashlib.sha256(g.tobytes()).hexdigest()[:16]
        cycle_at = seen.get(gh)
        novelty = 0.0 if cycle_at is not None else 1.0
        if cycle_at is None:
            seen[gh] = tick
        rows_per_token = max(1, grid_side // window_tokens)
        toks = []
        for t in range(window_tokens):
            chunk = g[t * rows_per_token:(t + 1) * rows_per_token].tobytes()
            toks.append(int.from_bytes(
                hashlib.sha256(chunk).digest()[:2], 'big') % vocab_size)
        logits = nano_gpt(toks, vocab_size=vocab_size,
                            base_seed=starting_seed)
        sampled = int(logits.argmax())
        flat = g.flatten()
        n_ = flat.size
        flat[sampled % n_]              ^= sampled        & 3
        flat[(sampled * 31 + 7) % n_]   ^= (sampled >> 2) & 3
        g = (flat & 3).reshape(grid_side, grid_side)
        history.append(CADMNStep(
            tick=tick, grid_hash=gh, sampled=sampled,
            novelty=novelty, cycle_at=cycle_at))
        if len(history) > 64:
            del history[0:len(history) - 64]
        obs = dmn_observables(history)
        payload = {
            'tick':    tick, 'grid': g.tolist(), 'hash': gh,
            'sampled': sampled, 'tokens': toks,
            'novelty': novelty, 'cycle_at': cycle_at,
            'observables': obs,
        }
        return g, payload

    async def stream():
        try:
            yield (
                'event: meta\ndata: ' + json.dumps({
                    'grid_side':    grid_side,
                    'vocab_size':   vocab_size,
                    'n_blocks':     n_blocks,
                    'max_steps':    max_steps,
                    'starting_seed': starting_seed,
                    'window_tokens': window_tokens,
                }) + '\n\n').encode()
            history: list = []
            seen: dict   = {}
            local_grid = grid
            for tick in range(max_steps):
                local_grid, payload = await asyncio.to_thread(
                    _step, local_grid, history, seen, tick)
                yield ('data: ' + json.dumps(payload) + '\n\n').encode()
            yield b'event: end\ndata: {}\n\n'
        except asyncio.CancelledError:
            # Client disconnected: bail without raising, daphne logs cleanly.
            return

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


# ──────────────────────────────────────────────────────────────────
# Chat window — char-level prompt → fully-CA forward → response.
# Lives at /caformer/chat/ with a ChatGPT-style transcript pane.
# ──────────────────────────────────────────────────────────────────


@login_required
def chat_view(request):
    """Render the chat page. Server persists each turn as a ChatTurn
    so the user can later run a "train on my chat" job — the
    conversational/training loop closes."""
    from .models import TrainedModel, ChatTurn
    try:
        from spoeqi.llm_lora import list_known_models
        backbones = list_known_models()
    except Exception:
        backbones = []
    chat_turn_count = ChatTurn.objects.filter(user=request.user).count()
    return render(request, 'caformer/chat.html', {
        'trained':  TrainedModel.objects.all()[:24],
        'backbones': backbones,
        'chat_turn_count': chat_turn_count,
    })


@login_required
async def train_distill(request):
    """SSE-streamed one-shot distillation of an LLM into a CA model.

    No GA, no iterative training: walks 16,384 LLM forwards (batched)
    and writes one byte per LUT entry. The result is a saved
    TrainedModel whose ``output_rule`` mimics the LLM's first-byte
    distribution.

    GET params:
      ?backbone=<name>  — any name accepted by spoeqi.llm_lora.load_backbone
      ?slug=<slug>      — TrainedModel slug to save under
      ?name=<name>      — display name (defaults to "distilled-from-<backbone>")
    """
    import asyncio
    import json as _json
    import time
    backbone = (request.GET.get('backbone') or 'distilgpt2').strip()
    slug     = (request.GET.get('slug') or
                  f'distilled-{backbone.replace("/", "_")}-{int(time.time())}')[:80]
    name     = (request.GET.get('name') or
                  f'distilled from {backbone}')[:80]

    async def stream():
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'backbone':  backbone,
                'slug':      slug,
                'name':      name,
                'lut_size':  16384,
            }) + '\n\n').encode()

            t0 = time.time()
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def _on_progress(done, total):
                loop.call_soon_threadsafe(q.put_nowait, ('progress', {
                    'done': int(done), 'total': int(total),
                    'pct':  round(100.0 * done / max(1, total), 1),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                }))

            from .distill import distill_to_trained_model

            async def _runner():
                obj = await asyncio.to_thread(
                    distill_to_trained_model,
                    backbone, name=name, slug=slug,
                    progress=_on_progress)
                await q.put(('done', obj))

            run_task = asyncio.create_task(_runner())
            saved = None
            try:
                while True:
                    kind, payload = await q.get()
                    if kind == 'done':
                        saved = payload
                        break
                    yield ('data: ' + _json.dumps(payload) + '\n\n').encode()
            finally:
                if not run_task.done():
                    run_task.cancel()

            yield ('event: end\ndata: ' + _json.dumps({
                'slug':       saved.slug,
                'name':       saved.name,
                'elapsed_ms': int((time.time() - t0) * 1000),
                'chat_url':   f'/caformer/chat/?model={saved.slug}',
            }) + '\n\n').encode()
        except asyncio.CancelledError:
            return
        except Exception as e:
            yield ('event: end\ndata: ' + _json.dumps({
                'error': str(e),
            }) + '\n\n').encode()

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


@login_required
def train_from_chat(request):
    """One-click POST: dump this user's chat history into the session
    training corpus, then return its size. After this the user can
    just hit "start" on /caformer/train/ and the GA trains directly
    on what they typed."""
    if request.method != 'POST':
        return _json_response({'ok': False, 'error': 'POST only'})
    from .models import ChatTurn
    corpus = ChatTurn.training_corpus(request.user)
    if not corpus.strip():
        return _json_response({
            'ok': False,
            'error': 'no chat history yet — say something to /caformer/chat/ first'})
    request.session['caformer_train_corpus'] = corpus[:CORPUS_CAP]
    return _json_response({
        'ok': True,
        'len': len(corpus[:CORPUS_CAP]),
        'turn_count': ChatTurn.objects.filter(user=request.user).count(),
    })


@login_required
@require_GET
def chat_reply(request):
    """Char-level prompt → ca_generate_qkv → text response.

    Chosen tokenisation: each byte = one token (vocab_size = 256).
    That keeps tokenisation trivial (no BPE table to ship), works for
    arbitrary text, and matches what `ca_forward_qkv` expects (small
    integer ids).  The model is currently *random rule tables* (no
    training), so the output will be incoherent — the point is the
    pipeline being end-to-end CA, not the model being smart yet.
    Run `caformer.ga.evolve_full_stack` if you want the rules to
    actually predict something.

    Query knobs:
      ?q=<text>            user prompt
      ?n=<int>             max new tokens (default 32, max 128)
      ?n_blocks=<int>      transformer depth (default 2)
      ?temperature=<float> sampling temperature (default 0.8)
      ?seed=<int>          base_seed for the model + sample seed
      ?model=<slug>        load a saved TrainedModel — overrides the
                            random-rule defaults so an evolved chat
                            actually uses its trained rules
    """
    from .transformer import ca_generate_qkv

    q = (request.GET.get('q') or '').strip()
    if not q:
        return _json_response({'reply': '', 'error': 'empty prompt'})
    n           = _clamp_int(request.GET.get('n'),         32,  1, 4096)
    seed        = _clamp_int(request.GET.get('seed'), 0xCAFE,  1, 2**31 - 1)
    try:
        temperature = max(0.0, min(20.0, float(request.GET.get('temperature') or 0.8)))
    except ValueError:
        temperature = 0.8

    model_slug   = request.GET.get('model') or ''
    dispatched   = ''
    # Per-prompt QRPair dispatch: when the caller didn't pin ?model=,
    # look up a trained QRPair whose `prompt` matches `q` and load it
    # automatically.  Lets one /caformer/chat/ handle every trained
    # pair without the user having to remember slugs.  When dispatch
    # fires, the pair's training-time n_blocks always wins — the chat
    # form sends its HTML default `n_blocks=2` unconditionally, so any
    # URL-pinned override would be indistinguishable from the default.
    # If you need a specific n_blocks, pick an explicit ?model= and the
    # dispatcher steps out of the way.
    composed = None
    n_user_set = 'n' in request.GET
    if not model_slug:
        # Dispatch priority:
        #   1. Action trigger  — phrase-driven heavier expert
        #   2. Exact prompt    — byte-for-byte match against trained QRPair
        #   3. Prenormalizer   — typo'd input; replace bytes with canonical
        #   4. Per-word        — split q; route each word
        #   5. Fall through    — random rules (untrained chat default)
        n_blocks = _clamp_int(request.GET.get('n_blocks'), 2, 1, 4)
        from .models import TrainedModel  # lazy
        trig = _resolve_action_trigger(q)
        if trig is not None:
            t_cfg, payload = trig
            t_slug = t_cfg.get('expert_slug') or ''
            if t_slug and TrainedModel.objects.filter(slug=t_slug).exists():
                model_slug = t_slug
                dispatched = f"action:{t_cfg.get('phrase','')}"
                n_blocks = _clamp_int(t_cfg.get('n_blocks', n_blocks),
                                          2, 1, 4)
                n = _clamp_int(t_cfg.get('n_tokens', n), n, 1, 4096)
                if payload:
                    q = payload
        if not model_slug:
            d_slug, d_blocks = _dispatch_qrpair_for_prompt(q)
            if d_slug:
                model_slug = d_slug
                dispatched = d_slug
                n_blocks = _clamp_int(d_blocks, 2, 1, 4)
        if not model_slug:
            norm = _normalize_prompt_to_trained(q)
            if norm is not None:
                canonical, slug, n_b, dist = norm
                model_slug = slug
                dispatched = (f"normalized:{q!r}→{canonical!r}"
                                f"(d={dist})")
                n_blocks = _clamp_int(n_b, 2, 1, 4)
                # CRITICAL: replace user input with canonical bytes;
                # positional rules were trained on those exact bytes.
                q = canonical
        # When dispatch routed to a positional QRPair and the user
        # didn't pin ?n=, cap generation at the trained length so we
        # don't trail off into base-rule noise after the real answer.
        if model_slug and not n_user_set:
            _pos_rules, _n_pos = _positional_output_rules_for_slug(model_slug)
            if _pos_rules is not None and _n_pos > 0:
                n = _n_pos
        if not model_slug:
            # Whole-prompt miss — try per-word composition.  If any
            # word matches a trained pair we short-circuit and emit
            # the composed reply directly.
            allowed_bytes_pre = _allowed_bytes_for_request(request)
            composed = _compose_per_word_reply(
                q, temperature=temperature, seed=seed,
                allowed_bytes=allowed_bytes_pre)
    else:
        n_blocks = _clamp_int(request.GET.get('n_blocks'), 2, 1, 4)

    if composed is not None and composed['any_match']:
        backbone = (request.GET.get('backbone') or '').strip()
        # Flatten the per-word token sequences plus space separators
        # so the caller's `tokens` field reflects exactly what was
        # emitted.
        all_tokens = []
        for i, part in enumerate(composed['parts']):
            if i > 0:
                all_tokens.append(ord(' '))
            all_tokens.extend(part['tokens']
                                or list(part['word'].encode('utf-8')))
        _persist_chat_turn(request, q, composed['reply'],
                             model_slug='', backbone=backbone)
        return _json_response({
            'reply':       composed['reply'],
            'tokens':      all_tokens,
            'prompt_len':  len(q.encode('utf-8')),
            'n_blocks':    n_blocks,
            'temperature': temperature,
            'seed':        seed,
            'model':       '',
            'dispatched':  'per-word',
            'parts':       [
                {'word': p['word'], 'slug': p['slug'],
                 'reply': p['reply'], 'matched': p['matched']}
                for p in composed['parts']
            ],
        })

    positional_rules, n_positional = \
        _positional_output_rules_for_slug(model_slug)
    # When in positional mode, source the base rules from the live
    # QRPair — its base + positional rules were co-trained, so they
    # only agree with each other.  The TrainedModel snapshot can be
    # stale if the user retrained the pair without re-deploying.
    if positional_rules is not None:
        forward_kw = _positional_forward_kwargs(model_slug, n_blocks) or \
                       _trained_model_kwargs(model_slug, n_blocks)
    else:
        forward_kw = _trained_model_kwargs(model_slug, n_blocks)
    prompt_ids = list(q.encode('utf-8'))[:64]    # cap context for latency
    backbone = (request.GET.get('backbone') or '').strip()
    # `ca_experts` knob: 0 = LLM only (default, fast — ~20-50 ms/token
    # warm), 1-3 = mix that many CA experts with the LLM (the original
    # hybrid behaviour, ~2-9 s/token because the CA experts dominate
    # step cost).
    ca_experts = _clamp_int(request.GET.get('ca_experts'), 0, 0, 3)
    allowed_bytes = _allowed_bytes_for_request(request)
    if backbone:
        # Hybrid path: cheap CA router decides per-token whether the
        # call goes to a CA expert or to a real LLM expert. Heavy on
        # first-call (model load), warm afterwards.
        out_ids = _hybrid_generate(prompt_ids,
                                     backbone=backbone,
                                     max_new_tokens=n,
                                     temperature=temperature,
                                     sample_seed=seed,
                                     base_seed=seed,
                                     allowed_bytes=allowed_bytes,
                                     n_ca_experts=ca_experts)
    elif positional_rules is not None:
        # Positional Q→R: per-token output rule.  Manual loop so each
        # generation step can swap output_rule before forwarding.
        from .transformer import ca_forward_qkv
        from .primitives import ca_softmax_sample
        out_ids = []
        seq = list(prompt_ids)
        for tick in range(n):
            step_kw = dict(forward_kw)
            if tick < n_positional:
                step_kw['output_rule'] = positional_rules[tick]
            logits = ca_forward_qkv(seq, n_blocks=n_blocks, vocab_size=256,
                                      base_seed=seed, **step_kw)
            nxt, _ = ca_softmax_sample(
                logits, temperature=temperature,
                ca_seed=seed ^ (tick + 1),
                allowed_bytes=allowed_bytes)
            out_ids.append(int(nxt)); seq.append(int(nxt))
    else:
        out_ids = ca_generate_qkv(prompt_ids,
                                    max_new_tokens=n, n_blocks=n_blocks,
                                    vocab_size=256, temperature=temperature,
                                    sample_seed=seed, base_seed=seed,
                                    allowed_bytes=allowed_bytes,
                                    **forward_kw)
    # Decode generated bytes back to text.  Latin-1 round-trips every
    # byte 0..255 to a char so the user can see exactly what came out;
    # printable-only would hide most of the model's output at this
    # untrained stage.
    reply = bytes(out_ids).decode('latin-1', errors='replace')
    _persist_chat_turn(request, q, reply,
                         model_slug=model_slug,
                         backbone=backbone)
    return _json_response({
        'reply':       reply,
        'tokens':      out_ids,
        'prompt_len':  len(prompt_ids),
        'n_blocks':    n_blocks,
        'temperature': temperature,
        'seed':        seed,
        'model':       model_slug,
        'dispatched':  dispatched,
    })


def _persist_chat_turn(request, prompt, reply, *,
                         model_slug='', backbone=''):
    """Best-effort save of one chat exchange. Silent on failure so a
    DB hiccup never breaks the chat reply path."""
    try:
        from .models import ChatTurn
        if not request.user.is_authenticated:
            return
        ChatTurn.objects.create(
            user=request.user,
            prompt=(prompt or '')[:8000],
            reply=(reply or '')[:8000],
            model_slug=(model_slug or '')[:80],
            backbone=(backbone or '')[:120],
        )
    except Exception:
        pass


def _hybrid_generate(prompt_ids, *, backbone, max_new_tokens,
                       temperature, sample_seed, base_seed,
                       allowed_bytes=None, n_ca_experts=0):
    """Autoregressive sampling with a real-LLM backbone.

    ``n_ca_experts=0`` (default): direct LLM-only path via
    ``real_llm_expert_logits`` — ~20-50 ms/token warm.  Picking a
    larger backbone stays usable.

    ``n_ca_experts=1..3``: route through ``chat_gpt3_5_hybrid`` with
    that many CA experts joining the LLM under the cheap CA router.
    Each CA expert adds ~1-2 s/token at seq_len=16 — fine for
    distilgpt2 + 1 expert, painful for larger combinations.

    The CA experts' step cost grows quickly with sequence length
    (~20 s/token at seq_len=40 on CPU); when they're enabled the seq
    is truncated to the trailing ``HYBRID_CTX_CAP`` tokens.  Char-
    level CAs don't benefit from longer context anyway.
    """
    from .primitives import ca_softmax_sample
    seq = list(prompt_ids)
    out = []

    if n_ca_experts <= 0:
        # LLM-only fast path — skip the MoE entirely so the CA experts
        # (which dominate per-token cost) don't fire at all.
        from .transformer import real_llm_expert_logits
        for step in range(max_new_tokens):
            logits = real_llm_expert_logits(seq, model_name=backbone,
                                              vocab_size=256)
            next_id, _ = ca_softmax_sample(
                logits, temperature=temperature,
                ca_seed=sample_seed ^ step,
                allowed_bytes=allowed_bytes)
            seq.append(next_id)
            out.append(next_id)
        return out

    from .transformer import chat_gpt3_5_hybrid
    expert_specs = (['ca'] * n_ca_experts) + [('llm', backbone)]
    top_k = min(2, len(expert_specs))
    for step in range(max_new_tokens):
        ctx = seq[-HYBRID_CTX_CAP:]
        logits = chat_gpt3_5_hybrid(
            ctx, vocab_size=256, base_seed=base_seed,
            expert_specs=expert_specs, top_k=top_k)
        next_id, _ = ca_softmax_sample(
            logits, temperature=temperature, ca_seed=sample_seed ^ step,
            allowed_bytes=allowed_bytes)
        seq.append(next_id)
        out.append(next_id)
    return out


# Sequence-length cap for the CA experts inside the hybrid path.
# At ~0.5 s/token for seq_len ≤ 16 vs ~7 s/token at seq_len=20+ the
# user perceives a freeze; 16-token recent-window keeps generation
# snappy without losing relevant character-level context.
HYBRID_CTX_CAP = 16


def _allowed_bytes_for_request(request):
    """Resolve the ``?ascii_only=1`` and ``?alphabet=corpus`` knobs
    into a frozenset of allowed byte ids (or None for unrestricted).

    Precedence:
      alphabet=corpus  → only bytes that occurred in the model's
                          stored corpus_excerpt (if a model is loaded)
      ascii_only=1     → ASCII printable + LF + CR
      (neither)        → None (no restriction)
    """
    from .primitives import ASCII_PRINTABLE
    alphabet = (request.GET.get('alphabet') or '').strip()
    if alphabet == 'corpus':
        slug = (request.GET.get('model') or '').strip()
        if slug:
            from .models import TrainedModel
            tm = TrainedModel.objects.filter(slug=slug).first()
            if tm is not None and tm.corpus_excerpt:
                seen = frozenset(tm.corpus_excerpt.encode('utf-8',
                                                              errors='replace'))
                if seen:
                    return seen
        # Fall through to ascii if corpus alphabet isn't recoverable.
        return ASCII_PRINTABLE
    if alphabet == 'ascii_only' or \
            request.GET.get('ascii_only') in ('1', 'true', 'on', 'yes'):
        return ASCII_PRINTABLE
    return None


def _json_response(payload):
    """Tiny json wrapper — saves a JsonResponse import boilerplate."""
    from django.http import JsonResponse
    return JsonResponse(payload)


def _trained_model_kwargs(model_slug: str, n_blocks: int) -> dict:
    """Look up a TrainedModel by slug and convert it to forward-pass
    kwargs for ca_forward_qkv / ca_generate_qkv.  Returns empty dict
    when no slug given (so the caller falls through to defaults)."""
    if not model_slug:
        return {}
    from .models import TrainedModel
    obj = TrainedModel.objects.filter(slug=model_slug).first()
    if obj is None:
        return {}
    g = obj.as_genome()
    block = {
        'q':     g['q'],     'k':     g['k'],
        'v':     g['v'],     'score': g['score'],
        'mix':   g['mix'],   'merge': g['merge'],
        'mlp':   g['mlp'],
    }
    return {
        'embed_rule':  g['embed'],
        'block_rules': [block] * n_blocks,
        'norm_rule':   g['norm'],
        'output_rule': g['output'],
    }


def _levenshtein(a: str, b: str) -> int:
    """Standard Wagner-Fischer Levenshtein.  Linear-space; O(|a|·|b|).
    Used by the fuzzy prenormalizer so a single typo doesn't drop the
    user off the trained-prompt cliff into random-rule territory."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur_row = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur_row.append(min(prev_row[j] + 1,
                                  cur_row[j - 1] + 1,
                                  prev_row[j - 1] + cost))
        prev_row = cur_row
    return prev_row[-1]


def _normalize_prompt_to_trained(q: str):
    """Fuzzy match q against every trained QRPair's prompt.  Returns
    (canonical_prompt, deployed_slug, n_blocks, edit_distance) for the
    closest match within tolerance, or None.

    Tolerance scales with prompt length so single-word typos (≤4 chars)
    are forgiven by 1 edit and longer phrases by ~25 %.  The CA needs
    the *trained* bytes to produce correct output, so when this fires,
    the caller MUST replace the user's input bytes with the canonical
    prompt before running the pipeline."""
    from .models import QRPair
    if not q:
        return None
    candidates = (QRPair.objects
                     .filter(best_exact=True)
                     .exclude(deployed_slug='')
                     .values_list('prompt', 'deployed_slug', 'n_blocks'))
    if not candidates:
        return None
    best = None
    for prompt, slug, n_blocks in candidates:
        # Skip self-match (exact dispatcher handled that already).
        if prompt == q:
            continue
        tol = max(1, len(prompt) // 4)
        d = _levenshtein(q, prompt)
        if d <= tol and (best is None or d < best[3]):
            best = (prompt, slug, int(n_blocks or 1), d)
    return best


# ── Action triggers — phrase-driven expert invocation ────────────────
#
# Triggers live in caformer/action_triggers.json so they're trivially
# editable.  Format:
#   {"triggers": [
#       {"phrase": "say hi", "expert_slug": "qr-...",
#        "payload_extract": "after-phrase|before-phrase|full-prompt|fixed",
#        "payload_literal": "hi",         (only used by 'fixed')
#        "n_tokens": 5, "n_blocks": 1,
#        "priority": 10, "enabled": true,
#        "description": "demo trigger"}
#   ]}
# The dispatcher consults this list BEFORE exact-prompt match, so a
# trigger fires even when the prompt isn't trained — that's the whole
# point of having an "agent-like" path for complex prompts.

def _action_triggers_path():
    from django.conf import settings
    from pathlib import Path
    return Path(settings.BASE_DIR) / 'caformer' / 'action_triggers.json'


def _load_action_triggers():
    """Read the action-triggers config.  Returns a list (possibly empty).
    Re-reads on every call — the trigger set is tiny, and this lets the
    user edit the JSON without restarting the server."""
    import json
    path = _action_triggers_path()
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text()).get('triggers', []))
    except (ValueError, OSError):
        return []


def _resolve_action_trigger(prompt: str):
    """Find the highest-priority enabled trigger whose phrase appears
    as a substring of ``prompt`` (case-insensitive).  Returns
    (trigger_dict, payload) or None.

    Payload extraction rules:
        after-phrase  → text after the matched phrase
        before-phrase → text before the matched phrase
        full-prompt   → the entire user input
        fixed         → trigger['payload_literal'] (constant input to
                            the expert; ignores user's surrounding text).
                            Useful when the expert is a positional QRPair
                            that only accepts one exact byte sequence.
    """
    triggers = _load_action_triggers()
    if not triggers:
        return None
    p_lower = prompt.lower()
    candidates = []
    for t in triggers:
        if not t.get('enabled', True):
            continue
        phrase = (t.get('phrase') or '').lower().strip()
        if not phrase:
            continue
        idx = p_lower.find(phrase)
        if idx == -1:
            continue
        candidates.append((t, idx, phrase))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-(x[0].get('priority', 0)), x[1]))
    t, idx, phrase = candidates[0]
    extract = t.get('payload_extract', 'after-phrase')
    if extract == 'after-phrase':
        payload = prompt[idx + len(phrase):].strip()
    elif extract == 'before-phrase':
        payload = prompt[:idx].strip()
    elif extract == 'full-prompt':
        payload = prompt
    elif extract == 'fixed':
        payload = str(t.get('payload_literal') or '')
    else:
        payload = prompt
    return (t, payload)


def _positional_output_rules_for_slug(model_slug: str):
    """If `model_slug` was deployed from a positional QRPair, return
    its list of per-position output rules — else None.  Called from
    the chat reply path so it can swap output rules per generated
    token.  Returns (rules_list, n_positions) or (None, 0)."""
    if not model_slug:
        return (None, 0)
    from .models import QRPair
    pair = QRPair.objects.filter(deployed_slug=model_slug).first()
    if pair is None or not pair.is_positional():
        return (None, 0)
    rules = pair.positional_output_rules()
    return (rules, len(rules) if rules else 0)


def _run_one_pair_inline(prompt: str, slug: str, n_blocks: int, *,
                            temperature: float, seed: int, allowed_bytes,
                            extra_tokens: int = 0) -> tuple[str, list[int]]:
    """Run one trained positional QRPair on a single prompt and return
    its full trained reply (and the token-id list).  Used by per-word
    composition — the dispatcher resolves each word to a pair, then we
    call this for each.

    Generates exactly ``n_positional + extra_tokens`` tokens; the pair
    has trained positional rules only for the first ``n_positional``
    so extra ticks fall back to the base output rule and are usually
    garbage.  Default extra=0 → emit exactly the trained response."""
    positional_rules, n_positional = \
        _positional_output_rules_for_slug(slug)
    forward_kw = (_positional_forward_kwargs(slug, n_blocks)
                    or _trained_model_kwargs(slug, n_blocks))
    if positional_rules is None or forward_kw is None or n_positional == 0:
        return ('', [])
    from .transformer import ca_forward_qkv
    from .primitives import ca_softmax_sample
    prompt_ids = list(prompt.encode('utf-8'))[:64]
    seq = list(prompt_ids)
    out_ids: list[int] = []
    n = n_positional + max(0, int(extra_tokens))
    for tick in range(n):
        step_kw = dict(forward_kw)
        if tick < n_positional:
            step_kw['output_rule'] = positional_rules[tick]
        logits = ca_forward_qkv(seq, n_blocks=n_blocks, vocab_size=256,
                                  base_seed=seed, **step_kw)
        nxt, _ = ca_softmax_sample(logits, temperature=temperature,
                                      ca_seed=seed ^ (tick + 1),
                                      allowed_bytes=allowed_bytes)
        out_ids.append(int(nxt))
        seq.append(int(nxt))
    text = bytes(out_ids).decode('latin-1', errors='replace')
    return (text, out_ids)


def _compose_per_word_reply(prompt: str, *,
                              temperature: float, seed: int,
                              allowed_bytes,
                              max_extra_per_word: int = 0
                              ):
    """Per-word chain composition: tokenize the prompt by whitespace,
    look up each word's QRPair, run its CA, concatenate the outputs
    with single spaces.  Unmatched words pass through verbatim so
    "hi there friend" with only `hi` and `friend` trained yields
    "<hi-reply> there <friend-reply>".

    Returns:
        {'reply': str,
         'parts': [{'word': str, 'slug': str, 'reply': str,
                      'matched': bool, 'tokens': [int, ...]}],
         'any_match': bool,
         'all_match': bool}
        or None if the prompt has no whitespace (caller should fall
        back to whole-prompt dispatch instead)."""
    words = prompt.split()
    if len(words) < 2:
        return None
    parts: list[dict] = []
    any_match = False
    all_match = True
    out_chunks: list[str] = []
    for w in words:
        slug, n_blocks = _dispatch_qrpair_for_prompt(w)
        if slug:
            any_match = True
            text, ids = _run_one_pair_inline(
                w, slug, n_blocks,
                temperature=temperature, seed=seed,
                allowed_bytes=allowed_bytes,
                extra_tokens=max_extra_per_word)
            parts.append({'word': w, 'slug': slug, 'reply': text,
                            'matched': True, 'tokens': ids})
            out_chunks.append(text)
        else:
            all_match = False
            parts.append({'word': w, 'slug': '', 'reply': w,
                            'matched': False, 'tokens': []})
            out_chunks.append(w)
    return {
        'reply':     ' '.join(out_chunks),
        'parts':     parts,
        'any_match': any_match,
        'all_match': all_match,
    }


def _dispatch_qrpair_for_prompt(prompt: str):
    """Per-prompt QRPair dispatcher.  When the user has not pinned a
    specific `?model=`, route the incoming prompt to the trained
    QRPair (best_exact=True, deployed_slug set) whose `prompt` field
    matches the incoming text — exact match first, then case-insensitive.

    Returns (deployed_slug, n_blocks) on hit, or (None, None) on miss.
    This is the multi-pair chat router: it lets one /caformer/chat/
    handle `hi → hello` AND `hey → goodbye` AND any future trained
    pair without the caller having to know which slug to pass."""
    from .models import QRPair
    if not prompt:
        return (None, None)
    # Exact prompt match only — positional output rules are trained
    # on a specific byte sequence; routing 'HI' to the 'hi' pair
    # produces garbage because the prior context bytes differ.
    pair = (QRPair.objects
              .filter(best_exact=True, prompt=prompt)
              .exclude(deployed_slug='')
              .first())
    if pair is None:
        return (None, None)
    return (pair.deployed_slug, int(pair.n_blocks or 1))


def _positional_forward_kwargs(model_slug: str, n_blocks: int):
    """When a model_slug points to a positional QRPair, return the
    forward kwargs sourced from the QRPair itself — not the deployed
    TrainedModel snapshot.  This keeps base rules and per-position
    output rules in sync when the user retrains a pair without
    re-deploying.  Returns None if the slug is not a positional QRPair."""
    if not model_slug:
        return None
    from .models import QRPair
    pair = QRPair.objects.filter(deployed_slug=model_slug).first()
    if pair is None or not pair.is_positional():
        return None
    g = pair.best_genome()
    if g is None:
        return None
    block = {k: g[k] for k in ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}
    return {
        'embed_rule':  g['embed'],
        'block_rules': [block] * n_blocks,
        'norm_rule':   g['norm'],
        'output_rule': g['output'],
    }


# ──────────────────────────────────────────────────────────────────
# Training UI.  Page: /caformer/train/  — corpus textarea + GA
# knobs.  Stream: /caformer/train/stream/ — async SSE that yields one
# event per generation with (best, mean, worst) fitness.  Save:
# /caformer/train/save/ — POST that takes the latest checkpoint and
# persists as a TrainedModel.
# ──────────────────────────────────────────────────────────────────

# Process-local registry of in-progress training runs, so the SSE
# stream can hand its winner to /caformer/train/save/ without going
# through the database.  Keyed by (request session key).  Bounded
# (drops oldest) so nothing leaks even if 100 users train at once.
_TRAIN_RESULTS: dict = {}
_TRAIN_RESULTS_CAP = 32


@ensure_csrf_cookie
@login_required
def train_view(request):
    """Render the training page.  Lists previously-saved TrainedModel
    rows so the user can see their evolved models + their fitness.

    ``@ensure_csrf_cookie`` so the JS fetch() calls (from-chat,
    post-corpus, distill) can read csrftoken from document.cookie
    on a fresh page load — otherwise the cookie isn't set yet and
    the POST returns Django's 403 HTML, which the JS then trips on
    with "JSON.parse: unexpected character at line 1 column 2".

    Also surfaces the LLM backbones list so the no-training distill
    panel has something to populate its dropdown."""
    from .models import TrainedModel
    try:
        from spoeqi.llm_lora import list_known_models
        backbones = list_known_models()
    except Exception:
        backbones = []
    return render(request, 'caformer/train.html', {
        'trained':   TrainedModel.objects.all()[:24],
        'backbones': backbones,
    })


@login_required
async def train_stream(request):
    """Async SSE training loop: one event per GA generation with the
    (best, mean, worst) fitness scalar.  Holds the final winning
    genome in ``_TRAIN_RESULTS[session_key]`` so a follow-up POST to
    ``/caformer/train/save/`` can persist it under a name.

    Accepts both GET (small corpus in query string) and POST (large
    corpus in body — EventSource doesn't natively POST so the page
    POSTs the corpus to /train/post-corpus/ first to stash it in the
    session, then the GET hits this endpoint without the corpus
    param and we pull it from the session)."""
    import asyncio
    import json as _json
    import time
    from .ga import (FULL_STACK_NAMES, GAConfig, _evolve,
                      make_text_fitness)
    from .primitives import random_rule_table

    src = request.POST if request.method == 'POST' else request.GET
    # Explicit `?source=chat` ALWAYS uses the chat-derived corpus
    # stashed by /train/from-chat/, ignoring any textarea-posted bytes
    # so the JS flag can't get out of sync with reality.
    if (src.get('source') or '').strip() == 'chat':
        corpus = request.session.get('caformer_train_corpus', '').strip()
    else:
        corpus = (src.get('corpus') or '').strip()
        if not corpus:
            # Fallback: pick up a corpus the page may have stashed in
            # the session (lets the form POST a large corpus first,
            # then EventSource GET the stream with no corpus param).
            corpus = request.session.get('caformer_train_corpus', '').strip()
    if len(corpus) < 32:
        # Fall back to a literary fragment so a curious user with no
        # corpus still sees the loop produce *some* signal.
        corpus = (
            'In the beginning the Universe was created. This has '
            'made a lot of people very angry and been widely '
            'regarded as a bad move. ') * 4
    pop_size    = _clamp_int(src.get('pop_size'),    8, 4, 32)
    generations = _clamp_int(src.get('generations'), 6, 1, 40)
    n_blocks    = _clamp_int(src.get('n_blocks'),    2, 1, 4)
    seed        = _clamp_int(src.get('seed'), 0xCAB00B5, 1, 2**31 - 1)
    n_windows   = _clamp_int(src.get('n_windows'),  16, 4, 64)
    window_len  = _clamp_int(src.get('window_len'), 12, 4, 64)

    fitness = make_text_fitness(corpus, vocab_size=256, n_blocks=n_blocks,
                                  n_windows=n_windows, window_len=window_len)
    template = {n: random_rule_table(seed ^ (0x100 * (i + 1)))
                 for i, n in enumerate(FULL_STACK_NAMES)}
    cfg = GAConfig(pop_size=pop_size, generations=generations,
                    tournament_k=3, elite_n=1,
                    mutation_rate=0.003, seed=seed)

    async def stream():
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'pop_size': pop_size, 'generations': generations,
                'n_blocks': n_blocks, 'seed': seed,
                'corpus_len': len(corpus),
                'total_evals': pop_size * generations,
            }) + '\n\n').encode()
            t0 = time.time()
            # Live-progress plumbing: the GA thread pushes events into a
            # queue; this coroutine drains the queue and emits SSE.
            # Without this the page sees `meta` then total silence
            # while the GA runs all generations as one blocking call.
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def _on_individual(gen_idx, ind_idx, score):
                loop.call_soon_threadsafe(
                    q.put_nowait,
                    ('ind', {
                        'gen': gen_idx, 'ind': ind_idx,
                        'score': float(score),
                        'elapsed_ms': int((time.time() - t0) * 1000),
                    }))

            def _on_generation(gen_idx, best, mean, worst):
                loop.call_soon_threadsafe(
                    q.put_nowait,
                    ('gen', {
                        'gen': gen_idx, 'best': float(best),
                        'mean': float(mean), 'worst': float(worst),
                        'elapsed_ms': int((time.time() - t0) * 1000),
                    }))

            async def _runner():
                result = await asyncio.to_thread(
                    _evolve, template, fitness, cfg,
                    on_individual=_on_individual,
                    on_generation=_on_generation)
                await q.put(('done', result))

            run_task = asyncio.create_task(_runner())
            result = None
            try:
                while True:
                    kind, payload = await q.get()
                    if kind == 'done':
                        result = payload
                        break
                    elif kind == 'ind':
                        yield ('event: individual\ndata: '
                                + _json.dumps(payload) + '\n\n').encode()
                    else:    # 'gen'
                        yield ('data: '
                                + _json.dumps(payload) + '\n\n').encode()
            finally:
                if not run_task.done():
                    run_task.cancel()

            # Stash the winner for /train/save/.
            sk = (getattr(getattr(request, 'session', None),
                             'session_key', None) or 'anon')
            if len(_TRAIN_RESULTS) >= _TRAIN_RESULTS_CAP:
                _TRAIN_RESULTS.pop(next(iter(_TRAIN_RESULTS)))
            _TRAIN_RESULTS[sk] = {
                'genome':    result.best_genome,
                'fitness':   result.best_fitness,
                'history':   result.history,
                'corpus':    corpus,
                'n_blocks':  n_blocks,
                'pop_size':  pop_size,
                'generations': generations,
            }
            yield ('event: end\ndata: ' + _json.dumps({
                'best_fitness': result.best_fitness,
                'elapsed_ms':   int((time.time() - t0) * 1000),
                'savable':      True,
            }) + '\n\n').encode()
        except asyncio.CancelledError:
            return

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


CORPUS_CAP = 2_000_000   # 2 MB session-cap; bigger corpora rarely help
                          # at the GA's per-eval cost anyway.


def _decode_upload(raw: bytes) -> str:
    """Best-effort decode of an uploaded file. Tries UTF-8 first
    (covers most modern text), then latin-1 (every byte round-trips
    to a char so a binary file still won't crash). Strips a BOM if
    present and normalises CRLF → LF."""
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            text = raw.decode(enc)
            return text.replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', errors='replace').replace('\r\n', '\n')


@login_required
def train_post_corpus(request):
    """Stash a training corpus in the session before kicking off the
    EventSource GET — sidesteps URL length limits.

    Three input shapes, all under one POST endpoint:
      * ``corpus=...`` form field  — pasted text
      * ``files`` multi-file upload — concatenated with ``\\n\\n`` separators
                                       so a folder of .txt files becomes
                                       one training corpus
      * ``url=...`` form field      — fetch up to CORPUS_CAP bytes from
                                       the URL (text/plain only)

    Whichever is non-empty wins; if multiple are given they're combined
    in the order listed above. Total caps at CORPUS_CAP bytes."""
    if request.method != 'POST':
        return _json_response({'ok': False, 'error': 'POST only'})
    parts: list = []
    pasted = (request.POST.get('corpus') or '').strip()
    if pasted:
        parts.append(pasted)
    file_count = 0
    file_names: list = []
    for f in request.FILES.getlist('files'):
        try:
            blob = f.read()
        except Exception as e:
            return _json_response({
                'ok': False, 'error': f'read failed for {f.name!r}: {e}'})
        parts.append(_decode_upload(blob))
        file_names.append(f.name)
        file_count += 1
    url = (request.POST.get('url') or '').strip()
    fetched_from = ''
    if url:
        if not (url.startswith('http://') or url.startswith('https://')):
            return _json_response({
                'ok': False, 'error': 'url must be http(s)://'})
        try:
            import urllib.request
            req = urllib.request.Request(
                url, headers={'User-Agent': 'caformer/1 (training-corpus)'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                blob = resp.read(CORPUS_CAP + 1)
            parts.append(_decode_upload(blob))
            fetched_from = url
        except Exception as e:
            return _json_response({
                'ok': False, 'error': f'fetch failed: {e}'})
    if not parts:
        return _json_response({'ok': False, 'error': 'no corpus given'})
    corpus = '\n\n'.join(parts)[:CORPUS_CAP]
    request.session['caformer_train_corpus'] = corpus
    return _json_response({
        'ok':            True,
        'len':           len(corpus),
        'sources': {
            'pasted_chars':  len(pasted),
            'files':         file_names,
            'file_count':    file_count,
            'fetched_from':  fetched_from,
        },
        'capped':        len(corpus) >= CORPUS_CAP,
    })


@login_required
async def train_polish(request):
    """SSE-streamed coordinate-descent polish on the latest GA winner.

    For each session, picks up the genome stashed by ``train_stream``
    in ``_TRAIN_RESULTS`` and runs ``polish_genome`` on it.  Each
    trial is one (rule, lut_index) coordinate; the trainer tries the
    other 3 colours and keeps any improvement (strictly monotone).

    Knobs (all GET params): ``trials`` (1..400, default 60),
    ``n_windows`` (1..32, default 6 — fewer windows than the GA so
    each trial is cheaper)."""
    import asyncio
    import json as _json
    import time
    from .ga import (FULL_STACK_NAMES, polish_genome, make_text_fitness)
    from .primitives import random_rule_table

    sk = request.session.session_key or 'anon'
    payload = _TRAIN_RESULTS.get(sk)
    if payload is None:
        return _json_response({
            'ok': False,
            'error': 'no training result in this session — run a GA job first'})
    trials      = _clamp_int(request.GET.get('trials'),   60, 1, 400)
    n_windows   = _clamp_int(request.GET.get('n_windows'), 6, 1,  32)
    window_len  = _clamp_int(request.GET.get('window_len'), 12, 4, 64)
    seed        = _clamp_int(request.GET.get('seed'), 0xF0115, 1, 2**31 - 1)
    n_blocks    = payload['n_blocks']
    corpus      = payload['corpus']

    fitness = make_text_fitness(corpus, vocab_size=256, n_blocks=n_blocks,
                                  n_windows=n_windows, window_len=window_len)

    async def stream():
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'trials': trials, 'n_windows': n_windows,
                'n_blocks': n_blocks, 'corpus_len': len(corpus),
                'starting_fitness': payload['fitness'],
            }) + '\n\n').encode()
            t0 = time.time()
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def _on_trial(idx, score, improved):
                loop.call_soon_threadsafe(q.put_nowait, ('trial', {
                    'trial': idx, 'score': float(score),
                    'improved': bool(improved),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                }))

            async def _runner():
                polished, best, n_imp = await asyncio.to_thread(
                    polish_genome, payload['genome'], fitness,
                    trials=trials, seed=seed, on_trial=_on_trial)
                await q.put(('done', (polished, best, n_imp)))

            run_task = asyncio.create_task(_runner())
            polished, best, n_imp = None, None, 0
            try:
                while True:
                    kind, data = await q.get()
                    if kind == 'done':
                        polished, best, n_imp = data
                        break
                    yield ('data: ' + _json.dumps(data) + '\n\n').encode()
            finally:
                if not run_task.done():
                    run_task.cancel()

            # Replace the stashed genome with the polished one so /save
            # picks up the better version.
            payload['genome']  = polished
            payload['fitness'] = best
            yield ('event: end\ndata: ' + _json.dumps({
                'best_fitness':   float(best),
                'improvements':   int(n_imp),
                'elapsed_ms':     int((time.time() - t0) * 1000),
                'starting_fitness': payload.get('fitness'),
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
def train_save(request):
    """POST endpoint: persist the latest training result for this
    session as a TrainedModel under a user-chosen name+slug."""
    if request.method != 'POST':
        return _json_response({'ok': False, 'error': 'POST only'})
    name = (request.POST.get('name') or '').strip()
    slug = (request.POST.get('slug') or '').strip()
    notes = (request.POST.get('notes') or '').strip()
    if not name or not slug:
        return _json_response({'ok': False,
                                 'error': 'need name + slug'})
    sk = request.session.session_key or 'anon'
    payload = _TRAIN_RESULTS.get(sk)
    if payload is None:
        return _json_response({'ok': False,
            'error': 'no training result in this session — run a job first'})
    from .ga import save_genome_as_model
    obj = save_genome_as_model(
        payload['genome'],
        name=name, slug=slug, notes=notes,
        corpus_excerpt=payload['corpus'],
        n_blocks=payload['n_blocks'],
        pop_size=payload['pop_size'],
        generations=payload['generations'],
        final_fitness=payload['fitness'],
        history=payload['history'],
    )
    return _json_response({'ok': True, 'slug': obj.slug,
                             'fitness': obj.final_fitness})


@login_required
@require_GET
async def chat_reply_stream(request):
    """SSE-streamed version of `chat_reply`: yields one event per
    generated token so the browser can paint each character as it
    arrives instead of waiting for the whole completion.

    Async view: per-token CA work runs via ``asyncio.to_thread`` so
    the daphne event loop stays free, and a client disconnect
    (refresh / close tab) propagates as ``CancelledError`` into the
    next ``await`` — no more leaked CLOSE-WAIT generators.

    Default ``n`` lowered 32 → 16 so a leaked stream self-terminates
    in well under a second at the post-optimisation ~18 ms/token rate.
    Bump via ``?n=N`` up to the absolute cap of 128.
    """
    import asyncio
    import json as _json
    import time
    import numpy as np
    from asgiref.sync import sync_to_async
    from .primitives import (
        ca_softmax_sample, ca_embedding, random_rule_table)
    from .transformer import ca_forward_qkv

    q = (request.GET.get('q') or '').strip()
    if not q:
        return _json_response({'reply': '', 'error': 'empty prompt'})
    n           = _clamp_int(request.GET.get('n'),         16,  1, 4096)
    seed        = _clamp_int(request.GET.get('seed'), 0xCAFE,  1, 2**31 - 1)
    try:
        temperature = max(0.0, min(20.0, float(request.GET.get('temperature') or 0.8)))
    except ValueError:
        temperature = 0.8

    prompt_ids = list(q.encode('utf-8'))[:64]
    model_slug = request.GET.get('model') or ''
    dispatched = ''
    composed   = None
    allowed_bytes_pre = _allowed_bytes_for_request(request)
    # Per-prompt dispatch — mirror of chat_reply's priority order:
    # 1. action trigger, 2. exact prompt, 3. prenormalizer, 4. per-word.
    if not model_slug:
        n_blocks = _clamp_int(request.GET.get('n_blocks'), 2, 1, 4)
        from .models import TrainedModel
        trig = await sync_to_async(_resolve_action_trigger)(q)
        if trig is not None:
            t_cfg, payload = trig
            t_slug = t_cfg.get('expert_slug') or ''
            exists = await sync_to_async(
                lambda s: TrainedModel.objects.filter(slug=s).exists())(t_slug) \
                if t_slug else False
            if exists:
                model_slug = t_slug
                dispatched = f"action:{t_cfg.get('phrase','')}"
                n_blocks = _clamp_int(t_cfg.get('n_blocks', n_blocks),
                                          2, 1, 4)
                n = _clamp_int(t_cfg.get('n_tokens', n), n, 1, 4096)
                if payload:
                    q = payload
                    prompt_ids = list(q.encode('utf-8'))[:64]
        if not model_slug:
            d_slug, d_blocks = await sync_to_async(
                _dispatch_qrpair_for_prompt)(q)
            if d_slug:
                model_slug = d_slug
                dispatched = d_slug
                n_blocks = _clamp_int(d_blocks, 2, 1, 4)
        if not model_slug:
            norm = await sync_to_async(_normalize_prompt_to_trained)(q)
            if norm is not None:
                canonical, slug, n_b, dist = norm
                model_slug = slug
                dispatched = (f"normalized:{q!r}→{canonical!r}"
                                f"(d={dist})")
                n_blocks = _clamp_int(n_b, 2, 1, 4)
                q = canonical
                prompt_ids = list(q.encode('utf-8'))[:64]
        if not model_slug:
            composed = await sync_to_async(_compose_per_word_reply)(
                q, temperature=temperature, seed=seed,
                allowed_bytes=allowed_bytes_pre)
        # Cap n to the trained byte count when dispatch routed to a
        # positional pair — same logic as chat_reply.
        if model_slug and 'n' not in request.GET:
            _pr, _np = await sync_to_async(
                _positional_output_rules_for_slug)(model_slug)
            if _pr is not None and _np > 0:
                n = _np
    else:
        n_blocks = _clamp_int(request.GET.get('n_blocks'), 2, 1, 4)

    # Per-word composition short-circuit — stream the composed reply
    # byte-by-byte so the chat UI sees a normal token stream.
    if composed is not None and composed['any_match']:
        async def _compose_stream():
            try:
                yield (
                    'event: meta\ndata: ' + _json.dumps({
                        'prompt_len':  len(q.encode('utf-8')),
                        'n_blocks':    n_blocks,
                        'temperature': temperature,
                        'seed':        seed,
                        'max_tokens':  n,
                        'backbone':    '',
                        'model':       '',
                        'dispatched':  'per-word',
                        'parts':       [
                            {'word': p['word'], 'slug': p['slug'],
                             'matched': p['matched']}
                            for p in composed['parts']
                        ],
                    }) + '\n\n').encode()
                # Flatten per-word output ids + ' ' separators.
                all_ids: list[int] = []
                for i, part in enumerate(composed['parts']):
                    if i > 0:
                        all_ids.append(ord(' '))
                    all_ids.extend(part['tokens']
                                     or list(part['word'].encode('utf-8')))
                t_start = time.time()
                for tick, tok in enumerate(all_ids):
                    yield ('data: ' + _json.dumps({
                        'tick':         tick,
                        'token':        int(tok),
                        'char':         bytes([tok]).decode(
                                              'latin-1', errors='replace'),
                        'last_seq_len': tick + 1,
                        'top3':         [int(tok)],
                        'elapsed_ms':   int((time.time() - t_start) * 1000),
                    }) + '\n\n').encode()
                    await asyncio.sleep(0)  # give the event loop a tick
                yield ('event: done\ndata: ' + _json.dumps({
                    'reply':      composed['reply'],
                    'n_tokens':   len(all_ids),
                    'elapsed_ms': int((time.time() - t_start) * 1000),
                }) + '\n\n').encode()
            except asyncio.CancelledError:
                return
        await sync_to_async(_persist_chat_turn)(
            request, q, composed['reply'], model_slug='', backbone='')
        resp = StreamingHttpResponse(_compose_stream(),
                                          content_type='text/event-stream')
        resp['Cache-Control'] = 'no-cache'
        resp['X-Accel-Buffering'] = 'no'
        return resp
    # Per-position output rules: when this model was deployed from a
    # positional QRPair, swap output_rule per generated token so each
    # output byte uses its own specifically-evolved rule.  Past the
    # last position, fall back to the base output rule.
    # All three helpers hit the ORM, so wrap in sync_to_async for the
    # async view (daphne raises SynchronousOnlyOperation otherwise).
    positional_rules, n_positional = \
        await sync_to_async(_positional_output_rules_for_slug)(model_slug)
    if positional_rules is not None:
        forward_kw = await sync_to_async(_positional_forward_kwargs)(
            model_slug, n_blocks)
        if forward_kw is None:
            forward_kw = await sync_to_async(_trained_model_kwargs)(
                model_slug, n_blocks)
    else:
        forward_kw = await sync_to_async(_trained_model_kwargs)(
            model_slug, n_blocks)
    backbone = (request.GET.get('backbone') or '').strip()
    ca_experts = _clamp_int(request.GET.get('ca_experts'), 0, 0, 3)
    allowed_bytes = _allowed_bytes_for_request(request)
    # When a TrainedModel is loaded, use its embed rule for the live
    # grid panel too — otherwise the panel paints an unrelated random
    # rule's output instead of the actual rule the model is using.
    if forward_kw.get('embed_rule') is not None:
        embed_rule_override = forward_kw['embed_rule']
    else:
        embed_rule_override = None

    want_trace = request.GET.get('trace') == '1'

    def _step(seq, embed_rule, tick):
        """Per-token compute, run on a worker thread."""
        trace = [] if want_trace else None
        if backbone:
            if ca_experts <= 0:
                # LLM-only fast path: ~20-50 ms/token warm regardless
                # of seq_len.  Skip the CA experts that dominate cost.
                from .transformer import real_llm_expert_logits
                logits = real_llm_expert_logits(seq, model_name=backbone,
                                                  vocab_size=256)
                if want_trace:
                    from .primitives import ca_embedding as _ce
                    trace = [{'name': 'embed',
                              'grid': _ce(seq[-1], rule_table=embed_rule),
                              'note': f'LLM-only ({backbone})'}]
            else:
                from .transformer import chat_gpt3_5_hybrid
                expert_specs = (['ca'] * ca_experts) + [('llm', backbone)]
                top_k = min(2, len(expert_specs))
                # Truncate to the CA experts' recent window so step
                # cost stays bounded (see HYBRID_CTX_CAP).
                ctx = seq[-HYBRID_CTX_CAP:]
                logits = chat_gpt3_5_hybrid(
                    ctx, vocab_size=256, base_seed=seed,
                    expert_specs=expert_specs, top_k=top_k)
                if want_trace:
                    from .primitives import ca_embedding as _ce
                    trace = [{'name': 'embed',
                              'grid': _ce(seq[-1], rule_table=embed_rule),
                              'note': f'MoE: {ca_experts} CA + 1 LLM '
                                       f'({backbone})'}]
        else:
            # Positional override: each output token gets its own rule.
            step_kw = dict(forward_kw)
            if positional_rules is not None and tick < n_positional:
                step_kw['output_rule'] = positional_rules[tick]
            logits = ca_forward_qkv(seq, n_blocks=n_blocks,
                                      vocab_size=256, base_seed=seed,
                                      trace=trace,
                                      **step_kw)
        next_id, _noise = ca_softmax_sample(
            logits, temperature=temperature, ca_seed=seed ^ tick,
            allowed_bytes=allowed_bytes)
        grid = ca_embedding(next_id, rule_table=embed_rule)
        top3 = list(map(int, np.argsort(logits)[::-1][:3]))
        # Stringify trace grids to plain int lists so JSON serialises
        # cleanly and the payload stays small (a 16×16 K=4 grid is
        # ~256 numbers per module).
        trace_out = None
        if trace is not None:
            trace_out = []
            for item in trace:
                g = item.get('grid')
                trace_out.append({
                    'name': item['name'],
                    'note': item.get('note', ''),
                    'grid': g.tolist() if g is not None else None,
                })
        return int(next_id), grid, top3, trace_out

    async def stream():
        t0 = time.time()
        try:
            yield (
                'event: meta\ndata: ' + _json.dumps({
                    'prompt_len':  len(prompt_ids),
                    'n_blocks':    n_blocks,
                    'temperature': temperature,
                    'seed':        seed,
                    'max_tokens':  n,
                    'backbone':    backbone,
                    'model':       model_slug,
                    'dispatched':  dispatched,
                }) + '\n\n').encode()

            # Pre-warm the LLM backbone before the per-token loop.  HF
            # model load (~5s for distilgpt2, 30s+ for gpt2-xl) plus
            # the 50k-entry byte-projection table run sync and would
            # otherwise produce a long silent pause before the first
            # token streams — visually indistinguishable from a hang.
            if backbone:
                from .transformer import (_LLM_EXPERT_CACHE,
                                            _LLM_BYTEMAP_CACHE,
                                            _load_llm_expert,
                                            _llm_byte_projection)
                if backbone not in _LLM_EXPERT_CACHE:
                    yield ('event: status\ndata: ' + _json.dumps({
                        'phase': 'load',
                        'msg':   f'loading backbone {backbone}…',
                    }) + '\n\n').encode()
                    try:
                        await asyncio.to_thread(_load_llm_expert, backbone)
                    except Exception as exc:
                        yield ('event: error\ndata: ' + _json.dumps({
                            'msg': f'backbone load failed: {exc!r}',
                        }) + '\n\n').encode()
                        return
                tok = _LLM_EXPERT_CACHE[backbone][0]
                if (id(tok), 256) not in _LLM_BYTEMAP_CACHE:
                    yield ('event: status\ndata: ' + _json.dumps({
                        'phase': 'project',
                        'msg':   f'building byte-projection table '
                                   f'({len(tok)} BPE → 256 bytes)…',
                    }) + '\n\n').encode()
                    await asyncio.to_thread(_llm_byte_projection, tok, 256)
                yield ('event: status\ndata: ' + _json.dumps({
                    'phase': 'ready',
                    'msg':   f'backbone {backbone} ready · '
                              f'{int((time.time() - t0) * 1000)} ms',
                }) + '\n\n').encode()

            embed_rule = random_rule_table(seed)
            seq = list(prompt_ids)
            for tick in range(n):
                next_id, grid, top3, trace = await asyncio.to_thread(
                    _step, seq, embed_rule, tick)
                seq.append(next_id)
                payload = {
                    'tick':         tick,
                    'token':        next_id,
                    'char':         chr(next_id) if 32 <= next_id < 127 else '·',
                    'last_seq_len': len(seq),
                    'last_grid':    grid.tolist(),
                    'top3':         top3,
                    'elapsed_ms':   int((time.time() - t0) * 1000),
                }
                if trace is not None:
                    payload['trace'] = trace
                yield ('data: ' + _json.dumps(payload) + '\n\n').encode()
            full = bytes(seq[len(prompt_ids):]).decode('latin-1',
                                                         errors='replace')
            # Persist this exchange for future chat→corpus training.
            # asyncio.to_thread keeps the (sync) ORM call off the loop.
            try:
                await asyncio.to_thread(
                    _persist_chat_turn, request, q, full,
                    model_slug=request.GET.get('model') or '',
                    backbone=backbone)
            except Exception:
                pass
            yield ('event: end\ndata: ' + _json.dumps({
                'reply':      full,
                'elapsed_ms': int((time.time() - t0) * 1000),
            }) + '\n\n').encode()
        except asyncio.CancelledError:
            return

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


# ── Export the best (or named) TrainedModel as a self-contained
#    64 KB C binary.  Wraps the `emit_tinyformer` management command
#    so the UI can offer a one-click "download the whole model" link.
SIZE_LIMIT = 65_536


@login_required
@require_GET
def train_export(request, slug=None):
    """Emit a TrainedModel as a self-contained .c source (``?format=c``)
    or compile it to a stripped binary (default).

    ``slug='best'`` selects the highest-fitness TrainedModel; an
    explicit slug exports that model.  ``?mode=simple`` skips the
    transformer blocks and bakes only embed+output rules (the smallest
    binary).  Default is the full single-block forward.
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from .models import TrainedModel
    from .management.commands.emit_tinyformer import generate_c_source

    if slug in (None, '', 'best'):
        m = (TrainedModel.objects.order_by('-final_fitness', '-created_at')
                                    .first())
        if m is None:
            return HttpResponseBadRequest(
                'no TrainedModel exists yet — train one first')
    else:
        m = TrainedModel.objects.filter(slug=slug).first()
        if m is None:
            raise Http404(f'no TrainedModel with slug={slug!r}')

    full = (request.GET.get('mode') or 'full').lower() != 'simple'
    want_source = request.GET.get('format') == 'c'

    c_src = generate_c_source(m, full=full)
    if want_source:
        resp = HttpResponse(c_src, content_type='text/x-c')
        resp['Content-Disposition'] = (
            f'attachment; filename=tinyformer-{m.slug}.c')
        resp['X-Source-Bytes'] = str(len(c_src))
        return resp

    cc = shutil.which('cc') or shutil.which('gcc')
    if cc is None:
        return HttpResponse(
            'no C compiler (cc/gcc) on PATH — use ?format=c to download '
            'the source instead.', status=503, content_type='text/plain')

    with tempfile.TemporaryDirectory(prefix='tinyformer-') as td:
        td_path = Path(td)
        c_path = td_path / f'tinyformer-{m.slug}.c'
        bin_path = td_path / f'tinyformer-{m.slug}'
        c_path.write_text(c_src)
        proc = subprocess.run(
            [cc, '-Os', '-s',
             '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
             '-o', str(bin_path), str(c_path), '-lm'],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return HttpResponse(
                f'compile failed (cc returned {proc.returncode}):\n\n'
                + (proc.stderr or proc.stdout),
                status=500, content_type='text/plain')
        blob = bin_path.read_bytes()

    resp = HttpResponse(blob, content_type='application/octet-stream')
    resp['Content-Disposition'] = (
        f'attachment; filename=tinyformer-{m.slug}')
    resp['X-Binary-Size']    = str(len(blob))
    resp['X-Size-Limit']     = str(SIZE_LIMIT)
    resp['X-Under-Limit']    = '1' if len(blob) <= SIZE_LIMIT else '0'
    resp['X-Model-Slug']     = m.slug
    resp['X-Model-Fitness']  = f'{m.final_fitness:.4f}'
    resp['X-Mode']           = 'full' if full else 'simple'
    return resp


# ── Live pipeline visualizer: 8 CAs side-by-side as a chat query flows ──


@ensure_csrf_cookie
@login_required
def pipeline_view(request):
    """Page with 8 named CA canvases + a chat input.  Each canvas
    corresponds to one of the major LLM components and re-paints live
    as the chat query is tokenised and forwarded through the CA
    transformer."""
    from .models import TrainedModel
    trained = list(TrainedModel.objects.order_by('-final_fitness', '-created_at')
                                          .values_list('slug', flat=True))
    return render(request, 'caformer/pipeline.html', {
        'trained_slugs': trained,
        'best_slug':     trained[0] if trained else '',
    })


@login_required
async def pipeline_stream(request):
    """SSE stream: for each generated byte, emit the per-stage CA
    grids that ca_forward_qkv produced when tracing.  The 8 slots
    mirror the 8 major components from components.py:

      embedding     ← trace['embed']
      layer_norm    ← trace['b0-norm-pre'] (first block's input norm)
      projection    ← trace['b0-q']         (Q projection)
      self_attention← trace['b0-mix']       (mix = attended output)
      mlp           ← trace['b0-mlp']
      transformer   ← trace['b0-merge-out'] (full block output)
      softmax       ← trace['output']       (diffused grid → logits)
      output        ← trace['norm-final']   (final layer-norm input)
    """
    import asyncio, json as _json
    from asgiref.sync import sync_to_async
    from django.http import StreamingHttpResponse
    from .primitives import ca_softmax_sample
    from .transformer import ca_forward_qkv

    q_text = (request.GET.get('q') or '').strip()
    if not q_text:
        return _json_response({'ok': False, 'error': 'empty query'})
    max_new = _clamp_int(request.GET.get('n'),        12,  1, 4096)
    n_blocks = _clamp_int(request.GET.get('n_blocks'), 1,  1, 4)
    seed    = _clamp_int(request.GET.get('seed'), 0xCA117E, 1, 2**31 - 1)
    try:
        temperature = max(0.0, min(20.0,
                                     float(request.GET.get('temperature') or 0.8)))
    except ValueError:
        temperature = 0.8
    # _trained_model_kwargs hits the ORM — wrap so the async view
    # doesn't trip SynchronousOnlyOperation.
    forward_kw = await sync_to_async(_trained_model_kwargs)(
        request.GET.get('model'), n_blocks)

    # Slot → trace-name mapping. Built once; the JS uses these keys
    # to update specific canvases.
    SLOT_TO_TRACE = {
        'embedding':      'embed',
        'layer_norm':     'b0-norm-pre',
        'projection':     'b0-q',
        'self_attention': 'b0-mix',
        'mlp':            'b0-mlp',
        'transformer':    'b0-merge-out',
        'softmax':        'output',
        'output':         'norm-final',
    }

    prompt_ids = list(q_text.encode('utf-8'))[:64]

    def _step_with_trace(seq):
        trace: list = []
        logits = ca_forward_qkv(seq, n_blocks=n_blocks,
                                  vocab_size=256, base_seed=seed,
                                  trace=trace, **forward_kw)
        by_name = {t['name']: t['grid'] for t in trace}
        # 8 named slots feed the big panels.
        grids = {}
        for slot, tname in SLOT_TO_TRACE.items():
            g = by_name.get(tname)
            grids[slot] = None if g is None else [
                int(x) & 3 for x in g.flatten().tolist()]
        # Full ordered trace feeds the tiny live-strip thumbnails —
        # one entry per trace stage, in pipeline order, so the strip
        # visualizes the byte's flow from embed through every block
        # to the output head.
        all_grids = []
        for item in trace:
            g = item.get('grid')
            if g is None:
                continue
            all_grids.append({
                'name':  item['name'],
                'cells': [int(x) & 3 for x in g.flatten().tolist()],
            })
        return logits, grids, all_grids

    async def stream():
        seq = list(prompt_ids)
        loop = asyncio.get_running_loop()
        rng_state = seed
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'prompt_len': len(seq),
                'max_new':    max_new,
                'slots':      list(SLOT_TO_TRACE.keys()),
                'model':      request.GET.get('model') or '(random)',
            }) + '\n\n').encode()

            for step_idx in range(max_new):
                logits, grids, all_grids = await asyncio.to_thread(
                    _step_with_trace, list(seq))
                next_id, _noise = ca_softmax_sample(
                    logits, temperature=temperature,
                    ca_seed=(seed ^ (step_idx + 1)))
                next_id = int(next_id)
                seq.append(next_id)
                yield ('event: token\ndata: ' + _json.dumps({
                    'step':      step_idx,
                    'next_byte': next_id,
                    'next_char': chr(next_id) if 32 <= next_id < 127 else '·',
                    'grids':     grids,
                    'all_grids': all_grids,
                }) + '\n\n').encode()

            full = bytes(seq[len(prompt_ids):]).decode('utf-8', errors='replace')
            yield ('event: end\ndata: ' + _json.dumps({
                'reply': full,
                'total_steps': max_new,
            }) + '\n\n').encode()
        except asyncio.CancelledError:
            return

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


# ── Inline Q→R autotrain on the pipeline page ────────────────────────


_PIPELINE_AUTOTRAIN_RESULTS: dict = {}
_PIPELINE_AUTOTRAIN_CAP = 16


@login_required
async def pipeline_autotrain_stream(request):
    """SSE: drive the model toward producing ``expected`` in response
    to ``q`` via the per-position trainer (the same path the CLI's
    ``--positional`` mode uses).  Each output byte gets its own evolved
    output rule, isolating the problem to a single-byte search per
    phase — the regime where the GA reliably converges in seconds.

    Single-rule autotrain (the old default) couldn't shift the rules
    enough in a chat-sized budget for the saved model's output to
    differ from the starting random rules.  Positional fixes that:
    the saved model produces ``expected`` byte-for-byte on the next
    chat send (assuming all phases converged).

    Maps positional events onto the existing event names the chat JS
    listens for: meta → meta; phase_end → gen+ind; positional_done →
    end. So the template needs no changes.
    """
    import asyncio, json as _json, time
    from asgiref.sync import sync_to_async
    from django.http import StreamingHttpResponse
    from .qr_trainer import (PositionalTrainConfig,
                                train_pair_positional)

    q_text   = (request.GET.get('q') or '').strip()
    expected = (request.GET.get('expected') or '').strip()
    if not q_text or not expected:
        return _json_response({'ok': False,
                                 'error': 'need both q and expected'})
    # Match the CLI's proven positional defaults (pop=24, gens=40):
    # those settings converged hi→hello to argmax-exact in ~50 s.
    # Smaller values are exposed via the UI for quick experiments,
    # but the defaults must actually converge or the saved model
    # produces the same garbage as the random starting rules.
    pop_size    = _clamp_int(request.GET.get('pop'),    24,  4, 48)
    gens_phase  = _clamp_int(request.GET.get('gens'),   40,  4, 100)
    polish_n    = _clamp_int(request.GET.get('pol'),   200, 20, 400)
    try:
        mut_rate = max(0.001, min(0.2,
                            float(request.GET.get('mut') or 0.012)))
    except ValueError:
        mut_rate = 0.012
    n_blocks    = _clamp_int(request.GET.get('n_blocks'),    1,  1, 4)
    seed        = _clamp_int(request.GET.get('seed'), 0xCAFE_AB, 1, 2**31 - 1)
    base_slug   = (request.GET.get('model') or '').strip()
    max_seconds = _clamp_int(request.GET.get('budget'), 600, 30, 1800)

    # Get-or-create the QRPair so the positional trainer can persist
    # progress + so save can just deploy the row.
    def _ensure_pair():
        from .models import QRPair
        pair = QRPair.objects.filter(prompt=q_text,
                                      expected=expected).first()
        if pair is None:
            pair = QRPair.objects.create(
                prompt=q_text, expected=expected,
                n_blocks=n_blocks, label='chat-autotrain')
        return pair

    pair = await sync_to_async(_ensure_pair)()
    n_positions = len(expected.encode('utf-8'))

    cfg = PositionalTrainConfig(
        pop_size=pop_size, gens_per_phase=gens_phase,
        polish_trials=polish_n, mutation_rate=mut_rate, argmax_bonus=5.0,
        max_seconds=float(max_seconds),
        base_seed=seed, out_seed=seed ^ 0xC0FFEE)

    async def stream():
        loop = asyncio.get_running_loop()
        evt_q: asyncio.Queue = asyncio.Queue()

        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'pop_size':    pop_size,
                'generations': gens_phase,
                'q':           q_text[:120],
                'expected':    expected[:120],
                'base_model':  f'positional · {n_positions} phases',
                # JS divides progress by total_evals; one tick per
                # position keeps the bar in sync with phase_end events.
                'total_evals': n_positions,
            }) + '\n\n').encode()

            t0 = time.time()

            def _on_event(kind, payload):
                # Hand off to the asyncio queue from the worker thread.
                loop.call_soon_threadsafe(evt_q.put_nowait,
                                            (kind, payload))

            async def _runner():
                try:
                    result = await asyncio.to_thread(
                        train_pair_positional, pair.pk,
                        cfg=cfg, on_event=_on_event)
                    await evt_q.put(('__done__', result))
                except Exception as e:
                    import traceback as _tb
                    await evt_q.put(('__error__',
                                       f'{e!r} :: {_tb.format_exc()[-400:]}'))

            run_task = asyncio.create_task(_runner())
            result = None
            # Track the current phase so the heartbeat can describe what
            # the trainer is working on right now — much better for
            # classroom demos than a blank stare during the 10-30s GA
            # run per target byte.
            cur_phase: dict = {'pos': None, 'char': None, 'started': t0}
            n_pos_total = n_positions
            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(
                            evt_q.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Mid-phase heartbeat — emit a status event with
                        # the current byte target + elapsed time so the
                        # UI updates every second instead of looking
                        # frozen during the GA's silent inner loop.
                        if cur_phase['pos'] is not None:
                            elapsed = time.time() - cur_phase['started']
                            phase_elapsed = (time.time()
                                                 - cur_phase['phase_t0'])
                            yield ('event: status\ndata: ' + _json.dumps({
                                'phase':   'working',
                                'pos':     cur_phase['pos'],
                                'n_pos':   n_pos_total,
                                'char':    cur_phase['char'],
                                'phase_s': round(phase_elapsed, 1),
                                'total_s': round(elapsed, 1),
                                'msg':     (f"evolving byte "
                                              f"{cur_phase['pos']+1}/"
                                              f"{n_pos_total} → "
                                              f"{cur_phase['char']!r} · "
                                              f"phase {phase_elapsed:.1f}s "
                                              f"· total {elapsed:.1f}s"),
                            }) + '\n\n').encode()
                        else:
                            yield b': heartbeat\n\n'
                        continue
                    if kind == '__done__':
                        result = payload
                        break
                    if kind == '__error__':
                        yield ('event: error\ndata: ' + _json.dumps(
                            {'msg': payload}) + '\n\n').encode()
                        return
                    # Translate positional events → chat-JS-friendly.
                    if kind == 'phase_begin':
                        cur_phase['pos']    = payload['pos']
                        cur_phase['char']   = payload.get('target_char',
                                                            '?')
                        cur_phase['phase_t0'] = time.time()
                        # Light progress nudge so the user sees "gen N
                        # · ind N" before the phase finishes.
                        out = ('event: ind\ndata: ' + _json.dumps({
                            'gen':      payload['pos'],
                            'ind':      payload['pos'],
                            'fitness':  0.0,
                            'elapsed_ms': int(
                                payload.get('elapsed_s', 0) * 1000),
                            'char':     cur_phase['char'],
                            'n_pos':    n_pos_total,
                        }) + '\n\n').encode()
                    elif kind == 'phase_end':
                        # Bar advances one slot per completed position.
                        f = float(payload['fitness'])
                        out = ('event: gen\ndata: ' + _json.dumps({
                            'gen':   payload['pos'] + 1,
                            'best':  f,
                            'mean':  f,
                            'worst': f,
                            'elapsed_ms': int(
                                payload.get('elapsed_s', 0) * 1000),
                            'argmax': payload.get('argmax_char', ''),
                            'target': cur_phase['char'],
                            'match':  bool(payload.get('match', False)),
                            'n_pos':  n_pos_total,
                        }) + '\n\n').encode()
                    elif kind == 'phase_failed':
                        out = ('event: status\ndata: ' + _json.dumps({
                            'phase': 'failed',
                            'msg':   payload.get('note', ''),
                        }) + '\n\n').encode()
                    elif kind == 'positional_start':
                        out = ('event: status\ndata: ' + _json.dumps({
                            'phase': 'start',
                            'msg':   f'positional · {payload["n_positions"]} '
                                       f'phases · budget '
                                       f'{int(payload["budget_s"])}s',
                        }) + '\n\n').encode()
                    elif kind == 'positional_done':
                        # Folded into the final 'end' event below.
                        out = None
                    else:
                        out = None
                    if out is not None:
                        yield out
            finally:
                if not run_task.done():
                    run_task.cancel()

            # Stash the pair pk so the save endpoint just deploys.
            sk = (getattr(getattr(request, 'session', None),
                             'session_key', None) or 'anon')
            if len(_PIPELINE_AUTOTRAIN_RESULTS) >= _PIPELINE_AUTOTRAIN_CAP:
                _PIPELINE_AUTOTRAIN_RESULTS.pop(
                    next(iter(_PIPELINE_AUTOTRAIN_RESULTS)))
            _PIPELINE_AUTOTRAIN_RESULTS[sk] = {
                'pair_pk':  pair.pk,
                'fitness':  float(result.get('completed_positions', 0)),
                'q':        q_text,
                'expected': expected,
                'exact':    bool(result.get('exact')),
                'sampled':  result.get('sampled', ''),
                'mode':     'positional',
            }
            # The positional trainer auto-deploys on best_exact (see
            # qr_trainer._persist_positional), so the pair is already in
            # the dispatcher pool by now.  Surface the deployed slug to
            # the chat UI so it can show "training-complete · now
            # routable" without requiring the user to click save+use.
            def _refresh_deployed():
                from .models import QRPair
                p = QRPair.objects.filter(pk=pair.pk).first()
                return p.deployed_slug if p else ''
            deployed_slug = await sync_to_async(_refresh_deployed)()
            yield ('event: end\ndata: ' + _json.dumps({
                'best_fitness':   float(result.get('completed_positions', 0)),
                'exact':          bool(result.get('exact')),
                'sampled':        result.get('sampled', ''),
                'elapsed_ms':     int((time.time() - t0) * 1000),
                'savable':        True,
                'auto_deployed':  bool(deployed_slug),
                'deployed_slug':  deployed_slug,
                'prompt':         q_text,
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
def pipeline_autotrain_save(request):
    """Persist the most recent autotrain result as a deployed
    TrainedModel.  The stream endpoint now uses the per-position
    trainer, which already saved its work to the QRPair row — this
    handler just deploys that pair so its slug shows up in the chat
    model dropdown and the next reply uses the per-position rules.
    """
    if request.method != 'POST':
        return _json_response({'ok': False, 'error': 'POST only'})
    sk = request.session.session_key or 'anon'
    payload = _PIPELINE_AUTOTRAIN_RESULTS.get(sk)
    if payload is None:
        return _json_response({'ok': False,
            'error': 'no autotrain result in this session — run one first'})
    if 'pair_pk' not in payload:
        return _json_response({'ok': False,
            'error': 'autotrain result is from the old single-rule path; '
                       'run autotrain again to use the positional trainer'})
    obj = _deploy_qr_pair(payload['pair_pk'])
    if obj is None:
        return _json_response({'ok': False,
            'error': 'deploy failed — QRPair has no best genome yet'})
    return _json_response({
        'ok': True,
        'slug':    obj.slug,
        'fitness': float(payload.get('fitness', 0.0)),
        'exact':   bool(payload.get('exact', False)),
        'sampled': payload.get('sampled', ''),
    })


# ── Per-component autotournament: continuously evolve all 8 components ──


@ensure_csrf_cookie
@login_required
def champions(request):
    """Leaderboard of best ComponentChampion per component + history.

    ``@ensure_csrf_cookie`` so the JS POST to /champions/compose/
    (which assembles the 8 component champions into a TrainedModel)
    can read csrftoken from document.cookie on a fresh load."""
    from .models import ComponentChampion
    from .component_fitness import COMPONENT_SPECS, COMPONENT_ROTATION

    rows = []
    for slug in COMPONENT_ROTATION:
        spec = COMPONENT_SPECS[slug]
        best = ComponentChampion.best_for(slug)
        recent = list(
            ComponentChampion.objects.filter(component_slug=slug)
                                       .order_by('-created_at')[:6])
        rows.append({
            'slug':     slug,
            'spec':     spec,
            'best':     best,
            'recent':   recent,
            'count':    ComponentChampion.objects.filter(
                            component_slug=slug).count(),
        })
    return render(request, 'caformer/champions.html', {
        'rows':       rows,
        'total':      ComponentChampion.objects.count(),
        'all_recent': ComponentChampion.objects.order_by('-created_at')[:30],
    })


# ── Q→R curated pair trainer (long-running) ──────────────────────────


@ensure_csrf_cookie
@login_required
def qr_index(request):
    """List + add Q→R pairs.  Each row shows the trainer's current
    best output + fitness + whether exact-match has been reached.

    POST handles add/delete (small forms inline)."""
    from .models import QRPair
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'add':
            prompt = (request.POST.get('prompt') or '').strip()
            expected = (request.POST.get('expected') or '').strip()
            n_blocks = max(1, min(4,
                int(request.POST.get('n_blocks') or 1)))
            if prompt and expected:
                QRPair.objects.create(
                    prompt=prompt, expected=expected,
                    n_blocks=n_blocks,
                    label=(request.POST.get('label') or '').strip())
        elif action == 'delete':
            pk = request.POST.get('pk') or ''
            if pk.isdigit():
                QRPair.objects.filter(pk=int(pk)).delete()
        elif action == 'reset':
            pk = request.POST.get('pk') or ''
            if pk.isdigit():
                QRPair.objects.filter(pk=int(pk)).update(
                    best_fitness=-1e9, best_genome_blob=None,
                    best_output='', best_exact=False, n_evals=0,
                    total_seconds=0.0, restarts=0, last_phase='')
        elif action == 'deploy':
            pk = request.POST.get('pk') or ''
            if pk.isdigit():
                _deploy_qr_pair(int(pk))
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(request.path)
    return render(request, 'caformer/qr_index.html', {
        'pairs': QRPair.objects.all(),
    })


def _deploy_qr_pair(pk: int):
    """Create a TrainedModel from a QRPair's best genome so the chat
    UI can select it.

    Positional QRPairs (per-position output rules) are stored under a
    qr-positional-<slug> name; the chat infers positional mode by
    looking up the matching QRPair row at generation time.

    Idempotent: if this pair already has a deployed TrainedModel,
    return that one instead of None (the previous behaviour caused the
    manual 'save' button to error-report 'no best genome yet' after
    auto-deploy had already happened during training)."""
    from .models import QRPair, TrainedModel
    from .ga import save_genome_as_model
    pair = QRPair.objects.filter(pk=pk).first()
    if pair is None or pair.best_genome_blob is None:
        return
    if pair.deployed_slug:
        existing = TrainedModel.objects.filter(slug=pair.deployed_slug).first()
        if existing:
            return existing
    genome = pair.best_genome()
    if genome is None:
        return
    import re, time as _time
    safe = re.sub(r'[^a-z0-9]+', '-',
                     (pair.prompt + '-' + pair.expected).lower()).strip('-')[:30]
    is_pos = pair.is_positional()
    prefix = 'qr-positional' if is_pos else 'qr'
    slug = (f'{prefix}-{safe}-{int(_time.time()) % 100000}')[:60]
    mode = 'positional' if is_pos else 'single-rule'
    name = (f'Q→R [{mode}]: {pair.prompt!r} → {pair.expected!r}'
              + (' ✓' if pair.best_exact else ''))[:80]
    obj = save_genome_as_model(
        genome, name=name, slug=slug,
        notes=(f'Deployed from QRPair pk={pair.pk} ({mode}). '
                  f'fitness={pair.best_fitness:.4f}, '
                  f'output={pair.best_output!r}, '
                  f'exact={pair.best_exact}.'),
        corpus_excerpt=(
            f'user: {pair.prompt}\nca: {pair.expected}\n\n'),
        n_blocks=pair.n_blocks, pop_size=0, generations=0,
        final_fitness=float(pair.best_fitness), history=[])
    pair.deployed_slug = obj.slug
    pair.save(update_fields=['deployed_slug'])
    return obj


@login_required
def champions_library(request):
    """Paginated browser of every ComponentChampion row.  Filters by
    component slug + sort order so a large library (60k+) stays
    navigable.  Default sort: latest first."""
    from django.core.paginator import Paginator
    from .models import ComponentChampion
    from .component_fitness import COMPONENT_SPECS

    qs = ComponentChampion.objects.all()
    slug = (request.GET.get('component') or '').strip()
    if slug and slug in COMPONENT_SPECS:
        qs = qs.filter(component_slug=slug)
    label = (request.GET.get('label') or '').strip()
    if label:
        qs = qs.filter(run_label=label)
    sort = request.GET.get('sort') or 'recent'
    ORDER = {
        'recent':   '-created_at',
        'fitness':  '-fitness',
        'lineage':  '-generation',
        'oldest':   'created_at',
    }
    qs = qs.order_by(ORDER.get(sort, '-created_at'))

    per_page = max(20, min(200, int(request.GET.get('per_page') or 50)))
    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page') or 1)

    # Per-component totals for the filter UI — attached to each spec
    # so the template can iterate without needing a custom dict-lookup
    # filter.
    specs_with_counts = [
        {'slug': s.slug, 'description': s.description,
         'count': ComponentChampion.objects.filter(
                      component_slug=s.slug).count()}
        for s in COMPONENT_SPECS.values()
    ]

    return render(request, 'caformer/champions_library.html', {
        'page':       page,
        'paginator':  paginator,
        'total':      ComponentChampion.objects.count(),
        'specs':      specs_with_counts,
        'cur_slug':   slug,
        'cur_label':  label,
        'cur_sort':   sort,
    })


@login_required
def champions_compose(request):
    """POST: assemble the 10 FULL_STACK rules by pulling each from its
    most specific available ComponentChampion, save as a new
    TrainedModel, return the slug + a resolution table so the UI can
    show which component each rule came from."""
    if request.method != 'POST':
        return _json_response({'ok': False, 'error': 'POST only'})
    from .component_tournament import compose_champions
    from .ga import save_genome_as_model

    genome, resolution = compose_champions()
    n_real = sum(1 for r in resolution if not r['random'])

    name = (request.POST.get('name') or '').strip()
    slug = (request.POST.get('slug') or '').strip()
    if not name or not slug:
        import time as _time
        ts = int(_time.time()) % 100000
        slug = f'composed-champions-{ts}'
        name = (f'composed champions ({n_real}/10 evolved · ts {ts})')[:80]

    parts = [(f'{r["rule"]}←{r["source"]}'
                + (f' g{r["generation"]} f={r["fitness"]:.3f}'
                    if not r['random'] else ''))
              for r in resolution]
    notes = (f'Composed from per-component champions. '
              f'{n_real}/10 rules from real champions, '
              f'{10 - n_real} random fallbacks. '
              f'Resolution: {"; ".join(parts)}.')
    obj = save_genome_as_model(
        genome, name=name[:80], slug=slug[:80], notes=notes,
        corpus_excerpt='',           # not corpus-trained
        n_blocks=1, pop_size=0, generations=0,
        final_fitness=0.0, history=[])
    return _json_response({
        'ok':         True,
        'slug':       obj.slug,
        'name':       obj.name,
        'n_real':     n_real,
        'n_random':   10 - n_real,
        'resolution': resolution,
    })


@login_required
async def champions_stream(request):
    """SSE-streamed autotournament run.  Each cycle's begin/end fires
    as an event; the saved-champion event lets the UI update the
    leaderboard in place."""
    import asyncio, json as _json
    from django.http import StreamingHttpResponse
    from .component_tournament import (
        ComponentTournamentConfig, run_autotournament,
    )

    def _ci(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.GET.get(name) or default)))
        except (TypeError, ValueError):
            return default

    cfg = ComponentTournamentConfig(
        pop_size=_ci('pop', 8, 4, 32),
        generations=_ci('gens', 6, 1, 30),
        mutation_rate=float(request.GET.get('mutation') or 0.005),
        seed=_ci('seed', 0xC0FFEE_CA, 1, 2**31 - 1),
        max_cycles=_ci('cycles', 1, 1, 100),
        max_seconds=float(request.GET.get('budget') or 0.0),
        only_components=tuple(
            s.strip() for s in (request.GET.get('only') or '').split(',')
            if s.strip()),
        skip_components=tuple(
            s.strip() for s in (request.GET.get('skip') or '').split(',')
            if s.strip()),
        run_label=(request.GET.get('label') or 'web'),
        save_all_individuals=(request.GET.get('save_all') == '1'),
    )

    async def stream():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def _emit(kind, payload):
            loop.call_soon_threadsafe(q.put_nowait, (kind, payload))

        async def _runner():
            try:
                report = await asyncio.to_thread(
                    run_autotournament, cfg, _emit)
                _emit('__done__', {
                    'cycles': len(report.cycles),
                    'improvements': sum(1 for c in report.cycles if c.improved),
                    'total_seconds': report.total_seconds,
                })
            except Exception as e:
                _emit('error', {'msg': repr(e)})
                _emit('__done__', None)

        run_task = asyncio.create_task(_runner())
        # Heartbeat: if no event arrives for this long, emit an SSE
        # comment line so the browser knows the connection is alive and
        # the run hasn't silently wedged on a slow fitness.  Stays under
        # nginx's typical 60s read timeout.
        heartbeat_after = 5.0
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(
                        q.get(), timeout=heartbeat_after)
                except asyncio.TimeoutError:
                    # Comment-only line is a no-op for EventSource but
                    # keeps the TCP stream + intermediaries warm.
                    yield b': heartbeat\n\n'
                    continue
                if kind == '__done__':
                    if payload is not None:
                        yield ('event: end\ndata: ' + _json.dumps(payload)
                                + '\n\n').encode()
                    return
                yield (f'event: {kind}\ndata: ' + _json.dumps(payload)
                        + '\n\n').encode()
        except asyncio.CancelledError:
            return
        finally:
            if not run_task.done():
                run_task.cancel()

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


@login_required
@require_GET
def rules_json(request, slug=None):
    """Serve a TrainedModel's 10 rule tables as 2-bit-packed base64
    blobs for the mechanism diagrams' JS hex-CA stepper.

    ``slug='best'`` (or no slug) picks the highest-fitness model.  Each
    rule is 4,096 bytes packed (16,384 K=4 entries, 4 per byte) → ~5 KB
    of base64 per rule × 10 rules = ~55 KB of JSON.
    """
    import base64
    from django.http import JsonResponse
    from .models import TrainedModel
    from .management.commands.emit_tinyformer import _pack_2bit

    if slug in (None, '', 'best'):
        m = (TrainedModel.objects.order_by('-final_fitness', '-created_at')
                                    .first())
        if m is None:
            return JsonResponse({'ok': False, 'error': 'no TrainedModels'},
                                  status=404)
    else:
        m = TrainedModel.objects.filter(slug=slug).first()
        if m is None:
            return JsonResponse({'ok': False, 'error': 'unknown slug'},
                                  status=404)

    names = ['embed', 'q', 'k', 'v', 'score', 'mix',
             'merge', 'mlp', 'norm', 'output']
    rules = {}
    for n in names:
        raw = bytes(getattr(m, f'rule_{n}'))
        rules[n] = base64.b64encode(_pack_2bit(raw)).decode('ascii')
    return JsonResponse({
        'ok':    True,
        'meta':  {
            'slug':     m.slug,
            'name':     m.name,
            'fitness':  m.final_fitness,
            'n_blocks': m.n_blocks,
            'created':  m.created_at.isoformat(),
        },
        'rules': rules,
    })

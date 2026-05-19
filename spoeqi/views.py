"""spoeqi views — list, create, detail.

The detail page is the substantive surface: it hands a Pact's seed,
rule, palette, and launch time to client-side JS that runs the 64
component CAs in lockstep.  The server is otherwise inert; it does
not stream state.
"""

from __future__ import annotations
import hashlib
import json
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Pact,
    COMPONENTS,
    COMPONENT_GRID,
    COMPONENT_GRID_CHOICES,
    RULE_TABLE_SIZE,
    DEFAULT_PALETTE,
    _random_rule,
    _identity_rule,
    compile_det_rule,
    is_per_component_palette,
    random_palette,
    random_palette_per_component,
    synthesise_rules_fleet,
    synthesise_rules_mutated,
)


# Threshold above which a candidate counts as "banded enough" for the
# horizon-only filter.  Set from empirical observation: in use_only
# mode the top of the pile sits around 0.20; values above ~0.15 are
# clearly striped rather than noise.
_HORIZON_BAND_THRESHOLD = 0.15


def _apply_horizon_pref(qs, horizon_pref: str):
    """Annotate / filter / sort a Det Candidate queryset by horizon-
    band preference.

    horizon_pref values:
      'any'     — no change (default; rank by class-4 score)
      'prefer'  — annotate horizon_band, sort banded candidates first
                  then by score (tie-breaker)
      'only'    — keep only candidates whose horizon_band ≥ threshold
    """
    from django.db.models import F, FloatField
    from django.db.models.functions import Cast
    # Pull the JSON key into a real float column so we can sort/filter
    # on it.  Candidates scored before the horizon metric existed have
    # NULL here — they sort last in DESC and are excluded by 'only'.
    qs = qs.annotate(
        horizon_band=Cast(F('analysis__horizon_band'), FloatField()))
    if horizon_pref == 'prefer':
        return qs.order_by(F('horizon_band').desc(nulls_last=True),
                           '-score')
    if horizon_pref == 'only':
        return qs.filter(horizon_band__gte=_HORIZON_BAND_THRESHOLD) \
                 .order_by('-horizon_band', '-score')
    return qs.order_by('-score')


def _det_class4_candidates(limit: int = 20, horizon_pref: str = 'any'):
    """Top class-4 candidates from Det with n_colors=4 — these compile
    directly into the 4-state spoeqi rule table without quantising.
    Returns a list of {id, score, n_rules, source} dicts for the form;
    swallowing import errors so spoeqi still works in environments
    where Det isn't migrated.

    In `only` mode the class-4 label filter is dropped — bands are
    the user's goal and a 'use_only' Det search produces banded
    candidates that don't reach the class-4 threshold (their score is
    the scaled horizon-band value, not the multi-signal class-4 sum).
    """
    try:
        from det.models import Candidate
        qs = Candidate.objects.filter(run__n_colors=4)
        if horizon_pref != 'only':
            qs = qs.filter(est_class='class4')
        qs = qs.select_related('run')
        qs = _apply_horizon_pref(qs, horizon_pref)[:limit]
        out = []
        for c in qs:
            hb = getattr(c, 'horizon_band', None)
            hb_tag = f' · band {hb:.2f}' if hb is not None else ''
            out.append({
                'id': c.id, 'score': c.score, 'n_rules': c.n_rules,
                'source': f'Det run {c.run_id}',
                'horizon_band': hb,
                'label': f'#{c.id}  score {c.score:.2f}{hb_tag}  '
                         f'({c.n_rules} rules, {c.run.wildcard_pct}% wildcard)',
            })
        return out
    except Exception:
        return []


def _det_class4_pool_size(horizon_pref: str = 'any') -> int:
    """Total candidates available for fleet sampling under the given
    horizon preference.  'only' drops the class-4 label filter; see
    `_det_class4_candidates` for why."""
    try:
        from det.models import Candidate
        qs = Candidate.objects.filter(run__n_colors=4)
        if horizon_pref != 'only':
            qs = qs.filter(est_class='class4')
        qs = _apply_horizon_pref(qs, horizon_pref)
        return qs.count()
    except Exception:
        return 0


def _sample_fleet_candidate_ids(rng, horizon_pref: str = 'any'):
    """Sample exactly COMPONENTS Det Candidate IDs from the matching
    pool.  Sampling is with-replacement when the pool is smaller than
    64 — better to duplicate a few rules than fail.

    Under 'prefer' the pool is unchanged (sorting matters at display
    time, not for an unbiased draw).  Under 'only' the class-4 filter
    is dropped and only banded candidates remain.
    """
    from det.models import Candidate
    qs = Candidate.objects.filter(run__n_colors=4)
    if horizon_pref != 'only':
        qs = qs.filter(est_class='class4')
    if horizon_pref == 'only':
        qs = _apply_horizon_pref(qs, 'only')
    pool_ids = list(qs.values_list('id', flat=True))
    if not pool_ids:
        raise ValueError('No 4-colour class-4 Det candidates available '
                         f'(horizon_pref={horizon_pref}).')
    if len(pool_ids) >= COMPONENTS:
        return rng.sample(pool_ids, COMPONENTS)
    # With-replacement fallback
    return [rng.choice(pool_ids) for _ in range(COMPONENTS)]


def index(request):
    pacts = Pact.objects.all()[:200]
    return render(request, 'spoeqi/index.html', {
        'pacts': pacts,
        'components': COMPONENTS,
        'component_grid': COMPONENT_GRID,
    })


def _parse_palette(raw):
    """Accept a JSON list of 4 [r,g,b] entries; reject anything else."""
    try:
        pal = json.loads(raw)
        if (isinstance(pal, list) and len(pal) == 4
                and all(isinstance(c, list) and len(c) == 3
                        and all(0 <= int(x) <= 255 for x in c) for c in pal)):
            return [[int(c[0]), int(c[1]), int(c[2])] for c in pal]
    except (ValueError, TypeError):
        pass
    return None


def _parse_rule(raw: str) -> bytes | None:
    """Accept a JSON array of 16384 ints in {0,1,2,3}, or a hex blob
    of exactly 32768 chars.  Returns canonical bytes or None.
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    # Hex form is far more compact for paste; try it first.
    if all(c in '0123456789abcdefABCDEF' for c in raw):
        if len(raw) == RULE_TABLE_SIZE * 2:
            try:
                b = bytes.fromhex(raw)
                if all(v <= 3 for v in b):
                    return b
            except ValueError:
                return None
        return None
    # JSON array fallback.
    try:
        arr = json.loads(raw)
    except ValueError:
        return None
    if not (isinstance(arr, list) and len(arr) == RULE_TABLE_SIZE):
        return None
    try:
        return bytes(int(v) & 0x03 for v in arr)
    except (TypeError, ValueError):
        return None


def _parse_seed(raw: str) -> bytes | None:
    """Accept a 128-char hex string (= 64 bytes) or a comma/whitespace
    list of 64 integers.  Returns canonical bytes or None.
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    # Hex form.
    flat = ''.join(raw.split())
    if all(c in '0123456789abcdefABCDEF' for c in flat) and len(flat) == COMPONENTS * 2:
        try:
            return bytes.fromhex(flat)
        except ValueError:
            return None
    # Integer list fallback.
    parts = [p for p in raw.replace(',', ' ').split() if p]
    if len(parts) != COMPONENTS:
        return None
    try:
        return bytes(int(p) & 0xFF for p in parts)
    except ValueError:
        return None


def create(request):
    errors = []
    # horizon_pref controls how Det candidates are filtered/ordered.
    # Read from POST when the user is submitting, otherwise from the
    # GET query string so the user can change the filter before
    # picking a candidate.
    horizon_pref = (request.POST.get('horizon_pref')
                    or request.GET.get('horizon_pref')
                    or 'any')
    if horizon_pref not in {'any', 'prefer', 'only'}:
        horizon_pref = 'any'
    det_candidates = _det_class4_candidates(horizon_pref=horizon_pref)
    fleet_pool = _det_class4_pool_size(horizon_pref=horizon_pref)
    default_mode = 'det' if det_candidates else 'random'
    default_det_id = det_candidates[0]['id'] if det_candidates else ''
    form = {
        'name': '', 'party_a': 'Alice', 'party_b': 'Bob',
        'clock_model': 'synced', 'tick_ms': '180',
        'component_grid': str(COMPONENT_GRID),
        'seed_mode': 'random', 'seed_text': '',
        'rule_mode': default_mode, 'rule_text': '',
        'det_candidate_id': str(default_det_id),
        'rule_diversity': 'shared',
        'mutation_density': '1024',
        'palette_mode': 'default',
        'palette_text': json.dumps(DEFAULT_PALETTE),
        'notes': '',
        'horizon_pref': horizon_pref,
    }

    # Repopulate the form from POST when the user is submitting, or
    # from GET when the user just clicked a horizon_pref radio (which
    # GET-submits the whole form so the candidate list re-renders).
    # The actual save/validate path stays gated on POST below.
    if request.method == 'POST':
        form.update({k: request.POST.get(k, form.get(k, '')) for k in form})
    elif request.method == 'GET' and request.GET:
        form.update({k: request.GET.get(k, form.get(k, '')) for k in form
                      if k in request.GET})

    if request.method == 'POST':
        if not form['name'].strip():
            errors.append('A name is required.')

        # Seed
        if form['seed_mode'] == 'paste':
            seed = _parse_seed(form['seed_text'])
            if seed is None:
                errors.append('Seed must be 128 hex chars or 64 '
                              'comma/whitespace-separated integers.')
        else:
            seed = secrets.token_bytes(COMPONENTS)

        # Rule
        rule = None
        det_candidate = None
        if form['rule_mode'] == 'paste':
            rule = _parse_rule(form['rule_text'])
            if rule is None:
                errors.append('Rule must be 32768 hex chars or a JSON '
                              'array of 16384 integers in {0,1,2,3}.')
        elif form['rule_mode'] == 'random':
            rule = _random_rule()
        elif form['rule_mode'] == 'det':
            try:
                from det.models import Candidate
                cid = int(form['det_candidate_id'])
                det_candidate = Candidate.objects.get(pk=cid)
                if det_candidate.run.n_colors != 4:
                    errors.append('Selected Det candidate has '
                                  f'n_colors={det_candidate.run.n_colors}; '
                                  'only 4-colour candidates compile cleanly.')
                else:
                    rule = compile_det_rule(det_candidate.rules_json)
            except (ValueError, KeyError):
                errors.append('Pick a Det class-4 candidate or switch mode.')
            except Exception as exc:
                errors.append(f'Could not load Det candidate: {exc}')
        else:
            rule = _identity_rule()

        # Palette
        palette_mode = form.get('palette_mode', 'default')
        if palette_mode == 'random':
            palette = random_palette()
        elif palette_mode == 'random_per_component':
            palette = random_palette_per_component()
        elif palette_mode == 'custom':
            palette = _parse_palette(form['palette_text']) or DEFAULT_PALETTE
        else:
            palette = [row[:] for row in DEFAULT_PALETTE]

        # tick_ms
        try:
            tick_ms = max(20, min(5000, int(form['tick_ms'])))
        except ValueError:
            tick_ms = 180

        # component_grid
        valid_grids = {n for n, _ in COMPONENT_GRID_CHOICES}
        try:
            component_grid = int(form['component_grid'])
        except (ValueError, TypeError):
            component_grid = COMPONENT_GRID
        if component_grid not in valid_grids:
            component_grid = COMPONENT_GRID

        # rule_diversity + mutation_density
        if form['rule_diversity'] not in ('shared', 'mutated', 'fleet'):
            form['rule_diversity'] = 'shared'
        rule_diversity = form['rule_diversity']
        try:
            mutation_density = max(0, min(8192, int(form['mutation_density'])))
        except (ValueError, TypeError):
            mutation_density = 1024

        # Per-component rule synthesis.  Only meaningful once we have
        # a base rule (`rule`) populated; the synthesis happens
        # *after* the per-rule-mode block above.  Default to None;
        # filled in below if applicable.
        rules_snapshot = None

        # Apply rule_diversity now that we have `rule` (the base).
        fleet_candidate_ids = None
        if not errors and rule is not None:
            try:
                if rule_diversity == 'mutated':
                    rules_snapshot = synthesise_rules_mutated(
                        rule, mutation_density,
                        master_seed=int.from_bytes(seed[:8], 'big'))
                elif rule_diversity == 'fleet':
                    import random as _r
                    rng = _r.Random(int.from_bytes(seed[:8], 'big'))
                    cand_ids = _sample_fleet_candidate_ids(
                        rng, horizon_pref=horizon_pref)
                    rules_snapshot = synthesise_rules_fleet(cand_ids)
                    fleet_candidate_ids = list(cand_ids)
                    # Bookkeeping: keep rule_snapshot as the first one
                    # so any single-rule reader still gets a sensible
                    # value, and surface provenance via det_candidate.
                    rule = rules_snapshot[:RULE_TABLE_SIZE]
                    if det_candidate is None:
                        from det.models import Candidate
                        det_candidate = Candidate.objects.filter(
                            pk=cand_ids[0]).first()
            except Exception as exc:
                errors.append(f'Rule synthesis ({rule_diversity}) failed: {exc}')

        if not errors:
            pact = Pact(
                name=form['name'].strip(),
                party_a=form['party_a'].strip() or 'Alice',
                party_b=form['party_b'].strip() or 'Bob',
                seed_matrix=seed,
                rule_snapshot=rule,
                rules_snapshot=rules_snapshot,
                rule_diversity=rule_diversity,
                mutation_density=mutation_density,
                palette=palette,
                clock_model=form['clock_model']
                            if form['clock_model'] in ('synced', 'local')
                            else 'synced',
                tick_ms=tick_ms,
                component_grid=component_grid,
                launch_time=timezone.now(),
                notes=form['notes'].strip(),
                det_candidate=det_candidate,
                fleet_candidate_ids=fleet_candidate_ids,
                created_by=request.user if request.user.is_authenticated else None,
            )
            pact.save()
            messages.success(request,
                f'Pact "{pact.name}" sealed at {pact.launch_time:%Y-%m-%d %H:%M:%S} UTC.')
            return redirect('spoeqi:detail', slug=pact.slug)

    return render(request, 'spoeqi/new.html', {
        'form': form,
        'errors': errors,
        'components': COMPONENTS,
        'component_grid': COMPONENT_GRID,
        'component_grid_choices': COMPONENT_GRID_CHOICES,
        'rule_table_size': RULE_TABLE_SIZE,
        'det_candidates': det_candidates,
        'fleet_pool': fleet_pool,
        'horizon_pref': horizon_pref,
    })


def detail(request, slug):
    pact = get_object_or_404(Pact, slug=slug)

    fleet_legend = []
    fleet_label_ids = []
    if pact.rule_diversity == 'fleet' and pact.fleet_candidate_ids:
        fleet_label_ids = list(pact.fleet_candidate_ids)
        try:
            from det.models import Candidate
            cmap = {c.id: c for c in Candidate.objects.filter(
                pk__in=fleet_label_ids).select_related('run')}
            for i, cid in enumerate(fleet_label_ids):
                c = cmap.get(cid)
                fleet_legend.append({
                    'component': i,
                    'component_hex': f'{i:02x}',
                    'candidate_id': cid,
                    'score': c.score if c else None,
                    'est_class': c.get_est_class_display() if c else None,
                    'n_rules': c.n_rules if c else None,
                    'available': c is not None,
                })
        except Exception:
            fleet_legend = []

    payload = {
        'slug': pact.slug,
        'name': pact.name,
        'party_a': pact.party_a,
        'party_b': pact.party_b,
        'clock_model': pact.clock_model,
        'tick_ms': pact.tick_ms,
        'launch_iso': pact.launch_time.isoformat(),
        'launch_ms':  int(pact.launch_time.timestamp() * 1000),
        'seed_hex':    pact.seed_hex,
        'rules_hex':   pact.rules_hex,
        'rule_diversity': pact.rule_diversity,
        'palette':     pact.palette,
        'components':  COMPONENTS,
        'component_grid': pact.component_grid,
        'fleet_label_ids': fleet_label_ids,
        # Album-seeded pacts override gen-0 cells with explicit grids
        # instead of xoshiro expansion.  None on non-album pacts.
        'initial_grids': pact.initial_grids,
        'album_hash':    pact.album_hash or None,
    }
    cells_per_tile = pact.component_grid * pact.component_grid
    if is_per_component_palette(pact.palette):
        swatch_palette = pact.palette[0]
        palette_is_per_component = True
    else:
        swatch_palette = pact.palette or DEFAULT_PALETTE
        palette_is_per_component = False

    # Bottom-out fingerprint: opt-in via ?fingerprint=1 so the default
    # detail load stays cheap.  When requested, run each component up
    # to N steps and resolve every "uniform" outcome to its actual RGB
    # from the pact's palette, so the template just lays out colour
    # swatches.
    fingerprint = None
    if request.GET.get('fingerprint') == '1':
        from . import analysis
        try:
            max_steps = int(request.GET.get('fp_steps') or 128)
        except (TypeError, ValueError):
            max_steps = 128
        max_steps = max(1, min(512, max_steps))
        fp = analysis.convergence_fingerprint(pact, max_steps=max_steps)
        # Resolve each component's colour-index to its RGB via the
        # palette (per-component when available).
        def _rgb_for(c, idx):
            if idx is None:
                return None
            if palette_is_per_component:
                pal = pact.palette[c]
            else:
                pal = swatch_palette
            r, g, b = pal[idx]
            return f'rgb({r}, {g}, {b})'
        flat = []
        for entry in fp['components']:
            flat.append({
                **entry,
                'rgb': _rgb_for(entry['component'], entry['colour']),
            })
        fingerprint = {
            'components': flat,
            'bitmap': [[flat[r * 8 + col] for col in range(8)]
                        for r in range(8)],
            'n_uniform': fp['n_uniform'],
            'n_stable':  fp['n_stable'],
            'n_cycling': fp['n_cycling'],
            'max_steps': fp['max_steps'],
            'uniform_pct': round(100 * fp['n_uniform'] / COMPONENTS, 1),
        }

    # Pull a recent-walks list for the gridprint form's "use a Mandelbrot
    # walk's final image as the CA initial state" dropdown.  Cheap query
    # (12 rows, slug+name only) and only matters if loupe is installed —
    # wrapped so a missing loupe app doesn't break the spoeqi detail page.
    try:
        from loupe.models import Walk
        recent_walks = list(
            Walk.objects.order_by('-pk')
                .values('slug', 'name')[:12])
    except Exception:
        recent_walks = []

    return render(request, 'spoeqi/detail.html', {
        'pact':    pact,
        'payload': json.dumps(payload),
        'now_ms':  int(timezone.now().timestamp() * 1000),
        'cells_per_tile':   cells_per_tile,
        'cells_total':      cells_per_tile * COMPONENTS,
        'fleet_legend':     fleet_legend,
        'swatch_palette':   swatch_palette,
        'palette_is_per_component': palette_is_per_component,
        'fingerprint':      fingerprint,
        'recent_walks':     recent_walks,
    })


@require_POST
def delete(request, slug):
    pact = get_object_or_404(Pact, slug=slug)
    name = pact.name
    pact.delete()
    messages.info(request, f'Pact "{name}" dissolved.')
    return redirect('spoeqi:index')


# ────────────────────── Oracle ────────────────────────────────────
#
# Pact-shared deterministic prompt → external non-deterministic LLM.
# GET renders the form; POST runs `ask_oracle` and re-renders with
# the prompt and (optional) response. Heavy: each POST loads the
# internal CausalLM and may take 5-30 s.

def _oracle_model_choices() -> list[str]:
    """Sourced from llm_lora.DEFAULT_TARGETS so newly-registered backbones
    (e.g. karpathy/minGPT-*) appear in the dropdown automatically."""
    from .llm_lora import list_known_models
    return list_known_models()


def oracle(request, slug):
    pact = get_object_or_404(Pact, slug=slug)

    from .oracle import (
        ask_oracle,
        DEFAULT_SEED_PROMPT,
        DEFAULT_EXTERNAL_SYSTEM_PROMPT,
    )
    try:
        from identity.models import LLMProvider
        providers = list(LLMProvider.objects.order_by('name'))
    except Exception:
        providers = []

    form_defaults = {
        'provider':                '',
        'seed_prompt':             DEFAULT_SEED_PROMPT,
        'external_system_prompt':  DEFAULT_EXTERNAL_SYSTEM_PROMPT,
        'component':               '0',
        'generation':              '0',
        'model':                   'distilgpt2',
        'scale':                   '0.1',
        'rank':                    '4',
        'max_new_tokens':          '60',
        'max_external_tokens':     '400',
    }
    form = dict(form_defaults)
    result = None

    if request.method == 'POST':
        for k in form:
            form[k] = request.POST.get(k, form_defaults[k]).strip()

        try:
            kwargs = dict(
                seed_prompt=form['seed_prompt'] or DEFAULT_SEED_PROMPT,
                component=int(form['component']),
                generation=int(form['generation']),
                model_name=form['model'],
                scale=float(form['scale']),
                rank=int(form['rank']),
                max_new_tokens=int(form['max_new_tokens']),
            )
            provider_slug = form['provider'] or None
            result = ask_oracle(
                pact,
                provider_slug=provider_slug,
                external_system_prompt=form['external_system_prompt']
                                        or DEFAULT_EXTERNAL_SYSTEM_PROMPT,
                max_external_tokens=int(form['max_external_tokens']),
                **kwargs,
            )
        except (ValueError, TypeError) as e:
            messages.error(request, f'bad form input: {e}')
        except Exception as e:  # noqa: BLE001
            messages.error(request, f'{type(e).__name__}: {e}')

    return render(request, 'spoeqi/oracle.html', {
        'pact':      pact,
        'form':      form,
        'providers': providers,
        'models':    _oracle_model_choices(),
        'result':    result,
    })


def textmask(request, slug):
    """Run a user-supplied text through the CA-as-attention-mask.
    Tile the text into one component's ``side × side`` grid at the
    requested generation, look up each cell's CA colour, dispatch
    through a named 4-entry mapping table, render the tinted grid
    plus the flattened output text.
    """
    from . import textmask as tm

    pact = get_object_or_404(Pact, slug=slug)
    palette = pact.palette
    if is_per_component_palette(palette):
        # Per-component palettes are 64 sub-palettes; we only render
        # one component at a time so pick the relevant one below.
        pass

    form_defaults = {
        'text':       'attention is all you need · 注意力就是一切',
        'component':  '0',
        'generation': '0',
        'mapping':    'attention',
        'mode':       'char',   # 'char' | 'token' | 'attention'
        'compare_all': '',
    }
    form = dict(form_defaults)
    result = None
    all_results = None
    token_result = None
    token_all_results = None
    attn_result = None
    attn_all_results = None
    error = None

    def _registry_for(mode):
        if mode == 'token':     return tm.TOKEN_MAPPING_TABLES
        if mode == 'attention': return tm.ATTENTION_TABLES
        return tm.MAPPING_TABLES

    def _default_mapping(mode):
        return next(iter(_registry_for(mode)))

    if request.method == 'POST':
        for k in form:
            form[k] = request.POST.get(k, form_defaults[k])
        mode = form['mode'] if form['mode'] in ('char','token','attention') else 'char'
        form['mode'] = mode
        registry = _registry_for(mode)
        if form['mapping'] not in registry:
            form['mapping'] = _default_mapping(mode)
        try:
            if mode == 'token':
                if form['compare_all']:
                    token_all_results = tm.apply_tokens_all(
                        pact, text=form['text'],
                        generation=int(form['generation']),
                        mapping=form['mapping'])
                else:
                    token_result = tm.apply_tokens(
                        pact, text=form['text'],
                        component=int(form['component']),
                        generation=int(form['generation']),
                        mapping=form['mapping'])
            elif mode == 'attention':
                if form['compare_all']:
                    attn_all_results = tm.apply_attention_all(
                        pact, generation=int(form['generation']),
                        mapping=form['mapping'])
                else:
                    attn_result = tm.apply_attention(
                        pact, component=int(form['component']),
                        generation=int(form['generation']),
                        mapping=form['mapping'])
            else:  # char
                if form['compare_all']:
                    all_results = tm.apply_all(
                        pact, text=form['text'],
                        generation=int(form['generation']),
                        mapping=form['mapping'])
                else:
                    result = tm.apply(
                        pact, text=form['text'],
                        component=int(form['component']),
                        generation=int(form['generation']),
                        mapping=form['mapping'])
        except (ValueError, TypeError) as e:
            error = f'bad input: {e}'
        except Exception as e:  # noqa: BLE001
            error = f'{type(e).__name__}: {e}'

    # Pick the palette to render: per-component picks the sub-palette
    # for the selected component; otherwise the single palette.
    sel_component = int(form['component']) if form['component'].lstrip('-').isdigit() else 0
    if is_per_component_palette(palette) and 0 <= sel_component < COMPONENTS:
        render_palette = palette[sel_component]
    else:
        render_palette = palette

    # Build (name, label-tuple, description) tuples for the dropdowns.
    # Both registries are surfaced so the client-side script can
    # repopulate the mapping dropdown when the mode flips, without an
    # extra round-trip.
    char_mappings = [
        {'name': m.name, 'description': m.description, 'labels': list(m.labels)}
        for m in tm.MAPPING_TABLES.values()
    ]
    token_mappings = [
        {'name': m.name, 'description': m.description, 'labels': list(m.labels)}
        for m in tm.TOKEN_MAPPING_TABLES.values()
    ]
    attn_mappings = [
        {'name': m.name, 'description': m.description, 'labels': list(m.labels)}
        for m in tm.ATTENTION_TABLES.values()
    ]
    mode = form.get('mode', 'char')
    if mode == 'token':       mappings = token_mappings
    elif mode == 'attention': mappings = attn_mappings
    else:                      mappings = char_mappings
    registry = _registry_for(mode)
    if form['mapping'] in registry:
        active_labels = registry[form['mapping']].labels
    else:
        active_labels = next(iter(registry.values())).labels

    # Pre-format the palette as CSS-ready rgb strings so the template
    # doesn't need an index filter.
    swatches = [
        {'color': i, 'css': f'rgb({c[0]},{c[1]},{c[2]})',
         'label': active_labels[i]}
        for i, c in enumerate(render_palette)
    ]

    # Attach the CSS colour to each cell once, in the view, so the
    # template loop stays trivial.
    rendered_cells = None
    if result is not None:
        rendered_cells = [
            {'char':  c.char, 'color': c.color, 'out': c.out,
             'row':   c.row,  'col':   c.col,
             'css':   swatches[c.color]['css']}
            for c in result.cells
        ]
    rendered_token_cells = None
    if token_result is not None:
        rendered_token_cells = [
            {'token': c.token, 'color': c.color, 'out': c.out,
             'row':   c.row,   'col':   c.col,
             'css':   swatches[c.color]['css']}
            for c in token_result.cells
        ]

    # Build a compact per-component summary row for the comparison
    # mode: component index, a 4-colour stacked-bar (counts of each
    # colour in this component's grid) so the eye can scan vertically
    # for "mostly red" vs "balanced", and the flattened output text.
    rendered_rows = None
    if all_results is not None:
        rendered_rows = []
        for r in all_results:
            counts = [0, 0, 0, 0]
            for c in r.cells:
                counts[c.color] += 1
            total = max(1, sum(counts))
            bar = [{'pct':   100.0 * counts[i] / total,
                     'count': counts[i],
                     'css':   swatches[i]['css']}
                    for i in range(4)]
            rendered_rows.append({
                'component':   r.component,
                'output_text': r.output_text,
                'bar':         bar,
            })
    # Same shape for token compare-all.
    rendered_token_rows = None
    if token_all_results is not None:
        rendered_token_rows = []
        for r in token_all_results:
            counts = [0, 0, 0, 0]
            for c in r.cells:
                counts[c.color] += 1
            total = max(1, sum(counts))
            bar = [{'pct':   100.0 * counts[i] / total,
                     'count': counts[i],
                     'css':   swatches[i]['css']}
                    for i in range(4)]
            rendered_token_rows.append({
                'component':   r.component,
                'output_text': r.output_text,
                'bar':         bar,
            })

    # Attention render data — flat list of cells with their CSS background
    # colour mixed by weight: positive weights tint green, zero is black,
    # negative weights tint red.  The eye reads the matrix as a heatmap.
    def _att_css(w):
        # Clip to [-1.5, 1.5] for colour-mapping purposes.
        x = max(-1.5, min(1.5, w))
        if x >= 0:
            g = int(round(255 * (x / 1.5)))
            return f'rgb(0,{g},{g // 2})'   # green/teal
        r = int(round(255 * (-x / 1.5)))
        return f'rgb({r},0,{r // 3})'        # red/magenta
    rendered_attn_cells = None
    attn_matrix_json = ''
    if attn_result is not None:
        rendered_attn_cells = [
            {'row': c.row, 'col': c.col, 'color': c.color,
             'weight': round(c.weight, 3),
             'css': _att_css(c.weight),
             'palette_css': swatches[c.color]['css']}
            for c in attn_result.cells
        ]
        attn_matrix_json = json.dumps(attn_result.matrix)

    rendered_attn_rows = None
    if attn_all_results is not None:
        rendered_attn_rows = []
        for r in attn_all_results:
            counts = [0, 0, 0, 0]
            density = 0.0
            for c in r.cells:
                counts[c.color] += 1
                density += max(0.0, c.weight)
            total = max(1, sum(counts))
            density /= total
            bar = [{'pct':   100.0 * counts[i] / total,
                     'count': counts[i],
                     'css':   swatches[i]['css']}
                    for i in range(4)]
            # Tiny inline heatmap of the matrix — 16 small cells per row,
            # rendered as CSS background colours.
            heat = [_att_css(w) for row in r.matrix for w in row]
            rendered_attn_rows.append({
                'component': r.component,
                'density':   round(density, 2),
                'bar':       bar,
                'heat':      heat,
            })

    # Payload for the live JS engine: enough to run the same 64 CAs
    # the detail page runs, plus the active mapping name and palette.
    # Only attached when there's a result to display — the empty-form
    # GET doesn't ship a megabyte of rule bytes.
    # Live JS engine runs in char mode and in token mode IF the
    # selected token table only uses primitives we have JS mirrors
    # for (everything except spaCy's POS/lemma).  For pos-distill or
    # any future server-only table the page renders the initial
    # result and stays static.
    live_payload_json = ''
    has_any_result = (result is not None or all_results is not None or
                       token_result is not None or token_all_results is not None or
                       attn_result is not None or attn_all_results is not None)
    live_capable = False
    if has_any_result:
        if form['mode'] == 'char':
            live_capable = True
        elif form['mode'] == 'token':
            tmap = tm.TOKEN_MAPPING_TABLES.get(form['mapping'])
            live_capable = bool(tmap and tmap.live_capable)
    if live_capable:
        live_payload = {
            'seed_hex':      pact.seed_hex,
            'rules_hex':     pact.rules_hex,
            'components':    COMPONENTS,
            'component_grid': pact.component_grid,
            'tick_ms':       pact.tick_ms,
            'palette':       pact.palette,
            'mode':          form['mode'],
            'mapping':       form['mapping'],
            'text':          form['text'],
            'generation':    int(form['generation']),
            'compare_all':   bool(form['compare_all']),
            'component':     int(form['component']) if not form['compare_all'] else 0,
            'initial_grids': pact.initial_grids,
        }
        if form['mode'] == 'token':
            tmap = tm.TOKEN_MAPPING_TABLES[form['mapping']]
            side = pact.component_grid
            live_payload['tokens']     = tm.tile_tokens(form['text'], side)
            live_payload['primitives'] = list(tmap.primitives)
        live_payload_json = json.dumps(live_payload)

    return render(request, 'spoeqi/textmask.html', {
        'pact':            pact,
        'form':            form,
        'result':          result,
        'rendered_cells':  rendered_cells,
        'all_results':     all_results,
        'rendered_rows':   rendered_rows,
        'token_result':         token_result,
        'rendered_token_cells': rendered_token_cells,
        'token_all_results':    token_all_results,
        'rendered_token_rows':  rendered_token_rows,
        'attn_result':          attn_result,
        'rendered_attn_cells':  rendered_attn_cells,
        'attn_matrix_json':     attn_matrix_json,
        'attn_all_results':     attn_all_results,
        'rendered_attn_rows':   rendered_attn_rows,
        'live_capable':         live_capable,
        'error':           error,
        'mappings':        mappings,
        'char_mappings':   char_mappings,
        'token_mappings':  token_mappings,
        'attn_mappings':   attn_mappings,
        'active_labels':   list(active_labels),
        'swatches':        swatches,
        'side':            pact.component_grid,
        'components':      list(range(COMPONENTS)),
        'live_payload':    live_payload_json,
    })


def album_new(request, slug=None):
    """Create a pact from a cover-image album.

    The user uploads N ∈ {2, 4, 8, 16} images.  Each image is
    quantized to 4 states under a single album-wide palette, then
    split into 64//N tiles which become the gen-0 cell grids of
    individual components.  The album's SHA-256 hash deterministically
    derives the seed_matrix and rule_snapshot via domain-separated
    KDF.  Two parties with the same album get bit-identical pacts.
    """
    from . import album as _album

    form_defaults = {
        'name':        '',
        'party_a':     'Alice',
        'party_b':     'Bob',
        'n_images':    '4',
        'clock_model': 'synced',
        'tick_ms':     '180',
    }
    form = dict(form_defaults)
    errors: list[str] = []

    if request.method == 'POST':
        for k in form:
            form[k] = request.POST.get(k, form_defaults[k]).strip()
        try:
            n = int(form['n_images'])
            if n not in _album.VALID_N:
                raise ValueError(f'n_images must be one of {_album.VALID_N}')
            files = request.FILES.getlist('images')
            if len(files) != n:
                raise ValueError(
                    f'expected exactly {n} images, got {len(files)}')
            images_bytes = [f.read() for f in files]
            targets = _album.quantize_album(images_bytes,
                                             side=COMPONENT_GRID)

            # Same album hash → same seed + rule + palette + initial
            # grids. Re-creating would just be a duplicate Pact, and
            # collide on Pact.name (UNIQUE) when the user accepted the
            # default name. Reuse the existing one and redirect.
            existing = Pact.objects.filter(
                album_hash=targets.album_hash).first()
            if existing is not None:
                messages.info(request,
                    f'Album already exists as pact "{existing.name}" '
                    f'(album hash {targets.album_hash[:12]}…) — '
                    f'redirecting to it.')
                return redirect('spoeqi:detail', slug=existing.slug)

            seed, rule = _album.derive_seed_and_rule(targets.album_hash)
            palette = _album.palette_to_pact_palette(targets.palette_rgb)
            initial_grids = _album.targets_to_initial_grids(targets)

            # Even with no album-hash collision, a manually-typed name
            # may collide with an existing pact (any source). Suffix in
            # that case so the create succeeds.
            base_name = form['name'] or f'album-{targets.album_hash[:8]}'
            name = base_name
            suffix = 2
            while Pact.objects.filter(name=name).exists():
                name = f'{base_name}-{suffix}'
                suffix += 1

            pact = Pact(
                name=name,
                party_a=form['party_a'],
                party_b=form['party_b'],
                clock_model=form['clock_model'],
                tick_ms=int(form['tick_ms']),
                component_grid=COMPONENT_GRID,
                seed_matrix=seed,
                rule_snapshot=rule,
                rule_diversity='shared',
                palette=palette,
                initial_grids=initial_grids,
                album_hash=targets.album_hash,
                album_n_images=n,
                launch_time=timezone.now(),
            )
            pact.save()
            messages.success(request,
                f'Album-seeded pact "{pact.name}" created '
                f'({n} images → 64 components, album hash '
                f'{targets.album_hash[:12]}…).')
            return redirect('spoeqi:detail', slug=pact.slug)
        except ValueError as e:
            errors.append(str(e))
        except Exception as e:  # noqa: BLE001
            errors.append(f'{type(e).__name__}: {e}')

    return render(request, 'spoeqi/album_new.html', {
        'form':    form,
        'errors':  errors,
        'valid_n': list(_album.VALID_N),
    })


def chain(request, slug):
    """Sequential pipeline of textmask stages.  Stage K's output_text
    becomes stage K+1's input_text.  All stages share the same Pact;
    each picks its own (mode, mapping, component, generation).
    """
    from . import textmask as tm

    pact = get_object_or_404(Pact, slug=slug)

    # Default chain: a classic IR preprocessing → MLM corruption.
    default_text = 'The quick brown fox jumps over the lazy dog and runs again into the woods'
    n_slots = 4   # cap on chain depth — keeps the UI tidy

    form_defaults = {'text': default_text}
    for i in range(n_slots):
        form_defaults.update({
            f'mode_{i}':       'token' if i == 0 else '',
            f'mapping_{i}':    'denoise' if i == 0 else '',
            f'component_{i}':  str(i),
            f'generation_{i}': '0',
        })
    form = dict(form_defaults)

    stages: list[tm.ChainStage] = []
    results = None
    error = None

    # Full-64 (gene-driven) mode runs a 64-stage chain where each
    # component's (mode, mapping) "task" is picked deterministically
    # from a CA meta-tap.  Same pact → same gene → same chain.  The
    # `chain64_prefer_mode` knob lets the user constrain everything to
    # char or token if they want a homogeneous-mode gene; default
    # 'auto' lets the gene byte decide per stage.
    form_defaults.update({
        'chain64_prefer_mode': 'auto',     # 'auto' | 'char' | 'token'
        'chain64_generation':  '0',
    })
    form.update({k: form_defaults[k] for k in form_defaults if k.startswith('chain64_')})

    chain_mode_used = 'manual'   # 'manual' | 'full64'
    full64_gene     = None       # populated when chain_64 ran

    if request.method == 'POST':
        for k in form:
            form[k] = request.POST.get(k, form_defaults[k])
        try:
            if request.POST.get('chain_64'):
                # Output of CA 0 feeds CA 1 feeds CA 2 ... feeds CA 63,
                # but each stage runs its *own gene-coded task* — not
                # the same mapping 64 times.  The gene is derived from
                # the pact's CA bytes via derive_chain_gene().
                chain_mode_used = 'full64'
                gen64     = int(form['chain64_generation'])
                pref      = form['chain64_prefer_mode']
                if pref not in ('auto', 'char', 'token'):
                    raise ValueError(f'bad prefer_mode {pref!r}')
                stages = tm.derive_chain_gene(
                    pact, generation=gen64,
                    prefer_mode=None if pref == 'auto' else pref,
                )
                full64_gene = stages
                results = tm.apply_chain(pact, stages, form['text'])
            else:
                for i in range(n_slots):
                    mode = form[f'mode_{i}']
                    if not mode:                    # empty slot — skip
                        continue
                    if mode not in ('char', 'token'):
                        raise ValueError(f'stage {i}: mode {mode!r} not chainable '
                                         f'(attention produces a matrix, not text)')
                    mapping = form[f'mapping_{i}']
                    comp = int(form[f'component_{i}'])
                    gen  = int(form[f'generation_{i}'])
                    stages.append(tm.ChainStage(
                        mode=mode, mapping=mapping,
                        component=comp, generation=gen))
                if stages:
                    results = tm.apply_chain(pact, stages, form['text'])
        except (ValueError, TypeError) as e:
            error = f'bad input: {e}'
        except Exception as e:  # noqa: BLE001
            error = f'{type(e).__name__}: {e}'

    char_mappings = [
        {'name': m.name, 'description': m.description, 'labels': list(m.labels)}
        for m in tm.MAPPING_TABLES.values()
    ]
    token_mappings = [
        {'name': m.name, 'description': m.description, 'labels': list(m.labels)}
        for m in tm.TOKEN_MAPPING_TABLES.values()
    ]

    # Per-stage rendered slots for the form (so the template iterates
    # over a list rather than juggling N variables).
    slots = []
    for i in range(n_slots):
        slots.append({
            'i':          i,
            'mode':       form[f'mode_{i}'],
            'mapping':    form[f'mapping_{i}'],
            'component':  form[f'component_{i}'],
            'generation': form[f'generation_{i}'],
        })

    # Preview the gene even on GET so the user sees what each component
    # will do *before* spending the cycles to run all 64 stages.  Cheap:
    # one keystream tap + 64 dict lookups.
    try:
        gene_preview = tm.derive_chain_gene(
            pact, generation=int(form.get('chain64_generation') or 0),
            prefer_mode=None if form.get('chain64_prefer_mode', 'auto') == 'auto'
                       else form['chain64_prefer_mode'],
        )
    except Exception:  # noqa: BLE001
        gene_preview = []

    return render(request, 'spoeqi/chain.html', {
        'pact':              pact,
        'form':              form,
        'slots':             slots,
        'results':           results,
        'error':             error,
        'char_mappings':     char_mappings,
        'token_mappings':    token_mappings,
        'components':        list(range(COMPONENTS)),
        'chain_mode_used':   chain_mode_used,
        'n_components':      COMPONENTS,
        'gene_preview':      gene_preview,
        'full64_gene':       full64_gene,
    })


@login_required
def chain_evolve(request, slug):
    """GA over per-component chain genes.  Each individual is a 64-tuple
    of (mode, mapping); fitness = weighted sum of metrics from
    spoeqi.chain_evolution.METRIC_REGISTRY.  See the textmask docstring
    for the long-term plan: chains as learnable LLM-prep preprocessors.
    """
    from . import chain_evolution as ce
    from . import textmask as tm

    pact = get_object_or_404(Pact, slug=slug)
    metric_registry = ce.METRIC_REGISTRY

    form_defaults = {
        'input_text':       'attention is all you need but the woods are lovely dark and deep',
        'reference_text':   '',                # blank → reference_match disabled
        'n_population':     '12',
        'n_generations':    '8',
        'mutation_rate':    '0.10',
        'crossover_rate':   '0.6',
        'generation':       '0',
        'seed_with_pact':   '1',
    }
    # Default weights: 1.0 on a few sane defaults, 0 elsewhere.
    default_weights = {
        'lexical_diversity':      1.0,
        'stopword_density':       1.0,
        'input_recall':           1.0,
        'bigram_diversity':       1.0,
        'avg_word_length':        0.5,
        'alpha_ratio':            0.5,
    }
    for name in metric_registry:
        form_defaults[f'w_{name}'] = str(default_weights.get(name, 0.0))
    form_defaults['w_reference_match'] = '0.0'

    form = dict(form_defaults)
    result = None
    error = None
    sample_chain = None

    if request.method == 'POST':
        for k in form_defaults:
            form[k] = request.POST.get(k, form_defaults[k])
        try:
            input_text = (form['input_text'] or '').strip()
            if not input_text:
                raise ValueError('input text is required')
            n_pop = max(2, min(40, int(form['n_population'])))
            n_gen = max(1, min(40, int(form['n_generations'])))
            m_rate = max(0.0, min(1.0, float(form['mutation_rate'])))
            c_rate = max(0.0, min(1.0, float(form['crossover_rate'])))
            gen    = max(0, int(form['generation']))
            seed_pact = form.get('seed_with_pact') == '1'

            weights = {}
            for name in metric_registry:
                w = float(form.get(f'w_{name}', '0') or 0)
                if w != 0.0:
                    weights[name] = w
            ref = (form.get('reference_text') or '').strip()
            ref_w = float(form.get('w_reference_match', '0') or 0)
            if ref_w != 0.0 and ref:
                # Inject the factory metric on top of the registry-driven sum.
                ref_fn = ce.reference_match(ref)
                weights['_reference_match_inline'] = ref_w
                # Build a custom fitness callable that adds the reference
                # match to the weighted-sum.  Cheaper than restructuring
                # weighted_fitness to accept ad-hoc callables.
                base_fit = ce.weighted_fitness(
                    {k: v for k, v in weights.items()
                      if not k.startswith('_')})
                base_w   = sum(v for k, v in weights.items() if not k.startswith('_')) or 1.0
                ref_only = ref_w / (base_w + ref_w)
                base_only = base_w / (base_w + ref_w)
                def fitness(inp, out, stages):
                    return (base_only * base_fit(inp, out, stages)
                            + ref_only * ref_fn(inp, out, stages))
            else:
                if not weights:
                    raise ValueError('all metric weights are 0 — pick at least one metric')
                fitness = ce.weighted_fitness(weights)

            result = ce.evolve(pact,
                                input_text=input_text,
                                fitness=fitness,
                                n_population=n_pop,
                                n_generations=n_gen,
                                mutation_rate=m_rate,
                                crossover_rate=c_rate,
                                generation=gen,
                                seed_with_pact_gene=seed_pact)

            # Re-run the winning gene to get per-stage breakdown for the UI.
            best_gene = result.final_population[0]
            stages = ce.gene_to_stages(best_gene, gen)
            sample_chain = tm.apply_chain(pact, stages, input_text)
        except (ValueError, TypeError) as e:
            error = f'bad input: {e}'
        except Exception as e:  # noqa: BLE001
            error = f'{type(e).__name__}: {e}'

    metric_rows = [
        {
            'name':        name,
            'description': desc,
            'weight':      form.get(f'w_{name}', '0'),
            'is_default':  default_weights.get(name, 0.0) > 0,
        }
        for name, (desc, _fn) in metric_registry.items()
    ]
    return render(request, 'spoeqi/chain_evolve.html', {
        'pact':            pact,
        'form':            form,
        'metric_rows':     metric_rows,
        'result':          result,
        'sample_chain':    sample_chain,
        'error':           error,
        'n_components':    COMPONENTS,
    })


_DEFAULT_EVOLVE_INPUTS = (
    'attention is all you need',
    'the quick brown fox jumps over the lazy dog',
    'a rose by any other name would smell as sweet',
)


def evolve(request, slug):
    """Run a small GA over textmask head-ensembles.  See
    spoeqi/evolution.py for the substrate; this view is just a thin
    form + result renderer.
    """
    from . import evolution as ev

    pact = get_object_or_404(Pact, slug=slug)

    form_defaults = {
        'inputs':         '\n'.join(_DEFAULT_EVOLVE_INPUTS),
        'ensemble_size':  '4',
        'n_population':   '8',
        'n_generations':  '6',
        'mutation_rate':  '0.25',
        'crossover_rate': '0.5',
        'n_elite':        '1',
        'tournament_k':   '3',
        'gen_lo':         '0',
        'gen_hi':         '12',
        'fitness':        'lexical_diversity',
        'rng_seed':       '',
    }
    form = dict(form_defaults)
    result = None
    error = None

    if request.method == 'POST':
        for k in form:
            form[k] = request.POST.get(k, form_defaults[k])
        try:
            inputs = [s for s in (form['inputs'] or '').splitlines() if s.strip()]
            if not inputs:
                raise ValueError('at least one non-empty input line is required')
            fitness_name = form['fitness']
            if fitness_name not in ev.FITNESS_REGISTRY:
                raise ValueError(f'unknown fitness {fitness_name!r}')
            seed_raw = form['rng_seed'].strip()
            rng_seed = int(seed_raw) if seed_raw else None
            result = ev.evolve(
                pact,
                inputs=inputs,
                ensemble_size=int(form['ensemble_size']),
                n_population=int(form['n_population']),
                n_generations=int(form['n_generations']),
                mutation_rate=float(form['mutation_rate']),
                crossover_rate=float(form['crossover_rate']),
                n_elite=int(form['n_elite']),
                tournament_k=int(form['tournament_k']),
                gen_window=(int(form['gen_lo']), int(form['gen_hi'])),
                fitness=ev.FITNESS_REGISTRY[fitness_name],
                rng_seed=rng_seed,
            )
        except (ValueError, TypeError) as e:
            error = f'bad input: {e}'
        except Exception as e:  # noqa: BLE001
            error = f'{type(e).__name__}: {e}'

    # Pre-render result rows so the template stays simple.
    history_rows = None
    final_rows   = None
    if result is not None:
        history_rows = []
        for g in result.history:
            history_rows.append({
                'gen':         g.gen,
                'best_score':  round(g.best_score, 4),
                'mean_score':  round(g.mean_score, 4),
                'best_heads':  [_head_chip(h) for h in g.best_heads],
                'sample':      g.best_sample_concat,
            })
        final_rows = []
        for rank, (heads, score, sample) in enumerate(zip(
                result.final_population,
                result.final_scores,
                result.final_sample_concats), start=1):
            final_rows.append({
                'rank':   rank,
                'score':  round(score, 4),
                'heads':  [_head_chip(h) for h in heads],
                'sample': sample,
            })

    return render(request, 'spoeqi/evolve.html', {
        'pact':          pact,
        'form':          form,
        'fitness_choices': list(ev.FITNESS_REGISTRY.keys()),
        'history_rows':  history_rows,
        'final_rows':    final_rows,
        'error':         error,
        'result':        result,
    })


def _head_chip(h):
    """Compact dict the template can render as a single chip."""
    return {
        'mode':       h.mode,
        'table_name': h.table_name,
        'component':  h.component,
        'generation': h.generation,
        'tag':        f'{h.mode}/{h.table_name}·c{h.component:02d}·g{h.generation}',
    }


def keystream_tap(request, slug, component, generation, n_bytes):
    """Return ``n_bytes`` of deterministic keystream from component
    ``c`` at generation ``g``.  Both Alice and Bob (or any two parties
    holding the same Pact) get the same bytes back from the same
    (slug, component, generation, n_bytes) tuple.

    JSON shape::

        {"ok": true, "bytes_hex": "…", "component": c,
         "generation": g, "n_bytes": n}

    On AdvanceCapExceeded: 503 with ``{"ok": false, "error": "..."}``
    so callers can poll for the cache to catch up incrementally.
    """
    from . import keystream

    pact = get_object_or_404(Pact, slug=slug)
    if n_bytes <= 0 or n_bytes > 65536:
        return JsonResponse({'ok': False,
                              'error': 'n_bytes must be 1..65536'}, status=400)
    try:
        out = keystream.tap(pact, component, generation, n_bytes)
    except keystream.AdvanceCapExceeded as exc:
        return JsonResponse({'ok': False, 'error': str(exc),
                              'advance_cap': keystream.ADVANCE_CAP},
                             status=503)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok':         True,
        'slug':       pact.slug,
        'component':  component,
        'generation': generation,
        'n_bytes':    n_bytes,
        'bytes_hex':  out.hex(),
    })


@require_POST
def export_tile_to_automaton(request, slug, component):
    """Decompose a tile's 16,384-byte rule into Automaton ExactRules
    and create a Simulation seeded from the current grid state the
    viewer POSTed.  Returns JSON with the new Simulation's URL — the
    JS handler then navigates to it.

    Identity entries (self-state preserved) are skipped: Automaton's
    step engine treats unmatched cells as identity, so a ~7700-row
    ruleset suffices instead of the full 16,384.
    """
    pact = get_object_or_404(Pact, slug=slug)
    if component < 0 or component >= COMPONENTS:
        return JsonResponse(
            {'ok': False, 'error': f'component must be 0..{COMPONENTS - 1}'},
            status=400)
    try:
        body = json.loads(request.body.decode())
        grid_state = body['grid_state']
        if not isinstance(grid_state, list) or not grid_state:
            raise ValueError('grid_state must be a non-empty 2-D list')
        for row in grid_state:
            if not isinstance(row, list):
                raise ValueError('grid_state rows must be lists')
            for v in row:
                if not (isinstance(v, int) and 0 <= v <= 3):
                    raise ValueError('grid cells must be ints in 0..3')
    except (ValueError, KeyError, TypeError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    from automaton.models import RuleSet, ExactRule, Simulation
    rule_bytes = pact.per_component_rules()[
        component * RULE_TABLE_SIZE:(component + 1) * RULE_TABLE_SIZE]

    if is_per_component_palette(pact.palette):
        component_palette = pact.palette[component]
    else:
        component_palette = pact.palette
    pal_hex = ['#{:02x}{:02x}{:02x}'.format(*c) for c in component_palette]
    rs_name = f'spoeqi {pact.name} · tile {component:02x}'
    # If a previous export collided on name, suffix; admin can rename.
    base_name = rs_name
    n = 2
    while RuleSet.objects.filter(name=rs_name).exists():
        rs_name = f'{base_name} ({n})'
        n += 1
    src_meta = {
        'spoeqi_pact_slug': pact.slug,
        'spoeqi_pact_name': pact.name,
        'spoeqi_component': component,
        'spoeqi_rule_diversity': pact.rule_diversity,
    }
    if pact.fleet_candidate_ids and component < len(pact.fleet_candidate_ids):
        src_meta['spoeqi_fleet_det_candidate_id'] = \
            pact.fleet_candidate_ids[component]
    rs = RuleSet.objects.create(
        name=rs_name,
        description=(f'Exported from spoeqi pact "{pact.name}" '
                     f'component {component:02x}.  '
                     f'rule_diversity={pact.rule_diversity}.'),
        n_colors=4,
        source='operator',
        source_metadata=src_meta,
        palette=pal_hex,
    )

    rules = []
    for key in range(RULE_TABLE_SIZE):
        s  = (key >> 12) & 0x03
        n0 = (key >> 10) & 0x03
        n1 = (key >> 8)  & 0x03
        n2 = (key >> 6)  & 0x03
        n3 = (key >> 4)  & 0x03
        n4 = (key >> 2)  & 0x03
        n5 = key         & 0x03
        r  = rule_bytes[key]
        if r == s:
            continue   # identity → covered by Automaton's default
        rules.append(ExactRule(
            ruleset=rs, self_color=s,
            n0_color=n0, n1_color=n1, n2_color=n2,
            n3_color=n3, n4_color=n4, n5_color=n5,
            result_color=r,
        ))
    ExactRule.objects.bulk_create(rules, batch_size=500)

    sim_name = f'spoeqi {pact.name} · tile {component:02x}'
    sim = Simulation.objects.create(
        name=sim_name, ruleset=rs,
        width=len(grid_state[0]), height=len(grid_state),
        palette=pal_hex, grid_state=grid_state,
        tick_count=0,
        notes=(f'Captured from spoeqi pact "{pact.name}" component '
               f'{component:02x} at its live state at click time. '
               f'rule_diversity={pact.rule_diversity}.'),
    )
    return JsonResponse({
        'ok': True,
        'ruleset_id': rs.pk,
        'simulation_id': sim.pk,
        'simulation_url': reverse('automaton:run', kwargs={'slug': sim.slug}),
        'rules_created': len(rules),
    })


# ────────────────────── Workspace (CA → ELF) ───────────────────────
#
# Per-pact 4096-byte ELF generator.  GET /spoeqi/<pact>/workspace/
# lists the apps and links to specific ticks; the .elf endpoint serves
# the patched binary as application/octet-stream.

WORKSPACE_APPS = {
    'app0_greeter': {
        'label':       'ANSI greeter',
        'description': 'CA-derived ANSI greeting — simplest verification.',
        'render':      'render_greeter_elf',
    },
    'app1_mandel': {
        'label':       'Mandelbrot frame',
        'description': 'One half-block frame at a CA-picked zoom preset.',
        'render':      'render_mandel_elf',
    },
    'app2_caview': {
        'label':       'Hex CA viewer',
        'description': 'Self-referential — the substrate viewing itself, '
                       'CA bytes pick rule + initial state for a 4-state '
                       'hex CA the ELF then runs locally.',
        'render':      'render_caview_elf',
    },
}


@login_required
def workspace_index(request, slug):
    pact = get_object_or_404(Pact, slug=slug)
    return render(request, 'spoeqi/workspace.html', {
        'pact':  pact,
        'apps':  WORKSPACE_APPS,
        'ticks': [0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144],
        'component_indices': list(range(COMPONENTS)),
        # Fully-qualified base URL so the curl recipe works from any
        # machine — request.get_host() includes the port when present.
        'scheme_host': f'{request.scheme}://{request.get_host()}',
    })


def _serve_workspace_elf(pact, app, tick):
    if app not in WORKSPACE_APPS:
        raise Http404(f'unknown workspace app {app!r}')
    from .workspace import slots as ws_slots
    fn = getattr(ws_slots, WORKSPACE_APPS[app]['render'])
    elf = fn(pact, tick=int(tick))
    resp = HttpResponse(elf, content_type='application/octet-stream')
    resp['Content-Disposition'] = (
        f'attachment; filename="{pact.slug}-{app}-tick{int(tick):05d}.elf"')
    resp['Content-Length'] = str(len(elf))
    # Cache aggressively: same (pact, app, tick) → identical bytes forever.
    resp['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@login_required
def workspace_app_elf(request, slug, app, tick):
    """Authenticated path — kept so a logged-in researcher can grab any
    pact's ELFs from the browser without juggling tokens."""
    pact = get_object_or_404(Pact, slug=slug)
    return _serve_workspace_elf(pact, app, tick)


def workspace_app_elf_token(request, slug, token, app, tick):
    """Bearer-token path — researchers on other machines (or curl from
    a terminal) hit this with the per-pact token displayed on the
    workspace index page.  Constant-time compare so the token can't be
    probed by timing.  No login required."""
    import hmac
    pact = get_object_or_404(Pact, slug=slug)
    if not pact.workspace_share_token:
        raise Http404('no share token issued for this pact')
    if not hmac.compare_digest(token, pact.workspace_share_token):
        raise Http404('bad share token')
    return _serve_workspace_elf(pact, app, tick)


# ─── Packed-ruleset downloads (per-component K=4 LUTs) ──────────────
#
# A pact's per-component rules are 64 × 16,384 bytes raw = 1 MiB total.
# Packed at 4 cells/byte (K=4 = 2 bits each) the same payload is
# 64 × 4,096 bytes = 256 KiB.  Per-component download + a single
# concatenated bundle so a researcher can grab the whole population in
# one shot.  See feedback_k4_stream_pack_default — raw 1B/cell wastes
# 75 % per byte; the packed form is what researchers actually want.

COMPONENT_LUT_BYTES = 16384   # 4^7 K=4 LUT entries, raw
COMPONENT_PACKED_BYTES = 4096  # K=4 packed, 4 cells/byte


def _packed_component_rules(pact):
    """Returns 64 × 4096 = 262,144 bytes (256 KiB) — packed K=4 LUTs
    in component order 0..63."""
    from .metachain import pack_k4_stream
    raw = pact.per_component_rules()  # 64 × 16,384 = 1 MiB
    if len(raw) != COMPONENTS * COMPONENT_LUT_BYTES:
        raise ValueError(
            f'pact {pact.slug}: per_component_rules returned '
            f'{len(raw)} B, expected {COMPONENTS * COMPONENT_LUT_BYTES}')
    out = bytearray()
    for c in range(COMPONENTS):
        s = c * COMPONENT_LUT_BYTES
        out.extend(pack_k4_stream(raw[s:s + COMPONENT_LUT_BYTES]))
    return bytes(out)


@login_required
def workspace_packed_component(request, slug, component):
    """Per-component packed K=4 LUT — 4,096 bytes.  component in 0..63."""
    pact = get_object_or_404(Pact, slug=slug)
    if not (0 <= component < COMPONENTS):
        raise Http404(f'component must be 0..{COMPONENTS - 1}')
    packed = _packed_component_rules(pact)
    s = component * COMPONENT_PACKED_BYTES
    blob = packed[s:s + COMPONENT_PACKED_BYTES]
    resp = HttpResponse(blob, content_type='application/octet-stream')
    resp['Content-Disposition'] = (
        f'attachment; filename="{pact.slug}-rule-c{component:02d}.k4pack"')
    resp['Content-Length'] = str(len(blob))
    resp['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@login_required
def workspace_packed_all(request, slug):
    """All 64 components concatenated, packed — 256 KiB total."""
    pact = get_object_or_404(Pact, slug=slug)
    blob = _packed_component_rules(pact)
    resp = HttpResponse(blob, content_type='application/octet-stream')
    resp['Content-Disposition'] = (
        f'attachment; filename="{pact.slug}-rules-all64.k4pack"')
    resp['Content-Length'] = str(len(blob))
    resp['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@login_required
def workspace_packed_tar(request, slug):
    """All 64 components as a tar archive of individual .k4pack files.
    Same total bytes as workspace_packed_all but each component lives in
    its own file inside the archive (~262 KB tarred)."""
    import io
    import tarfile
    pact = get_object_or_404(Pact, slug=slug)
    packed = _packed_component_rules(pact)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for c in range(COMPONENTS):
            blob = packed[c * COMPONENT_PACKED_BYTES:
                              (c + 1) * COMPONENT_PACKED_BYTES]
            info = tarfile.TarInfo(name=f'{pact.slug}-rule-c{c:02d}.k4pack')
            info.size = len(blob)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(blob))
    blob_out = buf.getvalue()
    resp = HttpResponse(blob_out, content_type='application/x-tar')
    resp['Content-Disposition'] = (
        f'attachment; filename="{pact.slug}-rules-all64.tar"')
    resp['Content-Length'] = str(len(blob_out))
    resp['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


# ─── Metapact views ──────────────────────────────────────────────────


@login_required
def metapact_list(request):
    from .models import Metapact
    return render(request, 'spoeqi/metapact_list.html', {
        'metapacts': Metapact.objects.all()[:60],
    })


@login_required
def metapact_create(request):
    from .models import Metapact
    from .metachain import GRID_AREA
    import numpy as np
    from django.utils.text import slugify
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip() or 'untitled metapact'
        slug = slugify(request.POST.get('slug') or name)[:80]
        seed_int = int(request.POST.get('seed') or 0xCAFEBABE) & 0xFFFFFFFF
        depth = max(2, min(20, int(request.POST.get('depth') or 10)))
        ticks = max(4, min(64, int(request.POST.get('chain_ticks') or 24)))
        leaf = (request.POST.get('leaf_probe') or
                  'In the beginning the Universe was created. ' * 4)
        rng = np.random.default_rng(seed_int)
        seed_state = bytes(rng.integers(0, 4, size=GRID_AREA,
                                          dtype=np.uint8))
        m = Metapact.objects.create(
            name=name, slug=slug,
            seed_state=seed_state, depth=depth, chain_ticks=ticks,
            leaf_probe=leaf,
        )
        chain = m.expand()
        m.final_chain_quality = chain.chain_quality
        m.final_class4_depth  = chain.depth_class4
        m.save(update_fields=['final_chain_quality', 'final_class4_depth'])
        return redirect('spoeqi:metapact_detail', slug=m.slug)
    return render(request, 'spoeqi/metapact_create.html', {})


@login_required
def metapact_detail(request, slug):
    from .models import Metapact
    m = get_object_or_404(Metapact, slug=slug)
    chain = m.expand()
    return render(request, 'spoeqi/metapact_detail.html', {
        'metapact': m, 'chain': chain,
        'levels':   list(zip(range(chain.depth), chain.classes, chain.scores)),
    })


@login_required
def metapact_expand(request, slug):
    from .models import Metapact
    m = get_object_or_404(Metapact, slug=slug)
    chain = m.expand()
    return JsonResponse({
        'slug': m.slug, 'depth': chain.depth,
        'depth_class4': chain.depth_class4,
        'chain_quality': chain.chain_quality,
        'classes': chain.classes,
        'scores':  [round(s, 4) for s in chain.scores],
    })


@login_required
def metapact_bytes(request, slug):
    """Raw byte stream of the expanded chain — depth × 16,384 bytes.
    Other apps (caframe, recursive metachains) slice this however they
    like. Deterministic: same Metapact slug → same bytes."""
    from .models import Metapact
    m = get_object_or_404(Metapact, slug=slug)
    blob = m.expand().as_bytes()
    resp = HttpResponse(blob, content_type='application/octet-stream')
    resp['Content-Disposition'] = f'inline; filename="{slug}.metachain.bin"'
    resp['X-Metachain-Depth'] = str(m.depth)
    resp['Cache-Control'] = 'public, max-age=300'
    return resp


@login_required
def metapact_chat(request, slug):
    from .models import Metapact
    m = get_object_or_404(Metapact, slug=slug)
    return render(request, 'spoeqi/metapact_chat.html', {'metapact': m})


@login_required
def metapact_chat_reply(request, slug):
    from .models import Metapact
    from caformer.transformer import ca_generate_qkv
    from caformer.primitives import ASCII_PRINTABLE
    m = get_object_or_404(Metapact, slug=slug)
    q = (request.GET.get('q') or '').strip()
    if not q:
        return JsonResponse({'reply': '', 'error': 'empty prompt'})
    n = max(1, min(96, int(request.GET.get('n') or 24)))
    try:
        temperature = max(0.0, min(20.0,
                                      float(request.GET.get('temperature') or 0.8)))
    except ValueError:
        temperature = 0.8
    seed = int(request.GET.get('seed') or 0xC0FFEE) & 0x7FFFFFFF
    ascii_only = request.GET.get('ascii_only') in ('1', 'true', 'on', 'yes')
    kw = m.caformer_kwargs(n_blocks=1)
    prompt_ids = list(q.encode('utf-8'))[:64]
    out = ca_generate_qkv(prompt_ids, max_new_tokens=n, n_blocks=1,
                            vocab_size=256, temperature=temperature,
                            sample_seed=seed, base_seed=seed,
                            allowed_bytes=(ASCII_PRINTABLE if ascii_only else None),
                            **kw)
    reply = bytes(out).decode('latin-1', errors='replace')
    return JsonResponse({
        'reply': reply, 'tokens': out, 'metapact': m.slug,
        'prompt_len': len(prompt_ids),
    })


@login_required
def metapact_evolve(request, slug):
    from .models import Metapact
    m = get_object_or_404(Metapact, slug=slug)
    return render(request, 'spoeqi/metapact_evolve.html', {'metapact': m})


# Process-local stash for GA results, keyed by session.
_METAPACT_RESULTS: dict = {}
_METAPACT_RESULTS_CAP = 16


@login_required
async def metapact_evolve_stream(request, slug):
    import asyncio, json as _json, time
    from .models import Metapact
    from .metachain_ga import evolve_metapact, MetaGAConfig
    from asgiref.sync import sync_to_async
    m = await sync_to_async(get_object_or_404)(Metapact, slug=slug)

    def _ci(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.GET.get(name) or default)))
        except (TypeError, ValueError):
            return default

    # Optional self-reproduction term: the user opts in by passing
    # ?w_sr=<float>.  When > 0, each candidate's seed is also scored
    # by how closely the rule reproduces its own LUT-as-image — a
    # ruleset-quine fitness that turns the metapact into a stable
    # generator of itself at every chain level.
    try:
        w_sr = max(0.0, min(2.0, float(request.GET.get('w_sr') or 0.0)))
    except (TypeError, ValueError):
        w_sr = 0.0
    sr_ticks = _ci('sr_ticks', 64, 1, 256)
    cfg = MetaGAConfig(
        pop_size=_ci('pop_size', 8, 4, 24),
        generations=_ci('generations', 8, 1, 30),
        mutation_rate=float(request.GET.get('mutation_rate') or 0.002),
        seed=_ci('seed', 0xCAB00B5, 1, 2**31 - 1),
        depth=m.depth, chain_ticks=m.chain_ticks,
        w_sr=w_sr, sr_ticks=sr_ticks,
    )
    template_seed = bytes(m.seed_state)
    corpus = m.leaf_probe or ('In the beginning ' * 32)

    async def stream():
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'pop_size': cfg.pop_size, 'generations': cfg.generations,
                'depth': cfg.depth, 'chain_ticks': cfg.chain_ticks,
                'total_evals': cfg.pop_size * cfg.generations,
                'starting_seed_slug': m.slug,
            }) + '\n\n').encode()
            t0 = time.time()
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def _on_individual(gen_idx, ind_idx, comp, cq, lf, sr):
                loop.call_soon_threadsafe(q.put_nowait, ('ind', {
                    'gen': gen_idx, 'ind': ind_idx,
                    'fitness': float(comp), 'chain_q': float(cq),
                    'leaf_logprob': float(lf),
                    'self_reproduce': float(sr),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                }))

            def _on_generation(gen_idx, best, mean, worst):
                loop.call_soon_threadsafe(q.put_nowait, ('gen', {
                    'gen': gen_idx, 'best': float(best),
                    'mean': float(mean), 'worst': float(worst),
                    'elapsed_ms': int((time.time() - t0) * 1000),
                }))

            async def _runner():
                result = await asyncio.to_thread(
                    evolve_metapact,
                    corpus=corpus, template_seed=template_seed, cfg=cfg,
                    on_individual=_on_individual,
                    on_generation=_on_generation)
                await q.put(('done', result))

            run_task = asyncio.create_task(_runner())
            result = None
            try:
                while True:
                    kind, payload = await q.get()
                    if kind == 'done':
                        result = payload; break
                    elif kind == 'ind':
                        yield ('event: individual\ndata: '
                                + _json.dumps(payload) + '\n\n').encode()
                    else:
                        yield ('data: '
                                + _json.dumps(payload) + '\n\n').encode()
            finally:
                if not run_task.done():
                    run_task.cancel()

            sk = request.session.session_key or 'anon'
            if len(_METAPACT_RESULTS) >= _METAPACT_RESULTS_CAP:
                _METAPACT_RESULTS.pop(next(iter(_METAPACT_RESULTS)))
            _METAPACT_RESULTS[sk] = {
                'parent_slug':    m.slug,
                'seed_state':     result.best_seed,
                'fitness':        result.best_fitness,
                'chain_quality':  result.best_chain_quality,
                'leaf_fitness':   result.best_leaf_fitness,
                'self_reproduce': result.best_self_reproduce,
                'history':        result.history,
                'cfg':            cfg,
            }
            yield ('event: end\ndata: ' + _json.dumps({
                'best_fitness': result.best_fitness,
                'best_chain_quality': result.best_chain_quality,
                'best_leaf_logprob':  result.best_leaf_fitness,
                'best_self_reproduce': result.best_self_reproduce,
                'elapsed_ms': int((time.time() - t0) * 1000),
                'savable':    True,
            }) + '\n\n').encode()
        except asyncio.CancelledError:
            return

    from django.http import StreamingHttpResponse
    resp = StreamingHttpResponse(stream(), content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp


@login_required
@require_POST
def metapact_save_winner(request, slug):
    from .models import Metapact
    sk = request.session.session_key or 'anon'
    payload = _METAPACT_RESULTS.get(sk)
    if payload is None or payload.get('parent_slug') != slug:
        return JsonResponse({'ok': False,
            'error': 'no evolution result in this session for this metapact'})
    name = (request.POST.get('name') or '').strip()
    new_slug = (request.POST.get('slug') or '').strip()
    if not name or not new_slug:
        return JsonResponse({'ok': False, 'error': 'need name + slug'})
    parent = Metapact.objects.filter(slug=slug).first()
    if parent is None:
        return JsonResponse({'ok': False, 'error': 'parent metapact gone'})
    m = Metapact.objects.create(
        name=name[:80], slug=new_slug[:80],
        notes=(request.POST.get('notes') or ''),
        seed_state=payload['seed_state'],
        depth=parent.depth, chain_ticks=parent.chain_ticks,
        parent_seed=parent.seed_state,
        ga_generations=payload['cfg'].generations,
        ga_pop_size=payload['cfg'].pop_size,
        final_chain_quality=payload['chain_quality'],
        final_leaf_fitness=payload['leaf_fitness'],
        leaf_probe=parent.leaf_probe,
    )
    chain = m.expand()
    m.final_class4_depth = chain.depth_class4
    m.save(update_fields=['final_class4_depth'])
    return JsonResponse({'ok': True, 'slug': m.slug,
        'detail_url': reverse('spoeqi:metapact_detail',
                                 kwargs={'slug': m.slug})})


@login_required
@require_POST
def metapact_delete(request, slug):
    from .models import Metapact
    m = get_object_or_404(Metapact, slug=slug)
    m.delete()
    messages.success(request, f'metapact {slug!r} deleted')
    return redirect('spoeqi:metapact_list')


# ─── Metapact tournament — autotournament UI ─────────────────────────


@login_required
def metapact_tournament(request):
    """Render the autotournament page: shows current Metapacts + a
    one-click "▶ Run autotournament" form with sensible defaults."""
    from .models import Metapact
    return render(request, 'spoeqi/metapact_tournament.html', {
        'metapacts': Metapact.objects.all()[:30],
        'total':     Metapact.objects.count(),
    })


@login_required
async def metapact_tournament_stream(request):
    """SSE: stream a tournament run.  Auto-includes existing metapacts
    as contestants by default.  Each round's champion is saved as a
    new Metapact row with parent_seed pointing back to the previous
    round's champion (so the lineage is visible in the DB).
    """
    import asyncio, json as _json, time
    from asgiref.sync import sync_to_async
    from django.http import StreamingHttpResponse
    from .models import Metapact
    from .metapact_tournament import (
        TournamentConfig, run_tournament, save_round_winner,
    )

    def _ci(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.GET.get(name) or default)))
        except (TypeError, ValueError):
            return default

    cfg = TournamentConfig(
        n_contestants=_ci('contestants', 6, 3, 16),
        rounds=_ci('rounds', 4, 1, 8),
        survivors_per_round=_ci('survivors', 2, 1, 6),
        refine_generations=_ci('refine_gens', 5, 1, 20),
        refine_pop=_ci('refine_pop', 6, 3, 16),
        mutation_rate=float(request.GET.get('mutation_rate') or 0.003),
        depth=_ci('depth', 6, 2, 16),
        chain_ticks=_ci('chain_ticks', 16, 4, 48),
        seed=_ci('seed', 0xCAFE_7E, 1, 2**31 - 1),
        corpus=(request.GET.get('corpus') or ''),
        run_label=(request.GET.get('label')
                     or time.strftime('%y%m%d-%H%M')),
        save_winners=(request.GET.get('save') != '0'),
    )
    include_existing = request.GET.get('include') != '0'
    limit_include = _ci('limit_include', cfg.n_contestants, 1, cfg.n_contestants)

    if include_existing:
        seeds = await sync_to_async(list)(
            Metapact.objects.order_by('-final_leaf_fitness',
                                          '-final_chain_quality',
                                          '-created_at')
                              [:limit_include]
                              .values_list('seed_state', 'slug'))
        contestants = [bytes(s) for s, _ in seeds]
        seed_slugs = [sl for _, sl in seeds]
    else:
        contestants = []
        seed_slugs = []

    async def stream():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        try:
            yield ('event: meta\ndata: ' + _json.dumps({
                'cfg': {
                    'rounds': cfg.rounds,
                    'contestants': cfg.n_contestants,
                    'survivors': cfg.survivors_per_round,
                    'refine_pop': cfg.refine_pop,
                    'refine_gens': cfg.refine_generations,
                    'depth': cfg.depth, 'chain_ticks': cfg.chain_ticks,
                    'run_label': cfg.run_label,
                    'save_winners': cfg.save_winners,
                },
                'seed_slugs': seed_slugs,
            }) + '\n\n').encode()

            saved_slugs = []
            prev_champion = {'seed': None}

            def _emit(kind, payload):
                loop.call_soon_threadsafe(q.put_nowait, (kind, payload))

            def _on_save(round_idx, report):
                try:
                    m = save_round_winner(
                        report, cfg=cfg, run_label=cfg.run_label,
                        prior_champion_seed=prev_champion['seed'])
                except Exception as e:
                    _emit('error', {'msg': f'save failed: {e!r}'})
                    return
                saved_slugs.append(m.slug)
                prev_champion['seed'] = report.champion_seed
                _emit('saved', {
                    'round': round_idx,
                    'slug': m.slug,
                    'class4_depth': m.final_class4_depth,
                })

            async def _runner():
                # save_winner DB writes happen on the worker thread —
                # ORM is happy with that as long as no async-context
                # collision.  We wrap save_round_winner via sync_to_async
                # by delegating through _emit + a small helper.
                def _on_save_wrapper(round_idx, report):
                    _emit('save_request', {'round': round_idx,
                                            'report': report})

                # Note: we want save calls to actually happen, so we
                # call save_round_winner *directly* here — the GA runs
                # in to_thread anyway so DB writes are off the loop.
                result = await asyncio.to_thread(
                    run_tournament,
                    cfg=cfg, contestants=contestants,
                    on_event=_emit, on_save_winner=_on_save)
                _emit('done', result)

            run_task = asyncio.create_task(_runner())
            try:
                while True:
                    kind, payload = await q.get()
                    if kind == 'done':
                        yield ('event: end\ndata: ' + _json.dumps({
                            'winner_fitness':      payload.winner_fitness,
                            'winner_chain_q':      payload.winner_chain_q,
                            'winner_leaf_logprob': payload.winner_leaf_lp,
                            'elapsed_seconds':     payload.elapsed_seconds,
                            'saved_slugs':         saved_slugs,
                        }) + '\n\n').encode()
                        return
                    if kind == 'error':
                        yield ('event: error\ndata: '
                                + _json.dumps(payload) + '\n\n').encode()
                        continue
                    yield (f'event: {kind}\ndata: '
                            + _json.dumps(payload) + '\n\n').encode()
            finally:
                if not run_task.done():
                    run_task.cancel()
        except asyncio.CancelledError:
            return

    resp = StreamingHttpResponse(stream(),
                                  content_type='text/event-stream')
    resp['Cache-Control']     = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding']  = 'identity'
    return resp



# ─── Class-4 quine browser surface ────────────────────────────────────
#
# Backed by ComponentChampion with component_slug='class4_quine'.  The
# 16,384-byte seed lives in `rules_blob` (rule_names_csv='seed'),
# fitness is the strict SR, and the per-rule metrics (c4, activity,
# arbitrary-σ SR, chain run-length) live as JSON in `notes`.
# See spoeqi/metachain.py for the discovery + analysis helpers.

_QUINE_SLUG = 'class4_quine'


def _quine_meta(champion):
    """Parse the JSON-blob meta on a class4_quine ComponentChampion."""
    try:
        m = json.loads(champion.notes or '{}')
        if not isinstance(m, dict):
            return {}
        return m
    except (ValueError, TypeError):
        return {}


_QUINE_SORT_FIELDS = {
    'pk':       'pk',
    'fitness':  'fitness',
    'created':  'created_at',
    'label':    'run_label',
}


@login_required
def quine_index(request):
    """List saved class-4 quine candidates with pagination, filters,
    sortable columns, inline LUT thumbnails, and summary stats.

    Query params (all optional):
        page       integer (1-based)
        per_page   25 | 50 | 100 | 200  (default 50)
        sort       pk | fitness | created | label | c4 | act |
                   arbsigma | run_len  (default fitness)
        dir        asc | desc          (default desc)
        min_sr     float, min strict SR
        min_c4     float, min c4 score
        min_run    int,   min class-4 chain run length
        origin     substring of meta.origin
        label      substring of run_label
        sha        hex prefix of sha1(rules_blob)[:8]
    """
    from caformer.models import ComponentChampion
    from django.core.paginator import Paginator, EmptyPage

    qs = ComponentChampion.objects.filter(component_slug=_QUINE_SLUG)

    # Server-side filters that hit the DB columns.
    label_q = (request.GET.get('label') or '').strip()
    if label_q:
        qs = qs.filter(run_label__icontains=label_q)

    # Sort field: only fitness/pk/created/label can be DB-sorted; the
    # meta-derived fields require post-filter Python sort.
    sort = (request.GET.get('sort') or 'fitness').lower()
    direction = (request.GET.get('dir') or 'desc').lower()
    sign = '-' if direction == 'desc' else ''
    if sort in _QUINE_SORT_FIELDS:
        qs = qs.order_by(f'{sign}{_QUINE_SORT_FIELDS[sort]}', '-pk')
        post_sort = False
    else:
        qs = qs.order_by('-fitness', '-pk')
        post_sort = sort in ('c4', 'act', 'arbsigma', 'run_len')

    # Materialise (with meta-filters applied) so we know total after filters.
    def _ci(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.GET.get(name, default))))
        except (TypeError, ValueError):
            return default
    def _cf(name, default):
        try:
            return float(request.GET.get(name, default))
        except (TypeError, ValueError):
            return default
    min_sr  = _cf('min_sr', 0.0)
    min_c4  = _cf('min_c4', 0.0)
    min_run = _ci('min_run', 0, 0, 200)
    origin_q = (request.GET.get('origin') or '').strip().lower()
    sha_q    = (request.GET.get('sha') or '').strip().lower()

    rows: list = []
    n_total_unfiltered = qs.count()
    # Iterate in chunks to avoid loading 1700+ champions all at once;
    # we still need to compute meta-fields client-side to filter on them.
    for c in qs.iterator(chunk_size=200):
        if min_sr and (c.fitness or 0.0) < min_sr:
            continue
        m = _quine_meta(c)
        c4_v   = float(m.get('c4', 0.0))
        run_v  = int(m.get('class4_run_length', 0))
        origin_v = str(m.get('origin', '?'))
        if min_c4 and c4_v < min_c4:
            continue
        if min_run and run_v < min_run:
            continue
        if origin_q and origin_q not in origin_v.lower():
            continue
        sha = hashlib.sha1(bytes(c.rules_blob)).hexdigest()[:8] \
                if c.rules_blob else ''
        if sha_q and not sha.startswith(sha_q):
            continue
        rows.append({
            'pk':        c.pk,
            'fitness':   c.fitness or 0.0,
            'c4':        c4_v,
            'act':       float(m.get('act', 0.0)),
            'arbsigma':  float(m.get('arbsigma', 0.0)),
            'run_len':   run_v,
            'origin':    origin_v,
            'sha':       sha,
            'created':   c.created_at,
            'run_label': c.run_label,
            'refined':   bool(m.get('refined', False)),
        })

    # Post-filter sort on derived columns when needed.
    if post_sort:
        key_map = {
            'c4': lambda r: r['c4'],
            'act': lambda r: r['act'],
            'arbsigma': lambda r: r['arbsigma'],
            'run_len': lambda r: r['run_len'],
        }
        rows.sort(key=key_map[sort], reverse=(direction == 'desc'))

    n_filtered = len(rows)

    # Summary stats on the filtered set.
    if rows:
        srs = [r['fitness'] for r in rows]
        c4s = [r['c4']      for r in rows]
        runs = [r['run_len'] for r in rows]
        origins_seen: dict = {}
        for r in rows:
            origins_seen[r['origin']] = origins_seen.get(r['origin'], 0) + 1
        stats = {
            'n':         n_filtered,
            'sr_mean':   sum(srs) / len(srs),
            'sr_max':    max(srs),
            'c4_mean':   sum(c4s) / len(c4s),
            'c4_max':    max(c4s),
            'run_max':   max(runs),
            'run_mean':  sum(runs) / len(runs),
            'origins':   sorted(origins_seen.items(),
                                  key=lambda kv: -kv[1])[:5],
        }
    else:
        stats = None

    per_page = _ci('per_page', 50, 10, 200)
    paginator = Paginator(rows, per_page)
    try:
        page_obj = paginator.page(_ci('page', 1, 1, paginator.num_pages or 1))
    except EmptyPage:
        page_obj = paginator.page(1)

    # Headers that toggle direction when clicked.
    def _header_url(col):
        cur = sort
        nxt_dir = ('asc' if (cur == col and direction == 'desc') else 'desc')
        return _qs_with(request, sort=col, dir=nxt_dir, page=1)
    sortable_headers = [
        ('pk',       '#',         _header_url('pk')),
        ('fitness',  'SR',        _header_url('fitness')),
        ('arbsigma', 'SRarbσ',    _header_url('arbsigma')),
        ('c4',       'c4',        _header_url('c4')),
        ('act',      'act',       _header_url('act')),
        ('run_len',  'chain',     _header_url('run_len')),
        ('label',    'label',     _header_url('label')),
        ('created',  'created',   _header_url('created')),
    ]
    return render(request, 'spoeqi/quine_index.html', {
        'page_obj':         page_obj,
        'rows':             page_obj.object_list,
        'paginator':        paginator,
        'sortable_headers': sortable_headers,
        'sort':             sort,
        'direction':        direction,
        'n_total':          n_total_unfiltered,
        'n_filtered':       n_filtered,
        'per_page':         per_page,
        'filters': {
            'min_sr':  request.GET.get('min_sr', ''),
            'min_c4':  request.GET.get('min_c4', ''),
            'min_run': request.GET.get('min_run', ''),
            'origin':  request.GET.get('origin', ''),
            'label':   label_q,
            'sha':     sha_q,
        },
        'stats':            stats,
        'base_qs':          _qs_without(request, 'page'),
    })


def _qs_with(request, **overrides) -> str:
    """Render the current query string with one or more params overridden."""
    from django.http import QueryDict
    qd = request.GET.copy()
    for k, v in overrides.items():
        if v in (None, '', 0) and k not in ('page',):
            qd.pop(k, None)
        else:
            qd[k] = str(v)
    return '?' + qd.urlencode() if qd else ''


def _qs_without(request, *drop) -> str:
    qd = request.GET.copy()
    for k in drop:
        qd.pop(k, None)
    return qd.urlencode()


@login_required
@require_POST
def quine_search(request):
    """Run a block-flip-from-identity sweep + hill-climb, persist the
    top winners as ComponentChampion(class4_quine) rows."""
    from caformer.models import ComponentChampion
    from spoeqi.metachain import (
        block_flip_search, hill_climb_quine, walk_chain,
        sr_arbitrary_sigma)
    import time

    def _ci(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.POST.get(name, default))))
        except (TypeError, ValueError):
            return default
    n_trials      = _ci('n_trials',      300, 50, 2000)
    n_keep        = _ci('n_keep',          3,  1,   20)
    climb_passes  = _ci('climb_passes',    1,  0,    8)
    climb_sample  = _ci('climb_sample', 1024, 128, 4096)
    label         = (request.POST.get('label') or 'browser').strip()[:40]

    rng_seed = int(time.time()) & 0xFFFFFFFF
    keepers = block_flip_search(n_trials=n_trials, rng_seed=rng_seed)
    if not keepers:
        messages.warning(request,
            f'block-flip sweep ({n_trials} trials) produced no candidates '
            f'matching SR>0.30 and activity in [0.05, 0.5].  Try more trials.')
        return redirect('spoeqi:quine_index')

    saved = 0
    for k in keepers[:n_keep]:
        seed = k['seed']
        sr, c4, act = k['sr'], k['c4'], k['act']
        block, nblk = k['block'], k['n_blocks']
        if climb_passes > 0:
            out = hill_climb_quine(seed, passes=climb_passes,
                                       sample_size=climb_sample)
            seed = out['seed']
            sr, c4, act = out['sr'], out['c4'], out['act']
        chain = walk_chain(seed, depth=20)
        arbs = sr_arbitrary_sigma(seed, ticks=16)
        meta = {
            'origin':            'block-flip + hill-climb',
            'sr':                float(sr),
            'c4':                float(c4),
            'act':               float(act),
            'arbsigma':          float(arbs),
            'class4_run_length': int(chain['class4_run_length']),
            'block_size':        int(block),
            'n_blocks':          int(nblk),
            'climb_passes':      climb_passes,
            'rng_seed':          rng_seed,
        }
        ComponentChampion.objects.create(
            component_slug=_QUINE_SLUG,
            rules_blob=seed,
            rule_names_csv='seed',
            fitness=float(sr),
            generation=0,
            run_label=label,
            ga_pop_size=0, ga_generations=0,
            eval_count=n_trials,
            notes=json.dumps(meta),
        )
        saved += 1
    messages.success(request,
        f'block-flip sweep: {len(keepers)} candidates / {n_trials} trials, '
        f'saved top {saved} (climb_passes={climb_passes}).')
    return redirect('spoeqi:quine_index')


@login_required
def quine_image(request):
    """Upload-and-test: image → posterize-to-4 → score as quine LUT.

    GET:  show upload form + (if any) the most recent image-quines.
    POST: process the uploaded image and render the result inline.

    The 16,384-byte candidate LUT is held in the session so the user
    can click "save this" without re-uploading.  Session keys expire
    when the session expires.
    """
    from caformer.models import ComponentChampion
    from . import image_quine as iq

    if request.method != 'POST':
        # Recent image-quine archive (last 48 — it's a gallery now).
        from django.conf import settings
        recent = []
        for c in (ComponentChampion.objects
                       .filter(component_slug=_QUINE_SLUG,
                                 run_label__startswith='img:')
                       .order_by('-pk')[:48]):
            m = _quine_meta(c)
            src_rel = (m.get('source_image_rel') or '').strip()
            recent.append({
                'pk':         c.pk,
                'label':      (c.run_label or '')[4:],   # strip 'img:'
                'fitness':    c.fitness or 0.0,
                'meta':       m,
                'source_url': (f'{settings.MEDIA_URL}{src_rel}'
                                 if src_rel else ''),
                'posterized_url': reverse('spoeqi:quine_posterized_png',
                                              args=[c.pk]),
            })
        n_total = (ComponentChampion.objects
                       .filter(component_slug=_QUINE_SLUG,
                                 run_label__startswith='img:').count())
        return render(request, 'spoeqi/quine_image.html', {
            'mode':    'form',
            'recent':  recent,
            'n_total': n_total,
        })

    # POST: process the upload.
    f = request.FILES.get('image')
    if not f:
        messages.warning(request, 'no image file submitted')
        return redirect('spoeqi:quine_image')
    if f.size > 20 * 1024 * 1024:
        messages.warning(request,
            f'image too large ({f.size/1024/1024:.1f} MB) — limit 20 MB')
        return redirect('spoeqi:quine_image')

    label = (request.POST.get('label') or f.name or 'upload').strip()[:120]
    quantize = request.POST.get('quantize') or 'median_cut'
    if quantize not in ('median_cut', 'kmeans', 'fast_octree'):
        quantize = 'median_cut'

    try:
        file_bytes = f.read()
        result = iq.image_to_rule(file_bytes, quantize=quantize,
                                       preview_scale=4)
    except Exception as e:
        messages.warning(request, f'failed to read image: {e}')
        return redirect('spoeqi:quine_image')

    try:
        scores = iq.score_rule(result.rule_bytes)
    except Exception as e:
        messages.warning(request, f'scoring failed: {e}')
        return redirect('spoeqi:quine_image')

    rule_sha = hashlib.sha1(result.rule_bytes).hexdigest()
    # Persist a resized copy of the source image immediately — we want
    # the library page to show originals later even if the user never
    # explicitly hits "save", and the file goes under MEDIA_ROOT keyed
    # by sha1 so the same image won't be stored twice.
    try:
        source_rel = iq.save_source_image(file_bytes, sha1=rule_sha)
    except Exception as e:
        source_rel = ''
        messages.warning(request, f'note: source image save failed ({e})')

    # Stash the candidate so the save endpoint can pick it up without
    # re-uploading.  Session-stored bytes go through base64 because the
    # default JSON serializer can't handle raw bytes.
    import base64
    request.session['image_quine_pending'] = {
        'rule_b64':       base64.b64encode(result.rule_bytes).decode('ascii'),
        'palette_rgb':    [list(rgb) for rgb in result.palette_rgb],
        'src_size':       [int(result.src_size[0]), int(result.src_size[1])],
        'quantize':       result.quantize_method,
        'label':          label,
        'sha':            rule_sha,
        'source_rel':     source_rel,
    }
    request.session.modified = True

    # Cheap preview PNG inline as data: URL — avoids a second request.
    import base64
    preview_b64 = base64.b64encode(result.preview_png).decode('ascii')
    preview_data_url = f'data:image/png;base64,{preview_b64}'

    existing = (ComponentChampion.objects
                    .filter(component_slug=_QUINE_SLUG,
                              rules_blob=result.rule_bytes).first())

    from django.conf import settings
    source_url = (f'{settings.MEDIA_URL}{source_rel}'
                    if source_rel else '')

    return render(request, 'spoeqi/quine_image.html', {
        'mode':            'result',
        'label':           label,
        'quantize':        result.quantize_method,
        'src_size':        result.src_size,
        'source_url':      source_url,
        'preview_data_url': preview_data_url,
        'scores':          scores,
        'palette_rgb':     result.palette_rgb,
        'palette_hex':     ['#%02x%02x%02x' % rgb for rgb in result.palette_rgb],
        'rule_sha':        rule_sha,
        'rule_sha8':       rule_sha[:8],
        'is_official':     iq.is_official_quine(scores),
        'is_interesting':  iq.is_interesting(scores),
        'thresholds':      {
            'sr_strict':   iq.QUINE_SR_STRICT_THRESHOLD,
            'sr_arbsigma': iq.QUINE_SR_ARBSIGMA_THRESHOLD,
            'interest':    iq.INTERESTING_SR_THRESHOLD,
        },
        'existing':        existing,
    })


@login_required
@require_POST
def quine_image_save(request):
    """Persist the most recently tested image-quine to the archive."""
    from . import image_quine as iq
    import base64

    pending = request.session.get('image_quine_pending')
    if not pending:
        messages.warning(request,
            'nothing to save — re-upload the image first')
        return redirect('spoeqi:quine_image')

    rule_bytes = base64.b64decode(pending['rule_b64'])
    if len(rule_bytes) != iq.LUT_SIZE:
        messages.warning(request,
            f'pending rule wrong length ({len(rule_bytes)} B)')
        return redirect('spoeqi:quine_image')

    scores = iq.score_rule(rule_bytes)

    # Allow the user to force-save below the threshold via an override.
    force = bool(request.POST.get('force'))
    if not (iq.is_official_quine(scores) or force):
        messages.warning(request,
            f'SR={scores["sr_strict"]:.3f}, arbσ={scores["sr_arbsigma"]:.3f} — '
            f'below thresholds; tick "force" to save anyway')
        return redirect('spoeqi:quine_image')

    palette = [tuple(rgb) for rgb in pending['palette_rgb']]
    label   = pending.get('label') or 'image-upload'
    src_size = tuple(pending.get('src_size') or (0, 0))
    quantize = pending.get('quantize') or 'median_cut'
    source_rel = pending.get('source_rel') or ''

    obj, created = iq.persist_image_quine(
        rule_bytes,
        scores=scores,
        image_label=label,
        quantize_method=quantize,
        src_size=src_size,
        palette_rgb=palette,
        source_image_rel=source_rel)

    if created:
        messages.success(request,
            f'saved as quine #{obj.pk} (SR={scores["sr_strict"]:.4f}, '
            f'arbσ={scores["sr_arbsigma"]:.4f})')
    else:
        messages.warning(request,
            f'identical LUT already saved as quine #{obj.pk}')
    # Clear pending state so a refresh doesn't re-save.
    request.session.pop('image_quine_pending', None)
    return redirect('spoeqi:quine_detail', pk=obj.pk)


@login_required
def quine_posterized_png(request, pk):
    """Render the 128×128 posterized image for an image-derived quine.

    Reconstructs from rules_blob + meta['palette_rgb'] — no extra
    storage needed since the LUT IS the posterized image, bijectively.
    Works for any class4_quine row; non-image-upload rows get the
    default 4-colour palette.
    """
    from caformer.models import ComponentChampion
    from . import image_quine as iq
    from django.views.decorators.http import condition

    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    meta = _quine_meta(c)
    palette_rgb = meta.get('palette_rgb') or [
        [220, 80, 40], [60, 120, 210], [80, 180, 90], [230, 200, 60]]
    palette_rgb = [tuple(rgb) for rgb in palette_rgb]
    try:
        scale = max(1, min(8, int(request.GET.get('scale', 2))))
    except (TypeError, ValueError):
        scale = 2
    png = iq.reconstruct_posterized_png(bytes(c.rules_blob),
                                              palette_rgb, scale=scale)
    resp = HttpResponse(png, content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=3600'
    return resp


@login_required
def quine_detail(request, pk):
    """Detail page: chain walk + per-level stats + actions."""
    from caformer.models import ComponentChampion
    from spoeqi.metachain import walk_chain
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    try:
        depth = max(5, min(60, int(request.GET.get('depth', 20))))
    except (TypeError, ValueError):
        depth = 20
    seed = bytes(c.rules_blob)
    walk = walk_chain(seed, depth=depth)
    return render(request, 'spoeqi/quine_detail.html', {
        'champion':           c,
        'meta':               _quine_meta(c),
        'levels':             walk['levels'],
        'class4_run_length':  walk['class4_run_length'],
        'depth':              depth,
        'seed_size_bytes':    len(seed),
    })


@login_required
@require_POST
def quine_refine(request, pk):
    """Hill-climb a saved candidate further, update in place."""
    from caformer.models import ComponentChampion
    from spoeqi.metachain import (
        hill_climb_quine, walk_chain, sr_arbitrary_sigma)
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    def _ci(name, d, lo, hi):
        try: return max(lo, min(hi, int(request.POST.get(name, d))))
        except (TypeError, ValueError): return d
    passes = _ci('passes',      2,   1,    8)
    sample = _ci('sample',   1024, 128, 4096)
    out = hill_climb_quine(bytes(c.rules_blob),
                              passes=passes, sample_size=sample)
    walk = walk_chain(out['seed'], depth=20)
    meta = _quine_meta(c)
    meta.update({
        'sr':                float(out['sr']),
        'c4':                float(out['c4']),
        'act':               float(out['act']),
        'arbsigma':          float(sr_arbitrary_sigma(out['seed'], ticks=16)),
        'class4_run_length': int(walk['class4_run_length']),
        'refined':           True,
        'refine_passes':     (meta.get('refine_passes', 0) or 0) + passes,
    })
    c.rules_blob = out['seed']
    c.fitness    = float(out['sr'])
    c.eval_count = (c.eval_count or 0) + passes * sample
    c.notes      = json.dumps(meta)
    c.save(update_fields=('rules_blob', 'fitness', 'eval_count', 'notes'))
    messages.success(request,
        f'refined #{c.pk}: SR={out["sr"]:.4f}, c4={out["c4"]:.4f}, '
        f'class-4 chain run={walk["class4_run_length"]} levels.')
    return redirect('spoeqi:quine_detail', pk=c.pk)


@login_required
@require_POST
def quine_delete(request, pk):
    from caformer.models import ComponentChampion
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    c.delete()
    messages.success(request, f'deleted quine candidate #{pk}')
    return redirect('spoeqi:quine_index')


@login_required
def quine_seed_bytes(request, pk):
    """Raw 16,384-byte seed download."""
    from caformer.models import ComponentChampion
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    resp = HttpResponse(bytes(c.rules_blob),
                          content_type='application/octet-stream')
    resp['Content-Disposition'] = f'attachment; filename="quine-{c.pk}.bin"'
    return resp


@login_required
@require_POST
def quine_to_pact(request, pk):
    """Mint a spoeqi Pact from a saved class-4 quine candidate.

    Modes:
      ``shared``  — single-rule Pact: all 64 components share this
                      quine's rule.  Cheap; the rule's class-4 dynamics
                      drive every component identically.
      ``mutated`` — single-rule Pact with per-component mutation: this
                      quine is the base; each component gets a small
                      deterministic perturbation.  Same diversity model
                      as the standard Pact ``mutated`` mode but using
                      a quine instead of a random rule as the base.
      ``chain``   — fleet Pact built from the metachain: walk 64 levels
                      from this quine, use level i as component i's rule.
                      Each component is a *distinct* class-4 rule that
                      is structurally related to its neighbours (each
                      level is derived from the previous by the rule's
                      own dynamics).  Filled with cycle-extension if the
                      chain closes before 64 levels.
    """
    from caformer.models import ComponentChampion
    from .models import (
        Pact, RULE_TABLE_SIZE, COMPONENTS, COMPONENT_GRID,
        COMPONENT_GRID_CHOICES,
    )
    from .metachain import chain_seeds
    import hashlib as _hashlib

    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    mode = (request.POST.get('mode') or 'shared').strip().lower()
    if mode not in ('shared', 'mutated', 'chain'):
        mode = 'shared'

    base_rule = bytes(c.rules_blob)
    if len(base_rule) != RULE_TABLE_SIZE:
        messages.error(request,
            f'quine #{c.pk}: rules_blob is {len(base_rule)} bytes, '
            f'expected {RULE_TABLE_SIZE}.')
        return redirect('spoeqi:quine_detail', pk=c.pk)

    # Generate a deterministic 64-byte seed_matrix from the rule so
    # the same quine always seals the same Pact (modulo name + time).
    seed_matrix = _hashlib.sha512(base_rule).digest()[:COMPONENTS]

    name = (request.POST.get('name') or '').strip()
    if not name:
        import time as _t
        name = f'quine-{c.pk}-{mode}-{int(_t.time()) % 100000}'
    name = name[:80]

    rule_diversity = mode if mode in ('shared', 'mutated') else 'fleet'
    rules_snapshot = None
    fleet_candidate_ids = None
    rule = base_rule
    if mode == 'chain':
        # Walk to 64 levels; if the chain cycles earlier, repeat the
        # available levels to fill all 64 components.
        levels = chain_seeds(base_rule, depth=COMPONENTS, ticks_per_level=16)
        if not levels:
            messages.error(request, 'chain_seeds returned no levels')
            return redirect('spoeqi:quine_detail', pk=c.pk)
        if len(levels) < COMPONENTS:
            # Tile the chain
            levels = (levels * ((COMPONENTS // len(levels)) + 1))[:COMPONENTS]
        rules_snapshot = b''.join(levels)
        rule = levels[0]  # first chain level as the single-rule default

    # Default palette: same 4-state K=4 anchors as the standard new-pact
    # form ships with (medium-saturation hexagonal mood).
    palette = [
        [40, 50, 70],
        [220, 100, 60],
        [120, 180, 200],
        [240, 220, 110],
    ]

    pact = Pact(
        name=name,
        party_a=(request.POST.get('party_a') or 'Alice').strip()[:40],
        party_b=(request.POST.get('party_b') or 'Bob').strip()[:40],
        seed_matrix=seed_matrix,
        rule_snapshot=rule,
        rules_snapshot=rules_snapshot,
        rule_diversity=rule_diversity,
        mutation_density=1024,
        palette=palette,
        clock_model='synced',
        tick_ms=250,
        component_grid=COMPONENT_GRID,
        launch_time=timezone.now(),
        notes=(f'Minted from class-4 quine candidate #{c.pk} '
                 f'(mode={mode}). Strict SR={c.fitness:.4f}.\n'
                 f'See /spoeqi/quine/{c.pk}/ for the source.'),
        det_candidate=None,
        fleet_candidate_ids=fleet_candidate_ids,
        created_by=request.user if request.user.is_authenticated else None,
    )
    pact.save()
    messages.success(request,
        f'Pact "{pact.name}" sealed from quine #{c.pk} '
        f'(mode={mode}, diversity={rule_diversity}).')
    return redirect('spoeqi:detail', slug=pact.slug)


# ─── Chain stream miner ──────────────────────────────────────────────
#
# 16 KB quine seed → 64 chain levels (each a distinct class-4 CA) →
# each runs as a deterministic data source.  This is the "compressed
# database in a small numberset" pattern: the seed is the only thing
# that needs to be shared, and any consumer can re-expand it to
# arbitrary amounts of per-level CA data.


def _quine_stream_init_seed(quine_pk: int, level: int) -> int:
    """Deterministic per-level LCG seed so streams are reproducible."""
    return ((quine_pk * 2654435761) ^ (level * 0x9E3779B1)
            ^ 0xCA1ED175) & 0xFFFFFFFF


@login_required
def quine_streams(request, pk):
    """Index page: list every chain level + offer downloads."""
    from caformer.models import ComponentChampion
    from .metachain import chain_seeds, classify_rule, probe_activity
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    seed = bytes(c.rules_blob)
    depth = max(1, min(64, int(request.GET.get('depth', 64))))
    try:
        ticks = max(1, min(2048, int(request.GET.get('ticks', 64))))
    except (TypeError, ValueError):
        ticks = 64

    levels_bytes = chain_seeds(seed, depth=depth, ticks_per_level=16)
    levels = []
    for i, rb in enumerate(levels_bytes):
        cls, c4 = classify_rule(rb, probe_ticks=16)
        act = probe_activity(rb, ticks=12)
        levels.append({
            'level':  i,
            'cls':    cls,
            'c4':     c4,
            'act':    act,
            'init_seed': _quine_stream_init_seed(c.pk, i),
            'distinct': i < len(set(levels_bytes[:i + 1])),
            'tile_of':  None,
        })
    # Mark which levels are duplicates (chain cycled and got tiled)
    seen = {}
    for i, rb in enumerate(levels_bytes):
        if rb in seen:
            levels[i]['tile_of'] = seen[rb]
        else:
            seen[rb] = i
    chain_full_length = len(levels_bytes)
    bytes_per_level_packed = ticks * 4096    # 4 cells per byte
    bytes_per_level_raw    = ticks * 16384   # 1 byte per cell
    total_bytes_packed = depth * bytes_per_level_packed
    total_bytes_raw    = depth * bytes_per_level_raw
    return render(request, 'spoeqi/quine_streams.html', {
        'champion':         c,
        'levels':           levels,
        'depth':            depth,
        'ticks':            ticks,
        'chain_full':       chain_full_length,
        'bytes_per_level':  bytes_per_level_packed,
        'bytes_per_level_packed': bytes_per_level_packed,
        'bytes_per_level_raw':    bytes_per_level_raw,
        'total_bytes':      total_bytes_packed,
        'total_bytes_packed':     total_bytes_packed,
        'total_bytes_raw':        total_bytes_raw,
        'seed_bytes':       len(seed),
    })


@login_required
def quine_stream_download(request, pk, level):
    """Bytes for one chain level's CA running ``?ticks=N`` ticks from a
    deterministic init.  Default output is packed K=4 (4 cells per
    byte; ``ticks × 4,096`` bytes), giving researchers dense 8-bit
    data instead of mostly-zero 2-bit cells.  Pass ``?raw=1`` to get
    the unpacked ``ticks × 16,384`` byte stream (one byte per cell,
    high 6 bits always zero)."""
    from caformer.models import ComponentChampion
    from .metachain import chain_seeds, run_ca_stream
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    levels = chain_seeds(bytes(c.rules_blob), depth=max(level + 1, 64),
                            ticks_per_level=16)
    if level < 0 or level >= len(levels):
        raise Http404(f'level {level} beyond chain length {len(levels)}')
    try:
        ticks = max(1, min(2048, int(request.GET.get('ticks', 64))))
    except (TypeError, ValueError):
        ticks = 64
    raw_mode = request.GET.get('raw', '') in ('1', 'true', 'yes')
    init_seed = _quine_stream_init_seed(c.pk, level)
    stream = run_ca_stream(levels[level], init_seed=init_seed, ticks=ticks,
                              packed=not raw_mode)
    resp = HttpResponse(stream, content_type='application/octet-stream')
    tag = 'raw' if raw_mode else 'packed'
    resp['Content-Disposition'] = (
        f'attachment; filename="quine-{c.pk}-L{level:02d}-t{ticks}-{tag}.bin"')
    resp['X-Stream-Init-Seed'] = str(init_seed)
    resp['X-Stream-Format'] = (
        'k4-raw-1byte-per-cell' if raw_mode
        else 'k4-packed-4cells-per-byte (LSB=cell0)')
    return resp


def _quine_default_ansi_palette() -> bytes:
    """4 ANSI-256 indices matching spoeqi's DEFAULT_PALETTE RGB triples.
    Used when importing a chain rule into Taxon so the rule has a
    sensible default render — the user can reroll via taxon UI."""
    from automaton.packed import nearest_ansi256
    from spoeqi.models import DEFAULT_PALETTE
    return bytes(nearest_ansi256(tuple(c)) for c in DEFAULT_PALETTE)


@login_required
def quine_chain_to_taxon(request, pk, level):
    """Materialise the (quine pk, chain level) rule, import as a Taxon
    Rule (kind=hex_k4_lut), tag it as a quine with the SR scores and
    nest depth, then redirect to /taxon/rules/<slug>/.

    Idempotent on the rule's sha1; clicking the same level repeatedly
    reuses the existing Taxon Rule and just refreshes the classification.
    """
    from caformer.models import ComponentChampion
    from taxon.models import Classification
    from taxon.importers import upsert_hex_lut
    from .metachain import (chain_seeds, classify_rule, probe_activity,
                              sr_arbitrary_sigma, self_reproduce_score,
                              walk_chain)
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    seed = bytes(c.rules_blob)
    depth = max(1, min(64, level + 1))
    levels = chain_seeds(seed, depth=max(level + 1, 8), ticks_per_level=16)
    if level < 0 or level >= len(levels):
        raise Http404(f'level {level} beyond chain length {len(levels)}')
    lut = levels[level]

    cls, c4 = classify_rule(lut, probe_ticks=16)
    act = probe_activity(lut, ticks=12)
    sr_strict = self_reproduce_score(lut, ticks=16)
    sr_arbs = sr_arbitrary_sigma(lut, ticks=16)
    sub_chain = walk_chain(lut, depth=20)
    nest_depth = int(sub_chain.get('class4_run_length', 0))

    name = f'spoeqi quine #{c.pk} L{level:02d}'
    rule = upsert_hex_lut(
        lut, _quine_default_ansi_palette(),
        name=name, source='spoeqi',
        source_ref=f'quine={c.pk}; chain_level={level}',
    )
    Classification.objects.create(
        rule=rule, wolfram_class=int(cls),
        confidence=float(c4),
        basis_json={'c4': c4, 'activity': act,
                    'probe_ticks': 16, 'probe_size': 128},
        is_quine=bool(sr_strict >= 0.30 or sr_arbs >= 0.85),
        sr_strict=float(sr_strict),
        sr_arbsigma=float(sr_arbs),
        nest_depth=nest_depth,
        quine_origin=f'spoeqi quine #{c.pk} chain L{level}',
    )
    return redirect('taxon:rule_detail', slug=rule.slug)


@login_required
def quine_streams_bundle(request, pk):
    """Zip bundle of every chain level's stream + a manifest JSON.

    The manifest records exactly which seed + LCG init + tick count
    produced each file, so a consumer with only the seed + manifest
    can re-derive the entire bundle byte-for-byte.
    """
    import io
    import zipfile
    from caformer.models import ComponentChampion
    from .metachain import chain_seeds, run_ca_stream, classify_rule
    c = get_object_or_404(ComponentChampion, pk=pk,
                            component_slug=_QUINE_SLUG)
    depth = max(1, min(64, int(request.GET.get('depth', 64))))
    try:
        ticks = max(1, min(512, int(request.GET.get('ticks', 32))))
    except (TypeError, ValueError):
        ticks = 32
    seed = bytes(c.rules_blob)
    levels = chain_seeds(seed, depth=depth, ticks_per_level=16)

    raw_mode = request.GET.get('raw', '') in ('1', 'true', 'yes')
    buf = io.BytesIO()
    manifest = {
        'quine_pk':       c.pk,
        'quine_sr':       c.fitness,
        'seed_size':      len(seed),
        'chain_depth':    len(levels),
        'ticks_per_level': ticks,
        'bytes_per_tick': 16384 if raw_mode else 4096,
        'stream_format':  (
            'concatenated post-tick 128x128 grids, one byte per cell, '
            'K=4 values in [0,3]' if raw_mode else
            'concatenated post-tick 128x128 grids, packed K=4 — '
            '4 cells per byte (LSB-first), so each tick = 4,096 bytes'),
        'levels': [],
    }
    with zipfile.ZipFile(buf, mode='w',
                            compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('seed.bin', seed)
        for i, rb in enumerate(levels):
            init_seed = _quine_stream_init_seed(c.pk, i)
            stream = run_ca_stream(rb, init_seed=init_seed, ticks=ticks,
                                      packed=not raw_mode)
            zf.writestr(f'streams/L{i:02d}.bin', stream)
            cls, c4 = classify_rule(rb, probe_ticks=16)
            manifest['levels'].append({
                'level':     i,
                'init_seed': init_seed,
                'class':     cls,
                'c4_score':  c4,
                'bytes':     len(stream),
            })
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    payload = buf.getvalue()
    resp = HttpResponse(payload, content_type='application/zip')
    resp['Content-Disposition'] = (
        f'attachment; filename="quine-{c.pk}-streams-d{depth}-t{ticks}.zip"')
    return resp

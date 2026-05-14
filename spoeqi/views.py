"""spoeqi views — list, create, detail.

The detail page is the substantive surface: it hands a Pact's seed,
rule, palette, and launch time to client-side JS that runs the 64
component CAs in lockstep.  The server is otherwise inert; it does
not stream state.
"""

from __future__ import annotations
import json
import secrets

from django.contrib import messages
from django.http import HttpResponseRedirect, Http404, JsonResponse
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

    if request.method == 'POST':
        form.update({k: request.POST.get(k, form.get(k, '')) for k in form})

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

ORACLE_MODEL_CHOICES = [
    'distilgpt2',
    'gpt2',
    'EleutherAI/pythia-70m',
    'TinyLlama/TinyLlama-1.1B-Chat-v1.0',
]


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
        'models':    ORACLE_MODEL_CHOICES,
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
            seed, rule = _album.derive_seed_and_rule(targets.album_hash)
            palette = _album.palette_to_pact_palette(targets.palette_rgb)
            initial_grids = _album.targets_to_initial_grids(targets)

            pact = Pact(
                name=form['name'] or f'album-{targets.album_hash[:8]}',
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

    if request.method == 'POST':
        for k in form:
            form[k] = request.POST.get(k, form_defaults[k])
        try:
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

    return render(request, 'spoeqi/chain.html', {
        'pact':           pact,
        'form':           form,
        'slots':          slots,
        'results':        results,
        'error':          error,
        'char_mappings':  char_mappings,
        'token_mappings': token_mappings,
        'components':     list(range(COMPONENTS)),
    })


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

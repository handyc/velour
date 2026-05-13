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


def _det_class4_candidates(limit: int = 20):
    """Top class-4 candidates from Det with n_colors=4 — these compile
    directly into the 4-state spoeqi rule table without quantising.
    Returns a list of {id, score, n_rules, source} dicts for the form;
    swallowing import errors so spoeqi still works in environments
    where Det isn't migrated."""
    try:
        from det.models import Candidate
        qs = (Candidate.objects
              .filter(est_class='class4', run__n_colors=4)
              .select_related('run')
              .order_by('-score')[:limit])
        return [{
            'id': c.id, 'score': c.score, 'n_rules': c.n_rules,
            'source': f'Det run {c.run_id}',
            'label': f'#{c.id}  score {c.score:.2f}  '
                     f'({c.n_rules} rules, {c.run.wildcard_pct}% wildcard)',
        } for c in qs]
    except Exception:
        return []


def _det_class4_pool_size() -> int:
    """Total class-4 4-color candidates available for fleet sampling."""
    try:
        from det.models import Candidate
        return (Candidate.objects
                .filter(est_class='class4', run__n_colors=4).count())
    except Exception:
        return 0


def _sample_fleet_candidate_ids(rng):
    """Sample exactly COMPONENTS Det Candidate IDs from the class-4
    4-color pool.  Sampling is with-replacement when the pool is
    smaller than 64 — better to duplicate a few rules than fail."""
    from det.models import Candidate
    pool_ids = list(Candidate.objects
                    .filter(est_class='class4', run__n_colors=4)
                    .values_list('id', flat=True))
    if not pool_ids:
        raise ValueError('No 4-colour class-4 Det candidates available.')
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
    det_candidates = _det_class4_candidates()
    fleet_pool = _det_class4_pool_size()
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
                    cand_ids = _sample_fleet_candidate_ids(rng)
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
    }
    cells_per_tile = pact.component_grid * pact.component_grid
    if is_per_component_palette(pact.palette):
        swatch_palette = pact.palette[0]
        palette_is_per_component = True
    else:
        swatch_palette = pact.palette or DEFAULT_PALETTE
        palette_is_per_component = False
    return render(request, 'spoeqi/detail.html', {
        'pact':    pact,
        'payload': json.dumps(payload),
        'now_ms':  int(timezone.now().timestamp() * 1000),
        'cells_per_tile':   cells_per_tile,
        'cells_total':      cells_per_tile * COMPONENTS,
        'fleet_legend':     fleet_legend,
        'swatch_palette':   swatch_palette,
        'palette_is_per_component': palette_is_per_component,
    })


@require_POST
def delete(request, slug):
    pact = get_object_or_404(Pact, slug=slug)
    name = pact.name
    pact.delete()
    messages.info(request, f'Pact "{name}" dissolved.')
    return redirect('spoeqi:index')


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

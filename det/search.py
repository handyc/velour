"""The search loop: generate random hex rulesets, step them forward,
score them for Class-4 signatures, save the survivors.

Class 4 in 1-D (Rule 110) is recognizable by: localized structures
that persist, a background texture that isn't pure noise, long
transients before any cycle closes. Translating those signatures to
a 2-D hex grid:

  - `uniform` must be False at the horizon — otherwise Class 1.
  - The activity rate (fraction of cells changing per tick) should
    hover in a middle band — not stuck at 0 (frozen), not near 0.5
    (boiling). Rule 110's 1-D analog sits around ~0.10-0.20.
  - No short cycle closes within the horizon — short cycles are
    Class 2. Very long periods or true aperiodicity pass.
  - Block entropy of the tail grid should be middling — uniform
    patches and textured patches coexist. Pure random (high ent)
    is Class 3; pure ordered (low ent) is Class 2.
  - Multiple colors should still be present at the tail — a rule
    that collapses to one color lost its vocabulary.

The scorer is a weighted sum of these five signals. It is a
heuristic, not a proof, so the UI surfaces the raw measurements
alongside the score; the operator gets the final say.
"""

import hashlib
import json
import random

from django.utils import timezone

from automaton.detector import step_exact

from . import engine


def _generate_rules(n_rules, n_colors, wildcard_pct, rng):
    """Random 7-tuple rules in automaton.detector.step_exact's format:
    [{'s': self, 'n': [n0..n5], 'r': result}]. Identical to
    automaton.views.create_exact_rules' logic but yielding in-memory
    dicts — Det builds without committing until the user promotes."""
    seen = set()
    rules = []
    attempts = 0
    max_attempts = n_rules * 10
    while len(rules) < n_rules and attempts < max_attempts:
        attempts += 1
        self_c = rng.randrange(n_colors)
        nbs = []
        for _ in range(6):
            if rng.randrange(100) < wildcard_pct:
                nbs.append(-1)
            else:
                nbs.append(rng.randrange(n_colors))
        result = rng.randrange(n_colors)
        # Skip no-op all-wildcard rules that map a color to itself
        if result == self_c and all(n == -1 for n in nbs):
            continue
        key = (self_c, tuple(nbs), result)
        if key in seen:
            continue
        seen.add(key)
        rules.append({'s': self_c, 'n': nbs, 'r': result})
    return rules


def _rules_hash(rules):
    """Short stable hash — used to dedupe within a run."""
    payload = json.dumps(rules, sort_keys=True).encode()
    return hashlib.sha1(payload).hexdigest()[:16]


def _step_and_measure(rules, W, H, n_colors, horizon, grid_seed):
    """Run a ruleset forward up to `horizon` ticks from a seeded
    random grid. Stops early if we detect a short cycle. Returns
    (analysis_dict, final_grid, prev_grid)."""
    grid = engine.seeded_random_grid(W, H, n_colors, grid_seed)
    history = [grid]
    prev = grid
    activity_samples = []
    period = None
    entered_at = None
    for t in range(1, horizon + 1):
        nxt = step_exact(grid, W, H, rules)
        activity_samples.append(engine.activity_rate(grid, nxt))
        history.append(nxt)
        prev = grid
        grid = nxt
        # Look back for a repeat every few steps to limit O(n²) cost
        if t >= 4 and t % 2 == 0:
            p, ea = engine.detect_cycle(history, max_period=16)
            if p is not None:
                period, entered_at = p, ea
                break

    uniform = engine.is_uniform(grid)
    block_ent = engine.block_entropy_grid(grid, k=2)
    dens = engine.density_profile(grid, n_colors)
    color_diversity = sum(1 for d in dens if d > 0.01)
    # Average activity over the last third of the run — settles into
    # the steady-state rate after initial transients
    tail_slice = activity_samples[-max(1, len(activity_samples) // 3):]
    activity_tail = sum(tail_slice) / len(tail_slice) if tail_slice else 0.0

    return {
        'uniform':         uniform,
        'period':          period,
        'entered_at':      entered_at,
        'ended_at_tick':   len(history) - 1,
        'activity_tail':   round(activity_tail, 4),
        'block_entropy':   round(block_ent, 4),
        'density_profile': [round(d, 4) for d in dens],
        'color_diversity': color_diversity,
    }, grid, prev


def _score(analysis, n_colors):
    """Class-4-likeness as a single float. Higher is better.

    The five signals and their weights are tuned so a moderate score
    (~3.5-5.0) flags something worth a human look, and the top
    candidates routinely score 5.5+. Weights are deliberate enough
    that dropping any one (e.g. setting block_entropy weight to 0)
    demonstrably changes the ranking."""
    score = 0.0
    breakdown = {}

    # 1. Not uniform — required for anything interesting
    if not analysis['uniform']:
        score += 1.0
        breakdown['non_uniform'] = 1.0

    # 2. No short cycle OR a long one
    p = analysis['period']
    if p is None:
        score += 1.5
        breakdown['aperiodic'] = 1.5
    elif p > 8:
        score += 0.75
        breakdown['long_period'] = 0.75

    # 3. Activity in the "edge of chaos" band
    a = analysis['activity_tail']
    if 0.03 <= a <= 0.30:
        # Peak at ~0.12, taper on either side
        peak = 0.12
        distance = abs(a - peak) / 0.18
        contrib = 2.0 * max(0.0, 1.0 - distance)
        score += contrib
        breakdown['activity_band'] = round(contrib, 3)

    # 4. Block entropy in the middle
    # k=2 block entropy caps at ~log2(n_colors**4). The "interesting"
    # Class-4 band is ~40-70% of that cap — rich but not saturated.
    be = analysis['block_entropy']
    be_cap = {2: 4.0, 3: 6.3, 4: 8.0}[n_colors]
    low = be_cap * 0.35
    high = be_cap * 0.75
    if low <= be <= high:
        mid = (low + high) / 2
        contrib = 1.5 * (1.0 - abs(be - mid) / ((high - low) / 2))
        score += contrib
        breakdown['entropy_band'] = round(contrib, 3)

    # 5. Color diversity — rule hasn't collapsed to a single color
    if analysis['color_diversity'] >= 2:
        bonus = 0.25 * min(analysis['color_diversity'], n_colors)
        score += bonus
        breakdown['color_diversity'] = round(bonus, 3)

    return round(score, 3), breakdown


def _classify(analysis, score, n_colors):
    """Coarse class label from the measurements. Same thresholds the
    UI surfaces — sort the rankings with the continuous `score`, not
    with this label."""
    if analysis['uniform']:
        return 'class1'
    p = analysis['period']
    if p is not None and p <= 4:
        return 'class2'
    a = analysis['activity_tail']
    be = analysis['block_entropy']
    be_cap = {2: 4.0, 3: 6.3, 4: 8.0}[n_colors]
    # Saturated entropy + high activity → chaotic (Class 3)
    if a > 0.35 and be > be_cap * 0.75:
        return 'class3'
    if score >= 3.5:
        return 'class4'
    if p is not None:
        return 'class2'
    return 'unknown'


def execute(run, progress_cb=None):
    """Run a SearchRun to completion. Blocks until done. Safe to call
    from a management command or synchronously from a view when
    n_candidates is kept modest (default 200 × 40 ticks × 20×20 grid
    runs in a few seconds of pure Python)."""
    from .models import Candidate

    if not run.seed:
        run.seed = timezone.now().strftime('%Y%m%d-%H%M%S')
    run.status = 'running'
    run.started_at = timezone.now()
    run.error = ''
    run.save()

    try:
        rng = random.Random(run.seed)
        seen_hashes = set()
        bulk = []

        for i in range(run.n_candidates):
            rules = _generate_rules(
                n_rules=run.n_rules_per_candidate,
                n_colors=run.n_colors,
                wildcard_pct=run.wildcard_pct,
                rng=rng,
            )
            rh = _rules_hash(rules)
            if rh in seen_hashes:
                continue
            seen_hashes.add(rh)

            grid_seed = f'{run.seed}-cand-{i}'
            analysis, _final, _prev = _step_and_measure(
                rules, run.screen_width, run.screen_height,
                run.n_colors, run.horizon, grid_seed,
            )
            score, breakdown = _score(analysis, run.n_colors)
            analysis['score_breakdown'] = breakdown
            analysis['grid_seed'] = grid_seed
            est = _classify(analysis, score, run.n_colors)

            bulk.append(Candidate(
                run=run,
                rules_json=rules,
                n_rules=len(rules),
                rules_hash=rh,
                score=score,
                est_class=est,
                analysis=analysis,
            ))

            if progress_cb and i % 10 == 0:
                progress_cb(i + 1, run.n_candidates)

        Candidate.objects.bulk_create(bulk, batch_size=200)
        run.status = 'finished'
    except Exception as exc:
        run.status = 'failed'
        run.error = str(exc)
        raise
    finally:
        run.finished_at = timezone.now()
        run.save()


def promote_to_evolution(candidate, population_size=16, generations=80,
                         mutation_rate=0.15, crossover_rate=0.5):
    """Hand `candidate` to the Evolution Engine as the founding parent
    of a new L0 run with gene_type='hexca'. The browser engine will
    breed mutated children of the candidate's ruleset and score each
    against the same screening substrate Det uses.

    Returns (EvolutionRun, seed_Agent). Caller redirects to the run.

    Reusing the candidate's original grid_seed means children are
    scored on the same initial condition the Det screener used, so
    scores are directly comparable. The mutate operator in
    hexca_gene.mjs perturbs rule results / neighbors / self-colors in
    place and occasionally adds or drops a rule.
    """
    from evolution.models import Agent as EvoAgent, EvolutionRun

    run_cfg = candidate.run
    grid_seed = candidate.analysis.get('grid_seed') or f'det-cand-{candidate.pk}'

    gene = {
        'rules': candidate.rules_json,
        'n_colors': run_cfg.n_colors,
        'source': 'det',
        'source_candidate_id': candidate.pk,
    }
    agent_base = f'det-cand-{candidate.pk}'
    agent_name = _unique_name(EvoAgent, agent_base)
    seed_agent = EvoAgent.objects.create(
        name=agent_name,
        level=0,
        gene=gene,
        seed_string='',
        script='',
        score=0.0,
        notes=(f'Seeded from Det Candidate #{candidate.pk} '
               f'(score {candidate.score:.2f}, '
               f'{candidate.get_est_class_display()}).'),
    )

    params = {
        'gene_type': 'hexca',
        'hexca_target': {
            'n_colors': run_cfg.n_colors,
            'screen_width': run_cfg.screen_width,
            'screen_height': run_cfg.screen_height,
            'horizon': run_cfg.horizon,
            'wildcard_pct': run_cfg.wildcard_pct,
            'n_rules_per_candidate': run_cfg.n_rules_per_candidate,
            'grid_seed': grid_seed,
            'det_candidate_id': candidate.pk,
            'det_search_run_id': candidate.run_id,
        },
        'mutation_rate': mutation_rate,
        'crossover_rate': crossover_rate,
        'tournament_k': 3,
    }
    run_base = f'det-cand-{candidate.pk}-evo'
    run_name = _unique_name(EvolutionRun, run_base)
    run = EvolutionRun.objects.create(
        name=run_name,
        level=0,
        goal_string='',
        population_size=population_size,
        generations_target=generations,
        target_score=1.0 - 1e-9,
        seed_agent=seed_agent,
        params=params,
        notes=(f'Bred from Det Candidate #{candidate.pk} '
               f'(Det score {candidate.score:.2f}). '
               f'Export best back with `det/import/`.'),
    )
    return run, seed_agent


def _unique_name(model, base, max_tries=200):
    """Tack on -2, -3, ... until we find a free name. Used for Agent
    and EvolutionRun, both of which have unique name constraints."""
    name = base
    n = 2
    while model.objects.filter(name=name).exists() and n <= max_tries:
        name = f'{base}-{n}'
        n += 1
    return name


def import_agent_as_candidate(agent, run=None):
    """Pull an evolution.Agent with a hex-CA gene back into Det as a
    Candidate row. If `run` is None, a fresh SearchRun of size 1 is
    created to hold it; otherwise we append to that run (useful for
    clustering several imports alongside a source Det sweep).

    Raises ValueError if the agent's gene doesn't look like a hex-CA
    gene (no 'rules' key), if any rule is malformed, or if the gene
    omits n_colors and we can't infer it safely.
    """
    from .models import Candidate, SearchRun

    gene = agent.gene or {}
    rules = gene.get('rules')
    if not isinstance(rules, list) or not rules:
        raise ValueError(
            f'Agent "{agent.name}" has no hex-CA rules in its gene.'
        )
    # Validate shape — each rule is {s, n: [6], r}, ints in range
    cleaned = []
    for er in rules:
        if not isinstance(er, dict):
            raise ValueError(f'Malformed rule (not a dict): {er!r}')
        if 's' not in er or 'n' not in er or 'r' not in er:
            raise ValueError(f'Rule missing s/n/r keys: {er!r}')
        if not isinstance(er['n'], list) or len(er['n']) != 6:
            raise ValueError(f'Rule needs 6 neighbors: {er!r}')
        cleaned.append({
            's': int(er['s']),
            'n': [int(x) for x in er['n']],
            'r': int(er['r']),
        })

    n_colors = gene.get('n_colors')
    if n_colors is None:
        # Infer from largest color index in the gene, clamp to [2, 4].
        max_col = 1
        for er in cleaned:
            max_col = max(max_col, er['s'], er['r'])
            for x in er['n']:
                max_col = max(max_col, x)
        n_colors = max(2, min(4, max_col + 1))
    n_colors = int(n_colors)
    if n_colors < 2 or n_colors > 4:
        raise ValueError(f'n_colors must be 2..4, got {n_colors}')

    # Figure out the screening substrate. Prefer the run this agent
    # emerged from; fall back to any run it seeded (round-trip case
    # where we imported the founder itself); fall back to Det defaults.
    target = {}
    source = agent.source_run or agent.runs_seeded.first()
    if source:
        target = (source.params or {}).get('hexca_target', {}) or {}
    W = int(target.get('screen_width') or 20)
    H = int(target.get('screen_height') or 20)
    horizon = int(target.get('horizon') or 40)
    grid_seed = target.get('grid_seed') or f'import-agent-{agent.pk}'

    if run is None:
        run = SearchRun.objects.create(
            label=f'import from evolution #{agent.pk}',
            n_colors=n_colors,
            n_candidates=1,
            n_rules_per_candidate=len(cleaned),
            wildcard_pct=int(target.get('wildcard_pct') or 25),
            screen_width=W,
            screen_height=H,
            horizon=horizon,
            seed=grid_seed,
            status='finished',
        )
        run.started_at = timezone.now()
        run.finished_at = timezone.now()
        run.save()

    analysis, _final, _prev = _step_and_measure(
        cleaned, W, H, n_colors, horizon, grid_seed,
    )
    score, breakdown = _score(analysis, n_colors)
    analysis['score_breakdown'] = breakdown
    analysis['grid_seed'] = grid_seed
    analysis['imported_from_agent_id'] = agent.pk
    analysis['imported_from_agent_slug'] = agent.slug
    est = _classify(analysis, score, n_colors)

    cand = Candidate.objects.create(
        run=run,
        rules_json=cleaned,
        n_rules=len(cleaned),
        rules_hash=_rules_hash(cleaned),
        score=score,
        est_class=est,
        analysis=analysis,
    )
    return cand, run


def promote(candidate, name=None):
    """Copy a Candidate into automaton.RuleSet + automaton.ExactRule so
    the operator can run it interactively from the Automaton app.
    Returns the created RuleSet.

    Also creates a matching `automaton.Simulation` using the same
    grid seed that was used to screen the candidate — that way the
    hex-CA run page will show the same trajectory Det scored."""
    from automaton.models import ExactRule, RuleSet, Simulation

    if candidate.promoted_to:
        return candidate.promoted_to

    if not name:
        name = f'Det #{candidate.pk} ({candidate.est_class}, '\
               f'{candidate.score:.2f})'

    rs = RuleSet.objects.create(
        name=name,
        n_colors=candidate.run.n_colors,
        source='seed',
        description=(
            f'Promoted from Det SearchRun #{candidate.run_id}. '
            f'Screening score {candidate.score:.2f}, estimated '
            f'{candidate.get_est_class_display()}.'
        ),
        source_metadata={
            'det_candidate_id': candidate.pk,
            'det_search_run_id': candidate.run_id,
            'analysis': candidate.analysis,
        },
    )
    exact_rules = [
        ExactRule(
            ruleset=rs, priority=i,
            self_color=r['s'],
            n0_color=r['n'][0], n1_color=r['n'][1], n2_color=r['n'][2],
            n3_color=r['n'][3], n4_color=r['n'][4], n5_color=r['n'][5],
            result_color=r['r'],
        )
        for i, r in enumerate(candidate.rules_json)
    ]
    ExactRule.objects.bulk_create(exact_rules)

    # Seeded initial grid — same seed Det used to screen.
    grid_seed = candidate.analysis.get('grid_seed',
                                       f'promote-{candidate.pk}')
    W, H = candidate.run.screen_width, candidate.run.screen_height
    grid = engine.seeded_random_grid(W, H, candidate.run.n_colors, grid_seed)
    palette = ['#0d1117', '#58a6ff', '#f85149', '#2ea043']
    Simulation.objects.create(
        name=name, ruleset=rs, width=W, height=H,
        palette=palette, grid_state=grid, tick_count=0,
        notes=f'Det-promoted. Grid seed: {grid_seed}',
    )

    candidate.promoted_to = rs
    candidate.save(update_fields=['promoted_to'])
    return rs

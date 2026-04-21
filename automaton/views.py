import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import DEFAULT_PALETTE, ExactRule, Rule, RuleSet, Simulation


@login_required
def home(request):
    q = (request.GET.get('q') or '').strip()
    sims = Simulation.objects.select_related('ruleset')
    rulesets = RuleSet.objects.all()
    if q:
        sims = sims.filter(name__icontains=q)
        rulesets = rulesets.filter(name__icontains=q)
    total_sims = Simulation.objects.count()
    simulations = list(sims[:200])
    return render(request, 'automaton/home.html', {
        'simulations':  simulations,
        'rulesets':     rulesets,
        'query':        q,
        'shown_sims':   len(simulations),
        'total_sims':   total_sims,
    })


@login_required
@require_POST
def create_simulation(request):
    """Create a new simulation from a ruleset + optional tileset."""
    ruleset_id = request.POST.get('ruleset', '')
    width = int(request.POST.get('width', 32))
    height = int(request.POST.get('height', 32))
    name = request.POST.get('name', '').strip()

    ruleset = get_object_or_404(RuleSet, pk=ruleset_id)

    # Prefer the ruleset's canonical palette if set; otherwise the built-in
    # default, optionally overlaid by a picked tileset.
    palette = list(ruleset.palette) if ruleset.palette else list(DEFAULT_PALETTE)

    tileset = None
    tileset_id = request.POST.get('tileset', '')
    if tileset_id:
        from tiles.models import TileSet
        tileset = TileSet.objects.filter(pk=tileset_id).first()
        if tileset and tileset.palette and not ruleset.palette:
            # Tileset only gets to seed when the ruleset hasn't claimed a palette.
            palette = (tileset.palette + palette)[:4]

    # Random initial grid
    nc = ruleset.n_colors
    grid = [[random.randint(0, nc - 1) for _ in range(width)]
            for _ in range(height)]

    if not name:
        name = f'{ruleset.name} ({width}×{height})'

    sim = Simulation.objects.create(
        name=name, ruleset=ruleset, tileset=tileset,
        width=width, height=height, palette=palette,
        grid_state=grid, tick_count=0,
    )
    messages.success(request, f'Created simulation "{sim.name}".')
    return redirect('automaton:run', slug=sim.slug)


@login_required
def run_simulation(request, slug):
    """The main simulation view — renders the canvas animator."""
    sim = get_object_or_404(Simulation, slug=slug)

    # Check for exact rules first, fall back to count-based rules
    exact_rules = list(sim.ruleset.exact_rules.order_by('priority'))
    if exact_rules:
        exact_json = json.dumps([{
            's': r.self_color, 'n': [r.n0_color, r.n1_color, r.n2_color,
                                     r.n3_color, r.n4_color, r.n5_color],
            'r': r.result_color,
        } for r in exact_rules])
        rules_json = '[]'
        rule_mode = 'exact'
    else:
        exact_json = '[]'
        rules = list(sim.ruleset.rules.order_by('priority'))
        rules_json = json.dumps([{
            'self_color': r.self_color,
            'neighbor_color': r.neighbor_color,
            'min_count': r.min_count,
            'max_count': r.max_count,
            'result_color': r.result_color,
        } for r in rules])
        rule_mode = 'count'

    return render(request, 'automaton/run.html', {
        'sim': sim,
        'grid_json': json.dumps(sim.grid_state),
        'palette_json': json.dumps(sim.palette),
        'rules_json': rules_json,
        'exact_json': exact_json,
        'rule_mode': rule_mode,
        'n_exact_rules': len(exact_rules),
    })


@login_required
def simulation_data_json(request, slug):
    """Return current grid state as JSON for API consumers."""
    sim = get_object_or_404(Simulation, slug=slug)
    return JsonResponse({
        'grid': sim.grid_state,
        'tick': sim.tick_count,
        'palette': sim.palette,
        'width': sim.width,
        'height': sim.height,
    })


@login_required
def export_simulation_json(request, slug):
    """Export a simulation and its ruleset as downloadable JSON."""
    sim = get_object_or_404(Simulation, slug=slug)
    rs = sim.ruleset

    exact_rules = list(rs.exact_rules.order_by('priority'))
    count_rules = list(rs.rules.order_by('priority'))

    data = {
        'simulation': {
            'name': sim.name,
            'width': sim.width,
            'height': sim.height,
            'palette': sim.palette,
            'grid_state': sim.grid_state,
            'tick_count': sim.tick_count,
            'notes': sim.notes,
        },
        'ruleset': {
            'name': rs.name,
            'n_colors': rs.n_colors,
            'source': rs.source,
            'description': rs.description,
            'exact_rules': [{
                'priority': r.priority,
                'self_color': r.self_color,
                'n0_color': r.n0_color, 'n1_color': r.n1_color,
                'n2_color': r.n2_color, 'n3_color': r.n3_color,
                'n4_color': r.n4_color, 'n5_color': r.n5_color,
                'result_color': r.result_color,
            } for r in exact_rules],
            'count_rules': [{
                'priority': r.priority,
                'self_color': r.self_color,
                'neighbor_color': r.neighbor_color,
                'min_count': r.min_count,
                'max_count': r.max_count,
                'result_color': r.result_color,
                'notes': r.notes,
            } for r in count_rules],
        },
    }

    response = JsonResponse(data, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="{sim.slug}.json"'
    return response


@login_required
@require_POST
def rename_simulation(request, slug):
    """Rename a simulation."""
    sim = get_object_or_404(Simulation, slug=slug)
    new_name = request.POST.get('name', '').strip()
    if not new_name:
        messages.error(request, 'Name cannot be empty.')
        return redirect('automaton:run', slug=sim.slug)
    sim.name = new_name
    # Regenerate slug from new name
    base = slugify(new_name)[:200] or 'sim'
    candidate = base
    n = 2
    while Simulation.objects.filter(slug=candidate).exclude(pk=sim.pk).exists():
        candidate = f'{base}-{n}'
        n += 1
    sim.slug = candidate
    sim.save()
    messages.success(request, f'Renamed to "{sim.name}".')
    return redirect('automaton:run', slug=sim.slug)


_HEX_COLOR_LEN = 7    # "#rrggbb"


@login_required
@require_POST
def update_palette(request, slug):
    """Persist a new cell-colour palette for this simulation.

    Expects a single `palette` POST field carrying a JSON-encoded list of
    "#rrggbb" strings. The list length must match the simulation's
    existing palette length — changing n_colors is a ruleset-level
    concern that this endpoint deliberately doesn't touch.
    """
    sim = get_object_or_404(Simulation, slug=slug)
    raw = (request.POST.get('palette') or '').strip()
    if not raw:
        messages.error(request, 'Palette payload missing.')
        return redirect('automaton:run', slug=sim.slug)
    try:
        palette = json.loads(raw)
    except json.JSONDecodeError:
        messages.error(request, 'Invalid palette JSON.')
        return redirect('automaton:run', slug=sim.slug)
    if not (isinstance(palette, list) and palette and all(
        isinstance(c, str) and len(c) == _HEX_COLOR_LEN and c.startswith('#')
        for c in palette
    )):
        messages.error(request, 'Palette must be a list of #rrggbb strings.')
        return redirect('automaton:run', slug=sim.slug)
    if sim.palette and len(palette) != len(sim.palette):
        messages.error(request,
            f'Palette length mismatch (expected {len(sim.palette)}, '
            f'got {len(palette)}).')
        return redirect('automaton:run', slug=sim.slug)
    sim.palette = palette
    sim.save(update_fields=['palette'])
    # Sync to the ruleset so future simulations + merges inherit these colours.
    # This is why palette edits feel "stickier" than grid state.
    sim.ruleset.palette = palette
    sim.ruleset.save(update_fields=['palette'])
    messages.success(request, 'Palette saved (ruleset updated too).')
    return redirect('automaton:run', slug=sim.slug)


@login_required
@require_POST
def create_life_rules(request):
    """Create a Game-of-Life-like ruleset for 4-color hex grids."""
    rs = RuleSet.objects.create(
        name=f'Hex Life {random.randint(100,999)}',
        n_colors=4,
        source='operator',
        description='Conway-style rules adapted for 4-color hex grid.',
    )

    # Classic GoL-like rules adapted for hex (6 neighbors):
    # Color 0 = dead. Colors 1-3 = alive variants.
    rules = [
        # Dead cell with exactly 2 neighbors of color 1 → born as color 1
        Rule(ruleset=rs, priority=1, self_color=0, neighbor_color=1,
             min_count=2, max_count=2, result_color=1,
             notes='Birth: dead + 2×c1 → c1'),
        # Dead cell with exactly 2 neighbors of color 2 → born as color 2
        Rule(ruleset=rs, priority=2, self_color=0, neighbor_color=2,
             min_count=2, max_count=2, result_color=2,
             notes='Birth: dead + 2×c2 → c2'),
        # Dead cell with exactly 2 neighbors of color 3 → born as color 3
        Rule(ruleset=rs, priority=3, self_color=0, neighbor_color=3,
             min_count=2, max_count=2, result_color=3,
             notes='Birth: dead + 2×c3 → c3'),
        # Alive cells with 2-3 same-color neighbors survive
        Rule(ruleset=rs, priority=10, self_color=1, neighbor_color=1,
             min_count=2, max_count=3, result_color=1,
             notes='Survive: c1 + 2-3×c1'),
        Rule(ruleset=rs, priority=11, self_color=2, neighbor_color=2,
             min_count=2, max_count=3, result_color=2,
             notes='Survive: c2 + 2-3×c2'),
        Rule(ruleset=rs, priority=12, self_color=3, neighbor_color=3,
             min_count=2, max_count=3, result_color=3,
             notes='Survive: c3 + 2-3×c3'),
        # Color competition: alive cell with 3+ neighbors of different color → convert
        Rule(ruleset=rs, priority=20, self_color=1, neighbor_color=2,
             min_count=3, max_count=6, result_color=2,
             notes='Convert: c1 overwhelmed by c2'),
        Rule(ruleset=rs, priority=21, self_color=2, neighbor_color=3,
             min_count=3, max_count=6, result_color=3,
             notes='Convert: c2 overwhelmed by c3'),
        Rule(ruleset=rs, priority=22, self_color=3, neighbor_color=1,
             min_count=3, max_count=6, result_color=1,
             notes='Convert: c3 overwhelmed by c1'),
        # Overcrowding: alive with 5-6 same-color neighbors → die
        Rule(ruleset=rs, priority=30, self_color=-1, neighbor_color=0,
             min_count=0, max_count=1, result_color=0,
             notes='Isolation: < 2 alive neighbors → die'),
    ]
    Rule.objects.bulk_create(rules)

    messages.success(request, f'Created ruleset "{rs.name}" with {len(rules)} rules.')
    return redirect('automaton:home')


@login_required
@require_POST
def create_exact_rules(request):
    """Create a 7-tuple exact-match ruleset with random rules.

    The user can specify:
    - n_rules: how many 7-tuple rules (default 100, range 20-500)
    - n_colors: 2-4 (default 4)
    - wildcard_pct: what fraction of neighbor positions are wildcards (0-80%)

    With 4 colors and 7 positions, the full space is 4^7 = 16384.
    We randomly sample n_rules unique patterns from this space.
    """
    n_rules = max(20, min(500, int(request.POST.get('n_rules', 100))))
    n_colors = max(2, min(4, int(request.POST.get('n_colors', 4))))
    wildcard_pct = max(0, min(80, int(request.POST.get('wildcard_pct', 15))))
    name = request.POST.get('name', '').strip()

    if not name:
        name = f'Exact-{n_colors}c-{n_rules}r-{random.randint(100, 999)}'

    rs = RuleSet.objects.create(
        name=name,
        n_colors=n_colors,
        source='operator',
        description=(f'{n_rules} exact 7-tuple rules for {n_colors}-color hex grid. '
                     f'{wildcard_pct}% wildcard positions.'),
    )

    # Generate unique random rules
    seen = set()
    rules = []
    attempts = 0
    max_attempts = n_rules * 10

    while len(rules) < n_rules and attempts < max_attempts:
        attempts += 1
        # Generate a random pattern
        self_c = random.randint(0, n_colors - 1)
        neighbors = []
        for _ in range(6):
            if random.randint(0, 99) < wildcard_pct:
                neighbors.append(-1)  # wildcard
            else:
                neighbors.append(random.randint(0, n_colors - 1))
        result = random.randint(0, n_colors - 1)

        # Don't create a rule that maps a cell to itself with all wildcards
        if result == self_c and all(n == -1 for n in neighbors):
            continue

        # Dedup
        key = (self_c, *neighbors, result)
        if key in seen:
            continue
        seen.add(key)

        rules.append(ExactRule(
            ruleset=rs,
            priority=len(rules),
            self_color=self_c,
            n0_color=neighbors[0],
            n1_color=neighbors[1],
            n2_color=neighbors[2],
            n3_color=neighbors[3],
            n4_color=neighbors[4],
            n5_color=neighbors[5],
            result_color=result,
        ))

    ExactRule.objects.bulk_create(rules)

    messages.success(request,
        f'Created ruleset "{rs.name}" with {len(rules)} exact 7-tuple rules.')
    return redirect('automaton:home')


def _merge_two(rs_a, rs_b, name=None):
    """Build a new RuleSet containing every unique rule from both parents.

    Exact rules dedup by 8-tuple (self + 6 neighbors + result); count rules
    dedup by 5-tuple (self, neighbor_color, min, max, result). Parent A's
    rules come first, then any B rule whose key is not already seen. Priority
    is renumbered 0..N-1 to preserve first-match order across the union.
    """
    exact_a = list(rs_a.exact_rules.order_by('priority'))
    exact_b = list(rs_b.exact_rules.order_by('priority'))
    count_a = list(rs_a.rules.order_by('priority'))
    count_b = list(rs_b.rules.order_by('priority'))

    if not name:
        name = f'{rs_a.name} ⊕ {rs_b.name}'

    # Palette dominance: parent A wins, falling back to B, then the built-in
    # default. Matches the first-match rule precedence already in place.
    inherited_palette = list(rs_a.palette or rs_b.palette or DEFAULT_PALETTE)

    rs = RuleSet.objects.create(
        name=name,
        n_colors=max(rs_a.n_colors, rs_b.n_colors),
        source='operator',
        description=(f'Merged union of "{rs_a.name}" and "{rs_b.name}". '
                     f'Duplicate rules folded; first-match priority preserved '
                     f'with parent A taking precedence.'),
        source_metadata={
            'merged_from': [rs_a.slug, rs_b.slug],
            'parent_pks': [rs_a.pk, rs_b.pk],
        },
        palette=inherited_palette,
    )

    merged_exact = []
    seen_e = set()
    for r in exact_a + exact_b:
        key = (r.self_color, r.n0_color, r.n1_color, r.n2_color,
               r.n3_color, r.n4_color, r.n5_color, r.result_color)
        if key in seen_e:
            continue
        seen_e.add(key)
        merged_exact.append(ExactRule(
            ruleset=rs, priority=len(merged_exact),
            self_color=r.self_color,
            n0_color=r.n0_color, n1_color=r.n1_color, n2_color=r.n2_color,
            n3_color=r.n3_color, n4_color=r.n4_color, n5_color=r.n5_color,
            result_color=r.result_color,
        ))
    ExactRule.objects.bulk_create(merged_exact)

    merged_count = []
    seen_c = set()
    for r in count_a + count_b:
        key = (r.self_color, r.neighbor_color,
               r.min_count, r.max_count, r.result_color)
        if key in seen_c:
            continue
        seen_c.add(key)
        merged_count.append(Rule(
            ruleset=rs, priority=len(merged_count),
            self_color=r.self_color, neighbor_color=r.neighbor_color,
            min_count=r.min_count, max_count=r.max_count,
            result_color=r.result_color, notes=r.notes,
        ))
    Rule.objects.bulk_create(merged_count)

    return rs, len(merged_exact), len(merged_count)


@login_required
@require_POST
def merge_rulesets(request):
    """Combine two explicit rulesets into a new one keeping unique rules."""
    a_id = request.POST.get('ruleset_a', '')
    b_id = request.POST.get('ruleset_b', '')
    if not a_id or not b_id or a_id == b_id:
        messages.error(request, 'Pick two different rulesets to merge.')
        return redirect('automaton:home')
    rs_a = get_object_or_404(RuleSet, pk=a_id)
    rs_b = get_object_or_404(RuleSet, pk=b_id)
    name = request.POST.get('name', '').strip() or None
    rs, n_exact, n_count = _merge_two(rs_a, rs_b, name=name)
    messages.success(request,
        f'Merged "{rs_a.name}" ⊕ "{rs_b.name}" → "{rs.name}" '
        f'({n_exact} exact + {n_count} count rules).')
    return redirect('automaton:home')


@login_required
@require_POST
def merge_random_rulesets(request):
    """Pick two random rulesets and merge them."""
    pks = list(RuleSet.objects.values_list('pk', flat=True))
    if len(pks) < 2:
        messages.error(request, 'Need at least two rulesets to merge.')
        return redirect('automaton:home')
    a_pk, b_pk = random.sample(pks, 2)
    rs_a = RuleSet.objects.get(pk=a_pk)
    rs_b = RuleSet.objects.get(pk=b_pk)
    rs, n_exact, n_count = _merge_two(rs_a, rs_b)
    messages.success(request,
        f'Random merge: "{rs_a.name}" ⊕ "{rs_b.name}" → "{rs.name}" '
        f'({n_exact} exact + {n_count} count rules).')
    return redirect('automaton:home')

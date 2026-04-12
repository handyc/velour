import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Rule, RuleSet, Simulation


@login_required
def home(request):
    simulations = Simulation.objects.select_related('ruleset').all()[:20]
    rulesets = RuleSet.objects.all()
    return render(request, 'automaton/home.html', {
        'simulations': simulations,
        'rulesets': rulesets,
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

    # Default palette: 4 colors
    palette = ['#0d1117', '#58a6ff', '#f85149', '#2ea043']

    # Try to get palette from a tileset
    tileset = None
    tileset_id = request.POST.get('tileset', '')
    if tileset_id:
        from tiles.models import TileSet
        tileset = TileSet.objects.filter(pk=tileset_id).first()
        if tileset and tileset.palette:
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
    rules = list(sim.ruleset.rules.order_by('priority'))

    rules_json = json.dumps([{
        'self_color': r.self_color,
        'neighbor_color': r.neighbor_color,
        'min_count': r.min_count,
        'max_count': r.max_count,
        'result_color': r.result_color,
    } for r in rules])

    return render(request, 'automaton/run.html', {
        'sim': sim,
        'grid_json': json.dumps(sim.grid_state),
        'palette_json': json.dumps(sim.palette),
        'rules_json': rules_json,
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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import (
    IntrospectiveLayer, LoopTraversal, StrangeLoop, ThoughtExperiment,
)


@login_required
def home(request):
    loops = StrangeLoop.objects.filter(is_active=True)
    experiments = ThoughtExperiment.objects.all()[:10]
    layers = IntrospectiveLayer.objects.filter(is_active=True)
    return render(request, 'hofstadter/home.html', {
        'loops': loops,
        'experiments': experiments,
        'layers_by_layer': {
            'brain':         layers.filter(layer='brain'),
            'mind':          layers.filter(layer='mind'),
            'consciousness': layers.filter(layer='consciousness'),
            'self':          layers.filter(layer='self'),
        },
    })


@login_required
def loop_detail(request, slug):
    loop = get_object_or_404(StrangeLoop, slug=slug)
    traversals = loop.traversals.all()[:10]
    return render(request, 'hofstadter/loop_detail.html', {
        'loop':       loop,
        'traversals': traversals,
    })


@login_required
@require_POST
def loop_traverse(request, slug):
    from .recursion import traverse_loop
    loop = get_object_or_404(StrangeLoop, slug=slug)
    try:
        max_depth = int(request.POST.get('max_depth', 7))
    except ValueError:
        max_depth = 7
    exit_content = request.POST.get('exit_content', '').strip() or None
    traversal = traverse_loop(loop, max_depth=max_depth,
                              exit_content=exit_content)
    messages.success(
        request,
        f'Traversal complete: {traversal.steps_taken} steps, '
        f'exited via {traversal.exit_reason}.',
    )
    return redirect('hofstadter:loop_detail', slug=slug)


@login_required
def experiment_list(request):
    experiments = ThoughtExperiment.objects.all()
    return render(request, 'hofstadter/experiment_list.html', {
        'experiments': experiments,
    })


@login_required
def experiment_detail(request, slug):
    experiment = get_object_or_404(ThoughtExperiment, slug=slug)
    return render(request, 'hofstadter/experiment_detail.html', {
        'experiment': experiment,
    })


@login_required
@require_POST
def experiment_run(request, slug):
    from .recursion import run_thought_experiment
    experiment = get_object_or_404(ThoughtExperiment, slug=slug)
    run_thought_experiment(experiment)
    messages.success(
        request,
        f'Ran "{experiment.name}" — {len(experiment.trace)} steps, '
        f'exit {experiment.exit_reason}.',
    )
    return redirect('hofstadter:experiment_detail', slug=slug)

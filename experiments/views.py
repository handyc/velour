from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Experiment


def _apply_post(exp, post):
    exp.name = post.get('name', '').strip()
    exp.slug = post.get('slug', '').strip()
    exp.description = post.get('description', '').strip()
    exp.status = post.get('status', 'active')
    exp.is_intermittent = bool(post.get('is_intermittent'))
    exp.notes = post.get('notes', '').strip()


@login_required
def experiment_list(request):
    experiments = Experiment.objects.all()
    return render(request, 'experiments/list.html', {'experiments': experiments})


@login_required
def experiment_add(request):
    exp = Experiment()
    if request.method == 'POST':
        _apply_post(exp, request.POST)
        if not exp.name:
            messages.error(request, 'Name is required.')
        else:
            try:
                exp.save()
                messages.success(request, f'Added experiment "{exp.name}".')
                return redirect('experiments:detail', slug=exp.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'experiments/form.html', {
        'experiment': exp,
        'action': 'Add',
        'status_choices': Experiment.STATUS_CHOICES,
    })


@login_required
def experiment_edit(request, slug):
    exp = get_object_or_404(Experiment, slug=slug)
    if request.method == 'POST':
        _apply_post(exp, request.POST)
        if not exp.name:
            messages.error(request, 'Name is required.')
        else:
            exp.save()
            messages.success(request, f'Updated "{exp.name}".')
            return redirect('experiments:detail', slug=exp.slug)
    return render(request, 'experiments/form.html', {
        'experiment': exp,
        'action': 'Edit',
        'status_choices': Experiment.STATUS_CHOICES,
    })


@login_required
@require_POST
def experiment_delete(request, slug):
    exp = get_object_or_404(Experiment, slug=slug)
    name = exp.name
    exp.delete()
    messages.success(request, f'Removed "{name}".')
    return redirect('experiments:list')


@login_required
def experiment_detail(request, slug):
    exp = get_object_or_404(Experiment, slug=slug)
    return render(request, 'experiments/detail.html', {
        'experiment': exp,
        'nodes': exp.nodes.select_related('hardware_profile').all(),
    })

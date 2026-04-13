"""Oracle views — web UI for managing lobes, viewing predictions,
and giving feedback on labels."""

import os

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .inference import FEATURE_NAMES, _models_dir, load_lobe, predict_distribution
from .models import OracleLabel


@login_required
def home(request):
    """Oracle dashboard: lobes + recent predictions + stats."""
    # Discover lobes from disk
    models_dir = _models_dir()
    lobes = []
    for fname in sorted(os.listdir(models_dir)):
        if fname.endswith('.tree.json'):
            name = fname.replace('.tree.json', '')
            lobe = load_lobe(name)
            if lobe:
                lobes.append({
                    'name': name,
                    'trained_at': lobe.get('trained_at', ''),
                    'features': lobe.get('features', []),
                    'classes': lobe.get('classes', []),
                    'n_features': len(lobe.get('features', [])),
                    'n_classes': len(lobe.get('classes', [])),
                })

    # Recent labels
    recent = list(OracleLabel.objects.order_by('-happened_at')[:50])

    # Stats per lobe
    lobe_stats = {}
    for lobe_info in lobes:
        name = lobe_info['name']
        total = OracleLabel.objects.filter(lobe_name=name).count()
        labeled = OracleLabel.objects.filter(
            lobe_name=name).exclude(verdict='').count()
        good = OracleLabel.objects.filter(
            lobe_name=name, verdict='good').count()
        bad = OracleLabel.objects.filter(
            lobe_name=name, verdict='bad').count()
        accuracy = (good / labeled * 100) if labeled > 0 else None
        lobe_stats[name] = {
            'total': total,
            'labeled': labeled,
            'good': good,
            'bad': bad,
            'accuracy': accuracy,
        }

    return render(request, 'oracle/home.html', {
        'lobes': lobes,
        'recent': recent,
        'lobe_stats': lobe_stats,
    })


@login_required
def lobe_detail(request, name):
    """Detail view for a single lobe: tree structure + predictions."""
    lobe = load_lobe(name)
    if not lobe:
        return render(request, 'oracle/lobe_not_found.html', {'name': name})

    labels = list(
        OracleLabel.objects.filter(lobe_name=name).order_by('-happened_at')[:100]
    )

    # Class distribution of predictions
    class_counts = {}
    for label in labels:
        class_counts[label.predicted] = class_counts.get(label.predicted, 0) + 1

    # Verdict distribution
    verdict_counts = {'good': 0, 'bad': 0, 'meh': 0, 'unlabeled': 0}
    for label in labels:
        v = label.verdict or 'unlabeled'
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    # Tree depth (approximate)
    def tree_depth(node):
        if 'feature' not in node:
            return 0
        return 1 + max(tree_depth(node['left']), tree_depth(node['right']))

    depth = tree_depth(lobe.get('root', {}))

    # Count leaves
    def count_leaves(node):
        if 'feature' not in node:
            return 1
        return count_leaves(node['left']) + count_leaves(node['right'])

    n_leaves = count_leaves(lobe.get('root', {}))

    return render(request, 'oracle/lobe_detail.html', {
        'lobe': lobe,
        'name': name,
        'labels': labels,
        'class_counts': class_counts,
        'verdict_counts': verdict_counts,
        'depth': depth,
        'n_leaves': n_leaves,
        'feature_names': lobe.get('features', FEATURE_NAMES),
    })


@login_required
@require_POST
def label_verdict(request, pk):
    """Set the verdict on a label via POST."""
    label = get_object_or_404(OracleLabel, pk=pk)
    verdict = request.POST.get('verdict', '')
    actual = request.POST.get('actual', '')
    if verdict in ('good', 'bad', 'meh'):
        label.verdict = verdict
        label.actual_source = 'operator'
    if actual:
        label.actual = actual
        label.actual_source = 'operator'
    label.save()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'verdict': label.verdict})
    return redirect('oracle:home')


@login_required
def labels(request):
    """Paginated label list with filtering."""
    lobe_name = request.GET.get('lobe', '')
    verdict_filter = request.GET.get('verdict', '')
    qs = OracleLabel.objects.order_by('-happened_at')
    if lobe_name:
        qs = qs.filter(lobe_name=lobe_name)
    if verdict_filter:
        if verdict_filter == 'unlabeled':
            qs = qs.filter(verdict='')
        else:
            qs = qs.filter(verdict=verdict_filter)
    label_list = list(qs[:200])
    lobe_names = list(
        OracleLabel.objects.values_list('lobe_name', flat=True).distinct()
    )
    return render(request, 'oracle/labels.html', {
        'labels': label_list,
        'lobe_names': lobe_names,
        'current_lobe': lobe_name,
        'current_verdict': verdict_filter,
    })

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Build, Feature, PortStatus, Variant


@login_required
def index(request):
    """Render the feature × variant parity matrix."""
    variants = list(Variant.objects.all())
    features = list(Feature.objects.all())
    statuses = {(s.feature_id, s.variant_id): s
                for s in PortStatus.objects.all()}
    # Latest build label per variant (for the column header).
    latest_builds = {}
    for v in variants:
        b = Build.objects.filter(variant=v).order_by('-created_at').first()
        if b:
            latest_builds[v.id] = b.label
    rows = []
    for f in features:
        cells = []
        for v in variants:
            s = statuses.get((f.id, v.id))
            cells.append({
                'variant': v,
                'state':   s.state if s else 'todo',
                'notes':   s.notes if s else '',
            })
        rows.append({'feature': f, 'cells': cells})
    return render(request, 'bidir/index.html', {
        'variants':      variants,
        'rows':          rows,
        'latest_builds': latest_builds,
    })


@login_required
def feature_detail(request, slug):
    feature = get_object_or_404(Feature, slug=slug)
    variants = list(Variant.objects.all())
    statuses = {s.variant_id: s
                for s in PortStatus.objects.filter(feature=feature)}
    cells = [{
        'variant': v,
        'state':   statuses.get(v.id).state if v.id in statuses else 'todo',
        'notes':   statuses.get(v.id).notes if v.id in statuses else '',
    } for v in variants]
    return render(request, 'bidir/feature_detail.html', {
        'feature':  feature,
        'cells':    cells,
        'variants': variants,
    })


@login_required
@require_POST
def set_status(request, slug):
    feature = get_object_or_404(Feature, slug=slug)
    variant = get_object_or_404(Variant, slug=request.POST.get('variant'))
    state = request.POST.get('state', 'todo')
    if state not in dict(PortStatus.STATE_CHOICES):
        messages.error(request, f'unknown state: {state}')
        return redirect('bidir:feature_detail', slug=feature.slug)
    PortStatus.objects.update_or_create(
        feature=feature, variant=variant,
        defaults={'state': state, 'notes': request.POST.get('notes', '')},
    )
    messages.success(request, f'{feature.slug}/{variant.slug} → {state}')
    return redirect('bidir:feature_detail', slug=feature.slug)


@login_required
def builds(request):
    return render(request, 'bidir/builds.html', {
        'builds': Build.objects.select_related('variant').all(),
    })


@login_required
@require_POST
def quickset_status(request):
    """Phase 2: inline status update from the matrix page.  Body has
    feature= variant= state= — same triple as set_status, but the
    redirect lands back on the matrix index, preserving any anchor
    so the user keeps their scroll position."""
    feature = get_object_or_404(Feature, slug=request.POST.get('feature', ''))
    variant = get_object_or_404(Variant, slug=request.POST.get('variant', ''))
    state = request.POST.get('state', 'todo')
    if state not in dict(PortStatus.STATE_CHOICES):
        messages.error(request, f'unknown state: {state}')
        return redirect('bidir:index')
    PortStatus.objects.update_or_create(
        feature=feature, variant=variant,
        defaults={'state': state},
    )
    return redirect(
        reverse('bidir:index') + f'#row-{feature.slug}')

import math

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import AppProfile, ComputeTask, EnergyComparable


def _annotate(task, comparables):
    """Attach the nearest comparable + useful display fields to a task."""
    if not comparables or task.energy_joules <= 0:
        task.match = None
        task.match_ratio = None
        return task
    target = math.log10(task.energy_joules)
    best = min(
        comparables,
        key=lambda c: abs(math.log10(c.energy_joules) - target),
    )
    task.match = best
    # How many "units" of the signpost does this task cost?
    task.match_ratio = task.energy_joules / best.energy_joules
    return task


@login_required
def index(request):
    comparables = list(EnergyComparable.objects.all())
    tasks = list(ComputeTask.objects.all())
    for t in tasks:
        _annotate(t, comparables)
        # Pre-compute position on log strip for the template.
        t.strip_pct = t.log_position() * 100.0

    # Category grouping while preserving the global energy ordering
    # inside each group.
    by_cat = {}
    for t in tasks:
        by_cat.setdefault(t.get_category_display(), []).append(t)

    # Log axis ticks for the strip visualisation. Same bounds as
    # ComputeTask.log_position() — keep these in sync.
    lo, hi = -12.0, 17.0
    axis_ticks = [
        {
            'exp': e,
            'pct': round((e - lo) / (hi - lo) * 100.0, 2),
        }
        for e in range(-12, 18, 3)
    ]

    context = {
        'tasks': tasks,
        'by_category': by_cat,
        'comparables': comparables,
        'axis_ticks': axis_ticks,
    }
    return render(request, 'reckoner/index.html', context)


@login_required
def detail(request, slug):
    task = get_object_or_404(ComputeTask, slug=slug)
    comparables = list(EnergyComparable.objects.all())
    _annotate(task, comparables)

    # Build neighbour comparables within ±2 orders of magnitude for
    # the detail page's "scale ruler".
    target = math.log10(task.energy_joules) if task.energy_joules > 0 else 0
    window = 2.0
    lo = target - window
    hi = target + window
    nearby = sorted(
        (
            c for c in comparables
            if lo <= math.log10(c.energy_joules) <= hi
        ),
        key=lambda c: c.energy_joules,
    )
    # Pre-compute the % left position for each peg on the local
    # log axis (template can't do logs).
    for c in nearby:
        c.pct = round((math.log10(c.energy_joules) - lo) / (hi - lo) * 100.0, 2)
    task_pct = round((target - lo) / (hi - lo) * 100.0, 2)

    # Lane assignment: greedy packing so pegs within MIN_GAP% of each
    # other drop into a lower lane. The task marker sits in lane -1
    # (above the axis) so it is always prominent.
    MIN_GAP = 14.0
    lane_last = []  # last peg % per lane
    for c in nearby:
        lane = None
        for i, last in enumerate(lane_last):
            if c.pct - last >= MIN_GAP:
                lane = i
                lane_last[i] = c.pct
                break
        if lane is None:
            lane_last.append(c.pct)
            lane = len(lane_last) - 1
        c.lane = lane
    ruler_lanes = max(1, len(lane_last))

    # Pick up to 6 peer tasks in the same category for context.
    peers = list(
        ComputeTask.objects
        .filter(category=task.category)
        .exclude(pk=task.pk)
        .order_by('energy_joules')[:6]
    )
    for p in peers:
        _annotate(p, comparables)

    # Factor bar widths: 0..5 → 0..50% (centred bars fill outward
    # from the midline). Social is signed; width uses |score|.
    def _pct5(x):
        return round(min(abs(x), 5) / 5.0 * 50.0, 1)

    context = {
        'task': task,
        'nearby': nearby,
        'task_pct': task_pct,
        'ruler_lanes': ruler_lanes,
        'peers': peers,
        'env_pct': _pct5(task.environmental_score),
        'pol_pct': _pct5(task.political_score),
        'eco_pct': _pct5(task.economic_score),
        'soc_pct': _pct5(task.social_score),
    }
    return render(request, 'reckoner/detail.html', context)


@login_required
def apps(request):
    """Reckon with Velour's own cost — every app as a typical-day
    bundle of ComputeTasks."""
    comparables = list(EnergyComparable.objects.all())
    tasks_by_id = {t.pk: t for t in ComputeTask.objects.all()}

    profiles = []
    total_velour = 0.0
    max_total = 0.0

    for app in AppProfile.objects.prefetch_related('usages__task'):
        # Pre-compute contribution per usage so the template can
        # rank them without extra queries.
        rows = []
        app_total = 0.0
        for u in app.usages.all():
            t = tasks_by_id.get(u.task_id) or u.task
            contrib = t.energy_joules * u.count_per_day
            rows.append({
                'task': t,
                'count': u.count_per_day,
                'note': u.note,
                'contrib': contrib,
            })
            app_total += contrib
        rows.sort(key=lambda r: r['contrib'], reverse=True)

        # Share-of-app percentages for the stacked bar.
        for r in rows:
            r['share_pct'] = (
                (r['contrib'] / app_total * 100.0) if app_total > 0 else 0.0
            )

        # Match to signpost.
        match = None
        if app_total > 0 and comparables:
            target = math.log10(app_total)
            match = min(
                comparables,
                key=lambda c: abs(math.log10(c.energy_joules) - target),
            )

        profiles.append({
            'app': app,
            'total': app_total,
            'rows': rows,
            'match': match,
        })
        total_velour += app_total
        max_total = max(max_total, app_total)

    # Sort heaviest first — the juiciest data at the top.
    profiles.sort(key=lambda p: p['total'], reverse=True)

    # Strip position for each app (local log axis anchored to the
    # heaviest app so relative weights are readable).
    if max_total > 0:
        hi = math.log10(max_total)
        # Go three decades down from the max — anything below is a
        # rounding error at this scale.
        lo = hi - 3.0
        for p in profiles:
            if p['total'] > 0:
                x = (math.log10(p['total']) - lo) / (hi - lo)
                p['strip_pct'] = round(max(0.0, min(1.0, x)) * 100.0, 2)
            else:
                p['strip_pct'] = 0.0
    else:
        for p in profiles:
            p['strip_pct'] = 0.0

    velour_match = None
    if total_velour > 0 and comparables:
        target = math.log10(total_velour)
        velour_match = min(
            comparables,
            key=lambda c: abs(math.log10(c.energy_joules) - target),
        )

    context = {
        'profiles': profiles,
        'total_velour': total_velour,
        'velour_match': velour_match,
        'n_apps': len(profiles),
    }
    return render(request, 'reckoner/apps.html', context)

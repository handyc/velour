"""Basic browsing views for the Agents app.

Phase 1 is read-mostly. We surface:
- /agents/                — town directory + total population
- /agents/town/<slug>/    — list residents in a town (paginated)
- /agents/<slug>/         — one Agent's detail page

Editing happens in admin for now.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Agent, AgentRelation, Town, TownCell


@login_required
def index(request):
    towns = Town.objects.all().order_by('name')
    rows = []
    for t in towns:
        rows.append({
            'town':      t,
            'count':     Agent.objects.filter(town=t).count(),
            'cells':     TownCell.objects.filter(town=t).count(),
            'mapped':    TownCell.objects.filter(town=t, world__isnull=False).count(),
        })
    total = Agent.objects.count()
    return render(request, 'agents/index.html', {
        'town_rows':  rows,
        'total':      total,
    })


@login_required
def town_detail(request, slug):
    town = get_object_or_404(Town, slug=slug)
    cells = list(TownCell.objects.filter(town=town).select_related('world'))
    qs = Agent.objects.filter(town=town).order_by('name', 'family_name')

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'agents/town_detail.html', {
        'town':  town,
        'cells': cells,
        'page':  page,
        'total': paginator.count,
    })


@login_required
def agent_detail(request, slug):
    a = get_object_or_404(
        Agent.objects.select_related('town', 'origin_world', 'current_cell'),
        slug=slug,
    )
    out = AgentRelation.objects.filter(src=a).select_related('dst')
    inc = AgentRelation.objects.filter(dst=a).select_related('src')
    return render(request, 'agents/agent_detail.html', {
        'agent':       a,
        'bio_bytes':   a.bio_size_bytes(),
        'estimated_row_bytes': a.estimated_row_bytes(),
        'outgoing':    out,
        'incoming':    inc,
    })

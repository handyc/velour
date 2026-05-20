from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from .models import StackGenome, EvolutionRun
from .population import pool_size, DEFAULT_POOL_DIRS


@login_required
def index(request):
    return render(request, 'boardstack/index.html', {
        'pool_size':  pool_size(),
        'pool_dirs':  DEFAULT_POOL_DIRS,
        'genomes':    StackGenome.objects.order_by('-fitness')[:20],
        'runs':       EvolutionRun.objects.order_by('-started_at')[:10],
    })

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Snapshot


@login_required
def index(request):
    snapshots = Snapshot.objects.all()[:50]
    counts = {
        r: Snapshot.objects.filter(retention=r).count()
        for r in ('daily', 'weekly', 'monthly', 'manual')
    }
    return render(request, 'backups/index.html', {
        'snapshots': snapshots,
        'counts': counts,
    })

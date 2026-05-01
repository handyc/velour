from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .genome import K_CHOICES, DEFAULT_K, DEFAULT_N_LOG2


@login_required
def index(request):
    """Single-page browser emulator for the nearest-neighbour CA.

    All compute (genome generation, step, render) runs in JS. The
    Django side just serves the page. This is the parallel of
    /s3lab/, but for the HXNN format — totally separate code path.
    """
    return render(request, 'hexnn/index.html', {
        'k_choices':  K_CHOICES,
        'default_k':  DEFAULT_K,
        'n_entries':  1 << DEFAULT_N_LOG2,
    })

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


@login_required
def tft_emulator(request):
    """Pixel-faithful 128×128 preview of the
    ``isolation/artifacts/hexnn_search/esp32_s3_tft/`` firmware.

    Renders to a 128×128 canvas at the same hex-tile pixel coordinates
    the device's ST7735 driver uses, so the canvas + the hardware
    panel show the same picture at the same seed. Same algorithm
    (imported from ``hexnn_engine.mjs``) — the device just runs the C
    port of it.
    """
    return render(request, 'hexnn/tft.html', {})

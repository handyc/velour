"""Zoetrope auto-edit — curate a large careful frame order from Attic.

Approach:
1. Sample up to K unique Attic image MediaItems.
2. Compute a small color fingerprint (mean RGB of a downscaled thumb)
   for each, and derive hue/brightness.
3. Order them via a greedy nearest-neighbor traversal in RGB space
   starting from a randomly picked seed — this gives smoothly
   changing color transitions rather than abrupt cuts.
4. If `count` is larger than the number of unique sources, walk the
   ordered list forward then back then forward again (ping-pong)
   until the target frame count is reached. Each image is therefore
   visited many times but never back-to-back with itself unless the
   source pool is genuinely tiny.
5. Store the ordered MediaItem PKs on `Reel.frame_order` and render.

This is an O(K²) ordering + K image reads. For K ≈ 500 that's tiny.
For count = 3000, duration = 10s, fps = 300 is the default: the mp4
contains 3000 real frames even if players drop most.
"""

import random
from io import BytesIO
from pathlib import Path

from django.utils import timezone


def _fingerprint_item(item):
    """Mean RGB of a downscaled image — a 3-float fingerprint."""
    from PIL import Image

    try:
        with item.file.open('rb') as f:
            data = f.read()
        img = Image.open(BytesIO(data)).convert('RGB').resize((24, 24))
    except Exception:
        return None
    pixels = list(img.getdata())
    if not pixels:
        return None
    rs, gs, bs = zip(*pixels)
    n = len(pixels)
    return (sum(rs) / n, sum(gs) / n, sum(bs) / n)


def _greedy_order(fingerprints, rng):
    """Greedy nearest-neighbor TSP from a random start.
    Input: list of (pk, rgb). Output: list of pks."""
    if not fingerprints:
        return []
    remaining = list(fingerprints)
    start = rng.randrange(len(remaining))
    current = remaining.pop(start)
    order = [current[0]]
    while remaining:
        cr, cg, cb = current[1]
        best_i, best_d = 0, float('inf')
        for i, (_pk, rgb) in enumerate(remaining):
            d = (rgb[0]-cr)**2 + (rgb[1]-cg)**2 + (rgb[2]-cb)**2
            if d < best_d:
                best_d, best_i = d, i
        current = remaining.pop(best_i)
        order.append(current[0])
    return order


def _ping_pong(order, target_count):
    """Extend `order` by walking forward then backward then forward
    until we have `target_count` entries. Avoids same-frame repeats."""
    if not order:
        return []
    out = []
    forward = True
    idx = 0
    direction = 1
    # Ping-pong: ... 0 1 2 .. n-1 n-2 ... 1 0 1 2 ...
    while len(out) < target_count:
        out.append(order[idx])
        idx += direction
        if idx >= len(order):
            idx = len(order) - 2 if len(order) > 1 else 0
            direction = -1
        elif idx < 0:
            idx = 1 if len(order) > 1 else 0
            direction = 1
    return out[:target_count]


def auto_edit_reel(count=3000, duration_seconds=10.0, fps=300,
                   source_sample_cap=500, title=None,
                   speech_sample_count=6, speech_volume=0.75,
                   width=960, height=540, rng=None):
    """Build a careful-selection Reel of `count` frames and render it.

    Returns the new Reel (possibly in status 'error' if render failed).
    """
    from attic.models import MediaItem

    from .models import Reel

    if rng is None:
        rng = random.Random()

    pool = list(MediaItem.objects.filter(kind='image'))
    if not pool:
        return None

    k = min(len(pool), max(8, source_sample_cap))
    sources = rng.sample(pool, k) if k < len(pool) else pool

    fps = max(24, min(300, int(fps)))
    count = max(1, min(int(count), 3000))
    duration_seconds = max(0.5, min(float(duration_seconds), 30.0))

    # Fingerprint every sampled source
    prints = []
    for item in sources:
        fp = _fingerprint_item(item)
        if fp is not None:
            prints.append((item.pk, fp))
    if not prints:
        return None

    ordered_pks = _greedy_order(prints, rng)
    frame_order = _ping_pong(ordered_pks, count)

    stamp = timezone.now().strftime('%Y-%m-%d %H:%M')
    if not title:
        title = f'Auto-edit · {count} frames · {stamp}'

    reel = Reel.objects.create(
        title=title,
        tag_filter='',
        selection_mode='random',
        image_count=count,
        fps=fps,
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        speech_sample_count=speech_sample_count,
        speech_volume=speech_volume,
        frame_order=frame_order,
    )
    reel.render()
    return reel

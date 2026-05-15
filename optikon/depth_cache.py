"""Server-side cache for custom depth maps used by autostereogram.

A user uploads an image through /optikon/depth/upload/.  We
greyscale + downsample with Pillow, discretise to N depth levels,
hash the resulting depth bytes, and cache as JSON under
MEDIA_ROOT/optikon/depth/.

The hash is short (64 hex chars) and fits comfortably in the
gridprint query string, so the same uploaded depth survives the
hand-off from the optikon playground to gridprint's A4 render.

We never delete cache entries automatically — the cache is small
(few KB per entry) and the hash is content-addressed so duplicate
uploads share storage.  A user can clear MEDIA_ROOT/optikon/ by
hand if they want to free space.
"""

from __future__ import annotations
from pathlib import Path
import hashlib
import io
import json

from django.conf import settings


CACHE_SUBDIR = 'optikon/depth'


def cache_dir() -> Path:
    p = Path(settings.MEDIA_ROOT) / CACHE_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path(sha: str) -> Path:
    """Path to a cached depth map.  Caller is responsible for
    validating `sha` is a hex string before passing in."""
    return cache_dir() / f'{sha}.json'


def image_to_depth(image_bytes: bytes, *,
                   max_dim:    int = 128,
                   n_levels:   int = 4,
                   invert:     bool = False) -> tuple[int, int, list[list[int]]]:
    """Greyscale + downsample an arbitrary image to a small depth
    map of size up to (max_dim × max_dim), with each cell quantised
    to 0..(n_levels-1).  Aspect-ratio preserved.

    Returns (w, h, depths-as-2D-list).
    """
    from PIL import Image

    n = max(2, min(8, int(n_levels)))
    img = Image.open(io.BytesIO(image_bytes))
    # Force greyscale; collapse alpha onto white.
    if img.mode in ('LA', 'RGBA'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    img = img.convert('L')
    # Downsample preserving aspect ratio.
    w0, h0 = img.size
    if w0 == 0 or h0 == 0:
        raise ValueError('image has zero dimension')
    scale = min(1.0, max_dim / max(w0, h0))
    nw = max(1, int(round(w0 * scale)))
    nh = max(1, int(round(h0 * scale)))
    img = img.resize((nw, nh), Image.LANCZOS)
    px = list(img.getdata())
    # Quantise: dark pixels = high depth (figure pops out) by default;
    # invert flips so light pixels are the figure.
    levels: list[list[int]] = []
    for y in range(nh):
        row = []
        for x in range(nw):
            v = px[y * nw + x]
            if invert: v = 255 - v
            # 0=background (light), n-1=top (dark)
            d = (255 - v) * n // 256
            if d >= n: d = n - 1
            if d < 0:  d = 0
            row.append(d)
        levels.append(row)
    return nw, nh, levels


def store(image_bytes: bytes, **kwargs) -> dict:
    """Convert + hash + persist.  Returns metadata including 'sha'.
    Idempotent: re-uploading the same image (with same kwargs) is a
    no-op — same hash, same file."""
    w, h, depths = image_to_depth(image_bytes, **kwargs)
    payload = {
        'kind':     'optikon-depth-map',
        'version':  1,
        'w':        w,
        'h':        h,
        'n_levels': max(d for row in depths for d in row) + 1 if depths else 0,
        'depths':   depths,
    }
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    sha = hashlib.sha256(body).hexdigest()
    cache_path(sha).write_bytes(body)
    return {'sha': sha, 'w': w, 'h': h, 'bytes': len(body)}


def load(sha: str) -> dict | None:
    """Look up a cached depth map by sha.  Returns the JSON payload
    (with 'depths' key) or None if not found / sha invalid."""
    if not sha or not all(c in '0123456789abcdef' for c in sha) or len(sha) != 64:
        return None
    p = cache_path(sha)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_bytes())
    except (ValueError, OSError):
        return None

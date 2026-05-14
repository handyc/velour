"""Bitmap-upload motif renderer.

Reads an :class:`UploadedMotif` from disk and emits the SVG body
fragment that places the image, base64-encoded, inside the
[0, 1]×[0, 1] motif box with its native aspect ratio preserved
and a small inset on the border.

We embed via ``<image href="data:...">`` rather than referencing a
``/media/`` URL so that downloaded SVG files are self-contained —
once you save the SVG you can email it / print it without the
escher server in the loop.
"""

from __future__ import annotations

import base64


def upload_motif(slug: str, *, inset: float = 0.04) -> str:
    """Return the SVG body fragment for the uploaded image at ``slug``.
    Falls back to a labelled placeholder if the record or file is
    missing.
    """
    from .models import UploadedMotif

    rec = UploadedMotif.objects.filter(slug=slug).first()
    if rec is None or not rec.file:
        return _placeholder(f'upload "{slug}" not found')
    try:
        rec.file.open('rb')
        raw = rec.file.read()
    except (FileNotFoundError, OSError) as exc:
        return _placeholder(f'upload file missing: {exc}')
    finally:
        try: rec.file.close()
        except Exception: pass

    b64 = base64.b64encode(raw).decode('ascii')
    href = f'data:{rec.content_type};base64,{b64}'

    # Compute fitted (x, y, w, h) within [inset, 1-inset]² preserving
    # the image's aspect ratio.
    iw = max(1, int(rec.width or 1))
    ih = max(1, int(rec.height or 1))
    avail = 1.0 - 2.0 * inset
    if iw >= ih:
        w = avail
        h = avail * (ih / iw)
    else:
        h = avail
        w = avail * (iw / ih)
    x = inset + (avail - w) / 2.0
    y = inset + (avail - h) / 2.0

    return (
        f'<image href="{href}" x="{x:.4f}" y="{y:.4f}" '
        f'width="{w:.4f}" height="{h:.4f}" '
        f'preserveAspectRatio="xMidYMid meet" />'
    )


def _placeholder(msg: str) -> str:
    import html
    return (
        '<rect x="0" y="0" width="1" height="1" '
        'fill="#fee" stroke="#c44" stroke-width="0.01" />'
        '<text x="0.05" y="0.5" '
        'font-family="ui-monospace,monospace" font-size="0.05" '
        f'fill="#a22">{html.escape(msg)}</text>'
    )

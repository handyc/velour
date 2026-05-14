"""Bitmap-upload motif renderer.

Reads an :class:`UploadedMotif` from disk and emits the SVG body
fragment that places the image inside the [0, 1]×[0, 1] motif box
with its native aspect ratio preserved and a small inset on the
border.

Modes (controlled by ``embed`` argument):

* ``embed='url'`` (default) — reference the file via its
  ``MEDIA_URL`` path, e.g. ``/media/escher/motifs/<sha>.jpg``.
  Reliable for previews loaded inside iframes; downloaded SVGs
  need network access back to the same server to render.
* ``embed='base64'`` — encode the file inline as a data URI so the
  downloaded SVG is self-contained.  Some browsers refuse to load
  ``<image href="data:...">`` when the SVG is itself loaded as a
  standalone iframe document, which is why this isn't the default.
"""

from __future__ import annotations

import base64


def upload_motif(slug: str, *, inset: float = 0.04,
                  embed: str = 'url') -> str:
    """Return the SVG body fragment for the uploaded image at ``slug``.

    Falls back to a labelled placeholder if the record or file is
    missing.  See module docstring for ``embed`` modes.
    """
    from .models import UploadedMotif

    rec = UploadedMotif.objects.filter(slug=slug).first()
    if rec is None or not rec.file:
        return _placeholder(f'upload "{slug}" not found')

    if embed == 'base64':
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
    else:
        # Default: reference the file by its served MEDIA_URL path.
        # Browsers render <image href="/media/.../file.jpg"> reliably
        # both inline and inside iframe-loaded SVGs.
        href = rec.file.url

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

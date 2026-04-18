"""Diagram rendering helpers.

Source-text diagrams go to Kroki.io, which fronts a zoo of renderers
(Mermaid, Graphviz, PlantUML, D2, the *diag family, WireViz, TikZ,
and more). The hosted instance at https://kroki.io is free; point at
a self-hosted one by setting `CODEX_KROKI_URL` in Django settings.

Network failures and bad input return None rather than raising — the
caller (Figure.save) treats None as "couldn't render, keep whatever
was there before".
"""

import urllib.error
import urllib.request

from django.conf import settings


DEFAULT_KROKI_URL = 'https://kroki.io'


def _kroki_url():
    return getattr(settings, 'CODEX_KROKI_URL', DEFAULT_KROKI_URL).rstrip('/')


def render_diagram_to_png(source, kind='mermaid', timeout=15):
    """Render a source-text diagram to PNG bytes.

    `kind='svg'` is handled locally via cairosvg — works offline and
    keeps KiCad / Inkscape / hand-authored SVG schematics entirely
    on-box. Every other kind goes to Kroki's `/<kind>/png` endpoint.

    Returns PNG bytes, or None on any error (bad source, network
    down, unsupported kind, timeout).
    """
    if not source or not source.strip():
        return None
    if kind == 'svg':
        return _render_svg_locally(source)
    try:
        req = urllib.request.Request(
            f'{_kroki_url()}/{kind}/png',
            data=source.encode('utf-8'),
            headers={
                'Content-Type': 'text/plain',
                'User-Agent': 'velour-codex/0.3',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def _render_svg_locally(svg_text):
    """Render a raw SVG string to PNG via cairosvg. The rasterisation
    target is 2x scale so diagrams stay crisp at typical PDF dpi."""
    try:
        import cairosvg
    except ImportError:
        return None
    try:
        return cairosvg.svg2png(
            bytestring=svg_text.encode('utf-8'),
            scale=2.0,
        )
    except Exception:
        return None

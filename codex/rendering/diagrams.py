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
    """POST diagram source to Kroki's `/<kind>/png` endpoint.

    `kind` is a canonical Kroki language name (mermaid, graphviz,
    plantuml, d2, blockdiag, …). Returns PNG bytes, or None on any
    error (network down, bad source, unsupported kind, timeout).
    """
    if not source or not source.strip():
        return None
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

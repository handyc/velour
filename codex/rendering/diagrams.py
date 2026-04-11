"""Diagram rendering helpers.

Currently implements Mermaid → PNG via the Kroki.io HTTP API.

Kroki is a lightweight diagram-rendering service that supports many
text-based diagram formats (Mermaid, PlantUML, Graphviz, BlockDiag,
etc.). The hosted instance at https://kroki.io is free and the
service is open-source, so this renderer can be pointed at a
self-hosted instance later by setting `CODEX_KROKI_URL` in Django
settings.

Network failures and bad input return None rather than raising —
the caller (Figure.save) treats None as "couldn't render, keep
whatever was there before".
"""

import urllib.error
import urllib.request

from django.conf import settings


DEFAULT_KROKI_URL = 'https://kroki.io'


def _kroki_url():
    return getattr(settings, 'CODEX_KROKI_URL', DEFAULT_KROKI_URL).rstrip('/')


def render_mermaid_to_png(source, timeout=15):
    """POST mermaid source to Kroki and return the rendered PNG bytes.

    Returns None on any error (network down, bad source, timeout).
    """
    if not source or not source.strip():
        return None
    try:
        req = urllib.request.Request(
            f'{_kroki_url()}/mermaid/png',
            data=source.encode('utf-8'),
            headers={
                'Content-Type': 'text/plain',
                'User-Agent': 'velour-codex/0.2',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

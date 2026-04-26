"""Datalift's contribution to the daily app-status manual.

Reports the gallery entry count and lists the 5 most recently added."""

from __future__ import annotations


def report() -> dict:
    from .views import GALLERY_ENTRIES

    total = len(GALLERY_ENTRIES)
    # Latest gallery entries are appended at the end of the list.
    recent = list(GALLERY_ENTRIES)[-5:]
    lines = [
        f'**Gallery entries:** {total}',
        '',
        'Five most-recently added:',
        '',
    ]
    for e in reversed(recent):
        lines.append(f'- *{e["title"]}* — {e["subtitle"]}')

    return {
        'title':     'Datalift',
        'sort_hint': 30,
        'body_md':   '\n'.join(lines),
    }

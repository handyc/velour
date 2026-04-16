"""Render-time helpers for ingested body_html.

Kept here (not in ingest_displace) so we don't have to mutate stored
content or re-ingest when we discover a new upstream quirk.
"""

import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


# Zotonic's oembed handler emits YouTube iframes like
#   src="https://www.youtube.com/embed/<id>?start=40&feature=oembed"
# YouTube responds to the feature=oembed parameter with player
# Error 153 ("Video player configuration error") because it's
# meant for the oEmbed API response, not direct iframe embedding.
_YT_BAD_PARAMS = re.compile(r'(?:^|[?&])(feature=oembed|enablejsapi=\d+)', re.I)


def _clean_youtube_src(src: str) -> str:
    if 'youtube.com/embed/' not in src and 'youtube-nocookie.com/embed/' not in src:
        return src
    # HTML-decode &amp; → & before splitting, re-encode after.
    raw = src.replace('&amp;', '&')
    if '?' not in raw:
        return src
    base, _, query = raw.partition('?')
    parts = [p for p in query.split('&')
             if p and not _YT_BAD_PARAMS.search('?' + p)]
    cleaned = base if not parts else f'{base}?{"&".join(parts)}'
    return cleaned.replace('&', '&amp;')


@register.filter(name='clean_embeds')
def clean_embeds(html: str) -> str:
    """Scrub upstream embed quirks from a body_html string.

    Currently fixes YouTube `feature=oembed` (→ Error 153). Safe to
    apply to any HTML; non-iframe content passes through untouched.
    """
    if not html or '<iframe' not in html:
        return mark_safe(html or '')

    def _fix(match):
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        return f'{prefix}{_clean_youtube_src(src)}{suffix}'

    fixed = re.sub(r'(<iframe\b[^>]*\bsrc=")([^"]+)(")', _fix, html)
    return mark_safe(fixed)

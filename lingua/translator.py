"""Cache-first translation entry point.

`translate(source_text, target_lang, source_lang='en')` returns a
dict:

    {
        'translation': str,
        'cached':      bool,
        'backend':     str,
        'error':       str ('' on success),
    }

Strategy:
    1. Normalise whitespace, skip empty or already-target-lang.
    2. Hash → look up TranslationCache row. If present, bump hit
       counters and return it. This is the common path and does not
       touch any network.
    3. Otherwise, call `backends.pick()`. If nothing is available,
       return an error — caller renders "—" in the UI.
    4. On success, store the row for next time.
"""

from __future__ import annotations

import re

from django.utils import timezone as djtz

from . import backends
from .models import TranslationCache, source_hash


_WS = re.compile(r'[ \t]+')

MAX_LEN = 4000  # Refuse to translate pathologically long strings.


def _norm(text: str) -> str:
    # Collapse runs of spaces/tabs inside lines; keep newlines.
    return '\n'.join(_WS.sub(' ', line).strip()
                     for line in (text or '').splitlines()).strip()


def translate(source_text: str, target_lang: str, source_lang: str = 'en') -> dict:
    text = _norm(source_text)
    if not text:
        return {'translation': '', 'cached': False,
                'backend': '', 'error': 'empty source'}
    if len(text) > MAX_LEN:
        return {'translation': '', 'cached': False,
                'backend': '', 'error': f'source exceeds {MAX_LEN} chars'}
    if not target_lang:
        return {'translation': '', 'cached': False,
                'backend': '', 'error': 'no target_lang'}
    if target_lang == source_lang:
        return {'translation': text, 'cached': False,
                'backend': 'identity', 'error': ''}

    h = source_hash(text)
    hit = TranslationCache.objects.filter(
        source_hash=h, source_lang=source_lang, target_lang=target_lang,
    ).first()

    if hit:
        TranslationCache.objects.filter(pk=hit.pk).update(
            hit_count=hit.hit_count + 1,
            last_hit_at=djtz.now(),
        )
        return {'translation': hit.translation, 'cached': True,
                'backend': hit.backend, 'error': ''}

    backend = backends.pick(source_lang, target_lang)
    if backend is None:
        return {'translation': '', 'cached': False,
                'backend': '', 'error': 'no backend available'}

    out = backend['translate'](text, source_lang, target_lang)
    if out.get('error') or not out.get('translation'):
        return {'translation': '', 'cached': False,
                'backend': backend['name'],
                'error': out.get('error') or 'empty translation'}

    row, _ = TranslationCache.objects.update_or_create(
        source_hash=h, source_lang=source_lang, target_lang=target_lang,
        defaults={
            'source_text': text,
            'translation': out['translation'],
            'backend':     backend['name'],
            'confidence':  float(out.get('confidence') or 0.0),
            'tokens_in':   int(out.get('tokens_in') or 0),
            'tokens_out':  int(out.get('tokens_out') or 0),
            'hit_count':   1,
            'last_hit_at': djtz.now(),
        },
    )
    return {'translation': row.translation, 'cached': False,
            'backend': backend['name'], 'error': ''}

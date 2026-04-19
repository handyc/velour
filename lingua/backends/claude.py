"""Anthropic Claude backend for Lingua.

Reads the API key from BASE_DIR/lingua_api_key.txt (chmod 600,
gitignored). Falls back to ANTHROPIC_API_KEY env var. If neither
is set, `enabled()` returns False and Lingua will only serve
already-cached rows.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from django.conf import settings


API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
MODEL = 'claude-haiku-4-5-20251001'


def _key_path():
    return os.path.join(str(settings.BASE_DIR), 'lingua_api_key.txt')


def _read_key():
    path = _key_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                k = f.read().strip()
                if k:
                    return k
        except OSError:
            pass
    return os.environ.get('ANTHROPIC_API_KEY', '').strip()


def enabled() -> bool:
    return bool(_read_key())


SYSTEM = (
    "You are a faithful translator. Return ONLY the translation, "
    "with no commentary, no romanisation, no quote marks around the result. "
    "Preserve proper nouns. If the source is already in the target language, "
    "return it unchanged. For classical/low-resource languages (Ancient Greek, "
    "Latin, Sanskrit) use the standard scholarly orthography."
)


def _lang_name(code: str) -> str:
    """Short hints to help the model resolve ambiguous codes."""
    return {
        'en': 'English',
        'nl': 'Dutch',
        'zh-Hans': 'Simplified Chinese',
        'zh-Hant': 'Traditional Chinese',
        'es': 'Spanish',
        'fr': 'French',
        'he': 'Modern Hebrew',
        'grc': 'Ancient Greek (polytonic)',
        'la':  'Latin',
        'san': 'Sanskrit (Devanagari)',
        'ja':  'Modern Japanese',
        'ko':  'Modern Korean',
        'de':  'German',
        'it':  'Italian',
        'pt':  'Portuguese',
        'ru':  'Russian',
        'ar':  'Modern Standard Arabic',
    }.get(code, code)


def translate(source_text: str, source_lang: str, target_lang: str) -> dict:
    key = _read_key()
    if not key:
        return {'translation': '', 'confidence': 0.0,
                'tokens_in': 0, 'tokens_out': 0,
                'error': 'no API key on disk or in env'}

    src = _lang_name(source_lang or 'en')
    tgt = _lang_name(target_lang)
    prompt = f"Translate from {src} to {tgt}:\n\n{source_text}"

    body = json.dumps({
        'model': MODEL,
        'max_tokens': 1024,
        'system': SYSTEM,
        'messages': [{'role': 'user', 'content': prompt}],
    }).encode('utf-8')

    req = urllib.request.Request(
        API_URL, data=body, method='POST',
        headers={
            'Content-Type':       'application/json',
            'x-api-key':          key,
            'anthropic-version':  API_VERSION,
            'User-Agent':         'velour-lingua/1',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')[:300]
        except Exception:
            err_body = ''
        return {'translation': '', 'confidence': 0.0,
                'tokens_in': 0, 'tokens_out': 0,
                'error': f'HTTP {e.code}: {err_body}'}
    except urllib.error.URLError as e:
        return {'translation': '', 'confidence': 0.0,
                'tokens_in': 0, 'tokens_out': 0,
                'error': f'Network: {e.reason}'}
    except Exception as e:
        return {'translation': '', 'confidence': 0.0,
                'tokens_in': 0, 'tokens_out': 0,
                'error': f'{type(e).__name__}: {e}'}

    try:
        data = json.loads(raw)
        content_blocks = data.get('content') or []
        text_parts = [b.get('text', '') for b in content_blocks
                      if b.get('type') == 'text']
        translation = ''.join(text_parts).strip()
        usage = data.get('usage') or {}
        tin  = int(usage.get('input_tokens')  or 0)
        tout = int(usage.get('output_tokens') or 0)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {'translation': '', 'confidence': 0.0,
                'tokens_in': 0, 'tokens_out': 0,
                'error': f'bad response shape: {raw[:200]}'}

    if not translation:
        return {'translation': '', 'confidence': 0.0,
                'tokens_in': tin, 'tokens_out': tout,
                'error': 'empty translation'}

    return {'translation': translation,
            'confidence': 0.8,
            'tokens_in': tin,
            'tokens_out': tout,
            'error': ''}


BACKEND = {
    'name':      'claude',
    'label':     'Anthropic Claude (haiku)',
    'enabled':   enabled,
    'translate': translate,
}

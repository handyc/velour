"""Backend registry for Lingua.

Each backend is a dict shaped like:

    {
        'name':      'claude',
        'label':     'Anthropic Claude',
        'enabled':   lambda: bool(api_key on disk),
        'translate': fn(source_text, source_lang, target_lang) -> dict
    }

`translate` returns:
    {
        'translation': str,
        'confidence':  float 0..1,
        'tokens_in':   int,
        'tokens_out':  int,
        'error':       str ('' on success),
    }

Never raises. On failure, returns translation='' with a populated error.
"""

from . import claude, manual


BACKENDS = [claude.BACKEND, manual.BACKEND]


def by_name(name):
    for b in BACKENDS:
        if b['name'].lower() == (name or '').lower():
            return b
    return None


def pick(source_lang, target_lang):
    """Return the first enabled backend that can handle this pair.
    Live backends (Claude) are tried first; 'manual' never auto-picks."""
    for b in BACKENDS:
        if b['name'] == 'manual':
            continue
        if b['enabled']():
            return b
    return None

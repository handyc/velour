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

from . import argos, claude, manual


# argos is first so offline translation is the default. claude is kept
# registered (so admins who drop a key at BASE_DIR/lingua_api_key.txt
# can opt into it) but only wins the `pick()` round if argos has no
# packages installed. Order matters: `pick()` returns the first enabled
# non-manual backend.
BACKENDS = [argos.BACKEND, claude.BACKEND, manual.BACKEND]


def by_name(name):
    for b in BACKENDS:
        if b['name'].lower() == (name or '').lower():
            return b
    return None


def pick(source_lang, target_lang):
    """Return the first backend that can handle this specific pair.
    'manual' never auto-picks. A backend can opt into pair-level
    filtering by exposing `can_translate(src, tgt)` — otherwise
    `enabled()` alone determines eligibility, and the backend owns the
    fallout when a pair turns out to be unsupported."""
    for b in BACKENDS:
        if b['name'] == 'manual':
            continue
        can = b.get('can_translate')
        if can is not None:
            if can(source_lang, target_lang):
                return b
            continue
        if b['enabled']():
            return b
    return None

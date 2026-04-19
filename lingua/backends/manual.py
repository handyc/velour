"""Placeholder backend: human-entered translations.

Used only by the admin (e.g. when a scholar edits a cached row).
`pick()` skips it so automatic translate calls never hit this path.
"""


def translate(source_text, source_lang, target_lang):
    return {'translation': '', 'confidence': 0.0,
            'tokens_in': 0, 'tokens_out': 0,
            'error': 'manual backend does not auto-translate'}


BACKEND = {
    'name':      'manual',
    'label':     'Human-edited',
    'enabled':   lambda: True,
    'translate': translate,
}

"""Argos Translate backend — fully offline, no external API keys.

Argos uses OPUS-MT models shipped as ~50–200 MB `.argosmodel` files.
After a one-time install of the language pairs you care about (see
`manage.py lingua_install_pair --from en --to nl` or `seed_argos_langs`),
translation runs entirely on CPU with no network traffic — which is the
whole point: Velour stays independent of Anthropic, OpenAI, or any
vendor cloud.

Language codes: Argos speaks ISO 639-1 ('en', 'nl', 'es', 'zh', 'ja',
…). Lingua's seeded codes include a couple of variants ('zh-Hans',
'grc', 'la', 'san') that Argos either maps to a base code or doesn't
cover at all. `_to_argos_code` handles the mapping; unsupported codes
cause `translate()` to return an empty translation with an informative
error so the UI shows a dash rather than silently falling back to
some other backend.
"""

from __future__ import annotations


# Lingua code → Argos code. None means "Argos has no model for this".
_CODE_MAP = {
    'en':      'en',
    'nl':      'nl',
    'es':      'es',
    'fr':      'fr',
    'de':      'de',
    'it':      'it',
    'pt':      'pt',
    'ru':      'ru',
    'ar':      'ar',
    'he':      'he',
    'ja':      'ja',
    'ko':      'ko',
    'zh-Hans': 'zh',
    'zh-Hant': 'zt',
    # Classical / low-resource — Argos doesn't ship these.
    'grc':     None,
    'la':      None,
    'san':     None,
}


def _to_argos_code(code: str):
    if code in _CODE_MAP:
        return _CODE_MAP[code]
    # Accept a bare ISO 639-1 we haven't explicitly listed.
    return code if code and len(code) == 2 else None


def _import():
    """Lazy import so Lingua still loads when argostranslate isn't
    installed (e.g. on a tiny deploy where offline translation isn't
    wanted). Any import error turns into a disabled backend."""
    try:
        import argostranslate.translate as tr
        import argostranslate.package as pkg
    except Exception:
        return None, None
    return tr, pkg


def _installed_pair_codes():
    tr, _ = _import()
    if tr is None:
        return set()
    out = set()
    for lang in tr.get_installed_languages():
        for t in getattr(lang, 'translations_from', []) or []:
            to_code = getattr(getattr(t, 'to_lang', None), 'code', None)
            if to_code:
                out.add((lang.code, to_code))
    return out


def enabled() -> bool:
    """True once the caller has installed at least one language pair.
    Without installed packages, Argos can do nothing, so the registry
    should skip this backend and fall through to `manual`."""
    return bool(_installed_pair_codes())


def can_translate(source_lang: str, target_lang: str) -> bool:
    s = _to_argos_code(source_lang)
    t = _to_argos_code(target_lang)
    if not s or not t or s == t:
        return False
    return (s, t) in _installed_pair_codes()


def translate(source_text: str, source_lang: str, target_lang: str) -> dict:
    tr, _ = _import()
    if tr is None:
        return _err('argostranslate not installed')

    s = _to_argos_code(source_lang)
    t = _to_argos_code(target_lang)
    if not s:
        return _err(f'no Argos mapping for source lang {source_lang!r}')
    if not t:
        return _err(f'no Argos mapping for target lang {target_lang!r}')
    if (s, t) not in _installed_pair_codes():
        return _err(
            f'no installed Argos package for {s}→{t}; '
            f'run `manage.py lingua_install_pair --from {s} --to {t}`'
        )

    try:
        out = tr.translate(source_text, s, t)
    except Exception as e:
        return _err(f'{type(e).__name__}: {e}')

    if not out:
        return _err('empty translation')

    # Token counts aren't exposed by Argos; leave them at 0.
    return {'translation': out.strip(),
            'confidence':  0.7,
            'tokens_in':   0,
            'tokens_out':  0,
            'error':       ''}


def _err(msg: str) -> dict:
    return {'translation': '', 'confidence': 0.0,
            'tokens_in': 0, 'tokens_out': 0, 'error': msg}


def install_pair(from_code: str, to_code: str) -> bool:
    """One-shot installer used by the management command. Downloads
    the remote index if needed, then installs the OPUS-MT package for
    the pair. Returns True on success."""
    _, pkg = _import()
    if pkg is None:
        return False
    try:
        pkg.update_package_index()
    except Exception:
        pass  # Offline machines may still have a local index.
    try:
        return bool(pkg.install_package_for_language_pair(from_code, to_code))
    except Exception:
        return False


BACKEND = {
    'name':          'argos',
    'label':         'Argos Translate (offline OPUS-MT)',
    'enabled':       enabled,
    'can_translate': can_translate,
    'translate':     translate,
}

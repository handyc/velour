"""Konso ↔ Lingua bridge.

Konso tracks languages by ISO 639-3 (e.g. ``nld``, ``jpn``, ``cmn``).
Lingua tracks them by BCP-47 for well-resourced ones (``nl``, ``ja``,
``zh-Hans``) and falls back to ISO 639-3 for low-resource languages
(``grc``, ``san``, ``lat``, ``arc``, ``hit``, ``xct``, ``pli``, ``hbo``).

This module provides one helper: ``lingua_language_for(konso_lang)``
resolves a ``konso.Language`` to the matching ``lingua.Language``,
creating the Lingua row if it doesn't exist yet. That lets the
"Add to flashcards" buttons work across all 72 Konso languages
without pre-seeding Lingua with every one.
"""

from __future__ import annotations

from lingua.models import Language as LinguaLanguage


# ISO 639-3 → Lingua code. Lingua prefers BCP-47 short tags for
# well-resourced languages (and falls back to 639-3 otherwise).
ISO3_TO_LINGUA = {
    # Explicit overrides where Lingua uses a short tag
    'nld': 'nl',
    'fra': 'fr',
    'jpn': 'ja',
    'spa': 'es',
    'deu': 'de',
    'eng': 'en',
    'heb': 'he',
    'kor': 'ko',
    'ita': 'it',
    'por': 'pt',
    'rus': 'ru',
    'ara': 'ar',
    'arb': 'ar',
    'tur': 'tr',
    'pol': 'pl',
    # Chinese variants — Lingua's generic code is zh-Hans
    'cmn': 'zh-Hans',
    'yue': 'zh-Hant',
    # Low-resource / classical — Lingua keeps the 639-3 code
    # (grc, san, lat, arc, hit, xct, pli, hbo, egy, bod, vie)
}


# Defaults used when auto-creating a lingua.Language row from a
# konso.Language. Keyed by Lingua code (post-mapping). Anything not
# in this table defaults to (latin, ltr, low_resource=True).
LINGUA_DEFAULTS = {
    'nl':       ('latin',      False, False),
    'fr':       ('latin',      False, False),
    'ja':       ('hiragana',   False, False),
    'es':       ('latin',      False, False),
    'de':       ('latin',      False, False),
    'en':       ('latin',      False, False),
    'he':       ('hebrew',     True,  False),
    'ko':       ('hangul',     False, False),
    'it':       ('latin',      False, False),
    'pt':       ('latin',      False, False),
    'ru':       ('cyrillic',   False, False),
    'ar':       ('arabic',     True,  False),
    'tr':       ('latin',      False, False),
    'pl':       ('latin',      False, False),
    'zh-Hans':  ('han',        False, False),
    'zh-Hant':  ('han',        False, False),
    'grc':      ('greek',      False, True),
    'san':      ('devanagari', False, True),
    'lat':      ('latin',      False, True),
    'arc':      ('hebrew',     True,  True),
    'hbo':      ('hebrew',     True,  True),
    'hit':      ('other',      False, True),
    'xct':      ('other',      False, True),
    'pli':      ('devanagari', False, True),
    'egy':      ('other',      False, True),
    'bod':      ('other',      False, True),
    'vie':      ('latin',      False, False),
}


def lingua_code_for(konso_lang) -> str | None:
    """Return the Lingua code that should correspond to a konso.Language.

    None if the Konso language has no ISO 639-3 code set.
    """
    iso3 = (konso_lang.iso639_3 or '').strip().lower()
    if not iso3:
        return None
    return ISO3_TO_LINGUA.get(iso3, iso3)


def lingua_language_for(konso_lang, create: bool = True):
    """Find (or create) the lingua.Language matching a konso.Language.

    Returns ``None`` if the Konso language has no ISO 639-3 code (we
    need that as the identifier). If ``create=False`` and no Lingua
    row exists, returns ``None``.
    """
    code = lingua_code_for(konso_lang)
    if not code:
        return None
    existing = LinguaLanguage.objects.filter(code=code).first()
    if existing or not create:
        return existing
    script, rtl, low_res = LINGUA_DEFAULTS.get(code, ('latin', False, True))
    return LinguaLanguage.objects.create(
        code=code,
        name=konso_lang.english_name or code,
        endonym=konso_lang.name or '',
        script=script,
        rtl=rtl,
        low_resource=low_res,
        notes=f'Auto-created from Konso language "{konso_lang.slug}".',
    )


def konso_slug_for_lingua_code(code: str) -> str | None:
    """Reverse: find a konso.Language slug matching a Lingua code.

    Used by the Lingua flashcards UI to link back to the Konso
    syntactic-tree library for the same language.
    """
    from .models import Language as KonsoLanguage
    code = (code or '').strip()
    if not code:
        return None
    # invert the ISO3_TO_LINGUA table
    iso3s = [k for k, v in ISO3_TO_LINGUA.items() if v == code]
    # Also try the code itself as a 639-3 (for grc/san/lat/etc.)
    iso3s.append(code)
    for iso3 in iso3s:
        k = KonsoLanguage.objects.filter(iso639_3=iso3).first()
        if k:
            return k.slug
    return None

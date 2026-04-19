"""Build a FlashCard deck for a target language.

Two modes:

    # 1. general deck — top N words from the bundled English frequency list
    manage.py lingua_build_deck --lang nl --size 100

    # 2. themed deck — words/phrases/sentences from themes.json
    manage.py lingua_build_deck --lang nl --theme body_parts
    manage.py lingua_build_deck --lang zh-Hans --theme out_on_the_town --level sentence

    # all themes at once, one level
    manage.py lingua_build_deck --lang nl --theme all --level word

Each input string is routed through `translator.translate()` (Argos by
default, falling back through the backend registry) and creates one
FlashCard row per string for the given user.

The per-word translations also land in the TranslationCache for free,
so hover translations of the same words elsewhere will be instant cache
hits afterwards.

If no `--user` is given, defaults to the first superuser — on a
single-tenant Velour this is normally the operator.

Skips strings already in the user's (language, theme, level) deck by
gloss, so re-running with a larger `--size` or the same theme extends
the deck rather than duplicating it.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from lingua import translator
from lingua.models import FlashCard, Language


DATA_DIR = Path(__file__).resolve().parents[2] / 'data'
FREQ_PATH = DATA_DIR / 'freq_en.txt'
THEMES_PATH = DATA_DIR / 'themes.json'


def _romanise(text: str, lang_code: str) -> str:
    """Optional transliteration of a translated string. Returns '' if we
    don't have a converter for this language or the import fails — the
    flashcard just shows no pronunciation line in that case.

    Currently only Chinese (zh / zh-Hans / zh-Hant) via pypinyin."""
    if not text:
        return ''
    if lang_code in ('zh', 'zh-Hans', 'zh-Hant'):
        try:
            from pypinyin import pinyin, Style
        except ImportError:
            return ''
        syllables = pinyin(text, style=Style.TONE, errors='ignore')
        return ' '.join(s[0] for s in syllables if s and s[0])
    return ''


def _load_themes():
    if not THEMES_PATH.exists():
        raise CommandError(f'themes file missing: {THEMES_PATH}')
    with THEMES_PATH.open(encoding='utf-8') as fh:
        return json.load(fh)


class Command(BaseCommand):
    help = ('Build a flashcard deck (general or themed) for a target '
            'language from bundled wordlists.')

    def add_arguments(self, parser):
        parser.add_argument('--lang',  required=True,
                            help='Target language code (e.g. nl, fr, zh-Hans).')
        parser.add_argument('--theme', default='',
                            help='Theme slug from themes.json (e.g. body_parts). '
                                 'Use "all" to iterate every theme that has the '
                                 'requested level. Omit for the general freq-list deck.')
        parser.add_argument('--level', default='word',
                            choices=['word', 'phrase', 'sentence'],
                            help='Level of entries to ingest (default: word). '
                                 'Only meaningful with --theme; the general freq '
                                 'deck is always --level word.')
        parser.add_argument('--size',  type=int, default=100,
                            help='Max entries per deck (default 100).')
        parser.add_argument('--user',  default=None,
                            help='Username to assign cards to (default: first superuser).')
        parser.add_argument('--source-lang', default='en',
                            help='Source language code (default: en).')

    def handle(self, *args, lang, theme, level, size, user, source_lang, **opts):
        User = get_user_model()
        if user:
            try:
                owner = User.objects.get(username=user)
            except User.DoesNotExist:
                raise CommandError(f'no such user: {user!r}')
        else:
            owner = User.objects.filter(is_superuser=True).order_by('pk').first()
            if not owner:
                raise CommandError('no --user given and no superuser exists')

        try:
            language = Language.objects.get(code=lang)
        except Language.DoesNotExist:
            raise CommandError(
                f'unknown language code {lang!r}. '
                f'Run `manage.py seed_lingua` first, or add the Language in admin.'
            )

        if theme:
            themes = _load_themes()
            if theme == 'all':
                theme_slugs = [t for t, spec in themes.items() if level in spec]
                if not theme_slugs:
                    raise CommandError(
                        f'no themes contain level {level!r}.')
            else:
                if theme not in themes:
                    raise CommandError(
                        f'unknown theme {theme!r}. Known: '
                        f'{", ".join(sorted(themes))}'
                    )
                if level not in themes[theme]:
                    raise CommandError(
                        f'theme {theme!r} has no {level!r} entries. '
                        f'Available levels: {", ".join(k for k in themes[theme] if k in ("word","phrase","sentence"))}'
                    )
                theme_slugs = [theme]

            total_created = total_skipped = total_failed = 0
            for slug in theme_slugs:
                strings = themes[slug][level][:size]
                self.stdout.write(self.style.NOTICE(
                    f'\n── {slug} / {level} · {len(strings)} entries · '
                    f'{language.name} ──'
                ))
                c, s, f = self._ingest(
                    owner=owner, language=language, source_lang=source_lang,
                    strings=strings, theme=slug, level=level,
                )
                total_created += c
                total_skipped += s
                total_failed  += f
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(
                f'themed build for {owner.username} / {language.name}: '
                f'{total_created} new, {total_skipped} already present, '
                f'{total_failed} without translation.'
            ))
            return

        # General freq-list deck (original behaviour).
        if not FREQ_PATH.exists():
            raise CommandError(f'frequency list missing: {FREQ_PATH}')
        words = []
        for line in FREQ_PATH.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            words.append(line)
        words = words[:size]
        self.stdout.write(self.style.NOTICE(
            f'── general freq list · {len(words)} words · {language.name} ──'
        ))
        c, s, f = self._ingest(
            owner=owner, language=language, source_lang=source_lang,
            strings=words, theme='', level='word',
        )
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'general deck for {owner.username} / {language.name}: '
            f'{c} new, {s} already present, {f} without translation.'
        ))

    def _ingest(self, *, owner, language, source_lang, strings, theme, level):
        existing = set(FlashCard.objects.filter(
            user=owner, language=language, source_lang=source_lang,
            theme=theme, level=level,
        ).values_list('gloss', flat=True))

        created = skipped = failed = 0
        for rank, gloss in enumerate(strings, start=1):
            if gloss in existing:
                skipped += 1
                continue

            result = translator.translate(
                gloss, target_lang=language.code, source_lang=source_lang,
            )
            translation = (result.get('translation') or '').strip()
            backend = result.get('backend') or ''
            err = result.get('error') or ''

            if err or not translation:
                self.stderr.write(self.style.WARNING(
                    f'  [{rank:3}] {gloss!r}: {err or "empty"}'
                ))
                translation = ''
                failed += 1

            pron = _romanise(translation, language.code)
            FlashCard.objects.create(
                user=owner,
                language=language,
                source_lang=source_lang,
                lemma=translation,
                pronunciation=pron,
                gloss=gloss,
                freq_rank=rank if not theme else None,
                backend=backend,
                theme=theme,
                level=level,
            )
            created += 1
            if translation:
                tail = f'  [{pron}]' if pron else ''
                self.stdout.write(f'  [{rank:3}] {gloss}  →  {translation}{tail}')
        return created, skipped, failed

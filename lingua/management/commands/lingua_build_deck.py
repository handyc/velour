"""Build a FlashCard deck for a target language.

Usage:
    manage.py lingua_build_deck --lang nl --size 100 [--user alice]

Reads the bundled English frequency list at `lingua/data/freq_en.txt`,
takes the first N words, routes each through `translator.translate()`
(Argos by default, falling back through the backend registry) and
creates one FlashCard row per word for the given user.

The per-word translations also land in the TranslationCache for free,
so hover translations of the same words elsewhere will be instant
cache hits afterwards.

If no `--user` is given, defaults to the first superuser — on a
single-tenant Velour this is normally the operator.

Skips words already in the user's deck for this language (by gloss),
so re-running with a larger `--size` extends the deck instead of
duplicating it.
"""
from __future__ import annotations

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from lingua import translator
from lingua.models import FlashCard, Language


FREQ_PATH = Path(__file__).resolve().parents[2] / 'data' / 'freq_en.txt'


def _romanise(text: str, lang_code: str) -> str:
    """Optional transliteration of a translated word. Returns '' if we
    don't have a converter for this language or the import fails — the
    flashcard just shows no pronunciation line in that case.

    Currently only Chinese (zh / zh-Hans / zh-Hant) via pypinyin, since
    pinyin is the one transliteration where most learners really do
    need it alongside the glyphs. Japanese would want kuroshiro + a
    kanji dictionary — left for later."""
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


class Command(BaseCommand):
    help = 'Build a flashcard deck for a target language from the bundled frequency list.'

    def add_arguments(self, parser):
        parser.add_argument('--lang',  required=True,
                            help='Target language code (e.g. nl, fr, zh-Hans).')
        parser.add_argument('--size',  type=int, default=100,
                            help='How many words to include (from the top of the list).')
        parser.add_argument('--user',  default=None,
                            help='Username to assign cards to (default: first superuser).')
        parser.add_argument('--source-lang', default='en',
                            help='Source language code (default: en).')

    def handle(self, *args, lang, size, user, source_lang, **opts):
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

        if not FREQ_PATH.exists():
            raise CommandError(f'frequency list missing: {FREQ_PATH}')

        words = []
        for line in FREQ_PATH.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            words.append(line)
        words = words[:size]

        existing = set(FlashCard.objects.filter(
            user=owner, language=language, source_lang=source_lang,
        ).values_list('gloss', flat=True))

        created = 0
        skipped = 0
        failed = 0
        for rank, gloss in enumerate(words, start=1):
            if gloss in existing:
                skipped += 1
                continue

            result = translator.translate(gloss, target_lang=lang,
                                          source_lang=source_lang)
            translation = (result.get('translation') or '').strip()
            backend = result.get('backend') or ''
            err = result.get('error') or ''

            if err or not translation:
                self.stderr.write(self.style.WARNING(
                    f'  [{rank:3}] {gloss!r}: {err or "empty"}'
                ))
                # Still create the card so the user can hand-edit later.
                translation = ''
                failed += 1

            pron = _romanise(translation, lang)
            FlashCard.objects.create(
                user=owner,
                language=language,
                source_lang=source_lang,
                lemma=translation,
                pronunciation=pron,
                gloss=gloss,
                freq_rank=rank,
                backend=backend,
            )
            created += 1
            if translation:
                tail = f'  [{pron}]' if pron else ''
                self.stdout.write(f'  [{rank:3}] {gloss}  →  {translation}{tail}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'deck built for {owner.username} / {language.name}: '
            f'{created} new, {skipped} already present, {failed} without translation.'
        ))

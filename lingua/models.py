"""Lingua models — central translation cache + per-user language prefs.

Design goals:

- The cache is project-wide. Every app hits the same table, so we
  avoid the 5000-translations-per-app bloat the user flagged. Keys
  are sha1(source_text) + source_lang + target_lang — same sentence
  rendered in 40 different templates is cached once.

- Low-resource languages (Ancient Greek, Sanskrit, etc.) are served
  by an LLM backend. High-resource languages can be too, or can
  plug in cheaper backends later via the same adapter registry.

- Prefs are per-user and ordered. The editor language is always
  the primary fallback; `priority_codes` is the list the user
  actually wants to see. Intentionally JSON-encoded, not a M2M,
  so reorder is a single write and the shape stays flexible.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import models
from django.utils import timezone as djtz


SCRIPT_CHOICES = [
    ('latin',      'Latin'),
    ('cyrillic',   'Cyrillic'),
    ('greek',      'Greek'),
    ('hebrew',     'Hebrew'),
    ('arabic',     'Arabic'),
    ('devanagari', 'Devanagari'),
    ('han',        'Han'),
    ('hiragana',   'Hiragana + kanji'),
    ('hangul',     'Hangul'),
    ('other',      'Other'),
]


def source_hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode('utf-8')).hexdigest()


class Language(models.Model):
    """One row per language we know how to translate into or from.

    `code` is the canonical identifier Lingua uses end-to-end. We
    prefer BCP-47 subtags where they exist (`nl`, `zh-Hans`, `ja`)
    and fall back to ISO-639-3 for languages that lack a BCP-47
    short form (`grc` for Ancient Greek, `san` for Sanskrit).
    """

    code          = models.CharField(max_length=16, unique=True)
    name          = models.CharField(max_length=80)
    endonym       = models.CharField(max_length=80, blank=True,
                        help_text="How speakers write the name in the language itself.")
    script        = models.CharField(max_length=16, choices=SCRIPT_CHOICES, default='latin')
    rtl           = models.BooleanField(default=False)
    low_resource  = models.BooleanField(default=False,
                        help_text="Translation quality may be uneven; LLM backend recommended.")
    notes         = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'


class TranslationCache(models.Model):
    """One cached (source, source_lang, target_lang) → translation row.

    We store the source text inline (not just the hash) so the admin
    can audit the cache without walking upstream. `hit_count` and
    `last_hit_at` power the LRU prune command.
    """

    source_hash        = models.CharField(max_length=40, db_index=True)
    source_text        = models.TextField()
    source_lang        = models.CharField(max_length=16, default='en')
    target_lang        = models.CharField(max_length=16)
    translation        = models.TextField()
    backend            = models.CharField(max_length=32,
                            help_text="Adapter that produced this row (e.g. 'claude', 'manual').")
    confidence         = models.FloatField(default=0.0,
                            help_text="Self-reported 0.0–1.0. LLM backends default to 0.8.")
    reviewed_by_human  = models.BooleanField(default=False)
    tokens_in          = models.PositiveIntegerField(default=0)
    tokens_out         = models.PositiveIntegerField(default=0)
    hit_count          = models.PositiveIntegerField(default=0)
    last_hit_at        = models.DateTimeField(null=True, blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('source_hash', 'source_lang', 'target_lang')]
        indexes = [
            models.Index(fields=['target_lang', 'last_hit_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        head = self.source_text[:40].replace('\n', ' ')
        return f'{self.source_lang}→{self.target_lang}: {head}'


class UserLanguagePreference(models.Model):
    """Per-user ordered priority list + toggles.

    priority_codes is a JSON list of Language.code strings. The first
    entry is the primary target; later entries are fallbacks for
    menus / secondary display.
    """

    user             = models.OneToOneField(settings.AUTH_USER_MODEL,
                          on_delete=models.CASCADE,
                          related_name='lingua_pref')
    priority_codes   = models.JSONField(default=list)
    auto_translate   = models.BooleanField(default=False,
                          help_text="If set, the hover tooltip is active on every page.")
    hover_modifier   = models.CharField(max_length=8, default='alt',
                          choices=[('alt','Alt'), ('ctrl','Ctrl'), ('shift','Shift'), ('none','None')],
                          help_text="Modifier key that must be held for the hover tooltip.")
    updated_at       = models.DateTimeField(auto_now=True)

    def primary_code(self) -> str:
        if self.priority_codes:
            return self.priority_codes[0]
        return ''

    def __str__(self):
        return f'{self.user}: {",".join(self.priority_codes) or "—"}'


# Leitner intervals in days, indexed by box number. Box 0 = "new / just
# failed": due immediately. Boxes climb to ~month spacing by box 6. The
# choice is deliberately rough (not SM-2) — scholars can grade nuance
# later; early on we just want each word to resurface periodically.
LEITNER_INTERVAL_DAYS = [0, 1, 2, 4, 8, 16, 32]


LEVEL_CHOICES = [
    ('word',     'Single word'),
    ('phrase',   'Phrase'),
    ('sentence', 'Full sentence'),
]


class FlashCard(models.Model):
    """One word/phrase/sentence the user is learning, stored per-user.

    `lemma` holds the string in the target language (what the user is
    trying to recognise). `gloss` holds the meaning in `source_lang`
    (usually English). `lingua_build_deck` populates `lemma` by running
    a bundled source-language wordlist through the translator.

    Cards cluster into decks via `(language, theme, level)`. `theme` is
    a slug like `body_parts` or empty (the general frequency deck).
    `level` distinguishes single words from phrases from full sentences,
    so the UI can render them differently (longer content gets smaller
    type and smarter wrapping).

    Per-user so two people sharing a Velour deploy can progress at
    their own pace and mark different cards as known.
    """

    user          = models.ForeignKey(settings.AUTH_USER_MODEL,
                        on_delete=models.CASCADE,
                        related_name='lingua_cards')
    language      = models.ForeignKey(Language,
                        on_delete=models.CASCADE,
                        related_name='flashcards',
                        help_text='Target language — the one being learned.')
    source_lang   = models.CharField(max_length=16, default='en')
    lemma         = models.CharField(max_length=400,
                        help_text='Word/phrase/sentence in the target language.')
    pronunciation = models.CharField(max_length=400, blank=True,
                        help_text='Romanisation / transliteration (e.g. pinyin for zh, romaji for ja).')
    gloss         = models.CharField(max_length=400, blank=True,
                        help_text='Meaning in source_lang (usually English).')
    example_src   = models.TextField(blank=True)
    example_trg   = models.TextField(blank=True)
    freq_rank     = models.PositiveIntegerField(null=True, blank=True,
                        help_text='Rank in the source frequency list (1 = most common).')
    backend       = models.CharField(max_length=32, blank=True,
                        help_text='Which adapter produced the translation.')
    theme         = models.CharField(max_length=60, blank=True, default='',
                        help_text='Theme slug, e.g. "body_parts". Empty = general deck.')
    level         = models.CharField(max_length=16, default='word',
                        choices=LEVEL_CHOICES,
                        help_text='word / phrase / sentence — controls rendering.')

    leitner_box   = models.PositiveSmallIntegerField(default=0)
    due_at        = models.DateTimeField(default=djtz.now)
    last_seen_at  = models.DateTimeField(null=True, blank=True)
    review_count  = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)

    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ('user', 'language', 'gloss', 'source_lang', 'theme', 'level'),
        ]
        indexes = [
            models.Index(fields=['user', 'language', 'due_at']),
            models.Index(fields=['user', 'language', 'theme', 'level']),
        ]
        ordering = ['due_at', 'freq_rank']

    def __str__(self):
        return f'{self.lemma} ({self.language.code}) → {self.gloss}'

    def promote(self):
        import datetime as _dt
        self.correct_count += 1
        self.review_count  += 1
        self.leitner_box = min(self.leitner_box + 1, len(LEITNER_INTERVAL_DAYS) - 1)
        delta = _dt.timedelta(days=LEITNER_INTERVAL_DAYS[self.leitner_box])
        self.due_at = djtz.now() + delta
        self.last_seen_at = djtz.now()

    def demote(self):
        self.review_count += 1
        self.leitner_box = 0
        self.due_at = djtz.now()
        self.last_seen_at = djtz.now()

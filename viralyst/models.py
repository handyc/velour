"""Viralyst — guided IDE for very small historical programs (<64 KB).

Phase 1 scope: source-only catalogue. Three models — Corpus (where the
sample came from), Language (what it's written in), Sample (one program).
No virus binaries are stored; if `kind == 'virus'` the row is purely a
historical pointer and `source_code` carries an academic reconstruction
or sanitized excerpt.

Byte-size and line-count are computed on the fly from `source_code`
(plus `binary_size_bytes` if the contributor knows the original
artifact's stripped binary size — DOS .COM, ELF after `strip`, etc.).
We don't store opcode histograms or any other expensive analysis yet;
that's Phase 2.
"""

from __future__ import annotations

from django.db import models


KIND_CHOICES = [
    ('quine',    'Quine / self-reproducing'),
    ('virus',    'Virus (source / reconstruction only)'),
    ('worm',     'Worm (source / reconstruction only)'),
    ('utility',  'Classic utility (DOS/Unix)'),
    ('demo',     'Demo / intro'),
    ('runtime',  'Tiny runtime / language core'),
    ('golf',     'Code-golf entry'),
    ('snippet',  'Library snippet / idiom'),
    ('other',    'Other'),
]

LANGUAGE_FAMILY_CHOICES = [
    ('asm',      'Assembly'),
    ('c',        'C / C++'),
    ('forth',    'Forth'),
    ('lisp',     'Lisp / Scheme'),
    ('basic',    'BASIC'),
    ('shell',    'Shell / bash'),
    ('script',   'Perl / Python / Ruby / Tcl'),
    ('esoteric', 'Esoteric (BF, BLC, subleq…)'),
    ('other',    'Other'),
]

TIER_CHOICES = [
    ('sub_512b', '≤ 512 bytes'),
    ('sub_4k',   '≤ 4 KB'),
    ('sub_64k',  '≤ 64 KB'),
    ('any',      'No tight bound'),
]


class Corpus(models.Model):
    """One archive / origin source (vx-underground, IOCCC, Madore quines…).

    The license_summary field is human-prose, not enum — every archive
    has its own redistribution caveats and we'd rather store them
    verbatim than try to taxonomize."""

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160)
    url = models.URLField(blank=True)
    license_summary = models.CharField(
        max_length=240, blank=True,
        help_text='Short human-readable license statement, e.g. '
                  '"MIT (Microsoft GitHub release)" or '
                  '"academic-only; sources extracted from public archive".')
    notes_md = models.TextField(
        blank=True,
        help_text='Markdown notes on how to harvest this corpus, '
                  'gotchas, what subset is in scope here.')
    is_quarantined = models.BooleanField(
        default=False,
        help_text='If true, samples from this corpus need an explicit '
                  'researcher gate before they render. Phase 2 feature; '
                  'set on virus/worm corpora when we add them.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'corpora'

    def __str__(self):
        return self.name


class Language(models.Model):
    """A language or dialect a sample is written in.

    `tier` records the smallest binary class the language is associated
    with (sectorforth → sub_512b, GW-BASIC → sub_64k, etc.) so the
    index page can sort/filter on "what languages target the smallest
    binaries"."""

    slug = models.SlugField(unique=True, max_length=60)
    name = models.CharField(max_length=80)
    family = models.CharField(
        max_length=12, choices=LANGUAGE_FAMILY_CHOICES, default='other')
    tier = models.CharField(
        max_length=10, choices=TIER_CHOICES, default='any')
    notes_md = models.TextField(
        blank=True,
        help_text='What this language is interesting for in viralyst — '
                  'the trick that makes it produce small binaries, the '
                  'historical context, where to learn it.')

    class Meta:
        ordering = ['family', 'name']

    def __str__(self):
        return self.name


class Sample(models.Model):
    """One historical program."""

    slug = models.SlugField(unique=True, max_length=120)
    name = models.CharField(max_length=200)
    corpus = models.ForeignKey(
        Corpus, on_delete=models.PROTECT, related_name='samples')
    language = models.ForeignKey(
        Language, on_delete=models.PROTECT, related_name='samples')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    year = models.IntegerField(
        null=True, blank=True,
        help_text='Year the program was published or first widely seen.')
    author = models.CharField(
        max_length=200, blank=True,
        help_text='Free-text author/team. Leave blank for anonymous.')
    origin_url = models.URLField(
        blank=True,
        help_text='Permalink to the canonical version (GitHub commit, '
                  'archive.org item, museum page).')
    license_override = models.CharField(
        max_length=160, blank=True,
        help_text='If the sample has a different licence to its corpus '
                  '(e.g. one MIT file inside an otherwise-shareware CD), '
                  'state it here. Otherwise leave blank.')
    source_code = models.TextField(
        help_text='The full source — text only. Phase 1 stores no binaries.')
    binary_size_bytes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Original artifact size if known (DOS .COM size, '
                  'stripped ELF size, .EXE size). Independent of '
                  'source-code length.')
    notes_md = models.TextField(
        blank=True,
        help_text='Markdown commentary — the "guided" part. What trick '
                  'is the program using? What was the era? Why look at '
                  'this one? Renders above the source on the detail page.')
    is_quarantined = models.BooleanField(
        default=False,
        help_text='Set on samples that the researcher gate should hide '
                  'until opted in. Default off — Phase 1 only seeds '
                  'public-domain / permissive sources.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.language.name})'

    @property
    def source_bytes(self) -> int:
        return len(self.source_code.encode('utf-8'))

    @property
    def n_lines(self) -> int:
        return self.source_code.count('\n') + (
            0 if self.source_code.endswith('\n') or not self.source_code else 1)

    @property
    def longest_line(self) -> int:
        return max((len(r) for r in self.source_code.splitlines()), default=0)

    @property
    def licence(self) -> str:
        return self.license_override or self.corpus.license_summary or '—'

    @property
    def runner(self) -> str:
        """Which in-page runner (if any) can execute this sample.

        Phase 2 starts with Brainfuck (pure JS, no server compile).
        Returning '' means "no runner; this stays a museum piece."
        Adding a language here is enough to make samples in that
        language runnable — sample_detail.html branches on this."""
        return {
            'brainfuck': 'bf',
        }.get(self.language.slug, '')

    @property
    def is_runnable(self) -> bool:
        return bool(self.runner)

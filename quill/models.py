"""Quill — Mellel-style word processor data model.

Mellel's discipline is *structure-first*: a document is an ordered
hierarchy of Sections whose appearance is governed by named Styles, not
by ad-hoc inline formatting. We mirror that on the server so cross-
references, footnotes, and outline operations stay first-class.

Tables:

- Document — the bound artefact. Has an owner, slug, and tracks updated_at.
- Style — a named paragraph or character style scoped to one Document.
  CSS rules live in a JSONField so the editor can render them and the
  PDF/DOCX exporter can translate them later.
- Section — one node in the document's outline. Optional parent, order
  within its siblings, level (cached for fast outline rendering), title,
  body (HTML for now; the structure is ProseMirror-shaped so the editor
  can be swapped in without a migration).
- Footnote — anchored to a section, ordered, body HTML.
- CrossReference — source section pointing to a target section. Label
  is computed at render time, but cached for export.

Hierarchy is single-table self-FK. We prefer that over MPTT for Phase 1
because the documents we expect (essays, manuals, theses) rarely exceed
a few hundred sections — recursion is fine, indexes are simple.
"""

from django.db import models
from django.utils.text import slugify


STYLE_KIND_CHOICES = [
    ('paragraph', 'Paragraph'),
    ('character', 'Character'),
    ('list',      'List'),
]

DIRECTION_CHOICES = [
    ('ltr',  'LTR (left-to-right)'),
    ('rtl',  'RTL (right-to-left)'),
    ('auto', 'Auto (browser detects from first strong char)'),
]


class Language(models.Model):
    """A research language with script, direction, and font hints.

    Mellel-style multilingual support: each Language carries a BCP-47
    code, a writing direction, and a CSS font stack tuned for its
    script. Documents pick the languages they care about (via
    DocumentLanguage), and the editor surfaces a toolbar of those for
    quick switching while typing.

    The ``font_stack`` strings are CSS-ready font-family lists. We
    don't ship the fonts; users see the best fallback their system
    has installed (Noto Sans is the safest cross-platform default for
    most non-Latin scripts).
    """

    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(
        max_length=80,
        help_text='English name — "Sanskrit", "Tibetan", "Hebrew".',
    )
    native_name = models.CharField(
        max_length=80, blank=True,
        help_text='Endonym in its own script — "संस्कृतम्", "བོད་སྐད་", "עברית".',
    )
    bcp47 = models.CharField(
        max_length=20,
        help_text='BCP-47 tag — "en", "nl", "sa", "bo", "zh-Hans", "he", "ar".',
    )
    direction = models.CharField(
        max_length=4, choices=[('ltr', 'LTR'), ('rtl', 'RTL')], default='ltr',
    )
    script_name = models.CharField(
        max_length=40, blank=True,
        help_text='Script family — "Latin", "Devanagari", "Tibetan", '
                  '"Han", "Hebrew", "Arabic", "Syriac", "Greek".',
    )
    font_stack = models.CharField(
        max_length=400, blank=True,
        help_text='CSS font-family list. Longer stacks fall back gracefully '
                  'across systems where users may have different fonts.',
    )
    sample_text = models.CharField(
        max_length=200, blank=True,
        help_text='A short sample for the language picker — usually a '
                  'pangram or characteristic phrase.',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Document(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    owner = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quill_documents',
    )
    primary_language = models.ForeignKey(
        Language, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='primary_documents',
        help_text='Default language for new sections. Drives the page\'s '
                  'overall direction and base font stack.',
    )
    languages = models.ManyToManyField(
        Language, through='DocumentLanguage', related_name='documents',
        blank=True,
        help_text='Languages enabled in this document\'s toolbar.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:300] or 'document'
            candidate, n = base, 2
            while Document.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('quill:detail', args=[self.slug])

    def root_sections(self):
        return self.sections.filter(parent__isnull=True).order_by('order', 'pk')

    def section_count(self):
        return self.sections.count()

    def word_count(self):
        from django.db.models import Sum
        # Approximate — counts whitespace-separated tokens in each body.
        # Cheaper than HTML stripping; close enough for the list page.
        total = 0
        for body in self.sections.values_list('body', flat=True):
            total += len((body or '').split())
        return total


class Style(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name='styles',
    )
    name = models.CharField(max_length=80)
    kind = models.CharField(
        max_length=20, choices=STYLE_KIND_CHOICES, default='paragraph',
    )
    css_rules = models.JSONField(
        default=dict, blank=True,
        help_text='{"font_family": "Charter", "font_size": "11pt", '
                  '"line_height": 1.45, "margin_top": "0.5em", ...}',
    )

    class Meta:
        ordering = ['kind', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'name'], name='quill_style_name_per_doc',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_kind_display()})'

    def as_inline_css(self):
        """Translate css_rules → an inline-style snippet for the editor."""
        rules = self.css_rules or {}
        out = []
        for k, v in rules.items():
            css_key = k.replace('_', '-')
            out.append(f'{css_key}: {v}')
        return '; '.join(out)


class Section(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name='sections',
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children',
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text='Position among siblings — smaller comes first.',
    )
    level = models.PositiveSmallIntegerField(
        default=1,
        help_text='Outline depth, cached. Top-level = 1.',
    )
    title = models.CharField(max_length=300, blank=True)
    style = models.ForeignKey(
        Style, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sections',
    )
    primary_language = models.ForeignKey(
        Language, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='primary_sections',
        help_text='The section\'s default language — drives its block '
                  'direction and base font stack. Inline spans can switch '
                  'to other languages.',
    )
    paragraph_direction = models.CharField(
        max_length=4, choices=DIRECTION_CHOICES, default='ltr',
        help_text='Block writing direction. RTL languages set this to '
                  '"rtl" by default; "auto" lets the browser decide from '
                  'first strong character.',
    )
    body = models.TextField(
        blank=True,
        help_text='HTML body. Inline language switches are encoded as '
                  '<span lang="..." dir="...">...</span> — web standard, '
                  'survives ProseMirror migration.',
    )

    class Meta:
        ordering = ['order', 'pk']
        indexes = [
            models.Index(fields=['document', 'parent', 'order']),
        ]

    def __str__(self):
        return self.title or f'§{self.pk}'

    def descendants(self):
        out = []
        stack = list(self.children.all().order_by('order', 'pk'))
        while stack:
            node = stack.pop(0)
            out.append(node)
            stack[0:0] = list(node.children.all().order_by('order', 'pk'))
        return out


class Footnote(models.Model):
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='footnotes',
    )
    order = models.PositiveIntegerField(default=0)
    body = models.TextField(blank=True)

    class Meta:
        ordering = ['section', 'order', 'pk']

    def __str__(self):
        return f'fn {self.order} on §{self.section_id}'


class CrossReference(models.Model):
    source = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='outgoing_refs',
    )
    target = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='incoming_refs',
    )
    label = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['source', 'pk']

    def __str__(self):
        return f'§{self.source_id} → §{self.target_id}'


class DocumentLanguage(models.Model):
    """Through model for Document.languages — preserves toolbar order.

    A document subscribes to a subset of the global Language registry.
    The toolbar shows them in the user-chosen order, with hotkeys
    Cmd/Ctrl+1..9 mapped to the first nine entries.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    language = models.ForeignKey(Language, on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'language'],
                name='quill_doc_lang_unique',
            ),
        ]

    def __str__(self):
        return f'{self.document_id}:{self.language.slug}@{self.order}'

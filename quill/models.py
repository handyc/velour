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


class Document(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    owner = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quill_documents',
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
    body = models.TextField(
        blank=True,
        help_text='HTML body. ProseMirror-ready: structure carried in '
                  'tags + class names, no inline styling beyond what a '
                  'Style covers.',
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

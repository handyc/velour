"""Codex — Velour's documentation system.

A `Manual` is a top-level document. A `Section` is a chapter or
sub-chapter of a manual; sections have a markdown body and an
optional bag of sidenotes that the renderer hangs in the right
margin alongside the section's body. A `Figure` is an image or
generated diagram embedded in a section by a `!fig:slug` reference.

Phase 1: flat sections, paragraphs + headings + lists, PDF via
fpdf2 with built-in Times.

Phase 2 (current): ET Book font, inline sidenote anchors via
`^[note]` syntax, figures with margin captions, Mermaid diagrams
generated via Kroki.

Phase 3 (planned): parent/child sections (chapters), tables,
sparklines, callout/admonition blocks.
"""

import hashlib

from django.core.files.base import ContentFile
from django.db import models
from django.utils.text import slugify


FORMAT_CHOICES = [
    ('quickstart', 'Quickstart (1 page, diagrams welcome)'),
    ('short',      'Short (10–15 pages)'),
    ('complete',   'Complete (full manual, ~256 pages)'),
]


class Manual(models.Model):
    """One document. Has a title page and a sequence of Sections.

    `format` is a hint to the renderer about page count expectations
    — it doesn't enforce anything, but the title page treatment and
    a few layout choices key off it.
    """

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subtitle = models.CharField(max_length=300, blank=True)
    format = models.CharField(
        max_length=16, choices=FORMAT_CHOICES, default='short',
    )
    author = models.CharField(max_length=200, default='Velour')
    version = models.CharField(max_length=32, blank=True, default='0.1')
    abstract = models.TextField(
        blank=True,
        help_text='Optional. Renders below the title on the cover page.',
    )
    double_spaced = models.BooleanField(
        default=False,
        help_text='Off by default — Tufte\'s preferred ~1.27 leading is '
                  'more readable in long form. Turn on for manuscript-style '
                  'output.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_built_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base = slugify(self.title)[:200] or 'manual'
            candidate = base
            n = 2
            while Manual.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def section_count(self):
        return self.sections.count()


class Section(models.Model):
    """A chapter or sub-chapter of a manual.

    `body` is markdown (subset: # ## ### headings, paragraphs, bullet
    lines starting with "- ", inline **bold** and *italic*).

    `sidenotes` is one note per line. The renderer stacks them in
    the right margin at the start of the section's body, in the
    order they appear.
    """

    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='sections',
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    body = models.TextField(
        blank=True,
        help_text='Markdown. Headings (# ## ###), paragraphs, "- " bullets, '
                  '**bold**, *italic*.',
    )
    sidenotes = models.TextField(
        blank=True,
        help_text='One per line. Rendered in the right margin alongside '
                  'this section.',
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['manual', 'slug'],
                name='codex_unique_section_slug_per_manual',
            ),
        ]

    def __str__(self):
        return f'{self.manual.title} / {self.title}'

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base = slugify(self.title)[:200] or 'section'
            candidate = base
            n = 2
            while Section.objects.filter(
                manual=self.manual_id, slug=candidate,
            ).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def sidenote_list(self):
        """Return sidenotes as a list of stripped non-empty lines."""
        return [ln.strip() for ln in self.sidenotes.splitlines() if ln.strip()]


FIGURE_KIND_CHOICES = [
    ('image',   'Uploaded image (PNG/JPG/SVG)'),
    ('mermaid', 'Mermaid diagram (rendered via Kroki)'),
]


class Figure(models.Model):
    """An image or generated diagram embedded in a Section.

    Two kinds:
      - 'image':   uploaded by the user, stored in `image`.
      - 'mermaid': source kept in `source`, rendered to PNG via the
                   Kroki HTTP API on save (and re-rendered when the
                   source text changes), with the resulting PNG
                   cached in `image`.

    Embedded in section bodies by writing `!fig:slug` on its own
    line; the renderer looks the slug up in the section's figures
    and inserts the image inline with the caption hanging in the
    right margin.
    """

    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='figures',
    )
    slug = models.SlugField(
        max_length=120,
        help_text='Stable identifier referenced from section bodies as '
                  '`!fig:<slug>`.',
    )
    kind = models.CharField(
        max_length=16, choices=FIGURE_KIND_CHOICES, default='image',
    )
    image = models.FileField(upload_to='codex/figures/', blank=True)
    source = models.TextField(
        blank=True,
        help_text='For Mermaid figures: the diagram source. Re-rendered '
                  'whenever this text changes.',
    )
    source_hash = models.CharField(max_length=64, blank=True)
    caption = models.TextField(
        blank=True,
        help_text='Hangs in the right margin alongside the figure.',
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['section', 'slug'],
                name='codex_unique_figure_slug_per_section',
            ),
        ]

    def __str__(self):
        return f'{self.section}: {self.slug} ({self.kind})'

    def save(self, *args, **kwargs):
        if self.kind == 'mermaid' and self.source.strip():
            new_hash = hashlib.sha256(
                self.source.strip().encode('utf-8')
            ).hexdigest()[:32]
            if new_hash != self.source_hash or not self.image:
                # Re-render via Kroki. Import locally so the model
                # module doesn't depend on the rendering layer at
                # import time.
                from .rendering.diagrams import render_mermaid_to_png
                png = render_mermaid_to_png(self.source)
                if png:
                    self.image.save(
                        f'{self.slug or "diagram"}.png',
                        ContentFile(png),
                        save=False,
                    )
                    self.source_hash = new_hash
        super().save(*args, **kwargs)

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
    bibliography = models.TextField(
        blank=True,
        help_text='BibTeX source. Cite entries from section bodies with '
                  '`[@key]` or `[@key, p. 42]`. Cited entries render in a '
                  'References section at the end of the PDF.',
    )

    # Edition metadata — if any of these are set, a colophon page is
    # inserted as page 2 (verso of the title page). All blank → no
    # colophon, no change to the output.
    edition = models.CharField(
        max_length=80, blank=True,
        help_text='e.g. "First edition" or "Second revised edition".',
    )
    isbn = models.CharField(max_length=20, blank=True)
    doi  = models.CharField(max_length=120, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    publisher_city = models.CharField(max_length=120, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    copyright_year = models.CharField(
        max_length=16, blank=True,
        help_text='Free text — typically a year or range like "2020–2026".',
    )
    copyright_holder = models.CharField(
        max_length=200, blank=True,
        help_text='Defaults to the manual\'s author if blank at render time.',
    )
    license = models.CharField(
        max_length=200, blank=True,
        help_text='e.g. "All rights reserved." or "CC BY-SA 4.0".',
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


# Every non-'image' kind is a Kroki language name — the value is POSTed
# to kroki.io/<kind>/png verbatim. Adding a kind: append a row here and
# nothing else (Figure.save dispatches uniformly).
FIGURE_KIND_CHOICES = [
    ('image',       'Uploaded image (PNG/JPG/SVG)'),
    ('svg',         'Raw SVG — paste / export from Inkscape, KiCad'),
    ('mermaid',     'Mermaid — flowcharts / sequences / state'),
    ('graphviz',    'Graphviz (DOT) — directed graphs, wiring'),
    ('plantuml',    'PlantUML — UML, sequence, architecture'),
    ('d2',          'D2 — modern architecture diagrams'),
    ('blockdiag',   'BlockDiag — block topology'),
    ('nwdiag',      'NwDiag — network topology'),
    ('packetdiag',  'PacketDiag — wire packet layout'),
    ('rackdiag',    'RackDiag — server rack elevation'),
    ('erd',         'ERD — entity-relationship'),
    ('ditaa',       'Ditaa — ASCII art → polished'),
    ('svgbob',      'SvgBob — ASCII art → SVG'),
    ('wireviz',     'WireViz — cable harnesses'),
    ('bytefield',   'Bytefield — byte / register layout'),
    ('wavedrom',    'WaveDrom — timing diagrams'),
    ('excalidraw',  'Excalidraw — hand-drawn style'),
    ('nomnoml',     'Nomnoml — simple UML sketches'),
    ('pikchr',      'Pikchr — compact diagrams'),
    ('vegalite',    'Vega-Lite — data charts'),
    ('bpmn',        'BPMN — business process'),
    ('tikz',        'TikZ — LaTeX diagrams'),
]

CAPTION_POSITION_CHOICES = [
    ('margin', 'In the right margin (Tufte default)'),
    ('below',  'Underneath the figure (academic style)'),
]


class ReportRecipe(models.Model):
    """A recipe for generating a periodic Codex manual from contributions.

    Each recipe specifies a list of contributor app slugs (in order),
    a time window in days, and metadata for the resulting manual. The
    `build_report` management command walks the contributors and
    composes the result into a Manual row that can be re-rendered to
    PDF on demand.

    Phase 1 supports user-defined recipes seeded with one default
    weekly recipe. Phase 2 will add cron-driven scheduling and email
    delivery via the mailboxes app.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    contributors = models.CharField(
        max_length=500,
        help_text='Comma-separated list of contributor slugs '
                  '(matching modules in codex/contributions/), in '
                  'the order they should appear in the report.',
    )
    period_days = models.IntegerField(
        default=7,
        help_text='How many days back the report covers.',
    )
    enabled = models.BooleanField(default=True)
    output_manual_slug = models.SlugField(
        max_length=160, blank=True,
        help_text='Slug of the Manual produced by build_report. '
                  'Auto-derived from the recipe slug if blank.',
    )
    last_built_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def output_slug(self):
        return self.output_manual_slug or f'report-{self.slug}'

    @property
    def contributor_list(self):
        return [c.strip() for c in self.contributors.split(',') if c.strip()]


class Volume(models.Model):
    """A bound collection of Manuals rendered into one PDF.

    Each VolumeManual row pins one Manual into the Volume with a
    sort order. The Volume's PDF is produced by rendering each Manual
    individually (via the usual Tufte renderer) and stitching the
    resulting PDFs together with pypdf, prefixed by a Volume title
    page + table of contents.
    """

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subtitle = models.CharField(max_length=300, blank=True)
    author = models.CharField(max_length=200, default='Velour')
    version = models.CharField(max_length=32, blank=True, default='0.1')
    abstract = models.TextField(blank=True)
    manuals = models.ManyToManyField(
        'Manual', through='VolumeManual', related_name='volumes',
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
            base = slugify(self.title)[:200] or 'volume'
            candidate = base
            n = 2
            while Volume.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class VolumeManual(models.Model):
    volume = models.ForeignKey(Volume, on_delete=models.CASCADE, related_name='entries')
    manual = models.ForeignKey(Manual, on_delete=models.CASCADE)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['volume', 'manual'],
                name='codex_unique_manual_per_volume',
            ),
        ]

    def __str__(self):
        return f'{self.volume.title} / {self.manual.title}'


class Figure(models.Model):
    """An image or generated diagram embedded in a Section.

    Either:
      - 'image': uploaded by the user, stored in `image`.
      - any Kroki language (mermaid, graphviz, plantuml, d2, ...):
        source kept in `source`, rendered to PNG via Kroki on save
        (and re-rendered when the source text changes), with the
        resulting PNG cached in `image`.

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
        help_text='Caption text. Where it appears is controlled by '
                  'caption_position.',
    )
    caption_position = models.CharField(
        max_length=8, choices=CAPTION_POSITION_CHOICES, default='margin',
        help_text='Margin = the Tufte default (caption hangs in the '
                  'right sidenote area). Below = academic style with '
                  'a "Figure N: …" caption underneath the image.',
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
        if self.kind != 'image' and self.source.strip():
            new_hash = hashlib.sha256(
                self.source.strip().encode('utf-8')
            ).hexdigest()[:32]
            if new_hash != self.source_hash or not self.image:
                # Local import: the model module stays independent of
                # the rendering layer at import time.
                from .rendering.diagrams import render_diagram_to_png
                png = render_diagram_to_png(self.source, kind=self.kind)
                if png:
                    self.image.save(
                        f'{self.slug or "diagram"}.png',
                        ContentFile(png),
                        save=False,
                    )
                    self.source_hash = new_hash
        super().save(*args, **kwargs)

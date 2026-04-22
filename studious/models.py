"""Studious — scholar library + argument workshop.

Ingest a scholar's work (URL scrape, PDF upload, raw paste), extract
candidate claims, and scaffold new arguments that braid claims across
scholars. Deterministic Phase 1: TF-IDF for distinguishing terms,
heuristic sentence extraction for claim candidates, template-based
argument scaffolds. LLM rephrasing is a Phase 2 toggle — see
:mod:`studious.analysis` for where it would slot in.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify


WORK_KINDS = [
    ('article',  'Article'),
    ('book',     'Book'),
    ('chapter',  'Chapter'),
    ('thesis',   'Thesis / dissertation'),
    ('preprint', 'Preprint'),
    ('talk',     'Talk / lecture'),
    ('note',     'Note / letter'),
    ('other',    'Other'),
]

CLAIM_KINDS = [
    ('claim',       'Claim'),
    ('thesis',      'Main thesis'),
    ('observation', 'Observation'),
    ('question',    'Open question'),
    ('hedge',       'Hedge / caveat'),
    ('counter',     'Counter / objection'),
]

ARGUMENT_KINDS = [
    ('across', 'Across scholars'),
    ('within', 'Within one scholar'),
    ('essay',  'Free-form essay'),
]

ARGUMENT_ROLES = [
    ('premise',      'Premise'),
    ('support',      'Support'),
    ('counter',      'Counter'),
    ('illustration', 'Illustration'),
    ('context',      'Context'),
]


class Scholar(models.Model):
    name         = models.CharField(max_length=200)
    slug         = models.SlugField(max_length=80, unique=True)
    affiliation  = models.CharField(max_length=200, blank=True)
    active_years = models.CharField(max_length=40, blank=True,
                    help_text='e.g. "1960–1992" or "active"')
    homepage_url = models.URLField(max_length=500, blank=True)
    bio          = models.TextField(blank=True,
                    help_text='Short biographical note.')
    notes        = models.TextField(blank=True,
                    help_text='Why you are interested. Feeds the argument workshop.')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:60] or 'scholar'
            slug = base
            i = 2
            while Scholar.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Domain(models.Model):
    """A broad field label — philosophy of mind, historical linguistics,
    etc. Works carry M2M domains so claim browsing can filter by field."""
    name        = models.CharField(max_length=120, unique=True)
    slug        = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:80]
        super().save(*args, **kwargs)


class Work(models.Model):
    scholar      = models.ForeignKey(Scholar, on_delete=models.CASCADE,
                                     related_name='works')
    title        = models.CharField(max_length=400)
    slug         = models.SlugField(max_length=80, unique=True)
    year         = models.PositiveIntegerField(null=True, blank=True)
    kind         = models.CharField(max_length=16, choices=WORK_KINDS,
                                    default='article')
    doi          = models.CharField(max_length=160, blank=True)
    url          = models.URLField(max_length=500, blank=True)
    source_file  = models.FileField(upload_to='studious/',
                                    null=True, blank=True)
    abstract     = models.TextField(blank=True)
    full_text    = models.TextField(blank=True,
                    help_text='Plain-text body. Searchable.')
    domains      = models.ManyToManyField(Domain, blank=True,
                                          related_name='works')
    analysis_json = models.JSONField(default=dict, blank=True,
                    help_text='TF-IDF top terms, token counts, etc.')
    notes        = models.TextField(blank=True)
    ingested_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-year', 'title']
        indexes = [models.Index(fields=['scholar', '-year'])]

    def __str__(self):
        y = f' ({self.year})' if self.year else ''
        return f'{self.title}{y}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:60] or 'work'
            slug = base
            i = 2
            while Work.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def top_terms(self, limit=20):
        terms = (self.analysis_json or {}).get('top_terms') or []
        return terms[:limit]

    def token_count(self):
        return (self.analysis_json or {}).get('n_tokens') or 0


class Claim(models.Model):
    """A single extractable assertion — user-curated or auto-extracted."""
    work          = models.ForeignKey(Work, on_delete=models.CASCADE,
                                      related_name='claims')
    text          = models.TextField()
    kind          = models.CharField(max_length=16, choices=CLAIM_KINDS,
                                     default='claim')
    page_ref      = models.CharField(max_length=40, blank=True,
                    help_text='e.g. "p.42" or "§3.1".')
    notes         = models.TextField(blank=True)
    auto_extracted = models.BooleanField(default=False,
                    help_text='True if Studious proposed this; user edits clear the flag.')
    score         = models.FloatField(default=0.0,
                    help_text='Heuristic claim-likelihood 0..1 when auto-extracted.')
    order         = models.PositiveIntegerField(default=0)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']
        indexes = [models.Index(fields=['work', 'order'])]

    def __str__(self):
        preview = self.text[:80]
        return f'{self.work.scholar.name}: {preview}'


class Argument(models.Model):
    """A user-authored argument that braids claims. Phase 1 scaffolds the
    premise / tension blocks; the synthesis is always human-authored."""
    user           = models.ForeignKey(settings.AUTH_USER_MODEL,
                                       on_delete=models.CASCADE,
                                       related_name='studious_arguments')
    title          = models.CharField(max_length=200)
    slug           = models.SlugField(max_length=80, unique=True)
    kind           = models.CharField(max_length=16, choices=ARGUMENT_KINDS,
                                      default='across')
    domain         = models.ForeignKey(Domain, null=True, blank=True,
                                       on_delete=models.SET_NULL)
    premises_text  = models.TextField(blank=True,
                    help_text='Auto-scaffolded on creation — edit freely.')
    tension_text   = models.TextField(blank=True,
                    help_text='Shared-vocabulary hints; edit to name real tensions.')
    synthesis_text = models.TextField(blank=True,
                    help_text='Your argument. Studious never writes this.')
    created_at     = models.DateTimeField(auto_now_add=True)
    modified_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-modified_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:60] or 'argument'
            slug = base
            i = 2
            while Argument.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def scholars(self):
        return list(dict.fromkeys(
            it.claim.work.scholar
            for it in self.items.select_related('claim__work__scholar')
        ))


class ArgumentClaim(models.Model):
    """Ordered through-table pinning claims into an argument with a role."""
    argument = models.ForeignKey(Argument, on_delete=models.CASCADE,
                                 related_name='items')
    claim    = models.ForeignKey(Claim, on_delete=models.CASCADE,
                                 related_name='argument_uses')
    role     = models.CharField(max_length=16, choices=ARGUMENT_ROLES,
                                default='premise')
    order    = models.PositiveIntegerField(default=0)
    note     = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ['order']
        unique_together = [('argument', 'claim')]

    def __str__(self):
        return f'{self.argument.title} · {self.get_role_display()} #{self.order}'

"""Grammar Engine — persistent Languages.

A Language carries a `spec` JSON blob containing the full acoustic
stack: phonic particles, subwords, words, L-system grammars, and
(later) corpora of phrases. Generation is deterministic from `seed`,
so a language can always be regrown exactly; stored specs let you
edit or freeze a language without regenerating it.

Consumers (Bridge, Aether worlds, Planets) refer to languages by
slug or id and feed the spec into the client-side GrammarEngine.
"""

from django.db import models
from django.utils.text import slugify


class Language(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    seed = models.BigIntegerField(
        help_text='Deterministic generation seed. Same seed → same language.'
    )
    spec = models.JSONField(
        default=dict, blank=True,
        help_text='Frozen language contents: particles, subwords, words, '
                  'grammars, corpora. Generated from seed on save if empty.'
    )
    notes = models.TextField(
        blank=True,
        help_text='Free-form description — speaker demographics, in-world '
                  'context, audio character notes.'
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-modified']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f'lang-{self.seed}'
            self.slug = base[:140]
        super().save(*args, **kwargs)

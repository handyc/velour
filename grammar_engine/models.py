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
    use_count = models.BigIntegerField(
        default=0,
        help_text='Incremented every time this language is fetched — '
                  'Bridge playback, Aether worlds, Evolution imports.'
    )
    last_used = models.DateTimeField(null=True, blank=True)
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

    def variants(self):
        """Yield (category, variant_name, axiom, iterations, rules_dict)
        for each L-system variant defined in this language's spec."""
        grammars = (self.spec or {}).get('grammars', {}) or {}
        for cat_name, cat in grammars.items():
            if not isinstance(cat, dict):
                continue
            axiom = cat.get('axiom', 'S')
            iters = int(cat.get('iterations', 4) or 4)
            variants = cat.get('variants', {}) or {}
            for var_name, rules in variants.items():
                if not isinstance(rules, dict):
                    continue
                norm = {}
                for k, v in rules.items():
                    if isinstance(v, list):
                        v = v[0] if v else ''
                    if isinstance(v, str):
                        norm[k] = v
                yield cat_name, var_name, axiom, iters, norm

    def expand_variant(self, category, variant, max_len=4000):
        """Expand a specific variant's L-system to a string."""
        for cat_name, var_name, axiom, iters, rules in self.variants():
            if cat_name == category and var_name == variant:
                return _expand(axiom, rules, iters, max_len)
        return ''

    def first_variant(self):
        """Return (category, variant_name, axiom, iterations, rules) for
        the first variant, or None if this language has no grammars."""
        for tup in self.variants():
            return tup
        return None


def _expand(axiom, rules, iterations, max_len=4000):
    s = axiom or ''
    for _ in range(max(0, min(8, int(iterations or 0)))):
        out = []
        total = 0
        for ch in s:
            r = rules.get(ch, ch) if rules else ch
            out.append(r)
            total += len(r)
            if total > max_len:
                break
        s = ''.join(out)[:max_len]
    return s

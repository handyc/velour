"""Re-slug existing Sign rows now that ``Sign.derive_slug`` no
longer concatenates the variety *slug* (which already contains the
language name) — it uses the variety *name* instead, dropping the
duplicated segments in slugs like
``water-ghanaian-sign-language-gsl-lexicon-2021``.

This migration walks every Sign row, recomputes the slug, and
saves the result. Idempotent.
"""

from django.db import migrations
from django.utils.text import slugify


def _reslug(apps, schema_editor):
    Sign = apps.get_model('signs', 'Sign')
    # Two-pass to avoid intra-batch slug collisions: clear slugs
    # to a guaranteed-unique temporary, then derive the real slug.
    used = set()
    for s in Sign.objects.select_related('lemma', 'variety').iterator():
        base = slugify(f'{s.lemma.gloss}-{s.variety.name}')[:200] or 'sign'
        slug = base
        i = 2
        while slug in used:
            tail = f'-{i}'
            slug = base[:200 - len(tail)] + tail
            i += 1
        used.add(slug)
        if s.slug != slug:
            s.slug = slug
            s.save(update_fields=['slug'])


def _noop_reverse(apps, schema_editor):
    # Old slugs are derivable but not worth restoring on rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [('signs', '0001_initial')]
    operations = [migrations.RunPython(_reslug, _noop_reverse)]

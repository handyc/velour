"""Backfill: every existing Rule gets one default Agent whose palette
mirrors the rule's current ``palette_ansi``. Idempotent — skips rules
that already have a default agent (in case the migration is run twice
or partial).

Slug shape: ``{rule.slug}-default``. If that collides (very unlikely
since rule slugs are unique and the suffix is fixed), append a counter.
"""
from django.db import migrations
from django.utils import timezone


def _unique_agent_slug(Agent, base: str) -> str:
    candidate = base[:100]
    n = 2
    while Agent.objects.filter(slug=candidate).exists():
        candidate = f'{base[:96]}-{n}'
        n += 1
    return candidate


def forwards(apps, schema_editor):
    Rule  = apps.get_model('taxon', 'Rule')
    Agent = apps.get_model('taxon', 'Agent')
    created = 0
    for rule in Rule.objects.all():
        if Agent.objects.filter(rule=rule, is_default=True).exists():
            continue
        Agent.objects.create(
            slug=_unique_agent_slug(Agent, f'{rule.slug}-default'),
            name=rule.name or rule.slug,
            rule=rule,
            palette_ansi=bytes(rule.palette_ansi or b''),
            is_default=True,
            created_at=rule.created_at or timezone.now(),
        )
        created += 1
    if created:
        print(f'  · backfilled {created} default agent(s)')


def backwards(apps, schema_editor):
    # Removing all default agents is destructive but reversible enough
    # — Rule.palette_ansi still has the canonical palette.
    Agent = apps.get_model('taxon', 'Agent')
    Agent.objects.filter(is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('taxon', '0004_agent'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]

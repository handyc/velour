"""Build a periodic Codex report from a recipe.

Walks the recipe's contributor list, calls each one's contribute()
function, and assembles the resulting Sections into a Manual that
can be rendered to PDF.

Idempotent — re-running with the same recipe slug updates the
existing manual rather than creating duplicates.

Usage:

    python manage.py build_report weekly
        Build the recipe slugged 'weekly'.

    python manage.py build_report --all
        Build every enabled recipe.

    python manage.py build_report --seed-default
        Seed the default 'weekly' recipe if it doesn't exist, then exit.

Add to crontab for periodic builds:

    0 8 * * 1 /var/www/webapps/<user>/apps/velour/venv/bin/python \\
              /var/www/webapps/<user>/apps/velour/manage.py build_report --all
"""

import importlib
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from codex.contributions import SectionContribution
from codex.models import Manual, ReportRecipe, Section


DEFAULT_RECIPE = {
    'slug':         'weekly',
    'name':         'Weekly status report',
    'description':  'A weekly summary of the state of the lab — calendar '
                    'events, attention ticks, fleet status, system snapshot, '
                    'mail volume, codex activity.',
    'contributors': 'identity,chronos,identity_attention,nodes,attic,mailroom,sysinfo,codex',
    'period_days':  7,
}


def _get_identity():
    try:
        from identity.models import Identity
        return Identity.get_self()
    except Exception:
        return None


def build_recipe(recipe):
    end_dt = timezone.now()
    start_dt = end_dt - timedelta(days=recipe.period_days)

    identity = _get_identity()
    author = identity.name if identity else 'Velour'

    manual_slug = recipe.output_slug
    manual, _ = Manual.objects.update_or_create(
        slug=manual_slug,
        defaults={
            'title':    f'{recipe.name} — {end_dt:%d %b %Y}',
            'subtitle': f'{recipe.period_days}-day period ending {end_dt:%a %d %b %Y}',
            'format':   'short',
            'author':   author,
            'version':  end_dt.strftime('%Y-%m-%d'),
            'abstract': recipe.description or
                        'Auto-generated periodic report from the codex contributions registry.',
        },
    )

    # Wipe existing sections so re-runs don't duplicate.
    manual.sections.all().delete()

    sort = 0
    for contributor_slug in recipe.contributor_list:
        try:
            module = importlib.import_module(
                f'codex.contributions.{contributor_slug}'
            )
        except ImportError:
            continue
        if not hasattr(module, 'contribute'):
            continue
        try:
            contributions = module.contribute(start_dt, end_dt)
        except Exception:
            contributions = []
        for c in contributions:
            sort += 10
            section_slug = slugify(f'{contributor_slug}-{c.title}')[:200]
            Section.objects.create(
                manual=manual,
                slug=section_slug,
                sort_order=sort + c.sort_offset,
                title=c.title,
                body=c.body,
                sidenotes=c.sidenotes,
            )

    recipe.last_built_at = end_dt
    recipe.save(update_fields=['last_built_at'])
    return manual


class Command(BaseCommand):
    help = 'Build a periodic Codex report from a ReportRecipe.'

    def add_arguments(self, parser):
        parser.add_argument('slug', nargs='?', default=None,
                            help='Recipe slug to build.')
        parser.add_argument('--all', action='store_true',
                            help='Build every enabled recipe.')
        parser.add_argument('--seed-default', action='store_true',
                            help='Seed the default weekly recipe if missing, then exit.')

    def handle(self, *args, **opts):
        if opts['seed_default']:
            obj, created = ReportRecipe.objects.update_or_create(
                slug=DEFAULT_RECIPE['slug'],
                defaults={
                    'name':         DEFAULT_RECIPE['name'],
                    'description':  DEFAULT_RECIPE['description'],
                    'contributors': DEFAULT_RECIPE['contributors'],
                    'period_days':  DEFAULT_RECIPE['period_days'],
                    'enabled':      True,
                },
            )
            verb = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb} default recipe: {obj.slug}'))
            return

        if opts['all']:
            recipes = ReportRecipe.objects.filter(enabled=True)
            if not recipes.exists():
                self.stdout.write(self.style.WARNING(
                    'No enabled recipes. Run with --seed-default to create one.'
                ))
                return
            for r in recipes:
                m = build_recipe(r)
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ {r.slug}: {m.slug} ({m.sections.count()} sections)'
                ))
            return

        slug = opts['slug']
        if not slug:
            self.stderr.write(self.style.ERROR(
                'Pass a recipe slug, or --all, or --seed-default.'
            ))
            return
        try:
            recipe = ReportRecipe.objects.get(slug=slug)
        except ReportRecipe.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                f'No recipe with slug "{slug}". Available: '
                f'{list(ReportRecipe.objects.values_list("slug", flat=True))}'
            ))
            return
        m = build_recipe(recipe)
        self.stdout.write(self.style.SUCCESS(
            f'Built {m.slug} ({m.sections.count()} sections)'
        ))

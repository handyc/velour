"""Seed the FormulaLanguage registry. Idempotent — re-runs are safe."""

from django.core.management.base import BaseCommand

from ledger.models import FormulaLanguage


SEEDS = [
    {
        'slug': 'excel',
        'name': 'Excel-compatible',
        'version': 'formulas-1.x',
        'description': 'Standard Excel formulas — SUM, IF, VLOOKUP, '
                       'arithmetic, comparisons. Backed by the `formulas` '
                       'pkg.',
    },
    {
        'slug': 'arith',
        'name': 'Arithmetic only',
        'version': '1.0',
        'description': 'Cell refs + the four operations. No functions. '
                       'Strict, parser-free, tiny.',
    },
]


class Command(BaseCommand):
    help = 'Seed Ledger formula-language registry rows.'

    def handle(self, *args, **opts):
        for s in SEEDS:
            obj, created = FormulaLanguage.objects.update_or_create(
                slug=s['slug'], defaults=s,
            )
            self.stdout.write(
                f"{'created' if created else 'updated'}: {obj.slug}"
            )

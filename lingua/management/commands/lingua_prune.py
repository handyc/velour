"""Cap the TranslationCache to MAX_ROWS via LRU on last_hit_at.

Run periodically (e.g. weekly) to keep cache footprint bounded as
the project grows. Reviewed-by-human rows are never pruned.
"""

from django.core.management.base import BaseCommand

from lingua.models import TranslationCache


DEFAULT_CAP = 20000


class Command(BaseCommand):
    help = "LRU-prune lingua.TranslationCache down to --cap rows."

    def add_arguments(self, parser):
        parser.add_argument('--cap', type=int, default=DEFAULT_CAP)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        cap = opts['cap']
        total = TranslationCache.objects.count()
        if total <= cap:
            self.stdout.write(f'cache has {total} rows (≤ {cap}); nothing to do')
            return

        purgeable = TranslationCache.objects.filter(reviewed_by_human=False)
        excess = total - cap
        # Order: oldest last_hit_at first; NULL → earliest.
        victims = list(purgeable.order_by('last_hit_at', 'created_at')
                       .values_list('pk', flat=True)[:excess])

        self.stdout.write(
            f'pruning {len(victims)} rows (target {cap}, had {total})'
        )
        if opts['dry_run']:
            return
        TranslationCache.objects.filter(pk__in=victims).delete()
        self.stdout.write(self.style.SUCCESS(
            f'remaining rows: {TranslationCache.objects.count()}'
        ))

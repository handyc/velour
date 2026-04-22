"""Pull all active Aggregator feeds once."""

from django.core.management.base import BaseCommand

from aggregator.models import Feed


class Command(BaseCommand):
    help = 'Fetch all active Aggregator feeds (RSS/Atom).'

    def add_arguments(self, parser):
        parser.add_argument('--feed', type=str, default='',
                            help='Limit to a single Feed by exact name.')

    def handle(self, *args, **opts):
        qs = Feed.objects.filter(active=True)
        if opts['feed']:
            qs = qs.filter(name=opts['feed'])
        total_new = total_upd = 0
        for f in qs:
            new, upd, err = f.fetch_once()
            total_new += new
            total_upd += upd
            status = f'+{new} new / {upd} upd'
            if err:
                status += f' · ERROR: {err}'
            self.stdout.write(f'  {f.name:40s} {status}')
        self.stdout.write(self.style.SUCCESS(
            f'Done. {total_new} new, {total_upd} updated.'))

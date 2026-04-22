"""Extract reader-mode body HTML/text for Articles missing a body."""

from django.core.management.base import BaseCommand

from aggregator.models import Article


class Command(BaseCommand):
    help = 'Fetch full article bodies (trafilatura) for articles that lack one.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50,
                            help='Max number of articles to process.')
        parser.add_argument('--retry-errors', action='store_true',
                            help='Re-try articles that previously failed.')
        parser.add_argument('--feed', type=str, default='',
                            help='Limit to one Feed by exact name.')

    def handle(self, *args, **opts):
        qs = Article.objects.filter(body_html='')
        if not opts['retry_errors']:
            qs = qs.filter(body_fetched_at__isnull=True)
        if opts['feed']:
            qs = qs.filter(feed__name=opts['feed'])
        qs = qs.select_related('feed').order_by('-published_at', '-fetched_at')[:opts['limit']]

        ok = fail = 0
        for art in qs:
            try:
                got = art.fetch_content()
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f'  ! {art.feed.name[:20]:20s} {art.title[:60]} — {exc}'))
                fail += 1
                continue
            mark = 'OK' if got else 'no body'
            self.stdout.write(
                f'  {mark:7s} {art.feed.name[:20]:20s} {art.title[:60]}')
            if got:
                ok += 1
            else:
                fail += 1
        self.stdout.write(self.style.SUCCESS(
            f'Done. {ok} extracted, {fail} without body.'))

"""Seed a starter set of well-known RSS/Atom feeds. Idempotent."""

from django.core.management.base import BaseCommand

from aggregator.models import Feed


SEEDS = [
    # (name, url, topics)
    ('BBC World',           'https://feeds.bbci.co.uk/news/world/rss.xml',        'world, news'),
    ('BBC Technology',      'https://feeds.bbci.co.uk/news/technology/rss.xml',   'tech'),
    ('BBC Science',         'https://feeds.bbci.co.uk/news/science_and_environment/rss.xml',
                                                                                   'science'),
    ('NYT World',           'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
                                                                                   'world, news'),
    ('NYT Technology',      'https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml',
                                                                                   'tech'),
    ('The Guardian World',  'https://www.theguardian.com/world/rss',               'world, news'),
    ('Ars Technica',        'https://feeds.arstechnica.com/arstechnica/index',     'tech, science'),
    ('Hacker News (top)',   'https://hnrss.org/frontpage',                         'tech, hn'),
    ('Al Jazeera English',  'https://www.aljazeera.com/xml/rss/all.xml',           'world, news'),
    ('Deutsche Welle',      'https://rss.dw.com/xml/rss-en-top',                   'world, news'),
    ('NASA Breaking News',  'https://www.nasa.gov/news-release/feed/',             'science, space'),
    ('Quanta Magazine',     'https://www.quantamagazine.org/feed/',                'science, math'),
    ('Nature News',         'https://www.nature.com/nature.rss',                   'science'),
    ('NRC Binnenland',      'https://www.nrc.nl/rss/',                             'nl, news'),
    ('NOS Algemeen',        'https://feeds.nos.nl/nosnieuwsalgemeen',              'nl, news'),
]


class Command(BaseCommand):
    help = 'Seed a default set of RSS/Atom feeds for Aggregator.'

    def handle(self, *args, **opts):
        created = updated = 0
        for name, url, topics in SEEDS:
            obj, was_created = Feed.objects.update_or_create(
                name=name,
                defaults={'url': url, 'topics': topics, 'kind': 'rss',
                          'active': True},
            )
            if was_created:
                created += 1
                self.stdout.write(f'  + {name}')
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {created} new feeds, refreshed {updated}.'))

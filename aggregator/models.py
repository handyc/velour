"""Aggregator — RSS/Atom feeds + custom newspaper issues.

Flow:
    Feed.fetch_once() → creates/updates Article rows
    compose_newspaper() → bundles recent Articles into a Newspaper issue
"""

from __future__ import annotations

import datetime as _dt
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


FEED_KIND_CHOICES = [
    ('rss',  'RSS / Atom (feedparser)'),
    ('html', 'HTML scrape (Phase 2 — not yet wired)'),
]


class Feed(models.Model):
    """An RSS/Atom source we poll for fresh articles."""

    name        = models.CharField(max_length=120)
    url         = models.URLField(max_length=500)
    kind        = models.CharField(max_length=8, choices=FEED_KIND_CHOICES,
                                   default='rss')
    topics      = models.CharField(max_length=240, blank=True,
                                   help_text='Comma-separated tags: tech, world, etc.')
    active      = models.BooleanField(default=True)
    last_fetched = models.DateTimeField(null=True, blank=True)
    last_error   = models.TextField(blank=True)
    fetch_count  = models.PositiveIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def topic_list(self):
        return [t.strip() for t in self.topics.split(',') if t.strip()]

    def fetch_once(self, max_articles=40):
        """Fetch the feed once. Returns (new_count, updated_count, error_or_None)."""
        if self.kind != 'rss':
            return (0, 0, f'kind "{self.kind}" not yet supported')
        import feedparser
        try:
            parsed = feedparser.parse(self.url)
        except Exception as exc:
            self.last_error = f'parse failed: {exc}'
            self.last_fetched = timezone.now()
            self.save(update_fields=['last_error', 'last_fetched'])
            return (0, 0, str(exc))

        new_count = 0
        updated_count = 0
        for entry in (parsed.entries or [])[:max_articles]:
            link = (entry.get('link') or '').strip()
            title = (entry.get('title') or '').strip()
            if not link or not title:
                continue
            published = None
            for key in ('published_parsed', 'updated_parsed'):
                tup = entry.get(key)
                if tup:
                    try:
                        published = _dt.datetime(*tup[:6],
                                                 tzinfo=_dt.timezone.utc)
                        break
                    except (TypeError, ValueError):
                        pass
            summary = (entry.get('summary') or '').strip()[:4000]
            author = (entry.get('author') or '').strip()[:160]
            guid = (entry.get('id') or link)[:400]

            obj, created = Article.objects.update_or_create(
                feed=self, guid=guid,
                defaults={
                    'title':        title[:400],
                    'url':          link[:500],
                    'summary':      summary,
                    'author':       author,
                    'published_at': published,
                },
            )
            if created:
                new_count += 1
            else:
                updated_count += 1

        self.last_fetched = timezone.now()
        self.last_error = '' if new_count + updated_count > 0 else \
            (f'no entries from {self.url}')
        self.fetch_count += 1
        self.save(update_fields=['last_fetched', 'last_error', 'fetch_count'])
        return (new_count, updated_count, None)


class Article(models.Model):
    """A single fetched article. Unique on (feed, guid)."""

    feed         = models.ForeignKey(Feed, on_delete=models.CASCADE,
                                     related_name='articles')
    guid         = models.CharField(max_length=400)
    title        = models.CharField(max_length=400)
    url          = models.URLField(max_length=500)
    author       = models.CharField(max_length=160, blank=True)
    summary      = models.TextField(blank=True)
    body_html    = models.TextField(blank=True,
        help_text='Reader-mode HTML extracted from the article URL.')
    body_text    = models.TextField(blank=True,
        help_text='Plain-text form of the body — searchable.')
    body_fetched_at = models.DateTimeField(null=True, blank=True)
    body_error   = models.CharField(max_length=240, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    fetched_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('feed', 'guid')]
        ordering = ['-published_at', '-fetched_at']
        indexes = [models.Index(fields=['-published_at'])]

    def __str__(self):
        return self.title

    def has_body(self):
        return bool(self.body_html.strip())

    def fetch_content(self):
        """Download the URL and extract reader-mode body. Returns bool."""
        import trafilatura
        try:
            downloaded = trafilatura.fetch_url(self.url)
            if not downloaded:
                self.body_error = 'download returned empty'
                self.body_fetched_at = timezone.now()
                self.save(update_fields=['body_error', 'body_fetched_at'])
                return False
            body_html = trafilatura.extract(
                downloaded, output_format='html',
                include_comments=False, include_tables=True,
                include_images=True, include_links=True,
                favor_recall=True,
            ) or ''
            body_text = trafilatura.extract(
                downloaded, output_format='txt',
                include_comments=False,
            ) or ''
        except Exception as exc:
            self.body_error = f'extract failed: {exc}'[:240]
            self.body_fetched_at = timezone.now()
            self.save(update_fields=['body_error', 'body_fetched_at'])
            return False

        self.body_html = body_html
        self.body_text = body_text
        self.body_error = '' if body_html.strip() else 'no readable content'
        self.body_fetched_at = timezone.now()
        self.save(update_fields=['body_html', 'body_text',
                                 'body_error', 'body_fetched_at'])
        return bool(body_html.strip())


class Newspaper(models.Model):
    """A compiled issue — snapshot of selected articles at a moment in time."""

    user        = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.CASCADE,
                                    related_name='newspapers')
    slug        = models.SlugField(max_length=80, unique=True)
    title       = models.CharField(max_length=200,
                                   default="Today's Velour Herald")
    subtitle    = models.CharField(max_length=200, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    window_hours = models.PositiveIntegerField(default=24,
        help_text='Articles no older than this are considered.')
    article_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.created_at:%Y-%m-%d %H:%M})'

    @classmethod
    def compose(cls, user, window_hours=24, max_per_feed=4, max_total=60,
                title=None):
        """Snapshot the latest articles into a new Newspaper. Returns the issue."""
        now = timezone.now()
        cutoff = now - timezone.timedelta(hours=window_hours)
        chosen = []
        per_feed_counts = {}

        qs = (Article.objects
              .filter(feed__active=True)
              .filter(models.Q(published_at__gte=cutoff) |
                      models.Q(published_at__isnull=True,
                               fetched_at__gte=cutoff))
              .select_related('feed')
              .order_by('-published_at', '-fetched_at'))

        for art in qs:
            k = art.feed_id
            if per_feed_counts.get(k, 0) >= max_per_feed:
                continue
            chosen.append(art)
            per_feed_counts[k] = per_feed_counts.get(k, 0) + 1
            if len(chosen) >= max_total:
                break

        base_slug = slugify(f'issue-{now:%Y%m%d-%H%M}')
        slug = base_slug
        salt = 1
        while cls.objects.filter(slug=slug).exists():
            salt += 1
            slug = f'{base_slug}-{salt}'

        issue = cls.objects.create(
            user=user,
            slug=slug,
            title=title or f"Velour Herald · {now:%a %d %b %Y %H:%M}",
            subtitle=f"{len(chosen)} stories · last {window_hours} h "
                     f"· {len(per_feed_counts)} sources",
            window_hours=window_hours,
            article_count=len(chosen),
        )
        for order, art in enumerate(chosen):
            NewspaperArticle.objects.create(
                newspaper=issue, article=art, order=order,
            )
        return issue


class NewspaperArticle(models.Model):
    """Ordered through-table so issues remain stable even if Articles change."""

    newspaper = models.ForeignKey(Newspaper, on_delete=models.CASCADE,
                                  related_name='items')
    article   = models.ForeignKey(Article, on_delete=models.CASCADE)
    order     = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = [('newspaper', 'article')]

    def __str__(self):
        return f'{self.newspaper.slug}#{self.order}: {self.article.title}'

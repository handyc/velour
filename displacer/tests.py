"""Tests for Article.display_order — the field that drives the
public Verhalen list ordering on /displace/verhalen/.

Three layers are covered:

1. ``_story_index_order`` — HTML parser that lifts the curated
   zotonic-id sequence off the source index page.
2. ``apply_curated_article_order`` — the reset-then-rank helper
   used by the ingest command.
3. ``Article`` Meta.ordering and the ``article_list`` view, which
   together make the curated order surface to readers.

Run via:
    venv/bin/python manage.py test displacer
"""

from bs4 import BeautifulSoup

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from displacer.models import Article
from displacer.management.commands.ingest_displace import (
    _story_index_order,
    apply_curated_article_order,
)


class StoryIndexOrderTests(SimpleTestCase):
    """The curated source order is whatever order the source index
    page lists its articles in. Duplicates collapse to first-seen."""

    def _parse(self, html):
        return _story_index_order(
            BeautifulSoup(html, 'html.parser'),
            'https://displace.nl/id/344.html',
        )

    def test_extracts_zotonic_ids_in_document_order(self):
        html = """
        <main>
          <ul id="verhalen">
            <li><a class="link" href="/id/501.html">First</a></li>
            <li><a class="link" href="/id/502.html">Second</a></li>
            <li><a class="link" href="/id/503.html">Third</a></li>
          </ul>
        </main>
        """
        self.assertEqual(self._parse(html), [501, 502, 503])

    def test_dedupes_repeated_links(self):
        # The source markup often links the same story from a hero
        # tile and the list — we want it ranked once, by first seen.
        html = """
        <div id="verhalen">
          <a href="/id/700.html">hero</a>
          <a href="/id/701.html">a</a>
          <a href="/id/700.html">hero again</a>
          <a href="/id/702.html">b</a>
        </div>
        """
        self.assertEqual(self._parse(html), [700, 701, 702])

    def test_falls_back_to_dot_list_then_main(self):
        # No #verhalen — should still find links in .list.
        list_only = """
        <main>
          <div class="list">
            <a href="/id/10.html">x</a>
            <a href="/id/11.html">y</a>
          </div>
        </main>
        """
        self.assertEqual(self._parse(list_only), [10, 11])
        # And no #verhalen + no .list — falls back to <main>.
        main_only = """
        <main>
          <a href="/id/20.html">x</a>
          <a href="/id/21.html">y</a>
        </main>
        """
        self.assertEqual(self._parse(main_only), [20, 21])

    def test_returns_empty_when_no_container(self):
        self.assertEqual(self._parse('<p>nothing here</p>'), [])

    def test_skips_non_zotonic_links(self):
        # External links and non-/id/<n>.html paths must not pollute the order.
        html = """
        <div id="verhalen">
          <a href="/themas/wonen/">theme</a>
          <a href="https://other.example/page">external</a>
          <a href="/id/42.html">real</a>
        </div>
        """
        self.assertEqual(self._parse(html), [42])


class ApplyCuratedArticleOrderTests(TestCase):
    """The reset-then-rank helper that the ingest command runs after
    each crawl. Idempotent across re-ingests."""

    def setUp(self):
        # Five articles, four with a zotonic_id (one — pk=5 — is a
        # locally-created article that never came from the source).
        self.a1 = Article.objects.create(title='A', zotonic_id=101)
        self.a2 = Article.objects.create(title='B', zotonic_id=102)
        self.a3 = Article.objects.create(title='C', zotonic_id=103)
        self.a4 = Article.objects.create(title='D', zotonic_id=104)
        self.local = Article.objects.create(title='Local', zotonic_id=None)

    def _orders(self):
        return {a.title: Article.objects.get(pk=a.pk).display_order
                for a in [self.a1, self.a2, self.a3, self.a4, self.local]}

    def test_assigns_one_through_n_in_input_order(self):
        applied = apply_curated_article_order([103, 101, 104])
        self.assertEqual(applied, 3)
        self.assertEqual(self._orders(), {
            'A': 2, 'B': 1000, 'C': 1, 'D': 3, 'Local': 1000,
        })

    def test_unranked_articles_stay_at_default(self):
        apply_curated_article_order([101])
        # B, C, D and the local article were never in the curated
        # list, so they keep the default (1000).
        self.assertEqual(Article.objects.get(pk=self.a2.pk).display_order, 1000)
        self.assertEqual(Article.objects.get(pk=self.local.pk).display_order, 1000)

    def test_rerun_resets_previously_curated_articles(self):
        # First crawl — A is rank 1.
        apply_curated_article_order([101, 102])
        self.assertEqual(Article.objects.get(pk=self.a1.pk).display_order, 1)
        # Second crawl drops A entirely; the editor un-featured it.
        # A must fall back to default rather than stay stuck at rank 1.
        applied = apply_curated_article_order([102, 103])
        self.assertEqual(applied, 2)
        self.assertEqual(Article.objects.get(pk=self.a1.pk).display_order, 1000)
        self.assertEqual(Article.objects.get(pk=self.a2.pk).display_order, 1)
        self.assertEqual(Article.objects.get(pk=self.a3.pk).display_order, 2)

    def test_unknown_zid_is_skipped_silently(self):
        # 999 isn't in our DB yet (e.g. crawl saw it on the index but
        # the article-page fetch failed). The helper must not crash.
        applied = apply_curated_article_order([101, 999, 102])
        self.assertEqual(applied, 2)
        self.assertEqual(Article.objects.get(pk=self.a1.pk).display_order, 1)
        self.assertEqual(Article.objects.get(pk=self.a2.pk).display_order, 3)


class ArticleDefaultOrderingTests(TestCase):
    """Article.Meta.ordering = ['display_order', '-zotonic_id'] —
    curated rank wins, ties broken by newest-on-source."""

    def test_lower_display_order_first(self):
        a = Article.objects.create(title='a', zotonic_id=1, display_order=3)
        b = Article.objects.create(title='b', zotonic_id=2, display_order=1)
        c = Article.objects.create(title='c', zotonic_id=3, display_order=2)
        self.assertEqual(
            list(Article.objects.values_list('title', flat=True)),
            ['b', 'c', 'a'],
        )

    def test_default_ties_break_by_descending_zotonic_id(self):
        # All at default 1000 — newest source id should appear first.
        old = Article.objects.create(title='old', zotonic_id=10)
        mid = Article.objects.create(title='mid', zotonic_id=20)
        new = Article.objects.create(title='new', zotonic_id=30)
        self.assertEqual(
            list(Article.objects.values_list('title', flat=True)),
            ['new', 'mid', 'old'],
        )

    def test_curated_articles_come_before_uncurated(self):
        # Realistic mix: two curated stories (rank 1 + 2) followed by
        # default-rank stories ordered by recency.
        Article.objects.create(title='hero', zotonic_id=500, display_order=1)
        Article.objects.create(title='runner-up', zotonic_id=501, display_order=2)
        Article.objects.create(title='newest-uncurated', zotonic_id=999)
        Article.objects.create(title='older-uncurated', zotonic_id=400)
        self.assertEqual(
            list(Article.objects.values_list('title', flat=True)),
            ['hero', 'runner-up', 'newest-uncurated', 'older-uncurated'],
        )


class ArticleListViewOrderingTests(TestCase):
    """The /displace/verhalen/ page must render articles in the same
    order the model declares — that's the public surface of
    display_order."""

    def test_article_list_respects_display_order(self):
        Article.objects.create(
            title='Third by rank', zotonic_id=300, display_order=3,
            published=True,
        )
        Article.objects.create(
            title='First by rank', zotonic_id=100, display_order=1,
            published=True,
        )
        Article.objects.create(
            title='Second by rank', zotonic_id=200, display_order=2,
            published=True,
        )
        # Drafts must not appear.
        Article.objects.create(
            title='Draft', zotonic_id=400, display_order=0, published=False,
        )
        resp = self.client.get(reverse('displacer:article_list'))
        self.assertEqual(resp.status_code, 200)
        articles = list(resp.context['articles'])
        self.assertEqual(
            [a.title for a in articles],
            ['First by rank', 'Second by rank', 'Third by rank'],
        )

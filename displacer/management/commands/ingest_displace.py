"""Ingest the public displace.nl mirror into the Displacement DB.

displace.nl is a wget-style static mirror of a Zotonic site, served at
``https://displace.nl/www.displace.nl/...``. Each piece of content has
a numeric id and lives at ``/www.displace.nl/id/<id>.html``.

We don't have a sitemap. Instead we BFS-crawl from known entry points
(home, themes index, stories index, footer pages) and follow every
internal id/<n>.html link we discover.

Idempotent: keyed on ``zotonic_id``. Re-running updates rather than
duplicates. Images are deduped by SHA-256.

Usage::

    python manage.py ingest_displace                     # full crawl
    python manage.py ingest_displace --max 5             # cap pages
    python manage.py ingest_displace --only 584 343      # specific ids
    python manage.py ingest_displace --no-images         # skip downloads
    python manage.py ingest_displace --dry-run           # parse only
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from displacer.models import (
    Article, ArticleCredit, Category, HomeBlock, MediaAsset, Page,
    Person, Theme,
)


BASE = 'https://displace.nl/www.displace.nl'
ID_URL = BASE + '/id/{id}.html'
ID_RE = re.compile(r'(?:^|/)id/(\d+)\.html$')

# Public landing page (real homepage layout with home-summary +
# home-featured strip). The /www.displace.nl/ subpath returns 403
# from outside; only the root serves the home template directly.
PUBLIC_HOME = 'https://displace.nl/'


# Known entry points — guaranteed pages we always start the crawl from.
SEED_IDS = [336, 343, 344, 347, 376, 381, 417, 433, 584, 630]


# --- Helpers --------------------------------------------------------


def _fetch(session: requests.Session, url: str) -> bytes | None:
    try:
        r = session.get(url, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    return r.content


def _zid(url: str) -> int | None:
    m = ID_RE.search(urlparse(url).path)
    return int(m.group(1)) if m else None


def _internal_id_links(soup: BeautifulSoup, current_url: str) -> list[int]:
    out = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        absurl = urljoin(current_url, href)
        if 'displace.nl' not in urlparse(absurl).netloc and \
           urlparse(absurl).netloc != '':
            continue
        zid = _zid(absurl)
        if zid is not None:
            out.append(zid)
    return out


def apply_curated_article_order(curated_zids: list[int]) -> int:
    """Reset every Article's display_order to the default (1000), then
    assign display_order=1..N to the zotonic ids in ``curated_zids``.

    Returns the number of articles that actually received a curated
    rank (curated_zids may include zids that aren't in our DB yet).
    """
    Article.objects.exclude(display_order=1000).update(display_order=1000)
    applied = 0
    for i, zid in enumerate(curated_zids, start=1):
        applied += Article.objects.filter(zotonic_id=zid).update(
            display_order=i,
        )
    return applied


def _story_index_order(soup: BeautifulSoup, current_url: str) -> list[int]:
    """On the stories index (id/344) the curated order lives in the
    list of <a class="link"> entries inside #verhalen / .list. Capture
    the order, de-duped, so we can drive Article.display_order."""
    candidates = []
    container = (soup.select_one('#verhalen') or soup.select_one('.list')
                 or soup.find('main'))
    if not container:
        return []
    for a in container.find_all('a', href=True):
        zid = _zid(urljoin(current_url, a['href']))
        if zid is not None:
            candidates.append(zid)
    seen, ordered = set(), []
    for zid in candidates:
        if zid not in seen:
            seen.add(zid)
            ordered.append(zid)
    return ordered


def _theme_article_ids(soup: BeautifulSoup,
                       current_url: str) -> list[int]:
    """On a theme page (id/348 etc.) the ``#verhalen`` list links to
    the stories in this theme. Return their zotonic ids in order."""
    container = soup.select_one('#verhalen') or soup.select_one('#list--haspart')
    if not container:
        return []
    seen, ordered = set(), []
    for a in container.find_all('a', href=True):
        zid = _zid(urljoin(current_url, a['href']))
        if zid is not None and zid not in seen:
            seen.add(zid)
            ordered.append(zid)
    return ordered


def _theme_index_order(soup: BeautifulSoup,
                       current_url: str) -> list[int]:
    """Zid order of themes on the THEMA'S index (id/343). Source
    orders these editorially (Wonen, Oorlog en sport, ...); without
    this hint they fall back to alphabetical title."""
    out = []
    for li in soup.select('li.list__item--vertical'):
        a = li.find('a', href=True)
        if not a:
            continue
        zid = _zid(urljoin(current_url, a['href']))
        if zid is not None and zid not in out:
            out.append(zid)
    return out


def _footer_page_order(soup: BeautifulSoup,
                       current_url: str) -> list[int]:
    """Zid order of the links inside ``ul.main-footer__nav``. The
    source orders these editorially (Toegankelijkheid, Privacy,
    Stuur ons uw verhaal); without this hook they fall back to
    alphabetical title and end up wrong."""
    out = []
    container = soup.select_one('ul.main-footer__nav')
    if not container:
        return out
    for a in container.find_all('a', href=True):
        zid = _zid(urljoin(current_url, a['href']))
        if zid is not None and zid not in out:
            out.append(zid)
    return out


def _menu_page_order(soup: BeautifulSoup,
                     current_url: str) -> list[int]:
    """Zid order of menu links carrying ``class="page_about"`` (or
    similar non-fixed page links) inside the global nav. Themes /
    Verhalen are wired separately in templates and skipped here."""
    out = []
    container = soup.select_one('ul.global-nav__menu')
    if not container:
        return out
    for li in container.find_all('li'):
        a = li.find('a', href=True)
        if not a:
            continue
        # Skip the two hard-wired buttons the template renders
        # itself; we only care about the page_about-style entries
        # that come from menu_pages.
        cls = ' '.join(a.get('class') or [])
        if 'themes' in cls or 'stories' in cls:
            continue
        zid = _zid(urljoin(current_url, a['href']))
        if zid is not None and zid not in out:
            out.append(zid)
    return out


def _home_blocks(soup: BeautifulSoup, current_url: str) -> list[dict]:
    """Editorial text blocks in the lower 'home-blocks' strip on the
    homepage. Each is a heading + short body + 'Lees meer' button."""
    out = []
    container = soup.find('div', class_='home-blocks')
    if not container:
        return out
    for div in container.select('div.text-block'):
        h2 = div.find('h2')
        body = div.select_one('.block__body')
        a = div.find('a', href=True)
        if not h2:
            continue
        link_zid = _zid(urljoin(current_url, a['href'])) if a else None
        # The visually-hidden span carries the editorial label, e.g.
        # ', over Toegankelijkheid'. Strip the leading comma + space.
        label = ''
        if a:
            vh = a.select_one('.visually-hidden')
            if vh:
                label = vh.get_text(' ', strip=True).lstrip(',').strip()
        # body_html: keep just the inner HTML of .block__body (no
        # outer div) so the template can wrap it itself.
        body_html = ''
        if body:
            body_html = ''.join(str(c) for c in body.contents).strip()
        out.append({
            'block_id':   div.get('id', ''),
            'title':      h2.get_text(' ', strip=True),
            'body_html':  body_html,
            'link_zid':   link_zid,
            'link_label': label,
        })
    return out


def _home_featured_cards(soup: BeautifulSoup,
                         current_url: str) -> list[dict]:
    """Featured strip on the homepage: returns one dict per card with
    ``zid`` and ``img_url`` (absolutised). Order is the visible order
    on the source homepage. Used to make our 'Uitgelicht' cards show
    the same images the source editors chose — the article body's first
    image often differs from the editor-curated 'depiction'."""
    out = []
    container = soup.find('div', class_='home-featured')
    if not container:
        return out
    for li in container.select('li.list__item'):
        a = li.find('a', href=True)
        if not a:
            continue
        zid = _zid(urljoin(current_url, a['href']))
        if zid is None:
            continue
        img = li.find('img')
        img_url = urljoin(current_url, img['src']) if (img and img.get('src')) else None
        out.append({'zid': zid, 'img_url': img_url})
    return out


def _classify(soup: BeautifulSoup) -> str:
    """Return one of: 'home', 'themes_index', 'stories_index',
    'theme', 'story', 'page', 'unknown'."""
    body = soup.find('body')
    cls = ' '.join(body.get('class') or []) if body else ''
    if 't--home' in cls:
        return 'home'
    if 't--themes' in cls:
        return 'themes_index'
    if 't--query' in cls:
        return 'stories_index'
    if 't--theme' in cls:
        return 'theme'
    if 't--story' in cls:
        return 'story'
    if 't--page' in cls or 't--text' in cls:
        return 'page'
    return 'unknown'


def _title(soup: BeautifulSoup) -> str:
    h1 = soup.find('h1', class_='page-title') or soup.find('h1')
    if h1:
        return h1.get_text(strip=True)
    title = soup.find('title')
    if title:
        # "Foo - Displace" → "Foo"
        t = title.get_text(strip=True)
        return re.sub(r'\s*-\s*Displace\s*$', '', t)
    return ''


def _story_body(soup: BeautifulSoup) -> tuple[str, str]:
    """Story bodies are everything inside ``article.story`` except the
    title, category strongs, and the structured credit/summary lines.

    Some stories keep the whole body inside one ``div.body-text``;
    others split content across body-text plus several sibling
    ``<p>``/``<h2>``/``<blockquote>`` elements after it. We need both."""
    article = soup.find('article', class_='story')
    if not article:
        body_div = soup.find('div', class_='body-text')
        if not body_div:
            return '', ''
        return '', str(body_div).strip()

    art = BeautifulSoup(str(article), 'lxml')

    # Editorial teaser sits in p.story-summary (above the body); prefer
    # that. Some articles only have p.summary inside the body-text.
    summary = ''
    p = art.find('p', class_='story-summary')
    if p:
        summary = p.get_text(' ', strip=True)
        p.decompose()
    else:
        bt = art.find('div', class_='body-text')
        if bt:
            p = bt.find('p', class_='summary')
            if p:
                summary = p.get_text(' ', strip=True)
                p.decompose()

    # Drop bits that the template renders separately.
    for sel in ['h1.page-title', 'strong.uppercase-title', 'a.skip-link']:
        for el in art.select(sel):
            el.decompose()

    body_article = art.find('article', class_='story') or art
    return summary, str(body_article).strip()


def _page_body(soup: BeautifulSoup) -> tuple[str, str]:
    """Pages use <article class="text-page"> with a full-bleed
    .text-page__header (the gray band) and one or more .main-container
    blocks below. We capture the article itself (including its h1) so
    the template can render it verbatim."""
    main = soup.find('main', id='main-content')
    if not main:
        return '', ''
    main = BeautifulSoup(str(main), 'lxml')

    summary = ''
    header_sum = main.find('p', class_='text-page__header__summary')
    if header_sum:
        summary = header_sum.get_text(' ', strip=True)

    for sel in ['a.skip-link']:
        for el in main.select(sel):
            el.decompose()

    article = main.find('article', class_='text-page')
    body = article if article else (main.find('main', id='main-content') or main)
    return summary, str(body).strip()


def _theme_body(soup: BeautifulSoup) -> tuple[str, str]:
    """Theme pages render as: full-bleed masthead figure, a red
    striped .theme-body band (title + intro + jump-to-stories
    button), then a .main-container list of stories. We keep the
    first two verbatim and strip the h1 + verhalen list — the
    template provides those itself."""
    main = soup.find('main', id='main-content')
    if not main:
        return '', ''
    main = BeautifulSoup(str(main), 'lxml')

    intro_p = main.select_one('article.theme-body p')
    summary = intro_p.get_text(' ', strip=True) if intro_p else ''

    for sel in ['h1.page-title', '#verhalen', 'a.skip-link']:
        for el in main.select(sel):
            el.decompose()

    body = main.find('main', id='main-content') or main
    inner = ''.join(str(c) for c in body.contents)
    return summary, inner.strip()


def _categories(soup: BeautifulSoup) -> list[str]:
    """Return the cat-style 'uppercase-title' strings on a story page,
    excluding the ones that came in via a 'page-title' h1."""
    cats = []
    for el in soup.select('article.story strong.uppercase-title'):
        text = el.get_text(strip=True)
        if text:
            cats.append(text)
    # de-dupe preserving order
    seen, out = set(), []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# Credits like "Written by:\nFoo Bar" or "Thanks to:\nA\nB". We pull
# them straight from the body text after we've stored body_html.
CREDIT_PATTERNS = [
    ('author', re.compile(r'(?:written by|geschreven door|tekst)\s*[:\-]?\s*\n?(.+?)(?:\n\s*\n|$)',
                          re.I | re.S)),
    ('thanks', re.compile(r'(?:with thanks to|thanks to|met dank aan)\s*[:\-]?\s*\n?(.+?)(?:\n\s*\n|$)',
                          re.I | re.S)),
]


def _extract_credits(body_text: str) -> list[tuple[str, str]]:
    found = []
    for role, rx in CREDIT_PATTERNS:
        for m in rx.finditer(body_text):
            for line in m.group(1).splitlines():
                name = line.strip(' \n\t,;.')
                if name and 1 < len(name) < 80:
                    found.append((role, name))
    return found


# --- Image handling ------------------------------------------------


_image_cache: dict[str, MediaAsset] = {}


def _download_image(session: requests.Session,
                    url: str,
                    *,
                    caption: str = '',
                    alt: str = '') -> MediaAsset | None:
    if url in _image_cache:
        return _image_cache[url]

    data = _fetch(session, url)
    if not data:
        return None

    sha = hashlib.sha256(data).hexdigest()
    existing = MediaAsset.objects.filter(sha256=sha).first()
    if existing:
        _image_cache[url] = existing
        if caption and not existing.caption:
            existing.caption = caption
            existing.save(update_fields=['caption'])
        return existing

    name = unquote(PurePosixPath(urlparse(url).path).name) or 'image.jpg'
    # Strip every Zotonic mediaclass suffix iteratively, e.g.
    # foo.png(mediaclass-X).jpg → foo.png
    # foo.jpg(180x180)(crop)(upscale)(quality-100)(HASH).jpg → foo.jpg
    while True:
        new = re.sub(r'\([^)]+\)\.?[a-z0-9]*$', '', name, flags=re.I)
        if new == name:
            break
        name = new
    if '.' not in name:
        name += '.jpg'
    name = name[:200]

    asset = MediaAsset(
        title=name,
        caption=caption,
        alt_text=alt,
        original_url=url[:500],
        sha256=sha,
    )
    asset.file.save(name, ContentFile(data), save=False)
    asset.save()
    _image_cache[url] = asset
    return asset


def _hero_image(soup: BeautifulSoup) -> str | None:
    """Best-guess hero: first <img> inside the article body, or the
    first listing-style image."""
    article = soup.find('article', class_='story') \
        or soup.find('main', id='main-content')
    if not article:
        return None
    img = article.find('img')
    return img.get('src') if img else None


def _rewrite_image_urls(soup: BeautifulSoup,
                        body_html: str,
                        session: requests.Session,
                        download_images: bool,
                        page_url: str) -> str:
    """Rewrite every media URL in body_html to point at a local
    MediaAsset. If the source can't be fetched (404, dead host, old
    asset never archived in the mirror) the attribute is dropped
    rather than left as a remote URL — the whole site must be
    self-contained. Handles <img>, <source>, and lightbox <a>."""
    if not body_html:
        return body_html

    def _localise(el, attr, caption='', alt=''):
        raw = el.get(attr)
        if not raw:
            return
        absurl = urljoin(page_url, raw)
        if download_images:
            asset = _download_image(session, absurl,
                                    caption=caption, alt=alt)
            if asset and asset.file:
                el[attr] = asset.file.url
                return
            # Couldn't download — don't leak a remote URL.
            del el[attr]
        else:
            el[attr] = absurl

    body_soup = BeautifulSoup(body_html, 'lxml')
    for img in body_soup.find_all('img'):
        cap_el = img.find_parent('figure')
        caption = ''
        if cap_el:
            fc = cap_el.find('figcaption')
            if fc:
                caption = fc.get_text(' ', strip=True)
        _localise(img, 'src', caption=caption, alt=img.get('alt') or '')

    for a in body_soup.find_all('a', href=True):
        if re.search(r'\.(jpe?g|png|gif|webp)$', a['href'], re.I):
            _localise(a, 'href')

    for src_el in body_soup.find_all('source'):
        _localise(src_el, 'src')

    # lxml wraps fragments in <html><body>…</body></html>; unwrap.
    body_el = body_soup.body
    return body_el.decode_contents() if body_el else str(body_soup)


# --- Page handlers --------------------------------------------------


def _save_theme(zid: int, soup: BeautifulSoup, page_url: str,
                session, download_images: bool, log) -> Theme:
    title = _title(soup)
    summary, body_html = _theme_body(soup)
    body_html = _rewrite_image_urls(soup, body_html, session,
                                    download_images, page_url)

    theme, created = Theme.objects.update_or_create(
        zotonic_id=zid,
        defaults={
            'title': title or f'Thema {zid}',
            'summary': summary,
            'body_html': body_html,
            'original_url': page_url[:400],
            'published': True,
        },
        create_defaults={
            'title': title or f'Thema {zid}',
            'summary': summary,
            'body_html': body_html,
            'original_url': page_url[:400],
            'published': True,
            'published_at': timezone.now(),
        },
    )
    hero = _hero_image(soup)
    if hero and download_images:
        asset = _download_image(session, urljoin(page_url, hero))
        if asset:
            theme.hero_image = asset
            theme.save(update_fields=['hero_image'])

    log(f'  Theme  {"+" if created else "·"} {zid} {title}')
    return theme


def _save_article(zid: int, soup: BeautifulSoup, page_url: str,
                  session, download_images: bool, log) -> Article:
    title = _title(soup)
    summary, body_html = _story_body(soup)
    cats = _categories(soup)
    body_html = _rewrite_image_urls(soup, body_html, session,
                                    download_images, page_url)

    article, created = Article.objects.update_or_create(
        zotonic_id=zid,
        defaults={
            'title': title or f'Verhaal {zid}',
            'summary': summary,
            'body_html': body_html,
            'original_url': page_url[:400],
            'published': True,
        },
        create_defaults={
            'title': title or f'Verhaal {zid}',
            'summary': summary,
            'body_html': body_html,
            'original_url': page_url[:400],
            'published': True,
            'published_at': timezone.now(),
        },
    )

    # Categories
    article.categories.clear()
    for cat_name in cats:
        cat, _ = Category.objects.get_or_create(name=cat_name)
        article.categories.add(cat)

    # Hero image
    hero = _hero_image(soup)
    if hero and download_images:
        asset = _download_image(session, urljoin(page_url, hero))
        if asset:
            article.hero_image = asset
            article.save(update_fields=['hero_image'])

    # Credits — best-effort from the body text
    body_text = BeautifulSoup(body_html, 'lxml').get_text('\n')
    credits = _extract_credits(body_text)
    if credits:
        article.articlecredit_set.all().delete()
        for i, (role, name) in enumerate(credits):
            person, _ = Person.objects.get_or_create(name=name)
            ArticleCredit.objects.update_or_create(
                article=article, person=person, role=role,
                defaults={'order': i},
            )

    log(f'  Story  {"+" if created else "·"} {zid} {title}')
    return article


def _save_page(zid: int, soup: BeautifulSoup, page_url: str,
               session, download_images: bool, log) -> Page:
    title = _title(soup)
    summary, body_html = _page_body(soup)
    body_html = _rewrite_image_urls(soup, body_html, session,
                                    download_images, page_url)

    show_in_footer = zid in {630, 376, 381}      # Toegankelijkheid, Privacy, Stuur
    show_in_menu = zid == 347                    # Over Displace

    page, created = Page.objects.update_or_create(
        zotonic_id=zid,
        defaults={
            'title': title or f'Pagina {zid}',
            'body_html': body_html,
            'original_url': page_url[:400],
            'published': True,
            'show_in_footer': show_in_footer,
            'show_in_menu': show_in_menu,
        },
    )
    log(f'  Page   {"+" if created else "·"} {zid} {title}')
    return page


# --- Command --------------------------------------------------------


class Command(BaseCommand):
    help = 'Crawl displace.nl and ingest into the Displacement DB.'

    def add_arguments(self, parser):
        parser.add_argument('--max', type=int, default=0,
                            help='Stop after N pages (0 = unlimited).')
        parser.add_argument('--only', type=int, nargs='+', default=None,
                            help='Crawl only these zotonic ids.')
        parser.add_argument('--no-images', action='store_true',
                            help='Skip image downloads (faster, useful for tests).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse but do not write to DB or download images.')
        parser.add_argument('--delay', type=float, default=0.3,
                            help='Seconds between requests (be polite).')

    def handle(self, *args, max=0, only=None, no_images=False,
               dry_run=False, delay=0.3, **kw):
        log = self.stdout.write
        download_images = not no_images and not dry_run

        session = requests.Session()
        session.headers['User-Agent'] = (
            'Velour-Displacement/0.1 (ingestion of displace.nl mirror)'
        )

        seeds = list(only) if only else list(SEED_IDS)
        queue = deque(seeds)
        seen: set[int] = set()
        # When --only is given the user wants exactly those pages —
        # do not BFS-discover linked ids beyond the seed set.
        crawl = not only
        stats = {'theme': 0, 'story': 0, 'page': 0, 'home': 0,
                 'themes_index': 0, 'stories_index': 0, 'unknown': 0,
                 'fetched': 0, 'failed': 0, 'skipped': 0}
        curated_story_order: list[int] = []
        curated_theme_order: list[int] = []
        theme_article_links: dict[int, list[int]] = {}

        while queue:
            if max and stats['fetched'] >= max:
                log(f'Reached --max {max}, stopping.')
                break
            zid = queue.popleft()
            if zid in seen:
                continue
            seen.add(zid)

            url = ID_URL.format(id=zid)
            log(f'GET {url}')
            data = _fetch(session, url)
            stats['fetched'] += 1
            if not data:
                stats['failed'] += 1
                log(f'  ! fetch failed for {zid}')
                continue

            soup = BeautifulSoup(data, 'lxml')
            kind = _classify(soup)
            stats[kind] = stats.get(kind, 0) + 1

            # Discover internal links — but only on a full crawl.
            if crawl:
                for child_zid in _internal_id_links(soup, url):
                    if child_zid not in seen and child_zid not in queue:
                        queue.append(child_zid)

            if dry_run:
                log(f'  ({kind}) — dry run, not saving')
                time.sleep(delay)
                continue

            if kind == 'theme':
                _save_theme(zid, soup, url, session, download_images, log)
                article_zids = _theme_article_ids(soup, url)
                if article_zids:
                    theme_article_links[zid] = article_zids
            elif kind == 'story':
                _save_article(zid, soup, url, session, download_images, log)
            elif kind == 'page':
                _save_page(zid, soup, url, session, download_images, log)
            elif kind == 'stories_index':
                # The Verhalen index page carries the editorial order
                # we want to mirror on our /verhalen/ list. There can
                # be several t--query pages (Featured strip vs full
                # Verhalen list); the longest one is the master order.
                found = _story_index_order(soup, url)
                if len(found) > len(curated_story_order):
                    curated_story_order = found
                    log(f'  (stories_index) curated order from {zid}: '
                        f'{curated_story_order}')
            elif kind == 'themes_index':
                # The THEMA'S index page carries the editorial order
                # for our /themas/ list. Same pattern as stories_index.
                found = _theme_index_order(soup, url)
                if len(found) > len(curated_theme_order):
                    curated_theme_order = found
                    log(f'  (themes_index) curated order from {zid}: '
                        f'{curated_theme_order}')
            elif kind == 'home':
                # Index page: just used for link discovery. (The real
                # home-featured strip lives at PUBLIC_HOME, fetched
                # separately below — the /www.displace.nl/ id paths
                # return a t--query rendering of zid 336 rather than
                # the home template.)
                pass
            else:
                # Treat unknown content-bearing pages as Pages so we
                # don't lose anything.
                if soup.find('div', class_='body-text'):
                    _save_page(zid, soup, url, session, download_images, log)
                else:
                    stats['skipped'] += 1
                    log(f'  ? unknown page kind for {zid}, skipping')

            time.sleep(delay)

        # Apply theme↔article links collected from each theme's
        # #verhalen list. Deferred so BFS ordering (themes first,
        # their articles second) doesn't leave dangling fks.
        if theme_article_links and not dry_run:
            for theme_zid, article_zids in theme_article_links.items():
                theme = Theme.objects.filter(zotonic_id=theme_zid).first()
                if not theme:
                    continue
                arts = list(Article.objects.filter(zotonic_id__in=article_zids))
                theme.articles.set(arts)
                log(f'  Theme {theme_zid}: linked {len(arts)}/'
                    f'{len(article_zids)} articles')

        # Apply the curated Verhalen order. Reset every Article first
        # so a previous run's order doesn't bleed through; then the
        # ones in the source index get display_order = 1..N and the
        # rest fall back to recency by zotonic_id.
        if curated_story_order and not dry_run:
            applied = apply_curated_article_order(curated_story_order)
            log(f'Applied curated display_order to {applied} '
                f'of {len(curated_story_order)} articles.')

        # Apply the curated Theme order. Reset every Theme first so
        # an earlier run's order doesn't bleed through; then the
        # ones in the source index get order = 1..N and the rest
        # fall back to the model default (100) + alphabetical title.
        if curated_theme_order and not dry_run:
            Theme.objects.exclude(order=100).update(order=100)
            applied = 0
            for i, zid in enumerate(curated_theme_order, start=1):
                applied += Theme.objects.filter(zotonic_id=zid).update(
                    order=i,
                )
            log(f'Applied curated Theme order to {applied} '
                f'of {len(curated_theme_order)} themes.')

        # Apply the homepage 'Uitgelicht' strip. Fetch the real
        # public landing page (its layout — and therefore the
        # editor-curated featured cards — only exist at the site
        # root). Reset every article first so a previous run's
        # selection doesn't bleed through; then mark the source-listed
        # ones featured + assign their editor-curated card images as
        # hero_image (the article body's first image is often a
        # different shot from the one editors picked for the card).
        if not dry_run:
            home_data = _fetch(session, PUBLIC_HOME)
            if home_data:
                home_soup = BeautifulSoup(home_data, 'lxml')

                # Footer + menu link order — the source orders these
                # editorially, ours falls back to alphabetical title
                # without an explicit hint. Number from 1..N so they
                # sort ahead of any newly-added pages (default 100).
                for i, zid in enumerate(
                    _footer_page_order(home_soup, PUBLIC_HOME), start=1,
                ):
                    Page.objects.filter(zotonic_id=zid).update(order=i)
                for i, zid in enumerate(
                    _menu_page_order(home_soup, PUBLIC_HOME), start=1,
                ):
                    Page.objects.filter(zotonic_id=zid).update(order=i)

                # Editorial 'home-blocks' (Toegankelijk voor iedereen
                # / Waarom DisPLACE?) — replace, don't merge, so a
                # source rename doesn't leave stale rows behind.
                blocks = _home_blocks(home_soup, PUBLIC_HOME)
                if blocks:
                    HomeBlock.objects.all().delete()
                    for i, blk in enumerate(blocks, start=1):
                        HomeBlock.objects.create(
                            block_id=blk['block_id'],
                            title=blk['title'],
                            body_html=blk['body_html'],
                            link_zotonic_id=blk['link_zid'],
                            link_label=blk['link_label'],
                            order=i,
                        )
                    log(f'Captured {len(blocks)} home-blocks: '
                        f'{[b["title"] for b in blocks]}')

                home_featured = _home_featured_cards(home_soup, PUBLIC_HOME)
                log(f'(home) PUBLIC_HOME featured: '
                    f'{[f["zid"] for f in home_featured]}')
                if home_featured:
                    Article.objects.filter(featured=True).update(
                        featured=False, featured_order=100,
                    )
                    applied = 0
                    for i, item in enumerate(home_featured, start=1):
                        article = Article.objects.filter(
                            zotonic_id=item['zid'],
                        ).first()
                        if not article:
                            continue
                        fields = {'featured': True, 'featured_order': i}
                        if download_images and item['img_url']:
                            asset = _download_image(session, item['img_url'])
                            if asset:
                                fields['hero_image'] = asset
                        Article.objects.filter(pk=article.pk).update(**fields)
                        applied += 1
                    log(f'Applied homepage featured strip to {applied} '
                        f'of {len(home_featured)} articles.')

        log('')
        log(self.style.SUCCESS('Done. Stats:'))
        for k, v in stats.items():
            log(f'  {k:18s} {v}')
        log(f'  themes in db:  {Theme.objects.count()}')
        log(f'  articles:      {Article.objects.count()}')
        log(f'  pages:         {Page.objects.count()}')
        log(f'  media assets:  {MediaAsset.objects.count()}')

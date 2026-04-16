"""Compare every ingested page against the live source.

For each Article / Theme / Page that has a ``zotonic_id``, fetch the
corresponding source page, extract structural signals from both
sides, and report any discrepancies. Catches problems like:

  * we only captured the first content block and dropped the rest
    (the original About-page bug — researcher profiles missing)
  * a section heading from the source isn't in our body_html
  * an inline image referenced in the source isn't in our body_html
  * the title or summary changed upstream

Designed to be re-run cheaply: HEAD-then-GET, polite delay, summary
table at the end. Exits non-zero if any page is flagged so the
command is CI-friendly.

Usage::

    python manage.py verify_displace                  # all
    python manage.py verify_displace --only 347 348   # specific ids
    python manage.py verify_displace --kind page      # filter by kind
    python manage.py verify_displace --quiet          # only show problems
    python manage.py verify_displace --report file.md # write a markdown report
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand

from displacer.models import Article, MediaAsset, Page, Theme


BASE = 'https://displace.nl/www.displace.nl'
ID_URL = BASE + '/id/{id}.html'

# How much body-text length tolerance is acceptable (10%).
LEN_TOLERANCE = 0.10
# Min length difference (chars) before we even bother flagging.
LEN_MIN_FLAG = 200

# Headings that the source page renders as auto-generated chrome
# (related stories, breadcrumbs, etc.) — not real editor content,
# so we don't expect them in our body_html.
CHROME_HEADINGS = {
    'Gerelateerde verhalen',
    'Verhalen',
    'Verhalen over Wonen',
    'Verhalen in dit thema',
}


# --- Signal extraction ---------------------------------------------


def _strip(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or '', 'lxml')


def _img_key(src: str) -> str:
    """Normalise an image src to a comparable key.

    Source uses Zotonic mediaclass URLs like
    ``foo.png(mediaclass-...).jpg`` — our DB uses Django storage paths
    like ``displacer/2026/04/foo.png``. Compare on the base
    filename stem, lowercased.
    """
    if not src:
        return ''
    name = unquote(PurePosixPath(urlparse(src).path).name)
    # Strip every `(...)` and trailing extension iteratively — Zotonic
    # mediaclass URLs stack several, e.g.
    # foo.jpg(180x180)(crop)(upscale)(quality-100)(HASH).jpg
    while True:
        new = re.sub(r'\([^)]+\)\.?[a-z0-9]*$', '', name, flags=re.I)
        if new == name:
            break
        name = new
    name = re.sub(r'\.[a-z0-9]+$', '', name, flags=re.I)  # final extension
    name = re.sub(r'-\d{6,}$', '', name)                  # cache-bust suffix
    return name.lower().strip('_-.')


@dataclass
class Signals:
    title: str = ''
    headings: list[str] = field(default_factory=list)   # h2 + h3 text, in order
    img_keys: set[str] = field(default_factory=set)
    text_len: int = 0
    paragraphs: int = 0


def _signals_from_source(soup: BeautifulSoup) -> Signals:
    title_el = soup.find('h1', class_='page-title') or soup.find('h1')
    title = title_el.get_text(' ', strip=True) if title_el else ''

    main = soup.find('main', id='main-content') or soup
    container = BeautifulSoup(str(main), 'lxml')

    # Drop the auto-generated story list and the page title from the
    # comparable area so we don't penalise a Theme for "missing"
    # story-card h3s that we generate ourselves.
    for sel in ['#verhalen', 'h1.page-title', 'a.skip-link', 'ul.list',
                'ul.list--vertical', 'footer', '.main-footer',
                'h2.uppercase-title']:
        for el in container.select(sel):
            el.decompose()

    headings = [h.get_text(' ', strip=True)
                for h in container.find_all(['h2', 'h3'])
                if h.get_text(strip=True)
                and h.get_text(' ', strip=True) not in CHROME_HEADINGS
                and not h.get_text(' ', strip=True).startswith('Verhalen over ')]
    img_keys = {_img_key(i.get('src', ''))
                for i in container.find_all('img')
                if i.get('src')}
    img_keys.discard('')
    text = container.get_text(' ', strip=True)
    paragraphs = len(container.find_all('p'))

    return Signals(title=title, headings=headings,
                   img_keys=img_keys, text_len=len(text),
                   paragraphs=paragraphs)


def _signals_from_obj(obj, asset_lookup: dict) -> Signals:
    """Build signals from a DB row's body_html / title.

    `asset_lookup` maps MediaAsset.file.url → MediaAsset.original_url
    so we can compare images by their ORIGINAL source URL rather than
    by their (often Django-renamed) local filename.
    """
    body = _strip(obj.body_html or '')
    headings = [h.get_text(' ', strip=True)
                for h in body.find_all(['h2', 'h3'])
                if h.get_text(strip=True)]
    img_keys = set()
    for i in body.find_all('img'):
        src = i.get('src', '')
        if not src:
            continue
        original = asset_lookup.get(src) or src
        img_keys.add(_img_key(original))
    img_keys.discard('')
    # Articles store the lead photo on a separate hero_image FK, not
    # inside body_html — the source page renders it inline at the top.
    hero = getattr(obj, 'hero_image', None)
    if hero and hero.file:
        original = hero.original_url or hero.file.name
        img_keys.add(_img_key(original))
    text = body.get_text(' ', strip=True)
    paragraphs = len(body.find_all('p'))
    summary = getattr(obj, 'summary', '') or ''
    if summary:
        text = summary + ' ' + text
        paragraphs += 1
    return Signals(title=obj.title, headings=headings,
                   img_keys=img_keys, text_len=len(text),
                   paragraphs=paragraphs)


# --- Diffing -------------------------------------------------------


@dataclass
class Diff:
    obj_kind: str           # 'article' / 'theme' / 'page'
    zid: int
    title: str
    url: str
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _compare(obj_kind: str, src: Signals, ours: Signals, *, zid: int,
             url: str, title: str) -> Diff:
    d = Diff(obj_kind=obj_kind, zid=zid, title=title, url=url)

    if src.title and src.title.strip() != ours.title.strip():
        d.issues.append(
            f'title mismatch: source="{src.title}" ours="{ours.title}"')

    src_h, ours_h = set(src.headings), set(ours.headings)
    missing_h = src_h - ours_h
    if missing_h:
        for h in sorted(missing_h):
            d.issues.append(f'missing heading: "{h}"')

    missing_img = src.img_keys - ours.img_keys
    if missing_img:
        # Cap how many we list — listing 30 is noise.
        sample = sorted(missing_img)[:6]
        more = '' if len(missing_img) <= 6 else f' (+{len(missing_img) - 6} more)'
        d.issues.append(
            f'missing {len(missing_img)} image(s): {", ".join(sample)}{more}')

    if src.text_len > 0:
        delta = abs(src.text_len - ours.text_len)
        if delta > LEN_MIN_FLAG and delta / src.text_len > LEN_TOLERANCE:
            d.issues.append(
                f'body length off by {delta} chars '
                f'(source {src.text_len}, ours {ours.text_len})')

    return d


# --- Command -------------------------------------------------------


class Command(BaseCommand):
    help = 'Verify ingested content against the live displace.nl source.'

    def add_arguments(self, parser):
        parser.add_argument('--only', type=int, nargs='+', default=None,
                            help='Verify only these zotonic ids.')
        parser.add_argument('--kind', choices=['article', 'theme', 'page'],
                            help='Restrict to one object kind.')
        parser.add_argument('--quiet', action='store_true',
                            help='Only print pages with issues.')
        parser.add_argument('--report', type=str,
                            help='Write a Markdown report to this path.')
        parser.add_argument('--delay', type=float, default=0.25,
                            help='Seconds between fetches.')

    def handle(self, *args, only=None, kind=None, quiet=False,
               report=None, delay=0.25, **kw):
        targets = []
        if not kind or kind == 'article':
            for a in Article.objects.exclude(zotonic_id__isnull=True):
                targets.append(('article', a))
        if not kind or kind == 'theme':
            for t in Theme.objects.exclude(zotonic_id__isnull=True):
                targets.append(('theme', t))
        if not kind or kind == 'page':
            for p in Page.objects.exclude(zotonic_id__isnull=True):
                targets.append(('page', p))

        if only:
            wanted = set(only)
            targets = [(k, o) for (k, o) in targets if o.zotonic_id in wanted]

        session = requests.Session()
        session.headers['User-Agent'] = (
            'Velour-Displacement-Verify/0.1'
        )

        # Map our local /media/... URL → the original source URL, so we
        # can compare image identity by source URL not local filename.
        asset_lookup = {a.file.url: a.original_url
                        for a in MediaAsset.objects.exclude(original_url='')
                        if a.file}

        diffs: list[Diff] = []
        for i, (obj_kind, obj) in enumerate(targets, 1):
            url = ID_URL.format(id=obj.zotonic_id)
            self.stdout.write(
                f'[{i:>3}/{len(targets):>3}] '
                f'{obj_kind:>7} {obj.zotonic_id:>5}  {obj.title[:60]}')
            try:
                r = session.get(url, timeout=20)
            except requests.RequestException as e:
                d = Diff(obj_kind=obj_kind, zid=obj.zotonic_id,
                         title=obj.title, url=url,
                         issues=[f'fetch error: {e}'])
                diffs.append(d)
                continue
            if r.status_code != 200:
                d = Diff(obj_kind=obj_kind, zid=obj.zotonic_id,
                         title=obj.title, url=url,
                         issues=[f'source returned HTTP {r.status_code}'])
                diffs.append(d)
                continue

            soup = BeautifulSoup(r.content, 'lxml')
            src = _signals_from_source(soup)
            ours = _signals_from_obj(obj, asset_lookup)
            d = _compare(obj_kind, src, ours,
                         zid=obj.zotonic_id, url=url, title=obj.title)
            diffs.append(d)

            if d.ok:
                if not quiet:
                    self.stdout.write(self.style.SUCCESS(
                        f'         ok  ({len(src.headings)} headings, '
                        f'{len(src.img_keys)} imgs, {src.text_len} chars)'))
            else:
                for issue in d.issues:
                    self.stdout.write(self.style.WARNING(
                        f'         !   {issue}'))

            time.sleep(delay)

        # Summary
        ok = sum(1 for d in diffs if d.ok)
        bad = len(diffs) - ok
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Verified {len(diffs)}: {ok} ok, {bad} with issues'))

        if report:
            _write_report(report, diffs)
            self.stdout.write(f'Wrote report to {report}')

        if bad:
            sys.exit(1)


def _write_report(path: str, diffs: list[Diff]) -> None:
    lines = ['# Displacement verification report', '']
    ok = [d for d in diffs if d.ok]
    bad = [d for d in diffs if not d.ok]
    lines.append(f'- Total checked: **{len(diffs)}**')
    lines.append(f'- OK: **{len(ok)}**')
    lines.append(f'- Issues: **{len(bad)}**')
    lines.append('')
    if bad:
        lines.append('## Pages with issues')
        lines.append('')
        for d in bad:
            lines.append(f'### [{d.obj_kind} {d.zid}] {d.title}')
            lines.append(f'- source: <{d.url}>')
            for issue in d.issues:
                lines.append(f'- {issue}')
            lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

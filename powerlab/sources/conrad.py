"""Conrad product-search scraper.

Conrad has no public API — this hits the public search page and pulls
the first result's price. It's fragile by design: if Conrad reworks
their markup the fetch returns {'error': '...'} and the refresher keeps
going. Prices are quoted in EUR; we convert to USD at a pinned rate
(powerlab.sources.EUR_TO_USD) so they sit alongside Mouser numbers in
the BOM comparison.

If you're on campus and need a Conrad-only price because of purchasing
restrictions, the chart shows vendor columns side by side regardless of
which source is freshest.
"""
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation


THROTTLE_SECONDS = 2.0
HTTP_TIMEOUT = 12

# Conrad operates several country storefronts. .nl matches the user's
# locale best (Leiden); .com is the English fallback. Both redirect to
# geo-appropriate results for the same search query.
SEARCH_URLS = [
    'https://www.conrad.nl/nl/search.html?search={q}',
    'https://www.conrad.com/search?search={q}',
]


# Euro amounts on Conrad pages look like "€ 1,23" or "1,23 €" or
# "€1.23". Comma is the decimal separator on .nl, dot on .com.
_PRICE_RE = re.compile(
    r'(?:€\s*)?(\d{1,4}(?:[.,]\d{2}))(?:\s*€)?'
)


def _fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (X11; Linux x86_64) velour-powerlab/1.0 '
                '(price check for academic research)'
            ),
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'nl,en;q=0.8',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='replace')
    except (urllib.error.URLError, TimeoutError) as exc:
        return {'error': f'HTTP error: {exc}'}


def _extract_first_price_eur(html):
    """Find the first plausible EUR price in the search result HTML.

    Conrad renders prices inside `data-testid="price"`-ish wrappers on
    their newer layouts and inside class-based spans on the older ones.
    Rather than tying to one selector we scan the first 200KB of markup
    for the first euro amount that passes a sanity check. Cheap, and
    robust to their next layout refresh."""
    if not html or len(html) < 500:
        return None
    head = html[:200_000]
    for match in _PRICE_RE.finditer(head):
        raw = match.group(1)
        # Decimal separator varies; '1,23' and '1.23' both mean 1.23.
        if ',' in raw and '.' not in raw:
            raw = raw.replace(',', '.')
        elif ',' in raw and '.' in raw:
            raw = raw.replace(',', '')
        try:
            val = Decimal(raw)
        except InvalidOperation:
            continue
        # Under €0.01 or over €10k is almost certainly a false positive
        # (order number, SKU fragment, year, etc.).
        if Decimal('0.01') <= val <= Decimal('10000'):
            return val
    return None


def _extract_result_url(html):
    m = re.search(
        r'href="(/[a-z]{2}/p/[^"#?]+?-\d{6,})"',
        html or '',
    )
    if m:
        path = m.group(1)
        return f'https://www.conrad.nl{path}'
    return ''


def _is_enabled():
    # No credentials; always on.
    return True


def _fetch(part):
    if not part.mpn:
        return {'error': 'no MPN'}
    from . import EUR_TO_USD

    query = urllib.parse.quote_plus(part.mpn)
    last_err = 'unknown'
    for tmpl in SEARCH_URLS:
        html_or_err = _fetch_html(tmpl.format(q=query))
        if isinstance(html_or_err, dict):
            last_err = html_or_err['error']
            continue
        price_eur = _extract_first_price_eur(html_or_err)
        if price_eur is None:
            last_err = 'no price in search results'
            continue
        unit_usd = (price_eur * EUR_TO_USD).quantize(Decimal('0.0001'))
        result_url = _extract_result_url(html_or_err) or tmpl.format(q=query)
        # Encode conversion provenance so the snapshot row is auditable.
        sep = '&' if '?' in result_url else '?'
        provenance = (
            f'{sep}velour_eur={price_eur}&velour_rate={EUR_TO_USD}'
        )
        return {
            'unit_price_usd': unit_usd,
            'qty_break':      1,
            'source_url':     (result_url + provenance)[:500],
        }
    return {'error': last_err}


SOURCE = {
    'name':         'Conrad',
    'vendor_label': 'Conrad',
    'auto_refresh': True,
    'enabled':      _is_enabled,
    'fetch':        _fetch,
    'throttle_s':   THROTTLE_SECONDS,
}

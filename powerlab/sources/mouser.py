"""Mouser keyword-search V2 adapter.

Extracted from the original powerlab_refresh_prices command. Free-tier
limit is 30 calls/min, so the refresher sleeps THROTTLE_SECONDS between
calls.
"""
import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings


ENDPOINT = 'https://api.mouser.com/api/v2/search/keyword'
THROTTLE_SECONDS = 1.2
HTTP_TIMEOUT = 10


def _load_key():
    key = os.environ.get('MOUSER_API_KEY')
    if key:
        return key.strip()
    candidate = Path(getattr(settings, 'BASE_DIR', '.')) / 'mouser_api_key.txt'
    if candidate.exists():
        try:
            return candidate.read_text().strip()
        except OSError:
            return None
    return None


def _extract_unit_price(price_str):
    """Mouser returns '$0.123' or '0,123 €' depending on locale."""
    if not price_str:
        return None
    digits = ''
    for ch in str(price_str):
        if ch.isdigit() or ch in '.,':
            digits += ch
        elif digits:
            break
    if not digits:
        return None
    if digits.count(',') == 1 and '.' not in digits:
        digits = digits.replace(',', '.')
    else:
        digits = digits.replace(',', '')
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def _is_enabled():
    return _load_key() is not None


def _fetch(part):
    if not part.mpn:
        return {'error': 'no MPN'}
    api_key = _load_key()
    if not api_key:
        return {'error': 'MOUSER_API_KEY not set'}

    payload = {
        'SearchByKeywordRequest': {
            'keyword':           part.mpn,
            'records':           5,
            'startingRecord':    0,
            'searchOptions':     '',
            'searchWithYourSignUpLanguage': '',
        }
    }
    url = f"{ENDPOINT}?apiKey={api_key}"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data,
        headers={
            'Content-Type':  'application/json',
            'Accept':        'application/json',
            'User-Agent':    'velour-powerlab/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
    except (urllib.error.URLError, TimeoutError) as exc:
        return {'error': f'HTTP error: {exc}'}
    try:
        parsed = json.loads(body)
    except ValueError:
        return {'error': 'bad JSON from Mouser'}
    errors = parsed.get('Errors') or []
    if errors:
        return {'error': '; '.join(str(e) for e in errors)}
    parts = (parsed.get('SearchResults') or {}).get('Parts') or []
    if not parts:
        return {'error': 'no matches'}
    first = parts[0]
    breaks = first.get('PriceBreaks') or []
    if not breaks:
        return {'error': 'no price breaks'}
    qty1 = next(
        (b for b in breaks if int(b.get('Quantity') or 0) == 1),
        breaks[0],
    )
    unit_price = _extract_unit_price(qty1.get('Price'))
    qty_break = int(qty1.get('Quantity') or 1)
    if unit_price is None or unit_price <= 0:
        return {'error': f'could not parse price {qty1.get("Price")!r}'}
    return {
        'unit_price_usd': unit_price,
        'qty_break':      qty_break,
        'source_url':     (first.get('ProductDetailUrl') or '')[:500],
    }


SOURCE = {
    'name':         'Mouser',
    'vendor_label': 'Mouser',
    'auto_refresh': True,
    'enabled':      _is_enabled,
    'fetch':        _fetch,
    'throttle_s':   THROTTLE_SECONDS,
}

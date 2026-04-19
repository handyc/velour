"""Refresh Part prices from vendor APIs.

Currently supports Mouser (keyword-search V2). Set MOUSER_API_KEY in the
environment or in a `mouser_api_key.txt` sibling of the project secrets
to enable it. Without a key the command is a friendly no-op — handy for
running it as part of a cron without conditionals.

Usage:
    venv/bin/python manage.py powerlab_refresh_prices
    venv/bin/python manage.py powerlab_refresh_prices --slug=attiny13a
    venv/bin/python manage.py powerlab_refresh_prices --dry-run
"""
import json
import os
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from powerlab.models import Part, PartPriceSnapshot


MOUSER_ENDPOINT = 'https://api.mouser.com/api/v2/search/keyword'
THROTTLE_SECONDS = 1.2        # Mouser free tier: 30 calls/min max
HTTP_TIMEOUT = 10


def _load_mouser_key():
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


def _mouser_keyword_search(api_key, keyword):
    """Return the first PriceBreak list from Mouser, or None."""
    payload = {
        'SearchByKeywordRequest': {
            'keyword':           keyword,
            'records':           5,
            'startingRecord':    0,
            'searchOptions':     '',
            'searchWithYourSignUpLanguage': '',
        }
    }
    url = f"{MOUSER_ENDPOINT}?apiKey={api_key}"
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
    return {
        'part':    first,
        'breaks':  breaks,
        'mpn':     first.get('ManufacturerPartNumber') or '',
        'brand':   first.get('Manufacturer') or '',
    }


def _extract_unit_price(price_str):
    """Mouser returns prices like '$0.123' or '0,123 €' depending on locale.
    Pull out the first decimal-looking run of digits and dots/commas."""
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
    # Normalise: if there's exactly one comma and no dot, treat comma as dp.
    if digits.count(',') == 1 and '.' not in digits:
        digits = digits.replace(',', '.')
    else:
        digits = digits.replace(',', '')
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Refresh Part prices from Mouser's keyword-search API."

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug', default='',
            help='Only refresh this one part slug.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be recorded without writing snapshots.',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Cap the number of parts queried (0 = no cap).',
        )

    def handle(self, *args, **opts):
        api_key = _load_mouser_key()
        if not api_key:
            self.stdout.write(self.style.WARNING(
                "MOUSER_API_KEY not set and mouser_api_key.txt not found — "
                "nothing to refresh. (This is fine — manual snapshots still "
                "work from the Part detail page.)"
            ))
            return

        qs = Part.objects.all()
        if opts['slug']:
            qs = qs.filter(slug=opts['slug'])
        # Only parts with a usable search key.
        qs = qs.exclude(mpn='').exclude(mpn__isnull=True)
        if opts['limit']:
            qs = qs[:opts['limit']]

        parts = list(qs)
        if not parts:
            self.stdout.write(self.style.WARNING(
                "no parts match — set MPNs on your parts first"
            ))
            return

        dry_run = opts['dry_run']
        recorded = 0
        for part in parts:
            time.sleep(THROTTLE_SECONDS)
            result = _mouser_keyword_search(api_key, part.mpn)
            if result.get('error'):
                self.stdout.write(
                    f"  [skip] {part.slug} ({part.mpn}): {result['error']}"
                )
                continue

            breaks = result['breaks']
            if not breaks:
                self.stdout.write(
                    f"  [skip] {part.slug}: matched {result['mpn']} but no price breaks"
                )
                continue

            # Prefer qty=1; fall back to the first break available.
            qty1 = next(
                (b for b in breaks if int(b.get('Quantity') or 0) == 1),
                breaks[0],
            )
            unit_price = _extract_unit_price(qty1.get('Price'))
            qty_break = int(qty1.get('Quantity') or 1)
            if unit_price is None or unit_price <= 0:
                self.stdout.write(
                    f"  [skip] {part.slug}: could not parse price "
                    f"{qty1.get('Price')!r}"
                )
                continue

            source_url = result['part'].get('ProductDetailUrl', '') or ''
            msg = (
                f"  [{'dry-run' if dry_run else 'recorded'}] "
                f"{part.slug}: Mouser ${unit_price} @ qty {qty_break}"
            )
            self.stdout.write(msg)
            if dry_run:
                continue

            PartPriceSnapshot.objects.create(
                part=part, vendor='Mouser',
                unit_price_usd=unit_price, qty_break=qty_break,
                source_url=source_url[:500],
            )
            part.recompute_avg_price()
            recorded += 1

        self.stdout.write(self.style.SUCCESS(
            f"done — {recorded} snapshot{'' if recorded == 1 else 's'} written"
        ))

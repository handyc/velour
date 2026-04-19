"""Price-source adapters for powerlab.

Each source is a dict with:
  - name:          display name ('Mouser', 'Conrad', 'AliExpress')
  - vendor_label:  value stored in PartPriceSnapshot.vendor
  - auto_refresh:  bool — does `powerlab_refresh_prices` call it?
  - enabled():     bool — returns True if the source is configured
  - fetch(part):   dict — {'unit_price_usd', 'qty_break', 'source_url'} on
                   success, {'error': '...'} on recoverable failure, or
                   None if skipped. unit_price_usd is already converted to
                   USD (conversion rate noted in source_url query string).

The refresher iterates SOURCES in registration order.
"""
from decimal import Decimal

from . import mouser, conrad, aliexpress


# Pinned conversion rate — approximate, updated manually. Conrad quotes
# EUR; AliExpress usually quotes USD already. If this drifts by >5% the
# comparison chart gets noisy; just bump it and rerun the refresher.
EUR_TO_USD = Decimal('1.08')


SOURCES = [
    mouser.SOURCE,
    conrad.SOURCE,
    aliexpress.SOURCE,
]


def by_name(name):
    for s in SOURCES:
        if s['name'].lower() == (name or '').lower():
            return s
    return None


def enabled_sources():
    return [s for s in SOURCES if s.get('auto_refresh') and s['enabled']()]

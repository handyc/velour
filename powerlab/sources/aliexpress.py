"""AliExpress — manual-paste only.

AliExpress actively obfuscates prices (JS-rendered, region-specific,
anti-bot) and their affiliate API is gated behind approval. A scraper
here would rot inside a month. Instead this adapter is a placeholder:
it registers the vendor name so the comparison chart has a column for
it, and the manual-snapshot form on the Part detail page is the intake.

If you paste prices in from AliExpress, set vendor = 'AliExpress' (the
form accepts any string; this adapter is only here to make the spelling
canonical and put it in the chart).
"""


def _is_enabled():
    return True


def _fetch(part):
    return {'error': 'AliExpress is manual-paste only (see part detail page)'}


SOURCE = {
    'name':         'AliExpress',
    'vendor_label': 'AliExpress',
    'auto_refresh': False,
    'enabled':      _is_enabled,
    'fetch':        _fetch,
    'throttle_s':   0,
}

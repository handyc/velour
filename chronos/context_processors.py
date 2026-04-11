"""Topbar clock context processor.

Injects `chronos_topbar` into every template render so `base.html` can
include the topbar partial without each view needing to know about it.

Resilient to fresh installs: if the chronos table doesn't exist yet (no
migration applied), or any other failure, returns an empty dict so the
partial silently renders nothing instead of breaking unrelated pages.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def topbar_clock(request):
    try:
        from .models import ClockPrefs
        prefs = ClockPrefs.load()
        tz = ZoneInfo(prefs.home_tz)
        now_local = datetime.now(tz)
        return {
            'chronos_topbar': {
                'tz_name': prefs.home_tz,
                'iso_now': now_local.isoformat(),
                'epoch_ms': int(now_local.timestamp() * 1000),
                'format_24h': prefs.format_24h,
                'show_seconds': prefs.show_seconds,
                'auto_sync_ms': prefs.auto_sync_seconds * 1000,
            }
        }
    except Exception:
        return {}

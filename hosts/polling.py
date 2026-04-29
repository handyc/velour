"""Stdlib-only HTTP poller for RemoteHost entries.

Avoids adding `requests` as a dependency by using urllib.request directly.
Each poll is bounded by a short timeout so a single unreachable host can't
stall a "refresh all" sweep of a dozen nodes.
"""

import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.utils import timezone


POLL_TIMEOUT_SECONDS = 8
HISTORY_KEEP_PER_HOST = 500


def poll(host):
    """Synchronously poll one RemoteHost, updating its last_* fields in place.

    Does NOT call host.save() — callers do that so they control whether a
    failed poll should overwrite a previously-successful snapshot.

    Returns the updated host for chaining.
    """
    host.last_polled_at = timezone.now()
    host.last_error = ''

    req = Request(host.health_url, headers={
        'Authorization': f'Bearer {host.token}',
        'Accept': 'application/json',
        'User-Agent': 'velour-hosts-poller/1',
    })
    ctx = ssl.create_default_context()

    try:
        with urlopen(req, timeout=POLL_TIMEOUT_SECONDS, context=ctx) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            data = json.loads(body)
    except HTTPError as e:
        host.last_status = 'unreachable'
        host.last_error = f'HTTP {e.code} {e.reason}'
        host.last_snapshot = None
        return host
    except URLError as e:
        host.last_status = 'unreachable'
        host.last_error = f'connection error: {e.reason}'
        host.last_snapshot = None
        return host
    except (json.JSONDecodeError, ValueError) as e:
        host.last_status = 'unreachable'
        host.last_error = f'invalid JSON response: {e}'
        host.last_snapshot = None
        return host
    except Exception as e:
        host.last_status = 'unreachable'
        host.last_error = f'{type(e).__name__}: {e}'
        host.last_snapshot = None
        return host

    host.last_snapshot = data
    host.last_status = data.get('status') or 'green'
    return host


def record_poll(host):
    """Persist the current host.last_* fields as a HostPoll history row,
    then prune the per-host history to HISTORY_KEEP_PER_HOST. Call this
    after a `poll(host)` if you want history accumulated."""
    from .models import HostPoll
    snap = host.last_snapshot if isinstance(host.last_snapshot, dict) else None
    cpu_la = ((snap or {}).get('cpu') or {}).get('load_average') or []
    HostPoll.objects.create(
        host=host,
        status=host.last_status or 'unreachable',
        cpu_load=cpu_la[0] if cpu_la else None,
        mem_pct=((snap or {}).get('memory') or {}).get('percent_used'),
        disk_pct=((snap or {}).get('disk') or {}).get('percent_used'),
        error=host.last_error or '',
        snapshot=snap,
    )
    # Auto-prune: keep only the most recent N rows per host.
    keep_ids = list(
        HostPoll.objects
        .filter(host=host)
        .order_by('-at')
        .values_list('id', flat=True)[:HISTORY_KEEP_PER_HOST]
    )
    HostPoll.objects.filter(host=host).exclude(id__in=keep_ids).delete()


def poll_all_enabled():
    """Cron entrypoint — poll every enabled host, save last_*, record
    history. Returns a Counter-style dict of status → count."""
    from .models import RemoteHost
    counts = {}
    for host in RemoteHost.objects.filter(enabled=True):
        poll(host)
        host.save()
        record_poll(host)
        counts[host.last_status] = counts.get(host.last_status, 0) + 1
    return counts

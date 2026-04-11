"""Identity sensors — small functions that read the current state of
various Velour subsystems and return dicts.

Each sensor is allowed to fail (returns an empty dict on any exception)
so a single broken subsystem doesn't crash the tick engine. The whole
sensors module runs once per tick (default: every 10-15 minutes), so
performance is not critical — but each individual sensor should still
be cheap (no network calls, no heavy computation, no fan-spinning
loops). The whole point of the design is that Identity stays light.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def sense_load():
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().split()
        return {
            'load_1':  float(parts[0]),
            'load_5':  float(parts[1]),
            'load_15': float(parts[2]),
        }
    except Exception:
        return {}


def sense_memory():
    try:
        with open('/proc/meminfo') as f:
            mem = {}
            for line in f:
                if ':' in line:
                    k, v = line.split(':', 1)
                    mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get('MemTotal', 1)
        avail = mem.get('MemAvailable', total)
        return {
            'total_kb': total,
            'avail_kb': avail,
            'used_pct': (total - avail) / total,
        }
    except Exception:
        return {}


def sense_disk():
    try:
        import shutil
        usage = shutil.disk_usage('/')
        return {
            'total': usage.total,
            'used':  usage.used,
            'free':  usage.free,
            'used_pct': usage.used / usage.total if usage.total else 0.0,
        }
    except Exception:
        return {}


def sense_uptime():
    try:
        with open('/proc/uptime') as f:
            secs = float(f.read().split()[0])
        return {
            'seconds': secs,
            'days':    secs / 86400,
        }
    except Exception:
        return {}


def sense_chronos():
    """Local time, day-of-week, hour bucket, season hint, moon phase
    (only the four named phases, derived cheaply by date arithmetic
    rather than calling skyfield)."""
    try:
        from chronos.models import ClockPrefs
        prefs = ClockPrefs.load()
        tz = ZoneInfo(prefs.home_tz)
    except Exception:
        tz = ZoneInfo('UTC')
    now = datetime.now(tz)
    hour = now.hour
    if   5 <= hour < 11: tod = 'morning'
    elif 11 <= hour < 17: tod = 'afternoon'
    elif 17 <= hour < 22: tod = 'evening'
    else: tod = 'night'
    # crude season for the northern hemisphere
    m = now.month
    if   3 <= m < 6:  season = 'spring'
    elif 6 <= m < 9:  season = 'summer'
    elif 9 <= m < 12: season = 'autumn'
    else:             season = 'winter'
    return {
        'iso':     now.isoformat(),
        'hour':    hour,
        'weekday': now.strftime('%A').lower(),
        'tod':     tod,
        'season':  season,
        'moon':    _moon_phase(now),
    }


def _moon_phase(now):
    """Approximate moon phase via the synodic period (29.530589 days
    since a known new moon). Returns one of: new, waxing, full, waning."""
    from datetime import timezone
    known_new = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = (now - known_new).total_seconds() / 86400
    phase_age = days % 29.530589
    if phase_age < 1.5 or phase_age > 28.0:
        return 'new'
    if 13.0 < phase_age < 16.0:
        return 'full'
    return 'waxing' if phase_age < 14.7 else 'waning'


def sense_nodes():
    """How many physical microcontrollers exist and how recently they
    last reported in. Returns both aggregate counts AND a `details`
    list of per-node info so Session 4's thought composer can reference
    specific nodes by name ('Gary has been quiet since noon')."""
    try:
        from datetime import timedelta
        from django.utils import timezone as djtz
        from nodes.models import Node
        total = Node.objects.count()
        if total == 0:
            return {'total': 0, 'recently_seen': 0, 'silent': 0, 'details': []}
        recent_cutoff = djtz.now() - timedelta(hours=2)
        recent = Node.objects.filter(last_seen_at__gte=recent_cutoff).count()

        details = []
        now = djtz.now()
        for n in Node.objects.all()[:30]:  # cap for tick cost
            last_seen_ago = None
            if n.last_seen_at:
                last_seen_ago = int((now - n.last_seen_at).total_seconds())
            details.append({
                'slug':          n.slug,
                'nickname':      n.nickname,
                'last_seen_sec': last_seen_ago,
                'silent':        last_seen_ago is None or last_seen_ago > 7200,
            })

        return {
            'total':         total,
            'recently_seen': recent,
            'silent':        total - recent,
            'details':       details,
        }
    except Exception:
        return {}


def sense_mailroom():
    """Recent inbound mail volume."""
    try:
        from datetime import timedelta
        from django.utils import timezone as djtz
        from mailroom.models import InboundMessage
        cutoff = djtz.now() - timedelta(hours=24)
        return {
            'last_24h': InboundMessage.objects.filter(received_at__gte=cutoff).count(),
            'total':    InboundMessage.objects.count(),
        }
    except Exception:
        return {}


def sense_codex():
    """How active the documentation system is."""
    try:
        from codex.models import Manual, Section
        return {
            'manuals':  Manual.objects.count(),
            'sections': Section.objects.count(),
        }
    except Exception:
        return {}


def sense_experiments():
    """Named experiments the user has registered. Session 4 uses these
    as a source of subject names — 'I have been watching {experiment}'.
    Returns the experiment names and recent activity counts, not a
    count-only aggregate."""
    try:
        from experiments.models import Experiment
        exps = list(Experiment.objects.all()[:20])
        return {
            'total': len(exps),
            'names': [e.name for e in exps if e.name],
        }
    except Exception:
        return {}


def sense_calendar():
    """Upcoming chronos events within the next week, as a list of
    names. Session 4 uses these so Identity can anticipate and
    reference them in thought ('the calendar shows Ramadan ends on
    Saturday')."""
    try:
        from datetime import timedelta
        from django.utils import timezone as djtz
        from chronos.models import CalendarEvent
        cutoff = djtz.now() + timedelta(days=7)
        upcoming = CalendarEvent.objects.filter(
            start__gte=djtz.now(),
            start__lte=cutoff,
        ).order_by('start')[:10]
        return {
            'upcoming': [
                {'title': e.title, 'when': e.start.isoformat()}
                for e in upcoming
            ],
        }
    except Exception:
        return {}


def gather_snapshot():
    """Run every sensor and return the merged snapshot dict."""
    return {
        'load':        sense_load(),
        'memory':      sense_memory(),
        'disk':        sense_disk(),
        'uptime':      sense_uptime(),
        'chronos':     sense_chronos(),
        'nodes':       sense_nodes(),
        'mailroom':    sense_mailroom(),
        'codex':       sense_codex(),
        'experiments': sense_experiments(),
        'calendar':    sense_calendar(),
    }

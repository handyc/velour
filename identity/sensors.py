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
    """Upcoming chronos events + holidays. Session 4 used a 7-day
    window; Session 5 widens it to 30 days and separates user-created
    CalendarEvents from tradition-tagged holidays so the reflection
    composer can talk about them differently. Each holiday carries
    its Tradition name when known — Identity can reference "the
    Christian tradition of Easter" or "the Wiccan tradition of Imbolc"
    without needing an LLM to look up what those words mean."""
    try:
        from datetime import timedelta
        from django.utils import timezone as djtz
        from chronos.models import CalendarEvent
        now = djtz.now()
        cutoff = now + timedelta(days=30)

        upcoming_events = []
        upcoming_holidays = []

        qs = CalendarEvent.objects.filter(
            start__gte=now, start__lte=cutoff
        ).select_related('tradition').order_by('start')[:30]

        for e in qs:
            entry = {
                'title': e.title,
                'when':  e.start.isoformat(),
                'days_away': max(0, (e.start - now).days),
            }
            if getattr(e, 'tradition', None):
                entry['tradition'] = e.tradition.name
                upcoming_holidays.append(entry)
            else:
                upcoming_events.append(entry)

        # Limit to the first handful of each so the thought composer
        # doesn't have too much to choose from
        return {
            'upcoming':  upcoming_events[:10],
            'holidays':  upcoming_holidays[:10],
            'total_upcoming': len(upcoming_events) + len(upcoming_holidays),
        }
    except Exception:
        return {}


def sense_mailboxes():
    """Outgoing mail activity. Zero-cost count query, useful for
    reflection aggregation ('this week I sent N messages')."""
    try:
        from datetime import timedelta
        from django.utils import timezone as djtz
        from mailboxes.models import MailAccount
        cutoff = djtz.now() - timedelta(days=7)
        # mailboxes app may or may not have a Sent model — guard.
        try:
            from mailboxes.models import SentMessage
            sent_week = SentMessage.objects.filter(sent_at__gte=cutoff).count()
        except Exception:
            sent_week = 0
        return {
            'accounts': MailAccount.objects.count(),
            'sent_7d':  sent_week,
        }
    except Exception:
        return {}


def sense_hosts():
    """Other Velour instances this one polls. Counts only."""
    try:
        from hosts.models import RemoteHost
        total = RemoteHost.objects.count()
        if total == 0:
            return {'total': 0, 'healthy': 0, 'unhealthy': 0}
        healthy = RemoteHost.objects.filter(last_status='ok').count()
        enabled = RemoteHost.objects.filter(enabled=True).count()
        return {
            'total':     total,
            'enabled':   enabled,
            'healthy':   healthy,
            'unhealthy': enabled - healthy,
        }
    except Exception:
        return {}


def sense_services():
    """How many system services are running. Tries supervisorctl first
    (for production Velour deploys), then systemctl, then returns an
    empty dict if neither is reachable. None of these are required —
    if the sensor returns {} the rule engine just won't see service
    counts and moves on."""
    import subprocess

    # Try supervisorctl first — that's what production Velour uses.
    try:
        out = subprocess.run(
            ['supervisorctl', 'status'],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
            running = sum(1 for ln in lines if 'RUNNING' in ln)
            return {
                'total':   len(lines),
                'running': running,
                'source':  'supervisorctl',
            }
    except Exception:
        pass

    # Fallback: systemctl — count active services the user can see.
    try:
        out = subprocess.run(
            ['systemctl', '--user', 'list-units', '--type=service',
             '--state=running', '--no-legend', '--no-pager'],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
            return {
                'running': len(lines),
                'source':  'systemctl-user',
            }
    except Exception:
        pass

    return {}


def sense_logs():
    """Rough error volume from syslog/dmesg over the last 15 minutes.
    Grep-and-count. Cheap if logs are small; can be slow on busy hosts
    so we cap and time out fast."""
    try:
        import subprocess
        # Use dmesg as the cheapest source — it's a kernel ring buffer
        # and doesn't require reading arbitrarily large syslog files.
        out = subprocess.run(
            ['dmesg', '--ctime', '--level=err,crit,alert,emerg'],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0:
            return {}
        errs = [ln for ln in out.stdout.splitlines() if ln.strip()]
        return {'dmesg_errors': len(errs)}
    except Exception:
        return {}


def sense_terminal():
    """How actively the operator has been working on the system.
    The terminal app itself is session-based with no persisted
    models, so we read the shell history file instead — approximate
    but honest. Looks at ~/.bash_history modification time as a
    proxy for 'was the operator here recently'."""
    import os
    candidates = ['~/.bash_history', '~/.zsh_history']
    for path in candidates:
        expanded = os.path.expanduser(path)
        if not os.path.exists(expanded):
            continue
        try:
            st = os.stat(expanded)
            from datetime import timedelta
            from django.utils import timezone as djtz
            age_sec = djtz.now().timestamp() - st.st_mtime
            return {
                'history_path': path,
                'mtime_age_sec': int(age_sec),
                'mtime_age_hours': round(age_sec / 3600, 1),
                'recently_active': age_sec < 3600,
            }
        except OSError:
            continue
    return {}


def sense_state_machine():
    """State-machine summary — how often each mood transitions to
    each other mood. Used by the meditation composer to reference
    transition patterns in its prose. Computed from Tick history
    on every tick; cheap because the table is small."""
    try:
        from .state_machine import compute_transition_matrix, prose_summary
        matrix = compute_transition_matrix()
        return {
            'total_ticks':   matrix['total_ticks'],
            'unique_moods':  len(matrix['unique_moods']),
            'most_common':   matrix['most_common_transition'],
            'most_stable':   matrix['most_stable_mood'],
            'most_volatile': matrix['most_volatile_mood'],
            'prose':         prose_summary(matrix),
        }
    except Exception:
        return {}


def sense_identity_self():
    """Identity's own recent tick activity — a meta-sensor that lets
    the system reflect on its own attention cadence. 'This week I
    ticked 97 times, up from 83 last week.'"""
    try:
        from datetime import timedelta
        from django.utils import timezone as djtz
        from .models import Tick, Concern
        now = djtz.now()
        ticks_24h = Tick.objects.filter(at__gte=now - timedelta(hours=24)).count()
        ticks_7d  = Tick.objects.filter(at__gte=now - timedelta(days=7)).count()
        open_concerns = Concern.objects.filter(closed_at=None).count()
        total_concerns_7d = Concern.objects.filter(
            opened_at__gte=now - timedelta(days=7)
        ).count()
        return {
            'ticks_24h': ticks_24h,
            'ticks_7d':  ticks_7d,
            'open_concerns': open_concerns,
            'concerns_opened_7d': total_concerns_7d,
        }
    except Exception:
        return {}


def gather_snapshot():
    """Run every sensor and return the merged snapshot dict.

    Sensor modules that can fail for environmental reasons (dmesg not
    accessible, supervisor not installed, etc.) return {} from their
    try/except and the corresponding snapshot key just has an empty
    dict — the rule evaluator treats missing metrics as not-matching,
    so a broken sensor can't crash the tick."""
    return {
        'load':        sense_load(),
        'memory':      sense_memory(),
        'disk':        sense_disk(),
        'uptime':      sense_uptime(),
        'chronos':     sense_chronos(),
        'nodes':       sense_nodes(),
        'mailroom':    sense_mailroom(),
        'mailboxes':   sense_mailboxes(),
        'codex':       sense_codex(),
        'experiments': sense_experiments(),
        'calendar':    sense_calendar(),
        'hosts':       sense_hosts(),
        'services':    sense_services(),
        'logs':        sense_logs(),
        'terminal':    sense_terminal(),
        'self':          sense_identity_self(),
        'state_machine': sense_state_machine(),
    }

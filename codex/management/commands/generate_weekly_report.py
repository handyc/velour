"""Generate a weekly system status report as a Codex Manual.

Creates (or updates) a Manual with slug `weekly-status-{date}` containing
~10 sections of live system data written in Velour's first-person voice.

Usage:
    python manage.py generate_weekly_report
    python manage.py generate_weekly_report --date 2026-04-06
"""

import os
import socket
import subprocess
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from codex.models import Manual, Section


# ---------------------------------------------------------------------------
# upsert helpers (same pattern as seed_manuals.py)
# ---------------------------------------------------------------------------

def upsert_manual(slug, **fields):
    m, _ = Manual.objects.get_or_create(slug=slug, defaults=fields)
    for k, v in fields.items():
        setattr(m, k, v)
    m.save()
    return m


def upsert_section(manual, slug, sort_order, title, body, sidenotes=''):
    s, _ = Section.objects.get_or_create(
        manual=manual, slug=slug,
        defaults={'sort_order': sort_order, 'title': title},
    )
    s.sort_order = sort_order
    s.title = title
    s.body = body
    s.sidenotes = sidenotes
    s.save()
    return s


# ---------------------------------------------------------------------------
# data-gathering helpers
# ---------------------------------------------------------------------------

def _read_proc(path):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def _uptime_str():
    raw = _read_proc('/proc/uptime')
    if not raw:
        return 'unknown', 0
    secs = float(raw.split()[0])
    days = int(secs // 86400)
    hours = int((secs % 86400) // 3600)
    mins = int((secs % 3600) // 60)
    parts = []
    if days:
        parts.append(f'{days}d')
    if hours:
        parts.append(f'{hours}h')
    parts.append(f'{mins}m')
    return ' '.join(parts), secs


def _load_averages():
    raw = _read_proc('/proc/loadavg')
    if not raw:
        return None
    parts = raw.split()
    return {'1m': parts[0], '5m': parts[1], '15m': parts[2]}


def _memory_info():
    raw = _read_proc('/proc/meminfo')
    if not raw:
        return None
    info = {}
    for line in raw.splitlines():
        if ':' in line:
            key, val = line.split(':', 1)
            # values like "1234 kB"
            num = val.strip().split()[0]
            try:
                info[key.strip()] = int(num)
            except ValueError:
                pass
    total = info.get('MemTotal', 0)
    avail = info.get('MemAvailable', info.get('MemFree', 0))
    used = total - avail
    pct = (used / total * 100) if total else 0
    return {
        'total_mb': total // 1024,
        'used_mb': used // 1024,
        'avail_mb': avail // 1024,
        'pct': pct,
    }


def _disk_usage():
    mounts = ['/']
    # add /home if it's a separate mount
    try:
        with open('/proc/mounts') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == '/home':
                    mounts.append('/home')
    except Exception:
        pass
    results = []
    for mp in mounts:
        try:
            st = os.statvfs(mp)
            total = st.f_frsize * st.f_blocks
            free = st.f_frsize * st.f_bavail
            used = total - free
            pct = (used / total * 100) if total else 0
            results.append({
                'mount': mp,
                'total_gb': total / (1024 ** 3),
                'used_gb': used / (1024 ** 3),
                'free_gb': free / (1024 ** 3),
                'pct': pct,
            })
        except Exception:
            pass
    return results


def _listening_ports():
    try:
        out = subprocess.check_output(
            ['ss', '-tlnp'], timeout=5, stderr=subprocess.DEVNULL,
        ).decode()
        lines = []
        for line in out.strip().splitlines()[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 4:
                local = parts[3]
                lines.append(local)
        return lines
    except Exception:
        return []


def _failed_ssh():
    for path in ['/var/log/auth.log', '/var/log/secure']:
        try:
            out = subprocess.check_output(
                ['grep', '-c', 'Failed password', path],
                timeout=5, stderr=subprocess.DEVNULL,
            ).decode().strip()
            return int(out)
        except Exception:
            continue
    return None


def _sqlite_sizes():
    base = Path(settings.BASE_DIR)
    sizes = {}
    for p in base.glob('*.sqlite3'):
        sizes[p.name] = p.stat().st_size / (1024 * 1024)
    return sizes


# ---------------------------------------------------------------------------
# section composers
# ---------------------------------------------------------------------------

def _sec_executive_summary(report_date):
    hostname = socket.gethostname()
    uptime_s, uptime_sec = _uptime_str()
    load = _load_averages()
    mem = _memory_info()

    health = 'nominal'
    issues = []
    if mem and mem['pct'] > 85:
        health = 'elevated memory pressure'
        issues.append('memory')
    if load:
        try:
            cpu_count = os.cpu_count() or 1
            if float(load['1m']) > cpu_count * 0.9:
                health = 'high CPU load'
                issues.append('cpu')
        except ValueError:
            pass
    disks = _disk_usage()
    for d in disks:
        if d['pct'] > 85:
            health = 'disk space concern'
            issues.append('disk')

    body = (
        f"I am **{hostname}**, reporting for the week ending "
        f"**{report_date.strftime('%A %d %B %Y')}**.\n\n"
        f"- **Uptime:** {uptime_s}\n"
        f"- **Overall health:** {health}\n"
    )
    if load:
        body += f"- **Load (1/5/15 min):** {load['1m']} / {load['5m']} / {load['15m']}\n"
    if mem:
        body += f"- **Memory:** {mem['used_mb']} MB used of {mem['total_mb']} MB ({mem['pct']:.0f}%)\n"
    body += (
        "\nThis report is compiled automatically from live system data. "
        "Each section below expands on a different facet of my current state."
    )
    sidenotes = f'Generated {timezone.now():%Y-%m-%d %H:%M:%S %Z}'
    return body, sidenotes


def _sec_system_resources():
    load = _load_averages()
    mem = _memory_info()
    disks = _disk_usage()

    body = "## CPU\n\n"
    if load:
        body += (
            f"Load averages stand at **{load['1m']}** (1 min), "
            f"**{load['5m']}** (5 min), **{load['15m']}** (15 min). "
        )
        cpu_count = os.cpu_count() or 1
        body += f"I have **{cpu_count}** CPU core{'s' if cpu_count > 1 else ''} available.\n\n"
    else:
        body += "Load average data is unavailable on this platform.\n\n"

    body += "## Memory\n\n"
    if mem:
        body += (
            f"- **Total:** {mem['total_mb']} MB\n"
            f"- **Used:** {mem['used_mb']} MB ({mem['pct']:.1f}%)\n"
            f"- **Available:** {mem['avail_mb']} MB\n\n"
        )
    else:
        body += "Memory information is unavailable.\n\n"

    body += "## Disk\n\n"
    if disks:
        for d in disks:
            body += (
                f"- **{d['mount']}**: {d['used_gb']:.1f} GB used of "
                f"{d['total_gb']:.1f} GB ({d['pct']:.1f}% full), "
                f"{d['free_gb']:.1f} GB free\n"
            )
    else:
        body += "Disk usage data is unavailable.\n"

    sidenotes = 'Memory figures from /proc/meminfo; disk from os.statvfs.'
    return body, sidenotes


def _sec_identity_status():
    body = ""
    sidenotes = ""
    try:
        from identity.models import Identity, Tick, Concern
        ident = Identity.get_self()
        body += (
            f"My current mood is **{ident.mood}** at intensity "
            f"**{ident.mood_intensity:.1f}**.\n\n"
        )
        week_ago = timezone.now() - timedelta(days=7)
        tick_count = Tick.objects.filter(at__gte=week_ago).count()
        total_ticks = Tick.objects.count()
        body += (
            f"- **Ticks this week:** {tick_count}\n"
            f"- **Total ticks (all time):** {total_ticks}\n\n"
        )

        open_concerns = Concern.objects.filter(closed_at=None)
        if open_concerns.exists():
            body += f"I have **{open_concerns.count()}** open concern{'s' if open_concerns.count() != 1 else ''}:\n\n"
            for c in open_concerns[:10]:
                body += f"- **{c.label}** (severity {c.severity}) — opened {c.opened_at:%Y-%m-%d}\n"
        else:
            body += "I have no open concerns at the moment. All is well.\n"

        sidenotes = (
            f'Mood: {ident.mood} ({ident.mood_intensity:.1f})\n'
            f'{tick_count} ticks this week'
        )
    except Exception as e:
        body = f"Identity data is unavailable: {e}"

    return body, sidenotes


def _sec_node_fleet():
    body = ""
    sidenotes = ""
    try:
        from nodes.models import Node
        now = timezone.now()
        total = Node.objects.count()
        enabled = Node.objects.filter(enabled=True).count()
        recent_cutoff = now - timedelta(hours=2)
        recent = Node.objects.filter(last_seen_at__gte=recent_cutoff).count()
        silent = enabled - recent

        body += (
            f"My fleet consists of **{total}** registered node{'s' if total != 1 else ''}, "
            f"of which **{enabled}** {'are' if enabled != 1 else 'is'} enabled.\n\n"
            f"- **Reported in the last 2 hours:** {recent}\n"
            f"- **Silent (enabled but not heard from):** {silent}\n\n"
        )

        nodes = Node.objects.filter(enabled=True).order_by('nickname')
        if nodes.exists():
            body += "### Fleet roster\n\n"
            for n in nodes:
                if n.last_seen_at:
                    age = (now - n.last_seen_at).total_seconds()
                    if age < 3600:
                        status = "active"
                    elif age < 7200:
                        status = "recent"
                    else:
                        status = "silent"
                else:
                    status = "never seen"
                profile = n.hardware_profile.name if n.hardware_profile else 'unknown board'
                body += f"- **{n.nickname}** ({profile}) — {status}\n"

        sidenotes = (
            f'{total} nodes total\n'
            f'{recent} reporting\n'
            f'{silent} silent'
        )
    except Exception as e:
        body = f"Node data is unavailable: {e}"

    return body, sidenotes


def _sec_database_health():
    body = ""
    sidenotes = ""
    try:
        from databases.models import Database
        db_count = Database.objects.count()
        body += f"I track **{db_count}** database record{'s' if db_count != 1 else ''} in the databases app.\n\n"

        if db_count > 0:
            for db in Database.objects.all()[:20]:
                body += f"- **{db.name}** — {db.engine}\n"
            body += "\n"
    except Exception as e:
        body += f"Database app data is unavailable: {e}\n\n"

    sqlite_files = _sqlite_sizes()
    if sqlite_files:
        body += "### SQLite files on disk\n\n"
        for name, size_mb in sorted(sqlite_files.items()):
            body += f"- **{name}**: {size_mb:.2f} MB\n"
        sidenotes = '\n'.join(f'{n}: {s:.1f} MB' for n, s in sorted(sqlite_files.items()))
    else:
        body += "No SQLite files found in the project root.\n"

    return body, sidenotes


def _sec_mail_activity():
    body = ""
    sidenotes = ""
    try:
        from mail.models import MailAccount, InboundMessage
        acct_count = MailAccount.objects.count()
        week_ago = timezone.now() - timedelta(days=7)
        recent_msgs = InboundMessage.objects.filter(received_at__gte=week_ago).count()
        total_msgs = InboundMessage.objects.count()

        body += (
            f"I manage **{acct_count}** mail account{'s' if acct_count != 1 else ''}.\n\n"
            f"- **Inbound messages this week:** {recent_msgs}\n"
            f"- **Total inbound (all time):** {total_msgs}\n"
        )
        if acct_count:
            body += "\n### Accounts\n\n"
            for a in MailAccount.objects.all()[:20]:
                body += f"- **{a.address}**\n"

        sidenotes = f'{acct_count} accounts, {recent_msgs} messages this week'
    except Exception as e:
        body = (
            "The mail app is not available in this installation. "
            f"({e})"
        )

    return body, sidenotes


def _sec_codex_library():
    manual_count = Manual.objects.count()
    section_count = Section.objects.count()

    body = (
        f"The Codex library contains **{manual_count}** manual{'s' if manual_count != 1 else ''} "
        f"comprising **{section_count}** section{'s' if section_count != 1 else ''} in total.\n\n"
    )

    if manual_count:
        body += "### Catalog\n\n"
        for m in Manual.objects.all().order_by('title'):
            sc = m.sections.count()
            body += f"- **{m.title}** ({m.get_format_display()}, {sc} section{'s' if sc != 1 else ''})\n"

    sidenotes = f'{manual_count} manuals, {section_count} sections'
    return body, sidenotes


def _sec_aether_worlds():
    body = ""
    sidenotes = ""
    try:
        from aether.models import World, Entity, Script
        world_count = World.objects.count()
        entity_count = Entity.objects.count()
        script_count = Script.objects.count()

        body += (
            f"Aether hosts **{world_count}** world{'s' if world_count != 1 else ''}, "
            f"populated by **{entity_count}** entit{'ies' if entity_count != 1 else 'y'} "
            f"and driven by **{script_count}** script{'s' if script_count != 1 else ''}.\n\n"
        )

        if world_count:
            body += "### Worlds\n\n"
            for w in World.objects.all().order_by('name')[:20]:
                ec = Entity.objects.filter(world=w).count()
                body += f"- **{w.name}** — {ec} entit{'ies' if ec != 1 else 'y'}\n"

        sidenotes = f'{world_count} worlds, {entity_count} entities, {script_count} scripts'
    except Exception as e:
        body = f"Aether data is unavailable: {e}"

    return body, sidenotes


def _sec_security():
    body = "## Listening ports\n\n"
    ports = _listening_ports()
    if ports:
        for p in sorted(set(ports)):
            body += f"- `{p}`\n"
    else:
        body += "Could not enumerate listening ports (ss not available or no permission).\n"

    body += "\n## SSH authentication failures\n\n"
    failed = _failed_ssh()
    if failed is not None:
        body += f"There have been **{failed}** failed SSH password attempts in the auth log.\n"
    else:
        body += (
            "SSH failure count is unavailable — either no auth log exists "
            "or I lack permission to read it. This is expected on WSL "
            "and container environments.\n"
        )

    sidenotes = f'{len(ports)} listening ports'
    return body, sidenotes


def _sec_recommendations():
    recs = []
    mem = _memory_info()
    if mem and mem['pct'] > 85:
        recs.append(
            f"**High memory usage ({mem['pct']:.0f}%).** Consider identifying "
            "large processes or adding swap space."
        )
    if mem and mem['pct'] > 70:
        recs.append(
            f"Memory usage is at {mem['pct']:.0f}% — not critical yet, but worth watching."
        )

    disks = _disk_usage()
    for d in disks:
        if d['pct'] > 90:
            recs.append(
                f"**Disk {d['mount']} is {d['pct']:.0f}% full.** "
                "Immediate cleanup recommended."
            )
        elif d['pct'] > 75:
            recs.append(
                f"Disk {d['mount']} is at {d['pct']:.0f}% — consider pruning old files."
            )

    load = _load_averages()
    if load:
        try:
            cpus = os.cpu_count() or 1
            if float(load['15m']) > cpus:
                recs.append(
                    f"**Sustained high CPU load** (15-min avg {load['15m']} "
                    f"across {cpus} cores). Investigate heavy processes."
                )
        except ValueError:
            pass

    try:
        from nodes.models import Node
        now = timezone.now()
        cutoff = now - timedelta(hours=2)
        silent = Node.objects.filter(
            enabled=True,
        ).exclude(
            last_seen_at__gte=cutoff,
        )
        silent_names = list(silent.values_list('nickname', flat=True)[:5])
        if silent_names:
            recs.append(
                f"**Silent nodes:** {', '.join(silent_names)}. "
                "Check power, Wi-Fi, or firmware status."
            )
    except Exception:
        pass

    try:
        from identity.models import Concern
        open_count = Concern.objects.filter(closed_at=None).count()
        if open_count > 5:
            recs.append(
                f"**{open_count} open concerns** in Identity. "
                "Review whether any can be resolved or closed."
            )
    except Exception:
        pass

    sqlite_files = _sqlite_sizes()
    for name, size_mb in sqlite_files.items():
        if size_mb > 500:
            recs.append(
                f"**{name} is {size_mb:.0f} MB.** Consider vacuuming or archiving old data."
            )

    if not recs:
        recs.append("No issues detected. Everything looks healthy. Carry on.")

    body = "Based on the data gathered for this report, here are my recommendations:\n\n"
    for r in recs:
        body += f"- {r}\n"

    sidenotes = f'{len(recs)} recommendation{"s" if len(recs) != 1 else ""}'
    return body, sidenotes


# ---------------------------------------------------------------------------
# command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Generate a weekly system status report as a Codex Manual.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            help='Report date in YYYY-MM-DD format (default: today).',
        )

    def handle(self, *args, **options):
        if options.get('date'):
            report_date = date.fromisoformat(options['date'])
        else:
            report_date = date.today()

        slug = f'weekly-status-{report_date.isoformat()}'
        title = f'Weekly Status Report — {report_date.strftime("%d %B %Y")}'

        manual = upsert_manual(
            slug,
            title=title,
            subtitle=f'Automated system health report for the week ending {report_date}',
            format='short',
            author='Velour',
            version='1.0',
            abstract=(
                'This report is generated automatically by Velour\'s Codex '
                'engine. It gathers live system metrics, application state, '
                'and fleet telemetry into a single document for review.'
            ),
        )

        sections = [
            ('executive-summary',  10, 'Executive Summary',   _sec_executive_summary, {'report_date': report_date}),
            ('system-resources',   20, 'System Resources',    _sec_system_resources,  {}),
            ('identity-status',    30, 'Identity Status',     _sec_identity_status,   {}),
            ('node-fleet',         40, 'Node Fleet',          _sec_node_fleet,        {}),
            ('database-health',    50, 'Database Health',     _sec_database_health,   {}),
            ('mail-activity',      60, 'Mail Activity',       _sec_mail_activity,     {}),
            ('codex-library',      70, 'Codex Library',       _sec_codex_library,     {}),
            ('aether-worlds',      80, 'Aether Worlds',       _sec_aether_worlds,     {}),
            ('security-overview',  90, 'Security Overview',   _sec_security,          {}),
            ('recommendations',   100, 'Recommendations',     _sec_recommendations,   {}),
        ]

        for sec_slug, order, sec_title, composer, kwargs in sections:
            body, sidenotes = composer(**kwargs)
            upsert_section(manual, sec_slug, order, sec_title, body, sidenotes)
            self.stdout.write(f'  {sec_title}')

        self.stdout.write(self.style.SUCCESS(
            f'\nGenerated: {title} (slug: {slug}, {len(sections)} sections)'
        ))

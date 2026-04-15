"""Seed Reckoner with per-app profiles of every Velour app.

Each entry is a typical-user-day mix: a list of
(task_slug, count_per_day, optional note). Reckoner multiplies
count × task.energy_joules to get the app's daily envelope, then
matches it to the closest real-world signpost.

Estimates are deliberately rough — the point is a defensible
order-of-magnitude, not a certified LCA. Re-runnable.
"""

from django.core.management.base import BaseCommand

from reckoner.models import AppProfile, AppTaskUsage, ComputeTask


# (slug, name, description, order, [(task_slug, count, note), ...])
APPS = [
    ('dashboard', 'Dashboard',
     'The landing grid — Office Suite bar + every tool as a card.',
     10, [
        ('django-request', 20, 'Page loads per day'),
        ('sql-select', 60, 'Auth + menu queries per load'),
     ]),
    ('terminal', 'Terminal',
     'Interactive shell over WebSocket (Channels ASGI).',
     20, [
        ('django-request', 50, 'HTTP + WS upgrades'),
        ('bash-echo', 200, 'Shell commands typed'),
        ('stream-1080p-min', 20, '~20 min of terminal streaming'),
     ]),
    ('app_factory', 'App Factory',
     'Scaffolds new Django projects with deploy glue.',
     30, [
        ('django-request', 5, 'Occasional visits'),
        ('python-pandas', 1, 'Template rendering on project creation'),
     ]),
    ('sysinfo', 'System Info',
     'Host inventory: hostname, uptime, load, disks, processes.',
     40, [
        ('django-request', 5, 'Refreshes per day'),
        ('bash-echo', 30, 'subprocess fanout per page'),
     ]),
    ('agricola', 'Agricola',
     'Agar.io-style browser game.',
     50, [
        ('stream-1080p-min', 10, '~10 min of play'),
        ('django-request', 2, 'Page + score posts'),
     ]),
    ('graphs', 'Graphs',
     'Live and historical system-usage plots.',
     60, [
        ('django-request', 10, 'Dashboard refreshes'),
        ('sql-select', 20, 'Metric queries'),
        ('python-pandas', 2, 'matplotlib renders'),
     ]),
    ('services', 'Services',
     'nginx sites, supervisor programs, gunicorn.',
     70, [
        ('django-request', 3, 'Status checks'),
        ('bash-echo', 10, 'supervisorctl / systemctl calls'),
     ]),
    ('logs', 'Logs',
     'System-log viewer with filtering.',
     80, [
        ('django-request', 3, 'Page loads'),
        ('sql-heavy', 2, 'Filter scans over log indexes'),
     ]),
    ('identity', 'Identity',
     'Self-model — ticks, moods, concerns, reflections, meditations.',
     90, [
        ('django-request', 24, '1 Tick per hour'),
        ('sql-select', 48, 'Mood / concern lookups per tick'),
        ('python-pandas', 2, 'Reflection composition'),
     ]),
    ('security', 'Security',
     'SSH / firewall / ports / users / update audit.',
     100, [
        ('django-request', 2, 'Audit runs'),
        ('bash-echo', 15, 'Audit shellouts'),
     ]),
    ('landingpage', 'Landing Page',
     'Newspaper-style public chronicle.',
     110, [
        ('django-request', 10, 'Anonymous visits'),
        ('sql-select', 20, 'Article lookups'),
     ]),
    ('winctl', 'Windows',
     'Control Windows from WSL.',
     120, [
        ('django-request', 2, 'Occasional ops'),
        ('bash-echo', 4, 'wsl.exe / powershell.exe calls'),
     ]),
    ('maintenance', 'Maintenance',
     'Backup and restore /home directories.',
     130, [
        ('django-request', 1, 'Trigger page'),
        ('python-pandas', 5, 'Backup pass per day'),
     ]),
    ('hosts', 'Hosts',
     'Remote Velour instances with /api/health polling.',
     140, [
        ('hash-one-string', 300, 'Token-hash per poll'),
        ('django-request', 20, 'Status refreshes'),
     ]),
    ('mail', 'Mail',
     'Inbound messages, mail accounts, SMTP server.',
     150, [
        ('email-check', 50, 'IMAP fetches across accounts'),
        ('django-request', 10, 'Inbox page loads'),
     ]),
    ('experiments', 'Experiments',
     'Lightweight experiment tracker.',
     160, [
        ('django-request', 2, 'Page loads'),
        ('sql-select', 4, 'Experiment queries'),
     ]),
    ('nodes', 'Nodes',
     'ESP8266/ESP32 fleet + OTA + telemetry API.',
     170, [
        ('hash-one-string', 300, 'Health-token hashes'),
        ('django-request', 20, 'Fleet views + API hits'),
     ]),
    ('chronos', 'Chronos',
     'Clocks, timezones, calendar.',
     180, [
        ('django-request', 20, 'Topbar clock pings negligible; page loads dominate'),
        ('sql-select', 10, 'Event queries'),
     ]),
    ('databases', 'Databases',
     'Browse and query SQLite / MySQL / PostgreSQL.',
     190, [
        ('django-request', 5, 'Browser page loads'),
        ('sql-heavy', 3, 'Ad-hoc queries'),
     ]),
    ('codex', 'Codex',
     'Manuals rendered to Tufte-style PDFs with charts + Kroki.',
     200, [
        ('django-request', 5, 'Reader page loads'),
        ('python-pandas', 50, 'PDF + Mermaid + chart renders'),
     ]),
    ('attic', 'Attic',
     'Files — images, audio, video, documents.',
     210, [
        ('django-request', 10, 'Browsing'),
        ('webpage-heavy', 2, 'Large media uploads / previews'),
     ]),
    ('cartography', 'Cartography',
     'Multi-scale maps: Earth → sky → planets.',
     220, [
        ('webpage-light', 20, 'Map tile + leaflet loads'),
        ('django-request', 5, 'View page loads'),
     ]),
    ('oracle', 'Oracle',
     'Classical-ML decision trees for fast judgements.',
     230, [
        ('django-request', 2, 'UI loads'),
        ('python-hello', 50, 'Inference invocations'),
     ]),
    ('hpc', 'HPC',
     'SSH/SLURM entry point to compute clusters.',
     240, [
        ('django-request', 1, 'Rarely visited (stub).'),
     ]),
    ('tiles', 'Tiles',
     'Wang tiles as substrate for ideas.',
     250, [
        ('django-request', 10, 'Gallery page loads'),
        ('python-pandas', 5, 'Tile-set generation'),
     ]),
    ('condenser', 'Condenser',
     'Distill apps through constrained tiers.',
     260, [
        ('django-request', 3, 'Config page loads'),
        ('python-hello', 5, 'Distillation passes'),
     ]),
    ('automaton', 'Automaton',
     'Hex cellular automata — 4-colour Game-of-Life.',
     270, [
        ('stream-1080p-min', 5, '~5 min of simulation animation'),
        ('django-request', 2, 'Page loads'),
     ]),
    ('aether', 'Aether',
     'Immersive 3D browser worlds (three.js).',
     280, [
        ('stream-1080p-min', 20, '~20 min in world per day'),
        ('django-request', 10, 'Portal + list loads'),
     ]),
    ('lsystem', 'L-System',
     'Procedural plants and architecture with 3D preview.',
     290, [
        ('stream-1080p-min', 10, '3D preview sessions'),
        ('python-pandas', 3, 'Grammar expansion + meshing'),
     ]),
    ('legolith', 'Legolith',
     'Studded-brick worlds + worksheet / gallery PDFs.',
     300, [
        ('django-request', 15, 'World pages'),
        ('python-pandas', 50, 'Brick renders + PDF assembly'),
     ]),
    ('datalift', 'Datalift',
     'MySQL → Django + SQLite, with anonymisation.',
     310, [
        ('sql-heavy', 10, 'Source-schema introspection + bulk copy'),
        ('python-pandas', 5, 'Model synthesis and migration generation'),
     ]),
    ('reckoner', 'Reckoner',
     'The app you are looking at — compute cost explorer.',
     320, [
        ('django-request', 5, 'Browsing the gradient'),
        ('sql-select', 10, 'Task and signpost lookups'),
     ]),
    ('bridge', 'Bridge',
     'Aether ↔ Legolith object exchange.',
     330, [
        ('django-request', 2, 'Bridge UI'),
        ('sql-select', 5, 'Cross-app lookups'),
     ]),
]


class Command(BaseCommand):
    help = 'Seed Reckoner with a per-day compute-cost profile for every Velour app.'

    def handle(self, *args, **options):
        # Build a fast slug → ComputeTask map once.
        tasks = {t.slug: t for t in ComputeTask.objects.all()}

        missing = set()
        n_apps = 0
        n_usages = 0

        for slug, name, desc, order, mix in APPS:
            app, _ = AppProfile.objects.update_or_create(
                slug=slug,
                defaults=dict(name=name, description=desc, order=order),
            )
            # Replace the usage set wholesale so edits in this file
            # propagate cleanly on re-run.
            app.usages.all().delete()
            for entry in mix:
                task_slug = entry[0]
                count = entry[1]
                note = entry[2] if len(entry) > 2 else ''
                task = tasks.get(task_slug)
                if task is None:
                    missing.add(task_slug)
                    continue
                AppTaskUsage.objects.create(
                    app=app, task=task, count_per_day=count, note=note,
                )
                n_usages += 1
            n_apps += 1

        if missing:
            self.stdout.write(self.style.ERROR(
                '  missing tasks (run seed_reckoner first?): '
                + ', '.join(sorted(missing))
            ))
        self.stdout.write(self.style.SUCCESS(
            f'  apps: {n_apps} · usages: {n_usages}'
        ))

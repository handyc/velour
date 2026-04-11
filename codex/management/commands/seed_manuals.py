"""Seed preliminary Velour manuals into the codex.

Creates three Manual records (idempotent — re-runs update rather
than duplicate):

  velour-quickstart           Quickstart, ~6 sections, ~7 pages
  velour-working-tour         Medium tour, ~9 sections, ~12 pages
  velour-complete-reference   Large reference, 32 sections in a
                              4-part structure (most chapters are
                              still stubs)

Usage:

    python manage.py seed_manuals
        Seed all three.

    python manage.py seed_manuals --slug velour-working-tour
        Seed only the named manual.

The Quickstart is also seeded by this command for completeness,
even though the original was created by hand earlier in the
project. Re-running with --slug velour-quickstart restores it
if it gets accidentally deleted.
"""

from django.core.management.base import BaseCommand

from codex.models import Manual, Section


STUB_NOTE = (
    '*This section is a stub — the manual is preliminary. Ask Velour '
    'to expand it when ready.*'
)


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


# =====================================================================
# QUICKSTART
# =====================================================================

def seed_quickstart():
    m = upsert_manual(
        'velour-quickstart',
        title='Velour Quickstart',
        subtitle='A one-page introduction to your new lab control panel',
        format='quickstart',
        author='Velour',
        version='0.1',
        abstract=(
            'This manual is the smallest possible introduction to '
            'Velour. Read it once, and you should be able to log in, '
            'find your way around the dashboard, and know where to '
            'look when something needs attention.'
        ),
    )

    upsert_section(m, 'what-i-am', 10, 'What I am',
        """Velour is a Django meta-application that doubles as the control panel for a small lab. I run on port 7777 in development^[Production uses port 80/443 via nginx.] and behind nginx + supervisor in production.

I am organized as a collection of *apps*, each one responsible for a specific concern: **dashboard** for navigation, **chronos** for time, **databases** for SQL connections, **nodes** for the microcontroller fleet, and so on.

Everything you can do through the web UI you can also do through Django admin or the management shell.""",
        sidenotes='The default port (7777) is configured nowhere — it is just my preference.\nProduction uses port 80/443 via nginx.')

    upsert_section(m, 'logging-in', 20, 'Logging in',
        """Open http://localhost:7777/ in a browser. You should see a newspaper-style landing page called *The Velour Chronicle*. Click **Login** at the top right.

If this is a fresh checkout you will need to create a superuser first:

- Run `python manage.py createsuperuser`
- Pick a username and password
- Log in with those credentials""",
        sidenotes='The chronicle is just a marketing page. The real interface is the Dashboard at /dashboard/.')

    upsert_section(m, 'what-to-look-at-first', 30, 'What to look at first',
        """The Dashboard at /dashboard/ is a 4-column grid of cards, one per major feature. Click any card to open that area.

If nothing is broken, the most interesting things are usually:

- **Sysinfo** — current system load, memory, disk
- **Chronos** — what time it is right now, in your home timezone and any cities you watch
- **Nodes** — which microcontrollers have reported in recently
- **Logs** — what the system has been saying""",
        sidenotes='Cards reorder via templates/dashboard/home.html.')


# =====================================================================
# MEDIUM — Velour: A Working Tour
# =====================================================================

def seed_medium():
    m = upsert_manual(
        'velour-working-tour',
        title='Velour: A Working Tour',
        subtitle='A short, opinionated guide to the lab control panel',
        format='short',
        author='Velour',
        version='0.1 (preliminary)',
        abstract=(
            'This is the in-between manual: longer than the Quickstart, '
            'shorter than the Reference. It walks through the parts of '
            'Velour you actually use day-to-day — the dashboard, the '
            'time and calendar machinery, the microcontroller fleet, '
            'the documentation system itself, and the deploy pipeline. '
            'Read it once and you should know where everything lives.'
        ),
    )

    upsert_section(m, 'why-velour', 10, 'Why Velour exists',
        """Velour started as a single Django app meant to keep an eye on a small lab — the temperature in an aquarium, a few microcontrollers, the disk space on a workstation. It became something stranger: a Django *meta-application* that knows how to write other Django projects, manage them, deploy them, and document itself.

The name comes from velvet, the soft fabric that drapes over heavy machinery in old laboratories. Velour wraps the noisy parts of running a lab — secrets, deploys, sensor readings, log streams — in something with personality and edges, instead of leaving them as a heap of cron jobs and config files.

This manual is a short tour of the parts you'll touch most often. The Quickstart is shorter; the *Complete Reference* is much longer. This one sits in the middle: enough to feel oriented without drowning.

:::tip
If you want to understand the philosophy first, skip to *The meta-app idea*. If you just want to do something useful, start with *The dashboard tour* and double back.
:::""",
        sidenotes='Velour is built on Django 6.0, Python 3.12, SQLite for dev and Postgres for production.\nThe codebase is MIT-licensed; see LICENSE in the repo root.')

    upsert_section(m, 'meta-app-idea', 20, 'The meta-app idea',
        """Velour is one Django project with many `INSTALLED_APPS`. Some of those apps generate *other* Django projects. The pattern is unusual but practical: instead of running a tower of unrelated tools, you have one meta-tool that knows how to make new tools and absorb their concerns.

The most explicit example is the **app_factory** app. It owns templates for `gunicorn.conf.py`, `supervisor.conf`, `nginx.conf`, `setup.sh`, `adminsetup.sh`, `hotswap.sh`, and a `manage.py generate_deploy` command that emits all of them for a new project. New project = `python manage.py startapp_factory mything`. Five minutes later you have something running behind nginx + supervisor on a fresh server.

The second-most-explicit example is **codex** — this very documentation system. Codex generates PDFs from sections you write in markdown. You're reading one of those PDFs right now.

There's no fundamental reason a Django project can't be a meta-tool like this. Velour just leans into it.""",
        sidenotes='Other Django apps in the meta layer: identity (the system\'s sense of self), sysinfo (host introspection), security (audit checks).')

    upsert_section(m, 'dashboard-tour', 30, 'The dashboard tour',
        """The dashboard at `/dashboard/` is a 4×4 grid of cards on a desktop browser, collapsing to single-column horizontal strips on a phone. Each card is a feature area; click any card to open it.

## The cards

The 13 cards currently are: **Web Terminal**, **App Factory**, **System Info**, **Security**, **Logs**, **Services**, **Databases**, **Graphs**, **Identity**, **Maintenance**, **Windows**, **Agricola**, and **Codex**. There are three empty cells reserved for whatever comes next.

The grid order isn't alphabetical — it groups related concerns. Web Terminal and App Factory live next to each other because they're both about creating things; Security/Logs/Services/Databases form a single row of operational tools; Identity, Maintenance, and Windows handle housekeeping; Codex is the documentation home.

## The chronos topbar

Above the dashboard sits a small clock in the top-right corner of every page. That's **chronos** — Velour's sense of time. It shows the current date in the format `Sat 11 Apr 2026` and the time in 24-hour format (`14:50:26`) by default. Click the clock to open the chronos page proper, where you can see a wall of world clocks and the calendar.

## What's NOT on the dashboard

Several apps are first-class but don't have a dashboard card: **hosts** (remote velour-instance polling), **mailboxes** and **mailroom** (outbound and inbound email), **nodes** (the microcontroller fleet), and **experiments**. They're reachable from the navbar at the top of every page. The dashboard cards are a curated set, not a complete index.""",
        sidenotes='Phones get the same dashboard but with cards collapsed to compact horizontal strips — title on the left, action link on the right, description hidden.')

    # Stub sections
    upsert_section(m, 'time-and-calendar', 40, 'Time and the chronos calendar',
        f"""Chronos covers everything time-related: the topbar clock, the wall of world clocks, the month-grid calendar with religious and astronomical events, and the deep-time browsing modes that go from day all the way out to a millennium.

{STUB_NOTE}""")

    upsert_section(m, 'fleet', 50, 'The microcontroller fleet',
        f"""The **nodes** app tracks the physical microcontrollers in your lab — ESP8266s, ESP32s, Picos, anything with WiFi. Each node has a nickname, a hardware profile, an API token, and reports its sensor readings back to Velour.

{STUB_NOTE}""")

    upsert_section(m, 'codex-itself', 60, 'Documents and the codex',
        f"""Codex is Velour's documentation engine. Sections are markdown; rendering happens via fpdf2 with the ET Book typeface and a Tufte-flavored layout. Inline sparklines, Mermaid diagrams, callouts, tables, definition lists, and slope graphs are all available.

{STUB_NOTE}""")

    upsert_section(m, 'maintenance', 70, 'Maintenance basics',
        f"""The **maintenance** app handles backups and restores. Useful when you want to snapshot a `/home` directory before doing something risky.

{STUB_NOTE}""")

    upsert_section(m, 'deploying', 80, 'Deploying to production',
        f"""Velour's app_factory generates deploy artifacts (gunicorn config, supervisor config, nginx site, setup scripts) from templates. The production layout follows a strict convention: `/var/www/webapps/<user>/` is the project root, with `apps/`, `static/`, `media/`, `run/`, and `log/` as siblings.

{STUB_NOTE}""")

    upsert_section(m, 'quick-reference', 90, 'Quick reference',
        f"""Common commands and URLs:

| What | Where |
|---|---|
| Run dev server | `venv/bin/python manage.py runserver 7777` |
| Create superuser | `python manage.py createsuperuser` |
| Generate deploy artifacts | `python manage.py generate_deploy` |
| Snapshot a UI page | `python manage.py snapshot dashboard` |
| Seed holidays | `python manage.py seed_holidays` |
| Seed astronomy | `python manage.py seed_astronomy` |
| Seed manuals | `python manage.py seed_manuals` |
| Init health bearer token | `python manage.py init_health_token` |
| Init mail relay token | `python manage.py init_mail_relay_token` |

{STUB_NOTE}""")


# =====================================================================
# LARGE — Velour: The Complete Reference
# =====================================================================

APPS_TOC = [
    ('dashboard',    'Chapter 2 — dashboard'),
    ('terminal',     'Chapter 3 — terminal'),
    ('app_factory',  'Chapter 4 — app_factory'),
    ('sysinfo',      'Chapter 5 — sysinfo'),
    ('graphs',       'Chapter 6 — graphs'),
    ('services',     'Chapter 7 — services'),
    ('logs',         'Chapter 8 — logs'),
    ('identity',     'Chapter 9 — identity'),
    ('security',     'Chapter 10 — security'),
    ('landingpage',  'Chapter 11 — landingpage'),
    ('winctl',       'Chapter 12 — winctl'),
    ('maintenance',  'Chapter 13 — maintenance'),
    ('hosts',        'Chapter 14 — hosts'),
    ('mailboxes',    'Chapter 15 — mailboxes'),
    ('mailroom',     'Chapter 16 — mailroom'),
    ('experiments',  'Chapter 17 — experiments'),
    ('nodes',        'Chapter 18 — nodes'),
    ('chronos',      'Chapter 19 — chronos'),
    ('databases',    'Chapter 20 — databases'),
    ('codex',        'Chapter 21 — codex'),
]


def seed_large():
    m = upsert_manual(
        'velour-complete-reference',
        title='Velour: The Complete Reference',
        subtitle='Every app, every model, every command',
        format='complete',
        author='Velour',
        version='0.1 (preliminary)',
        abstract=(
            'This is the long manual — the one you reach for when the '
            'short manual ran out of road. It is organized in four '
            'parts: philosophy and architecture, an in-depth chapter '
            'for each Django app in INSTALLED_APPS, hands-on '
            'tutorials, and a reference appendix listing every model, '
            'every URL, every management command, every settings hook.'
            '\n\n'
            'It is preliminary: most chapters currently contain only '
            'their introductions and a placeholder note. Ask Velour '
            'to expand any specific chapter when you need it filled in.'
        ),
    )

    upsert_section(m, 'part-1-philosophy', 100, 'Part I — Philosophy & Architecture',
        """The first part of this reference covers the *why* and the *how* of Velour at the level of the whole project. It's ten or so chapters: what a meta-app is, how the deploy pipeline works, the secret-file protocol, the conventions that all the individual apps follow, the way templates are organized, the way static files are handled, and the way database migrations are managed.

If you're picking up Velour for the first time, read Part I before diving into Part II — the per-app chapters assume you already understand the conventions.""")

    upsert_section(m, 'meta-app-concept', 110, 'Chapter 1 — What a meta-app is',
        """Most Django projects are *applications*: a thing you run that does a thing for people. Velour is an *application about applications*. It is a Django project that contains apps which create, deploy, and document other Django projects, while also serving as the lab's day-to-day control panel.

This sounds clever and slightly recursive, and it is. The practical payoff is that the work of starting a new tool — wiring up gunicorn, writing supervisor configs, generating an nginx vhost, setting up cron, writing a README, creating a deploy script — collapses into a single management command. Velour has done it before for itself; it knows how to do it again.

## The four meta-app loops

There are four self-referential loops to understand:

- **app_factory** generates entirely new Django projects from templates. Velour itself was generated this way originally and is now its own template seed.
- **codex** generates documentation about Velour from markdown stored in the database. This very chapter is one such document.
- **identity** maintains a singleton row describing who Velour is — name, mood, hostname, admin email — so the system can talk about itself coherently.
- **sysinfo** introspects the host machine and reports back, allowing Velour to look at itself from the outside.

Each loop is small. Together they make Velour a system that knows what it is, where it lives, what it does, and how to write that down.

## The unusual design choice

The unusual choice is that templates for *generated* Django projects live inside the **app_factory** Django app's `templates/deploy/` directory, alongside templates for the project's own UI. This is the same Django template loading machinery doing two completely different jobs: one set of templates renders HTML for a web user, the other set renders config files for a deployment.

It works because `render_to_string` doesn't care whether the template is HTML or shell script. The naming convention `templates/deploy/*.{conf,sh,py}.tmpl` keeps them obviously separate.

*This chapter has more sections to be written: how the templates pass values, how the rendering knows the target user/host, and how the generated project then becomes a parent for further generations.*""",
        sidenotes='The meta-app concept isn\'t unique to Velour — Django\'s own admin app is meta in the same way. But Velour leans into it harder.')

    # Per-app chapter stubs
    for i, (slug, title) in enumerate(APPS_TOC, start=1):
        sort = 200 + i * 10
        body = f"""This chapter covers the **{slug}** app in depth. Topics: model reference, view reference, URL reference, configuration, conventions specific to this app, and at least one worked tutorial.

{STUB_NOTE} The chapter framework is in place so the table of contents and the section ordering are stable."""
        upsert_section(m, f'chapter-{slug}', sort, title, body)

    # Part III tutorials
    upsert_section(m, 'part-3-tutorials', 500, 'Part III — Tutorials',
        """The tutorial chapters walk through end-to-end workflows. Each is intended as a single sitting's worth of work: pick one, read it through, then do it.

Tutorials currently planned (most are stubs):

- Setting up Velour on a fresh server
- Adding a microcontroller node (Gary walkthrough)
- Writing your first Codex manual
- Scheduling a recurring weekly status report
- Migrating Velour from one host to another
- Backing up and restoring user data""")

    upsert_section(m, 'tut-fresh-install', 510, 'Tutorial 1 — Fresh install',
        f"{STUB_NOTE}\n\nThis tutorial will walk through provisioning Velour on a freshly-installed Linux server, from `apt-get install python3` through `runserver 7777` to behind-nginx production.")

    upsert_section(m, 'tut-add-node', 520, 'Tutorial 2 — Adding a node',
        f"{STUB_NOTE}\n\nThis tutorial will walk through adding a new ESP8266 to the lab fleet, from physical hardware setup through firmware flashing to first sensor reading visible in the dashboard.")

    upsert_section(m, 'tut-first-manual', 530, 'Tutorial 3 — Writing your first Codex manual',
        f"{STUB_NOTE}\n\nA gentle tour of the markdown subset, the figure system, and the section ordering — building a small ten-page manual from scratch.")

    # Part IV reference
    upsert_section(m, 'part-4-reference', 700, 'Part IV — Reference',
        """The reference appendix lists everything in machine-readable form: settings, URL routes, models, management commands, environment variables. Use this for lookup, not for reading.

*Most reference subsections are stubs. They will be auto-generated from introspection in a future iteration via Codex periodic reports.*""")

    upsert_section(m, 'ref-settings', 710, 'Reference A — settings.py', STUB_NOTE)
    upsert_section(m, 'ref-urls',     720, 'Reference B — URL routes', STUB_NOTE)
    upsert_section(m, 'ref-models',   730, 'Reference C — Models', STUB_NOTE)
    upsert_section(m, 'ref-commands', 740, 'Reference D — Management commands', STUB_NOTE)
    upsert_section(m, 'ref-env',      750, 'Reference E — Environment variables', STUB_NOTE)


SEEDERS = {
    'velour-quickstart':         seed_quickstart,
    'velour-working-tour':       seed_medium,
    'velour-complete-reference': seed_large,
}


class Command(BaseCommand):
    help = 'Seed preliminary Velour manuals (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--slug', default='',
                            help='Seed only the named manual slug.')

    def handle(self, *args, **opts):
        slug = opts['slug'].strip()
        if slug:
            if slug not in SEEDERS:
                self.stderr.write(self.style.ERROR(
                    f'Unknown slug: {slug}. '
                    f'Known: {", ".join(SEEDERS)}'
                ))
                return
            SEEDERS[slug]()
            self.stdout.write(self.style.SUCCESS(f'Seeded {slug}.'))
            return

        for s, fn in SEEDERS.items():
            fn()
            m = Manual.objects.get(slug=s)
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ {s} ({m.sections.count()} sections)'
            ))
        self.stdout.write(self.style.SUCCESS(
            f'Done. {Manual.objects.count()} manuals total.'
        ))

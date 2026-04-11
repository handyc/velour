"""Seed preliminary Velour manuals into the codex.

Creates three Manual records (idempotent — re-runs update rather
than duplicate):

  velour-quickstart           Quickstart, ~6 sections
  velour-working-tour         Medium tour, ~9 sections
  velour-complete-reference   Large reference. Part IV is
                              auto-generated from live introspection
                              of settings, urls, models, commands,
                              env vars — re-running this command
                              picks up code changes automatically.

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

from codex.introspection import (
    commands_for_app, commands_section, env_section, models_for_app,
    models_section, settings_section, urls_for_app, urls_section,
)
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

    # Per-app chapter stubs. Chronos is hand-written; the others get
    # a brief intro stub plus auto-introspected models / urls / commands
    # for that app — so each chapter has real content even before the
    # narrative is written.
    for i, (slug, title) in enumerate(APPS_TOC, start=1):
        sort = 200 + i * 10
        if slug == 'chronos':
            body = _chronos_chapter()
        else:
            intro = f"""This chapter covers the **{slug}** app. The narrative section is still a stub — the model, URL, and command tables below are auto-generated from the live codebase by `python manage.py seed_manuals`, so they update automatically when the code changes.

{STUB_NOTE}"""
            sections = [intro]
            m_block = models_for_app(slug)
            if m_block:
                sections.append(m_block)
            u_block = urls_for_app(slug)
            if u_block:
                sections.append(u_block)
            c_block = commands_for_app(slug)
            if c_block:
                sections.append(c_block)
            body = '\n\n'.join(sections)
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

    upsert_section(m, 'ref-settings', 710, 'Reference A — settings.py',
        f"""Selected entries from `velour/settings.py`. The full file has
many more lines than this — these are the ones most often touched
by an operator.

{settings_section()}

*This section is auto-generated from live settings introspection
by `python manage.py seed_manuals`. Re-running picks up changes.*""")

    upsert_section(m, 'ref-urls', 720, 'Reference B — URL routes',
        f"""Every URL pattern registered in the project, walked from the
root resolver. Admin sub-URLs are excluded for brevity.

{urls_section()}

*Auto-generated from `django.urls.get_resolver()` walking.*""")

    upsert_section(m, 'ref-models', 730, 'Reference C — Models',
        f"""Every Django model in every non-builtin app. For each model:
the docstring (if any), the field table, and ordering / index
metadata. Reverse relations are omitted.

{models_section()}

*Auto-generated from `django.apps.apps.get_app_configs()`.*""")

    upsert_section(m, 'ref-commands', 740, 'Reference D — Management commands',
        f"""Every `python manage.py <command>` registered by a non-builtin
app, with its short help text. Run any of these with `--help` for
the full argument list.

{commands_section()}

*Auto-generated from `django.core.management.get_commands()`.*""")

    upsert_section(m, 'ref-env', 750, 'Reference E — Environment variables',
        f"""Environment variables that `velour/settings.py` reads via
`os.environ.get(...)`. The defaults and exact lookup logic live
in settings.py — this is just a quick index.

{env_section()}

*Auto-generated by grepping settings.py for os.environ.get patterns.*""")


# --- hand-written sample chapter (chronos) -------------------------------


def _chronos_chapter():
    return """The **chronos** app is Velour's sense of time. It started as a small home-clock display in the navbar and grew into a full calendar with religious and astronomical events stretching deep into the past and the future. This chapter walks through every part of it: the data model, the rendering pipeline, the holiday and astronomy adapters, and the deep-time browsing modes.

## Why chronos exists

A lab control panel needs to know what time it is, but it usually needs to know that in *several* timezones at once. The lab might be in Leiden but the people the operator collaborates with are in NYC, Denver, Auckland, and Bangkok. The aquarium controller (Gary) might be on UTC. The data analysis batch jobs might be on whatever the cloud server happens to be set to.

Chronos solves this with a singleton `ClockPrefs` row that stores the operator's home timezone, plus a `WatchedTimezone` table that pins additional cities. Both are exposed via a context processor that injects a small clock into every page render — so the operator always knows the local time without leaving whatever page they're working on.

The calendar layer was added later, in Phase 2 of the chronos roadmap. It reuses the `ClockPrefs.home_tz` setting to know which timezone to interpret event start/end times in.

## Models

There are five models in chronos:

:::def
ClockPrefs: singleton, stores home timezone, 12/24h preference, show-seconds, auto-resync interval, and a country code used by the civic holiday adapter
WatchedTimezone: pinned world clocks shown on the /chronos/ page
Tradition: a holiday tradition (civic, christianity, judaism, etc) — color, enabled flag, description
CalendarEvent: one scheduled event with start/end/all_day/color/tags/source/tradition FK
:::

The `CalendarEvent` model is shared between user-scheduled events and auto-seeded holidays / astronomical events. The `source` enum distinguishes them (`user`, `holiday`, `astro`, `feed`) and the optional `tradition` foreign key ties holiday/astro rows to their parent grouping. User events have `source='user'` and `tradition=None`.

This unified model means the calendar grid view doesn't have to special-case anything — it queries `CalendarEvent` once and renders everything that touches the visible date range.

## The topbar context processor

The clock that appears in the top-right of every page is rendered by `chronos.context_processors.topbar_clock`. It runs on every request, loads the singleton `ClockPrefs` row, computes the current time in the home timezone, and returns a context dict that the `_topbar_clock.html` partial uses.

The partial sets four data attributes on the topbar div: the IANA timezone name, the server-side epoch_ms baseline, the 12/24-hour format flag, and the auto-sync interval. A small piece of JavaScript in `static/js/chronos.js` then ticks the clock every second by adding `Date.now()` to the offset captured at page load. Every N seconds (default 600) it re-syncs against `/chronos/now.json` so accumulated drift never exceeds the configured interval.

There's a subtle browser quirk worth knowing about. The data attribute name was originally `data-format-24h`, but per the HTML5 dataset spec, when a dash is followed by an ASCII digit (the "2" in "24h") the dash is *not* removed in the JavaScript dataset conversion — so `topbar.dataset.format24h` returned undefined and the clock silently rendered in 12-hour format regardless of the prefs. The fix was to rename the attribute to `data-hour-format` with values "24" or "12".

## The world clocks page

`/chronos/` shows the home clock first (in green) followed by every `WatchedTimezone` row in user-defined sort order. Each clock is a horizontal strip filling the full available width: city name on the left, IANA timezone in small grey monospace below it, current date and time in the middle, UTC offset on the right, and edit/delete buttons at the far right.

Each strip is rendered server-side at page load time with the actual current time, then taken over by the same JavaScript ticker that handles the topbar.

Cities of special interest can be tinted with a per-row hex color. The original use case was marking the cities the operator's project collaborators live in: Tampa in saffron, Sao Paulo in forest green, London in brick orange, Leiden in moss green, and so on. Untinted clocks display in the default neutral grey.

## The calendar grid

`/chronos/calendar/` is a 7-column month grid with day cells that are always perfect squares. The cell size is computed by a single CSS `min()` expression in the page CSS: it picks the smaller of `(viewport width − margin) / 7` and `(viewport height − chrome) / 6.6`, so the entire calendar always fits within the visible viewport on both axes — no horizontal or vertical scrolling, on either a desktop or a phone.

The 6.6 row count covers six possible week rows (the maximum any month can have) plus 0.6 of a cell for the header row above them.

## Holiday adapters

Phase 2b of chronos added eleven holiday source adapters under `chronos/holiday_sources/`. Each is a small module exposing `get(year)` that returns a list of `(date, name)` tuples for the requested Gregorian year. The seeder iterates the registry and creates `CalendarEvent` rows attached to the matching `Tradition`.

Sources used:

| Tradition | Library | Notes |
|---|---|---|
| civic | `holidays` | Country selected via `ClockPrefs.country` |
| christianity | `dateutil.easter` | Easter + dependent feasts + fixed feasts |
| judaism | `pyluach` | Hebrew calendar |
| islam | `hijridate` | Hijri calendar |
| hinduism | `holidays.India` | With fallback to fixed approximate dates |
| buddhism | `holidays.Sri Lanka` | Filtered by Buddhist keyword |
| chinese | `cnlunar` | Lunisolar walker |
| shinto | hand-curated | Fixed Gregorian dates per modern Japanese practice |
| daoism | `cnlunar` | Lunisolar walker for deity birthdays |
| confucianism | hand-curated | Fixed Gregorian dates |
| wicca | hand-curated | Eight sabbats (4 fixed + 4 approximate solar) |

Run `python manage.py seed_holidays --year-from 2026 --year-to 2030` to populate five years of holidays in one shot.

## Astronomy adapters

Phase 2c added astronomical events via skyfield using the JPL DE421 ephemeris (downloaded automatically on first use to `chronos/data/`, ~17MB, gitignored).

Five sources in `chronos/astro_sources/`:

- **equinoxes.py**: vernal/autumnal equinoxes, summer/winter solstices via `skyfield.almanac.seasons`
- **moon_phases.py**: full moons (with traditional names — Wolf, Snow, Worm, Pink, Flower, Strawberry, Buck, Sturgeon, Harvest, Hunter's, Beaver, Cold) and new moons; first/last quarters omitted to keep the calendar uncluttered
- **eclipses.py**: solar and lunar eclipses, computed by checking sun/moon angular separation at each new and full moon
- **meteors.py**: hand-curated table of major annual meteor shower peaks
- **_skyfield_loader.py**: lazy ephemeris loading + caching across calls

Run `python manage.py seed_astronomy --year-from 2026 --year-to 2030` to populate.

## Deep-time browsing

Phase 2d added scale modes that drill from a single day all the way out to a millennium:

| Scale | URL | What you see |
|---|---|---|
| month | `/chronos/calendar/<y>/<m>/` | 7×6 day grid, the default |
| day | `/chronos/calendar/<y>/<m>/<d>/` | event list for one day |
| year | `/chronos/calendar/year/<y>/` | 12 mini month grids in a 4×3 layout |
| decade | `/chronos/calendar/decade/<start>/` | 10 year cells with event counts |
| century | `/chronos/calendar/century/<start>/` | 10 decade cells |
| millennium | `/chronos/calendar/millennium/<start>/` | 10 century cells |

Each scale's toolbar links upward to the next-larger scale and downward to the next-smaller. Click a cell at any level to drill in.

The current scale chain stops at the millennium. 10K-year and 100K-year scales are not implemented because nothing in the existing data sources extrapolates cleanly that far — only astronomical events would still be meaningful, and their accuracy degrades over geological timescales. The UI pattern is identical, so adding them is a small change when needed.

## Event CRUD

Users create events through `/chronos/events/add/` (or by clicking "New Event" from the calendar toolbar). The form uses HTML `datetime-local` inputs interpreted in the user's home timezone — no naive UTC trap. Events are referenced everywhere by their auto-generated slug, not their numeric primary key, so URLs stay readable.

A `?date=YYYY-MM-DD` query parameter on the add form pre-fills the start date to the clicked day. Clicking "Add one" from a day-detail view that has no events takes you to the form already pre-filled.

## Recommended reading order

If you're new to chronos and want to understand it from the inside out:

- Read `chronos/models.py` to see the five models and how they relate.
- Open `/chronos/` in a browser to see the world clocks page — the simplest view.
- Open `/chronos/calendar/` to see the month grid — the most complex view.
- Read `chronos/views.py` end-to-end. It's about 350 lines and covers everything.
- Run `python manage.py seed_holidays` and `python manage.py seed_astronomy` to populate a year of events, then re-open the calendar.
- Read `chronos/holiday_sources/__init__.py` to see how the eleven traditions are registered.
"""


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

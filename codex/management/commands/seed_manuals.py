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

It works because `render_to_string` doesn't care whether the template is HTML or shell script. The naming convention `templates/deploy/*.{conf,sh,py}.tmpl` keeps them obviously separate.""",
        sidenotes='The meta-app concept isn\'t unique to Velour — Django\'s own admin app is meta in the same way. But Velour leans into it harder.')

    upsert_section(m, 'deploy-pipeline', 120, 'Chapter 1.5 — The deploy pipeline',
        """A Velour deploy is a one-shot bundle of generated artifacts that the operator scp's onto a fresh server, runs `setup.sh`, and walks away from. The pipeline is small enough to read end-to-end in an afternoon, and that smallness is the design.

## The four artifacts

`python manage.py generate_deploy` produces four files for a target user/host pair:

- **`gunicorn.conf.py`** — the gunicorn worker config. Bind path, worker count, log paths, the Python path adjustments needed for Velour to run.
- **`supervisor.conf`** — the supervisor program declaration that owns the gunicorn process. Restart policy, log rotation, the user the process runs as.
- **`nginx.conf`** — the nginx vhost. SSL config (or HTTP-only fallback), the static / media path mounts, the upstream socket path that gunicorn binds to.
- **`setup.sh`** — the one-shot bootstrap script that the operator runs as root on the target host. Creates the project user, the `/var/www/webapps/<user>/` directory tree, installs system packages, drops the supervisor and nginx files into place, and reloads both services.

A fifth artifact, `adminsetup.sh`, is for the operator's own machine: it rsyncs the project tree to the server while excluding venv/, db.sqlite3, and the secret token files. `hotswap.sh` is similar but assumes the server is already set up and only pushes code changes.

## The user/dir/socket convention

Every Velour deploy follows a strict naming convention:

:::def
User: a Linux user named after the project (e.g., `swibliq` for the production Velour)
Project root: `/var/www/webapps/<user>/`
App tree: `/var/www/webapps/<user>/apps/<projectname>/`
Static files: `/var/www/webapps/<user>/static/`
Media files: `/var/www/webapps/<user>/media/`
Run sockets: `/var/www/webapps/<user>/run/<projectname>.sock`
Logs: `/var/www/webapps/<user>/log/`
:::

This convention is hardcoded into the deploy templates because consistency across hosts is more valuable than per-host flexibility. When you ssh into a new server you already know where everything is.

## generate_deploy

The management command takes optional `--server-name`, `--user`, and `--project` arguments. If you don't pass them, the command reads `Identity.hostname` for the server name (which is why the identity app is load-bearing for the deploy pipeline), and the current Django settings for project name and user.

The command writes the artifacts to the project's `deploy/` directory. From there, scp them to the target host.""")

    upsert_section(m, 'secret-file-protocol', 130, 'Chapter 1.7 — The secret-file protocol',
        """Velour stores its secrets as plain text files in `BASE_DIR`, chmod 600, owned by the project user. There is no settings.py constant for any secret, no environment variable for any secret, and no encrypted vault. Secrets are files.

This is unusual enough to warrant explanation.

## The four secret files

- **`secret_key.txt`** — Django's `SECRET_KEY`. Read by settings.py at startup if the file is present, falling back to an env var, falling back to an insecure dev default.
- **`health_token.txt`** — bearer token for the `/sysinfo/health.json` endpoint. Generated by `python manage.py init_health_token`.
- **`mail_relay_token.txt`** — bearer token for the `/mailboxes/relay/` endpoint. Generated by `python manage.py init_mail_relay_token`.
- **`*.token`** — wildcard reserved for future per-app tokens.

All four are in `.gitignore`. `adminsetup.sh` and `hotswap.sh` rsync exclude them as well, so dev secrets never leak to prod and prod secrets never get clobbered when the operator pushes code.

## Why files instead of env vars

Three reasons:

First, files have permissions. `chmod 600 secret_key.txt` is a real, kernel-enforced barrier — only the file's owner can read it. Environment variables, by contrast, are visible to anything that can run `ps -ef` or read `/proc/<pid>/environ`. For a single-tenant lab control panel running as a non-root user, file permissions are the right granularity.

Second, files are bootstrapped automatically. The `init_*_token` management commands create them on first run with chmod 600 already set. The operator doesn't have to remember a separate "set this env var before starting the server" step.

Third, files are inspectable. The operator can `cat health_token.txt` to see the current value and copy-paste it into a remote `RemoteHost` configuration. Env vars require a shell session.

## Rotation

Re-running any `init_*_token` command with `--force` overwrites the file with a fresh random token. The old token is now invalid. Anywhere the old token was being used (other Velour instances polling this one's health endpoint, external apps posting to the mail relay) needs to be updated by hand.

There's no automatic rotation schedule. The tokens are 48-character random strings; the operator rotates them when they want to.""")

    upsert_section(m, 'app-conventions', 140, 'Chapter 1.9 — App layout conventions',
        """Every Velour app follows the same on-disk layout. The conventions are not unusual but they ARE strict, and the strictness is what lets the meta-layer (app_factory, codex introspection) work without per-app exceptions.

## The directory tree

```
appname/
    __init__.py
    apps.py
    admin.py
    models.py
    views.py
    urls.py
    migrations/
        __init__.py
        0001_initial.py
```

That's the minimum. Some apps add `management/commands/` for management commands, `templatetags/` for template tag libraries, or sub-packages for non-trivial logic (codex has `codex/rendering/`, chronos has `chronos/holiday_sources/` and `chronos/astro_sources/`).

## Templates

Templates do **not** live inside the app directory. They live under `templates/<appname>/` at the project root. This is one of the few places Velour deviates from Django's own template-loading default behavior.

The reason is consistency: every page across the project extends the same `templates/base.html`, and having a single top-level templates directory makes the inheritance chain obvious. Apps that need their own template subdirectory create `templates/<appname>/`.

## Static files

Source CSS lives in `static/css/style.css` (one file for the whole project — Velour does not use per-app CSS). Source JS lives in `static/js/`. Bundled fonts live under `static/fonts/`. The collectstatic output goes to `staticfiles/` which is gitignored.

## URLs

Each app's `urls.py` defines an `app_name` and a list of `urlpatterns`. The project-level `velour/urls.py` includes each app under a single prefix: `path('chronos/', include('chronos.urls'))` and so on. Cross-app URL references use the namespace: `{% url 'chronos:home' %}`.

## Models

App labels are short and lowercase. Model names are CamelCase singulars. Foreign keys point at app_label.ModelName strings to avoid circular imports.

The `id` field is `BigAutoField` everywhere (set in each app's `apps.py` config) — Velour was started after Django moved to BigAutoField as the default and there's no reason to use the older AutoField.""")

    # Per-app chapter stubs. Chronos is hand-written; the others get
    # a one-page narrative intro plus auto-introspected models / urls
    # / commands for that app, so every chapter has real content.
    for i, (slug, title) in enumerate(APPS_TOC, start=1):
        sort = 200 + i * 10
        if slug == 'chronos':
            body = _chronos_chapter()
            upsert_section(m, f'chapter-{slug}', sort, title, body)
            continue

        intro = APP_INTROS.get(slug) or f"""This chapter covers the **{slug}** app. The narrative section is still a stub.

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
        """This tutorial walks through provisioning Velour on a freshly-installed Linux server, from `apt-get install python3` through `runserver 7777` to behind-nginx production.

## Prerequisites

A Linux server you have root access to. Ubuntu 24.04 is the reference target. Other Debian-based distros work the same; RHEL-family distros need different package names but the same overall sequence.

You'll also need a domain name pointing at the server's public IP (for the SSL step), and SSH access from your laptop.

## Step 1 — install system packages

As root on the server:

```
apt-get update
apt-get install -y python3 python3-venv python3-pip git nginx supervisor
apt-get install -y libnspr4 libnss3 libasound2t64 libpango-1.0-0 libcairo2
```

The second line is for headless Chromium (used by `manage.py snapshot`), only needed if you want UI screenshot support. Skip it if you don't care about that.

## Step 2 — create the project user

By convention, every Velour deploy runs as a dedicated non-root user named after the project. For production Velour the user is `swibliq`; for any other deploy you'd pick a different name.

```
adduser --system --group --home /var/www/webapps/swibliq swibliq
mkdir -p /var/www/webapps/swibliq/{apps,static,media,run,log,backups}
chown -R swibliq:swibliq /var/www/webapps/swibliq
```

The `apps/` subdirectory will hold the Velour project itself plus any app_factory-generated child projects.

## Step 3 — clone Velour

As the project user:

```
sudo -u swibliq -i
cd ~/apps
git clone https://github.com/handyc/velour.git
cd velour
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

If the installation fails on a system library (most likely the psycopg or skyfield wheels), check the error message and `apt-get install` the missing dev package.

## Step 4 — initialize the database

```
venv/bin/python manage.py migrate
venv/bin/python manage.py createsuperuser
venv/bin/python manage.py init_health_token
venv/bin/python manage.py init_mail_relay_token
venv/bin/python manage.py seed_manuals
```

The seed_manuals call populates the three default Codex manuals. Skip it if you'd rather start with an empty Codex.

## Step 5 — generate deploy artifacts

From the velour directory, still as the project user:

```
venv/bin/python manage.py generate_deploy
```

This produces `deploy/gunicorn.conf.py`, `deploy/supervisor.conf`, `deploy/nginx.conf`, and `deploy/setup.sh`. Inspect them — the values come from your Identity model and your project user.

## Step 6 — install the artifacts

As root:

```
cp deploy/supervisor.conf /etc/supervisor/conf.d/swibliq.conf
cp deploy/nginx.conf /etc/nginx/sites-available/swibliq
ln -s /etc/nginx/sites-available/swibliq /etc/nginx/sites-enabled/
supervisorctl reread && supervisorctl update
nginx -t && systemctl reload nginx
```

If nginx complains about the SSL certificate paths, you'll need to run certbot first or comment out the SSL block in the generated nginx.conf.

## Step 7 — verify

Open `https://your-domain/` in a browser. You should see the Velour Chronicle landing page. Click Login and use the superuser credentials from Step 4.

## Common pitfalls

- Static files 404: did you run `collectstatic`? `venv/bin/python manage.py collectstatic --noinput`.
- 502 from nginx: gunicorn isn't running. Check `supervisorctl status` and `tail /var/www/webapps/swibliq/log/gunicorn.err`.
- Permission denied on the socket path: nginx and gunicorn need to share access to `/var/www/webapps/swibliq/run/swibliq.sock`. The supervisor.conf template handles this; if it's wrong, you may have edited the file after generation.""")

    upsert_section(m, 'tut-add-node', 520, 'Tutorial 2 — Adding a node',
        f"{STUB_NOTE}\n\nThis tutorial will walk through adding a new ESP8266 to the lab fleet, from physical hardware setup through firmware flashing to first sensor reading visible in the dashboard.")

    upsert_section(m, 'tut-first-manual', 530, 'Tutorial 3 — Writing your first Codex manual',
        """A gentle tour of the markdown subset, the figure system, and the section ordering — building a small ten-page manual from scratch.

## Goal

We're going to write a manual called *Lab Notebook 2026* with five sections: an opening summary, a methodology section with a definition list, a results section with a table and an inline sparkline, a discussion section with a callout block and a Mermaid diagram, and a conclusion. By the end you'll have used most of Codex's authoring features.

## Step 1 — create the manual

Open `/codex/add/` in your browser. Fill in:

- **Title**: Lab Notebook 2026
- **Subtitle**: Working notes from the spring quarter
- **Format**: Short
- **Author**: your name
- **Version**: 0.1
- **Abstract**: A few sentences describing the scope

Click Save. You're now on the manual detail page with no sections yet.

## Step 2 — add the opening summary

Click "New Section". Title it "Summary" and paste this body:

```
This notebook collects observations from the spring 2026 quarter — temperature stability of the **aquarium** experiment, *soil moisture* drift on the solar monitor, and one anomaly in the mail relay statistics that's still under investigation.

The data was collected automatically via the Velour `nodes` app and is summarized below.
```

Save. You'll be back on the manual detail page with one section listed.

## Step 3 — add the methodology section with a definition list

Click "New Section". Title "Methodology". Body:

```
Three sources contribute data to this notebook.

:::def
Aquarium temperature: ESP32-WROOM (Gary), DS18B20 sensor, sampled every 60 seconds
Soil moisture: ESP8266 (SolarMon), capacitive sensor, sampled every 5 minutes during daylight
Mail relay statistics: scraped from /mailboxes/relay/ logs, daily aggregates
:::

All data passes through the standard Velour `SensorReading` table.
```

The `:::def ... :::` block is the definition-list syntax. Each line becomes a bold-label / plain-value pair in the rendered PDF.

## Step 4 — add the results section

Title "Results". Body:

```
## Aquarium temperature

The aquarium held within ±0.3°C of target throughout the quarter. Inline sparkline shows daily averages: [[spark:24.1,24.2,24.0,24.3,24.1,24.2,24.4,24.1,24.0,24.2,24.1,24.3 | end]].

| Week | Min | Max | Mean |
|---|---|---|---|
| 1 | 23.8 | 24.5 | 24.1 |
| 2 | 23.9 | 24.4 | 24.2 |
| 3 | 24.0 | 24.6 | 24.3 |
| 4 | 24.1 | 24.5 | 24.2 |

## Soil moisture

The soil moisture trended downward over the quarter as expected. [[spark:62,60,58,55,52,49,46,44,42,40 | end min max]] shows the decline with min/max markers.
```

The sparklines render as inline word-sized graphics in the body text. The table renders as Tufte minimal-rule (no vertical lines).

## Step 5 — add the discussion with a callout and a Mermaid figure

Title "Discussion". Before saving the body, scroll down to the Figures section and click "Add Figure". For this figure:

- **Slug**: data-flow
- **Kind**: Mermaid diagram
- **Source**:
  ```
  graph LR
      A[ESP32 Gary] --> B[/api/nodes/gary/report/]
      C[ESP8266 SolarMon] --> B
      B --> D[(Velour DB)]
      D --> E[Codex manual]
  ```
- **Caption**: How the lab nodes feed Codex via the nodes API.

Save the figure. It renders to PNG via Kroki and gets cached on the figure row.

Now back to the section body:

```
The aquarium controller (Gary) is performing as designed. The soil moisture decline is expected behavior for a non-irrigated bed and matches last quarter's pattern.

:::note
The dip in week 3 (24.0 min) coincided with a brief power glitch on March 14th. No equipment was damaged.
:::

The mail relay anomaly is still under investigation. Possible causes include:

- A misconfigured cron job hammering the relay endpoint
- Bot traffic hitting the public-facing form on the landing page
- An upstream change at the SMTP provider

!fig:data-flow
```

The `!fig:data-flow` line on its own embeds the figure inline. The `:::note ... :::` block becomes a callout with a quiet blue bar.

## Step 6 — add the conclusion and render

Title "Conclusion". Short body:

```
The spring quarter went smoothly. Recommend increasing the soil moisture sampling rate to once per minute for the summer quarter when irrigation begins.
```

Save. Back on the manual detail page, click **Render PDF**. A new browser tab opens with your finished 8-page manual.

## What you've used

- Headings (`##`)
- Inline `**bold**` and `*italic*`
- Definition lists (`:::def`)
- Tables (`| col | col |`)
- Inline sparklines (`[[spark:1,2,3 | end]]`)
- Callouts (`:::note`)
- Mermaid figures (uploaded via the figure form, embedded with `!fig:slug`)

You've now used about 70% of Codex's authoring features. The remaining 30% (slope graphs, bordered tables, small multiples grid, code blocks, inline links, figure-caption-below) follow the same pattern — see the "Phase 3 Features" section of the Velour Quickstart for examples of each.""")

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


# --- per-app narrative intros (one page each) ----------------------------

APP_INTROS = {
    'dashboard': """The **dashboard** app is the front door of Velour. After login, every navigational path passes through it: the 4×4 card grid you see at `/dashboard/` is the home screen, and the `templates/base.html` that wraps every other page in the project lives here too.

The grid is a curated set of cards rather than an exhaustive index. Apps that need fast access — Web Terminal, App Factory, System Info, Codex — get a card. Apps that are first-class but used less often (mailroom, hosts, nodes, experiments) live in the navbar above. The card order isn't alphabetical; it groups concerns by purpose. Web Terminal and App Factory sit together because they both create things; Security/Logs/Services/Databases form a single row of operational tools; Identity/Maintenance/Windows handle housekeeping.

The dashboard responds to viewport width with progressive breakpoints (4 columns at ≥1200px, 3 at 900px, 2 at 600px, 1 below) and on phones each card collapses into a compact horizontal strip with the description hidden, so the whole 13-card set fits on one phone screen without scrolling.

Conventions worth knowing: the navbar template (`templates/base.html`) is the only template that lists every app explicitly. Every new app needs a navbar link added by hand. The Chronos topbar clock is mounted above the navbar via a context processor so it floats independently of the dashboard layout.""",

    'terminal': """The **terminal** app is a real interactive shell rendered in the browser. It uses Django Channels and a WebSocket session to spawn a PTY on the server side and stream bytes back and forth. xterm.js handles the rendering on the client.

This is one of the few Velour apps that depends on the asynchronous Channels stack rather than plain WSGI. The ASGI application is `velour.asgi.application` (set in settings.py), and the ASGI routing pulls in `terminal.routing` for the WebSocket consumer. Without ASGI, the terminal won't work — fall-back to plain WSGI is fine for the rest of Velour.

The shell that gets spawned is whatever Velour's user has as their default ($SHELL), so terminal sessions inherit the same environment Velour itself runs in. Useful for poking at db.sqlite3 with `sqlite3`, running ad-hoc Python through `manage.py shell`, or just checking disk usage without leaving the browser.

Security caveat: anyone with login access to Velour gets shell access to the host. Treat it accordingly. The mitigation is that Velour itself is gated behind login_required and runs as a non-root user (typically `swibliq` in production, `handyc` in dev).""",

    'app_factory': """The **app_factory** app is the meta layer of Velour — the part that generates other Django projects. It owns templates for `gunicorn.conf.py`, `supervisor.conf`, `nginx.conf`, `setup.sh`, `adminsetup.sh`, `hotswap.sh`, and a small Django-app skeleton. The `manage.py generate_deploy` management command renders all of those for a target user/host combination, producing a complete deploy bundle ready to scp into place.

The unusual choice that makes this work is that the deploy templates live inside `app_factory/templates/deploy/`, alongside templates for the project's own UI. Django's template engine doesn't care that one set renders HTML for browsers and the other set renders shell scripts for servers — `render_to_string` works the same on both. The naming convention `templates/deploy/*.{conf,sh,py}.tmpl` keeps them obviously separate.

The `GeneratedApp` model tracks projects that app_factory has generated. Each row knows the target directory, the app type, the deploy user, and any in-flight `dev_pid` / `dev_port` so the dashboard can show what's currently running.

Velour itself was originally generated by app_factory and is now its own template seed: changes to the Velour codebase that should propagate to all generated projects get back-ported into `templates/deploy/`. The result is a self-improving meta-app where every new project starts with the latest practices.""",

    'sysinfo': """The **sysinfo** app is Velour's host introspection layer. It reads `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, `df` output, and `ps` output, then renders the results as the System Info page. Nothing here is novel — every monitoring tool ever has done load/memory/disk — but having it built-in means Velour can tell you what's wrong without you needing to ssh into the host.

The more interesting part of sysinfo is the `/sysinfo/health.json` endpoint. It returns a small JSON document describing the host's current state, gated behind a bearer token stored in `BASE_DIR/health_token.txt` (chmod 600, gitignored, generated by `python manage.py init_health_token`). Other Velour instances can be configured to poll this endpoint via the `hosts` app, building a small fleet-monitoring layer where every instance watches every other.

The token-file pattern is part of Velour's secret-file protocol: secrets live as plain text files in BASE_DIR with chmod 600, and `adminsetup.sh` / `hotswap.sh` rsync exclude them so dev secrets never leak to prod and prod secrets never get clobbered.

The `init_health_token` command is idempotent in the safe direction (won't overwrite without `--force`). Use `--show` to print the current token without modifying anything.""",

    'graphs': """The **graphs** app turns the system metrics that sysinfo exposes into Chart.js visualizations. It's the historical view to sysinfo's instantaneous one: where sysinfo says "load is 1.5 right now", graphs says "here is load over the last hour, and here was the spike at 14:32 when the backup ran".

Data sources: load average, memory usage, disk I/O, and entropy pool size, all scraped from /proc periodically. The data is stored in a small SQLite-backed time-series rather than a real time-series database — this is fine for a single host with a few weeks of retention but would not scale to fleet monitoring.

The rendering is Chart.js loaded as a static asset, with data fetched via small JSON endpoints under `/graphs/data/?type=<metric>`. The page polls those endpoints to keep the charts current. There's no WebSocket here — polling at 5-second intervals is good enough for the human eye and avoids complications.

Graphs is the second-most-likely candidate for Codex periodic-report contribution: a weekly Velour status manual would naturally embed sparklines from graphs as inline figures. That work is in the codex periodic-reports backlog.""",

    'services': """The **services** app is a UI for systemd. It lists all services on the host (or just the user-relevant ones), shows their state, and provides start/stop/restart buttons. Behind the scenes it shells out to `systemctl` and parses the output.

This is one of the more dangerous apps in Velour from a permissions perspective. Stopping the wrong service can take the host offline. The mitigation is that systemctl actions require either root or a polkit rule, and Velour runs as a non-root user, so by default the buttons fail with permission denied unless polkit is configured to allow the project user to manage specific services.

In production this is the right default: the operator opts in by writing a tightly-scoped polkit rule for the services Velour should be allowed to touch (e.g., the gunicorn unit, the supervisor unit). Other services stay read-only.

The list view groups services by state (running / failed / inactive) so the eye lands on failures first.""",

    'logs': """The **logs** app is a read-only viewer for system log files. It supports the standard Linux log inventory: syslog, auth.log, nginx access/error, supervisor stderr, dmesg, and `journalctl` output via subprocess.

The interesting design choice here is the *filter chain*. Each log source has its own page, but the filter UI is shared: a search box for substring matching, level filters (info / warning / error / fatal), and a "tail" mode that polls every few seconds for new lines. The filters compose — "all error-level lines from nginx in the last hour matching 'rate-limit'" is one URL.

There's no full-text indexing. The filter runs on every page load by reading the file fresh and applying the filters in Python. This is fine for files up to a few hundred MB; larger logs would benefit from a real indexing layer (the periodic-reports backlog mentions this).

Templates for this app were reconstructed at some point during development after they went missing in a checkout. Worth knowing if a future change to base.html breaks them — the inheritance chain is the standard one but some details may have drifted.""",

    'identity': """The **identity** app is Velour's sense of self. There is exactly one row in the `Identity` table — a singleton — and it carries everything Velour knows about itself: name, tagline, mood, journal, an "about" self-description, hostname, and admin email.

The hostname field is load-bearing in a way that's easy to miss. When `app_factory.generate_deploy` renders the nginx config, it reads `Identity.hostname` to compose the `server_name` directive. If you change the hostname here and re-run `generate_deploy`, the next nginx reload picks up the new hostname automatically. There's no other source of truth for "what is this Velour called on the network".

The `mood` and `journal` fields are softer. They exist because the project's authors think a system that knows who it is communicates better than one that doesn't. The landing page (`landingpage` app) reads from Identity to compose its newspaper-style masthead. Mood data is exposed via `/identity/mood-data/` for downstream visualization.

If you're cloning Velour to a new host, the first `manage.py shell` command you run should probably be `Identity.objects.update_or_create(pk=1, defaults={'name': '...', 'hostname': '...'})`.""",

    'security': """The **security** app runs a battery of read-only checks against the host: SSH config (PermitRootLogin, PasswordAuthentication), firewall (ufw or iptables rules), open ports (`ss` output), user accounts (uid 0 sanity, /etc/passwd anomalies), and pending OS package updates.

Each check has a pass/warn/fail outcome, and the page renders them as a status grid. Click any check to see the underlying command output. The intent is "five-minute security audit" — not a substitute for a real security team, but enough to catch the embarrassing defaults that ship with most Linux installs.

The audit page lives at `/security/audit/` and there's a streaming variant at `/security/audit/stream/` that runs the checks one at a time and live-updates the page so the user sees progress without waiting for everything to finish.

None of the checks attempt to FIX anything. That's deliberate. Auto-fixing security checks would mean Velour needs root, which is a huge expansion of attack surface. The user fixes things themselves via `sudo` after seeing what the audit reports.""",

    'landingpage': """The **landingpage** app renders the public landing page at the project root — the one a logged-out visitor sees. It's styled as a newspaper masthead called *The Velour Chronicle*, complete with serif typography, faux-newsprint background, and dated articles below the masthead.

The design is intentionally not Tufte-influenced. The Chronicle is a marketing surface where personality matters more than information density; the dashboard inside is where Tufte's principles take over.

The articles shown on the landing page are stored as `Article` rows. The masthead pulls from `Identity` (for the name + tagline) and from `ClockPrefs` (for the displayed date). Articles can be marked as draft or published, and the published set is shown in reverse chronological order.

There is no comment system, no analytics, no tracking. The landing page is purely declarative — it tells visitors what Velour is and links them to the login form.""",

    'winctl': """The **winctl** app exists because Velour runs under WSL2 in development and the operator wanted to control the Windows host from inside the Linux VM. It exposes Windows process management, services, firewall rules, and an "execute PowerShell" terminal — all via the `powershell.exe` binary that WSL surfaces from the Windows host.

This is uniquely a development-environment app. In production (where Velour runs on a normal Linux server with no Windows host underneath) winctl is dead code. The dashboard card still shows up but every button returns an error. Removing the app entirely on production is a future cleanup item.

The PowerShell bridge is the most useful piece: typing `Get-Process | Where-Object {$_.CPU -gt 100}` in the winctl terminal hits the actual Windows process table. This is occasionally life-saving when something on the Windows side is misbehaving and Velour is the most convenient thing the operator has open.

Security note: any user who can log into Velour (which is just you, in dev) can issue arbitrary PowerShell commands as the Windows user. The mitigation, again, is that Velour itself is gated behind login_required and the dev environment has only one user.""",

    'maintenance': """The **maintenance** app handles backups and restores. It tarballs `/home` directories (or any directory tree the operator points it at), stores them under `backups/`, and provides a UI for listing and restoring snapshots.

This is the simplest app in Velour. Two views, two models, no surprises. It exists because the operator wanted a "snapshot before doing something risky" button and didn't want to memorize tar flags every time.

The backup format is plain `.tar.gz`. Restore re-extracts into the original location, optionally overwriting. There's no incremental backup, no deduplication, no encryption — those are real-tool concerns and maintenance is explicitly a tool for the small case.

The `backups/` directory is gitignored so the snapshots themselves never end up in the project repo. On a production deployment, `backups/` lives under `/var/www/webapps/<user>/backups/` and is part of the regular host backup rotation.""",

    'hosts': """The **hosts** app is the cross-fleet monitoring layer. It tracks `RemoteHost` rows — other Velour instances running on other machines — and polls each one's `/sysinfo/health.json` endpoint periodically, storing the results so the operator can see "is everything still up" across the fleet at a glance.

Don't confuse `hosts` with `nodes`. `hosts` tracks other Velour instances (other Django projects). `nodes` tracks physical microcontrollers (ESP8266s, ESP32s, Picos). They're different scales of "thing under observation".

Each RemoteHost row carries: nickname, base URL, bearer token (which must match the remote's `health_token.txt`), last poll timestamp, last poll status, last poll latency, last response body. The polling logic uses stdlib `urllib.request` with Bearer token auth — no requests dependency for this small network call.

The list view shows green for healthy, red for unreachable, gray for never-polled. Click into a row for the latest response detail.

For two velour instances to monitor each other, you need to install each one's health token in the other one's RemoteHost record. The token rotation flow (re-running `init_health_token --force`) requires updating the dependent RemoteHost rows by hand.""",

    'mailboxes': """The **mailboxes** app handles outbound email. The central model is `MailAccount`, which stores SMTP server, port, username, password, From address, and an `is_default` flag. The `DynamicMailboxBackend` is set as Django's `EMAIL_BACKEND` in settings.py and reads the default MailAccount at send time, which means Django's built-in password-reset flow uses whichever account is currently marked default — without any settings.py edits.

The other half of mailboxes is the HTTP relay endpoint at `/mailboxes/relay/`. External apps (PHP scripts, shell scripts using curl) can POST a JSON payload with To/Subject/Body and have Velour relay it through the configured fleet, authenticated via a bearer token in `mail_relay_token.txt` (same secret-file pattern as health_token).

There's also `mailboxes.sending.send_mail(..., mailbox='name')` for explicit per-call routing when you want to bypass the default and send through a specific account. Useful for "send this from the lab address" vs "send this from the project address".

The relay endpoint exists because the production host has port 25 blocked by the cloud provider (snel.com), so the only way to send mail from there is to relay through Velour's configured smarthost.""",

    'mailroom': """The **mailroom** app handles inbound email — the counterpart to mailboxes. It polls IMAP accounts, dedupes messages by `(mailbox, uid)`, stores them as `InboundMessage` rows, and renders them in a familiar list/detail UI.

The polling is implemented via stdlib `imaplib.IMAP4_SSL` with `BODY.PEEK` so the polls don't disturb other IMAP clients (the messages stay marked unread). The `manage.py poll_inbox` management command runs one polling pass; cron is the natural way to schedule it.

Dedupe is critical because IMAP polling is naturally re-entrant. The unique constraint on `(mailbox, uid)` makes the dedupe a database concern rather than application logic, which means re-running poll_inbox is always safe.

The UI lives at `/mailroom/` with filters (account, sender, date range, search) and a detail view per message. Attachments are stored under MEDIA_ROOT/mailroom/ and served via the standard Django media serving path.

Mailroom and mailboxes together turn Velour into a small but complete mail terminal. The original use case was managing the lab's various automated email accounts (form notifications, system alerts, project mailing lists) without juggling several separate webmail interfaces.""",

    'experiments': """The **experiments** app is the abstraction layer over the lab's actual research. An `Experiment` row is a long-running thing the operator is doing: "monitor aquarium temperature for six months", "compare two soil moisture sensors", "calibrate a new pH probe". It carries a name, slug, status, and an `is_intermittent` flag for experiments that run on a schedule rather than continuously.

Currently the model is minimal — Phase 1 of experiments is just the metadata layer. Phase 2 will add `SensorChannel`, `ActuatorChannel`, `Decision`, and `TrainedTree` rows that model the data flows in more detail, plus integration with the nodes app so sensor readings can be tagged with which experiment they belong to.

The relationship with `nodes` is the important one. A `Node` (a physical microcontroller) has a foreign key to an `Experiment` so the operator can look at the fleet view and ask "which microcontrollers are part of which experiment". This is also how the codex periodic report would group sensor data by experiment when generating a weekly summary.

For now, experiments is a hand-curated list. There's no auto-discovery, no inference, just rows the operator creates when starting a new line of work.""",

    'nodes': """The **nodes** app is the physical microcontroller fleet — every ESP8266, ESP32, Pico, or other small board the lab owns. Each `Node` row has a nickname (Gary, Solar Monitor, etc.), a slug, an optional MAC address, an optional hostname, an API token, a hardware profile, an experiment reference, and a power mode.

Identity is intentionally layered. The nickname is for humans and isn't unique. The slug is the URL-safe stable identifier and IS unique. The MAC address is unique-when-set but can be blank until the operator reads it off a freshly-flashed chip.

The `HardwareProfile` model is a catalog of board variants — six are seeded by default (Wemos D1 Mini, ESP32-WROOM, ESP32-S3, Pico, etc.). Each Node picks a profile from a dropdown, so adding a new board family means creating a HardwareProfile row once and then every unit of that board reuses it. Queries like "all LoRa-capable nodes" or "every ESP8266 still in service" become trivial joins.

The `power_mode` enum (always_on, solar, battery, on_demand, unknown) lets the fleet UI distinguish between "expected to be offline" (a solar node at night) and "actually broken" (an always-on node that hasn't reported in for hours). Both render as muted; broken nodes get red borders.

`SensorReading` is the per-reading time-series. The schema is intentionally loose: a free-text channel name, a float value, a received_at timestamp, and an optional JSON blob for any extra metadata the node wanted to attach. Phase 2 will tighten this with declared SensorChannel rows.

The machine-facing endpoint at `/api/nodes/<slug>/report/` accepts POSTs from field devices, authenticated via Bearer token (`node.api_token`). The drop-in C++ client lives in `nodes/firmware/` for ESP8266 / ESP32 builds.""",

    'databases': """The **databases** app is a registry of MySQL and PostgreSQL connections. Each `Database` row stores nickname, slug, engine, host, port, username, password, database name, SSL mode, notes, and the result of the last connection test (status, server version, error trace, timestamp).

Phase 1 stores credentials and tests connections. The "Test connection" button on the detail page runs `SELECT VERSION()` (MySQL) or `SELECT version()` (PostgreSQL) via pymysql / psycopg with a 5-second timeout, then writes the result back to the row so the list view can show green/red status dots.

Phase 2 (planned, in the codex periodic-reports backlog) will add table browsing, row viewing/editing, and a raw SQL shell rendered into the detail page. The data model is already designed to support all of that — Phase 2 is purely views + templates + driver helpers.

Drivers are pinned in requirements.txt: `pymysql==1.1.2` (pure Python, no compilation needed) and `psycopg[binary]==3.3.3` (psycopg 3 with binary wheels — newer than psycopg2 and recommended). The lazy `databases/drivers.py` module imports them on demand and reports a clear error if a driver is missing.

Storage caveat: passwords are stored as plain text in the SQLite db. This matches the trust model used by mailboxes for SMTP/IMAP passwords — fine for a single-user lab control panel, not appropriate for a multi-tenant SaaS.""",

    'codex': """The **codex** app is Velour's documentation system. You're reading one of its outputs right now. Sections written in markdown are stored as `Section` rows attached to a parent `Manual` row, and the renderer turns them into Tufte-flavored A4 PDFs via fpdf2 with the ET Book typeface bundled under `static/fonts/et-book/`.

The markdown subset is small but expressive: H1/H2/H3 headings, paragraphs with inline `**bold**` / `*italic*` / `[text](url)` links, bullet lists, blockquotes, code blocks, fenced callouts (`:::note ... :::`), pipe-syntax tables (Tufte minimal-rule by default, `!table:bordered` for spreadsheet-style), definition lists (`:::def ... :::`), inline sparklines (`[[spark:1,2,3,4 | end]]`), inline sidenote anchors (`^[note text]`), figure references (`!fig:slug`), small-multiples grids (`!figs cols=N a b c`), and slope graphs (`!slope:Left,Right` followed by series lines).

The figure system has two kinds: uploaded images (PNG/JPG/SVG) and Mermaid diagrams that are rendered to PNG via the Kroki HTTP API and cached on the figure row. Captions can hang in the right margin (Tufte default) or below the figure (academic style) — controlled by the `caption_position` field on each Figure.

The renderer in `codex/rendering/tufte.py` is ~700 lines and handles the page geometry (A4 with a wide right margin for sidenotes), inline sidenote anchoring with collision avoidance, and table pagination for long auto-generated content. Sparklines are drawn directly with fpdf2 line/rect/ellipse primitives — no images, no extra dependencies.

Phase 2b (the introspection layer) is the reason this Reference manual exists. Re-running `python manage.py seed_manuals` walks the live codebase and re-generates the model/url/command tables in every chapter, so the reference never goes stale.""",
}


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

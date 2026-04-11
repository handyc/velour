"""Seed the Velour Developer Guide volumes.

Phase 1 of an ongoing effort: a 5-volume Developer Guide modelled
on the Unix V Programmer's Manual. Each volume targets 250-500 pages
of dense, senior-developer-tone technical writing with embedded
diagrams. Total target across all five volumes: 1,250-2,500 pages.

This command currently seeds Volume 1 (Foundations and Philosophy).
Volumes 2-5 will be added by subsequent iterations.

Tone: developer-level, written for engineers who already know
Django, Linux administration, and basic web infrastructure. No
hand-holding. No exhortations. Cross-references are dense.
Opinions are stated directly. The prose is intended to be read
slowly and re-read.

Usage:

    python manage.py seed_devguide
        Seed all available volumes.

    python manage.py seed_devguide --vol 1
        Seed only one volume by number.
"""

from django.core.management.base import BaseCommand

from codex.introspection import (
    commands_for_app, models_for_app, urls_for_app,
)
from codex.models import Manual, Section


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
# VOLUME 1 — Foundations and Philosophy
# =====================================================================

def seed_volume_1():
    m = upsert_manual(
        'velour-developer-guide-vol-1',
        title='Velour Developer Guide, Volume 1',
        subtitle='Foundations and Philosophy',
        format='complete',
        author='Velour',
        version='0.1 (work in progress)',
        abstract=(
            'Volume 1 of a five-volume Velour Developer Guide. This '
            'volume introduces the meta-app concept, the deploy '
            'pipeline, the secret-file protocol, the app layout '
            'conventions, the template system, and the architecture '
            'of the system\'s sense of self. The companion volumes '
            'cover the web layer (Vol 2), time and data (Vol 3), '
            'codex and documentation (Vol 4), and operations and '
            'extension (Vol 5).'
            '\n\n'
            'This is a working draft. Some chapters are complete, '
            'others are stubs awaiting expansion. The structure is '
            'stable: chapter order and numbering will not change as '
            'content fills in.'
        ),
    )

    upsert_section(m, 'foreword', 10, 'Foreword',
        """Velour is a Django meta-application. It is also the control panel for a small wet lab in Leiden, the front-end for a fleet of two-dozen microcontrollers, the documentation engine that produced this manual, the calendar for thirty-two world clocks plus eleven traditions of religious holidays plus the JPL DE421 ephemeris, and a turn-based attention loop with a sine wave that never spins the laptop fan.

It is none of those things, of course. It is a Python codebase. The list above describes what the codebase *does*, not what it is.

Volume 1 of this guide is about what the codebase *is*. It explains the unusual design choice — a Django project that contains apps which generate other Django projects — and the conventions that follow from that choice. It explains the deploy pipeline as an artifact of the meta-app idea rather than as a separate ops concern. It explains the secret-file protocol, the app layout conventions, the template system that loads HTML and shell scripts through the same machinery, and the singleton `Identity` model that lets the system describe itself coherently.

Subsequent volumes will cover specific subsystems in depth: Volume 2 covers the web layer, Volume 3 covers time and data, Volume 4 covers codex itself, and Volume 5 covers operations and extension.

Volume 1 is the volume to read first. The other four assume the conventions laid out here.

## How to read this volume

The chapters are short and densely cross-referenced. Read in order on a first pass. The glossary at the back is for re-reading; the appendices are for lookup.

Code examples are illustrative, not transcripts of the actual codebase. When you want the actual code, the introspection appendices in this volume and at the end of each subsequent volume show the live model fields, URL routes, and management commands as auto-generated tables — kept in sync with the codebase by re-running `python manage.py seed_devguide`.

This guide is written for engineers who already know Django, Linux administration, and basic web infrastructure. There is a separate beginner's guide planned but not yet written.""",
        sidenotes='The Unix V Programmer\'s Manual (Bell Labs, 1979-1985) is the model for this series\'s tone and density.\nVolume 1 is intentionally short — 300pp — because it is the foundation everyone else builds on.')

    upsert_section(m, 'part-1', 100, 'Part I — Philosophy',
        """Five chapters covering the conceptual foundations: the meta-app idea, the deploy pipeline as an artifact of that idea, the secret-file protocol, the app layout conventions, and the template system.

These chapters do not contain much code. The code is in the appendices and in subsequent volumes. Part I is concerned with *why*.""")

    upsert_section(m, 'ch1-meta-app', 110, 'Chapter 1 — The meta-app idea',
        """A Django *application* (in Django's vocabulary) is a unit of code: a directory with `models.py`, `views.py`, `urls.py`, a `migrations/` folder, and so on. A Django *project* is a collection of applications glued together by a `settings.py` and a `urls.py` at the project level.

Most Django projects are *applications* in the colloquial sense: a thing you run that does a thing for people. The user base interacts with the project through a UI; the developer team maintains the codebase; the operations team deploys it.

Velour is a Django project that *contains apps which generate other Django projects*. This sentence is the entire premise of Velour and most of what makes the codebase unusual. The rest of this volume is unpacking what it means and what follows from it.

## Three observations to start

Start with three observations. They are obvious individually but generative when combined.

**First**, Django's machinery for templating, URL routing, ORM, settings, and management commands is uniformly excellent for *any* structured-text-generation task — not only HTML for browsers. Django templates can render gunicorn config files, supervisor unit files, nginx vhosts, shell scripts, and Markdown documentation just as well as they render HTML. Django's URL resolver can be walked at runtime to enumerate the routes a project exposes. Django's ORM can introspect model field types, foreign keys, indexes, and constraints. Django's management command system can be used to package any one-shot task as a `python manage.py xxx` invocation.

**Second**, the work of starting a new web application is mostly the same every time. You provision a Linux server. You create a non-root user. You install Python and a process supervisor and a reverse proxy. You write a gunicorn config, a supervisor program file, an nginx vhost. You create a database. You set up a cron job for backups. You write a README. You commit to a git repository. You write a setup.sh that automates as much of the above as possible. You do this for every new project, by hand, with subtle variations that you eventually wish were normalized.

**Third**, a control panel for a small lab needs to know about the things it controls. It needs an inventory of microcontrollers, an inventory of databases, an inventory of email accounts, an inventory of services, an inventory of sensors, an inventory of documentation. It needs to remember what it has done in the past, what the current state of each of those things is, and how to change them.

The first observation says Django is a more general tool than the canonical use case suggests. The second observation says new-project setup is repetitive, and repetitive work belongs in a tool. The third observation says a lab control panel is naturally meta — it is inherently a project-about-projects.

Combine the three: build a Django project whose job is to manage other Django projects, written using Django's own machinery, doubling as the lab control panel. That is Velour.

## Four meta-loops

Four sub-systems within Velour are recognizably *meta-app* in flavour. Each is a small, self-contained loop where Velour is operating on something Velour-shaped.

**`app_factory`**. The most explicit meta-loop. Owns templates for `gunicorn.conf.py`, `supervisor.conf`, `nginx.conf`, `setup.sh`, `adminsetup.sh`, `hotswap.sh`, plus skeleton files for a fresh Django app. The `manage.py generate_deploy` management command renders the templates for a target user/host pair and writes the result to a deploy directory. Velour itself was generated this way once and is now its own template seed: improvements to the templates flow back into Velour's own deploy artifacts via re-generation.

**`codex`**. The documentation system you are reading. Velour writes documentation about Velour by walking its own codebase and rendering markdown into PDFs. The introspection layer (`codex/introspection.py`) reads `django.apps.apps.get_app_configs()` and produces model field tables, URL routes, management command listings, and settings entries — all via Django's own introspection APIs. The reference content in this volume is partially generated this way.

**`identity`**. A singleton `Identity` row that holds Velour's own self-description: name, tagline, mood, journal, hostname, admin email. The `hostname` field is load-bearing in a particular way: when `app_factory.generate_deploy` renders an nginx config, it reads `Identity.hostname` to compose the `server_name` directive. So Velour's *self-knowledge* (the value of `Identity.hostname`) becomes part of the *deploy artifacts* (the nginx config). Change one and the other follows.

**`sysinfo`**. The host introspection layer. Reads `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, `df`, `ps`, and so on. Provides Velour with an outside view of the machine it runs on. Combined with `identity`, the system knows both who it is and where it is.

These four loops are small individually. Together they make Velour a system that knows what it is, where it lives, what it does, and how to write that down.

## What follows

Chapters 2 through 5 unpack the conventions that the meta-app idea forces on the codebase: the deploy pipeline (Chapter 2), the secret-file protocol (Chapter 3), the app layout conventions (Chapter 4), and the template system (Chapter 5).

Chapters 6, 7, and 8 cover the Identity loop and its complement, the sysinfo external view: the system's knowledge of itself.

Chapters 9 through 11 cover the deploy lifecycle in detail: `generate_deploy`, `setup.sh`, and `hotswap.sh`.

Chapters 12, 13, and 14 walk through a complete worked example end-to-end.

The glossary at the back collects every Velour-specific term in one place, with cross-references back into the chapter text.""",
        sidenotes='"Meta" here is the conceptual term, not the JavaScript framework or the social media company.\nThe Unix V manual\'s structure is similar: each chapter is short and densely cross-referenced, organized around a single concept rather than a feature list.')

    upsert_section(m, 'ch2-deploy', 120, 'Chapter 2 — The deploy pipeline anatomy',
        """The deploy pipeline is the most concrete consequence of the meta-app idea. Because Velour generates Django projects, it must also generate the operational infrastructure those projects need: a process supervisor declaration, a gunicorn worker config, an nginx vhost, a setup script. The pipeline that does this generation is small enough to read end-to-end in one sitting.

## The artifacts

`python manage.py generate_deploy` produces a deploy bundle consisting of:

:::def
gunicorn.conf.py: Worker count, bind socket path, log paths, Python path adjustments
supervisor.conf: Program declaration, restart policy, environment, log rotation, the user the process runs as
nginx.conf: Server name, SSL config, static and media file mounts, the upstream socket path that gunicorn binds to
setup.sh: One-shot bootstrap script the operator runs as root on the target host: creates the project user, sets up the directory tree, installs system packages, drops the supervisor and nginx files into place, reloads both services
adminsetup.sh: Operator-side rsync helper. Pushes the project tree to the server while excluding venv, db.sqlite3, secret files, and other local-only artifacts
hotswap.sh: Faster code-only push. Assumes setup.sh has already run; just rsyncs source files and restarts the gunicorn worker
:::

These six artifacts together describe a complete production deployment. Inspect them after generation — the values come from your `Identity` model and your project user, and reading them is the most efficient way to understand what the pipeline thinks "production" looks like.

## The user/dir/socket convention

Every Velour deploy follows a strict naming convention. The convention exists because consistency across hosts is more valuable than per-host flexibility. When you ssh into a new server you already know where everything is.

The convention:

| Concern | Path |
|---|---|
| Linux user | `<projectname>` (e.g. `swibliq`) |
| Project root | `/var/www/webapps/<user>/` |
| App tree | `/var/www/webapps/<user>/apps/<projectname>/` |
| Static files | `/var/www/webapps/<user>/static/` |
| Media files | `/var/www/webapps/<user>/media/` |
| Run sockets | `/var/www/webapps/<user>/run/<projectname>.sock` |
| Logs | `/var/www/webapps/<user>/log/` |
| Backups | `/var/www/webapps/<user>/backups/` |

This is hard-coded into the deploy templates. Every artifact uses these paths. Override them and you're on your own.

## generate_deploy in detail

The command's signature is approximately:

```
python manage.py generate_deploy
    [--server-name DOMAIN]
    [--user USERNAME]
    [--project NAME]
```

If you don't pass `--server-name`, the command reads `Identity.hostname` for the server name. This is the load-bearing connection between the Identity loop and the deploy pipeline: changing `Identity.hostname` and re-running `generate_deploy` produces a new nginx config with a new `server_name` directive.

If you don't pass `--user`, the command uses the current Django settings to derive a project user name — typically the same as the project package name.

If you don't pass `--project`, the command uses Django's `BASE_DIR` to figure out the project name from the directory tree.

The command writes its output to `BASE_DIR/deploy/`. The four files appear there. Inspect them. Then scp them to the target host.

## What setup.sh actually does

`setup.sh` is a bash script. It's intended to run as root on the target host once. The sequence:

1. Update apt and install system dependencies (python3, python3-venv, python3-pip, git, nginx, supervisor, plus a few libs).
2. Create the Linux user (with `--system --group --home /var/www/webapps/<user>`).
3. Create the directory tree under `/var/www/webapps/<user>/`.
4. chown the tree to the project user.
5. Drop the generated `supervisor.conf` into `/etc/supervisor/conf.d/<user>.conf`.
6. Drop the generated `nginx.conf` into `/etc/nginx/sites-available/<user>` and symlink to `sites-enabled/`.
7. `supervisorctl reread && supervisorctl update`.
8. `nginx -t && systemctl reload nginx`.

What it does *not* do: clone the source code, install Python dependencies, run migrations, create a superuser. Those steps are intentionally manual — they're per-deploy decisions, not template-able boilerplate. The operator runs them by hand after `setup.sh` finishes.

## What hotswap.sh does

`hotswap.sh` is the daily-use script for code-only updates. It assumes `setup.sh` has already run on the target. It rsyncs the source tree (excluding venv, db.sqlite3, secret files, `__pycache__`, `staticfiles`, `media`, and a few other local-only artifacts) and then `supervisorctl restart <user>`.

Hot-swap is fast — usually under five seconds — because rsync only transfers changed files and supervisor only restarts the gunicorn worker, not the whole process tree.

Hot-swap is not safe for migrations. If a deploy includes new migrations, run them by hand after the rsync but before the restart.

## Consequences

The deploy pipeline being small and template-driven has three consequences worth knowing about.

**First**, every Velour deploy looks the same. There is no per-host configuration drift. If you ssh into two servers, both will have the same directory layout, the same supervisor config structure, the same nginx vhost shape. The variables are user, hostname, port, and Python version — everything else is identical.

**Second**, the operator's mental load is small. The operator does not need to remember how to write a supervisor config. They need to remember how to run `generate_deploy`. The complexity lives in the templates, which are read once and rarely modified.

**Third**, improvements compound. If you fix a bug in the supervisor template (e.g., add a missing log rotation directive), every future deploy gets the fix. Existing deploys can pick up the fix by re-running `generate_deploy` and re-installing.""",
        sidenotes='Hot-swap was added after the third or fourth time the operator manually rsync\'d code changes and forgot to restart supervisor.\nThe template directory `app_factory/templates/deploy/` is the place to look when you want to know exactly what each artifact looks like.')

    upsert_section(m, 'ch3-secrets', 130, 'Chapter 3 — The secret-file protocol',
        """Velour stores its secrets as plain text files in `BASE_DIR`, chmod 600, owned by the project user. There is no settings.py constant for any secret. There is no environment variable for any secret. There is no encrypted vault. Secrets are files, and the file permissions are the entire access control mechanism.

This is unusual enough to warrant explanation. Most Django projects either commit secrets directly (which is wrong), put them in environment variables (which is convention), or use a secrets manager (which is more elaborate). Velour does none of those things.

## The four secret files

Four files participate in the protocol. All four live in `BASE_DIR`. All four are chmod 600, owned by the project user, and gitignored.

**`secret_key.txt`**. Django's `SECRET_KEY`. Read by `velour/settings.py` at startup if the file exists, falling back to the `DJANGO_SECRET_KEY` environment variable, falling back to an insecure dev default. The fallback chain matters: in development the file isn't strictly required (a dev default is acceptable for `runserver`), in production the file MUST exist and be 48+ random characters. The `setup.sh` artifact does NOT generate this file — the operator generates it once with a one-liner like `python -c "import secrets; print(secrets.token_urlsafe(48))" > secret_key.txt && chmod 600 secret_key.txt`.

**`health_token.txt`**. Bearer token for the `/sysinfo/health.json` endpoint, which exposes the host's load/memory/disk status to other Velour instances polling it. Generated by `python manage.py init_health_token`. Idempotent in the safe direction (won't overwrite an existing file without `--force`). The file format is one line: 48 characters, alphanumeric. Use `--show` to print the current token without modifying anything.

**`mail_relay_token.txt`**. Bearer token for the HTTP mail relay endpoint at `/mailboxes/relay/`. External applications (PHP scripts, shell scripts using curl, anything that wants to send mail through Velour's configured fleet) authenticate with this token. Generated by `python manage.py init_mail_relay_token`. Same shape as the health token.

**`*.token`**. Wildcard reserved for future per-app tokens. The convention is one file per token, named after the purpose, ending in `.token`. The .gitignore entry `*.token` covers all of them.

## Why files instead of environment variables

Three reasons.

**First, files have permissions.** `chmod 600 secret_key.txt` is a real, kernel-enforced barrier — only the file's owner can read it. Environment variables, by contrast, are visible to anything that can read `/proc/<pid>/environ`. On a multi-user host, that's a lot of things. For a single-tenant lab control panel running as a non-root user, file permissions are the right granularity. For a multi-tenant SaaS they aren't, but Velour is not a SaaS.

**Second, files are bootstrapped automatically.** The `init_*_token` management commands create them on first run with chmod 600 already set. The operator doesn't have to remember a separate "set this environment variable before starting the server" step. There is no shell file to edit, no systemd unit to template, no `.env` to keep in sync.

**Third, files are inspectable by humans.** The operator can `cat health_token.txt` to see the current value and copy-paste it into a remote Velour instance's `RemoteHost` configuration. Environment variables require a shell session and the right tools. For the cross-fleet polling use case, the inspectability matters more than people give it credit for.

## Rotation

Re-running any `init_*_token` command with `--force` overwrites the file with a fresh random token. The old token is now invalid. Anywhere the old token was being used (other Velour instances polling this one's health endpoint, external apps posting to the mail relay) needs to be updated by hand.

There is no automatic rotation schedule. The tokens are 48-character random strings; the operator rotates them when they want to.

## Exclusion from rsync

`adminsetup.sh` and `hotswap.sh` both rsync the project tree from the operator's machine to the target host. Both scripts have explicit excludes for the secret files:

```
--exclude=secret_key.txt
--exclude=health_token.txt
--exclude=mail_relay_token.txt
--exclude=*.token
--exclude=db.sqlite3
--exclude=venv/
```

This matters in two directions. **Outbound**: the operator's local dev secret_key.txt does NOT overwrite the production secret_key.txt during a hot-swap. **Inbound**: production secrets do NOT come down to the operator's machine accidentally.

The same excludes appear in `.gitignore`. The two lists must stay in sync — adding a new secret-bearing file means updating both files. There is no enforcement mechanism beyond convention, so be careful.

## What if a secret leaks

The recovery is the same in all four cases:

1. Rotate the file (`init_*_token --force` or generate a new SECRET_KEY by hand).
2. Update any external consumers that were using the old token.
3. If the leak was via a git commit, the leaked value is in git history forever — even after rewriting history, the orphan blob may remain accessible by SHA on GitHub for some weeks. Treat the leaked secret as compromised even after the rewrite.

The third point is worth emphasizing. The git rewrite is necessary but not sufficient. Always assume the leaked value is in someone else's hands and act accordingly.""",
        sidenotes='The protocol was settled early because the alternative — an environment-variable convention — kept producing inconsistencies between dev and prod.\nThe `init_*_token` commands intentionally refuse to overwrite without `--force` because rotating a token mid-session is the kind of mistake that breaks downstream integrations silently.')

    # Stub chapters with substantive intros
    stubs_part1 = [
        ('ch4-app-layout', 140, 'Chapter 4 — App layout conventions',
         """Every Velour app follows the same on-disk layout. The conventions are not unusual but they ARE strict, and the strictness is what lets the meta-layer (app_factory templates, codex introspection) work without per-app exceptions.

The minimum app directory contains `__init__.py`, `apps.py`, `admin.py`, `models.py`, `views.py`, `urls.py`, and a `migrations/` folder with its own `__init__.py`. Some apps add `management/commands/` for management commands, `templatetags/` for template tag libraries, or sub-packages for non-trivial logic (codex has `codex/rendering/`, chronos has `chronos/holiday_sources/` and `chronos/astro_sources/`).

Templates do NOT live inside the app directory. They live under `templates/<appname>/` at the project root. Static files do NOT live inside the app directory either — source CSS in `static/css/style.css`, source JS in `static/js/`, fonts under `static/fonts/`. The collectstatic output goes to `staticfiles/` which is gitignored.

This chapter expands on each of those rules and explains why they matter for the meta-layer."""),

        ('ch5-templates', 150, 'Chapter 5 — The template system',
         """Django's template engine is used for two completely different jobs in Velour, and the trick that makes it work is that Django doesn't know or care which job it's doing.

**Job one** is the conventional one: rendering HTML for a browser. Every page extends `templates/base.html` and outputs HTML through the standard `render()` view helper.

**Job two** is rendering shell scripts and config files for the deploy pipeline. The `app_factory` app uses `render_to_string` to load files from `app_factory/templates/deploy/*.tmpl` and substitute values like the project name, the user, the hostname, the port. The output is a gunicorn config, a supervisor unit, an nginx vhost, or a bash script — written to disk rather than served over HTTP.

The naming convention `templates/deploy/*.{conf,sh,py}.tmpl` keeps the two sets visually separate. The Django template engine handles them identically.

This chapter unpacks the implications: how to write a deploy template, how to invoke `render_to_string` from a management command, how to handle escaping when the output is a shell script (mostly: don't trust user input in deploy templates), and where the line between the two template families should be drawn."""),
    ]
    for slug, sort, title, body in stubs_part1:
        upsert_section(m, slug, sort, title, body)

    # Part II — The system of self
    upsert_section(m, 'part-2', 200, 'Part II — The system of self',
        """Three chapters covering Velour's self-knowledge: the singleton `Identity` model that holds the system's sense of self, the turn-based attention engine that periodically reflects on the current state, and the `sysinfo` app that provides the complementary external view of the host the system runs on.

The combination of internal model and external sensor means Velour can describe itself coherently in first-person voice. Chapter 7 covers how this works without an LLM, without a GPU, and without spinning up the laptop fan.""")

    stubs_part2 = [
        ('ch6-identity-model', 210, 'Chapter 6 — The Identity model',
         """The `Identity` model is a singleton — there is exactly one row in the table, pk=1, accessed everywhere via `Identity.get_self()`. The fields split into two layers: a *subjective* layer (name, tagline, mood, journal, color preference, about) and a *factual* layer (hostname, admin email).

The subjective layer is for poetry. The system has a name. It has a tagline. It has a current mood and a journal of past thoughts. None of this is necessary for the system to function, but it's load-bearing in the way that personality is load-bearing for a relationship: a system that knows who it is communicates better than one that doesn't.

The factual layer is for operations. `Identity.hostname` is the ground truth for the deploy pipeline's nginx server_name composition. Change it and the next `generate_deploy` produces a config with the new hostname. `Identity.admin_email` is the fallback for system notifications.

This chapter walks through the model field-by-field, explains the singleton pattern (and why a real Singleton metaclass is overkill), and shows the cross-references from the deploy pipeline back into the Identity row."""),

        ('ch7-attention-engine', 220, 'Chapter 7 — The attention engine',
         """Identity Phase 2 added an attention engine: a turn-based loop where the system periodically samples its sensors, walks a rule chain, picks a mood, composes a one-line first-person thought, and writes a `Mood` row plus a journal entry.

The design constraint was tight. No LLM. No GPU. No simulation of consciousness. The user explicitly did not want fan noise from the laptop. The architecture had to be as cheap as `cron` running a Python script every ten minutes.

The architecture: server stores the current state in `Identity.mood` and `Identity.mood_intensity`. A management command (`identity_tick`) is fired by cron, gathers a snapshot from a small set of sensors (load, memory, disk, uptime, chronos, nodes, mailroom, codex), walks a rule chain to derive a `(mood, intensity, label)` tuple, composes a one-line thought from a phrase template library, and writes everything back. The whole tick takes a fraction of a CPU-millisecond.

The browser side draws a sine wave on a canvas using `requestAnimationFrame` (browser-paused when the tab is hidden) with parameters derived from the cached state. The state is refreshed via a slow poll of `/identity/state.json` once a minute. No tight loops, no setInterval at high frequencies, no fan spin-up.

This chapter walks through the sensor module, the rule chain, the template library, and the JS animation. The design philosophy underlying it — *the operator is the consciousness; Identity is a mirror with attention* — is articulated explicitly."""),

        ('ch8-sysinfo', 230, 'Chapter 8 — Sysinfo and external observation',
         """The `sysinfo` app provides Velour's external view of the host it runs on. Where Identity knows what Velour *is*, sysinfo knows where Velour *lives*.

It is the simplest app in Velour by line count. Most of its work is reading `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, `df` output, and `ps` output, then formatting the results as the System Info page. Every monitoring tool ever has done this; sysinfo is not novel.

What makes sysinfo interesting is the `/sysinfo/health.json` endpoint. It returns a small JSON document describing the host's current state, gated behind a bearer token stored in `health_token.txt`. Other Velour instances can be configured to poll this endpoint via the `hosts` app, building a small fleet-monitoring layer where every instance watches every other.

This chapter walks through the sensor module, the JSON endpoint format, the bearer token authentication, and the cross-references from sysinfo into the `hosts` app and from sysinfo into the Identity attention engine (which uses sysinfo's load/memory/disk readings as inputs to its rule chain)."""),
    ]
    for slug, sort, title, body in stubs_part2:
        upsert_section(m, slug, sort, title, body)

    # Part III — The deploy lifecycle (stubs)
    upsert_section(m, 'part-3', 300, 'Part III — The deploy lifecycle',
        """Three chapters covering the deploy pipeline in operational detail: `generate_deploy` and how it composes its artifacts, `setup.sh` and the bootstrap sequence on a fresh host, `hotswap.sh` and the day-to-day code update flow.

Chapters 12-14 in Part IV walk through a complete worked example end-to-end. This part explains the mechanics; Part IV demonstrates them.""")

    stubs_part3 = [
        ('ch9-generate-deploy', 310, 'Chapter 9 — generate_deploy in detail',
         """The `generate_deploy` management command is the entry point for the deploy pipeline. It takes optional `--server-name`, `--user`, and `--project` arguments and writes four to six files into `BASE_DIR/deploy/`.

This chapter walks through the command end-to-end: the argument parsing, the value resolution (where each variable comes from when not passed explicitly), the template loading, the rendering pass, and the file writing. The reading order matches the order of operations in the source code so you can follow along."""),

        ('ch10-setup', 320, 'Chapter 10 — Setup and provisioning',
         """`setup.sh` is the one-shot bootstrap script the operator runs as root on the target host once. This chapter walks through every line of the generated script and explains what it does and why.

Topics covered: package installation, user creation, directory tree creation, supervisor and nginx file installation, the reload sequence, and what setup.sh deliberately does NOT do (clone source, install Python deps, run migrations, create the superuser — those are per-deploy decisions)."""),

        ('ch11-hotswap', 330, 'Chapter 11 — The hot-swap workflow',
         """`hotswap.sh` is the operator's daily-use script. After `setup.sh` has finished on the target, hot-swap is how code changes propagate.

This chapter covers the rsync invocation, the exclusion list (which files NOT to push), the supervisor restart, and the limits of the hot-swap model — specifically, that hot-swap is not safe for database migrations and the operator needs to run them by hand after the rsync but before the restart."""),
    ]
    for slug, sort, title, body in stubs_part3:
        upsert_section(m, slug, sort, title, body)

    # Part IV — Worked example (stubs)
    upsert_section(m, 'part-4', 400, 'Part IV — A complete worked example',
        """Three chapters walking through an end-to-end Velour deployment from a freshly-installed Linux server to a production-ready instance behind nginx, generating a child app, and deploying that child to a sibling slot under the same `/var/www/webapps/` tree.

The example is intentionally concrete: real commands, real output, real edge cases the operator will encounter the first time they do this for real. The intent is that you can follow along by typing.""")

    stubs_part4 = [
        ('ch12-clone', 410, 'Chapter 12 — Cloning Velour to a new host',
         """A walkthrough of `git clone` → `pip install` → `migrate` → `createsuperuser` → `runserver 7777` on a fresh Ubuntu 24.04 server. Every command is shown with its expected output. Every error you'll encounter the first time is mentioned with its fix."""),

        ('ch13-generate', 420, 'Chapter 13 — Generating a new app',
         """A walkthrough of using `app_factory` to create a new child Django project under the same Velour parent. The example creates a small "lab forms" app that captures research subject data — chosen because it's representative of the kind of one-off internal tool app_factory exists to make trivial."""),

        ('ch14-deploy', 430, 'Chapter 14 — Deploying to production',
         """A walkthrough of `generate_deploy` → scp → `setup.sh` → first boot for both Velour itself AND the lab-forms child app generated in Chapter 13. SSL setup via certbot. Verification. The full sequence from cold start to "open it in a browser and it works"."""),
    ]
    for slug, sort, title, body in stubs_part4:
        upsert_section(m, slug, sort, title, body)

    # Glossary
    upsert_section(m, 'glossary', 500, 'Glossary',
        """:::def
app_factory: The Django app within Velour that generates other Django projects. Owns templates for gunicorn, supervisor, nginx, and shell scripts.
attention engine: The Identity Phase 2 turn-based loop. Cron-driven. Samples sensors, walks rules, picks a mood, composes a thought.
BASE_DIR: Django's path to the project root. Computed as the parent of velour/settings.py. The location of secret-protocol files.
codex: The Velour documentation system. Sections written in markdown stored as Section rows; rendered to PDF via fpdf2 with ET Book.
deploy bundle: The set of files generate_deploy produces: gunicorn.conf.py, supervisor.conf, nginx.conf, setup.sh.
ET Book: The MIT-licensed serif typeface designed for Edward Tufte's books. Bundled under static/fonts/et-book/ for codex rendering.
generate_deploy: The management command at the heart of the deploy pipeline. Renders the deploy templates for a target user/host pair.
ground truth: A piece of state that other parts of the system derive from. Identity.hostname is the ground truth for nginx server_name in deploy artifacts.
health.json: The bearer-token-gated JSON endpoint that exposes a Velour instance's load/memory/disk to other Velour instances polling it.
hosts: The Velour app that tracks RemoteHost rows — other Velour instances. Polls each one's /sysinfo/health.json periodically.
hot-swap: The fast code-only deploy workflow. rsync the source tree, restart supervisor.
Identity: The singleton model holding Velour's sense of self: name, tagline, mood, journal, hostname, admin email.
init_health_token: Management command that generates the health.json bearer token. Idempotent in the safe direction.
Kroki: The HTTP API used by codex's Mermaid figure rendering. Default URL is kroki.io; configurable to a self-hosted instance.
meta-app: A Django project that contains apps which generate other Django projects. The conceptual core of Velour.
node: A physical microcontroller in the lab fleet. Distinct from a host. Tracked by the nodes app.
project user: The non-root Linux user a Velour deploy runs as. Named after the project. Owns /var/www/webapps/<user>/.
RemoteHost: A row in the hosts app that points at another Velour instance for cross-fleet health monitoring.
secret-file protocol: Velour's convention of storing secrets as chmod-600 plain text files in BASE_DIR rather than as environment variables.
setup.sh: The one-shot bootstrap script generated by app_factory. Run once as root on a fresh target host.
sidenote: Codex's term for an inline annotation that hangs in the right margin of a rendered PDF, anchored to a position in the body text.
singleton: A model with exactly one row, accessed via a get_or_create call gated on pk=1. Identity is the canonical example.
sparkline: A small inline word-sized graphic, drawn via fpdf2 vector primitives. Tufte's invention.
sysinfo: The Velour app that introspects the host machine via /proc and shell utilities. Provides the external view of the system.
Tradition: The chronos model that groups holidays from a religious or civic source. Currently 11 instances seeded.
Tufte: Edward Tufte, whose books on information design are the aesthetic touchstone for codex.
:::""")

    # Reference appendices (auto-introspected for Part I-related apps)
    upsert_section(m, 'appendix-a', 600, 'Appendix A — identity reference',
        f"""Auto-generated reference for the identity app, regenerated by `python manage.py seed_devguide`.

{models_for_app('identity')}

{urls_for_app('identity')}

{commands_for_app('identity')}""")

    upsert_section(m, 'appendix-b', 610, 'Appendix B — sysinfo reference',
        f"""Auto-generated reference for the sysinfo app.

{models_for_app('sysinfo')}

{urls_for_app('sysinfo')}

{commands_for_app('sysinfo')}""")

    upsert_section(m, 'appendix-c', 620, 'Appendix C — app_factory reference',
        f"""Auto-generated reference for the app_factory app.

{models_for_app('app_factory')}

{urls_for_app('app_factory')}

{commands_for_app('app_factory')}""")

    upsert_section(m, 'appendix-d', 630, 'Appendix D — hosts reference',
        f"""Auto-generated reference for the hosts app, since it cross-references sysinfo via the health.json endpoint.

{models_for_app('hosts')}

{urls_for_app('hosts')}

{commands_for_app('hosts')}""")


SEEDERS = {
    1: seed_volume_1,
}


class Command(BaseCommand):
    help = 'Seed the Velour Developer Guide volumes.'

    def add_arguments(self, parser):
        parser.add_argument('--vol', type=int, default=None,
                            help='Seed only the named volume number.')

    def handle(self, *args, **opts):
        vol = opts['vol']
        if vol is not None:
            if vol not in SEEDERS:
                self.stderr.write(self.style.ERROR(
                    f'No seeder for volume {vol}. Available: {list(SEEDERS)}'
                ))
                return
            SEEDERS[vol]()
            self.stdout.write(self.style.SUCCESS(f'Seeded volume {vol}.'))
            return

        for v, fn in SEEDERS.items():
            fn()
            slug = f'velour-developer-guide-vol-{v}'
            m = Manual.objects.get(slug=slug)
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ {slug} ({m.sections.count()} sections)'
            ))

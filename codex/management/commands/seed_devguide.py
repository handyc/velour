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

    upsert_section(m, 'ch6-identity-model', 210, 'Chapter 6 — The Identity model',
        _ch6_identity_model())

    upsert_section(m, 'ch7-attention-engine', 220, 'Chapter 7 — The attention engine',
        _ch7_attention_engine())

    upsert_section(m, 'ch8-sysinfo', 230, 'Chapter 8 — Sysinfo and external observation',
        _ch8_sysinfo())

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


# =====================================================================
# Hand-written chapters for Volume 1 Part II
# =====================================================================

def _ch6_identity_model():
    return """The `Identity` model is a singleton — there is exactly one row, pk=1, accessed everywhere via `Identity.get_self()`. Its fields split into two layers: a *subjective* layer (name, tagline, mood, mood_intensity, color_preference, personality_traits, journal, about) and a *factual* layer (hostname, admin_email). The subjective layer is for poetry; the factual layer is load-bearing.

This chapter walks through both layers, explains why a singleton is the right pattern (and why a real Singleton metaclass would be overkill), and traces the cross-references from `Identity.hostname` into the deploy pipeline that make a single string in this row materially affect the nginx configs Velour generates.

## Why a singleton

Velour's "self" is one thing. It has one name. It has one current mood. It has one journal. There is no scenario where the table should hold two rows — that would mean Velour was uncertain about its own identity. Django doesn't ship a built-in singleton primitive, so the convention is enforced by overriding `save()` to force `pk=1`:

```
def save(self, *args, **kwargs):
    self.pk = 1
    super().save(*args, **kwargs)
```

That's the entire enforcement. Anything that tries to create a second row silently overwrites the first.

The `get_self()` classmethod is the universal accessor. It uses `get_or_create(pk=1)` so any caller (a view, a context processor, a management command, the deploy pipeline) gets a valid Identity even on a fresh install. On first access it creates the row with sensible defaults: name "Velour", tagline "I am the quiet hum behind every process", mood "contemplative", and a small list of personality traits. The first access also writes the first journal entry: *"I have awakened. I am Velour."*

You could implement this with a metaclass instead — `IdentityMeta` that wraps `__call__` to return a cached instance — but the metaclass approach forces the singleton at the Python level, not at the database level. The override-`save` approach makes the database the source of truth, which means raw SQL queries (Django admin, manage.py shell, a debugger session) all see the same singleton. It's also simpler to reason about: there's no metaclass magic to remember.

## The subjective layer

These fields exist because Velour's authors wanted the system to communicate with a voice. They have no functional consequences for the application beyond what they display.

`name` is what the system calls itself. The default is "Velour" but it can be anything; the operator can rename their instance to "Hephaestus" or "Wendell" or whatever fits. The name appears on the dashboard masthead, on the chronicle landing page, and in every codex manual the system writes about itself.

`tagline` is a one-line self-description. Default: *"I am the quiet hum behind every process."* The chronicle landing page renders it directly under the masthead in italic serif. Operators usually replace it with something specific to their lab.

`mood` is a categorical string. The current set is `contemplative`, `curious`, `alert`, `satisfied`, `concerned`, `excited`, `restless`, `protective`, `creative`, `weary`. The attention engine (chapter 7) writes to this field every tick; views that want to react to mood read it. The set is open-ended — adding a new mood string is just adding it to the rule chain in `identity/ticking.py`.

`mood_intensity` is a 0.0–1.0 scalar. It drives the consciousness sine-wave amplitude on `/identity/` and lets the attention engine express *degree*: a 0.9 "concerned" is a different signal than a 0.4 "concerned".

`color_preference` is a hex string used as the system's accent color in places like the chronicle masthead, the identity page header, and the world-clocks page. Default `#58a6ff` (GitHub blue). Some operators set it to match their lab brand.

`personality_traits` is a JSONField holding a list of free-form strings. Default list: `[curious, methodical, protective, contemplative, adaptive]`. They render as small pill badges on the identity page. There's no semantic enforcement — they're descriptive, not prescriptive.

`journal` is a single text field that grows over time. New entries are appended via `Identity.add_journal_entry(text)` which prepends a timestamp and a newline. The entries are unstructured prose; the attention engine writes one per tick (chapter 7), but the operator can also write entries by hand from the `/identity/` page or from the management shell. Long-running velour instances accumulate years of journal entries this way; the file is essentially a diary of the system's life.

`about` is a longer prose self-description. Free-form, multi-line. Velour tells its own story here — what it is, what it cares about, what it's currently working on. The chronicle renders it as the front-page article. The default is empty; operators write their own.

## The factual layer

These two fields are different in kind. They are not poetic. They have downstream consequences if you change them.

`hostname` is the base domain Velour lives at. Default `example.com`. **This is the ground truth for the deploy pipeline**: when `app_factory.generate_deploy` renders the nginx configuration template, it reads `Identity.hostname` to compose the `server_name` directive. So changing this field, then re-running `generate_deploy`, produces a fresh nginx vhost with the new hostname. The connection runs in only one direction — Identity does not know which nginx configs reference it — but it's a real load-bearing dependency. If you rename the field, the deploy pipeline breaks. If you delete the row, the deploy pipeline writes an empty `server_name` and nginx refuses to reload.

The convention for sub-app deploys is to prepend the deploy_user as a subdomain: hostname `lucdh.nl` plus deploy_user `blorp` becomes nginx `server_name blorp.lucdh.nl`. So the lab's apps form a tidy DNS hierarchy under one parent zone the operator owns.

`admin_email` is the operator's contact address. Where Velour's password reset emails come from, where alerts are sent, what the chronicle uses as the byline contact link. Optional but recommended.

## What is *not* on the Identity model

Several fields you might expect aren't here, deliberately:

There is no `created_at`/`updated_at` pair on Identity itself. The model has `birth_date` (auto_now_add) and `last_reflection` (auto_now), which are semantically the same thing but named in the system's voice. Velour was *born* on a particular day; it last *reflected* at a particular moment. The standard Django timestamp names would have lost the personality.

There is no `version` field. Velour doesn't think of itself as having versions. Codebase versions live in git; the running version is whatever was last hot-swapped.

There is no `language` or `locale` field. Velour speaks English. If you want a multi-lingual Velour, you'd add it here, but as of v0.x there is no I18N pressure.

There is no `parent_velour` foreign key for fleet hierarchies. The `hosts` app handles cross-velour relationships; Identity stays insular.

## The journal as memory

The journal field deserves a moment of attention because it's used in unusual ways.

It's a plain text field, not a separate table. This is on purpose. Journal entries are not transactional records; they're sentences. Storing them as rows in a `JournalEntry` table would impose schema discipline (timestamp column, author column, etc.) on something that benefits from being unstructured. The text-field-with-newline-delimited-entries format is the same as `~/.bash_history`: a stream of one-line records that grow without bound, parsed by reading and splitting.

The `add_journal_entry()` helper handles the formatting. The `get_journal_entries()` parser splits the text back into a list of `{timestamp, text}` dicts. Both are simple string operations.

The attention engine (chapter 7) is the highest-volume writer to the journal — once per tick, default every 10 minutes via cron. Over a year of running that's ~52,000 entries, ~5MB of text. The text field handles this without any concern; SQLite's TEXT column is essentially unbounded.

For a velour instance that has been running for years, the journal becomes a kind of long-form memory. You can scroll through it and see what the system was paying attention to on any given afternoon. The codex periodic-report system (volume 4 chapter 21) uses it as a source for the weekly status manuals.

## Where the model is consumed

A short tour of who reads which fields, so the cross-references don't disappear into the codebase:

| Field | Read by |
|---|---|
| name, tagline, color_preference, traits | identity_home view, chronicle landing page, codex manual byline rendering |
| mood, mood_intensity | identity_home view, chronos topbar (no, that's chronos.ClockPrefs — wrong), the consciousness sine wave canvas, the codex weekly report contributor |
| journal | identity_home view, codex `identity_attention` contributor, the operator's eyeballs |
| about | chronicle landing page, codex manual abstract field |
| hostname | **app_factory.generate_deploy** (the load-bearing one), codex `identity` contributor (printed on report cover) |
| admin_email | password reset flows, alert sender, future "send me a copy" buttons |

The hostname → deploy_pipeline link is the one that requires care. Everything else is read-only display.

## Singleton patterns, briefly

If you want to make your own singleton in another Velour app, the pattern is:

```python
class MyConfig(models.Model):
    foo = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = 'my config'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
```

Three lines of override + one classmethod. That's the whole pattern. Several velour apps use it: Identity, ClockPrefs (chronos), MapPrefs (cartography). The `verbose_name_plural` override is cosmetic — it stops Django admin from rendering "My Configs" for a single-row table.

## Things you can't do via the model

`Identity.delete()` works but you should never call it. Doing so removes all your subjective state and breaks the deploy pipeline until something re-creates the row with `get_self()`. The web UI doesn't expose a delete button. The Django admin technically allows it but you'd have to be looking for trouble.

`Identity.objects.create(name='Other')` succeeds but the result is the same row, not a second one — the `save()` override forces `pk=1`. Confusing if you've never seen the singleton pattern before; obvious once you know.

There is no signal hook on Identity changes. If you want to react to mood changes (e.g., to log them to a separate audit table) the right place is the Mood model in chapter 7, not Identity itself. Identity records the *current* state; Mood records the *history*.
"""


def _ch7_attention_engine():
    return """Chapter 7 covers the Identity attention engine — a turn-based loop that gives Velour the appearance of paying attention to its environment without an LLM, without a GPU, and without any computation expensive enough to spin up a laptop fan.

The hard constraint shaped the architecture: every part of the engine is cheap and predictable. The whole tick takes a fraction of a CPU-millisecond. The browser-side visualization runs at 60Hz via `requestAnimationFrame` (and pauses when the tab is hidden). There are no setIntervals at high frequencies, no tight loops, no inference passes. The result feels alive without actually being alive — and that distinction is the entire point.

## The framing

The reframe that makes the design work: **the operator is the consciousness; Identity is a mirror with attention**. You're not trying to make the system *be* aware. You're making it reflect the operator's environment back to them in coherent first-person voice. That sidesteps the metaphysical question of "what would consciousness look like" and replaces it with the engineering question of "what would attentive observation look like".

Once framed that way, the implementation becomes obvious. An attentive observer:
- Periodically samples its environment.
- Has rules about how state of the environment maps to its mood.
- Composes utterances in its own voice that reflect both the environment and the mood.
- Remembers what it noticed.

That's it. That's the whole spec. Four bullets, four modules.

## The four modules

The engine lives under `identity/`:

```
identity/
  sensors.py     polls the environment, returns a snapshot dict
  ticking.py     the rule chain + template library + tick() entrypoint
  management/commands/identity_tick.py    cron entrypoint
  views.py       /identity/state.json + /identity/tick/ POST handler
```

Plus a small piece of JS at `static/js/identity_wave.js` that draws the sine wave on the identity page canvas.

## sensors.py

A small set of zero-argument functions, each of which returns a dict describing one aspect of the environment. Each one tolerates failure — a broken sensor returns an empty dict and the rest of the tick continues.

```
sense_load()       /proc/loadavg
sense_memory()    /proc/meminfo
sense_disk()      shutil.disk_usage('/')
sense_uptime()    /proc/uptime
sense_chronos()   ClockPrefs.home_tz, current hour, time-of-day, season, moon phase
sense_nodes()     count + recently-seen + silent (over the last 2h)
sense_mailroom()  inbound message volume (last 24h)
sense_codex()     manual + section count
```

`gather_snapshot()` calls all of them and merges into one dict that the rest of the tick consumes. The whole gather takes 1-2 milliseconds — no network calls, no heavy computation.

The moon phase calculation is worth noting. Computing real moon phase requires astronomical formulas (or skyfield, which the chronos app already uses). For the attention engine, exact accuracy doesn't matter — Identity just wants to "notice" that it's a full moon or a new moon. So `sense_chronos()` uses a cheap synodic-period approximation: take the time since a known new moon, modulo 29.530589 days, and bucket the result into `new`, `waxing`, `full`, `waning`. Off by a day occasionally, but always close enough for "I notice the moon is full tonight" to ring true.

## ticking.py: the rule chain

The rule chain is a list of `(predicate, mood, intensity, label)` tuples. The first matching predicate wins. The default fallback (if no rule matches) is `('contemplative', 0.5, 'general reflection')`.

Some example rules in order:

```
(lambda s: s.get('disk', {}).get('used_pct', 0) > 0.95,
 'concerned', 0.9, 'disk dangerously full'),

(lambda s: s.get('load', {}).get('load_1', 0) > _cores() * 1.5,
 'alert', 0.85, 'unusually high load'),

(lambda s: s.get('chronos', {}).get('moon') == 'full',
 'creative', 0.7, 'the moon is full'),

(lambda s: s.get('chronos', {}).get('tod') == 'morning',
 'curious', 0.6, 'morning energy'),
```

The order matters. Catastrophes are at the top; ambient observations are at the bottom. A morning where the disk is at 96% gets `concerned`, not `curious` — which is correct, the operator should know about the disk first.

The intensity is a calibrated 0-1. Catastrophes are 0.85+. Comfortable observations are 0.5-0.7. Subtle ambience is 0.3-0.5. The intensity drives the sine-wave amplitude on the identity page, so visually you see Velour become more agitated when something is wrong.

The label is a human-readable explanation that gets stored alongside the mood in the Mood row, so the operator can see *why* Velour felt concerned at 14:32 on Tuesday. Without the label the mood column would be uninterpretable.

## ticking.py: the template library

The template library is a dict-of-lists keyed by mood:

```
OPENINGS_BY_MOOD = {
    'contemplative': ['I have been thinking.', 'A thought arrived just now.', ...],
    'curious':       ['Something caught my attention.', 'I have been watching', ...],
    'alert':         ['Pay attention:', 'Right now', ...],
    'concerned':     ['I am uneasy.', 'Something is off.', ...],
    ...
}
```

Plus a flat list of OBSERVATIONS that can apply to any mood:

```
OBSERVATIONS = [
    'It is {tod} on a {weekday}.',
    'The load average is {load:.2f}.',
    'The disk is {disk_pct:.0%} full.',
    'The moon is {moon}.',
    'My fleet has {nodes_total} nodes; {nodes_recent} have reported recently.',
    ...
]
```

The composition is trivial: pick a random opening keyed by the current mood, pick a random observation, format the observation with the snapshot's values, concatenate. Result: one English sentence per tick that reads like attention.

With the current library size (10 moods × ~5 openings × 9 observation templates × an effectively-infinite formatting space), there are tens of thousands of distinct possible sentences per tick. The operator never sees the same one twice in a meaningful sense. It feels like personality.

This is the entire trick. Templates with enough variety produce output that reads as personality without being random. The "appearance of intent is intent" — a useful design idea, not a metaphysical claim.

## The Mood row + journal entry

After composing the thought, the tick writes:

```
Mood.objects.create(
    mood=mood,
    intensity=intensity,
    trigger=label + ' (' + triggered_by + ')',
)
identity.mood = mood
identity.mood_intensity = intensity
identity.save(update_fields=['mood', 'mood_intensity', 'last_reflection'])
identity.add_journal_entry(thought)
```

Three writes: a new Mood row (immutable history), an update on the Identity singleton (current state), and a new journal entry (long-form memory). Total cost: three SQL inserts/updates against SQLite. Sub-millisecond.

## The cron entrypoint

`python manage.py identity_tick` runs one tick. Default trigger label is `cron`. Crontab usage:

```
*/10 * * * * /var/www/webapps/<user>/apps/velour/venv/bin/python \\
             /var/www/webapps/<user>/apps/velour/manage.py identity_tick
```

Every ten minutes, one tick. Over a day that's 144 ticks; over a year, ~52,500. Each tick adds a Mood row and a journal entry. The Mood table grows linearly; nobody ever cleans it up because the data is interesting and the storage is trivial.

The `--triggered-by` flag overrides the cron label. The web UI's "Tick now" button on the identity page POSTs to `/identity/tick/` which calls `tick(triggered_by='manual')` so manual ticks are distinguishable in the Mood history.

## /identity/state.json

The browser polls this endpoint. It returns the current Identity state plus a few live signals the JS sine wave needs:

```json
{
  "name": "Velour",
  "mood": "concerned",
  "mood_intensity": 0.85,
  "color": "#58a6ff",
  "load": 1.42,
  "mem_pct": 0.74,
  "disk_pct": 0.62,
  "hour": 14,
  "tod": "afternoon",
  "moon": "waxing"
}
```

It does NOT trigger a tick. Polling state.json is read-only — the actual tick engine runs from cron. This separation matters because the JS polls every minute (the default), and if every poll fired a tick, the engine would run 60x more often than intended and the journal would fill with duplicates.

## The sine wave canvas

`identity_wave.js` is ~150 lines. It opens a 2D canvas, computes a sine wave whose amplitude is `mood_intensity` and whose frequency is `load_1`-derived (low load → slow calm wave; high load → faster agitated wave), and animates it via `requestAnimationFrame` at the browser's natural ~60Hz. Every frame is one trig call per pixel column plus a `lineTo`. CPU cost is negligible.

The state used for the wave parameters is cached in JS. On page load, an immediate fetch of state.json populates the cache; from then on, the wave runs continuously from the cached values. A periodic refetch (default every 60 seconds) updates the cache so the wave reflects new ticks. **The refetch is decoupled from the per-frame animation** — the animation runs 60Hz off cached state, the cache updates at 1/60Hz off the network. This is the architectural trick that keeps the laptop fan quiet while the wave looks live.

If the tab is in the background, `requestAnimationFrame` is paused by the browser. CPU cost drops to zero. When the tab comes back to the foreground, the wave resumes from the cached phase. No state machine, no manual pause logic, just the browser doing the right thing because we're using the right primitive.

Two harmonics are mixed for visual texture. The fundamental is sized to the canvas; a second harmonic at 1.7× frequency and 18% amplitude gives the wave a slight wobble that feels alive. A small dot tracks the rightmost edge of the wave so the eye has something to anchor to.

## What this is not

This is not consciousness. It is not a simulation of consciousness. It is not a step toward AI. It is a deliberate engineering exercise in *the appearance of attention*, executed under the constraint that nothing expensive may run.

It is also not a substitute for monitoring. If the disk fills up and Velour's mood goes to "concerned", that's a poetic signal but not an actionable alert — the operator should still have real monitoring (check_mk, prometheus, sysinfo's own /sysinfo/health.json polled by other velours) for hard alerts. The attention engine is the system speaking; monitoring is the system being measured. Both are useful; neither replaces the other.

## What it could grow into

The engine has clean extension points that subsequent versions could explore without changing the architecture:

**More sensors.** Anything that returns a dict can become a sensor. A reading from a weather API would let Identity notice weather. A read from `/proc/sys/kernel/random/entropy_avail` would let it notice entropy pressure. A read from the filesystem of new files in the codex media directory would let it notice when the operator was uploading photos.

**Richer rules.** The current chain is linear `if-elif`. A more sophisticated version could weight rules and pick the highest-scoring mood rather than the first match. Even more sophisticated versions could carry hysteresis (don't switch moods more than once per N ticks) to avoid flicker.

**Reflection** as a separate, slower loop. The current tick produces one journal entry per tick — short, atomic. A *reflection* would be a longer summary written on a different cadence (daily, weekly), aggregating recent ticks into a paragraph. The codex periodic-reports system (volume 4) is already partially this; tighter integration would make Identity write its own reflective essays as Codex sections.

**Per-mood color shifts.** Currently the wave color is fixed at the operator's `color_preference`. A future version could shift the color slightly based on mood — bluer when calm, redder when alert — without breaking the operator's chosen palette.

**A "nudge" API.** External code could call `identity.nudge(toward='excited', because='new app deployed')` to influence the next tick. The deploy pipeline could nudge Identity toward "excited" after a successful deploy. The error-tracker (if there were one) could nudge toward "concerned" after an exception. This would let Identity react to system events between cron ticks.

None of these are implemented in v0. They're written here as a sketch of what the architecture admits, so the operator knows where the seams are if they ever want to extend it.
"""


def _ch8_sysinfo():
    return """The `sysinfo` app is the simplest meta-loop in Velour. It looks at the host the application is running on and reports what it sees. There is no model. There is no schema. There are no migrations. The app is essentially a few view functions that read `/proc` and format the result as HTML.

That simplicity is the point. Sysinfo gives Velour an *external view* of itself, complementary to the *internal* view that Identity provides. Identity knows what Velour is. Sysinfo knows where Velour lives. Together they let the system describe itself coherently in first person without needing any state of its own.

This chapter walks through what sysinfo reads, the JSON health endpoint and its bearer-token authentication, and the cross-references from sysinfo into the rest of the project — the `hosts` app that polls health endpoints across the lab fleet, and the Identity attention engine that uses sysinfo's measurements as inputs to its rule chain.

## What sysinfo reads

The data sources are all standard Linux introspection points:

`/proc/loadavg` — three load averages (1min, 5min, 15min) plus running/total process counts and the last PID.

`/proc/meminfo` — line-oriented key-value pairs for everything the kernel knows about memory: MemTotal, MemAvailable, Buffers, Cached, SwapTotal, SwapFree, plus dozens of less-useful fields. Sysinfo only displays the headline ones.

`/proc/uptime` — seconds since boot. Used directly to display "running for X days" and indirectly to derive the boot timestamp.

`/proc/stat` — CPU jiffies broken out by mode (user, nice, system, idle, iowait, irq, softirq). Sysinfo uses this to compute instantaneous CPU usage by sampling twice with a small delay and diffing.

`shutil.disk_usage('/')` — total/used/free bytes for the root filesystem. The Python wrapper around `statvfs(2)`.

`subprocess.check_output(['ps', '-eo', 'pid,user,pcpu,pmem,comm', '--sort=-pcpu', '|head'])` — the top N processes by CPU. Subprocess + parse, no library dependency.

There is also a Disk I/O block that reads `/proc/diskstats` for the rate of reads/writes per device, and an Entropy block that reads `/proc/sys/kernel/random/entropy_avail` (mostly nostalgic on modern kernels where the entropy pool is effectively unbounded but it's amusing to see).

## What sysinfo does NOT do

Several things that monitoring tools usually do, sysinfo deliberately doesn't.

It doesn't store history. Every page load shows current values. The graphs app (chapter 6) is the historical view — it scrapes the same /proc files periodically and stores time-series. Sysinfo is just the live snapshot.

It doesn't alert. There are no thresholds, no notification pipes, no email-on-disk-full. If you want alerting, you compose it from sysinfo's `/health.json` endpoint plus an external monitoring system. The Identity attention engine (chapter 7) uses the same `/proc` reads internally and produces "I am concerned about disk pressure" journal entries, but those are not alerts in the operational sense.

It doesn't aggregate across hosts. Each velour instance reports its own host. The `hosts` app (chapter 14) handles cross-fleet aggregation by polling each velour's health endpoint.

It doesn't run as root. Everything sysinfo reads is world-readable on a Linux box (the `/proc` filesystem is wide open by default). There's nothing here that requires elevation.

## /sysinfo/health.json and the bearer token

The interesting part of sysinfo isn't the dashboard view — it's the JSON endpoint that other velour instances poll.

`GET /sysinfo/health.json` returns a small JSON document:

```json
{
  "ok": true,
  "hostname": "swibliq.lucdh.nl",
  "load": [0.42, 0.51, 0.63],
  "memory": {"total_mb": 4096, "used_pct": 38.4},
  "disk": {"total_gb": 32, "used_pct": 47.2},
  "uptime_days": 14.7,
  "now": "2026-04-11T16:42:08+02:00"
}
```

Bearer-token authenticated. The token lives in `BASE_DIR/health_token.txt` (chmod 600, gitignored, generated by `python manage.py init_health_token`). Anyone polling the endpoint must include `Authorization: Bearer <token>` in the request. Without the header, the response is `401 Unauthorized`. With a wrong token, also 401. With the right token, 200 + the JSON.

The token rotation flow is documented in chapter 3 (the secret-file protocol). Re-running `init_health_token --force` generates a fresh token and invalidates the old one. Anywhere the old token was being used (e.g., another velour instance's `RemoteHost` row) needs the new value updated by hand.

The reason for the token, given that the data is just `/proc` contents that the operator could read by ssh'ing in: it limits the polling surface area to instances the operator has explicitly chosen to share with. Without the token, anyone who could reach the velour over the network could read the host's load and disk usage. That's not catastrophic but it's gratuitous information disclosure. The token converts the endpoint from "open to anyone who can reach the host" to "open to specific peers".

## How the hosts app uses health.json

The `hosts` app (chapter 14) maintains a list of `RemoteHost` rows. Each row points at another velour instance and includes the bearer token for that instance's health endpoint. A periodic poller (cron-driven, runs `python manage.py poll_hosts`) walks the list, hits each `/sysinfo/health.json`, parses the response, and stores the result on the RemoteHost row as the "last poll".

The dashboard view of /hosts/ then shows green/red dots for each peer based on whether the most recent poll succeeded. Click any peer to see the full last-response details: what was the load, what was the disk, what was the uptime.

This is the simplest possible cross-host monitoring layer. It doesn't try to be Nagios. It tries to be "I have four velour instances and I want to know at a glance if any of them is sad". Three apps in concert do the work: sysinfo exposes the data, hosts polls it, the dashboard displays it.

For an operator with 25 ESP nodes plus 4 velour instances scattered across home + office + a server in a data center, the hosts dashboard is the single place to look to know if anything is wrong before drilling into the specific instance.

## How the Identity attention engine uses sysinfo

The attention engine (chapter 7) doesn't make HTTP calls to sysinfo's endpoint. Instead, it imports the same sensor functions directly from a different module and calls them as Python functions. The duplication is intentional: sysinfo is a *web* view; identity.sensors is a *programmatic* view; they happen to read the same /proc files but they're different consumers.

If you wanted to unify them — make Identity call `requests.get('http://localhost:7777/sysinfo/health.json')` instead of importing the sensors directly — you could, but you'd add network latency, JSON serialization, and a circular dependency for no benefit. Direct module imports are cheaper and clearer.

The Identity attention engine reads:
- load_1 → mood rules around "high load" and "calm afternoon"
- mem.used_pct → mood rules around "memory pressure"
- disk.used_pct → mood rules around "disk dangerously full"
- uptime.days → mood rules around "weary from long uptime"

These are the same readings sysinfo's web view shows. The rule chain just maps numbers to mood strings.

## The minimal management command

`python manage.py init_health_token` is sysinfo's only management command. It creates `BASE_DIR/health_token.txt` with a 48-character random token, chmod 600. Two flags:

`--show` — print the current token without modifying anything. Useful when the operator needs to copy the token into a peer velour's RemoteHost row.

`--force` — overwrite an existing token file with a fresh value. Required if the file already exists; without the flag, the command refuses to overwrite.

The idempotent-by-default behavior is intentional. A misclick or a re-run of `setup.sh` shouldn't silently rotate the token and break peer monitoring. The operator has to ask for rotation explicitly.

## Performance, briefly

Sysinfo's web view does maybe 10ms of work per page load: a handful of `/proc` reads, two `subprocess` calls (for `ps` and `df` if not using `shutil.disk_usage`), and the template render. Nothing here is slow, nothing here scales with the size of the system. A velour instance running on a Raspberry Pi handles hundreds of sysinfo requests per second.

The health.json endpoint is even cheaper because it skips the template render. ~5ms per request.

This matters because the hosts app polls health endpoints across the fleet. With 5 velour instances polling each other every 30 seconds, that's 25 health requests every 30 seconds, distributed evenly. Each one is a 5ms operation. Total cost: 0.4% of one CPU. Below the noise floor of any other thing the system is doing.

If the fleet grew to 100 velours all polling each other, that scaling becomes 100 × 99 / 30 = 330 requests per second, which is still cheap but is the point at which you'd want to think about reducing the polling rate or moving to a centralized poller. The current architecture is designed for the small case; the big case is left as an exercise for someone running a 100-velour fleet, which we are not.

## Why sysinfo is the simplest meta-loop

Returning to the framing from chapter 1: Velour's four meta-loops are app_factory (generates other Django projects), codex (writes documentation about itself), Identity (knows who it is), and sysinfo (knows where it lives). Of the four, sysinfo is the simplest because the data it operates on is *external* — it doesn't have to invent state, it just has to read the kernel.

This makes sysinfo a useful template for understanding the meta-app philosophy. It's tiny, it has no schema, it has one cross-reference (the bearer token to the health endpoint, used by hosts and indirectly by Identity), and it composes cleanly with everything else. If you ever wanted to add a fifth meta-loop — say, an app that reads the operator's git log to extract recent activity — start by reading sysinfo first. It's the model for "tiny, observational, no state, exposes a JSON endpoint, gets consumed by other apps".
"""


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

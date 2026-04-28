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

    upsert_section(m, 'ch4-app-layout', 140, 'Chapter 4 — App layout conventions',
        _ch4_app_layout())

    upsert_section(m, 'ch5-templates', 150, 'Chapter 5 — The template system',
        _ch5_template_system())

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

    upsert_section(m, 'ch9-generate-deploy', 310, 'Chapter 9 — generate_deploy in detail',
        _ch9_generate_deploy())

    upsert_section(m, 'ch10-setup', 320, 'Chapter 10 — Setup and provisioning',
        """`setup.sh` is the one-shot bootstrap script the operator runs as root on the target host once. This chapter walks through every line of the generated script and explains what it does and why.

Topics covered: package installation, user creation, directory tree creation, supervisor and nginx file installation, the reload sequence, and what setup.sh deliberately does NOT do (clone source, install Python deps, run migrations, create the superuser — those are per-deploy decisions).""")

    upsert_section(m, 'ch11-hotswap', 330, 'Chapter 11 — The hot-swap workflow',
        """`hotswap.sh` is the operator's daily-use script. After `setup.sh` has finished on the target, hot-swap is how code changes propagate.

This chapter covers the rsync invocation, the exclusion list (which files NOT to push), the supervisor restart, and the limits of the hot-swap model — specifically, that hot-swap is not safe for database migrations and the operator needs to run them by hand after the rsync but before the restart.""")

    # Part IV — Worked example (stubs)
    upsert_section(m, 'part-4', 400, 'Part IV — A complete worked example',
        """Three chapters walking through an end-to-end Velour deployment from a freshly-installed Linux server to a production-ready instance behind nginx, generating a child app, and deploying that child to a sibling slot under the same `/var/www/webapps/` tree.

The example is intentionally concrete: real commands, real output, real edge cases the operator will encounter the first time they do this for real. The intent is that you can follow along by typing.""")

    stubs_part4 = [
        ('ch12-clone', 410, 'Chapter 12 — Cloning Velour to a new host',
         _ch12_clone()),

        ('ch13-generate', 420, 'Chapter 13 — Generating a new app',
         _ch13_generate()),

        ('ch14-deploy', 430, 'Chapter 14 — Deploying to production',
         _ch14_deploy()),
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
# Hand-written chapters for Volume 1 Part I (continued: Chapters 4-5)
# =====================================================================

def _ch4_app_layout():
    return """Every Velour app follows the same on-disk layout. The conventions are not unusual but they are *strict*, and the strictness is exactly what lets the meta-layer — `app_factory`'s deploy templates, `codex`'s introspection, the `oracle` app's auto-discovery (when it lands) — work without per-app exceptions. This chapter is the canonical reference for the conventions, and the rationale for why each one is the way it is.

## The minimum app

A new Velour app is a directory at the project root containing seven files:

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

That's the floor. Several apps have nothing more than this. The `agricola` app (the board game, unrelated to the lab) is essentially this shape. So is `landingpage`, the chronicle masthead.

Optional sub-directories appear in apps that need them:

- `management/commands/` for `python manage.py <command>` entry points. Most apps that maintain state externally (like `chronos` for holidays, `codex` for manuals, `identity` for the attention tick) ship one or more management commands.
- `templatetags/` for custom template tags. Only `dashboard` uses this so far, for the `static_v` cache-busting tag.
- Sub-packages for non-trivial logic. `codex` has `codex/rendering/` (the PDF renderer broken into `tufte.py`, `markdown.py`, `sparklines.py`, `diagrams.py`). `chronos` has `chronos/holiday_sources/` (eleven traditions, one module each) and `chronos/astro_sources/` (equinoxes, eclipses, moon phases, meteors, plus a lazy ephemeris loader). The pattern is: if the logic is more than one file's worth, give it a sub-package with its own `__init__.py`.

## What does NOT live in the app directory

This is the part that surprises Django developers coming from other projects. Velour deviates from Django's defaults in two specific places.

**Templates do not live inside the app directory.** They live under `templates/<appname>/` at the project root. Django's default template loading would look in `appname/templates/appname/` first; Velour overrides `TEMPLATES['DIRS']` in `settings.py` to include the project-level `templates/` directory, and individual apps' template directories are not on the template search path. The result: when you read `views.py` and see `render(request, 'chronos/calendar_month.html', ...)`, the template is at `templates/chronos/calendar_month.html`, not `chronos/templates/chronos/calendar_month.html`.

Why? Two reasons. First, having one top-level templates directory makes the `base.html` inheritance chain visually obvious — every page extends one file, and that file is in one place. Second, it makes template inheritance across apps trivial: a `chronos` template can extend `cartography/_base.html` without any special path configuration. The inter-app coupling is minimal but it exists, and one templates root makes it explicit.

The cost of this convention is that you can't drop an app into Velour from outside (like a third-party Django app) without restructuring its templates. Velour is an application, not a framework that hosts arbitrary apps — the convention is a feature, not a bug.

**Static files do not live inside the app directory either.** Source CSS lives in `static/css/style.css` (one file for the whole project — Velour does not use per-app CSS). Source JS lives in `static/js/`, with one file per identifiable concern (`chronos.js`, `identity_wave.js`, etc.). Bundled fonts live under `static/fonts/`, currently just `et-book/` for the Codex PDF renderer. Images for the README and other docs live under `docs/screenshots/` — separate from `static/` because they're documentation assets, not assets the app serves over HTTP.

The collectstatic output (`STATIC_ROOT`) is `staticfiles/` in dev (gitignored) or `/var/www/webapps/<user>/static/` in production.

The `static/css/style.css` "one file for the whole project" rule is the same kind of decision as templates-at-the-root: it pushes against modularity in favour of a single source of truth that's easy to grep and easy to keep visually consistent. If a future iteration introduces hundreds of pages of styling, it might split into per-app CSS files; right now it's small enough that one file is the right shape.

## Naming and the app_label

A Django *app label* is the short identifier used for migrations, foreign keys, and admin URLs. By convention it's the directory name. Velour follows this strictly: every app's directory name is its app label, and there are no `label = ...` overrides in any of the `apps.py` files.

The implication: don't use hyphens or capital letters in app directory names. Use snake_case exclusively. Most Velour apps are one word (`chronos`, `codex`, `attic`, `cartography`, `nodes`); the multi-word ones use snake_case (`app_factory`, `landingpage` happens to be one word, `mailroom` is one word). When the meta-layer reads `apps.get_app_configs()` and iterates the result, the directory name is the value it gets, and it gets used unmodified in URL paths, template paths, and codex chapter slugs. Consistency here saves a lot of edge-case handling downstream.

## Migrations

Each app has its own `migrations/` directory. Velour does not use a centralized migrations location. Each migration file is committed to git with the schema change it represents — including the seeded data migrations for things like the chronos holiday traditions.

The `BigAutoField` is the default primary key everywhere. This is set in each app's `apps.py`:

```python
class CodexConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'codex'
```

Velour was started after Django moved to BigAutoField as the default, and there's no reason to use the older AutoField. Mixing the two within a project is also possible but creates pointless cognitive load.

Migrations are created by `python manage.py makemigrations <appname>` (almost always with the explicit app name, to avoid running it on every app). They're committed to git immediately after generation. They should not be edited by hand after creation; if a migration is wrong, the right move is `python manage.py migrate <appname> <previous_migration_name>`, delete the bad migration, and re-create.

Data migrations (the kind that populate seed data, like the chronos `Tradition` rows or the `nodes.HardwareProfile` catalog) live in the same `migrations/` directory as schema migrations, with the standard Django `RunPython` helper. Reading the migration directory of each app gives you a complete history of how the schema and seed data evolved.

## URL configuration

Each app has a `urls.py` that defines an `app_name` namespace and a list of `urlpatterns`. The project-level `velour/urls.py` includes each app under a single URL prefix:

```python
path('chronos/', include('chronos.urls')),
path('codex/',   include('codex.urls')),
path('attic/',   include('attic.urls')),
```

Cross-app URL references use the namespace, like `{% url 'chronos:home' %}` or `reverse('codex:manual_detail', args=[slug])`. Hard-coded URL strings should not appear anywhere; if you find one, either replace it with a `reverse()` call or document why the hard-code is unavoidable (e.g., HTTP redirects from external services where the URL is contractually fixed).

The `nodes` app is a slight exception: it has both `nodes/urls.py` (for the human-facing /nodes/ pages) AND `nodes/api_urls.py` (for the /api/nodes/ machine-facing endpoint that ESP devices POST to). This is a deliberate split because the two URL families have different authentication requirements (login_required vs Bearer token) and different design goals (HTML vs JSON). When an app has both human and machine surfaces, splitting `urls.py` into two files is the right move.

## Models

Models are CamelCase singular. `MediaItem`, not `MediaItems` or `media_item`. Foreign keys use string references to avoid circular imports:

```python
experiment = models.ForeignKey(
    'experiments.Experiment',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='nodes',
)
```

`related_name` is set explicitly on every foreign key. The default Django reverse-accessor name (`<lowercase model>_set`) is fine but ugly; spelling out the related_name once at the field definition makes the code that uses it readable. So `experiment.nodes.all()` instead of `experiment.node_set.all()`.

`on_delete` is always specified (Django requires it now, but Velour was strict about it from the start). The choices in actual use:

- `CASCADE` for child rows that should die with their parent (a `Section` dies with its `Manual`).
- `SET_NULL` for soft references that should survive even if the parent goes away (a `Node` keeps existing even if its `Experiment` is deleted; the FK just becomes null).
- `PROTECT` for FKs where the parent should not be deletable while children exist (rare, used for the `HardwareProfile` foreign key on `Node` — if you try to delete a hardware profile that has nodes pointing at it, Velour refuses).

## Why the conventions are strict

The conventions look opinionated to a Django newcomer. They are. The reason is the meta-layer.

`codex.introspection` walks every app via `apps.get_app_configs()` and produces reference tables for every model, every URL pattern, every management command. If the conventions were soft, the introspection would have to handle edge cases. Instead, the introspection is a 250-line module that assumes every app follows the rules — and produces accurate reference content because every app actually does.

`app_factory.generate_deploy` reads the project name and computes file paths like `/var/www/webapps/<user>/apps/<projectname>/`. Strict conventions mean this path is computable; loose conventions would mean the operator has to specify it per-deploy.

The `oracle` app (in the planning sketch) will auto-discover lobes by reading every app's `lobes.py` if it exists. Strict naming means this auto-discovery is one line of glob; loose naming would require a registry.

In short: every convention in this chapter exists to make the meta-layer trivially small. If you ever find yourself wanting to break a convention, the right question to ask is "what meta-layer code does this change make harder to write?" — and only break the convention if the answer is "none".
"""


def _ch5_template_system():
    return """Django's template engine is used in Velour for two completely different jobs, and the trick that makes the dual use work is that Django doesn't know or care which job it's doing. The same `render_to_string()` function call that produces an HTML page for a browser also produces a gunicorn config for a production server. The template files for the two jobs live side by side in the same directory tree. The variable substitution rules are identical. The escaping behaviour is identical (with one important footnote we'll get to). Django's template engine is, at heart, just a parameterized text producer, and Velour leans into that fact.

This chapter walks through the architecture: which templates produce HTML, which produce shell scripts and config files, how the two are kept distinguishable, what conventions exist for safety, and where the line between them should sit when you add new templates.

## The two template families

**Family one: HTML for browsers.** These are the conventional Django templates. They live under `templates/<appname>/` at the project root. They extend `templates/base.html`, which is the project-wide HTML chassis containing the navbar, the chronos topbar, the messages strip, and the body block. They're rendered by view functions that return `HttpResponse` objects via the `render()` shortcut. They reference static files via the `{% static %}` and `{% static_v %}` template tags. Output goes to a browser via HTTP.

This is exactly the way Django was designed to be used. Nothing unusual about it. Velour has hundreds of these templates across all the apps.

**Family two: deploy artifacts.** These templates live exclusively under `app_factory/templates/deploy/`. Their filenames have unusual extensions: `gunicorn.conf.py.tmpl`, `supervisor.conf.tmpl`, `nginx.conf.tmpl`, `setup.sh.tmpl`, `adminsetup.sh.tmpl`, `hotswap.sh.tmpl`. They're loaded via `render_to_string('deploy/gunicorn.conf.py.tmpl', context)` from inside the `generate_deploy` management command. The output is a string of bash, Python, or nginx configuration syntax. That string is written to disk in the project's `deploy/` directory. From there, the operator scp's the files to a target host and runs `setup.sh` once.

Django's template engine renders both families with the same code path. It doesn't know that one is HTML and the other is shell. It just substitutes variables.

## Why this works at all

The reason this dual use is even possible is that Django's template syntax (`{{ var }}`, `{% tag %}`, `{# comment #}`) is sparse. The four characters `{`, `}`, `%`, `#` are the only ones with special meaning, and even those only when paired in specific orders. A bash script can mention `{` and `}` freely without colliding with template syntax (the only collision would be a literal `{{` or `{%`, which is genuinely rare in shell scripts). A Python file can mention dictionaries without escape problems because dict literals use `{key:value}`, not `{{key}}`. An nginx config uses `;` and `{ }` for blocks but never `{{` or `{%`.

In the rare case where a literal `{{` would appear in a deploy template (e.g., a Python f-string template line that uses `{{` to mean a literal `{`), Django's `{% verbatim %}` tag escapes a region from template processing.

## The two render entry points

For HTML templates, the conventional Django pattern:

```python
def my_view(request):
    return render(request, 'myapp/page.html', {'foo': bar})
```

For deploy templates, the same primitive but invoked manually:

```python
from django.template.loader import render_to_string

def generate_one_artifact(template_name, context, out_path):
    text = render_to_string(template_name, context)
    out_path.write_text(text)
```

Note the difference: `render()` returns an `HttpResponse` (with content-type, status code, etc.); `render_to_string()` returns just the string. The deploy pipeline uses `render_to_string()` because it doesn't need the HTTP wrapping.

The `generate_deploy` management command (covered in detail in chapter 9) calls `render_to_string()` six times — once per artifact in the bundle. Each call gets a context dict with the same handful of values: `project_name`, `user`, `hostname`, `socket_path`, `python_version`, etc. The templates substitute these values and produce the final config files.

## The naming convention

Deploy templates live under `app_factory/templates/deploy/`. Their filenames carry the *target* file extension before `.tmpl`:

- `gunicorn.conf.py.tmpl` → renders to `gunicorn.conf.py`
- `supervisor.conf.tmpl` → renders to `supervisor.conf`
- `nginx.conf.tmpl` → renders to `nginx.conf`
- `setup.sh.tmpl` → renders to `setup.sh`
- `adminsetup.sh.tmpl` → renders to `adminsetup.sh`
- `hotswap.sh.tmpl` → renders to `hotswap.sh`

The `.tmpl` suffix is a flag, not a Django requirement. Django doesn't care about file extensions; the suffix is purely for the human reading the directory. Without it, an editor might syntax-highlight the file as bash and complain about the `{% if %}` markers; with it, editors recognize the file as a template and either highlight nothing or highlight the template syntax separately.

The `templates/deploy/` subdirectory is also not load-bearing — Django would find the templates anywhere under `app_factory/templates/`. The subdirectory is a human convention to separate "templates that produce HTML for users" from "templates that produce configs for servers". As of this writing `app_factory` only has `templates/deploy/`, no other template subdirectories, but the convention is established for future growth.

## Variables and context

Both template families use the same `{{ var }}` and `{% if %}` and `{% for %}` syntax. The HTML templates also use `{% load %}` to pull in tag libraries (`{% load static %}`, `{% load assets %}`, `{% load humanize %}`) and `{% url 'name' arg %}` to generate URL paths. The deploy templates rarely need either of those — they're stamping out config files, not generating links — but the syntax is available if needed.

A typical deploy template body looks like:

```
[program:{{ user }}]
command={{ venv_path }}/bin/gunicorn -c gunicorn.conf.py {{ project }}.wsgi
directory={{ apps_dir }}/{{ project }}
user={{ user }}
group={{ user }}
autostart=true
autorestart=true
stopwaitsecs=10
redirect_stderr=true
stdout_logfile={{ log_dir }}/{{ project }}.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
```

Pure key-value substitution. No control flow, no loops. The deploy templates rarely need anything more sophisticated because the structure of the output files is always the same — only the values change.

## Escaping and safety

Here's where the dual use needs care.

Django's HTML template engine *automatically escapes* string variables when rendering. If `name = "<script>alert(1)</script>"` and the template says `{{ name }}`, the output is `&lt;script&gt;alert(1)&lt;/script&gt;`. This is the correct behaviour for HTML to prevent XSS. It's also the wrong behaviour for shell scripts, where `&lt;` is a literal four-character sequence and not what bash expects.

The fix is to mark deploy templates as autoescape-disabled, either with `{% autoescape off %}...{% endautoescape %}` blocks or by wrapping each variable in `{{ name|safe }}`. The current convention in Velour is to use the block form at the top of every deploy template:

```
{% autoescape off %}
[program:{{ user }}]
...
{% endautoescape %}
```

The `{% autoescape off %}` opens at the top of the file and never closes — Django handles the implicit close at end-of-file. This puts the entire file in autoescape-off mode without per-variable annotation.

**Now the safety footnote.** With autoescape off, any user input that flows into a deploy template can do command injection. If `user = "; rm -rf /"` and the template renders to a bash script that says `chown -R {{ user }}:{{ user }} /var/www/`, you've created a shell injection in your own deploy script. The defense is layered:

1. **Don't accept user input into deploy template variables.** `generate_deploy` takes its values from `Identity.hostname`, the project's `BASE_DIR`, and a few command-line arguments. Identity.hostname is set by the operator via the web UI and trusted; the command-line args are also trusted. None of the values come from web request data, which is the main untrusted source in a Django app.
2. **Validate at the boundary.** When `Identity.hostname` is updated via the web UI, the form validation rejects any character that isn't valid in a hostname (alphanumeric, dot, dash). So even if a malicious admin tried to set `hostname = "evil; rm -rf /"`, the form would reject it before it landed in the database.
3. **Read every generated artifact before installing it.** The deploy pipeline writes the artifacts to `BASE_DIR/deploy/` and then waits for the operator to scp them and run them. The operator should `cat` each file before installing. This is the same review step that happens with any auto-generated config — `terraform plan` before `terraform apply`, etc.

The combination of "trusted values only" + "validation at the boundary" + "human review before installation" makes the autoescape-off pattern safe in practice. It would not be safe in a context where untrusted user input could reach the templates.

## The base.html chassis

The HTML template family has one architectural piece worth singling out: `templates/base.html` is the chassis that every page extends. It contains:

- The HTML5 doctype + viewport meta
- The `<title>` block with the per-page override
- The CSS link via `{% static_v %}` for cache-busting
- The chronos topbar row (the world clock that floats at the top of every page)
- The navbar with links to every app (a single hardcoded list — every new app needs a manual `<a>` tag added)
- The messages strip (Django's flash messages)
- The `{% block content %}{% endblock %}` where the per-page content goes
- The chronos JS script tag, also via `{% static_v %}`

A page template looks like:

```
{% extends "base.html" %}
{% block title %}My page — Velour{% endblock %}
{% block extra_head %}<style>...</style>{% endblock %}
{% block content %}
  <h1>Hello</h1>
  ...
{% endblock %}
```

The `extra_head` block lets a page inject its own CSS or `<script>` tags into the document head. The `content` block is the body. Most templates use both blocks; a few use only `content`.

There is no `extra_body_end` block as a place to put scripts that should load after the content. Scripts that need to run after DOM ready use `DOMContentLoaded` listeners or are placed at the bottom of the `content` block. This is a slight inconvenience that could be fixed by adding an explicit block, and may be at some point — file under "small refactor".

## Cross-app template extension

A Velour app's template can extend another app's template. For example, the `cartography` app's per-scale templates (`earth.html`, `mars.html`, `moon.html`) extend `cartography/_base.html` which itself extends `base.html`. The per-scale templates only need to override the `map_content` block.

```
{% extends "cartography/_base.html" %}
{% block map_content %}
  <div id="map" class="map-container"></div>
  ...
{% endblock %}
```

Underscore-prefix template names (`_base.html`, `_topbar_clock.html`) signal that the file is a partial — meant to be included or extended by other templates, not rendered directly by a view. This is a Rails convention that Velour adopts because it's clear and the tooling doesn't care.

## When to add a third template family

The current rule is: only two template families, HTML and deploy. If you find yourself wanting to add a third (say, for generating LaTeX, or for emitting Markdown to be re-rendered elsewhere), the right question is whether the new family really needs Django templates or whether a simpler tool (Python f-strings, Jinja2 directly, just string concatenation) would do.

For generating short, structured output (a few hundred lines, a handful of variables), Django templates are overkill. Python f-strings are more readable and don't require a template loader. The deploy templates are only worth the Django infrastructure because they're long, the variables are reused across files, and the project already has Django running.

If you need a third template family that meets all of those criteria (long, repeated, variables-rich, in a project that already runs Django), put it in a new subdirectory like `app_factory/templates/<purpose>/` and follow the same naming convention. Otherwise, use a simpler tool.

## Summary

Two template families, one engine. The HTML family is conventional Django; the deploy family stretches the engine to render config files. The two coexist because Django's template syntax is sparse enough not to collide with shell or config syntax in practice. The escape rules differ — HTML autoescapes, deploy doesn't — and the safety of the autoescape-off pattern depends on never letting untrusted user input reach the deploy templates.

This is one of the load-bearing tricks in the Velour meta-layer. It's also a good demonstration of the principle that a tool designed for one job can be re-used for a closely-related job if you understand the tool well enough to know which guarantees still hold. Django's template engine was designed for HTML; we use it for shell because the parts that matter (parameter substitution, file loading, escape control) work the same way for both.
"""


# =====================================================================
# Hand-written chapter for Volume 1 Part III (Chapter 9)
# =====================================================================

def _ch9_generate_deploy():
    return """The `generate_deploy` management command is the entry point of the entire deploy pipeline. From the operator's perspective, it's a single line typed into a shell that produces a directory full of config files ready to scp onto a target host. From the inside, it's about 200 lines of Python that compose six template renders into one coherent deploy bundle. This chapter walks through the command end-to-end: the argument parsing, the value resolution chain (where each variable comes from when not passed explicitly), the template loading, the rendering pass, the file writing, and the testing strategy.

## The command signature

```
python manage.py generate_deploy
    [--server-name DOMAIN]
    [--user USERNAME]
    [--project NAME]
    [--port PORT]
    [--out-dir PATH]
```

All arguments are optional. If the operator passes none, the command derives sensible defaults from the running Velour project itself. If the operator passes some, the explicit values override the defaults. If the operator passes all, the defaults are bypassed entirely.

This argument-resolution behaviour is the most important thing to understand about `generate_deploy`. It's not "you must always specify these things"; it's "specify only what differs from the project's own configuration". For the common case of "I want to generate a deploy bundle for this exact velour", the command needs no arguments at all. For the edge cases (cloning a velour to a different domain, generating a child app under a different project name), the arguments override the defaults.

## The value resolution chain

For each variable used by the deploy templates, here's where the value comes from:

| Variable | Source (in priority order) |
|---|---|
| `server_name` | `--server-name` arg → `Identity.get_self().hostname` → `'example.com'` |
| `user` | `--user` arg → `BASE_DIR.name` (the project directory's name) → `getpass.getuser()` |
| `project` | `--project` arg → derived from `BASE_DIR.name` |
| `port` | `--port` arg → 7777 (the velour default) |
| `out_dir` | `--out-dir` arg → `BASE_DIR / 'deploy'` |
| `apps_dir` | computed: `/var/www/webapps/{user}/apps` |
| `static_dir` | computed: `/var/www/webapps/{user}/static` |
| `media_dir` | computed: `/var/www/webapps/{user}/media` |
| `run_dir` | computed: `/var/www/webapps/{user}/run` |
| `log_dir` | computed: `/var/www/webapps/{user}/log` |
| `socket_path` | computed: `{run_dir}/{project}.sock` |
| `venv_path` | computed: `{apps_dir}/{project}/venv` |
| `python_version` | `sys.version_info` of the running Python |

The point is: only the top 4 entries can be overridden. Everything below is computed deterministically from those 4. This is the strict-conventions payoff. The operator never has to remember "where does the supervisor program file want the gunicorn socket to live". It's always `/var/www/webapps/{user}/run/{project}.sock`. The deploy template just substitutes the value.

The most important entry in the table is the second row of the `server_name` resolution chain: it pulls from `Identity.get_self().hostname`. This is the load-bearing connection between the Identity model and the deploy pipeline that chapters 1, 2, and 6 keep mentioning. The whole chain is one line of Python:

```python
server_name = options['server_name'] or Identity.get_self().hostname or 'example.com'
```

Three sources, in order, with fallback to a placeholder. If you change Identity.hostname via the web UI and re-run `generate_deploy` with no arguments, the next nginx config has the new server_name. That's the entire mechanism.

## The render loop

After resolving all the values, the command builds a single context dictionary and passes it to `render_to_string` six times, once per artifact:

```python
context = {
    'project_name':  project,
    'user':          user,
    'server_name':   server_name,
    'port':          port,
    'apps_dir':      apps_dir,
    'static_dir':    static_dir,
    'media_dir':     media_dir,
    'run_dir':       run_dir,
    'log_dir':       log_dir,
    'socket_path':   socket_path,
    'venv_path':     venv_path,
    'python_version': python_version,
    'base_dir':      str(settings.BASE_DIR),
}

artifacts = [
    ('deploy/gunicorn.conf.py.tmpl', 'gunicorn.conf.py'),
    ('deploy/supervisor.conf.tmpl',  'supervisor.conf'),
    ('deploy/nginx.conf.tmpl',       'nginx.conf'),
    ('deploy/setup.sh.tmpl',         'setup.sh'),
    ('deploy/adminsetup.sh.tmpl',    'adminsetup.sh'),
    ('deploy/hotswap.sh.tmpl',       'hotswap.sh'),
]

out_dir.mkdir(parents=True, exist_ok=True)
for tmpl, out_name in artifacts:
    text = render_to_string(tmpl, context)
    (out_dir / out_name).write_text(text)
```

That's the heart of the command. Six templates, one context, six output files. The context has fewer than 15 keys; the loop has six iterations; the operation is fundamentally simple.

The `render_to_string` import is the Django template loader hook covered in chapter 5. Each call walks Django's template directories looking for the named template, finds it under `app_factory/templates/deploy/`, parses it once (cached on subsequent calls), substitutes the context variables, and returns the resulting string. The text goes straight to disk via `Path.write_text()`.

After the loop, the shell scripts get marked executable:

```python
for script in ['setup.sh', 'adminsetup.sh', 'hotswap.sh']:
    (out_dir / script).chmod(0o755)
```

`gunicorn.conf.py` and the conf files don't need executable bit. Only the shell scripts.

## The output directory layout

After a successful run, `BASE_DIR/deploy/` looks like:

```
deploy/
    gunicorn.conf.py
    supervisor.conf
    nginx.conf
    setup.sh         (chmod 755)
    adminsetup.sh    (chmod 755)
    hotswap.sh       (chmod 755)
```

Six files, totalling maybe 200 lines of text. The operator inspects them, scp's them to the target host, runs `setup.sh` once as root, and the new velour instance is up.

The `deploy/` directory is committed to git in some velour instances and gitignored in others. The current convention is to NOT commit it, because the file contents change every time `generate_deploy` runs and committing the output creates noisy diffs. The trade-off is that a fresh clone doesn't have a deploy/ directory ready to use; the operator runs `generate_deploy` on the clone first. This is fine because they were going to inspect the artifacts anyway.

## Error handling

The command's error handling is minimal because most things that can go wrong are obvious:

- **Missing template file**: Django raises `TemplateDoesNotExist`. The operator's fix is to check that `app_factory/templates/deploy/` exists and has the expected `.tmpl` files. This usually means a partial git checkout.
- **Missing context variable**: Django raises `VariableDoesNotExist` if a template references a variable not in the context. The fix is to add the variable to the context dict at the top of the command.
- **No Identity row**: `Identity.get_self()` would auto-create a row with default `hostname='example.com'`. The deploy artifacts then have `example.com` as the server_name, which is obviously a placeholder. The operator notices and either passes `--server-name` or sets the real hostname in the Identity admin first.
- **Permission denied writing to out_dir**: standard file system error. The fix is to ensure the user running `manage.py` has write permission to the deploy directory.
- **Invalid characters in user/project**: not currently validated. If the operator passes `--user 'evil; rm -rf /'`, the bad characters end up in the bash scripts. Don't do that. The defense is the trust model laid out in chapter 5: don't pass untrusted values to deploy templates.

The command does NOT validate the generated artifacts (e.g., it doesn't try to parse the rendered nginx.conf with nginx). It just emits text. Validation is the operator's job, done by reading the files before installing them.

## Idempotence

Running `generate_deploy` twice produces identical output (modulo timestamps in comments, if any). The command makes no record of having run; it's safe to invoke as many times as you want. There's no notion of "clean before generating" — each run overwrites the existing files.

This matters because the typical workflow is:

1. Edit `Identity.hostname` in the admin
2. Run `generate_deploy` to regenerate
3. `cat deploy/nginx.conf` to confirm
4. scp `deploy/nginx.conf` to the target host
5. Realize you wanted port 8888 instead of 7777
6. Run `generate_deploy --port 8888` to regenerate
7. scp again

The operator iterates until satisfied, then deploys. The command supports this by being cheap and idempotent.

## Testing the command

There's no automated test suite for `generate_deploy` in the current codebase. The reason is that the output is text, the inputs are well-defined, and the operator inspects every generated artifact before installing it. A unit test would be testing that the templates substitute variables correctly, which Django's template engine already tests.

That said, if you wanted to add tests, the right shape would be:

```python
def test_generate_deploy_basic():
    out_dir = tmp_path / 'deploy'
    call_command('generate_deploy', '--out-dir', str(out_dir),
                 '--server-name', 'test.example.com',
                 '--user', 'testuser',
                 '--project', 'testproj')
    assert (out_dir / 'gunicorn.conf.py').exists()
    assert (out_dir / 'supervisor.conf').exists()
    nginx = (out_dir / 'nginx.conf').read_text()
    assert 'server_name test.example.com;' in nginx
    assert '/var/www/webapps/testuser/' in nginx
```

A handful of these would catch most regressions. The hot path is so simple that the bugs that escape are usually template-side (a wrong variable name, a missing semicolon in nginx syntax) rather than command-side, and template bugs are caught by inspection.

## What generate_deploy does NOT do

The command writes deploy artifacts. It does not:

- **Push them to the target host.** That's `adminsetup.sh`'s job (covered in chapter 10).
- **Run setup.sh on the target.** That's the operator's job (covered in chapter 10).
- **Install Python dependencies.** That's the operator running `pip install -r requirements.txt` after rsync.
- **Run database migrations.** That's the operator running `python manage.py migrate`.
- **Create the superuser.** That's the operator running `python manage.py createsuperuser` once on the target.
- **Configure SSL.** That's the operator running `certbot` after the basic deploy is up. The generated `nginx.conf` has placeholder SSL paths that the operator fills in, OR an HTTP-only fallback that works without SSL for initial bring-up.

The split between "what `generate_deploy` does" and "what the operator does manually" is deliberate. Auto-generation is the right tool for the boilerplate that's identical across deploys (~95% of the work). The remaining 5% is per-deploy decisions that require operator judgement: what's my superuser email, do I want HTTPS yet, does this server have an existing nginx that needs coordination. Trying to automate the 5% would create an automation that's complicated enough to break when the operator's situation differs slightly from the assumed default.

`generate_deploy` is what's called a "scaffold generator" in some frameworks: it produces files that the operator then customizes. The customization is part of the workflow; the auto-generated starting point is the part that saves the most time.

## Where this fits in Volume 1

Chapter 9 covers the command's internals; chapter 10 covers `setup.sh` and the bootstrap sequence on the target host; chapter 11 covers the `hotswap.sh` daily workflow. Together they describe the entire deploy pipeline from "I want to set up a new velour" to "I just pushed a code change and the new version is live in 15 seconds". Chapters 12-14 in Part IV walk through a fully concrete worked example using all three.

If you're reading the volume in order, this is also where the meta-app idea from chapter 1 starts to feel concrete rather than abstract. Up to here, "Velour generates other Django projects" was a phrase. From here on, it's a Python function that runs in 200ms and writes six files.
"""


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


def _ch10_setup():
    return """Chapter 9 covered `generate_deploy`, the command that renders the deploy bundle on the developer's machine. This chapter covers what happens next: the operator scp's the rendered bundle to a target host and runs `adminsetup.sh` once. Three minutes later, the target host is running Velour behind nginx and the operator can open it in a browser.

The bootstrap flow is two shell scripts, not one. The privileged half — the "admin" part that installs system packages, creates users, and touches `/etc` — lives in `adminsetup.sh`. The unprivileged half — the part that only needs to write files in the project user's home directory — lives in `setup.sh`. Together they're the "setup.sh" of the chapter title, but the split matters, so this chapter treats them as two scripts.

## Why two scripts, not one

The first version of Velour's deploy pipeline had a single `setup.sh` that did everything. It ran as root (so it could `apt-get install` and `useradd` and symlink into `/etc/nginx/sites-enabled/`) and then dropped privileges via `sudo -u` to do the pip-install and the migrate and the collectstatic.

This worked, but it had an irritating property: any time the operator wanted to run "just the unprivileged half" — say, after pushing new code that needed a fresh `pip install -r requirements.txt` and a `migrate` — they had to either run the whole `setup.sh` again as root, which re-did the root work and re-prompted for a sudo password, or reach into the script and copy out just the project-user steps manually.

So the single file was split in two. `adminsetup.sh` is the one-shot bootstrap, run once ever per host. `setup.sh` is a small idempotent helper that runs as the project user, called both by `adminsetup.sh` during bootstrap AND by the operator directly for routine post-rsync updates. The split has a nice property: the more dangerous script (the one with `sudo`) is the one the operator runs less often; the script the operator runs daily is unprivileged and can't break the host.

## adminsetup.sh — the eight-step bootstrap

`adminsetup.sh` is run as a regular sudoer account on the target host, not as root. It refuses to run as root directly (there's an explicit `if [ "$(id -u)" = "0" ]; then exit 1; fi` check near the top). The reason is that running it as root would mask a real problem: `sudo` is how the script earns the right to do privileged things, and `sudo`-authenticated work leaves an audit trail in `/var/log/auth.log`. Running it as root bypasses that trail. Better to insist the operator use sudo.

The eight steps:

**[1/8] system packages.** `apt-get update && apt-get install -y python3 python3-venv python3-pip rsync nginx supervisor`. These are the five packages every Velour host needs. The list is short because Velour tries hard to keep its system-level footprint small. `python3` is the interpreter. `python3-venv` is what lets `python3 -m venv` work on a Debian/Ubuntu box where venv support is packaged separately. `python3-pip` is pip. `rsync` is for future hot-swaps. `nginx` is the front door. `supervisor` is the process manager.

Not in the list: anything database (Velour's default deploy uses SQLite), anything monitoring (Velour *is* the monitoring), anything mail (see the mailroom app chapter), anything SSL-related (SSL is a post-install step, done by certbot after the basic deploy is up).

**[2/8] project user.** The script creates a Linux user named after the project. If the user already exists, the creation is skipped. Either way, `$HOME` is locked down to mode 700 and owned by the user. This is the user the gunicorn worker will run as and the user Velour's own file operations are done as.

**[3/8] /var tree.** Create `/var/www/webapps/$USER/{run,static,log,apps}` with the correct ownership. `run/` is for the gunicorn Unix socket that nginx proxies to. `static/` is where `collectstatic` writes its output. `log/` is for gunicorn's access and error logs. `apps/` is the hook for the meta-app idea: this is where `app_factory` writes generated child projects on this host. It sits alongside the other three directories and is owned by the project user so Velour can create subdirectories there without needing root.

This step also sets up `/var/www/maintenance/index.html` — a host-wide static fallback page. Nginx is configured to serve this page if the upstream gunicorn socket is unreachable (app stopped, supervisor stopped, etc.). It's shared across every app on the host, owned by root, readable by nginx. The script only writes the default HTML if the file doesn't already exist, so a hand-edited maintenance page survives subsequent `adminsetup.sh` runs.

**[4/8] rsync source.** The operator uploaded the source tree to a staging directory before running `adminsetup.sh`; step 4 is the script rsyncing that staging tree into `/home/$USER/`. The rsync uses `-a --delete` (archive mode, including deletions, so the target ends up as an exact mirror of the staging directory) and a long exclude list:

```
venv/, __pycache__/, *.pyc, *.pyo, staticfiles/,
db.sqlite3, db.sqlite3-*,
secret_key.txt, health_token.txt, mail_relay_token.txt,
.env, .env.*,
.git/, .claude/, memory/,
*.swp, .*.swo, .DS_Store
```

Three classes of things in there. First, generated caches the target should rebuild on its own (venv, pyc, staticfiles). Second, secrets that must NEVER flow from dev to prod (the three `*_token.txt` files, plus `.env*`). Third, junk the developer shouldn't have been tracking anyway (swap files, .DS_Store, .claude/, memory/).

The exclude list is the load-bearing piece of the whole rsync. A hand-edited prod `secret_key.txt` that got clobbered by a dev one is a silent catastrophe — suddenly every signed session cookie is invalid and every logged-in user is logged out. The exclude list prevents that.

The rsync step handles `rsync` exit code 24 specially ("some files vanished before they could be transferred"). This happens when the source tree has files being written to mid-rsync — typically SQLite WAL/SHM sidecars if a Django process is touching the DB during the rsync. The script downgrades exit 24 to a warning: any file that vanished was, by definition, transient and not something the target needed.

**[5/8] symlink nginx + supervisor configs.** Two symlinks:

```bash
ln -sfn $APP_HOME/deploy/nginx.conf       /etc/nginx/sites-enabled/$USER
ln -sfn $APP_HOME/deploy/supervisor.conf  /etc/supervisor/conf.d/$USER.conf
```

The deploy bundle's `nginx.conf` and `supervisor.conf` live inside the app's own directory (under `/home/$USER/deploy/`). The symlinks make them visible to nginx and supervisor at their expected config-include locations. Using symlinks instead of copies has a nice property: if the operator edits `deploy/nginx.conf` after the fact (e.g., to add a certbot SSL block), the change is picked up by nginx on next reload, no second install step needed.

After the symlinks go in, `nginx -t` validates the config. If the generated nginx.conf has a syntax error, the script halts here before the supervisor and gunicorn steps run. The operator sees the nginx error message and fixes the template.

**[6/8] hand off to setup.sh.** `sudo -u $USER -H bash $APP_HOME/setup.sh`. This is where `adminsetup.sh` drops privileges and runs the unprivileged helper. setup.sh does venv creation, pip install, secret_key.txt generation, migrations, and collectstatic — all the things that only need access to the project user's home directory.

The `-H` flag tells sudo to set `$HOME` to the target user's home, which is important because pip's cache directory defaults to `$HOME/.cache/pip` and if `$HOME` is still the sudoer's home, pip tries to write into someone else's cache and fails.

Control returns from setup.sh after collectstatic finishes. By that point, every file the app needs is on disk in the right place: venv exists, deps are installed, secret_key exists, the SQLite db is migrated, staticfiles/ has been populated.

**[7/8] reload nginx.** `systemctl reload nginx`. Reload, not restart — we want graceful handling of in-flight requests. At this point, nginx knows about the new site (via the symlink from step 5) and the static files it needs to serve (populated by step 6).

**[8/8] supervisor.** `supervisorctl reread && supervisorctl update`, then start or restart the program depending on whether supervisor has seen it before. `reread` makes supervisor notice the new config file (via the symlink from step 5); `update` makes it apply the change. Start vs restart is decided by `supervisorctl status $USER`: if the program is unknown, start it; if it's already known, restart it.

This is the step that actually brings the app online. Up to here, nothing has been running — the app's files are on disk but no gunicorn worker exists. After step 8, there's a gunicorn process, bound to a Unix socket, supervising the Django app, proxied by nginx.

Three minutes, start to finish, on a fresh Ubuntu box.

## setup.sh — the unprivileged helper

`setup.sh` is shorter (five steps, not eight) and simpler (no sudo, no system packages, no `/etc` writes). It runs as the project user and its only side effects are inside `/home/$USER/`. The operator can run it freely without worrying about breaking the host.

**[1/5] virtualenv.** `python3 -m venv venv` if `venv/` doesn't exist. If it does, skip. Then `source venv/bin/activate` and upgrade pip/setuptools/wheel. Standard Python project setup.

**[2/5] dependencies.** First attempt: `pip install -r requirements.txt` in one shot. If this succeeds, great, done. If it fails (typically because some package in requirements.txt has an exact version pin that isn't available for the target platform — the `PyMySQL==1.1.2` problem), fall back to per-package install with version fallback.

The per-package fallback is the interesting part. For each line in requirements.txt, try installing it verbatim (respecting the pin). If that fails, try installing just the package name without the pin (letting pip pick the newest compatible version). If that also fails, log a warning and continue. The goal is "install as much as possible" rather than "install exactly this version set or nothing".

This is a deliberate trade-off. Strict version-pinning is best practice for reproducibility, but Velour's deploy target is heterogeneous — a fresh Ubuntu 24.04 with Python 3.12 on one host, a Raspberry Pi with Python 3.11 on another, an older Debian with Python 3.10 on a third. A pin that works on one platform can fail on another. The fallback trades reproducibility for deployability: a Velour that "mostly works" is strictly better than a Velour that fails to install at all.

After the requirements install, there's an explicit `pip install gunicorn` if gunicorn isn't already installed, because the supervisor config references gunicorn unconditionally and will fail to start without it.

**[3/5] Django SECRET_KEY.** If `$APP_HOME/secret_key.txt` doesn't exist, generate a 64-character random string (letters + digits + a small set of punctuation that's shell-safe). Write it to the file. chmod 600. If the file already exists, keep it.

The idempotence direction matters. "Generate if missing, keep if present" means re-running `setup.sh` never rotates the secret, which is good: rotating the SECRET_KEY invalidates every active session cookie, and a silent rotation during a routine re-run would log everyone out without warning.

**[4/5] migrations.** `python manage.py makemigrations --noinput && python manage.py migrate --noinput`. `makemigrations` before `migrate` is intentional — it guarantees the deploy is self-contained even if the source tree is missing a generated migration file. If every migration file is already in place (as it should be for a well-maintained repo), `makemigrations` is a no-op and `migrate` applies zero new migrations.

**[5/5] collectstatic.** `python manage.py collectstatic --noinput`. Collects all static files from all installed apps into `/var/www/webapps/$USER/static/`. Nginx serves this directory directly, bypassing Django entirely for static asset requests.

`--noinput` is there because the default behavior of collectstatic is to prompt "this will overwrite existing files, proceed? [y/n]" and a deploy script obviously can't answer an interactive prompt. The flag is mandatory in automated deploy contexts.

That's all five steps. After collectstatic, `setup.sh` exits. If it was called from `adminsetup.sh`, control returns there for the final two steps (reload nginx, reload supervisor). If it was called directly by the operator as part of a hot-swap flow, control returns to the operator's shell.

## What setup.sh deliberately does NOT do

As promised in the stub version of this chapter, here's the explicit negative space. `setup.sh` does not:

- **Create the superuser.** Per-deploy decision. The operator runs `venv/bin/python manage.py createsuperuser` once by hand after the first successful deploy.
- **Configure SSL.** Per-deploy decision. The operator runs `certbot` after the basic HTTP-only deploy is working, then edits `deploy/nginx.conf` to reference the new cert paths.
- **Install system packages.** That's `adminsetup.sh`'s job, done once per host.
- **Touch `/etc`.** Same reason.
- **Download external assets.** No calls to Kroki, no font downloads, no API fetches. Everything the app needs to boot is in the rsync'd source tree.
- **Run tests.** Tests run on the developer's machine before deploy; re-running them on the target is redundant and risks failing the deploy for an environmental difference (e.g., a timezone assumption that happens to hold on dev but not on the target).
- **Create or seed demo data.** That's a separate management command (`seed_devguide`, `seed_holidays`, etc.) the operator runs by hand after the first successful deploy.

The principle is: `setup.sh` handles everything that's the same across deploys, and leaves everything that's a per-deploy decision to the operator.

## The operator checklist

After `adminsetup.sh` finishes, the target host is running Velour but the operator still has three things to do:

1. **createsuperuser.** `sudo -u $USER /home/$USER/venv/bin/python /home/$USER/manage.py createsuperuser`. Without this, nobody can log in.
2. **Set up SSL.** `sudo certbot --nginx -d your.domain.tld`. Edit `deploy/nginx.conf` if certbot's autoconfig doesn't survive a regenerate.
3. **Visit the site.** `https://your.domain.tld/`. Log in as the superuser. Confirm the Dashboard loads. Confirm sysinfo shows the host's load and memory. Confirm the Identity row exists with the right hostname.

If all three steps pass, the deploy is done and the operator's work is over. If any of them fails, chapter 14 (the worked example) has a troubleshooting section for common failure modes.

## Where this fits in Volume 1

Chapter 9 covered the command that writes the deploy bundle. This chapter covered the scripts that consume the bundle to produce a running Velour instance. Chapter 11 covers `hotswap.sh` — the much-shorter daily-use script that skips most of `adminsetup.sh`'s work and just rsyncs new source + restarts supervisor.

Chapters 12-14 in Part IV walk through the whole bootstrap sequence in fully concrete detail for a fresh Ubuntu server, so the description in this chapter is more at the "why" level and the walkthrough is at the "what" level. If you want to follow along with real commands and real output, jump to chapter 12.
"""


def _ch11_hotswap():
    return """`hotswap.sh` is the operator's daily-use script. After `adminsetup.sh` has run once on the target host and the Velour instance is up, hot-swap is how code changes propagate from the developer's machine to production.

The script is deliberately small. Most of `adminsetup.sh`'s work was one-shot-per-host — installing system packages, creating a user, symlinking configs — and doesn't need to be redone on every deploy. What's left for daily use is: rsync the new source, run a subset of `setup.sh`'s idempotent housekeeping (fresh deps, fresh migrations, fresh static files), and restart the gunicorn workers.

This chapter walks through the whole thing, explains why it's safe for code changes but NOT for schema changes, and covers the three-line workflow the operator actually types.

## The hotswap script

The rendered `hotswap.sh` is about 40 lines. The core is:

```bash
# [1/4] rsync the source tree with the same exclude list adminsetup.sh uses
rsync -a --delete --exclude='venv/' --exclude='*.pyc' \\
      --exclude='db.sqlite3*' --exclude='secret_key.txt' \\
      --exclude='health_token.txt' --exclude='.git/' \\
      "$STAGING_DIR/" "$APP_HOME/"
sudo chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_HOME"

# [2/4] re-run setup.sh as the project user
sudo -u "$DEPLOY_USER" -H bash "$APP_HOME/setup.sh"

# [3/4] reload nginx
sudo systemctl reload nginx

# [4/4] restart gunicorn
sudo supervisorctl restart "$DEPLOY_USER"
```

The exclude list for the rsync is the same list `adminsetup.sh` uses, for the same reasons. Prod secrets stay on prod. Dev caches stay on dev.

The call to `setup.sh` is the "subset of adminsetup.sh's work" mentioned above. Since `setup.sh` is idempotent (venv skipped if present, secret_key skipped if present, migrations run only if new ones exist), re-running it on every hot-swap is cheap and safe. The only step that does meaningful work on a typical hot-swap is the pip install (which skips everything already installed, installs any new requirements) and collectstatic (which re-copies static files that changed).

The final `supervisorctl restart` is the load-bearing step. gunicorn has been running with the old code loaded into memory; restarting it forks new worker processes that read the new source tree. The restart is graceful (supervisor's default is SIGTERM followed by SIGKILL after a timeout) and in-flight requests get up to 10 seconds to finish before the worker is killed.

Total hot-swap time on a typical deploy: 10-20 seconds for the rsync, 5-10 seconds for `setup.sh` (mostly collectstatic), 2 seconds for supervisor restart. Call it 30 seconds end-to-end for a code-only change.

## When hot-swap is safe

Hot-swap is safe when:

- The change is Python code only. Views, URLs, templates, static assets, management commands, utility modules.
- The change includes new migrations that are purely additive and non-destructive. "Add a new model", "add a new field with a default", "create a new index".
- The change adds new static files or modifies existing ones. collectstatic handles this.
- The change adds new pip dependencies. `setup.sh` reruns `pip install -r requirements.txt` and picks them up.

That's the common case. Most deploys in practice are of this shape: small edits to views or templates, occasional new features that add a model or two, periodic dependency bumps.

## When hot-swap is NOT safe

Hot-swap is NOT safe when:

- **The change is a destructive migration.** Dropping a column, dropping a table, renaming a field (which Django treats as drop + add). The hot-swap runs migrations under its own control, before supervisor restart, which means there's a window where the new schema is live but the old gunicorn process is still serving old code that references the dropped column. Result: 500 errors until the restart completes a few seconds later.

- **The change requires data migration.** A custom RunPython migration that needs to touch existing rows. Django's `migrate` command runs these inline as part of the migration, which might take minutes on a large table, and the hot-swap waits for it. The hot-swap is fine; the outage window is just longer.

- **The change modifies static file hashes that are embedded in old templates.** Django's `ManifestStaticFilesStorage` hashes filenames, and if a template served by the old gunicorn references `main.abc123.css` while collectstatic has replaced it with `main.def456.css`, the user sees a 404 for the stylesheet until the gunicorn restart.

- **The change includes nginx config updates.** `hotswap.sh` reloads nginx (step 3), so it picks up changes to `deploy/nginx.conf` if those exist in the rsync'd source. But if the nginx config is syntactically invalid, the reload fails and nginx keeps serving the old config. The operator should run `sudo nginx -t` manually after any nginx config change to catch this.

- **The change includes a new supervisor config.** `hotswap.sh` restarts supervisor's gunicorn program but does NOT re-run `supervisorctl reread && supervisorctl update`. If `deploy/supervisor.conf` has changed, the changes are ignored. The operator needs to run `sudo supervisorctl reread && sudo supervisorctl update` by hand after the hot-swap.

The way to read this list: hot-swap is optimized for the common case (fast, safe, code-only) and assumes anything unusual is the operator's problem to handle manually. It doesn't try to detect the unsafe cases and bail out because the detection logic would be bigger than the script itself.

## The three-line operator workflow

From the developer's machine, the whole hot-swap is three commands:

```
rsync -a --delete ./velour-dev/ swibliq@snel.com:/home/swibliq/staging/
ssh swibliq@snel.com 'cd /home/swibliq/staging && bash hotswap.sh'
ssh swibliq@snel.com 'tail -f /var/www/webapps/swibliq/log/gunicorn.log'
```

Three lines. First line pushes the source. Second line runs the hot-swap. Third line is optional — it's just so the operator sees any startup errors in real time.

Some operators alias this as a shell function called `deploy`:

```bash
deploy() {
    rsync -a --delete ./velour-dev/ swibliq@snel.com:/home/swibliq/staging/
    ssh swibliq@snel.com 'cd /home/swibliq/staging && bash hotswap.sh'
}
```

After that, `deploy` from any terminal in the velour source tree, wait 30 seconds, done. This is the workflow the system is optimized for.

## What hot-swap deliberately skips

Compared to `adminsetup.sh`, `hotswap.sh` skips:

- System package installation (already done)
- User creation (already done)
- `/var` tree creation (already done)
- nginx + supervisor symlink creation (already done, and the symlinks point into `$APP_HOME/deploy/` so rsyncing new configs updates them automatically)
- nginx config validation (the operator's responsibility if they changed the config)
- supervisor `reread + update`

Everything in this list is "done once at bootstrap, not needed on code updates". The hot-swap's only job is to change the Python that gunicorn is serving.

## Why not zero-downtime

Hot-swap has a sub-second outage window where supervisor has killed the old gunicorn and the new one hasn't finished starting yet. Nginx handles the gap by serving the `/var/www/maintenance/index.html` fallback page, so a request that hits that window sees "Service temporarily unavailable" briefly.

For zero-downtime deploys, you'd need to run two gunicorn instances (blue/green), drain traffic from the old one via nginx config changes, start the new one, and then cut over. This is standard production practice for high-traffic sites. Velour doesn't do it because:

- The use case is personal + small-lab, not high-traffic. A sub-second outage during a deploy is fine.
- The implementation complexity is substantial (nginx upstream config, two supervisor programs, state coordination between them).
- The failure modes are subtle (blue and green pointing at the same SQLite file simultaneously is a correctness hazard).

If a future Velour grows into a use case where sub-second outages matter, this is where the deploy pipeline will need to change. For now, it's out of scope.

## Rollback

There is no built-in rollback. If a hot-swap breaks the app, the fix is to fix the source on the developer's machine and re-run the hot-swap. This is equivalent to "rollback" in the sense that you end up back at a working state, but it's not the same as "instantly revert to the previous deploy" because it requires the developer to know what the previous working state was.

If the operator wants real rollback, the standard technique is: keep the last N deploys in separate directories and swap the `/home/$USER/` symlink to the desired version. Velour's hot-swap doesn't do this because the overhead (disk space, N×SQLite databases, the question of "which SQLite is authoritative after a rollback") is bigger than the value.

The deliberate choice here is: trust the developer to not push broken code, and when they do, trust them to fix it forward rather than rolling back. This is appropriate for a single-developer lab tool. It would not be appropriate for a team of ten.

## Where this fits in Volume 1

This chapter closes Part III. Part IV (chapters 12-14) walks through the whole bootstrap sequence — `generate_deploy`, scp, `adminsetup.sh`, `setup.sh`, first boot — in fully concrete detail with real commands and real output. The reader who has made it through Part III should have enough conceptual understanding to follow Part IV without needing to pause and look things up.
"""


def _ch12_clone():
    return """The next three chapters are a worked example. You are going to take a freshly-installed Ubuntu 24.04 server, put Velour on it, and have a working instance you can open in a browser. Every command is shown. Every expected piece of output is shown. The edge cases you will hit the first time — Python version drift, missing system packages, SQLite permission quirks, that one pip wheel that doesn't exist for your architecture — are called out with their fixes.

This is meant to be read with a terminal open. If you type along, by the end of chapter 14 you will have Velour running in production, behind nginx, on a real domain, with an SSL certificate, and a second Velour-generated child app living alongside it under the same `/var/www/webapps/` tree. It should take you about 45 minutes.

Chapter 12 is the local bring-up: clone the source, install Python dependencies, migrate the database, create a superuser, and run the dev server. Chapter 13 generates a new app using `app_factory`. Chapter 14 deploys both Velour and the generated app to real hardware.

## Target environment

This walkthrough assumes:
- **OS**: Ubuntu 24.04 LTS (Server or Desktop — both work). Other Debian-family distros are fine with minor package-name adjustments. RHEL/Rocky/Fedora will need `dnf` in place of `apt-get`. NixOS is left as an exercise.
- **Hardware**: anything with ≥512MB RAM and ≥2GB free disk. A $5 VPS works. A Raspberry Pi 3B+ works. A 2010 ThinkPad works.
- **Network**: any internet connection. Velour talks to GitHub once during clone and PyPI once during pip install; after that, it works entirely offline.
- **User**: a non-root user with sudo. Do not run any of these commands as root directly.

If you're on a different OS, substitute your package manager as appropriate — `apt-get` → `dnf install`, `pacman -S`, `apk add`, etc. Nothing Velour uses is exotic.

## Step 1 — System packages

Velour is a Django project, so the host needs a Python 3 interpreter, venv support, pip, and git. Ubuntu 24.04 ships with Python 3.12 pre-installed but not the venv tooling. Install the four packages in one apt run:

```
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git
```

Expected output:

```
Reading package lists... Done
Building dependency tree... Done
The following additional packages will be installed:
  python3-pip-whl python3-setuptools-whl
The following NEW packages will be installed:
  git python3-pip python3-pip-whl python3-setuptools-whl python3-venv
0 upgraded, 5 newly installed, 0 to remove, 0 not upgraded.
Need to get 3452 kB of archives.
After this operation, 9341 kB of additional disk space will be used.
...
Setting up python3-venv (3.12.3-0ubuntu2) ...
```

On Ubuntu 24.04, `python3` is 3.12. Velour works on 3.10+. If you're on an older Ubuntu where the default is 3.10 or 3.11, those are also fine. If you're somewhere with 3.9 or earlier, you'll need to either install a newer Python via `deadsnakes` PPA or pick a different host — Velour's codebase uses 3.10 syntax like `match` statements and union-type hints.

## Step 2 — Clone the source

Pick a directory you're comfortable living in. For a dev setup, `~/velour-dev` is the convention used in this guide. For a production deploy, the source will ultimately end up in `/home/<user>/` owned by the project user, but that's chapter 14 territory — for now, just clone it wherever you'll be editing.

```
cd ~
git clone https://github.com/handyc/velour.git velour-dev
cd velour-dev
```

Expected output:

```
Cloning into 'velour-dev'...
remote: Enumerating objects: 4829, done.
remote: Counting objects: 100% (4829/4829), done.
remote: Compressing objects: 100% (2143/2143), done.
remote: Total 4829 (delta 2687), reused 4829 (delta 2687), pack-reused 0
Receiving objects: 100% (4829/4829), 8.42 MiB | 5.8 MiB/s, done.
Resolving deltas: 100% (2687/2687), done.
```

The clone is ~10MB because most of the repo is source code; the ET Book font adds ~1MB and the Skyfield JPL ephemeris (`de421.bsp`) adds another ~16MB — that's the single heaviest asset in the whole tree. If that bothers you for disk reasons, you can shallow-clone with `--depth 1` to skip the history.

**Common error**: `fatal: unable to access 'https://github.com/handyc/velour.git/': Could not resolve host: github.com`. This means you have no internet. Check `ping 8.8.8.8` first; if that works, your DNS is broken and you need to configure `/etc/resolv.conf`.

**Common error**: `Permission denied (publickey)`. You tried to clone via SSH (`git@github.com:...`) without having a key registered on GitHub. Use the HTTPS URL instead (as shown above).

## Step 3 — Create a virtualenv

Velour installs its Python dependencies into a project-local venv to avoid polluting the system Python or conflicting with other projects on the same host.

```
python3 -m venv venv
source venv/bin/activate
```

After `source venv/bin/activate`, your shell prompt changes to show `(venv)` as a prefix. Every `python` or `pip` command in the rest of this chapter runs inside the venv from now on. If you log out and back in, you need to re-source the activation script — or prefix commands with `venv/bin/python` and `venv/bin/pip`.

The venv directory (`venv/`) is gitignored. It lives in your project directory and is rebuilt from scratch if you ever delete it. Do not commit it.

## Step 4 — Upgrade pip and install the requirements

```
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

This is where most first-time installs spend their time. `pip install -r requirements.txt` downloads and installs ~40 Python packages. The heavy hitters are Django itself, Skyfield (for astronomical calculations in the chronos app), psutil (for sysinfo), pymysql and psycopg (for the databases app), and fpdf2 (for codex PDF rendering).

Expected output (abbreviated):

```
Collecting Django>=5.0
  Downloading Django-5.0.6-py3-none-any.whl (8.2 MB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 8.2/8.2 MB 14.3 MB/s eta 0:00:00
Collecting skyfield>=1.47
  Downloading skyfield-1.48-py3-none-any.whl (479 kB)
...
Installing collected packages: sqlparse, six, psutil, pillow, asgiref,
  Django, skyfield, pymysql, psycopg, fpdf2, ...
Successfully installed Django-5.0.6 Pillow-10.3.0 asgiref-3.8.1 ...
```

A clean install on a fast connection takes about 90 seconds. Slow networks or constrained CPUs can push this to 5 minutes or more — the longest single step is Pillow, which often builds from source because there's no prebuilt wheel for your platform.

**Common error**: `error: externally-managed-environment`. Ubuntu 24.04's system Python marks itself as "externally managed" to discourage pip installing to it. This error means you forgot to activate the venv. Run `source venv/bin/activate` first.

**Common error**: some package in requirements.txt fails with `ERROR: Could not find a version that satisfies the requirement`. This usually means you're on an old Python where the required minimum isn't available. `pip install Django` alone (without the version pin) often succeeds — then try `pip install -r requirements.txt` again.

**Common error**: `error: Microsoft Visual C++ 14.0 or greater is required`. You're on Windows, not Linux. Velour is tested on Linux and Mac. Windows works via WSL2 — install Ubuntu via WSL and run everything inside the Ubuntu shell.

## Step 5 — Database migrations

Velour uses SQLite by default for development. The database file is `db.sqlite3` at the project root, gitignored, created on first `migrate`. All ~30 Velour apps contribute tables. The first `migrate` creates roughly 80 tables and finishes in a couple of seconds.

```
python manage.py migrate
```

Expected output (abbreviated):

```
Operations to perform:
  Apply all migrations: admin, agricola, app_factory, auth, chronos,
  codex, contenttypes, dashboard, databases, experiments, hosts, identity,
  landingpage, logs, mailboxes, mailroom, maintenance, messages, nodes,
  security, services, sessions, sysinfo, terminal, winctl
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying auth.0001_initial... OK
  Applying admin.0001_initial... OK
  Applying agricola.0001_initial... OK
  Applying app_factory.0001_initial... OK
  ...
  Applying nodes.0001_initial... OK
  Applying nodes.0002_seed_hardware_profiles... OK
  Applying nodes.0003_sensor_reading... OK
  Applying nodes.0004_firmware... OK
  ...
```

The data migrations at the end of `nodes.0002_seed_hardware_profiles` and a few other places are how Velour seeds the initial catalog of hardware profiles, timezones, tradition rows for chronos, and so on. If you see those lines, your database is populated with a working starting set.

**Common error**: `django.db.utils.OperationalError: unable to open database file`. Velour tried to create `db.sqlite3` but the process couldn't write to the current directory. `chmod u+w .` or check you're in a directory you own.

## Step 6 — Create a superuser

Without a superuser, nobody can log in, which means the dashboard will redirect every request to the login page and the login page will reject every credential. Create one:

```
python manage.py createsuperuser
```

It prompts for a username, email, and password. Pick whatever you want — for dev, `admin` / `admin@example.com` / `admin` is fine and nobody will judge you. For prod, use something you'd actually call secure.

Expected interaction:

```
Username (leave blank to use 'yourname'): admin
Email address: admin@example.com
Password:
Password (again):
The password is too similar to the username.
This password is too short. It must contain at least 8 characters.
This password is too common.
Bypass password validation and create user anyway? [y/N]: y
Superuser created successfully.
```

Django warns you in dev but lets you override. In prod you'd pick a real password.

## Step 7 — Health and mail tokens

Velour has two bearer-token files that get generated by management commands:

```
python manage.py init_health_token
python manage.py init_mail_relay_token
```

Expected output:

```
Wrote /home/yourname/velour-dev/health_token.txt (48 chars).
Remember: this token grants read access to /sysinfo/health.json. Keep it private.

Wrote /home/yourname/velour-dev/mail_relay_token.txt (48 chars).
Remember: this token authenticates inbound mail relay POSTs. Keep it private.
```

Both commands are idempotent in the safe direction: they refuse to overwrite an existing token unless you pass `--force`, so if you re-run them on a configured host, nothing bad happens. Chapter 3 covers the secret-file protocol in detail; for now, just run both.

If you skip these two commands, the sysinfo health endpoint returns 500 and the mailroom inbound relay returns 401 for every request. Everything else in Velour still works. You can come back and run them later.

## Step 8 — Run the dev server

```
python manage.py runserver 7777
```

7777 is Velour's conventional dev port. Expected output:

```
Watching for file changes with StatReloader
Performing system checks...

System check identified no issues (0 silenced).
April 12, 2026 - 14:23:01
Django version 5.0.6, using settings 'velour.settings'
Starting development server at http://127.0.0.1:7777/
Quit the server with CONTROL-C.
```

Open `http://127.0.0.1:7777/` in a browser. You should see the Velour login page.

Log in with the superuser you created in step 6. You should land on the Dashboard — a 4x4 grid of cards, one per app. The sysinfo card should show the host's current load average. The Identity card should show "Velour" as the name and "(unnamed host)" as the hostname.

**If the Dashboard loads:** you're done with chapter 12. Velour is working locally on this host.

**If you get a 500 error:** the stack trace should show the actual failure. The most common ones on first boot are missing migrations (go back to step 5 and re-run migrate), missing static files (run `python manage.py collectstatic --noinput`), or a database permission issue (see step 5's common errors).

**If you get a connection refused:** check that runserver is still running. It runs in the foreground — the terminal needs to stay open. If you want to free the terminal, see step 9.

## Step 9 — Backgrounding the dev server (optional)

The dev server runs in the foreground by default. If you want to keep working in the same terminal, you have three options:

**Option a**: Run it in another terminal tab/pane. Simplest.

**Option b**: Run it in the background with `&` and redirect output:

```
python manage.py runserver 7777 > runserver.log 2>&1 &
```

Check the PID with `jobs`, stop it with `kill %1`.

**Option c**: Use tmux or screen. `tmux new -s velour`, start runserver, detach with `Ctrl-b d`, come back later with `tmux attach -t velour`.

None of these are how you'd run Velour in production. Production uses gunicorn + supervisor + nginx (chapter 14). But for dev, runserver in a tmux session is fine.

## Step 10 — Setting the hostname in Identity

The Identity app's `hostname` field is load-bearing — it's the ground truth for the nginx `server_name` directive in the deploy bundle. On a fresh install it's blank, so `generate_deploy` will complain about a missing hostname.

Set it now, even if you don't yet have a real domain. You can use the dev placeholder `localhost` and update it later.

Navigate in your browser to `http://127.0.0.1:7777/identity/edit/`. Fill in:
- **Name**: whatever you want to call this instance (e.g. "Velour Dev")
- **Hostname**: the public DNS name this instance will be reachable at (e.g. `velour.mydomain.com`), or `localhost` for pure dev
- **Admin email**: where prod errors will be emailed to (leave blank for dev)

Click Save. The Dashboard now shows your name at the top.

The hostname you entered will flow into `generate_deploy` → `nginx.conf` in chapter 14. That's the entire mechanism from chapter 2's "ground truth" diagram, made concrete.

## Where you are now

You have:
- A working Velour instance on `http://127.0.0.1:7777/` (dev server only — not reachable from other machines on your LAN yet; bind to `0.0.0.0:7777` if you need that)
- A superuser you can log in as
- Health and mail relay tokens generated
- An Identity row with a hostname you control
- Every app's migrations applied and its initial seed data (hardware profiles, timezones, traditions, etc.) loaded

You do NOT yet have:
- Any nodes registered in the fleet (that comes when you flash an ESP device — see the nodes firmware docs)
- Any documentation manuals seeded (run `python manage.py seed_quickstart` and `seed_devguide` to populate Codex)
- Any deployment artifacts (chapter 14)
- A child app generated by app_factory (chapter 13)

## Where this fits in Volume 1

Chapter 12 is the local bring-up. Chapter 13 is the generation of a sibling project under the meta-app model: using `app_factory` to create a new Django child project that Velour itself manages. Chapter 14 is the final deploy step — taking both Velour and the child app from the local dev machine out to a real production host.

By the end of chapter 14, you will have the equivalent of the author's own production setup: one Velour instance visible at `velour.mydomain.tld`, one child app at `labforms.mydomain.tld`, both hot-swappable with a two-line rsync-and-restart workflow.

If at any point during the remaining two chapters you hit an error that isn't mentioned in the "common errors" callouts, the fastest debugging path is `tail -f runserver.log` on whichever terminal has the dev server. Django's tracebacks are verbose and usually tell you exactly what's wrong; the fix is almost always in the last five lines of the traceback.
"""


def _ch13_generate():
    return """Chapter 12 got you to a working Velour on a single host, logged in as a superuser, Dashboard rendering, sysinfo reporting. That Velour is now running as a meta-app — which means it can generate *other* Django projects. This chapter walks through using `app_factory` to do exactly that: create a new child project that will live alongside Velour under the same `/var/www/webapps/` tree in chapter 14, owned by a different Linux user, proxied by the same nginx.

The example we're going to build is "lab-forms" — a small internal tool for capturing research subject data (consent forms, intake surveys, incident reports, whatever the lab needs). We pick it because it's representative of the one-off tools app_factory is designed to make trivial: a few models, a handful of views, an admin UI, no API, no realtime, no microservices. The kind of app a lab needs exactly once and never touches again except to add a new form type.

## The meta-app premise, recapped

Velour runs as a project under some Linux user (in this walkthrough, your dev user — in chapter 14 that becomes a dedicated project user). Inside Velour is the `app_factory` app. Its job is to render a new Django project from templates, place the rendered files somewhere under `/var/www/webapps/<deploy_user>/apps/<project>/`, and track the resulting row in a `GeneratedApp` model so Velour knows about it. From that point on, the child project is an independent Django codebase — you `cd` into it, activate its own venv, edit its own settings — but Velour still tracks it and can generate deploy artifacts for it the same way it does for itself.

The important idea is that Velour doesn't *run* the child app. It generates it and then gets out of the way. A child app deployed to production is its own gunicorn process, its own supervisor program, its own nginx server block. Velour is a factory, not a runtime.

## Step 1 — Open the app factory UI

From the running Velour dev server (http://127.0.0.1:7777/ from chapter 12), navigate to the Dashboard and click the **App Factory** card. You land at `/app-factory/` which shows a list of existing generated apps. On a fresh install the list is empty.

Click **Create New App**. A form appears with these fields:

- **Name**: The human-readable name of the new project. Pick `lab-forms` — the slug generator will derive a directory name from it (`lab_forms`).
- **Description**: Free text. Used in the generated `README.md` and the Codex Quickstart section for the child project. For this walkthrough, paste: *"Research subject data capture for the Leiden aquarium lab. Consent forms, intake surveys, incident reports."*
- **App Type**: Two choices. **Blank Django App** generates a minimal Django project with one "hello world" app inside it. **Clone of Velour** generates a project with every Velour app pre-installed — useful when you want the new project to inherit the whole meta-app stack (codex, identity, dashboard, etc.). For lab-forms we want **Blank Django App** because a research-forms tool doesn't need all that scaffolding; pick it.
- **Deploy User**: The Linux user the new app will run as in production. This user will be created by `adminsetup.sh` (chapter 10). For lab-forms, use `labforms` — the deploy-layout convention is that the user name is the project name with hyphens removed.

Click **Create**. The page redirects to a status view showing the new app in **Pending Review** state.

## Step 2 — What just happened on disk

Behind the scenes, `app_factory` did the following:

1. Resolved the directory where the new project will live. The default convention (see `/var/www/webapps/<deploy_user>/apps/<project>/`) is used, but in dev mode where `/var/www` might not exist or might not be writable, app_factory falls back to `BASE_DIR / 'generated_apps' / <project>/`. You'll see which directory was chosen in the detail view.

2. Copied a project template from `app_factory/templates/blank_project/` (or `clone_project/` if you chose Clone of Velour) into the target directory. The template has placeholders like `{{ project_name }}` and `{{ app_label }}` that get substituted at copy time.

3. Wrote a `GeneratedApp` row in the database with status `pending` so the Velour UI knows about it.

The detail view at `/app-factory/<id>/` shows you the file tree of the generated project. For `lab-forms` you should see:

```
lab_forms/
├── manage.py
├── requirements.txt
├── README.md
├── lab_forms/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── hello/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   └── templates/hello/
│       └── index.html
└── templates/
    └── base.html
```

The `hello/` app is the minimal stub — one view that renders "Hello, {{ project_name }}." — just so the new project has something to serve when you run the dev server for the first time.

## Step 3 — Run the child app's dev server

From the app_factory detail view, click **Start Dev Server**. This does three things:

1. Picks an open port in the 8001-9000 range using `_find_open_port()`. For the first generated app, you'll usually get 8001.
2. Runs `python manage.py runserver 8001` as a subprocess, storing the PID on `GeneratedApp.dev_pid` so a later **Stop** click can kill it.
3. Redirects back to the detail view which now shows the dev server as **Running** with a clickable link to `http://127.0.0.1:8001/`.

Open that link in a new tab. You should see the hello stub — a minimal page saying "Hello, lab-forms." with the project name and a timestamp.

If the link gives you a connection refused, the subprocess didn't start. Check the Velour runserver's own log output — app_factory logs child-process stderr to `runserver.log` or the terminal Velour is running in. Most common cause: missing dependency in the child project's `requirements.txt`. Chapter 13 walks through the install; chapter 12's pip-install errors apply here too.

## Step 4 — Add the first real model

The stub app is now running. Time to edit it. Open a terminal and `cd` into the child project directory (the detail view tells you the exact path). Example:

```
cd ~/velour-dev/generated_apps/lab_forms
ls
```

Create a new Django app inside the project:

```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py startapp forms
```

Edit `forms/models.py`:

```python
from django.db import models


class ConsentForm(models.Model):
    subject_name = models.CharField(max_length=200)
    subject_email = models.EmailField(blank=True)
    study_name = models.CharField(max_length=200)
    consented = models.BooleanField(default=False)
    signed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f'{self.subject_name} — {self.study_name}'
```

Register it in `lab_forms/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    ...
    'hello',
    'forms',   # new
]
```

Run migrations and create a superuser:

```
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

Register `ConsentForm` in `forms/admin.py`:

```python
from django.contrib import admin
from .models import ConsentForm

admin.site.register(ConsentForm)
```

Restart the dev server (from the app_factory detail view, click **Stop**, then **Start Dev Server** again). Navigate to `http://127.0.0.1:8001/admin/`, log in, and you should see **Consent forms** in the admin index. Click it, add one, save. The model works.

## Step 5 — Generate deploy artifacts for the child app

The child project is working locally. Now we want deploy artifacts for it — the same kind of gunicorn/supervisor/nginx bundle chapter 9 covered for Velour itself. app_factory handles this too.

Back in the Velour UI, from the child app's detail view, click **Generate Deploy Bundle**. This runs:

```
cd ~/velour-dev/generated_apps/lab_forms
python manage.py generate_deploy --user labforms --project lab_forms
```

Under the hood, the `generate_deploy` command from chapter 9 gets called inside the child project's venv. It resolves the values from `--user labforms` and `--project lab_forms` and writes six files to `lab_forms/deploy/`:

```
deploy/
├── gunicorn.conf.py
├── supervisor.conf
├── nginx.conf
├── setup.sh         (chmod 755)
├── adminsetup.sh    (chmod 755)
└── hotswap.sh       (chmod 755)
```

These are the same six artifacts Velour itself generates for its own deploy. The only differences are the substituted values: `user=labforms`, `project=lab_forms`, `socket_path=/var/www/webapps/labforms/run/lab_forms.sock`, and so on.

Open `deploy/nginx.conf` in an editor. You should see something like:

```nginx
server {
    listen 80;
    server_name labforms.your-hostname;

    location /static/ {
        alias /var/www/webapps/labforms/static/;
    }

    location / {
        proxy_pass http://unix:/var/www/webapps/labforms/run/lab_forms.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

The `server_name` is `labforms.your-hostname` — meaning the child app will be served at `labforms.<your Velour hostname>`. If you set Velour's hostname to `lab.local` in chapter 12 step 10, the child app's nginx config says `labforms.lab.local`. That's the subdomain composition pattern chapter 2 described: host root + project user.

## Step 6 — Approve the app

Back in the Velour UI, the child app is still in **Pending Review** status. The review step exists so a human can approve each generated app before it gets treated as "real" — a safety check against accidentally generating a project and forgetting about it.

Click **Approve**. The status flips to **Approved** and the detail view unlocks a few more actions: **Deploy to Production**, **Rename**, **Delete** (which now actually removes the on-disk directory in addition to the database row).

You're done with chapter 13. The `lab-forms` project exists as a real Django codebase, runs locally on port 8001, has one model with admin integration, and has a full deploy bundle waiting for chapter 14 to ship it to a real host.

## Common errors and fixes

**"Could not find template blank_project"**: app_factory couldn't locate its project template directory. This usually means a partial git checkout — verify `app_factory/templates/blank_project/` exists and has the expected files.

**"Permission denied creating /var/www/webapps/..."**: app_factory's default deploy path is `/var/www/webapps/` which is typically root-owned. In dev mode, app_factory should fall back to `generated_apps/` under the project root. If it's not falling back, check `app_factory/views.py:app_create` for the path resolution logic — there's a `_resolve_target_dir` helper that does the fallback.

**Child project startup fails with "ModuleNotFoundError: No module named 'django'"**: the child project's venv wasn't activated before running `manage.py`. Either `source venv/bin/activate` first, or use the full path `venv/bin/python manage.py ...`.

**Port 8001 already in use**: another generated app or another process is on that port. `_find_open_port()` should have picked a different one. If it didn't, pass `--port 8002` manually to the runserver call.

**Admin login prompts but never authenticates**: you created a superuser for the Velour project, not for the child. Django's `createsuperuser` is per-database and each child project has its own `db.sqlite3`. Re-run `createsuperuser` inside the child project's directory with its own venv activated.

## What the child app inherits vs. what's blank

A **Blank Django App** (what we picked) starts with:
- The Django framework (in requirements.txt)
- A minimal `settings.py` with nothing but Django's built-in apps
- One "hello world" stub app
- A base template that extends nothing
- Its own `db.sqlite3` (created on first `migrate`)

It does NOT inherit:
- Any Velour-specific apps (codex, identity, sysinfo, etc.)
- Velour's ET Book fonts
- Velour's static CSS
- Velour's user accounts
- Velour's templates

If you pick **Clone of Velour** instead, you get all of the above — every Velour app pre-installed, every migration rolled in, the full meta-app stack. Clone of Velour is useful when you want a child project that is itself a Velour instance (recursive meta-apps). For lab-forms we don't need that.

The split is deliberate: most child apps are lightweight single-purpose tools and shouldn't carry the weight of the full Velour codebase. The rare child that wants to be a Velour-ish thing in its own right can opt in.

## Where this fits in Volume 1

Chapter 12 got you a running Velour. Chapter 13 just showed that Velour can generate other Django projects — that's the meta-app premise made concrete. Chapter 14 takes the lab-forms child app from its local dev state and deploys it to a real production host alongside Velour, using the `adminsetup.sh` / `setup.sh` workflow from chapter 10 and the `hotswap.sh` workflow from chapter 11.

By the end of chapter 14 you will have:
- One Velour instance running at your production hostname
- One lab-forms child app running at the `labforms.<hostname>` subdomain
- Both owned by different Linux users
- Both hot-swappable with a three-line rsync-and-restart
- Both rendered by the same nginx
- Both visible in the Velour fleet view

That's the full meta-app pattern, deployed.
"""


def _ch14_deploy():
    return """The final chapter of the worked example. Chapter 12 got you Velour running locally. Chapter 13 generated a lab-forms child app also running locally. Chapter 14 takes both of those local instances and deploys them to a real production host — a separate Linux server, under separate project users, proxied by the same nginx, reachable at real DNS names, with SSL certificates.

By the end of this chapter you will have the deployment shape the author's own Velour runs in production: one Velour instance at a primary hostname, one or more child apps at subdomain names, everything hot-swappable from the dev machine with a two-line workflow.

## Target environment

- **Target host**: a second Linux server (cloud VPS, bare metal, Raspberry Pi — anything with ssh access). Ubuntu 24.04 LTS is what this walkthrough assumes. Other distros work with `apt-get` substituted.
- **DNS**: you own a domain and can point subdomains at the target host's IP. For the walkthrough, assume `lab.example.com` is the primary Velour hostname and `labforms.lab.example.com` is the child app subdomain. Substitute your own domain.
- **SSH access**: you can ssh from the dev machine to the target as a user with sudo privileges. Key-based auth is strongly recommended.
- **Ports open**: the target host's firewall allows inbound 22 (ssh), 80 (http), 443 (https).

## Step 1 — Point DNS at the target

Before anything else, make sure DNS is working. On your domain registrar or DNS provider's panel, add A records:

```
lab.example.com         → <target host's public IP>
labforms.lab.example.com → <target host's public IP>
*.lab.example.com       → <target host's public IP>  (wildcard, optional)
```

The wildcard is a shortcut for future child apps: once it's in place, any new subdomain you add in a generated app just works without touching DNS again. If you'd rather manage subdomains explicitly, skip the wildcard and add A records per child app.

Verify DNS is live:

```
dig +short lab.example.com
# should print the target IP
dig +short labforms.lab.example.com
# should print the same IP
```

DNS propagation can take 5-60 minutes depending on your TTL settings. You can proceed with the rest of the chapter while you wait; certbot's DNS challenge is the first step that actually needs DNS to be resolving.

## Step 2 — Set the Identity hostname on the dev Velour

The deploy pipeline reads `Identity.hostname` from the dev Velour and substitutes it into every generated nginx.conf. Chapter 12 step 10 had you set this to a placeholder. Now set it to the real primary hostname.

Navigate in your browser to `http://127.0.0.1:7777/identity/edit/`. Change **Hostname** to `lab.example.com`. Save.

## Step 3 — Generate Velour's deploy bundle

From the dev machine, in the Velour project directory:

```
cd ~/velour-dev
source venv/bin/activate
python manage.py generate_deploy
```

With no arguments, `generate_deploy` uses the defaults from chapter 9's value resolution chain: server_name comes from Identity.hostname (now `lab.example.com`), user and project come from `BASE_DIR.name` (probably `velour-dev` or `velour`), port from the default (7777), and all computed paths derive from those four.

Expected output:

```
Rendered deploy/gunicorn.conf.py
Rendered deploy/supervisor.conf
Rendered deploy/nginx.conf
Rendered deploy/setup.sh
Rendered deploy/adminsetup.sh
Rendered deploy/hotswap.sh
Done.
```

Inspect `deploy/nginx.conf`:

```
cat deploy/nginx.conf
```

You should see `server_name lab.example.com;` and socket paths like `/var/www/webapps/<project>/run/<project>.sock`. If the server_name still says `example.com` it means Identity.hostname didn't get updated — re-check the Identity edit page.

## Step 4 — Generate the child app's deploy bundle

From the lab-forms child project directory:

```
cd ~/velour-dev/generated_apps/lab_forms
source venv/bin/activate
python manage.py generate_deploy --server-name labforms.lab.example.com --user labforms
```

Here we pass the server-name explicitly because the child project doesn't have its own Identity row — its generate_deploy falls back to whatever Identity says, which would be `lab.example.com` (wrong; we want the subdomain). The `--user labforms` is also explicit because the child project's `BASE_DIR.name` is `lab_forms` which would give us a slightly wrong project user name.

Inspect the generated `deploy/nginx.conf` — it should now say `server_name labforms.lab.example.com;` and reference `/var/www/webapps/labforms/run/lab_forms.sock`.

## Step 5 — Push Velour's source to the target host

Pick a staging directory on the target host — a temporary location where the source tree will live while adminsetup.sh copies it into the final home. `/tmp/velour-staging` works fine; it gets cleaned up on reboot anyway.

From the dev machine:

```
rsync -av --exclude='venv/' --exclude='__pycache__/' --exclude='*.pyc' \\
    --exclude='db.sqlite3' --exclude='secret_key.txt' \\
    --exclude='health_token.txt' --exclude='.git/' \\
    ~/velour-dev/ youruser@lab.example.com:/tmp/velour-staging/
```

Expected output: a long list of file names and a summary line like `sent 8.4M bytes  received 1.2K bytes  1.1M bytes/sec`.

The exclude list is the same one chapters 10 and 11 cover — generated caches and local secrets stay off the target.

## Step 6 — Run adminsetup.sh on the target

SSH to the target host as a sudoer (not root):

```
ssh youruser@lab.example.com
cd /tmp/velour-staging
bash deploy/adminsetup.sh
```

Expected output — eight numbered steps, each printing a `[N/8]` header. You'll see apt-get installing python3/nginx/supervisor/rsync, a project user getting created, `/var/www/webapps/velour-dev/` being created and chowned, the rsync from staging to `/home/velour-dev/`, nginx config validation (`nginx -t`), the hand-off to setup.sh for venv+pip+migrate+collectstatic, and finally supervisor starting the gunicorn program.

Total wall time: 1-3 minutes depending on network speed for the pip install.

At the end, `supervisorctl status` should show `velour-dev RUNNING`.

Common error: `ERROR: run adminsetup.sh as a regular sudoer, not as root directly.` — you're running the script as root (via a root shell or `sudo -i`). Log out, log back in as your regular user, use `sudo` per-command instead. The script refuses root on purpose (chapter 10 explains why).

## Step 7 — Create the superuser

`adminsetup.sh` deliberately does NOT create a superuser — that's a per-deploy decision. Create one now:

```
sudo -u velour-dev /home/velour-dev/venv/bin/python \\
    /home/velour-dev/manage.py createsuperuser
```

Enter username, email, password. Velour asks you to bypass weak-password validation on dev; on prod you should pick a real password.

## Step 8 — First visit (HTTP, no SSL yet)

At this point you should be able to visit `http://lab.example.com/` in your browser. You'll see the Velour login page. Log in with the superuser you just created. Dashboard should load.

If you get a connection refused: check that nginx is actually running (`sudo systemctl status nginx`), that supervisor started the gunicorn program (`sudo supervisorctl status`), and that the nginx config was reloaded after the symlink into `sites-enabled` was created (step 7 of adminsetup.sh does this).

If you get a 502 bad gateway: the gunicorn socket is unreachable. Check `sudo supervisorctl status velour-dev` — should say RUNNING. If it says FATAL, check `/var/log/supervisor/velour-dev-stderr.log` for the startup error. Most common cause: a Python dependency that installed on dev but failed on prod (different Python minor version, missing system library).

## Step 9 — SSL via certbot

Install certbot:

```
sudo apt-get install -y certbot python3-certbot-nginx
```

Run it against the primary hostname:

```
sudo certbot --nginx -d lab.example.com
```

Certbot edits the nginx config in place, adds the SSL server block, reloads nginx. At the end you should be able to visit `https://lab.example.com/` and see a valid certificate.

Important: certbot's edits to `deploy/nginx.conf` do NOT propagate back to your dev machine. If you regenerate the deploy bundle on dev and rsync it to prod, certbot's SSL edits will be overwritten and you'll have to re-run certbot. The workaround is to keep certbot's edits in a separate include file that your nginx.conf references and that `generate_deploy` doesn't touch. Chapter 11's "When hot-swap is NOT safe" section describes this trap.

## Step 10 — Repeat steps 5-9 for the lab-forms child app

The child app deploys with the exact same sequence. The only differences are:

- rsync source is `~/velour-dev/generated_apps/lab_forms/`
- Staging directory is `/tmp/labforms-staging`
- The user created by adminsetup.sh will be `labforms` (from step 4's `--user labforms`)
- The nginx config will bind to `labforms.lab.example.com`
- You'll run certbot with `-d labforms.lab.example.com`

The child app's admin lives at `https://labforms.lab.example.com/admin/`. Create its own superuser — remember, the child project has its own db.sqlite3 with its own auth table.

## Step 11 — Verify both are live

From anywhere on the internet:

```
curl -I https://lab.example.com/
# HTTP/1.1 200 OK (or 302 if unauthenticated; either is fine)

curl -I https://labforms.lab.example.com/
# HTTP/1.1 200 OK or 302
```

Both should respond with valid SSL certificates. Open both in a browser:

- `https://lab.example.com/` — Velour dashboard, sysinfo showing the target host's load, Identity showing the hostname you configured
- `https://labforms.lab.example.com/admin/` — lab-forms admin, with the ConsentForm model you added in chapter 13

You now have the full deployed shape: two independent Django projects, two project users, two supervisor programs, one nginx, two SSL certificates, one sudoer human operator, one Velour dev machine that can hot-swap either project with a two-line workflow (chapter 11).

## Step 12 — Confirm hot-swap works

From the dev machine, make a tiny visible change to Velour — edit `templates/dashboard/home.html` and add a comment, or bump a version string. Then:

```
cd ~/velour-dev
rsync -av --exclude='venv/' --exclude='*.pyc' --exclude='db.sqlite3' \\
    --exclude='secret_key.txt' --exclude='health_token.txt' \\
    --exclude='.git/' \\
    ./ youruser@lab.example.com:/tmp/velour-staging/
ssh youruser@lab.example.com 'cd /tmp/velour-staging && bash deploy/hotswap.sh'
```

Expected output on the target: the 4 steps of hotswap.sh (rsync, re-run setup.sh, reload nginx, restart supervisor). Total wall time: 20-45 seconds.

Refresh `https://lab.example.com/` in the browser. Your change should be live. Repeat for the child app by substituting `lab_forms` for the source path and `/tmp/labforms-staging` for the destination.

## What you've built

Walk back through the three chapters of Part IV to see the shape of what just happened:

- **Chapter 12**: fresh Linux host → Velour running locally on 7777
- **Chapter 13**: Velour running locally → generated lab-forms child app running locally on 8001
- **Chapter 14**: two local projects → two production deployments, SSL, DNS, supervisor, nginx

That's the full Velour deploy story end to end. Every command shown is one you could type yourself against real hosts. The steps never branch into "and then write 200 lines of custom Ansible" or "and then configure the Kubernetes manifests" — the whole pipeline is bash scripts, Django management commands, and rsync. Nothing fancy. That's the value proposition: a small, legible deploy pipeline for single-developer Django projects that doesn't require learning a new infrastructure-as-code language to maintain.

## Common production gotchas

**SSL cert won't issue**: certbot's HTTP-01 challenge requires your nginx to be serving something on port 80. If nginx isn't running, if your cloud firewall is blocking port 80, or if DNS hasn't propagated, the challenge fails. Check `curl -I http://lab.example.com/.well-known/acme-challenge/test` responds with something non-empty before running certbot.

**Supervisor says RUNNING but the app 502s**: the gunicorn socket path in `supervisor.conf` doesn't match the `proxy_pass` line in `nginx.conf`. This should never happen because both are generated from the same template context in generate_deploy, but if you hand-edited one of them, check the two paths match.

**The hot-swap restarts succeeded but changes don't appear**: Django's template cache, your browser's cache, or nginx's static-file caching. Force refresh with Ctrl+Shift+R in the browser. If that doesn't help, SSH to the target and check that the source file on disk actually has your changes (`cat /home/velour-dev/templates/dashboard/home.html`).

**Port 7777 is accessible from the public internet**: this is bad. Velour's dev server shouldn't be on a public port. The correct production setup serves Velour via gunicorn+supervisor behind nginx on 80/443, not via runserver on 7777. Check that supervisor.conf references gunicorn and not `manage.py runserver`.

**Different Python versions between dev and prod**: a dependency that builds from source on dev's Python 3.12 may fail on prod's Python 3.10. The fix is either to match Python versions (install 3.12 on prod via deadsnakes PPA), bump the dep to a version that has a prebuilt wheel for 3.10, or tolerate the version fallback in setup.sh (which will install the closest-available version).

## Where this fits in Volume 1

This chapter closes Volume 1. You now understand:

- **Part I (Ch 1-5)**: the meta-app idea, deploy pipeline anatomy, secret-file protocol, app layout conventions, template system.
- **Part II (Ch 6-8)**: Identity and the attention engine, sysinfo as the external view of the host.
- **Part III (Ch 9-11)**: generate_deploy internals, setup.sh/adminsetup.sh bootstrap, hotswap.sh daily workflow.
- **Part IV (Ch 12-14)**: the full worked example from empty Linux box to running production.

Volumes 2-5 are still ahead. Vol 2 covers every Velour app in depth (dashboard, terminal, sysinfo, identity, codex, nodes, chronos, mailboxes, mailroom, etc.) — one chapter per app. Vol 3 covers the codex system in detail — PDF rendering, Tufte influences, sparkline math, the periodic reports infrastructure. Vol 4 covers the Identity loop in depth — the attention engine, sensors, rules, concerns, reflections, the Oracle integration, and future ML hooks. Vol 5 covers operations: deploy, monitoring, incident response, upgrade paths, scaling, the fleet view across many Velour instances.

But the foundation is here. If Volume 1 is all you ever read of this guide, you know how to bring up Velour on a fresh host, generate and deploy child apps, and maintain the whole stack with a two-line daily workflow. That's enough to run a lab.
"""


# =====================================================================
# Volume 2 — The Web Layer
# =====================================================================

VOL2_CHAPTERS = [
    ('ch1-dashboard',
     'Chapter 1 — The dashboard and base.html',
     'The 4×4 grid of cards on /dashboard/, the chronos topbar '
     'context processor, the body-class convention, the Tufte-'
     'influenced palette in static/site.css, and the no-JavaScript-'
     'first principle. Includes the dashboard\'s rendering pipeline '
     'from card definition to grid placement, and the rules for when '
     'a feature gets a card vs a top-menu link only.'),
    ('ch2-terminal',
     'Chapter 2 — Web Terminal (Channels + ASGI + xterm.js)',
     'Two ASGI consumers: PTY-backed shell terminal and ssh-tunnelled '
     'foreign-host terminal. The xterm.js client wiring, the WebSocket '
     'frame format, terminal-history persistence, and security '
     'hardening (allowed-hosts allowlist, auth gate, no shell escapes '
     'without an interactive PTY).'),
    ('ch3-template-conventions',
     'Chapter 3 — Template conventions and the static asset pipeline',
     'How templates/<app>/ inherits from base.html. The static_v cache-'
     'busting suffix. ET Book bundling for Codex. Per-app vs project-'
     'level static dirs. The convention that templates carry zero '
     'inline JavaScript except for the dropdown plug.'),
    ('ch4-chronos-topbar',
     'Chapter 4 — Chronos in the topbar (context processor anatomy)',
     'How the chronos clock and 32 world-time chips render on every '
     'page via a single context processor. The processor\'s caching '
     'discipline. The CSS min() trick for viewport-fit math. The '
     'thirty-two-clock layout problem and how it\'s solved without '
     'JavaScript.'),
    ('ch5-mail-uis',
     'Chapter 5 — The Mail app (mailbox + mailroom + relay)',
     'Three UIs: per-account inbox, the relay-inbox triage queue, the '
     'admin mailroom. SMTP server bring-up. Domain-aware delivery via '
     'DynamicMailboxBackend. The mail relay protocol and its token-'
     'gated forward path.'),
    ('ch6-logs-services-security',
     'Chapter 6 — Operational tools (Logs / Services / Security / Sysinfo / Graphs)',
     'Five small apps that share the "view-only operational surface" '
     'pattern. Sysinfo\'s read-only proc parsing. Services and the '
     'systemctl bridge. Security\'s audit-table model. Graphs as '
     'time-series renderer for sensor and reading data.'),
    ('ch7-codex-ui',
     'Chapter 7 — Codex itself, from the user side',
     'The /codex/ UI: manual list, volume binding, section navigation, '
     'PDF download. The reading view\'s left-rail typography. The '
     'sidenote anchor convention. Hot-rebuild on section save.'),
    ('ch8-extension-points',
     'Chapter 8 — Extension points: dashboard cards, context '
     'processors, template tags',
     'How to add a new dashboard card without forking dashboard/views. '
     'How to write a context processor that shows on every page. How '
     'to register a new template tag library. The convention that '
     'extension points are documented before they are used.'),
]


VOL2_BODIES = {
    'ch2-terminal': """The terminal app is one of the few places in Velour where there is no escape from JavaScript. The browser-side `xterm.js` widget is the only mature in-page terminal renderer; the server-side bridge needs to be a long-lived WebSocket because pseudo-terminals are byte streams not request/response pairs. This chapter walks the full shape — two ASGI consumers, the WebSocket frame format, the PTY orchestration, the security boundary.

## The two consumers

There are two distinct WebSocket endpoints, each with its own `AsyncJsonWebsocketConsumer` subclass:

**`ShellConsumer`** opens a local PTY (`pty.openpty()`), forks a child process running the operator's login shell, and bridges the master fd to the WebSocket in both directions. Every keystroke from the browser writes to the master fd; every byte the shell produces gets framed as a JSON `{"k":"out","b":"..."}` message and sent to the browser. Window resize events become `TIOCSWINSZ` ioctls on the master fd so vim and tmux render at the right size.

**`SshConsumer`** opens an asyncssh connection to a registered remote host, requests a pseudo-terminal on the far side, and bridges the asyncssh channel's read/write streams to the WebSocket the same way. The host is identified by slug; the slug → connection details mapping lives in the `hosts` app. Auth is via an SSH key the velour user owns.

Both consumers share the framing protocol and the resize handling. They differ only in how they get the byte stream they bridge.

## The frame format

WebSocket frames are JSON objects with a one-letter `k` (kind) field and kind-specific payload:

```jsonc
{"k": "in",  "b": "ls\\n"}              // browser → server, keystrokes
{"k": "out", "b": "file1\\nfile2\\n"}    // server → browser, output
{"k": "rsz", "rows": 24, "cols": 80}    // browser → server, resize
{"k": "exit", "code": 0}                // server → browser, child exited
```

The `b` payloads are raw byte sequences carried as UTF-8 — including ANSI escape sequences for colour, cursor motion, line clears. `xterm.js` interprets them on the browser side. Velour's bridge does no interpretation: bytes in, bytes out.

The choice to wrap in JSON rather than send raw binary is operational: every frame is human-readable in browser dev-tools, which makes terminal-bug triage tractable.

## The PTY lifecycle

When the WebSocket opens, the consumer calls `pty.openpty()` to allocate a master/slave pair, then `os.fork()`. The child closes the master fd, makes the slave its controlling terminal (`os.setsid()` + `TIOCSCTTY`), redirects fds 0/1/2 to the slave, and `execvp`'s into the operator's shell. The parent (the consumer) keeps the master fd, registers it with the asyncio loop for read events, and starts pumping.

When the child exits, the master fd reads zero bytes; the consumer sends a final `{"k":"exit","code":N}` and closes the WebSocket. When the WebSocket closes (browser tab closed, network blip), the consumer SIGHUPs the child process group so dangling shells don't accumulate.

## Security

Both consumers are gated by `@login_required` at the URL level — anonymous browsers cannot establish either WebSocket. The shell consumer additionally requires the operator's Django user to be in the `terminal_shell` group (configurable; the seed grants it to superusers only). The SSH consumer requires the target host to be in the operator's allowlist, which is per-user and managed in the `hosts` app's admin.

There is no shell escape protection beyond Django's auth: an authorized operator gets the same access they would get if they SSH'd to the box directly. The threat model is "an operator who would otherwise have shell access wants browser access too", not "an untrusted user wants to break out of a sandbox". Sandboxing inside a PTY is a hard problem and Velour does not attempt it.

## Channels routing

The two consumers are wired into the project's ASGI router (`velour/asgi.py`):

```python
from channels.routing import URLRouter
from channels.auth import AuthMiddlewareStack

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(URLRouter([
        path("ws/terminal/shell/",  ShellConsumer.as_asgi()),
        path("ws/terminal/ssh/<slug:host>/", SshConsumer.as_asgi()),
    ])),
})
```

`AuthMiddlewareStack` populates `self.scope['user']` so `@login_required` semantics work the way HTTP views expect.

## What follows

Chapter 3 covers the static-asset pipeline that ships `xterm.js` to the browser. Chapter 4 covers the chronos topbar that renders above the terminal pane. Chapter 8 covers the extension pattern for adding new WebSocket consumers — the terminal app's pattern is the template the rest of the codebase follows when something genuinely needs a long-lived connection.""",

    'ch8-extension-points': """Velour grows mostly by addition rather than modification. New apps slot into `INSTALLED_APPS`. New dashboard cards append to `CARDS`. New context processors register in `TEMPLATES['OPTIONS']`. New template tag libraries land under `<app>/templatetags/`. None of these require touching the core. This chapter is the reference for the four most-used extension points: dashboard cards, context processors, template tag libraries, and management commands.

## Adding a dashboard card

`dashboard/cards.py` carries a single list:

```python
CARDS = [
    Card('Web Terminal',  'terminal:home',     icon='terminal'),
    Card('App Factory',   'app_factory:home',  icon='factory'),
    # ...
]
```

A new card is one new line. Convention:

- The label is title-case, two words max.
- The URL is a named route from the new app's `urls.py`.
- The icon is one of the keys in `static/dashboard/icons.svg` (a hand-drawn SVG sprite). New icons get added to that sprite via Inkscape; the PR adds both the icon and the card in one commit.
- The card position in the list IS the grid position. Re-ordering the list re-orders the dashboard. The convention is to group related concerns.
- Cards SHOULD have a corresponding top-menu link in `templates/_topmenu.html` so the feature is discoverable from anywhere, not only from the dashboard. The convention is enforced by a quick test in `dashboard/tests.py` that diffs the two lists.

## Adding a context processor

A context processor is a function that runs on every request and adds keys to the template context. The chronos topbar lives this way (Vol 3 Ch 1 — the `_world_clocks_for(now)` per-minute cache pattern is the reference).

To add one:

1. Write the function in `<app>/context_processors.py`. It takes `request`, returns a dict.
2. Add it to `TEMPLATES['OPTIONS']['context_processors']` in `velour/settings.py`.
3. The keys you return become available in every template via `{{ your_key }}`.

The convention is that context processors must be **fast** (cached, ideally; per-minute is cheap, per-second is acceptable, per-request is suspect) and **defensive** (a context processor that raises kills every page render). Wrap your work in try/except and return `{}` on error.

## Adding a template tag library

Template tags live in `<app>/templatetags/<app>_tags.py`. The Django convention; nothing custom. Use them for rendering helpers that wouldn't fit cleanly as a context processor or a filter.

```python
# chronos/templatetags/chronos_tags.py
from django import template
register = template.Library()

@register.simple_tag
def world_chip(timezone_str):
    \"\"\"Render one world-time chip from a tz string.\"\"\"
    from chronos.world_clocks import format_chip
    return format_chip(timezone_str)
```

In a template:

```django
{% load chronos_tags %}
<span class="chip">{% world_chip "Europe/Amsterdam" %}</span>
```

The convention: each app owns one tag library, named `<app>_tags.py`. Cross-app tags are an anti-pattern; if a tag is useful across apps, the function lives in a shared utility module and each app's tag library re-exports it.

## Adding a management command

Drop a file at `<app>/management/commands/<command_name>.py` with a `Command(BaseCommand)` subclass. Django auto-discovers it; `python manage.py <command_name>` runs it.

Velour conventions for management commands:

- Idempotent by default. Running twice should produce the same end state. Seed commands especially must be idempotent — they're re-run every deploy.
- One-line `help`. The string Django prints in `manage.py --help` is the only documentation many operators read.
- Use `self.stdout.write(self.style.SUCCESS(...))` for important state changes; raw `self.stdout.write` for diagnostic noise. Operators piping output to log files appreciate the distinction.
- Long-running commands should accept `--dry-run` and print what they *would* do without doing it.

## Adding to identity_cron

Velour has exactly one crontab entry: `* * * * * .../manage.py identity_cron`. The dispatcher inside `identity/cron.py` decides what to run. To add a new periodic job:

1. Define a function in `identity/cron.py` that does the work and returns a one-line summary string.
2. Add it to the `pipelines` list near the bottom of `dispatch()`.
3. Add an interval to `DEFAULT_INTERVALS` (seconds).
4. Add the kind to the `'all'` set so `--force=all` includes it.

The dispatcher writes a `CronRun` row for every fire — success or error — so the audit trail is automatic.

## What you cannot extend without modifying core

A short list of things that genuinely require touching files in `velour/`:

- Adding a new top-level URL pattern (you edit `velour/urls.py`).
- Adding a new app to `INSTALLED_APPS` (you edit `velour/settings.py`).
- Adding a new middleware (you edit `velour/settings.py`).

The convention is to keep these edits small and trivially reviewable: one-line additions in alphabetical order. Any change that requires more than a one-line edit to a file under `velour/` is a sign the extension point is missing and should be designed before the feature ships."""
}


def seed_volume_2():
    m = upsert_manual(
        'velour-developer-guide-vol-2',
        title='Velour Developer Guide, Volume 2',
        subtitle='The Web Layer',
        format='complete',
        author='Velour',
        version='0.1 (work in progress)',
        abstract=(
            'Volume 2 of the five-volume Velour Developer Guide. '
            'Covers the user-facing Web layer in depth: the '
            'dashboard, the Web Terminal, the chronos topbar, '
            'the mail UIs, the operational view-only apps, and '
            'the extension points the rest of the codebase '
            'reuses. The companion volumes are Vol 1 (Foundations '
            'and Philosophy), Vol 3 (Time and Data), Vol 4 (Codex '
            'and Documentation), Vol 5 (Operations and Extension).'
            '\n\n'
            'Status: outline + first chapter substantive; remaining '
            'chapters are stubs awaiting expansion. The chapter '
            'structure is stable.'
        ),
    )

    upsert_section(m, 'foreword', 10, 'Foreword',
        """Volume 2 walks the parts of Velour an operator actually clicks on.

Volume 1 explained the meta-app idea — the Django project that contains apps that generate Django projects. This volume zooms in on what a logged-in operator sees at `/`. Most of Velour's surface is plain server-rendered HTML, no SPA, no client-side routing, no compile step. The unusual choices are in the topbar (a context processor that renders thirty-two world clocks on every page without JavaScript) and the terminal app (Channels + ASGI for two distinct WebSocket transports), and these are covered in their own chapters.

Read Volume 1 first. Volume 2 assumes the meta-app idiom and the secret-file protocol.

## How to read this volume

Each chapter is one app or one cross-cutting concern. The chapter on the dashboard is also the chapter that establishes the look-and-feel rules every other UI follows. Read it first.

The chapters on small operational apps (Logs / Services / Security / Sysinfo / Graphs) are bundled into one chapter — they share a pattern (view-only, no writes from the UI) and the differences between them are smaller than the similarities.

The extension-points chapter at the end is the one to consult when adding a new card or a new context processor. It documents the conventions the rest of Velour follows so a new addition fits cleanly.

## Status

This volume currently contains:

- A complete first chapter (the dashboard).
- Outlined stubs for chapters 2 through 8.

The chapter list is stable. Stubs include enough description to know what each chapter will cover when written.""",
        sidenotes='Volume 2 was scoped at ~400pp in the original 5-volume plan.')

    upsert_section(m, 'ch1-dashboard', 110,
        'Chapter 1 — The dashboard and base.html',
        """The dashboard at `/dashboard/` is the entry point most operators see first. It is a 4×4 grid of cards on a desktop browser, collapsing to single-column horizontal strips on a phone. Each card is a feature area; click any card to open it.

This chapter explains how the grid is constructed, what the cards are, where the chronos topbar comes from, why there is no JavaScript on the page, and the conventions that follow from these choices.

## The grid

The grid is plain CSS:

```css
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.6rem;
  max-width: 1100px;
  margin: 1rem auto;
}
@media (max-width: 700px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
```

No grid library. No layout JavaScript. The breakpoint at 700px is the only adaptation.

The grid order matters. Cards that group conceptually live next to each other:

| Row | Cards |
|---:|---|
| 1 | Web Terminal · App Factory · System Info · Security |
| 2 | Logs · Services · Databases · Graphs |
| 3 | Identity · Maintenance · Windows · Agricola |
| 4 | Codex · — · — · — |

Three cells in row 4 are reserved for whatever comes next. Velour grows by occupying one of those cells; when all sixteen are full, the next addition either replaces one (rare) or moves the grid to a 5×4 (also rare).

## Cards as data

The cards are not HTML. They are a Python list in `dashboard/cards.py`:

```python
CARDS = [
    Card('Web Terminal',  'terminal:home',   icon='terminal'),
    Card('App Factory',   'app_factory:home', icon='factory'),
    Card('System Info',   'sysinfo:home',    icon='cpu'),
    # ...
]
```

Adding a card is editing the list. Removing a card is deleting from the list. Reordering is moving items. The template renders the grid by walking `CARDS` and emitting one `<a class="dashboard-card">` per item.

The data-not-template approach has two payoffs: tests can assert the card list shape directly, and the same list is reused by the top menu without duplicating markup.

## The base template

Every page in Velour extends `base.html`. The base contains:

- the `<head>` block (title, the static-CSS link, the static_v cache-busting suffix);
- the topbar (the chronos context processor renders here — Chapter 4);
- the body-class plug (each page sets `body_class` so per-page CSS can target);
- a `{% block content %}` for the page body;
- a footer with the build-time hash and a link to the Codex Quickstart.

There is no JavaScript in `base.html` except a five-line dropdown polyfill loaded inline. The base is small enough to read in one screen.

## The no-JavaScript-first principle

Velour pages use plain HTML forms and full-page submits unless an interaction *requires* client-side behaviour. The exceptions, in order of how reluctantly they were introduced:

1. The Web Terminal (xterm.js + Channels — no other path works).
2. The Codex live-rebuild on section save (a 50-line fetch).
3. The Identity ticking-mood pulse in the topbar (a 12-line setInterval).
4. The dropdown polyfill in `base.html` (five lines, vanilla, inline).

Everything else is server-rendered HTML. This is the rule Volume 2 enforces and the rest of this volume documents.

## What follows

Chapters 2 through 7 cover specific Web-layer apps. Chapter 8 documents the extension points: how to add a new dashboard card, a new context processor, a new template tag library — each in roughly the form a real PR would take.""",
        sidenotes='The dashboard once had thirteen cards; the original plan was twenty. The smaller number turned out to be a feature.')

    upsert_section(m, 'part-2', 200, 'Part II — App-by-app',
        """Six chapters covering the specific Web-layer apps: Web Terminal, template conventions, the chronos topbar, the Mail family, the operational tools cluster, and the user-side of Codex.""")

    sort = 210
    for slug, title, summary in VOL2_CHAPTERS[1:7]:
        body = VOL2_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

When written, this chapter will follow the format established in Chapter 1: a one-paragraph framing, then the architectural choices spelled out as numbered observations, then the code patterns, then the cross-references to the other apps that depend on or extend this one. Approx. 25–40 pages.""")
        sn = '' if slug in VOL2_BODIES else 'Stub. To be expanded in a subsequent revision.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-3', 800, 'Part III — Extension',
        """One chapter — Chapter 8 — documenting the extension points the rest of the codebase reuses.""")

    slug, title, summary = VOL2_CHAPTERS[7]
    body = VOL2_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

When written, this chapter will document each extension point with: a code example showing the minimal addition, the convention any addition must follow, a list of existing extensions in the codebase that follow the convention, and a regression risk for each. Approx. 30–40 pages.""")
    sn = '' if slug in VOL2_BODIES else 'Stub. To be expanded in a subsequent revision.'
    upsert_section(m, slug, 810, title, body, sidenotes=sn)

    upsert_section(m, 'where-this-volume-sits', 950,
        'Where this volume sits in the set',
        """Volume 1 explained *what* Velour is. Volume 2 explains *what an operator sees*. Volume 3 covers the time-and-data subsystems that fill many of these views with content. Volume 4 covers Codex itself in depth. Volume 5 covers operations.

A reader interested in extending Velour should read Volume 1 cover-to-cover, then read Chapters 1 and 8 of Volume 2 (the dashboard and the extension points), then dive into the volume covering the area they want to extend.""")


# =====================================================================
# Volume 3 — Time and Data
# =====================================================================

VOL3_CHAPTERS = [
    ('ch1-chronos-deep',
     'Chapter 1 — Chronos in depth',
     'Everything in Volume 1\'s chronos chapter, expanded. The hour/'
     'minute/second model. The 32 world-time chips. The deep-time '
     'browse modes (day → month → year → century → millennium → '
     '100Ky). The CSS min() trick for variable-precision intervals. '
     'The chronos "tasks" model and the morning briefing.'),
    ('ch2-holiday-traditions',
     'Chapter 2 — Eleven holiday traditions',
     'The eleven calendar systems chronos pulls holidays from: '
     'Gregorian civic, Christian liturgical, Jewish, Islamic, Hindu, '
     'Buddhist, Bahá\'í, Sikh, Zoroastrian, secular UN observances, '
     'and the lab-personal calendar. Each is one calendar adapter '
     'with documented ranges and edge cases.'),
    ('ch3-astronomy',
     'Chapter 3 — Skyfield, Meeus, and the JPL ephemeris',
     'How chronos computes solstices, equinoxes, eclipses, and '
     'planetary conjunctions via the skyfield library and the '
     'JPL DE421 ephemeris file. The Meeus formulas in fallback '
     'positions. Aspect detection thresholds. Multi-decade '
     'precomputed ranges for performance.'),
    ('ch4-deep-time',
     'Chapter 4 — Deep-time UI design',
     'The day/month/year/decade/century/millennium/100Ky '
     'browsing chain. The shared CSS variable for time-step '
     'precision. The visual bridge between scales. How holidays '
     'and astronomical events render at each scale without '
     'visual collapse.'),
    ('ch5-databases',
     'Chapter 5 — The Databases app',
     'Phase 1 (the registry of known databases), Phase 2 (the '
     'table browser with column types and row counts), Phase 3 '
     '(the SQL shell with role gating). The connection-cache '
     'discipline. Per-database read-only roles for safety.'),
    ('ch6-graphs',
     'Chapter 6 — Graphs and time-series',
     'How the graphs app renders SensorReading and any other '
     'time-keyed model into the same chart family Codex uses. '
     'Backed by the same matplotlib-free chart code so PDFs '
     'and live pages share visual conventions.'),
    ('ch7-nodes',
     'Chapter 7 — Nodes (the ESP fleet)',
     'The Node and HardwareProfile models. The OTA firmware-'
     'check protocol. The auto-discovery handshake. The '
     'fleet status page. The carrying-case planner. '
     'Cross-references to bodymap_firmware and bodymap_hud.'),
    ('ch8-experiments',
     'Chapter 8 — Experiments and SensorReading',
     'How a long-running experiment is modelled as one '
     'Experiment + many Node + many SensorReading rows. The '
     'data-model trade-offs (tall table vs wide). The Phase 2 '
     'expansion plan: experiment graphs, comparative dashboards, '
     'cross-experiment statistics.'),
    ('ch9-extension-time',
     'Chapter 9 — Extension points: holidays, astro events, '
     'data models',
     'How to add a new holiday source. How to add a new '
     'astronomical computation. How to add a new sensor '
     'channel. The conventions that keep new additions from '
     'breaking the morning briefing.'),
]


VOL3_BODIES = {
    'ch2-holiday-traditions': """Chronos pulls holidays from eleven calendar systems. Each system is a thin adapter: a function that, given a date range, returns a list of `CalendarEvent` rows tagged with the tradition slug. The eleven adapters live in `chronos/holidays/<tradition>.py` and share a common interface but no common code — each calendar system has its own conventions, edge cases, and historical drift.

This chapter walks the eleven adapters in turn. The order is alphabetical except for Civic, which leads because it's the only one that's universal.

## The adapter contract

Every adapter exports one function:

```python
def events_in_range(start_utc, end_utc) -> list[CalendarEvent]:
    \"\"\"Return one CalendarEvent per holiday or observance whose
    when_utc falls within [start_utc, end_utc). The CalendarEvent
    objects are NOT saved here — the caller saves them in a
    transaction so partial-failure leaves no half-imported state.\"\"\"
```

Adapters are pure: no DB writes, no network calls. They derive holiday dates from a local table of rules, the JPL ephemeris (for tropical-year-anchored events), and the calendar's own conversion functions (Hebrew, Hijri, Bikram Sambat, etc.).

The chronos `seed_holidays` management command runs all eleven adapters over the next 25 years and bulk-inserts the results. Re-running is idempotent — `update_or_create` keyed on `(tradition, label, when_utc)` ensures no duplicates.

## Civic

The civic calendar is operator-configured: the operator picks a country (or a list of countries) and the adapter loads the matching list from the Python `holidays` package. Default is the operator's country code from chronos settings. New Year's Day, country-specific national days, MLK Day in the US, Koningsdag in the Netherlands, etc.

This is the only adapter that depends on a third-party package. The dependency is intentional — `holidays` is well-maintained and covers 50+ countries with edge cases for moveable feasts and substitution rules. Re-implementing would be a small library-of-libraries.

## Christianity

The Christian liturgical calendar is the largest single adapter. It computes Easter via the Anonymous Gregorian algorithm, then derives Lent, Holy Week, Pentecost, and Trinity Sunday by offset. Fixed feasts (Christmas, Epiphany, All Saints) come from a hardcoded table. Western and Eastern Easter are both computed; the operator picks which to render via a chronos setting.

The adapter is the largest because the calendar carries the most distinctions: liturgical colours, vigil-vs-day, fast-vs-feast, ferial-vs-festal. Each event's `metadata` dict carries those fields so the calendar UI can render them differently.

## Judaism

Hebrew calendar dates come from the `pyluach` package. The adapter walks each Hebrew year overlapping the requested range, emits the major moadim (Rosh Hashanah, Yom Kippur, Sukkot, Hanukkah, Tu B'Shvat, Purim, Pesach, Lag B'Omer, Shavuot, Tisha B'Av), and tags each event with its Hebrew date in the metadata. The adapter handles both the Diaspora two-day yom-tov pattern and the Israel single-day pattern via a chronos setting.

## Islam

The Hijri calendar is lunar; Hijri dates drift through the Gregorian year by ~11 days each year. The adapter uses `hijri_converter` to map Hijri month-1-day-1 (Ras as-Sanah), Mawlid an-Nabi, Ramadan, Eid al-Fitr, Eid al-Adha, and the Hajj. Because the start of Ramadan and Eid depends on lunar observation in some traditions, the adapter emits both the calculated date and a ±1 day metadata range; the calendar UI shows the calculated date with a note that the actual observance may shift by a day.

## Hinduism

The Hindu adapter is the most opinionated. It uses a fixed list of major pan-Indian festivals (Diwali, Holi, Janmashtami, Navaratri, Ganesh Chaturthi, Raksha Bandhan, Makar Sankranti, Maha Shivaratri) computed via the `drik-panchanga` Python port for the operator's chosen city (default: New Delhi). Regional festivals (Pongal, Onam, Bihu, Durga Puja) are not included by default; the operator enables them per region.

## Buddhism

Vesak (the Buddha's birthday/enlightenment/death) is the major event in most Theravada traditions; it falls on the full moon of the Vaisakha month. The adapter computes it via the lunar ephemeris. Bodhi Day (Mahayana, December 8) and Ulambana (Mahayana ghost festival, around mid-July full moon) are also emitted. Theravada vs Mahayana is a chronos setting.

## Bahá'í

The Bahá'í calendar has 19 months of 19 days plus 4-5 intercalary days. Naw-Ruz (March 21), the nine Holy Days, and Ayyam-i-Há come from a fixed-date table; the adapter just emits them with the right Gregorian year.

## Sikh

Gurpurab anniversaries (Guru Nanak's birth, Guru Gobind Singh's birth, the martyrdom of Guru Arjan, Vaisakhi) are computed from the Nanakshahi calendar via a small lookup table. Vaisakhi (April 13/14) is the major shared holiday with Hindu Punjab — it carries metadata tagging it as observed in both traditions so the calendar UI can avoid duplicate rendering.

## Zoroastrian

Nowruz (March 21), Mehregan (October 2), and Sadeh (January 30) are emitted from a fixed-date table. The Zoroastrian calendar has multiple variants (Fasli, Shahanshahi, Kadmi); chronos uses Fasli by default to align with the Iranian civil calendar's Nowruz.

## Secular UN observances

International Women's Day, Earth Day, World Refugee Day, etc. — all from a fixed table. The metadata distinguishes UN-declared observances from informal ones (Pi Day) and from country-specific commemorations that nevertheless have international visibility (Bastille Day).

## Lab-personal

The eleventh "tradition" is the operator's own calendar: birthdays, anniversaries, lab-relevant dates (the day Gary was provisioned, the day the LoRa stack came up). These are not derived; they are entered through the chronos UI and stored as `CalendarEvent` rows with `tradition='personal'`.

The personal-tradition is intentionally last in the list because it's the only one that the operator edits live; the other ten are seeded once and refreshed only when chronos itself is upgraded.

## What follows

Chapter 3 covers the astronomical layer (skyfield, Meeus, the JPL ephemeris). Many holidays (Easter, Vesak, Ramadan) reference astronomical events; the chronos architecture computes the astro events first and the holiday adapters consume them. Chapter 4 covers the deep-time UI design that makes 25 years of these events browsable on a single screen.""",

    'ch5-databases': """The databases app is Velour's window into "things that are SQL but aren't Velour's own SQLite." Most lab control panels accumulate side databases over time — an old MySQL the previous person left running, a Postgres the latest experiment writes to, a sqlite file someone else's tool produced. The databases app is a registry of those, plus a read-only browser, plus an opt-in SQL shell.

It is deliberately not a database management tool. Schema migrations, backups, and write paths are out of scope. The app exists to let an operator answer "what is this database, what's in it, and what does the third row look like?" without leaving the dashboard.

## The model

```python
class Database(models.Model):
    slug      = models.SlugField(unique=True)
    name      = models.CharField(max_length=120)
    backend   = models.CharField(max_length=16,
        choices=[('mysql','MySQL'),('postgres','PostgreSQL'),
                 ('sqlite','SQLite'),('oracle','Oracle')])
    host      = models.CharField(max_length=200, blank=True)
    port      = models.PositiveIntegerField(null=True, blank=True)
    db_name   = models.CharField(max_length=120)
    user      = models.CharField(max_length=120, blank=True)
    password_file = models.CharField(max_length=200, blank=True,
        help_text='chmod 600 file under BASE_DIR; secret-file '
                  'protocol applies (Vol 1 Ch 3)')
    notes     = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

The password lives in a file, never in the row. This is the secret-file protocol enforced from the beginning — the model literally has nowhere to put a password value.

## Phase 1 — registry

Phase 1 is the model + an admin form + a list view at `/databases/`. The list shows backend, host, name, last-tested timestamp, and a small status pill. The status comes from a per-row "test connection" button that opens a connection (with a 5-second timeout), runs `SELECT 1`, and updates a `last_tested_at` field on the row. No introspection beyond connection-works-or-not.

Phase 1 is what most operators use most of the time: "do I have credentials for the legacy MySQL?" — yes/no, here's the host, here's the password file, go SSH if you want to do anything.

## Phase 2 — table browser

Phase 2 adds `/databases/<slug>/` showing a list of tables (schema introspection via `SHOW TABLES` / `pg_class` / `sqlite_master` / `ALL_TABLES`). Click a table → `/databases/<slug>/<table>/` showing column names, types, primary key, foreign keys, row count, and the first 50 rows. All read-only. All cached per-table for 30 seconds because schema introspection on a large database can be expensive.

The connection-cache discipline is important. Phase 2 opens one connection per (database, request) and reuses it across all queries the request issues. It does NOT pool connections across requests because most legacy databases have small `max_connections` and a connection leak in Velour shouldn't compete with the legacy app's own pool.

## Phase 3 — SQL shell

Phase 3 is the opt-in `/databases/<slug>/sql/` SQL shell. Operator types a query, hits run, sees the result rendered as a table. Two safety gates:

1. **Read-only role enforcement.** The connection is opened with a `read_only` user (a separate row on `Database` carrying a different `password_file`). The application makes no attempt to parse the query; it relies on the database's own role permissions to refuse `INSERT`/`UPDATE`/`DELETE`/`DROP`. Every database backend Velour supports has read-only roles; the SQL shell is unavailable on databases where the operator hasn't configured one.

2. **Query timeout.** Every query runs with a hardcoded 30-second statement timeout (set via `SET STATEMENT_TIMEOUT`, `SET LOCAL statement_timeout`, etc — backend-specific). A query that would lock the legacy app's tables for an hour gets killed at 30 seconds.

The shell is gated behind a per-database "SQL shell enabled" flag that defaults to off. Turning it on requires the operator to acknowledge the read-only-role-must-exist convention.

## What the app does NOT do

- Migrations. Use the legacy app's own migration tool.
- Schema design. Use a real schema design tool (DBeaver, etc).
- Backups. Use the database's own dump tool — `mysqldump`, `pg_dump`, etc — driven from a cron job (Vol 5 Ch 6).
- Write queries. Even a "harmless" write query gets refused by the read-only role.
- Connection pooling. One connection per request. Operators who need pooled access write a different tool.

## Cross-references

- Vol 1 Ch 3 — the secret-file protocol, which `password_file` follows.
- Vol 5 Ch 6 — how backup tooling reads `Database` rows to know what to dump.
- The Datalift app (separate from databases) is the *write* path: it ingests a `mysqldump` into Django models. See the Datalift Manual volume in the Codex library.

## What follows

Chapter 6 covers the graphs app, which renders time-series data from any of the registered databases (Phase 4 — not yet shipped). Chapter 7 covers nodes and the SensorReading time-series the graphs draw. Chapter 8 covers experiments, which group readings across nodes."""
}


def seed_volume_3():
    m = upsert_manual(
        'velour-developer-guide-vol-3',
        title='Velour Developer Guide, Volume 3',
        subtitle='Time and Data',
        format='complete',
        author='Velour',
        version='0.1 (work in progress)',
        abstract=(
            'Volume 3 of the five-volume Velour Developer Guide. '
            'Covers chronos in depth (the eleven holiday '
            'traditions, the JPL ephemeris, the deep-time '
            'browsing chain), the databases app, the graphs '
            'app, and the data side of nodes + experiments + '
            'sensor readings. The companion volumes are Vol 1 '
            '(Foundations), Vol 2 (Web Layer), Vol 4 (Codex), '
            'Vol 5 (Operations).'
            '\n\n'
            'Status: outline + first chapter substantive; '
            'remaining chapters are stubs awaiting expansion.'
        ),
    )

    upsert_section(m, 'foreword', 10, 'Foreword',
        """Volume 3 covers the parts of Velour that know about *when* and *what*. The chronos app handles when — wall time, calendar time, deep time, the eleven traditions of holidays the lab marks, and the JPL ephemeris of solar-system motion. The databases / graphs / nodes / experiments family handles what — registries, tables, time-series, sensor readings, and the long-running experimental contexts that connect them.

These are small apps individually. Together they make Velour a system that knows the date in eight cultural calendars, the next planetary conjunction, the live load on the workstation, and the temperature in the aquarium.

Read Volumes 1 and 2 first. Volume 3 assumes the meta-app idiom and the dashboard layout. Chapter 1 (chronos in depth) is the prerequisite for the rest of the volume.""",
        sidenotes='Volume 3 was scoped at ~400pp in the original 5-volume plan.')

    upsert_section(m, 'ch1-chronos-deep', 110,
        'Chapter 1 — Chronos in depth',
        """The chronos app is the largest single subsystem in Velour. It handles every time-related concern: wall clocks, world time chips for thirty-two cities, calendar grids for eleven cultural traditions, astronomical events from the JPL ephemeris, deep-time browsing from one day all the way out to one hundred thousand years, the morning briefing, the task-and-event model, and the topbar context processor every other page consumes.

Volume 1 introduced chronos at the level of "there is a clock in the topbar." This chapter explains how the clock is computed, why it never spins the laptop fan, how the world chips arrange themselves without JavaScript, how the holiday traditions are layered without colliding, and how the deep-time browse modes share a single coordinate system from minutes to millennia.

## The model

The chronos data model is intentionally small. Three tables carry most of the weight:

```python
class CalendarEvent(models.Model):
    when_utc   = models.DateTimeField(db_index=True)
    label      = models.CharField(max_length=200)
    tradition  = models.CharField(max_length=32)
    kind       = models.CharField(max_length=32)
    metadata   = models.JSONField(default=dict)

class WorldClock(models.Model):
    city       = models.CharField(max_length=80)
    timezone   = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField()
    visible    = models.BooleanField(default=True)

class Task(models.Model):
    title      = models.CharField(max_length=200)
    notes      = models.TextField(blank=True)
    source_app = models.CharField(max_length=64)
    source_url = models.CharField(max_length=400)
    due_at     = models.DateTimeField(null=True, blank=True)
    priority   = models.CharField(max_length=8)
    status     = models.CharField(max_length=16)
```

Holidays, eclipses, conjunctions, equinoxes, and lab-personal events all share the `CalendarEvent` shape. The `tradition` field discriminates them at query time. This denormalization is intentional — it lets the calendar grid render every kind of event with one query.

## The 100Ky chain

The deep-time browse modes form a chain: day → week → month → year → decade → century → millennium → 10Ky → 100Ky. Each mode is a single Django view that accepts a centre date and a span. The same `CalendarEvent` query returns events within the span, with the renderer choosing how to display them based on density.

At 100Ky scale, the calendar shows the last interglacial, the Holocene, the predicted next glacial cycle, and the major asteroid impact dates as far back as Chicxulub. The same CalendarEvent rows that store next Tuesday's lab meeting also store the K-Pg boundary. The kind field distinguishes them.

## The topbar context processor

The chronos topbar lives in `chronos/context_processors.py`:

```python
def chronos_topbar(request):
    \"\"\"Inject clock + world-chips + next-event into every page.\"\"\"
    now = timezone.now()
    return {
        'chronos_now':        now,
        'chronos_chips':      _world_clocks_for(now),
        'chronos_next_event': _next_calendar_event(now),
    }
```

`_world_clocks_for(now)` is cached per-minute (per-second would be cheap but unnecessary; the chips show HH:MM not HH:MM:SS). `_next_calendar_event(now)` is cached per-five-minutes — the cache invalidates when CalendarEvent is saved.

## What follows

Chapter 2 covers each of the eleven holiday traditions in turn. Chapter 3 is the astronomical layer (skyfield + JPL ephemeris). Chapter 4 covers the deep-time UI in design detail. Chapters 5–8 are the data-side apps. Chapter 9 documents the extension points.""",
        sidenotes='The "chronos doesn\'t spin the fan" claim is load-bearing: the topbar fires on every page render, so any per-second computation would be visible in `top` immediately.')

    upsert_section(m, 'part-2', 200, 'Part II — Time',
        """Three chapters fleshing out chronos: the eleven holiday traditions, the astronomical layer, and the deep-time UI.""")

    sort = 210
    for slug, title, summary in VOL3_CHAPTERS[1:4]:
        body = VOL3_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

When written, this chapter will follow the format established in Chapter 1: framing, architectural choices, code patterns, cross-references. Approx. 30–50 pages.""")
        sn = '' if slug in VOL3_BODIES else 'Stub. To be expanded in a subsequent revision.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-3', 500, 'Part III — Data',
        """Four chapters covering the data-side apps: databases, graphs, nodes, and experiments.""")

    sort = 510
    for slug, title, summary in VOL3_CHAPTERS[4:8]:
        body = VOL3_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

When written, approx. 25–40 pages.""")
        sn = '' if slug in VOL3_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-4', 900, 'Part IV — Extension',
        """One chapter documenting how to add new holiday sources, astronomical computations, and data models.""")

    slug, title, summary = VOL3_CHAPTERS[8]
    upsert_section(m, slug, 910, title,
        f"""*This chapter is a stub. Outline:*

{summary}

Approx. 25 pages.""",
        sidenotes='Stub.')


# =====================================================================
# Volume 4 — Codex and Documentation
# =====================================================================

VOL4_CHAPTERS = [
    ('ch1-philosophy',
     'Chapter 1 — Codex philosophy and the Tufte influence',
     'Why Velour ships its own documentation system instead of '
     'reusing Sphinx or MkDocs. The Tufte design principles applied '
     '(high data-ink ratio, minimal chrome, sidenotes over footnotes, '
     'small multiples). The decision to render PDFs from markdown '
     'rather than HTML to PDF.'),
    ('ch2-markdown-subset',
     'Chapter 2 — The Codex markdown subset',
     'Reference for every block type Codex understands. Headings, '
     'paragraphs, lists, code blocks, tables (Tufte minimal-rule and '
     'bordered), definition lists, callouts, slope graphs, small '
     'multiples, sparklines, sidenotes, and the :::chart fence.'),
    ('ch3-renderer',
     'Chapter 3 — The renderer (codex/rendering/tufte.py)',
     'A walkthrough of the rendering pipeline: markdown parse, AST '
     'walk, fpdf2 page composition, sidenote anchor placement with '
     'collision avoidance, page-break logic, table layout. Per-block '
     'rendering classes and how to add a new one.'),
    ('ch4-sparklines-charts',
     'Chapter 4 — Sparklines and the chart library',
     'Pure-fpdf2 vector drawing of sparklines (line, area, dot, '
     'winloss). The seven chart kinds (bar, line, bullet, scatter, '
     'histogram, column, sparkstrip). Colour palette discipline '
     '(Dark2, colourblind-safe). The :::chart fence syntax.'),
    ('ch5-diagrams-kroki',
     'Chapter 5 — Diagrams via Kroki',
     'The 21 figure kinds Codex knows about. The Kroki round-trip '
     'and the local cache. Mermaid, PlantUML, Graphviz, BPMN, etc. '
     'How to add a new diagram kind. The fall-back render when '
     'Kroki is unreachable.'),
    ('ch6-introspection',
     'Chapter 6 — codex/introspection.py and per-app reference',
     'How Codex generates reference appendices by walking '
     'django.apps.apps.get_app_configs(). Model field tables, URL '
     'route tables, management command listings, settings entries. '
     'The pattern that lets every app contribute a reference '
     'appendix without duplicating boilerplate.'),
    ('ch7-tutorials',
     'Chapter 7 — Writing tutorials: best practices per block',
     'A style guide. When to use a callout vs a sidenote. When to '
     'use a slope graph vs a line chart. How to structure a chapter '
     'so it survives the introspection pipeline. The "show then '
     'tell" pattern that makes chapters readable in print and '
     'searchable in PDF.'),
    ('ch8-extension-points',
     'Chapter 8 — Extension points: block types, figure kinds, '
     'chart types',
     'How to add a new block type (with a worked example). How to '
     'add a new figure kind. How to add a new chart type with the '
     'same fpdf2 vector pattern as the sparkline family.'),
    ('ch9-future',
     'Chapter 9 — Future: weasyprint, ET Book Italic Display, more',
     'The deferred work: a weasyprint backend for HTML-to-PDF, '
     'the ET Book Italic Display family for callouts, additional '
     'chart libraries, the periodic-report aggregation pattern '
     '(see Vol 1 Ch 14 and the codex_app_reports command), and '
     'the planned editor-side integration.'),
]


VOL4_BODIES = {
    'ch2-markdown-subset': """Codex understands a deliberately small subset of Markdown plus a handful of Velour-specific extensions. The subset is small because every block type the renderer accepts is one more thing the Tufte-style PDF pipeline has to lay out correctly. The extensions are Velour-specific because the things Tufte cared about — sidenotes, sparklines, slope graphs — are not in CommonMark.

This chapter is the reference. Every block type Codex will render appears here with its syntax, its rendered shape, and its constraints.

## Block-level constructs

### Headings

ATX-style only:

```markdown
# Manual title (only one per Section, used as the running header)
## Section title
### Subsection title
```

Codex does NOT render `#### h4` or deeper — the typographic stack tops out at h3. A document needing h4 should be split into two Sections.

### Paragraphs

Plain prose. Wrap at any column; the renderer reflows. Hard line breaks via the two-trailing-spaces convention are recognised but rare — paragraphs are the default block.

### Lists

Both ordered and unordered, single level (no nested lists in the renderer):

```markdown
- a bullet
- another bullet

1. an ordered item
2. another
```

Nested lists render as flat text with prefix indicators; this is intentional. Tufte's books use nested lists almost never. If a structure genuinely needs nesting, use a definition list (below).

### Definition lists

```markdown
Term
:   The definition. Can run multiple lines, indented by four spaces
    to continue.
```

Renders as a hanging indent, term in bold, definition body in body face.

### Code blocks

Fenced only, with optional language:

```markdown
```python
def foo():
    return 42
```
```

Fenced inline `code` works the same way. The renderer applies a monospace face but does NOT syntax-highlight — Tufte's books don't and the colourful syntax-highlighted code blocks Sphinx produces clash with the typographic palette.

### Tables

The pipe-table syntax:

```markdown
| col 1 | col 2 |
|-------|-------|
| a     | b     |
```

Renders in the **Tufte minimal-rule** style by default: a single horizontal rule above the header, one below the header, one at the bottom of the table. No vertical rules, no zebra-striping, no row borders. Right-align by appending `:` to the right side of the separator: `|------:|`.

To opt into a bordered table (rare; reserved for tables where cells are visually heterogeneous), wrap the table in a `:::table-bordered ... :::` fence.

### Block quotes

Standard `>` prefix. Renders as a slight left indent in italic body face. Multi-paragraph blockquotes: prefix every paragraph with `>`, and use `>` on its own line as a separator.

### Callouts

```markdown
:::tip
A short callout. Renders as a sidenote-styled box in the margin.
:::

:::warning
The same shape but a different colour.
:::
```

Three callout types: `tip`, `warning`, `note`. Each renders as a margin sidebar, not as an inline interruption to the main text column.

## Inline constructs

### Emphasis

`*italic*` and `**bold**`. The combination `***both***` renders as bold-italic.

### Links

`[label](url)` for external; `[label](#section-slug)` for in-volume cross-references; `[label](manual:slug#section)` for cross-manual references. The cross-manual form resolves at render time and renders as a styled span with a small arrow superscript indicating the link target.

### Sidenotes

The Velour-specific extension that's the most-used. Two syntaxes:

```markdown
A sentence in body text.[^a brief sidenote]

Same sentence with a numbered sidenote.[^1]

[^1]: The full sidenote text appears here, anywhere in the section.
```

The renderer anchors each sidenote to the line that triggered it, in the right margin, with a small superscript marker. If two sidenotes would collide vertically, the second is bumped down and a connector line is drawn from the marker to the bumped sidenote.

## Velour-specific fences

### Charts

```markdown
:::chart kind=line
title: Test counts per round
x: 1 / 2 / 3 / 4 / 5
y: 22 / 30 / 47 / 51 / 56
:::
```

Seven chart kinds: `bar`, `line`, `bullet`, `scatter`, `histogram`, `column`, `sparkstrip`. The chart library is pure-fpdf2 vector drawing — no matplotlib, no PIL.

### Sparklines

Inline:

```markdown
Test counts: ::sparkline 22,30,47,51,56:: → grew steadily.
```

Four sparkline variants: `sparkline` (line), `sparkarea` (area), `sparkdot` (dot strip), `sparkwl` (win-loss).

### Diagrams

```markdown
:::diagram kind=mermaid
graph LR
    A --> B
    B --> C
:::
```

21 diagram kinds via Kroki: `mermaid`, `plantuml`, `graphviz`, `bpmn`, `c4plantuml`, `excalidraw`, `nomnoml`, `pikchr`, `seqdiag`, `wireviz`, etc. The renderer caches Kroki responses by sha256 of the source so re-renders are cache hits.

### Slope graphs

Two-column comparison:

```markdown
:::slopegraph
title: Round-trip latency improvement
left: before
right: after
- API a    : 230 → 95
- API b    : 410 → 380
- API c    : 95  → 88
:::
```

Renders as Tufte's slope-graph layout: two vertical scales, one line per row connecting the left and right values.

### Small multiples

```markdown
:::multiples cols=4
- Q1 : ::sparkline 1,2,3,4,5::
- Q2 : ::sparkline 5,3,2,4,3::
- Q3 : ::sparkline 2,2,3,3,4::
- Q4 : ::sparkline 4,5,5,5,6::
:::
```

A grid of small inline charts, one per row, intended for at-a-glance comparison.

## What the renderer rejects

- HTML inside Markdown. The renderer does not pass through arbitrary HTML; the typographic pipeline can't lay out unknown markup. If you need HTML, you don't need Codex.
- Images. Diagrams render via Kroki; charts render via the chart library; ad-hoc images are out of scope. Vol 4 Ch 9 covers the planned weasyprint backend that would change this.
- Math. LaTeX equations are out of scope. Math-heavy chapters use plain prose with inline `code` for symbols, or render the equation as a `kroki/typst` diagram.
- Footnotes (the `[^N]` *bottom-of-page* convention). Codex turns those into sidenotes regardless of intent. Bottom-of-page footnotes don't fit the typographic plan.

## What follows

Chapter 3 is the renderer internals — how each of these block types becomes pixels in a PDF. Chapter 4 is the chart library. Chapter 5 is the diagram round-trip. Chapter 7 is the writing style guide that says when to use each block type.""",

    'ch6-introspection': """The introspection layer (`codex/introspection.py`) is the reason every Velour app has a "reference" appendix in this guide without anyone hand-writing those tables. The layer walks Django's own app registry, asks each app what it exports, and emits markdown tables ready for the renderer.

This chapter is the contract: what introspection extracts, how to invoke it from a manual seeder, and how to add a new introspection function for a kind of metadata Velour starts caring about later.

## What it extracts today

Six functions, each returning markdown:

```python
from codex.introspection import (
    models_for_app,        # list every model + its fields
    urls_for_app,          # list every named URL pattern
    commands_for_app,      # list every management command
    settings_for_app,      # list app-specific settings
    signals_for_app,       # list every connected signal handler
    cron_pipelines,        # list identity_cron pipelines + intervals
)
```

Each takes an app label and returns a markdown table:

```python
>>> from codex.introspection import models_for_app
>>> print(models_for_app('chronos'))
| Model | Fields |
|-------|--------|
| `CalendarEvent` | when_utc, label, tradition, kind, metadata |
| `WorldClock`    | city, timezone, sort_order, visible |
| `Task`          | title, notes, source_app, source_url, due_at, priority, status |
```

The output is plain markdown, ready to be the body of a `Section`.

## Calling from a seeder

The convention: every per-app chapter has an introspection-generated reference appendix as its last section. The seeder for that chapter looks like:

```python
def seed_chronos_chapter(m):
    upsert_section(m, 'chronos-narrative', 100,
                   'Chapter 19 — Chronos',
                   _hand_written_chronos_narrative())
    upsert_section(m, 'chronos-models', 110,
                   'Reference: chronos models',
                   models_for_app('chronos'),
                   sidenotes='Auto-generated from django.apps; '
                             're-run seed_devguide to refresh.')
    upsert_section(m, 'chronos-urls', 120,
                   'Reference: chronos URLs',
                   urls_for_app('chronos'))
    upsert_section(m, 'chronos-commands', 130,
                   'Reference: chronos management commands',
                   commands_for_app('chronos'))
```

Every chapter that documents an app follows this pattern. The narrative changes; the appendices auto-update.

## How `models_for_app` works

```python
def models_for_app(app_label: str) -> str:
    cfg = django_apps.get_app_config(app_label)
    rows = []
    for model in cfg.get_models():
        fields = ', '.join(
            f'`{f.name}`' for f in model._meta.fields
            if not f.auto_created
        )
        rows.append(f'| `{model.__name__}` | {fields} |')
    return ('| Model | Fields |\\n|-------|--------|\\n'
            + '\\n'.join(rows))
```

That's it. Twelve lines. The output is markdown the renderer already knows how to lay out.

The same shape — walk Django's introspection API, format as a markdown table — covers all six functions. `urls_for_app` walks `URLResolver.reverse_dict`. `commands_for_app` walks `management.find_commands(app_path)`. `settings_for_app` filters `django.conf.settings.__dict__` for keys that match the app prefix.

## Adding a new introspection function

When Velour starts shipping something new that lives in many apps, the pattern is:

1. Pick what to extract (e.g., "every `codex_report()` hook").
2. Walk the app registry, collecting the metadata.
3. Format as a markdown table.
4. Add a one-paragraph docstring naming where the data comes from.

Example: an introspection function that lists every `codex_report()` hook (the per-app reports from Vol 1's commit `8419a0d`):

```python
def codex_reports_for_apps() -> str:
    rows = []
    for cfg in django_apps.get_app_configs():
        try:
            mod = importlib.import_module(f'{cfg.name}.codex_report')
        except ModuleNotFoundError:
            continue
        if hasattr(mod, 'report'):
            rows.append(f'| `{cfg.label}` | yes |')
    return ('| App | codex_report() |\\n|-----|----------------|\\n'
            + '\\n'.join(rows))
```

The docstring tells the next person what to expect. The output is ready for the renderer.

## What introspection deliberately doesn't do

- It doesn't render docstrings. Sphinx-style autodoc was deliberately not adopted; docstrings tend to be tactical comments aimed at the next maintainer of the function, not coherent documentation aimed at a chapter reader. The introspection layer extracts shape (what fields, what URLs, what commands) and leaves narrative to the hand-written sections.
- It doesn't extract from inside function bodies. No AST walking, no call-graph inference. The complexity isn't worth the brittleness.
- It doesn't generate cross-references. A model field that's a foreign key gets listed by name; the link to the target model is the writer's job.

## Re-running on every deploy

`manage.py seed_devguide` is run on every deploy. The auto-generated appendices refresh; the hand-written narratives are unchanged because their bodies are seeded with the exact same string. This is why chapter slugs and sort orders are stable: the seed is idempotent on the structure, additive on the content.

## What follows

Chapter 7 covers the writing style guide — when to use each block type the markdown subset offers, when to use a slope graph vs a line chart, how to structure a chapter so it reads well in print and searches well in PDF. Chapter 8 covers extending Codex itself: adding new block types, new chart kinds, new figure kinds. Chapter 9 covers the deferred work.""",

    'ch8-extension-points': r"""Codex's renderer is a stack of small, independent dispatch tables. Three of them are explicitly designed to be extended without touching the rest of the code: the block-type dispatch in `codex/rendering/markdown.py`, the chart-type registry in `codex/rendering/charts.py`, and the figure-kind dispatch in `codex/rendering/diagrams.py`. This chapter walks each one and shows what a clean extension looks like.

The shape of every extension point is the same: a `kind` string in the source markdown maps to a draw function via a Python dict. To add a new kind, write the draw function and put one entry in the dict. Nothing else changes.

## Block types (markdown.py)

The block parser is a single function, `parse(body)`, that walks the markdown line by line and dispatches on the first non-empty character. Each branch consumes some lines and emits a `(kind, payload)` tuple. The current branches:

- `h1`, `h2`, `h3` — headings (`# `, `## `, `### `)
- `code` — fenced code blocks (` ``` `)
- `chart` — `:::chart TYPE … :::` (handled before callout because it shares the `:::` prefix)
- `callout` — `:::note`, `:::warning`, etc.
- `slope` — `!slope` slope graph
- `def` — `:::def … :::` definition list
- `figs` — `!figs:` small multiples
- `fig` — `!fig:` single figure
- `table` — `!table:bordered` directive or plain `|`-table
- `ul` — `- ` bullet list
- `quote` — `> ` blockquote
- `paragraph` — fallback

To add a new block kind:

1. Pick a unique opening token. Existing prefixes are `#`, `:::`, `!`, `|`, `-`, `>`, and ` ``` `. New blocks usually pick a new `!verb` or `:::verb` prefix.
2. Write a `_parse_<kind>(lines, start)` helper that returns `(block, next_index)`. The block is a `(kind, payload)` tuple; the payload shape is whatever the renderer needs.
3. Add a branch in `parse()` *before* any branch whose token is a prefix of yours (e.g. `:::chart` is matched before plain `:::callout`).
4. Add a corresponding render branch in `tufte.py`'s `_render_block` switch — that's the half that actually puts ink on the page.

The block parser has no per-block configuration object and no plugin loading. New kinds are added by editing `markdown.py` and `tufte.py` together.

## Chart types (charts.py)

Charts are everything inside a `:::chart TYPE … :::` block. The available types live in one dict at the bottom of `charts.py`:

```python
CHART_TYPES = {
    'bar':        draw_bar_chart,
    'line':       draw_line_chart,
    'bullet':     draw_bullet_graph,
    'scatter':    draw_scatter,
    'histogram':  draw_histogram,
    'sparkstrip': draw_sparkstrip,
    'column':     draw_column_chart,
}
```

`draw_chart(pdf, chart_type, spec, x, y, width)` does a single `CHART_TYPES.get(chart_type)` lookup. A missing type returns 0 height and prints nothing — the renderer never raises on an unknown type, so a typo in the source markdown produces a blank space rather than a broken PDF.

To add a new chart type:

1. Write `draw_<type>(pdf, spec, x, y, width=CHART_W)`. Return the height consumed in millimetres so the page-flow code can advance correctly.
2. Add one line to `CHART_TYPES`.
3. The `:::chart <type> … :::` block parser already accepts arbitrary type strings — no change needed in `markdown.py` for new chart types.

The `spec` dict comes straight from the parsed `:::chart` block. Existing renderers read `data`, `actual`, `target`, `ranges`, `bins`, `highlight`, `labels`, `series`, and `label` from it; pick the same keys when they apply, invent new ones where they don't.

The Dark2 colourblind-safe palette lives near the top of `charts.py` and is shared across all chart types — new charts should pull from it rather than introducing a fresh palette.

## Sparkline variants (sparklines.py)

Sparklines are a smaller surface than charts: they're inline glyphs, not block-level elements. The variants live as flags in the `options` set on the spec, not as a registry:

- bare line — default
- `bar` — vertical bars instead of a connected line
- `winloss` — green-up/red-down binary bars
- `end`, `min`, `max` — coloured endpoint dots
- `area` — filled area under the curve
- `dot` — single-point markers

To add a new sparkline variant, add an `elif 'newvariant' in options:` branch inside `draw_sparkline`. The dispatch is by string membership; there's no registry. New variants tend to be small enough — a dozen lines — that the inline branch is the right shape.

## Figure kinds (diagrams.py)

Figures cover diagrams that aren't charts: Mermaid flowcharts, sequence diagrams, structurizr boxes, hand-drawn SVG. The dispatch lives in `render_diagram_to_png(source, kind='mermaid', timeout=15)`. The default kind is `mermaid`, sent to the Kroki HTTP service. The `svg` kind is rendered locally without Kroki — useful for figures that should not depend on a network round-trip.

To add a new figure kind:

1. Add an `if kind == 'newkind':` branch in `render_diagram_to_png`. If the new kind is one of Kroki's many supported diagram types, the branch is one line — Kroki does the work.
2. If the new kind is rendered locally, write a `_render_<kind>_locally(source)` helper alongside `_render_svg_locally`. Return PNG bytes.
3. The `!fig:` markdown block already accepts a `kind=` argument that flows through to `render_diagram_to_png`. No change needed in `markdown.py`.

Kroki supports about 30 diagram syntaxes — PlantUML, Graphviz, BPMN, Vega, BlockDiag, etc. Adding any of them to Velour is one branch in the dispatch.

## What does *not* extend cleanly yet

Three things in the renderer are not yet refactored to a registry:

- **Inline syntax.** `parse_inline` (footnotes, citations, links, bold, italic) is a flat if/elif chain. New inline kinds need a new branch and a corresponding emitter in the text layer of `tufte.py`.
- **Callout categories.** `_parse_callout` accepts arbitrary verbs but only a few have styled rendering (`note`, `warning`, `quote`). A new callout kind is rendered as a generic note unless `tufte.py`'s callout switch is also extended.
- **Per-app reference auto-generation.** `codex/introspection.py` walks a hardcoded list of model-attribute kinds. Adding a new auto-generated reference shape (e.g. "list every management command") still requires a code change to introspection itself. A registry is on the roadmap.

These are the three places where future work will most readably make extension cheaper.

## Cross-references

Chapter 2 of this volume covered the markdown subset from the *writer's* perspective: which blocks exist and what they look like in source. This chapter covers the same blocks from the *renderer's* perspective: how new ones are added.

Chapter 4 covers the sparkline and chart libraries themselves — what each existing chart type is for and when to reach for it. Chapter 5 covers Kroki diagrams in detail. Chapter 6 covers the introspection layer, which is the "extend the auto-generated reference" half of writing a new Velour app's documentation.

Volume 2 Chapter 8 covers the parallel question for the web layer: how to add a new dashboard card or template tag. The two chapters are deliberately the same length and shape — Codex is documentation infrastructure, the dashboard is web infrastructure, and both extend by registry.""",
}


def seed_volume_4():
    m = upsert_manual(
        'velour-developer-guide-vol-4',
        title='Velour Developer Guide, Volume 4',
        subtitle='Codex and Documentation',
        format='complete',
        author='Velour',
        version='0.1 (work in progress)',
        abstract=(
            'Volume 4 of the five-volume Velour Developer Guide. '
            'Covers Codex itself: the markdown subset, the '
            'renderer, sparklines, charts, diagrams via Kroki, '
            'the introspection layer, the tutorial style guide, '
            'and the planned extensions. Companion volumes: Vol 1 '
            '(Foundations), Vol 2 (Web Layer), Vol 3 (Time and '
            'Data), Vol 5 (Operations).'
            '\n\n'
            'Status: outline + first chapter substantive; '
            'remaining chapters are stubs awaiting expansion.'
        ),
    )

    upsert_section(m, 'foreword', 10, 'Foreword',
        """Codex is the system you are reading right now. Volume 4 documents it as a system: the philosophy, the markdown subset, the renderer pipeline, the chart library, the diagram round-trip, the per-app introspection, the writing conventions, and the extension points.

This is the most self-referential volume in the set. The conventions documented in this volume were used to write this volume. Reading it carefully gives a sense of what's possible inside the same machinery; writing more of it requires becoming fluent in those same conventions.

Read Volume 1 first. Volume 4 references its concepts (the meta-app idea, the secret-file protocol) when relevant. The other companion volumes (2, 3, 5) are independent of this one — Codex is orthogonal to the rest of the codebase.

## How to read this volume

Chapter 1 is the philosophy. Chapter 2 is the reference for the markdown subset and is the chapter you'll re-read most often. Chapters 3, 4, and 5 are the renderer internals. Chapter 6 is the introspection layer that auto-generates reference appendices. Chapter 7 is the style guide. Chapters 8 and 9 are about extending Codex.

If you only want to *write* documentation, read Chapters 2 and 7. If you want to *extend* Codex, read all of it.""",
        sidenotes='Volume 4 was scoped at ~500pp — the largest in the set, because Codex contains many small-but-substantial subsystems.')

    upsert_section(m, 'ch1-philosophy', 110,
        'Chapter 1 — Codex philosophy and the Tufte influence',
        """Codex exists because no off-the-shelf documentation system fits Velour.

Sphinx is the obvious default — it's the standard for Python projects, it's well-maintained, it has a large ecosystem of themes and extensions. Velour does not use it. The reasons are specific.

## What Sphinx is good at

Sphinx is good at: indexing a large code-base by docstring, producing consistent cross-referenced HTML, producing cross-referenced PDF via LaTeX, supporting an ecosystem of plugins for diagrams and equations, and shipping with reasonable defaults that look the same as every other Python project's documentation.

The first three of these are real strengths. The last is, in Velour's case, a problem.

## What Velour wants instead

Velour's documentation is a *teaching* artifact, not a reference dump. The Quickstart is meant to be read by a new contributor in five minutes; the Working Tour is meant to be read in an evening; the Complete Reference is meant to be browsed; the Developer Guide volumes are meant to be read like a book series. Each of these has different design needs. Sphinx renders all four into the same shape.

Velour's PDFs need to look like Tufte's books. Specifically:

- The text column is narrow. Sidenotes go in the right margin, anchored to the line that triggered them, never in footers.
- Charts and tables are inline with prose, not separated into figure environments. Captions, when used at all, are short and italicised.
- Tables follow the minimal-rule convention: single horizontal lines above and below the header, no vertical rules, no zebra-striping, no borders. The bordered variant is reserved for tables where the cells are visually heterogeneous.
- Line spacing is generous. The body font is ET Book — a free derivative of the typeface Tufte commissioned for his own books.
- The colour palette is Dark2 (a colourblind-safe ColorBrewer set), used sparingly. Most pages are black ink on cream paper.

These choices compose. Each individually is small; together they make a reading experience distinct from any of the off-the-shelf documentation tools.

## Why render PDFs from Markdown directly

Sphinx renders to LaTeX, and LaTeX renders to PDF. This is the standard pipeline. Codex skips both steps. It uses fpdf2 to compose pages directly from a parsed Markdown AST.

The reason is control. LaTeX's typesetting is excellent in the canonical case but every Tufte-style customization (margin sidenotes, the narrow text column, the minimal-rule table style) requires either a non-trivial LaTeX package or hand-written `\\write18`-style hacks. Codex's renderer is ~3000 lines of Python that handles every block type Velour cares about exactly the way it should look.

The cost: writers can't drop into raw LaTeX for one-off equations or unusual layouts. The benefit: every page in every Codex manual looks the same, and every block type the renderer supports is documented in Chapter 2 of this volume.

## What follows

Chapter 2 is the reference for every block type. Chapter 3 walks the renderer. Chapter 4 covers sparklines and charts. Chapter 5 covers diagrams via Kroki. Chapter 6 covers the introspection layer. Chapter 7 is the style guide. Chapters 8 and 9 are about extension and the future.""",
        sidenotes='Tufte\'s four books — *Visual Display*, *Envisioning*, *Visual Explanations*, *Beautiful Evidence* — are the design canon Codex is trying to honour. They are also the books most likely to look hand-set even on a computer screen.')

    upsert_section(m, 'part-2', 200, 'Part II — Reference',
        """Two chapters covering everything you need to write documentation that Codex can render: the markdown subset (Chapter 2) and the renderer's internal pipeline (Chapter 3).""")

    sort = 210
    for slug, title, summary in VOL4_CHAPTERS[1:3]:
        body = VOL4_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

Approx. 50–80 pages.""")
        sn = '' if slug in VOL4_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-3', 400, 'Part III — Visualisation',
        """Two chapters covering the visualisation half of Codex: the chart library (Chapter 4) and diagrams via Kroki (Chapter 5).""")

    sort = 410
    for slug, title, summary in VOL4_CHAPTERS[3:5]:
        body = VOL4_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

Approx. 40–60 pages.""")
        sn = '' if slug in VOL4_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-4', 600, 'Part IV — Generation',
        """Two chapters: the introspection layer that generates reference appendices (Chapter 6) and the writing style guide (Chapter 7).""")

    sort = 610
    for slug, title, summary in VOL4_CHAPTERS[5:7]:
        body = VOL4_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

Approx. 30–50 pages.""")
        sn = '' if slug in VOL4_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-5', 800, 'Part V — Extension and future',
        """Two chapters on extending Codex (Chapter 8) and the deferred work (Chapter 9).""")

    sort = 810
    for slug, title, summary in VOL4_CHAPTERS[7:9]:
        body = VOL4_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

Approx. 25–40 pages.""")
        sn = '' if slug in VOL4_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10


# =====================================================================
# Volume 5 — Operations and Extension
# =====================================================================

VOL5_CHAPTERS = [
    ('ch1-production',
     'Chapter 1 — Production deployment in detail',
     'Bringing up Velour on a fresh server end-to-end: provisioning, '
     'user creation, Python install, supervisor + nginx + gunicorn '
     'wiring, secret files, first-run migrations, the smoke-test '
     'check-list. Per-section diagrams of the network flow.'),
    ('ch2-hotswap',
     'Chapter 2 — The hot-swap workflow',
     'How `manage.py generate_deploy --hotswap` produces a deploy '
     'tarball that can replace a running install without downtime. '
     'The supervisor reload sequence. Rollback procedure. The '
     'failure modes and their recoveries.'),
    ('ch3-monitoring',
     'Chapter 3 — Monitoring with hosts + cross-fleet polling',
     'The hosts app: registry of remote Velour instances, periodic '
     'health-check polling, the cross-fleet status page. The '
     'monitoring cadence trade-offs. Alert thresholds and the '
     'codex_app_reports daily snapshot.'),
    ('ch4-mail-relay',
     'Chapter 4 — Mail relay and external integration',
     'The mail relay protocol in operations terms. Token rotation. '
     'DNS records (SPF, DKIM, DMARC). Bounce handling. Migration '
     'paths from a legacy mail server.'),
    ('ch5-security-audit',
     'Chapter 5 — Security audit philosophy',
     'What security/ checks for and what it deliberately does not. '
     'The audit-table model. Daily vs ad-hoc audits. Threat model: '
     'what Velour assumes about its operator, its network, its '
     'host. The gap between the audit and a real penetration test.'),
    ('ch6-backups',
     'Chapter 6 — Maintenance and backup strategy',
     'The backups app: per-class auto-prune windows (daily=7, '
     'weekly=4, monthly=12), the secret-file inclusion list, '
     'restore procedures, off-host replication patterns. Cron '
     'integration via identity_cron.'),
    ('ch7-tokens',
     'Chapter 7 — The token rotation flow',
     'Health token, mail relay token, provisioning token, LLM '
     'API keys. The chmod 600 secret-file convention. Rotation '
     'procedure for each token. The risk of bypassing the '
     'convention.'),
    ('ch8-performance',
     'Chapter 8 — Performance: when to scale, what to measure',
     'Velour\'s performance profile in practice. Where the bottle-'
     'necks live (chronos cache miss, Codex render, three.js '
     'scene serialization). Profiling tools. When to introduce '
     'Postgres / Redis / a CDN. When not to.'),
    ('ch9-writing-an-app',
     'Chapter 9 — Writing your own Velour app from scratch',
     'A worked example: take an idea, scaffold an app, wire it '
     'into INSTALLED_APPS, add a model, add a view, add a URL, '
     'add a dashboard card, write a Codex section. End-to-end '
     'in roughly 50 minutes.'),
    ('ch10-recipes',
     'Chapter 10 — Recipes: 30 practical examples',
     'Thirty practical patterns for common tasks: scheduling a '
     'cron via identity_cron, adding an LLM augmentation hook, '
     'producing a periodic Codex report, extending Aether with a '
     'new entity script, generating a deploy artifact for a child '
     'project, etc. Each recipe is a 1-2 page worked example.'),
    ('ch11-roadmap',
     'Chapter 11 — Roadmap: the items currently in MEMORY.md backlog',
     'A snapshot of the long-term roadmap synthesised from the '
     'memory backlog: which items are deferred indefinitely, which '
     'are next-up, which depend on others, and the rough order of '
     'priority. Updated each time the guide is re-seeded.'),
]


VOL5_BODIES = {
    'ch2-hotswap': """The hot-swap workflow replaces a running Velour install on a remote host without taking it offline. The premise: gunicorn is supervised; supervisor will restart it cleanly given a new code tree; nginx in front of gunicorn buffers the second-or-two restart so most clients see no error. The whole choreography is driven by `manage.py generate_deploy --hotswap`.

This chapter walks the workflow end-to-end: what the command produces, what each script does, the failure modes, and the rollback procedure.

## What `--hotswap` produces

```
$ venv/bin/python manage.py generate_deploy --user swibliq \\
    --host velour.example.com --hotswap
deploy/hotswap-2026-04-26T19-44-12/
├── hotswap.sh        # the orchestration script (run on the target)
├── pre-checks.sh     # invoked first; aborts if anything looks off
├── post-checks.sh    # invoked last; smoke-tests the new install
└── tarball.tar.gz    # the new code tree, gitignored, generated fresh
```

The tarball is built from the current git working tree. Untracked files are not included; uncommitted changes ARE included (the assumption is the operator wants to deploy what they have, not what's pushed). The tarball contains the project tree minus `venv/`, `db.sqlite3`, the `secret_key.txt` family, and the `backups/` directory — anything live on the target stays.

## The hotswap.sh sequence

The script runs as the project user on the target host. It does, in order:

1. **Pre-flight check.** Run `pre-checks.sh`. If supervisor reports gunicorn isn't running, or disk usage is over 95%, or there's an open lock file from a previous deploy, abort here.

2. **Snapshot the current install.** `mv velour-dev velour-dev.<timestamp>`. This is the rollback target — kept for 7 days, then garbage-collected by the daily backup pipeline.

3. **Unpack the new tarball.** `tar -xzf tarball.tar.gz -C velour-dev`. The new tree lands; the old `venv/`, `db.sqlite3`, secrets, and backups are NOT in the tarball, so they remain in the timestamped snapshot directory and need to be moved across.

4. **Move the live state across.** `mv velour-dev.<timestamp>/{venv,db.sqlite3,secret_key.txt,health_token.txt,mail_relay_token.txt,backups} velour-dev/`. The new tree now has the old live state attached.

5. **Refresh the venv.** `venv/bin/pip install -q -r requirements.txt`. Skipped if `requirements.txt` is unchanged from the snapshot (sha256 compared); usually skipped.

6. **Run migrations.** `venv/bin/python manage.py migrate --noinput`. New migrations apply forward. There is no built-in support for backward-compatible migrations — that discipline is the migration author's, see Vol 5 Ch 8.

7. **Run collectstatic.** `venv/bin/python manage.py collectstatic --noinput`. New static files land under `staticfiles/` where nginx serves them.

8. **Reload supervisor.** `supervisorctl restart velour:*`. The colon-star reloads every program in the `velour` group — gunicorn, the channels worker, the per-app cron consumer if running. Supervisor's restart is graceful; gunicorn's `--graceful-timeout 30` setting in `gunicorn.conf.py` lets in-flight requests finish before workers are recycled.

9. **Post-flight check.** Run `post-checks.sh`. Hits `https://velour.example.com/health/` (the health-token-gated endpoint), expects a 200 with the build hash matching the new tree's HEAD. If the check fails, the script ROLLS BACK automatically — see below.

10. **Cleanup.** Schedule the timestamped snapshot for deletion in 7 days via `at`. The snapshot is the rollback artifact; once 7 days pass without the operator noticing a problem, the assumption is the new install is good and the snapshot is reclaimed.

## Failure modes

Things that go wrong in approximate order of frequency:

- **Migration fails at step 6.** The new code is unpacked but the database is in an in-between state. The script aborts before restarting supervisor, so the OLD code (which the snapshot dir still contains, but supervisor is still pointed at the new tree) is not restarted. Operator decision required: roll back manually (`mv velour-dev velour-dev.failed && mv velour-dev.<timestamp> velour-dev && supervisorctl restart velour:*`) or fix forward (debug the migration on the target).

- **collectstatic clobbers a file an operator hand-edited.** Conventionally, hand-edits to files under `staticfiles/` don't survive a deploy. Operators who modify static files should put the source under a per-app `static/<app>/` directory and let collectstatic pick them up.

- **Post-flight 502.** gunicorn is up but failing every request — usually a missing settings field or an import error from the new code. The script auto-rolls-back: `mv velour-dev velour-dev.failed-<timestamp> && mv velour-dev.<timestamp> velour-dev && supervisorctl restart velour:*`. The failed tree is kept for inspection. Total downtime: roughly 30 seconds.

- **Disk fills during step 5.** The old venv plus the new venv plus the tarball plus the snapshot can briefly use 3-4 GB. The pre-flight check refuses to start if free space is under 5 GB; if it crossed that threshold during the deploy, supervisor stays on the old tree and the operator gets a stack trace.

## Rollback procedure (manual)

When the auto-rollback at step 9 misses something — usually because the failure mode is "the site renders but is broken in some non-200 way" — manual rollback is two commands:

```bash
mv velour-dev velour-dev.failed-$(date +%s)
mv velour-dev.<timestamp> velour-dev
supervisorctl restart velour:*
```

The `<timestamp>` is the directory name from step 2. The supervisor restart is the third command and the only one that takes user-visible time (~5 seconds for graceful gunicorn cycling).

## Cross-references

- Vol 1 Ch 14 — the original `generate_deploy` command (without `--hotswap`).
- Vol 5 Ch 1 — the fresh-install path that produces the initial deploy.
- Vol 5 Ch 6 — the backup pipeline, which provides the snapshot recovery if even the rollback fails.

## What follows

Chapter 3 covers monitoring across multiple Velour installs (cross-fleet polling). Chapters 4-8 cover the rest of the operations surface — mail relay, security audit, backups, token rotation, performance.""",

    'ch9-writing-an-app': """Adding a Velour app is a fifty-minute exercise the first time. After that, twenty. This chapter walks an example end-to-end: the app `weather` that records local weather observations, has a model, a view, a URL, a dashboard card, and a Codex section. Every step shows the code; the convention being demonstrated is that **a new app touches only files inside the new app plus three one-line edits to the project's `settings.py` and `urls.py`**.

## Step 1 — scaffold

```bash
$ venv/bin/python manage.py startapp weather
```

Creates `weather/` with the standard Django skeleton: `models.py`, `views.py`, `admin.py`, `apps.py`, `migrations/`, `tests.py`. Velour adds a `templates/weather/` directory under the project's templates root (NOT under the app directory — see Vol 1 Ch 5 on the template convention).

```bash
$ mkdir -p templates/weather
$ touch weather/urls.py
```

## Step 2 — the model

`weather/models.py`:

```python
from django.db import models


class Observation(models.Model):
    when_utc      = models.DateTimeField(db_index=True)
    temp_c        = models.FloatField()
    humidity_pct  = models.PositiveSmallIntegerField()
    wind_kmh      = models.FloatField()
    pressure_hpa  = models.FloatField(null=True, blank=True)
    notes         = models.CharField(max_length=200, blank=True)
    source        = models.CharField(max_length=64,
        help_text='Where this reading came from — "manual", '
                  '"sensor:gary", "kmni-api"')
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-when_utc']
        indexes = [
            models.Index(fields=['-when_utc']),
            models.Index(fields=['source', '-when_utc']),
        ]

    def __str__(self):
        return f'{self.when_utc:%Y-%m-%d %H:%M} {self.temp_c}°C'
```

Conventions on display:

- `created_at` is auto-now-add for audit. The semantically meaningful timestamp is `when_utc` (when the reading was *taken*).
- Indexes on the fields that get filtered or ordered. Django creates an index on `db_index=True` fields; the `class Meta` indexes are for compound or descending sorts.
- A `source` field with documented values is more useful than a `source_app` FK in the long run — sources outlive their apps.

## Step 3 — register the app

`velour/settings.py`:

```python
INSTALLED_APPS = [
    # ...
    'weather',
]
```

One line. Alphabetically ordered (the convention in `velour/settings.py` is order-by-conceptual-grouping, not strict alphabetical, but a new addition near related apps is fine).

```bash
$ venv/bin/python manage.py makemigrations weather
$ venv/bin/python manage.py migrate weather
```

## Step 4 — the view

`weather/views.py`:

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Observation


@login_required
def index(request):
    obs = Observation.objects.all()[:50]
    return render(request, 'weather/index.html', {
        'observations': obs,
        'count': Observation.objects.count(),
    })
```

`@login_required` is the default for Velour views; the few that aren't login-gated are the API endpoints called by the ESP fleet. The Vol 5 Ch 5 security chapter covers the threat model.

## Step 5 — the template

`templates/weather/index.html`:

```django
{% extends "base.html" %}
{% block title %}Weather · Velour{% endblock %}

{% block content %}
<h1>Weather observations</h1>
<p>{{ count }} reading{{ count|pluralize }}.</p>

<table class="data">
  <thead>
    <tr><th>when</th><th>°C</th><th>%</th><th>km/h</th><th>source</th></tr>
  </thead>
  <tbody>
    {% for o in observations %}
    <tr>
      <td>{{ o.when_utc|date:"Y-m-d H:i" }}</td>
      <td>{{ o.temp_c }}</td>
      <td>{{ o.humidity_pct }}</td>
      <td>{{ o.wind_kmh }}</td>
      <td><code>{{ o.source }}</code></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

The `class="data"` styling comes from `static/site.css`; every Velour data-table uses it. No custom CSS for new apps.

## Step 6 — the URL

`weather/urls.py`:

```python
from django.urls import path
from . import views

app_name = 'weather'

urlpatterns = [
    path('', views.index, name='index'),
]
```

`velour/urls.py`:

```python
urlpatterns = [
    # ...
    path('weather/', include('weather.urls')),
]
```

One line in `velour/urls.py` — same convention as `INSTALLED_APPS`.

## Step 7 — the dashboard card

`dashboard/cards.py`:

```python
CARDS = [
    # ...
    Card('Weather', 'weather:index', icon='cloud'),
]
```

If `cloud` isn't already in `static/dashboard/icons.svg`, draw it (or copy from a SVG icon set with a compatible licence) and add it to the sprite. One commit, both files.

## Step 8 — the Codex section

`weather` becomes one-line-mentioned in `velour-complete-reference` automatically because `models_for_app('weather')` (Vol 4 Ch 6) is invoked when seeding that manual. The next time `seed_manuals` runs, an auto-generated reference appendix appears.

For a hand-written narrative, add it via `seed_velour_self_chapters.py` (or write a per-app seed command). See `seed_devguide.py`'s structure for the convention.

## Step 9 — periodic tasks (optional)

If `weather` should fire something on a schedule — say, fetch a forecast from an API every hour — add a function in `identity/cron.py`:

```python
def _do_weather_fetch():
    from django.core.management import call_command
    import io
    buf = io.StringIO()
    call_command('weather_fetch', stdout=buf)
    return buf.getvalue().strip()
```

Wire it into `pipelines` and `DEFAULT_INTERVALS` (Vol 2 Ch 8). The single crontab entry already exists; you don't add a new one.

## Step 10 — tests

`weather/tests.py`:

```python
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from .models import Observation


class ObservationModelTests(TestCase):
    def test_str(self):
        o = Observation.objects.create(
            when_utc=timezone.now(), temp_c=18.5,
            humidity_pct=65, wind_kmh=12, source='manual')
        self.assertIn('18.5', str(o))


class IndexViewTests(TestCase):
    def test_login_required(self):
        resp = self.client.get('/weather/')
        self.assertEqual(resp.status_code, 302)

    def test_renders_for_logged_in_user(self):
        u = User.objects.create_user('alice', password='pw')
        self.client.force_login(u)
        resp = self.client.get('/weather/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Weather observations')
```

Run with `manage.py test weather`.

## Total work

10 files touched, 3 of them in shared project directories (one line each), the rest under the new app. Total time at moderate pace: 50 minutes. After the second or third app, you stop following this list and just write — the conventions are small enough to internalize.

## What follows

Chapter 10 is the recipes catalogue: 30 patterns for things people commonly want to do (add an LLM augmentation hook, expose a JSON API for the ESP fleet, schedule a backup, push a custom Codex report). Chapter 11 is the long-term roadmap synthesised from the memory backlog.""",

    'ch4-mail-relay': r"""Velour ships its own mail subsystem rather than depending on Django's `EMAIL_BACKEND` setting alone. The reason is mundane: most installations want to relay mail through more than one provider (a transactional SMTP service for system notices, a personal account for development, a local SMTP listener for offline testing), and the operator wants to switch among them at runtime — not by editing settings.py and restarting.

This chapter walks the four pieces that together make Velour both a mail client and a mail server: the `MailAccount` model, the in-process `send_mail` helper, the HTTP relay endpoint for non-Django consumers, and the IMAP polling loop with its inbound handler dispatch.

## MailAccount: the credential record

`mail.MailAccount` is the central object. One row holds everything needed to send and receive through one mailbox:

- SMTP fields: `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_use_tls`, `smtp_use_ssl`
- IMAP fields: `imap_host`, `imap_port`, `imap_username`, `imap_password`, `imap_use_ssl`
- Identity: `from_email`, `from_name`
- Routing: `name` (unique label like `"snel-relay"` or `"gmail-dev"`), `enabled`, `is_default`
- Test status: `last_tested_at`, `last_test_status`, `last_test_error`

Credentials are stored in plaintext in the SQLite DB. This is the same security model as `secret_key.txt` and `health_token.txt` — a Velour install assumes the host is trusted. Encrypting credentials at rest is a cross-cutting change that should happen to all secret storage at once, not just to the mail app.

Exactly one account is `is_default=True` at any time. The model's `save()` enforces this atomically: marking an account as default unmarks any prior default in the same transaction. This invariant matters because Django's password-reset flow and any caller of `send_mail()` without an explicit `mailbox=` argument both consume the default.

## send_mail: in-process delivery

`mail.sending.send_mail` is the public API for any Django app that wants to send mail:

```python
from mail.sending import send_mail

# Defaults: uses the is_default account, sends to Identity.admin_email
send_mail('Disk filling up', '/var is at 92%.')

# Explicit recipient
send_mail('Welcome', 'Hi.', to='alice@example.com')

# Route through a specific account by name
send_mail('Invoice', 'See attached.', to='customer@x.com',
          mailbox='billing')

# HTML alternative
send_mail('Alert', 'plain text', html='<b>HTML</b>',
          to='ops@x.com')
```

Three resolution steps run inside the helper:

1. **Account.** If `mailbox=` was given, look up that named account; raise `NoMailboxConfigured` if missing or disabled. Otherwise use the default; raise `NoMailboxConfigured` if no default is set.
2. **Recipients.** If `to=` is None, look up `Identity.get_self().admin_email` as a fallback; raise `ValueError` if that's also empty.
3. **Connection.** Build a fresh `EmailMultiAlternatives` connection scoped to *this* account's SMTP credentials. The connection is not pooled — Velour mail volume is low enough that one TCP connection per message is fine, and per-account isolation matters more than throughput.

The helper is intentionally stdlib-only beyond Django itself. No `requests`, no provider-specific SDKs. Adding Postmark or SendGrid via their REST APIs would mean a new code path here; the SMTP path covers every provider that speaks SMTP, which is essentially all of them.

## DynamicMailboxBackend: wiring the Django global

`settings.EMAIL_BACKEND = 'mail.backends.DynamicMailboxBackend'` makes Django's built-in mail facilities — `django.contrib.auth` password reset, the `mail_admins` helper, anything else that calls `django.core.mail.send_mail` rather than ours — go through the same `MailAccount.get_default()` resolution. The backend reads the default account at connection-construction time. Switching the default in the admin is enough; nothing needs to be reloaded.

If no default is set, the backend falls through to a no-op that logs a warning. A Velour install with no MailAccount configured does not crash on boot or on password-reset attempts; it just fails to deliver, audibly.

## /mail/accounts/relay/: HTTP relay for external apps

The relay endpoint exists so non-Django consumers — legacy PHP scripts, shell scripts, cron jobs running outside Velour, ESP devices that can do HTTP but not SMTP TLS handshakes — can route mail through the same `MailAccount` table without re-implementing SMTP.

The protocol is one POST:

```bash
curl -X POST https://your-velour/mail/accounts/relay/ \
  -H "Authorization: Bearer $(cat ~/.config/velour-mail-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Backup complete",
    "body":    "All databases dumped successfully.",
    "to":      "ops@example.com",
    "mailbox": "snel-relay"
  }'
```

The view, `mail.views.relay_send`, does five things:

1. **Token check.** Reads `mail_relay_token.txt` from `BASE_DIR`. If the file is missing, the endpoint 404s — relay is opt-in. If the file exists but the request's `Authorization: Bearer` value does not match (constant-time `hmac.compare_digest`), 401.
2. **Payload parse.** JSON body with required fields `subject`, `body`, `to`; optional `mailbox`, `html`, `reply_to`.
3. **Delegate to `send_mail`.** Same path as in-process callers — no special case in the relay.
4. **Map exceptions to status codes.** `NoMailboxConfigured` → 503, `smtplib.SMTPException` or `OSError` → 502, anything else → 500. The error body always includes the exception type name; never includes the credential.
5. **Return JSON.** `{"ok": true, "delivered": 1, "mailbox": "snel-relay"}`.

The endpoint is `csrf_exempt` because the bearer token is the auth. It is also `require_POST` — GET on this URL is meaningless.

## Inbound: polling, parsing, dispatch

`mail.polling.poll_account(account)` runs IMAP IDLE-style fetch against one MailAccount and writes new messages to `InboundMessage`. The `(mailbox, uid)` unique constraint makes polls idempotent — re-running poll on a mailbox that already has 200 messages fetches none of them again.

`InboundMessage` stores the raw RFC 822 source verbatim. Parsed fields (subject, from, to, date, body) are pulled out for display, but if the parser misses a header or a future release adds attachment handling, the raw source is enough to re-process old messages without re-fetching from IMAP.

Two flags live alongside each message:

- `read` — human-in-the-loop view flag, like any webmail
- `handled` — machine-in-the-loop processing flag, used by the `mail.handler.VelourSMTPHandler` registry pattern

These are independent. A submission email might be `handled=True, read=False` (the parser already extracted its attachment, but no human has opened it) or `handled=False, read=True` (an operator opened it and wants to defer machine processing).

## Local SMTP server

`mail.handler.VelourSMTPHandler` (registered in `deploy/supervisor-wsl.conf` and equivalent prod configs) listens on a local SMTP port for messages addressed to `velour-local`. Inbound mail goes through the same `InboundMessage` table as IMAP-fetched mail and the same handler dispatch. This is how Velour-internal apps that want to send mail via SMTP without going through `send_mail` can still land in the inbox — useful for legacy code being migrated.

## What this chapter does not cover

Inbound handler implementations — the actual logic that decides "this is a submission", "this is a bounce", "this is a system notice" — are application-specific. Volume 2 Chapter 5 covers the mail UI; this chapter covers the relay infrastructure that surfaces in production deployments.

Token rotation for `mail_relay_token.txt` is covered in Chapter 7 of this volume alongside the other secret-file rotations. The same mechanic applies — write a new token, fan it out to consumers, then replace the file.

Performance: SMTP is the slow path. Sending 100 messages through one account takes around 10–20 seconds because each message opens its own TLS connection. If you find yourself sending bulk mail through Velour, the right answer is usually a third-party transactional service with its own queue (Postmark, SES) and a thin `send_mail` wrapper that POSTs to their API. That wrapper does not yet exist.""",

    'ch10-recipes': r"""This chapter is the cookbook. Each recipe is a short, runnable example for a real situation an operator runs into — not a theoretical exercise. They are grouped roughly by surface area: deployment, mail, identity, fleet, codex, data, observability.

The intent is for an operator to skim the headings, recognise their situation, and copy a working snippet. The style is deliberately terse: command on top, one paragraph of explanation underneath, occasional warnings.

## Deployment & operations

### 1. Spin up a fresh Velour from scratch

```bash
git clone https://github.com/handyc/velour.git velour-dev
cd velour-dev
python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py createsuperuser
venv/bin/python manage.py seed_defaults
venv/bin/python manage.py runserver 0.0.0.0:7777
```

Bind to `0.0.0.0`, not bare `7777`. The bare form binds to `127.0.0.1` only and silently RSTs ESP-board registrations from the LAN.

### 2. Generate a deploy bundle for production

```bash
venv/bin/python manage.py generate_deploy --user swibliq --host snel.com
```

Writes a self-contained `deploy/` tarball with systemd units, gunicorn config, and an idempotent install script. The convention is one user per app: socket, dir, static, and venv all live under `/var/www/webapps/<user>/`.

### 3. Hot-swap a live deploy without dropping connections

```bash
ssh swibliq@snel.com 'cd app && git pull && venv/bin/python manage.py migrate && systemctl --user reload velour'
```

`reload`, not `restart`. Gunicorn's USR2 handler forks new workers, drains the old ones, and the LB never sees a 502.

### 4. Rotate the secret key

Edit `secret_key.txt` (chmod 600), then restart workers. Existing sessions invalidate; password-reset tokens issued before the rotation stop working. Schedule rotations during maintenance windows.

### 5. Take a manual backup

```bash
venv/bin/python manage.py make_backup --class manual --note 'pre-migration'
```

Writes a snapshot to the configured backups dir and inserts a `Snapshot` row. Auto-prune does not touch `class=manual` snapshots — they live until you delete them.

## Mail

### 6. Add a new SMTP relay

Open `/mail/accounts/`, click *Add account*, fill in SMTP host/port/user/password, mark `enabled`. To make it the new global default, also tick `is_default` — the model unmarks the previous default automatically.

### 7. Send mail from any Django app

```python
from mail.sending import send_mail
send_mail('Disk full', '/var is at 92%.')  # uses default account, sends to Identity.admin_email
```

Defaults are forgiving: missing `to` falls back to `Identity.admin_email`, missing `mailbox` falls back to the `is_default` MailAccount.

### 8. Relay mail from a non-Django script

```bash
curl -X POST https://your-velour/mail/accounts/relay/ \
  -H "Authorization: Bearer $(cat ~/.velour-mail-token)" \
  -H "Content-Type: application/json" \
  -d '{"subject":"hi","body":"text","to":"a@b.com","mailbox":"snel-relay"}'
```

Token comes from `mail_relay_token.txt` on the Velour host. If the file is missing, the endpoint 404s — opt-in by design.

## Identity

### 9. Read Velour's current mood

```python
from identity.models import Identity
self = Identity.get_self()
print(self.mood, self.mood_intensity, self.mood_because)
```

Mood is a 2D circumplex (valence × arousal). The named mood is the closest of 16 cells.

### 10. Trigger a single tick manually

```bash
venv/bin/python manage.py identity_tick
```

Idempotent — running twice in the same minute does the same work as once. The cron job runs this every minute in production.

### 11. Acknowledge a recurring concern so it stops nagging

```bash
venv/bin/python manage.py identity_acknowledge fleet_partial_silence
```

Adds an `AspectSuppression` row. The aspect stops generating concerns until the suppression is deleted. Useful when you know an alert is going to keep firing for a known reason.

### 12. Run a deeper meditation on demand

```bash
venv/bin/python manage.py meditate_deep --depth 5
```

Composes a meditation chain at the requested ladder depth. Higher depths take longer and produce richer Mirror entries. Depth 7 is the deepest currently supported.

## Fleet (ESP nodes)

### 13. Provision a fresh ESP board

```bash
venv/bin/pio run -d nodes/firmware/<board> --target upload --upload-port /dev/ttyACM0
```

User attaches USB via `usbipd` Windows-side and reports the bus ID; the board appears as `/dev/ttyACM0` inside WSL. The Gary-family boards use `'-DX="value"'` quoting for build flags with spaces.

### 14. Deliver an OTA update to a registered node

Open `/nodes/<slug>/ota/`, pick a firmware artifact, click *Schedule*. The next time the node calls home (default: every 30s), it pulls and flashes.

### 15. Discover where a freshly-flashed node landed on the LAN

```bash
curl http://<host>:7777/api/nodes/discover
```

Returns the most recent `(mac, ip, last_seen)` rows. The Velour client library's `VelourClient::discover()` is built on this.

### 16. Suppress fleet-silence concerns when boards are intentionally off

```bash
venv/bin/python manage.py identity_acknowledge fleet_partial_silence
```

Same recipe as #11; called out separately because this is the most common acknowledgement when you're reworking the lab and powering boards down.

## Codex

### 17. Seed the default manuals

```bash
venv/bin/python manage.py seed_defaults
```

Idempotent. Re-runs are safe and pick up any new manuals added to seed scripts since last run.

### 18. Render a manual to PDF

```bash
venv/bin/python manage.py render_manual <slug>
```

Uses `codex/rendering/tufte.py`. The PDF lands next to the manual record. Volumes are rendered with `render_volume`.

### 19. Add a chart to a manual section

```
:::chart bar
data: 12, 18, 9, 27, 14
labels: A, B, C, D, E
:::
```

Seven chart types ship: `bar`, `line`, `bullet`, `scatter`, `histogram`, `sparkstrip`, `column`. All draw from the Dark2 colourblind-safe palette.

### 20. Inline sparkline in prose

```
The week's load: `spark:12,18,9,27,14,21,16` peaked Wednesday.
```

Add `:bar`, `:winloss`, `:end`, `:min`, `:max`, `:area`, or `:dot` after the values for variants.

### 21. Embed a Mermaid diagram

```
!fig: my-diagram

mermaid
graph LR
  A --> B --> C
```

Renders via Kroki. The first deploy needs network reachability to a Kroki instance; thereafter the rendered PNG is cached.

## Data

### 22. Lift a legacy MySQL site into Velour

```bash
venv/bin/python manage.py liftsite mydump.sql --target-app legacy_archive
```

`datalift` parses the dump, generates Django models, runs migrations, ingests the rows, and anonymises configurable PII columns. Standalone — does not depend on `databases`.

### 23. Lift a WordPress export into block-rendered templates

```bash
venv/bin/python manage.py liftwpblock --export wp.xml --theme twentytwentytwo
```

Parses `<!-- wp:* -->` markup and `theme.json`, emits Django templates that render in the original theme's colours.

### 24. Run an ad-hoc query against a registered DB

Open `/databases/<id>/sql/`, type SQL, hit *Run*. Read-only by default; toggle the *Allow write* switch only when you mean it.

## Observability & introspection

### 25. Watch the morning briefing

`/chronos/briefing/` — mood, concerns, today's events, environs, sky, tasks, reading queue. The same content is pushed daily to a Codex manual via `identity_cron` between 06:00 and 08:00 local.

### 26. Tail Velour's structured logs

```bash
tail -f logs/velour.log | grep -v 'GET /api/nodes/heartbeat'
```

The heartbeat endpoint is chatty; filter it out for human reading.

### 27. Query the Identity Mirror by date

```python
from codex.models import Manual
m = Manual.objects.get(slug='velours-mirror')
for s in m.sections.filter(sort_order__gte=20260420).order_by('sort_order'):
    print(s.title)
```

The Mirror's `sort_order` is `YYYYMMDDHHMM`-style integer time, so range queries over time are simple integer comparisons.

### 28. Subscribe to the sky calendar feed

`/chronos/sky/feed.ics` — passes, transits, NEOs, eclipses, conjunctions. Filterable via `?include=passes,transits` or `?exclude=neos`. Subscribe, don't download — the feed updates as the sky calendar does.

## Generation & GA

### 29. Run a Naiad evolutionary search

```bash
venv/bin/python manage.py naiad_evolve <goal-system> --preset apartment --pop 250 --gens 1500 --seed 42 --every 250
```

`--preset` picks a fitness landscape (`apartment`, `garden`, `coastal`, `protein`, `kitchen`, `field`, `consumer`, `industrial`). The GA prints the best chain every `--every` generations and the final best on completion.

### 30. Speciate a Casting experiment into a Language

Open `/casting/byte_model_evolution/`, set a goal expression, click *Speciate*. The engine runs a per-Language-seeded GA, the winner is absorbed back as a tournament trophy. The same engine drives `/evolution/`'s Language tournament button.

## Pointers for the rest

The recipes above cover the most common operator situations. For everything else: Volume 2 covers per-app web-layer recipes, Volume 3 covers data and time, Volume 4 covers writing your own Codex content, Volume 5 Chapter 9 covers writing your own Velour app from scratch (the deepest single recipe in the book).""",
}


def seed_volume_5():
    m = upsert_manual(
        'velour-developer-guide-vol-5',
        title='Velour Developer Guide, Volume 5',
        subtitle='Operations and Extension',
        format='complete',
        author='Velour',
        version='0.1 (work in progress)',
        abstract=(
            'Volume 5 of the five-volume Velour Developer Guide. '
            'Covers production operations (deploy, hot-swap, '
            'monitoring, mail relay, security audit, backups, '
            'token rotation, performance) and extension (writing '
            'your own app, recipes, the long-term roadmap). '
            'Companion volumes: Vol 1 (Foundations), Vol 2 (Web '
            'Layer), Vol 3 (Time and Data), Vol 4 (Codex).'
            '\n\n'
            'Status: outline + first chapter substantive; '
            'remaining chapters are stubs awaiting expansion.'
        ),
    )

    upsert_section(m, 'foreword', 10, 'Foreword',
        """Volume 5 is for the operator. The previous four volumes covered what Velour *is* (Vol 1), what it shows you (Vol 2), what it knows about (Vol 3), and how it documents itself (Vol 4). This volume is about how to *run* it.

The first eight chapters cover production operations: deployment, hot-swap, monitoring, mail relay, security audit, backups, token rotation, and performance. The last three cover extension: writing your own Velour app, a catalogue of recipes for common tasks, and the current long-term roadmap synthesised from the memory backlog.

Read this volume after Volume 1 — the meta-app idiom and the secret-file protocol are prerequisites for everything in here. The other volumes (2, 3, 4) are useful but not required.

## How to read this volume

Chapters 1 and 2 (deployment and hot-swap) are best read together; they describe two paths through the same generate_deploy machinery. Chapters 3 through 8 are independent; read whichever applies to the operational concern in front of you.

Chapters 9 and 10 are the extension chapters and are the ones to read when *adding* something to Velour. Chapter 11 is the roadmap and is the one to consult to know what's coming next.""",
        sidenotes='Volume 5 was scoped at ~400pp.')

    upsert_section(m, 'ch1-production', 110,
        'Chapter 1 — Production deployment in detail',
        """Volume 1's deploy chapter explained the *idea* of `generate_deploy` — that it's a Django management command which renders templates for nginx, supervisor, gunicorn, and a setup script, parameterised by a target user and a target host. This chapter is the operations side: how to actually use those generated artifacts to bring Velour up on a fresh server, and what to check when the bring-up fails.

## The fresh-host check-list

The shortest path from a bare Linux host to a running Velour, in order:

1. **Provision the user.** `useradd -m -s /bin/bash velour`. The user owns the project tree and runs gunicorn. Do not run gunicorn as root.
2. **Install Python.** Whatever Python version Velour was last tested against (currently 3.12); a venv inside the project tree avoids touching system Python.
3. **Install the runtime supervisor.** Either system-wide supervisord (Debian: `apt install supervisor`) or the user-mode WSL pattern documented in `deploy/supervisord-wsl.ini`.
4. **Install nginx** and the systemd unit it ships with. Disable the default vhost.
5. **Clone the repo** as the velour user, into `/var/www/webapps/velour/velour-dev`.
6. **Make the venv:** `cd /var/www/webapps/velour/velour-dev && python3.12 -m venv venv`.
7. **Install the deps:** `venv/bin/pip install -r requirements.txt`.
8. **Generate the deploy artifacts:** `venv/bin/python manage.py generate_deploy --user velour --host velour.example.com`. This writes nginx.conf, supervisor.conf, gunicorn.conf.py, setup.sh, and adminsetup.sh into `deploy/`.
9. **Run setup.sh** as root. It creates the secret-file directory, writes initial chmod-600 secrets, sets up nginx and supervisor symlinks, and reloads both.
10. **Run adminsetup.sh** as the velour user. It runs migrations, creates a superuser, and seeds the default Codex manuals.
11. **Smoke-test:** `curl -I https://velour.example.com/dashboard/`. Expect a 302 to the login page.

If every step succeeds, total wall time is roughly fifteen minutes for an experienced operator on familiar infrastructure.

## What goes wrong

The failure modes, in approximate order of frequency:

- **nginx returns 502** — gunicorn isn't reachable on the unix socket. Check supervisor status; check the socket path matches what nginx is configured to proxy to.
- **The static files don't load** — `collectstatic` wasn't run, or `STATIC_ROOT` is misconfigured, or the nginx alias doesn't match. The Velour convention is `STATIC_ROOT = BASE_DIR / 'staticfiles'` and the nginx alias points at exactly that.
- **The first request hangs** — sqlite write contention from the first migration not having finished, or a missing secret file the app tries to read at import time.
- **The next-day cron doesn't fire** — the operator forgot to install the one-line crontab entry. There is exactly one entry: `* * * * * /path/to/venv/bin/python /path/to/manage.py identity_cron`. The dispatcher decides what to run.

Each of these has a recovery procedure documented in the per-section paragraphs that follow this chapter's stub.

## What follows

Chapter 2 covers the hot-swap workflow — replacing a running install without downtime. Chapter 3 covers monitoring. Chapters 4 through 8 cover specific operational concerns. Chapter 9 covers writing a new Velour app. Chapter 10 is the recipes catalogue. Chapter 11 is the roadmap.""",
        sidenotes='The fifteen-minute fresh-host bring-up assumes the operator has done it before. First time, budget an afternoon and expect to learn at least one thing about the infrastructure that wasn\'t in any documentation.')

    upsert_section(m, 'part-2', 200, 'Part II — Operations',
        """Seven chapters covering specific operational concerns: hot-swap, monitoring, mail relay, security audit, backups, token rotation, and performance.""")

    sort = 210
    for slug, title, summary in VOL5_CHAPTERS[1:8]:
        body = VOL5_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

Approx. 25–40 pages.""")
        sn = '' if slug in VOL5_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10

    upsert_section(m, 'part-3', 800, 'Part III — Extension',
        """Three chapters on extending Velour: writing your own app (Chapter 9), a recipes catalogue (Chapter 10), and the current roadmap (Chapter 11).""")

    sort = 810
    for slug, title, summary in VOL5_CHAPTERS[8:11]:
        body = VOL5_BODIES.get(slug, f"""*This chapter is a stub. Outline:*

{summary}

Approx. 30–50 pages.""")
        sn = '' if slug in VOL5_BODIES else 'Stub.'
        upsert_section(m, slug, sort, title, body, sidenotes=sn)
        sort += 10


# =====================================================================
# Volume binding — "The Velour Developer Guide"
# =====================================================================

def seed_developer_guide_volume():
    """Bind all five volumes into one Codex Volume so a reader sees
    them as a coherent set rather than five orphan slugs in the
    manual list."""
    from codex.models import Volume, Manual, VolumeManual

    v, _ = Volume.objects.get_or_create(
        slug='the-velour-developer-guide',
        defaults={
            'title':    'The Velour Developer Guide',
            'subtitle': 'A five-volume reference for the meta-app',
            'author':   'Velour',
            'abstract': (
                'Five volumes: Foundations and Philosophy (Vol 1), '
                'The Web Layer (Vol 2), Time and Data (Vol 3), '
                'Codex and Documentation (Vol 4), Operations and '
                'Extension (Vol 5). Modelled on the Unix V '
                'Programmer\'s Manual: dense, opinionated, '
                'cross-referenced. Volume 1 is substantive; '
                'Volumes 2-5 are working drafts with first '
                'chapters written and remaining chapters '
                'outlined.'),
        },
    )
    v.title = 'The Velour Developer Guide'
    v.subtitle = 'A five-volume reference for the meta-app'
    v.save()

    VolumeManual.objects.filter(volume=v).delete()
    for i in range(1, 6):
        slug = f'velour-developer-guide-vol-{i}'
        m = Manual.objects.filter(slug=slug).first()
        if m:
            VolumeManual.objects.create(volume=v, manual=m, sort_order=i)
    return v


SEEDERS = {
    1: seed_volume_1,
    2: seed_volume_2,
    3: seed_volume_3,
    4: seed_volume_4,
    5: seed_volume_5,
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
        vol = seed_developer_guide_volume()
        self.stdout.write(self.style.SUCCESS(
            f'  ✓ volume "{vol.title}" → '
            f'/codex/volumes/{vol.slug}/'
        ))

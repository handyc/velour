# CLAUDE.md

Project orientation for Claude (or any agent / new contributor).

## What Velour is

Velour is a Django "meta-app" — an app factory that is also the app
it generates. Single Django project (`velour/`) with many apps at
the repo root. Templates live under `templates/<appname>/`.

## Running locally

```
venv/bin/python manage.py runserver 7777
```

SQLite at `db.sqlite3` (gitignored). Fresh checkout needs `migrate`,
`createsuperuser`, and `seed_defaults`.

## App layout

Each app: `appname/{__init__,apps,admin,models,views,urls}.py` +
`migrations/`. Templates at `templates/appname/`. One `base.html`.

## Apps (see settings.py for authoritative list)

**Office suite:** mail (accounts + inbound + SMTP server), chronos
(clocks + calendar), codex (manuals + PDFs), attic (media library).

**System:** dashboard, terminal, sysinfo, security, logs, services,
databases, graphs, maintenance, winctl, hosts, landingpage.

**Identity:** identity (mood, ticks, concerns, reflections,
meditations, strange loops, introspective layers, assertions).

**IoT:** nodes (ESP fleet + API), experiments, oracle (decision trees).

**Creative:** tiles (Wang tiles — square + hexagonal), app_factory,
lsystem (procedural L-system plant species with 3D preview + Aether export/import).

**Data:** datalift (MySQL→Django models+SQLite conversion, data anonymization).

**Other:** agricola (game), cartography (maps), hpc (clusters).

## Secrets

Three secret files at `BASE_DIR` (chmod 600, gitignored):
`secret_key.txt`, `health_token.txt`, `mail_relay_token.txt`.
**Never commit secrets.**

## House style

- Comments only when the *why* is non-obvious.
- Edit existing files; don't add new ones unless required.
- Three similar lines beats a premature helper.
- UI: Tufte-influenced — high data-ink ratio, minimal chrome.

## Don'ts

- Don't `git add -A` blindly. Review the diff.
- Don't commit `db.sqlite3`.
- Don't switch HTTPS to SSH for the GitHub remote.
- Don't rename Django apps casually (migration tables).
- Don't bypass git hooks without an explicit ask.

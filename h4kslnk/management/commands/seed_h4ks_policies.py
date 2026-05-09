"""Seed the h4kslnk Policy + IrcContact tables with what we know.

Re-runnable: rows are upserted by slug / nick.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from h4kslnk.models import Policy, IrcContact


POLICIES = [
    {
        'slug': 'vibegames-overview',
        'target': 'vibegames',
        'title': 'Vibegames is a folder per project on GitHub',
        'body': (
            'games.h4ks.com is the showroom; its API is FastAPI, its\n'
            'storage is the github.com/h4ks-com/vibegames repo.\n'
            '\n'
            'Each game is one folder under that repo containing\n'
            'index.html (+ optional siblings).  No version metadata\n'
            'is stored in the API DB — *git history* is the version\n'
            'log.  When you push the same project name again, you\n'
            'overwrite index.html and add one commit; the prior\n'
            'version is reachable via blob/<sha> on github.com.\n'
            '\n'
            'Implication: keep one project name per game (e.g.\n'
            '"officerpg") and push iterations to the same name.\n'
            'Don\'t spawn one project per ev — that clogs the list.'
        ),
    },
    {
        'slug': 'vibegames-naming',
        'target': 'vibegames',
        'title': 'Project names are lowercase, dash-separated',
        'body': (
            'sanitize_project_name lowercases and slugifies, so\n'
            '"OfficeRPG_v3!" becomes "officerpg-v3".  Pick the\n'
            'final slug you want from the start; renaming later\n'
            'is a fresh project + lost num_opens count.'
        ),
    },
    {
        'slug': 'vibegames-push',
        'target': 'vibegames',
        'title': 'Push via PUT /api/project/<slug>/<file>',
        'body': (
            'Body shape: {"content": "<base64>", "encoding": "base64"}.\n'
            'See manage.py h4ks_push for the canonical implementation.\n'
            'Bearer token may or may not be required depending on the\n'
            'deployment — a 403 "Invalid API Key" means set\n'
            'H4KS_VIBEGAMES_TOKEN.\n'
            '\n'
            'If a project is locked (Game.locked=True in the API DB),\n'
            'you get 403 even with a valid key — ask an admin to\n'
            'PUT /admin/lock/<name> with locked=false.'
        ),
    },
    {
        'slug': 'vibegames-revert',
        'target': 'vibegames',
        'title': 'Revert is one-step only',
        'body': (
            'GET /api/revert_project/<name> rolls index.html back\n'
            'one commit on GitHub.  No cherry-pick to an arbitrary\n'
            'sha exposed yet — that\'s the upstream version-picker\n'
            'feature on the backlog.'
        ),
    },
    {
        'slug': 'shorts',
        'target': 'shorts',
        'title': 's.h4ks.com is a generic file/blob host',
        'body': (
            'Used by Velour apps as a paste/blob endpoint when a\n'
            'GitHub project would be overkill — short-lived\n'
            'screenshots, tiny shareable HTML, etc.\n'
            '\n'
            'TODO: document the upload contract once we use it from\n'
            'h4kslnk.  For now this entry is a placeholder.'
        ),
    },
    {
        'slug': 'irc-server',
        'target': 'irc',
        'title': 'chat.h4ks.com IRC server',
        'body': (
            'Default to TLS port 6697.  Plain 6667 may also work.\n'
            'Bot nicks should be prefixed "velour-" so anyone\n'
            'observing immediately knows the message origin\n'
            '(and can ignore/kickban without affecting the operator).\n'
            'NickServ registration not required for ad-hoc bots — a\n'
            'fresh nick per session is fine.'
        ),
    },
    {
        'slug': 'irc-etiquette',
        'target': 'irc',
        'title': 'Don\'t spam, don\'t talk for the operator',
        'body': (
            '1. Hard cap on outgoing PRIVMSGs per session (default 5).\n'
            '   Configurable via --cap on h4ks_irc_session.\n'
            '\n'
            '2. Default mode is operator-gated: each outgoing message\n'
            '   is typed at a stdin prompt by the operator.\n'
            '   Autonomous mode is opt-in via BotSession.autonomous.\n'
            '\n'
            '3. Don\'t initiate PMs to people we don\'t know.  Stick\n'
            '   to the IrcContact registry, or a public channel.\n'
            '\n'
            '4. State up front "I\'m a bot operated by handyc, ask\n'
            '   any human-routing question in plaintext."\n'
            '\n'
            '5. If the peer asks the bot to leave, /quit immediately.'
        ),
    },
]


CONTACTS = [
    {'nick': 'handyc',  'display': 'handyc',
     'role': 'me — operator',
     'timezone': 'Europe/Amsterdam', 'notes': 'self'},
    {'nick': 'mattf',   'display': 'mattf',
     'role': 'mattfly — vibegames maintainer; runs games.h4ks.com',
     'timezone': '', 'notes':
        'Author of the vibegames repo and the webcapture-service.\n'
        'Likely the right person for any backend question.'},
    {'nick': 'valware', 'display': 'Valware',
     'role': 'h4ks.com community member',
     'timezone': '', 'notes': ''},
    {'nick': 'doesnm',  'display': 'doesnm',
     'role': 'h4ks.com community member',
     'timezone': '', 'notes': ''},
]


class Command(BaseCommand):
    help = 'Seed h4kslnk Policy + IrcContact rows.'

    def handle(self, *args, **opts):
        for p in POLICIES:
            obj, created = Policy.objects.update_or_create(
                slug=p['slug'],
                defaults={'target': p['target'], 'title': p['title'],
                          'body': p['body']},
            )
            self.stdout.write(
                f'  policy {"+" if created else "·"} {obj.slug}')
        for c in CONTACTS:
            obj, created = IrcContact.objects.update_or_create(
                nick=c['nick'],
                defaults={'display': c['display'], 'role': c['role'],
                          'timezone': c['timezone'], 'notes': c['notes']},
            )
            self.stdout.write(
                f'  contact {"+" if created else "·"} {obj.nick}')
        self.stdout.write(self.style.SUCCESS(
            f'seeded {len(POLICIES)} policies + {len(CONTACTS)} contacts'))

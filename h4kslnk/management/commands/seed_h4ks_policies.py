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
        'title': 'Push via .vibeimport in #lobby (NOT the HTTP API)',
        'body': (
            'CONFIRMED 2026-05-09: the HTTP PUT /api/project/<slug>/<file>\n'
            'endpoint requires a Bearer key we do not have, and that is\n'
            'NOT the canonical workflow.  The real upload path is:\n'
            '\n'
            '1. Host the file at a public URL.  Cleanest: commit to\n'
            '   github.com/handyc/velour and use the raw.githubusercontent\n'
            '   URL on main.  Same project name = next push is a new\n'
            '   commit on that path; old versions stay reachable via git.\n'
            '\n'
            '2. Join #lobby on irc.h4ks.com (TLS 6697) and PRIVMSG:\n'
            '       .vibeimport <slug>/<file> <raw_url>\n'
            '   _cloudbot fetches the URL and registers/updates the\n'
            '   game.  Confirmation comes back as a NOTICE with the\n'
            '   live URL: https://<slug>.games.h4ks.com\n'
            '\n'
            '3. Iterate by re-pushing to the same git path AND repeating\n'
            '   .vibeimport with the same slug.  No archive flooding.\n'
            '\n'
            'h4ks_push (HTTP PUT) is kept as a fallback for any deployment\n'
            'that re-enables direct upload, but the real flow is IRC.'
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
        'title': 'irc.h4ks.com:6697 (NOT chat.h4ks.com — cert mismatch)',
        'body': (
            'CONFIRMED 2026-05-09 by connecting:\n'
            '  server   irc.h4ks.com\n'
            '  port     6697\n'
            '  TLS      yes (cert CN=irc.h4ks.com only;\n'
            '           connecting to chat.h4ks.com fails SNI verify)\n'
            '  password not needed for ad-hoc nicks\n'
            '  registration: not required, but operator nick of choice\n'
            '                is "hamburgerman" (per handyc 2026-05-09).\n'
            '\n'
            'Main channel is #lobby (NOT #h4ks).  cloudbot lives\n'
            'there and answers .vibeimport.  Regulars seen 2026-05-09:\n'
            'handyc (operator), mattf (vibegames maintainer/cloudbot),\n'
            '_cloudbot (the channel bot itself).'
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
    {'nick': 'loudercake', 'display': 'loudercake',
     'role': 'h4ks.com community member',
     'timezone': '', 'notes':
        'Friend of the channel; hamburgerman is fond of him alongside '
        'mattf and handyc.  Greet warmly when seen, brief chats welcome.'},
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

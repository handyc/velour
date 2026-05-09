"""Push a local file to games.h4ks.com as <project>/<filename>.

Usage:
    manage.py h4ks_push <local_file> <project> [<dest_filename>]

Vibegames keeps version history in git.  Same project name = same
folder = next push is a new commit on that path; old versions stay
viewable via GitHub's blob history.  No version metadata to track
locally beyond a row in VibegamePush so the dashboard can show
"last pushed N minutes ago".

If the deployed games.h4ks.com requires a Bearer key, set it via:
    --token <key>          # one-shot
    H4KS_VIBEGAMES_TOKEN=… # env, picked up automatically

If neither is set the push is attempted unauthenticated; vibegames
will return 403 and the failure is recorded in the row.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from h4kslnk.models import VibegamePush


DEFAULT_API_BASE = 'https://games.h4ks.com'


class Command(BaseCommand):
    help = 'Push a local file to vibegames as <project>/<filename>.'

    def add_arguments(self, parser):
        parser.add_argument('local_file', help='Local path to upload.')
        parser.add_argument('project', help='Vibegames project slug.')
        parser.add_argument('dest', nargs='?', default='index.html',
                            help='Filename inside the project folder '
                                 '(default: index.html).')
        parser.add_argument('--api-base', default=DEFAULT_API_BASE,
                            help='Vibegames API root.')
        parser.add_argument('--token', default=None,
                            help='Bearer token (or set H4KS_VIBEGAMES_TOKEN).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print the request without sending.')

    def handle(self, *args, **opts):
        src = Path(opts['local_file'])
        if not src.is_file():
            raise CommandError(f'No such file: {src}')

        project = opts['project']
        dest = opts['dest']
        token = opts['token'] or os.environ.get('H4KS_VIBEGAMES_TOKEN', '')

        content_bytes = src.read_bytes()
        content_b64 = base64.b64encode(content_bytes).decode('ascii')
        url = f'{opts["api_base"].rstrip("/")}/api/project/{project}/{dest}'

        body = {'content': content_b64, 'encoding': 'base64'}
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        self.stdout.write(f'PUT {url}')
        self.stdout.write(f'    {len(content_bytes)} bytes from {src}')
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('dry-run; not sending'))
            return

        try:
            resp = requests.put(url, json=body, headers=headers, timeout=30)
        except requests.RequestException as e:
            VibegamePush.objects.create(
                project=project, filename=dest,
                source_path=str(src), bytes_sent=len(content_bytes),
                response_code=0, response_body=f'request error: {e}')
            raise CommandError(f'request failed: {e}')

        push = VibegamePush.objects.create(
            project=project, filename=dest,
            source_path=str(src), bytes_sent=len(content_bytes),
            response_code=resp.status_code,
            response_body=resp.text[:4000],
        )

        if 200 <= resp.status_code < 300:
            self.stdout.write(self.style.SUCCESS(
                f'OK {resp.status_code} · push #{push.pk}'))
            try:
                data = resp.json()
                if 'thumb_url' in data or 'html_path' in data:
                    self.stdout.write(f'    {data}')
            except Exception:
                pass
        else:
            self.stdout.write(self.style.ERROR(
                f'FAIL {resp.status_code}: {resp.text[:300]}'))

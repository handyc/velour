"""Generate (or display) the bearer token used by the HTTP mail relay endpoint.

    python manage.py init_mail_relay_token           # creates if missing
    python manage.py init_mail_relay_token --show    # print existing token
    python manage.py init_mail_relay_token --force   # overwrite existing

Lives in BASE_DIR/mail_relay_token.txt, mirrors the shape of
sysinfo/init_health_token so external apps can POST to /mailboxes/relay/
with `Authorization: Bearer <token>` and have velour relay mail through
the configured MailAccount fleet.
"""

import os
import secrets
import string

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


TOKEN_FILENAME = 'mail_relay_token.txt'
TOKEN_LENGTH = 48
TOKEN_ALPHABET = string.ascii_letters + string.digits


class Command(BaseCommand):
    help = (
        'Initialize the bearer token for /mailboxes/relay/. '
        'Stored in BASE_DIR/mail_relay_token.txt.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--show', action='store_true')
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **opts):
        token_file = settings.BASE_DIR / TOKEN_FILENAME

        if opts['show']:
            if not token_file.is_file():
                raise CommandError(f'No token file at {token_file}.')
            self.stdout.write(token_file.read_text().strip())
            return

        if token_file.exists() and not opts['force']:
            raise CommandError(
                f'{token_file} already exists. Use --show or --force.'
            )

        token = ''.join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        token_file.write_text(token + '\n')
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass

        self.stdout.write(self.style.SUCCESS(f'Wrote {token_file}'))
        self.stdout.write('')
        self.stdout.write('Token (use in Authorization: Bearer header when POSTing to /mailboxes/relay/):')
        self.stdout.write('')
        self.stdout.write(f'  {token}')

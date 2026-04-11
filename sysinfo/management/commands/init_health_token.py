"""Generate (or display) the health endpoint bearer token for this host.

    python manage.py init_health_token           # creates if missing, prints location
    python manage.py init_health_token --show    # prints the current token
    python manage.py init_health_token --force   # overwrites an existing token
"""

import os
import secrets
import string

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


TOKEN_FILENAME = 'health_token.txt'
TOKEN_LENGTH = 48
TOKEN_ALPHABET = string.ascii_letters + string.digits


class Command(BaseCommand):
    help = (
        'Initialize the bearer token used to authenticate requests to '
        '/sysinfo/health.json. Stored in BASE_DIR/health_token.txt '
        'alongside secret_key.txt.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--show', action='store_true',
            help='Print the existing token instead of generating a new one.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Overwrite any existing token file.',
        )

    def handle(self, *args, **opts):
        token_file = settings.BASE_DIR / TOKEN_FILENAME

        if opts['show']:
            if not token_file.is_file():
                raise CommandError(f'No token file at {token_file}. Run without --show to create one.')
            self.stdout.write(token_file.read_text().strip())
            return

        if token_file.exists() and not opts['force']:
            raise CommandError(
                f'{token_file} already exists. Use --show to print it, '
                f'or --force to overwrite.'
            )

        token = ''.join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        token_file.write_text(token + '\n')
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass

        self.stdout.write(self.style.SUCCESS(f'Wrote {token_file}'))
        self.stdout.write('')
        self.stdout.write('Token (copy this into the RemoteHost entry on any polling node):')
        self.stdout.write('')
        self.stdout.write(f'  {token}')
        self.stdout.write('')
        self.stdout.write(
            'The endpoint is now active at /sysinfo/health.json. '
            'Clients must send Authorization: Bearer <token>.'
        )

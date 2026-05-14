"""Decrypt a .spenv file using a pact's current-generation envelope key.

Walks a ±window of ticks around the current generation; AEAD tag
validates which one (if any) is correct.
"""

from __future__ import annotations
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from spoeqi.models import Pact


class Command(BaseCommand):
    help = ("Decrypt a .spenv file. Searches ±window ticks around "
            "the pact's current generation.")

    def add_arguments(self, parser):
        parser.add_argument('pact_slug')
        parser.add_argument('input', help='Sealed .spenv file.')
        parser.add_argument('-o', '--output',
                            help='Output path; default: strips .spenv suffix '
                                 'or appends .unsealed.')
        parser.add_argument('--window', type=int, default=20,
                            help='Tick window to search around current generation '
                                 '(default 20 ≈ 3.6 s at the 180 ms/tick default).')

    def handle(self, *args, **opts):
        try:
            pact = Pact.objects.get(slug=opts['pact_slug'])
        except Pact.DoesNotExist:
            raise CommandError(f"No pact with slug {opts['pact_slug']!r}")

        from spoeqi.envelope import unseal, EnvelopeError, current_generation

        in_path = Path(opts['input'])
        if not in_path.exists():
            raise CommandError(f'input file not found: {in_path}')

        if opts['output']:
            out_path = Path(opts['output'])
        elif in_path.suffix == '.spenv':
            out_path = in_path.with_suffix('')
        else:
            out_path = in_path.with_suffix(in_path.suffix + '.unsealed')

        from django.utils import timezone
        now = timezone.now()  # pin once so reported drift matches what unseal used
        g_now = current_generation(pact, now=now)

        sealed = in_path.read_bytes()
        try:
            plaintext, g = unseal(pact, sealed, window=opts['window'], now=now)
        except EnvelopeError as e:
            raise CommandError(
                f'unseal failed: {e}\n'
                f'  (this pact was at generation {g_now} at unseal time)')

        out_path.write_bytes(plaintext)
        drift = g - g_now
        self.stdout.write(self.style.SUCCESS(
            f'unsealed {len(sealed)} B → {len(plaintext)} B'))
        self.stdout.write(
            f'  decrypted at gen={g}; pact was at gen={g_now} when unseal started; '
            f'drift={drift:+d} ticks')
        self.stdout.write(f'  output: {out_path}')

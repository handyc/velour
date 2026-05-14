"""Encrypt a file under a pact's current-generation envelope key.

The sealed file is decryptable only by a party holding the same
pact, within a small window of the current generation at decrypt
time. The generation is not written into the file — decryptor
must use *its* "right now."
"""

from __future__ import annotations
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from spoeqi.models import Pact


class Command(BaseCommand):
    help = ("Encrypt a file under the current-generation envelope key "
            "of a spoeqi pact. Output is a .spenv blob.")

    def add_arguments(self, parser):
        parser.add_argument('pact_slug')
        parser.add_argument('input', help='Plaintext file to seal.')
        parser.add_argument('-o', '--output',
                            help='Output path; default: <input>.spenv')
        parser.add_argument('--generation', type=int, default=None,
                            help='Encrypt to a specific future/past generation '
                                 'instead of "now" (time-capsule mode).')

    def handle(self, *args, **opts):
        try:
            pact = Pact.objects.get(slug=opts['pact_slug'])
        except Pact.DoesNotExist:
            raise CommandError(f"No pact with slug {opts['pact_slug']!r}")

        from spoeqi.envelope import seal, current_generation

        in_path = Path(opts['input'])
        if not in_path.exists():
            raise CommandError(f'input file not found: {in_path}')

        out_path = Path(opts['output']) if opts['output'] else in_path.with_suffix(in_path.suffix + '.spenv')

        plaintext = in_path.read_bytes()
        g = opts['generation'] if opts['generation'] is not None else current_generation(pact)
        sealed = seal(pact, plaintext, generation=g)
        out_path.write_bytes(sealed)

        self.stdout.write(self.style.SUCCESS(
            f'sealed {len(plaintext)} B → {len(sealed)} B at gen={g}'))
        self.stdout.write(f'  output: {out_path}')

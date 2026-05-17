"""manage.py keychain_provision — bake a chosen quine into the
ESP32-S3 firmware tree so the next `pio run -t upload` flashes a
keychain with that seed embedded.

Usage:
    manage.py keychain_provision <quine_pk>
    manage.py keychain_provision <quine_pk> --out PATH

Writes the 16,384-byte seed to ``isolation/artifacts/keychain_quine/
data/seed.bin`` by default, which is the path the platformio config
embeds at build time.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


DEFAULT_OUT = Path('isolation/artifacts/keychain_quine/data/seed.bin')


class Command(BaseCommand):
    help = 'Bake a class-4 quine seed into the ESP32-S3 firmware tree.'

    def add_arguments(self, parser):
        parser.add_argument('quine_pk', type=int,
                                help='ComponentChampion pk of the class-4 '
                                     'quine to embed.')
        parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                                help=f'Output path '
                                     f'(default: {DEFAULT_OUT}).')

    def handle(self, *args, **opts):
        from caformer.models import ComponentChampion
        try:
            c = ComponentChampion.objects.get(
                pk=opts['quine_pk'], component_slug='class4_quine')
        except ComponentChampion.DoesNotExist:
            raise CommandError(
                f'no saved class4_quine champion with pk={opts["quine_pk"]}')
        seed = bytes(c.rules_blob)
        if len(seed) != 16384:
            raise CommandError(
                f'quine #{c.pk} has malformed rules_blob '
                f'({len(seed)} bytes; expected 16,384)')
        out = (Path(settings.BASE_DIR) / opts['out']
                  if not opts['out'].is_absolute() else opts['out'])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(seed)
        sha = hashlib.sha256(seed).hexdigest()
        self.stdout.write(self.style.SUCCESS(
            f'wrote {len(seed):,} bytes → {out}\n'
            f'  seed sha256 = {sha}\n'
            f'  quine #{c.pk}  fit={c.fitness:.4f}\n'
            f'\n'
            f'Next: cd {out.parent.parent} && pio run -t upload'))

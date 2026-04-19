"""List which Argos Translate language pairs are installed.

Useful on a fresh deploy to see whether offline translation is wired up
at all, and to spot missing pairs from the seeded Language list.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from lingua.backends import argos
from lingua.models import Language


class Command(BaseCommand):
    help = 'List Argos-installed language pairs.'

    def handle(self, *args, **opts):
        pairs = sorted(argos._installed_pair_codes())
        if not pairs:
            self.stdout.write(self.style.WARNING(
                'No Argos packages installed. '
                'Run `manage.py lingua_install_pair --from en --to nl` '
                '(or any other pair) to enable offline translation.'
            ))
        else:
            self.stdout.write(f'{len(pairs)} Argos pair(s) installed:')
            for s, t in pairs:
                self.stdout.write(f'  {s} → {t}')

        # Cross-check against Languages that Velour has seeded: any
        # seeded language Argos cannot reach from/to English is worth
        # flagging so the operator knows which ones will need Claude
        # or a manual translation.
        argos_codes = {c for s, t in pairs for c in (s, t)}
        missing = []
        for lang in Language.objects.all():
            mapped = argos._to_argos_code(lang.code)
            if mapped and mapped not in argos_codes:
                missing.append((lang.code, mapped, lang.name))
            elif mapped is None:
                missing.append((lang.code, '?', lang.name))
        if missing:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Seeded languages without an Argos package here:'
            ))
            for code, mapped, name in missing:
                self.stdout.write(f'  {code:8} ({mapped:>3})  {name}')

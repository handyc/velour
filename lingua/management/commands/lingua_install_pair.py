"""Install an Argos Translate language pair.

Usage:
    manage.py lingua_install_pair --from en --to nl

Downloads the OPUS-MT `.argosmodel` file for the pair (~50–200 MB) into
Argos's local package cache. First invocation also refreshes the remote
package index. Safe to re-run; Argos skips installs it already has.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from lingua.backends import argos


class Command(BaseCommand):
    help = 'Install an Argos Translate OPUS-MT package for a language pair.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='src', required=True,
                            help='ISO 639-1 source code, e.g. en')
        parser.add_argument('--to',   dest='tgt', required=True,
                            help='ISO 639-1 target code, e.g. nl')

    def handle(self, *args, src, tgt, **opts):
        if src == tgt:
            raise CommandError('source and target must differ')
        self.stdout.write(f'Installing Argos package {src}→{tgt}…')
        ok = argos.install_pair(src, tgt)
        if not ok:
            raise CommandError(
                f'could not install {src}→{tgt}; check that the pair '
                f'exists at https://www.argosopentech.com/argospm/index/'
            )
        self.stdout.write(self.style.SUCCESS(
            f'installed {src}→{tgt}'
        ))

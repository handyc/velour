"""manage.py alice_analyze_qrpair_vocab <slug> [--ingest]

Reads outputs/*.json from a pulled-back qrpair-vocab bundle and prints
a summary.  With --ingest, also creates/updates QRPair rows + auto-
deploys exact-match pairs into the chat dispatcher.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Summarise (and optionally ingest) a qrpair-vocab bundle '
            'after pull.sh.')

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str,
                            help='bundle slug (e.g. vocab-65k-echo)')
        parser.add_argument('--ingest', action='store_true',
                            help='create QRPair rows + auto-deploy exact ones')
        parser.add_argument('--no-deploy', action='store_true',
                            help='with --ingest, skip auto-deploy step')

    def handle(self, slug, ingest, no_deploy, **_):
        bundle_dir = (Path(settings.BASE_DIR) / 'conduit' / 'alice'
                          / 'bundles' / slug)
        if not bundle_dir.exists():
            raise CommandError(f'bundle not found: {bundle_dir}')

        from conduit.alice.qrpair_vocab import analyse
        from conduit.alice import qrpair_vocab as mod
        summary = analyse(bundle_dir)
        if 'error' in summary:
            raise CommandError(summary['error'])
        self.stdout.write('--- summary ---')
        for k, v in summary.items():
            if k == 'failures':
                if v:
                    self.stdout.write(f'  failures: {len(v)}')
                    for f in v[:5]:
                        self.stdout.write(f'    {f}')
                continue
            self.stdout.write(f'  {k}: {v}')

        if ingest:
            self.stdout.write('--- ingesting QRPair rows ---')
            r = mod.ingest(bundle_dir, auto_deploy=not no_deploy)
            for k, v in r.items():
                self.stdout.write(f'  {k}: {v}')
            self.stdout.write(self.style.SUCCESS(
                f'done — {r["deployed"]} pairs now reachable via '
                'the chat dispatcher.'))

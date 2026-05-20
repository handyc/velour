"""Ingest an ALICE board128 bundle's outputs into the QRPair DB.

  manage.py alice_ingest_board128 sonnets-v1
  manage.py alice_ingest_board128 sonnets-v1 --analyse-only
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Read an ALICE board128 bundle\'s outputs/ + merge into QRPair.')

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str)
        parser.add_argument('--analyse-only', action='store_true')

    def handle(self, *, slug, analyse_only, **opts):
        from conduit.alice.caformer_board128 import analyse, ingest

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        bundle_dir = repo_root / 'conduit' / 'alice' / 'bundles' / slug
        if not bundle_dir.is_dir():
            raise CommandError(f'no bundle at {bundle_dir}')

        a = analyse(bundle_dir)
        print(f'=== analyse {slug} ===')
        for k, v in a.items():
            if isinstance(v, dict) and len(v) > 12:
                print(f'  {k}: {len(v)} entries (truncated)')
                for kk, vv in list(v.items())[:6]:
                    print(f'    {kk}: {vv}')
                print('    …')
            else:
                print(f'  {k}: {v}')

        if analyse_only:
            return

        print(f'\n=== ingesting ===')
        r = ingest(bundle_dir)
        for k, v in r.items():
            print(f'  {k}: {v}')

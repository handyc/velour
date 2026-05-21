"""Ingest an ALICE cell8 bundle's outputs into the live QRPair DB.

  manage.py alice_ingest_cell8 cell8-batch-A
  manage.py alice_ingest_cell8 cell8-batch-A --analyse-only
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Read an ALICE bundle\'s outputs/ + merge into QRPair.')

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str)
        parser.add_argument('--analyse-only', action='store_true',
                              help='print summary without DB writes')
        parser.add_argument('--verify', action='store_true',
                              help='re-derive byte_matched per record by '
                                     'cascading the rules forward.  Pre-fix '
                                     'cell8 bundles needed this to undo the '
                                     'byte_matched=True-by-default bug; new '
                                     'bundles set the flag correctly but '
                                     '--verify still works as a sanity check.')

    def handle(self, *, slug, analyse_only, verify, **opts):
        from conduit.alice.caformer_cell8 import analyse, ingest

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        bundle_dir = repo_root / 'conduit' / 'alice' / 'bundles' / slug
        if not bundle_dir.is_dir():
            raise CommandError(f'no bundle at {bundle_dir}')

        a = analyse(bundle_dir)
        print(f'=== analyse {slug} ===')
        for k, v in a.items():
            print(f'  {k}: {v}')

        if analyse_only:
            return

        print(f'\n=== ingesting{" (verify)" if verify else ""} ===')
        r = ingest(bundle_dir, verify=verify)
        for k, v in r.items():
            print(f'  {k}: {v}')

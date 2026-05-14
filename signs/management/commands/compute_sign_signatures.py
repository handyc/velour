"""Backfill Sign.signature for the similarity engine.

Walks every Sign, pulls its frames in order, computes a fixed-size
L2-normalised signature, and writes it to ``Sign.signature``.
Idempotent — re-running just overwrites with the latest value.
"""

from __future__ import annotations
import time

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from signs.models import Sign
from signs import similarity


class Command(BaseCommand):
    help = ('Compute the pose-signature for every Sign in the corpus '
            '(used by the similarity engine).')

    def add_arguments(self, parser):
        parser.add_argument('--only-missing', action='store_true',
                            help='Skip Signs that already have a signature.')
        parser.add_argument('--batch-size', type=int, default=200,
                            help='Commit every N signs (default 200).')

    def handle(self, *args, **opts):
        with connection.cursor() as c:
            c.execute('PRAGMA journal_mode = WAL')
            c.execute('PRAGMA busy_timeout = 60000')

        qs = Sign.objects.all()
        if opts['only_missing']:
            qs = qs.filter(signature__isnull=True)
        total = qs.count()
        self.stdout.write(self.style.NOTICE(
            f'computing signatures for {total} signs '
            f'(k={similarity.K_SIGNATURE_KEYFRAMES}, '
            f'pose_dim={similarity.POSE_DIM}, '
            f'signature_dim={similarity.SIGNATURE_DIM})'))

        t0 = time.monotonic()
        n_done = 0
        n_empty = 0
        batch: list[Sign] = []
        for sign in qs.iterator():
            frame_rotations = list(
                sign.frames.order_by('index').values_list(
                    'cylinder_rotations', flat=True))
            sig = similarity.compute_signature(frame_rotations)
            if not sig:
                n_empty += 1
            sign.signature = sig
            batch.append(sign)
            if len(batch) >= opts['batch_size']:
                with transaction.atomic():
                    Sign.objects.bulk_update(batch, ['signature'])
                n_done += len(batch)
                batch = []
                elapsed = time.monotonic() - t0
                self.stdout.write(
                    f'  [{n_done:4d}/{total}] {elapsed:.1f}s elapsed · '
                    f'{n_done/elapsed:.1f} signs/s')
        if batch:
            with transaction.atomic():
                Sign.objects.bulk_update(batch, ['signature'])
            n_done += len(batch)

        self.stdout.write(self.style.SUCCESS(
            f'\ncomputed {n_done} signatures '
            f'(empty: {n_empty}) in {time.monotonic() - t0:.1f}s'))

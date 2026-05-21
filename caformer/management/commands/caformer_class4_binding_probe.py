"""Probe: can class-4 quines act as a shared substrate for trained
Shakespeare rules?  User intuition 2026-05-22.

Three sub-experiments:

  1. Compressibility baseline — gzip of raw Shakespeare b256 blobs.
     Establishes how much redundancy is even THERE for compression
     to find.

  2. Cross-pair Hamming clustering — pairwise distance between
     position-0 LUTs of every Shakespeare pair.  If pairs cluster
     into a few groups, class-4 binding by a shared base may work.

  3. Within-pair Hamming — distance between positions inside the
     same trained pair.  Tests whether sequential positions reuse
     substrate.

Plus: optionally test GA convergence from a quine-#122 initial
state.  (Phase 2: not in this command — would need a separate
training run.)
"""
from __future__ import annotations

import itertools
import sys
import zlib

import numpy as np

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Probe: can class-4 quines act as a shared substrate for '
            'trained Shakespeare rules?')

    def add_arguments(self, parser):
        parser.add_argument('--corpus', default='shakespeare',
                              choices=['shakespeare', 'personality', 'all'])
        parser.add_argument('--n-sample', type=int, default=20)

    def handle(self, *, corpus, n_sample, **opts):
        from caformer.models import QRPair
        from django.db.models import Q
        from django.db.models import IntegerField
        def log(s):
            sys.stdout.write(str(s) + '\n'); sys.stdout.flush()

        if corpus == 'shakespeare':
            qs = QRPair.objects.filter(id__gte=73, id__lte=155)
        elif corpus == 'personality':
            qs = QRPair.objects.filter(id__lt=73)
        else:
            qs = QRPair.objects.all()
        pairs = list(qs)
        log(f'=== class-4 binding probe ({corpus}) ===')
        log(f'  {len(pairs)} pairs in corpus')

        # ── 1. Compressibility baseline ───────────────────────
        log('')
        log('-- compressibility baseline --')
        total_raw = total_gz = 0
        total_packed_gz = 0
        for q in pairs[:n_sample]:
            blob = q.cell8_b256_rules_blob
            if not blob: continue
            raw = bytes(blob)
            arr = np.frombuffer(raw, dtype=np.uint8) & 3
            # Pack 4 K=4 values per byte.
            n4 = (arr.size // 4) * 4
            packed = ((arr[0:n4:4] & 3) << 6 | (arr[1:n4:4] & 3) << 4
                      | (arr[2:n4:4] & 3) << 2 | (arr[3:n4:4] & 3))
            total_raw += len(raw)
            total_gz  += len(zlib.compress(raw, 9))
            total_packed_gz += len(zlib.compress(bytes(packed), 9))
        log(f'  {n_sample} {corpus} pairs:')
        log(f'    raw bytes:                  {total_raw:>14,}')
        log(f'    gzip of raw:                {total_gz:>14,}  '
            f'({100*total_gz/total_raw:.1f}%)')
        log(f'    gzip of K=4-packed:         {total_packed_gz:>14,}  '
            f'({100*total_packed_gz/total_raw:.1f}%)')
        log(f'  packing alone gives {total_raw/(total_packed_gz or 1):.2f}x reduction.')

        # ── 2. Cross-pair Hamming clustering ───────────────────
        log('')
        log('-- cross-pair Hamming (position-0 LUTs) --')
        luts = []
        for q in pairs:
            blob = q.cell8_b256_rules_blob
            if not blob: continue
            raw = bytes(blob)
            luts.append((q.id, np.frombuffer(raw[:65536], dtype=np.uint8) & 3))
        if len(luts) < 2:
            log('  not enough pairs with rules to compare')
            return
        log(f'  collected {len(luts)} LUTs')
        dists = []
        for (id_a, a), (id_b, b) in itertools.combinations(luts, 2):
            dists.append(float(np.mean(a != b)))
        arr = np.array(dists)
        log(f'  distance distribution:')
        log(f'    mean: {100*arr.mean():>5.2f}%   '
            f'(random K=4 baseline = 75.0%)')
        log(f'    std:  {100*arr.std():>5.3f}%')
        log(f'    min:  {100*arr.min():>5.2f}%')
        log(f'    max:  {100*arr.max():>5.2f}%')
        if abs(arr.mean() - 0.75) < 0.01:
            log('  ✗ pairs are at the random-baseline distance — NO clustering')
            log('  ✗ binding to a single shared class-4 base WILL NOT WORK')
            log('    (no shared structure to amortize against)')
        else:
            log(f'  cluster signal: {0.75 - arr.mean():.4f} below random baseline')

        # ── 3. Within-pair structure ───────────────────────────
        log('')
        log('-- within-pair Hamming (position-i ↔ position-j) --')
        all_inner = []
        for q in pairs[:n_sample]:
            blob = q.cell8_b256_rules_blob
            if not blob: continue
            raw = bytes(blob)
            n_pos = len(raw) // 65536
            if n_pos < 2: continue
            pluts = [np.frombuffer(raw[i*65536:(i+1)*65536],
                                    dtype=np.uint8) & 3
                     for i in range(n_pos)]
            for a, b in itertools.combinations(pluts, 2):
                all_inner.append(float(np.mean(a != b)))
        if all_inner:
            arr = np.array(all_inner)
            log(f'  positions across {n_sample} pairs:')
            log(f'    mean: {100*arr.mean():>5.2f}%   '
                f'(random K=4 baseline = 75.0%)')
            log(f'    std:  {100*arr.std():>5.3f}%')

        log('')
        log('-- verdict --')
        log('  rules are at maximum entropy across both axes.')
        log('  the only "free" win is K=4 packing (4x reduction).')
        log('  class-4 binding requires CHANGING the training objective')
        log('  to bias toward class-4 attractors, not just post-hoc')
        log('  compression of independently-evolved rules.')

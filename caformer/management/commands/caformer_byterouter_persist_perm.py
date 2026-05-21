"""Recompute + persist the byte_router's trained permutation.

The original training run wrote LUTs to disk but didn't save the
permutation (introduced after that training).  Compute the
permutation from the existing LUTs against router_corpus.CORPUS and
write it as permutation.json in the artifact dir.

Optionally also promote the artifact (e.g. byte_router_full →
byte_router_v1) so the default get_router() loader picks it up.

  manage.py caformer_byterouter_persist_perm
  manage.py caformer_byterouter_persist_perm --in-dir .artifacts/byte_router_full \\
      --promote-to .artifacts/byte_router_v1
"""
from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Recompute the byte_router permutation against the router '
            'corpus and persist it alongside the LUTs.')

    def add_arguments(self, parser):
        parser.add_argument('--in-dir',  type=str,
                              default='.artifacts/byte_router_full',
                              help='source artifact dir (must have LUTs)')
        parser.add_argument('--promote-to', type=str, default='',
                              help='if set, also copy the artifact (LUTs '
                                     '+ meta + permutation) here so '
                                     'get_router() picks it up by default')
        parser.add_argument('--n-bytes', type=int, default=4)

    def handle(self, *, in_dir, promote_to, n_bytes, **opts):
        from caformer.byte_router import (load_router,
                                                    save_router,
                                                    compute_permutation_for_corpus)
        from caformer.router_corpus import CORPUS, CATEGORY_NAMES, by_category

        src = Path(settings.BASE_DIR) / in_dir
        if not (src / 'meta.json').exists():
            self.stdout.write(self.style.ERROR(
                f'no meta.json at {src}'))
            return
        self.stdout.write(f'loading byte_router from {src} …')
        router = load_router(src)
        if router.permutation:
            self.stdout.write(
                f'  (existing permutation: {len(router.permutation)} entries — '
                f'will overwrite)')
        self.stdout.write(f'computing permutation against {len(CORPUS)} '
                          f'corpus rows with n_bytes={n_bytes} …')
        mapping, n_correct = compute_permutation_for_corpus(
            router, CORPUS, n_bytes=n_bytes)
        accuracy = n_correct / max(1, len(CORPUS))
        self.stdout.write(
            f'  {len(mapping)} distinct output bytes; '
            f'best-permutation accuracy {n_correct}/{len(CORPUS)} '
            f'({accuracy:.3f})')

        # Per-category breakdown.
        for cat, names in by_category().items():
            n = 0
            ok = 0
            for prompt, target in CORPUS:
                if target != cat: continue
                n += 1
                agg = router._aggregate_byte(prompt, n_bytes)
                if mapping.get(agg) == cat: ok += 1
            self.stdout.write(
                f'    {CATEGORY_NAMES[cat]:12}: {ok:>2}/{n:<2} '
                f'({100*ok/max(1,n):5.1f}%)')

        # Persist back to the source dir.
        router.permutation = mapping
        router.n_bytes_train = n_bytes
        save_router(router, src)
        self.stdout.write(self.style.SUCCESS(
            f'permutation written to {src}/permutation.json'))

        if promote_to:
            dst = Path(settings.BASE_DIR) / promote_to
            dst.mkdir(parents=True, exist_ok=True)
            for name in ('meta.json', 'permutation.json'):
                p = src / name
                if p.exists():
                    shutil.copy2(p, dst / name)
            for l in range(4):
                for b in range(4):
                    lut = src / f'layer_{l}_board_{b}.lut'
                    if lut.exists():
                        shutil.copy2(lut, dst / lut.name)
            # Clear the get_router cache so the next load picks it up.
            from caformer import byte_router as _br
            _br._CACHE.clear()
            self.stdout.write(self.style.SUCCESS(
                f'promoted to {dst}'))

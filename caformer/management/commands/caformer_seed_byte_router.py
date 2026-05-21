"""Seed a random-LUT byte_router so the harness has a deterministic
artifact to load.  Phase 1 has no training; this command just writes
random LUTs to disk under a stable seed so behaviour is reproducible
across server restarts."""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed a byte_router with random LUTs (Phase 1).'

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=0xBE7E_F011)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/byte_router_v1')

    def handle(self, *, seed, out_dir, **opts):
        from pathlib import Path
        from caformer.byte_router import (ByteRouter, save_router,
                                                    _random_layer_luts,
                                                    N_LAYERS, N_BOARDS)
        out = Path(settings.BASE_DIR) / out_dir
        self.stdout.write(f'Seeding byte_router into {out} '
                          f'({N_LAYERS} layers × {N_BOARDS} boards, '
                          f'seed={hex(seed)})')
        luts = _random_layer_luts(seed=seed)
        router = ByteRouter(luts)
        path = save_router(router, out)
        # Sanity probe.
        for s in ('h', 'A', '?', ' '):
            r = router.route_prompt(s)
            from caformer.byte_router import path_label
            self.stdout.write(
                f'  probe {s!r}: byte={r["first_byte"]:#04x} '
                f'→ fingerprint {path_label(r["fingerprint"])}')
        self.stdout.write(self.style.SUCCESS(f'Saved to {path}'))

"""Hill-climb the Mondrian artwork LUT toward a strict K=4 quine.

Starts from the posterised Mondrian *Composition with Red Blue Yellow*
seed (SR=0.7007 — the strongest of 27 famous-artwork seeds tested by
test_artwork_quines).  Random single-byte mutations are accepted iff
sr_strict improves.  Periodically logs progress; saves the best LUT to
.artifacts/mondrian_climb/.

Usage::

    manage.py spoeqi_mondrian_climb
    manage.py spoeqi_mondrian_climb --iters 50000 --workers 1
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


MONDRIAN_CACHE_SHA = 'a29dcc1be576df0c'


def _load_seed() -> bytes:
    from spoeqi import image_quine as iq
    cache = Path(settings.BASE_DIR) / '.artifacts' / 'artwork_cache' / f'{MONDRIAN_CACHE_SHA}.jpg'
    img_bytes = cache.read_bytes()
    return iq.image_to_rule(img_bytes).rule_bytes


def _score(lut: bytes) -> dict:
    from spoeqi import image_quine as iq
    return iq.score_rule(lut)


def _mutate(lut: bytes, rng: random.Random, n_flips: int) -> bytes:
    arr = bytearray(lut)
    n = len(arr)
    for _ in range(n_flips):
        idx = rng.randrange(n)
        cur = arr[idx] & 3
        new = rng.randint(0, 3)
        while new == cur:
            new = rng.randint(0, 3)
        arr[idx] = new
    return bytes(arr)


class Command(BaseCommand):
    help = 'Hill-climb the Mondrian artwork LUT toward strict-SR quine.'

    def add_arguments(self, parser):
        parser.add_argument('--iters', type=int, default=20000)
        parser.add_argument('--flips-min', type=int, default=1)
        parser.add_argument('--flips-max', type=int, default=8)
        parser.add_argument('--seed', type=int, default=0xC0FFEE)
        parser.add_argument('--save-every', type=int, default=200)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/mondrian_climb')
        parser.add_argument('--target-sr', type=float, default=0.99)
        parser.add_argument('--seed-file', type=str, default='',
                              help='Use this 16,384-byte LUT as the cold '
                                     'start instead of the Mondrian seed. '
                                     'Used to hill-climb arbitrary class-4 '
                                     'candidates (e.g. fractal-derived).')

    def handle(self, *, iters, flips_min, flips_max, seed,
                 save_every, out_dir, target_sr, seed_file, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        if seed_file:
            log(f'Loading seed LUT from {seed_file} ...')
            seed_lut = Path(seed_file).read_bytes()
            if len(seed_lut) != 16384:
                raise ValueError(
                    f'seed-file must be exactly 16,384 bytes; '
                    f'got {len(seed_lut)}')
        else:
            log('Loading Mondrian seed LUT...')
            seed_lut = _load_seed()
        s0 = _score(seed_lut)
        log(f'  seed: SR={s0["sr_strict"]:.4f} arbσ={s0["sr_arbsigma"]:.4f} '
            f'cls={s0["wolfram_class"]} c4={s0["c4"]:.3f}')

        (out / 'seed.lut').write_bytes(seed_lut)
        (out / 'seed_scores.json').write_text(json.dumps(s0, indent=2))

        rng = random.Random(seed)
        best_lut = seed_lut
        best_sr = float(s0['sr_strict'])
        best_scores = s0
        n_accept = 0
        n_total = 0
        t0 = time.time()

        log(f'climbing for {iters} iters (target SR={target_sr})...')
        for it in range(iters):
            n_flips = rng.randint(flips_min, flips_max)
            cand = _mutate(best_lut, rng, n_flips)
            try:
                sc = _score(cand)
            except Exception as e:
                log(f'  skip (score fail @ it {it}: {e})')
                continue
            n_total += 1
            sr = float(sc['sr_strict'])
            if sr > best_sr:
                best_sr = sr
                best_lut = cand
                best_scores = sc
                n_accept += 1
                log(f'  it {it:>6}: ACCEPT SR={sr:.4f} arbσ={sc["sr_arbsigma"]:.4f} '
                    f'cls={sc["wolfram_class"]} c4={sc["c4"]:.3f} '
                    f'flips={n_flips} ({n_accept}/{n_total} accept, '
                    f'{time.time()-t0:.0f}s)')
            if (it + 1) % save_every == 0:
                (out / 'best.lut').write_bytes(best_lut)
                (out / 'best_scores.json').write_text(
                    json.dumps(best_scores, indent=2))
                log(f'  · it {it+1}: best SR={best_sr:.4f} '
                    f'({n_accept}/{n_total} accept, {time.time()-t0:.0f}s)')
            if best_sr >= target_sr:
                log(f'  >>> hit target SR={target_sr}, stopping early')
                break

        (out / 'best.lut').write_bytes(best_lut)
        (out / 'best_scores.json').write_text(json.dumps(best_scores, indent=2))
        log('')
        log(f'=== Done ===')
        log(f'  iters:      {n_total}')
        log(f'  accepted:   {n_accept}')
        log(f'  seed SR:    {s0["sr_strict"]:.4f}')
        log(f'  final SR:   {best_sr:.4f}')
        log(f'  delta SR:   {best_sr - s0["sr_strict"]:+.4f}')
        log(f'  wall:       {time.time()-t0:.0f}s')
        log(f'  saved:      {out}/best.lut')

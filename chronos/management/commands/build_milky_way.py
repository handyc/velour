"""Generate a procedural scatter of dim points along the galactic
plane and write to static/chronos/milky_way.json.

Each point is (RA, Dec, brightness). The Aether sky scene fetches
this once at world load and renders it as a faint Points cloud
parallel to the bright-stars catalog. Brightness is baked in (peaks
near the galactic center in Sagittarius, decays with longitude away
from l=0 and Gaussian-decays with galactic latitude). Points are
drawn deterministically by seeding the RNG so the same dot pattern
ships every time and visual diffs are reproducible.

Usage:

    python manage.py build_milky_way
    python manage.py build_milky_way --count 2000 --seed 42
"""

import json
import math
import random
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


# Galactic-to-ICRS (J2000) rotation matrix. Verify with the galactic
# centre (l=0, b=0) → (RA 266.405°, Dec −28.936°). Source: IAU
# definition / Wikipedia "Galactic coordinate system".
M_GAL_TO_EQ = (
    (-0.0548755604, +0.4941094279, -0.8676661490),  # ex coefficients
    (-0.8734370902, -0.4448296300, -0.1980763734),  # ey coefficients
    (-0.4838350155, +0.7469822445, +0.4559837762),  # ez coefficients
)


def gal_to_eq(l_deg, b_deg):
    """Galactic (l, b) → ICRS (RA, Dec) in degrees."""
    l = math.radians(l_deg)
    b = math.radians(b_deg)
    gx = math.cos(b) * math.cos(l)
    gy = math.cos(b) * math.sin(l)
    gz = math.sin(b)
    M = M_GAL_TO_EQ
    ex = M[0][0]*gx + M[0][1]*gy + M[0][2]*gz
    ey = M[1][0]*gx + M[1][1]*gy + M[1][2]*gz
    ez = M[2][0]*gx + M[2][1]*gy + M[2][2]*gz
    dec = math.degrees(math.asin(max(-1.0, min(1.0, ez))))
    ra = math.degrees(math.atan2(ey, ex)) % 360.0
    return ra, dec


def _gauss(rng, sigma):
    """Box-Muller; trim outliers > 4 sigma to keep the band tight."""
    while True:
        u1 = max(rng.random(), 1e-12)
        u2 = rng.random()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        if abs(z) <= 4:
            return z * sigma


class Command(BaseCommand):
    help = 'Generate static/chronos/milky_way.json — galactic-plane '\
           'point scatter for the Aether sky scene.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=1500,
                            help='Number of points to generate.')
        parser.add_argument('--seed',  type=int, default=20260427,
                            help='RNG seed (default ships a stable scatter).')

    def handle(self, *args, **opts):
        # Sanity: galactic centre should map near Sagittarius.
        ra_gc, dec_gc = gal_to_eq(0, 0)
        if not (265.5 < ra_gc < 267.5 and -29.5 < dec_gc < -28.5):
            raise RuntimeError(
                f'Galactic→equatorial transform is wrong: '
                f'GC mapped to ({ra_gc:.2f}°, {dec_gc:.2f}°), '
                f'expected (~266.4°, -28.94°). Check rotation matrix.'
            )

        rng = random.Random(opts['seed'])
        n = opts['count']
        points = []
        for _ in range(n):
            # Galactic longitude: uniform [0, 360), but with brightness
            # falloff toward the anti-centre. Latitude: tight Gaussian.
            l = rng.random() * 360.0
            b = _gauss(rng, 4.5)  # sigma = 4.5° — most of the band ±10°

            ra, dec = gal_to_eq(l, b)

            # Brightness: peaks at l=0 (Sgr A*), tapers toward l=180°.
            # Cosine of angular distance along the band approximates
            # the dust + bulge density profile crudely.
            dl = min(l, 360.0 - l)  # 0..180, 0 = galactic centre
            longitude_factor = 0.25 + 0.55 * math.cos(math.radians(dl))
            latitude_factor = math.exp(-abs(b) / 8.0)
            brightness = max(0.05, longitude_factor * latitude_factor)

            points.append({
                'ra':   round(ra, 3),
                'dec':  round(dec, 3),
                'b':    round(brightness, 3),
            })

        out_dir = Path(settings.BASE_DIR) / 'static' / 'chronos'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / 'milky_way.json'
        out_path.write_text(json.dumps({
            'description': 'Procedural Milky Way point scatter for the '
                           'Aether sky scene. Each point is (ra, dec, '
                           'brightness 0..1) on the celestial sphere.',
            'count':  n,
            'seed':   opts['seed'],
            'points': points,
        }, separators=(',', ':')))

        self.stdout.write(self.style.SUCCESS(
            f'Wrote {out_path} · {n} points · '
            f'GC sanity: l=0 b=0 → RA={ra_gc:.2f}°, Dec={dec_gc:+.2f}° · '
            f'{out_path.stat().st_size} bytes.'
        ))

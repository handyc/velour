"""Build static/chronos/constellation_lines.json from a hand-curated
list of stick figures for the most recognisable constellations.

Each constellation is encoded by a list of (Bayer-letter or proper
name, approximate RA/Dec) vertex tuples plus a list of (i, j) edge
pairs into that vertex list. We then resolve every vertex to a
Hipparcos number by closest-RA/Dec match in static/chronos/
bright_stars.json — same catalog the Aether sky script already
ships and uses for star positions. The output JSON references stars
by HIP, so the JS can position constellation lines by looking up
the same star coordinates that drive the Points geometry.

Idempotent: re-running rebuilds the JSON in place. Safe to ship
the output to git.

Usage:

    python manage.py build_constellations
        Rebuild static/chronos/constellation_lines.json.

    python manage.py build_constellations --verbose
        Print every vertex resolution for debugging.
"""

import json
import math
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


# Curated stick figures. Each entry: (constellation_name, abbr,
# vertices = [(label, ra_deg_approx, dec_deg_approx), ...],
# edges = [(i, j), ...]).
#
# RA/Dec approximations are to ~0.5° precision, sourced from
# Wikipedia infoboxes. The closest-match step in resolve_hip()
# rejects matches > 1.5° away, so a rough number is fine.
CONSTELLATIONS = [
    # Orion
    ('Orion', 'Ori', [
        ('Betelgeuse',  88.79,  +7.41),  # alpha
        ('Bellatrix',   81.28,  +6.35),  # gamma
        ('Mintaka',     83.00,  -0.30),  # delta
        ('Alnilam',     84.05,  -1.20),  # epsilon
        ('Alnitak',     85.19,  -1.94),  # zeta
        ('Saiph',       86.94,  -9.67),  # kappa
        ('Rigel',       78.63,  -8.20),  # beta
    ], [
        (0, 1),  # shoulders: Betelgeuse - Bellatrix
        (0, 4),  # right side: Betelgeuse - Alnitak
        (1, 2),  # left side: Bellatrix - Mintaka
        (2, 3),  # belt 1: Mintaka - Alnilam
        (3, 4),  # belt 2: Alnilam - Alnitak
        (4, 5),  # right leg: Alnitak - Saiph
        (2, 6),  # left leg: Mintaka - Rigel
    ]),

    # Ursa Major / Big Dipper
    ('Ursa Major', 'UMa', [
        ('Dubhe',     165.93, +61.75),  # alpha
        ('Merak',     165.46, +56.38),  # beta
        ('Phecda',    178.46, +53.69),  # gamma
        ('Megrez',    183.86, +57.03),  # delta
        ('Alioth',    193.51, +55.96),  # epsilon
        ('Mizar',     200.98, +54.93),  # zeta
        ('Alkaid',    206.89, +49.31),  # eta
    ], [
        (0, 1),  # cup outer
        (1, 2),  # cup bottom
        (2, 3),  # cup other
        (3, 0),  # cup top (closes the bowl)
        (3, 4),  # handle 1
        (4, 5),  # handle 2
        (5, 6),  # handle 3
    ]),

    # Cassiopeia (the W)
    ('Cassiopeia', 'Cas', [
        ('Caph',        2.30, +59.15),  # beta
        ('Schedar',     10.13, +56.54),  # alpha
        ('Cih',         14.18, +60.72),  # gamma
        ('Ruchbah',     21.45, +60.24),  # delta
        ('Segin',       28.60, +63.67),  # epsilon
    ], [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
    ]),

    # Cygnus / Northern Cross
    ('Cygnus', 'Cyg', [
        ('Deneb',     310.36, +45.28),  # alpha — head of cross (top)
        ('Sadr',      305.55, +40.26),  # gamma — centre
        ('Albireo',   292.68, +27.96),  # beta — foot
        ('Fawaris',   296.85, +45.13),  # delta — left wingtip
        ('Aljanah',   311.55, +33.97),  # epsilon — right wingtip
    ], [
        (0, 1),  # top to centre
        (1, 2),  # centre to foot (long axis)
        (1, 3),  # centre to left wing
        (1, 4),  # centre to right wing
    ]),

    # Lyra
    ('Lyra', 'Lyr', [
        ('Vega',      279.23, +38.78),  # alpha
        ('Sheliak',   282.52, +33.36),  # beta
        ('Sulafat',   284.73, +32.69),  # gamma
        ('Zeta1 Lyr', 281.19, +37.61),  # zeta1
    ], [
        (0, 3),  # Vega to Zeta
        (3, 1),  # Zeta to Sheliak
        (1, 2),  # Sheliak to Sulafat
        (2, 0),  # Sulafat back to Vega — completes lyre body
    ]),

    # Aquila — eagle
    ('Aquila', 'Aql', [
        ('Altair',    297.70, +8.87),   # alpha
        ('Tarazed',   296.57, +10.61),  # gamma
        ('Alshain',   298.83, +6.41),   # beta
        ('Theta Aql', 302.83, -0.82),   # theta
        ('Zeta Aql',  286.35, +13.86),  # zeta
    ], [
        (1, 0),  # Tarazed - Altair
        (0, 2),  # Altair - Alshain (head triplet)
        (0, 3),  # Altair - Theta (body down)
        (0, 4),  # Altair - Zeta (wing left)
    ]),

    # Bootes (the kite)
    ('Bootes', 'Boo', [
        ('Arcturus',  213.92, +19.18),  # alpha
        ('Izar',      221.25, +27.07),  # epsilon
        ('Seginus',   218.02, +38.31),  # gamma
        ('Nekkar',    225.49, +40.39),  # beta
        ('Delta Boo', 228.40, +33.31),  # delta
        ('Eta Boo',   208.67, +18.39),  # eta
    ], [
        (0, 5),  # Arcturus - Eta
        (5, 2),  # Eta - Seginus
        (2, 3),  # Seginus - Nekkar
        (3, 4),  # Nekkar - Delta
        (4, 1),  # Delta - Izar
        (1, 0),  # Izar - Arcturus (closes kite)
    ]),

    # Leo (sickle + triangle)
    ('Leo', 'Leo', [
        ('Regulus',   152.09, +11.97),  # alpha — base of sickle / front leg
        ('Eta Leo',   151.83, +16.76),  # eta
        ('Algieba',   154.99, +19.84),  # gamma
        ('Adhafera',  154.17, +23.42),  # zeta
        ('Rasalas',   148.19, +26.01),  # mu
        ('Algenubi',  146.31, +23.77),  # epsilon
        ('Denebola',  177.27, +14.57),  # beta — tail
        ('Zosma',     168.53, +20.52),  # delta
        ('Chertan',   168.56, +15.43),  # theta
    ], [
        (0, 1),  # sickle base
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),  # sickle top hook
        (5, 3),  # close sickle into a hook (zeta back)
        (0, 8),  # Regulus - Chertan (front to belly)
        (8, 7),  # Chertan - Zosma (belly to back)
        (7, 6),  # Zosma - Denebola (back to tail)
        (8, 6),  # Chertan - Denebola (closes triangle)
    ]),

    # Scorpius (heart + tail; scorpius is far south, often below
    # northern-temperate horizons)
    ('Scorpius', 'Sco', [
        ('Acrab',     241.36, -19.81),  # beta
        ('Dschubba',  240.08, -22.62),  # delta
        ('Pi Sco',    239.71, -26.11),  # pi
        ('Antares',   247.35, -26.43),  # alpha
        ('Tau Sco',   248.97, -28.22),  # tau
        ('Epsilon',   252.54, -34.29),  # epsilon
        ('Mu1 Sco',   252.97, -38.05),  # mu1
        ('Zeta2 Sco', 253.99, -42.36),  # zeta2
        ('Eta Sco',   258.04, -43.24),  # eta
        ('Theta',     264.33, -42.99),  # theta
        ('Iota1',     266.89, -40.13),  # iota
        ('Kappa',     265.62, -39.03),  # kappa
        ('Shaula',    263.40, -37.10),  # lambda
    ], [
        (0, 1),  # claws: Acrab - Dschubba
        (1, 2),  # claw down: Dschubba - Pi
        (1, 3),  # body: Dschubba - Antares
        (3, 4),  # Antares - Tau
        (4, 5),  # tau - epsilon
        (5, 6),
        (6, 7),
        (7, 8),
        (8, 9),
        (9, 10),
        (10, 11),
        (11, 12),  # … - Shaula (stinger)
    ]),

    # Crux / Southern Cross
    ('Crux', 'Cru', [
        ('Acrux',     186.65, -63.10),  # alpha
        ('Mimosa',    191.93, -59.69),  # beta
        ('Gacrux',    187.79, -57.11),  # gamma
        ('Imai',      183.79, -58.75),  # delta
    ], [
        (0, 2),  # alpha - gamma (long axis)
        (1, 3),  # beta - delta (short axis)
    ]),

    # Canis Major
    ('Canis Major', 'CMa', [
        ('Sirius',    101.29, -16.71),  # alpha
        ('Mirzam',     95.67, -17.96),  # beta — snout
        ('Adhara',    104.66, -28.97),  # epsilon
        ('Wezen',     107.10, -26.39),  # delta
        ('Aludra',    111.02, -29.30),  # eta
    ], [
        (1, 0),  # snout
        (0, 2),  # head to front haunch
        (2, 3),  # haunch to back
        (3, 4),  # back to tail tip
    ]),

    # Taurus (Hyades V + horns)
    ('Taurus', 'Tau', [
        ('Aldebaran',  68.98, +16.51),  # alpha — eye of bull
        ('Hyadum I',   64.95, +15.63),  # gamma
        ('Delta1 Tau', 67.16, +17.54),  # delta
        ('Epsilon',    67.15, +19.18),  # epsilon
        ('Elnath',     81.57, +28.61),  # beta — north horn
        ('Zeta Tau',   84.41, +21.14),  # zeta — south horn
    ], [
        (1, 2),  # V left arm
        (2, 0),  # V to Aldebaran
        (3, 0),  # epsilon to Aldebaran
        (0, 4),  # Aldebaran - Elnath (north horn)
        (0, 5),  # Aldebaran - Zeta (south horn)
    ]),
]


def angular_distance_deg(ra1, dec1, ra2, dec2):
    """Great-circle distance on the celestial sphere."""
    r1, d1 = math.radians(ra1), math.radians(dec1)
    r2, d2 = math.radians(ra2), math.radians(dec2)
    cosc = (math.sin(d1) * math.sin(d2)
            + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2))
    return math.degrees(math.acos(max(-1, min(1, cosc))))


class Command(BaseCommand):
    help = 'Build static/chronos/constellation_lines.json from curated '\
           'stick figures.'

    def add_arguments(self, parser):
        parser.add_argument('--verbose', action='store_true')

    def handle(self, *args, **opts):
        verbose = opts['verbose']
        cat_path = Path(settings.BASE_DIR) / 'static' / 'chronos' \
                   / 'bright_stars.json'
        out_path = Path(settings.BASE_DIR) / 'static' / 'chronos' \
                   / 'constellation_lines.json'
        if not cat_path.exists():
            self.stdout.write(self.style.ERROR(
                f'{cat_path} missing. Run the Phase 2 seed step that '
                f'generates the bright stars catalog first.'
            ))
            return

        catalog = json.loads(cat_path.read_text())['stars']

        def resolve(ra, dec):
            best = None
            best_d = 999.0
            for s in catalog:
                d = angular_distance_deg(ra, dec, s['ra'], s['dec'])
                if d < best_d:
                    best_d = d
                    best = s
            if best_d > 1.5:  # too far — likely missing from catalog
                return None, best_d
            return best, best_d

        out_constellations = []
        total_segments = 0
        unresolved = 0
        for name, abbr, verts, edges in CONSTELLATIONS:
            hips = []
            for label, ra, dec in verts:
                star, d = resolve(ra, dec)
                if star is None:
                    self.stdout.write(self.style.WARNING(
                        f'  {abbr}: vertex {label!r} '
                        f'(RA {ra:.2f}, Dec {dec:+.2f}) '
                        f'unresolved (closest {d:.2f}°)'
                    ))
                    hips.append(None)
                    unresolved += 1
                else:
                    if verbose:
                        self.stdout.write(
                            f'  {abbr}: {label} → HIP {star["hip"]} '
                            f'(mag {star["mag"]:.2f}, miss {d:.3f}°)'
                        )
                    hips.append(star['hip'])
            lines = []
            for a, b in edges:
                if hips[a] is not None and hips[b] is not None:
                    lines.append([hips[a], hips[b]])
            total_segments += len(lines)
            out_constellations.append({
                'name':  name,
                'abbr':  abbr,
                'lines': lines,
            })
            self.stdout.write(
                f'  {abbr:5s} {name:14s} '
                f'{len(lines)}/{len(edges)} segments'
            )

        out_path.write_text(json.dumps({
            'description': 'Stick-figure line segments by Hipparcos ID '
                           'for the most recognisable constellations. '
                           'Each line is [hip_a, hip_b]; positions are '
                           'looked up in static/chronos/bright_stars.json.',
            'constellations': out_constellations,
        }, separators=(',', ':')))

        self.stdout.write(self.style.SUCCESS(
            f'Wrote {out_path} · '
            f'{len(out_constellations)} constellations · '
            f'{total_segments} segments · '
            f'{unresolved} unresolved vertices · '
            f'{out_path.stat().st_size} bytes.'
        ))

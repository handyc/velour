"""Seed Place rows on the Mars cartography map for the same six
landmarks tracked by chronos's Mars clocks (Airy-0 + 5 mission
landing sites). Idempotent: re-running update_or_creates each row
on its slug, so values can be edited and re-seeded.

Usage:

    python manage.py seed_mars_places
"""

from django.core.management.base import BaseCommand


# (slug, name, lat°N, lon°E, color, zoom, notes).
# Coordinates from each mission's published landing-site coordinates;
# colors picked to be distinguishable and roughly evocative of the
# vehicle (NASA orange/red, JPL cyan for InSight, purple for the
# Ingenuity flight programme, gold for Tianwen-1 / Zhurong).
MARS_PLACES = [
    ('mars-airy-0', 'Airy-0 (prime meridian)',
     -5.07, 0.00, '#ffffff', 4,
     'Reference crater that defines the Mars prime meridian. '
     'MTC (Airy Mean Time, the Mars clock the chronos page shows '
     'as just "Mars") is local solar time at this longitude. '
     'About 0.5 km wide; lies inside the larger Airy crater.'),

    ('mars-gale-curiosity', 'Curiosity · Gale Crater',
     -4.5895, 137.4417, '#e87722', 5,
     'Mars Science Laboratory landing site, Aeolis Palus inside '
     'Gale Crater. Landed 2012-08-06 05:17 UTC. The chronos '
     '"Curiosity LMST" clock counts mission sols since this date.'),

    ('mars-jezero-perseverance', 'Perseverance · Jezero Crater',
     18.4663, 77.4500, '#cc3333', 5,
     'Mars 2020 landing site at Octavia E. Butler Landing. '
     'Landed 2021-02-18 20:55 UTC. Selected for its ancient lake '
     'delta. The chronos "Perseverance LMST" clock counts '
     'mission sols since landing.'),

    ('mars-elysium-insight', 'InSight · Elysium Planitia',
     4.502, 135.623, '#3399cc', 5,
     'Geophysical lander studying the Martian interior with a '
     'seismometer (SEIS) and heat-flow probe (HP³). Landed '
     '2018-11-26 19:53 UTC. Mission ended 2022-12-21; the LMST '
     'clock continues regardless.'),

    ('mars-wright-brothers-field-ingenuity',
     'Ingenuity · Wright Brothers Field',
     18.4663, 77.4500, '#9966cc', 5,
     'Takeoff site of Flight 1 — the first powered, controlled '
     'flight on another planet, 2021-04-19 12:33 UTC. Co-located '
     'with Perseverance at Jezero Crater. Ingenuity completed 72 '
     'flights before damage to a rotor blade ended the programme '
     'in January 2024.'),

    ('mars-utopia-zhurong', 'Zhurong · Utopia Planitia',
     25.066, 109.925, '#daa520', 5,
     'Tianwen-1 mission rover landing site. Landed 2021-05-14 '
     '23:18 UTC, becoming the second nation to operate a rover '
     'on Mars. Went into planned hibernation May 2022 and did '
     'not wake; the LMST clock continues regardless.'),
]


class Command(BaseCommand):
    help = 'Seed Place rows on the Mars cartography map for the six '\
           'Mars-clock landmarks (Airy-0 + 5 mission landing sites).'

    def handle(self, *args, **opts):
        from cartography.models import Place

        n_created = n_updated = 0
        for slug, name, lat, lon, color, zoom, notes in MARS_PLACES:
            place, created = Place.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':  name,
                    'scale': 'mars',
                    'lat':   lat,
                    'lon':   lon,
                    'zoom':  zoom,
                    'color': color,
                    'notes': notes,
                },
            )
            if created:
                n_created += 1
                self.stdout.write(f'  created  {slug}')
            else:
                n_updated += 1
                self.stdout.write(f'  updated  {slug}')

        self.stdout.write(self.style.SUCCESS(
            f'Done. {n_created} created · {n_updated} updated · '
            f'{len(MARS_PLACES)} Mars landmarks on file.'
        ))

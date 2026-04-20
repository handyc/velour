"""Seed Naiad with a representative stage-type catalog and a few
source / target water profiles.

Removal fractions are order-of-magnitude rough and pulled from
commodity spec sheets (residential-scale treatment gear). Refine
them over time as experimental data comes in from the lab.

Idempotent — re-running upserts rows by slug.
"""

from django.core.management.base import BaseCommand

from naiad.models import StageType, System, WaterProfile


STAGE_TYPES = [
    dict(
        slug='sediment-5um', name='5 µm sediment filter',
        kind='physical',
        description='Pleated / spun polypropylene cartridge. Grabs '
                    'particulates down to ~5 µm. Cheap, disposable, '
                    'the standard first stage in almost any system.',
        removal={'turbidity': 0.85},
        flow_lpm=10.0, energy_watts=0.0,
        cost_eur=4.0, maintenance_days=90,
    ),
    dict(
        slug='sediment-1um', name='1 µm sediment filter',
        kind='physical',
        description='Finer polish stage — picks up most protozoa '
                    'cysts and the residual turbidity a 5 µm stage '
                    'misses.',
        removal={'turbidity': 0.95, 'protozoa': 0.99},
        flow_lpm=8.0, energy_watts=0.0,
        cost_eur=6.0, maintenance_days=90,
    ),
    dict(
        slug='carbon-block', name='Activated carbon block',
        kind='adsorption',
        description='Compressed coconut-shell carbon. Adsorbs '
                    'chlorine, VOCs, and taste/odour compounds. '
                    'Limited help with dissolved inorganics.',
        removal={'chlorine': 0.98, 'voc': 0.92, 'pfas': 0.40,
                 'lead': 0.30},
        flow_lpm=5.0, energy_watts=0.0,
        cost_eur=12.0, maintenance_days=180,
    ),
    dict(
        slug='granular-carbon', name='Granular activated carbon (GAC)',
        kind='adsorption',
        description='Higher flow than a carbon block but less '
                    'aggressive adsorption; good for large volumes '
                    'of lightly-contaminated water.',
        removal={'chlorine': 0.90, 'voc': 0.80, 'pfas': 0.25},
        flow_lpm=15.0, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=365,
    ),
    dict(
        slug='reverse-osmosis', name='Reverse osmosis membrane',
        kind='membrane',
        description='Residential 50-100 GPD TFC membrane. Rejects '
                    'the vast majority of dissolved solids, metals, '
                    'and nitrate but wastes ~3× water as brine.',
        removal={'tds': 0.97, 'lead': 0.98, 'nitrate': 0.92,
                 'fluoride': 0.95, 'arsenic': 0.97, 'pfas': 0.95,
                 'iron': 0.98, 'bacteria': 0.999},
        flow_lpm=0.5, energy_watts=30.0,
        cost_eur=85.0, maintenance_days=730,
    ),
    dict(
        slug='uv-sterilizer', name='UV-C sterilizer 55 W',
        kind='uv',
        description='Whole-house UV lamp at 254 nm. Inactivates '
                    'bacteria, viruses, and protozoa by damaging '
                    'their DNA. Requires clear water (pair with '
                    'sediment stages upstream).',
        removal={'bacteria': 0.9999, 'viruses': 3.0 / 6.0,
                 'protozoa': 0.999},
        flow_lpm=20.0, energy_watts=55.0,
        cost_eur=55.0, maintenance_days=365,
    ),
    dict(
        slug='slow-sand', name='Slow sand filter',
        kind='biological',
        description='Biofilm-based filter — the schmutzdecke on the '
                    'sand surface digests bacteria and protozoa. Low '
                    'flow but passive and long-lived.',
        removal={'bacteria': 0.99, 'protozoa': 0.99,
                 'turbidity': 0.90},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=0.0, maintenance_days=180,
    ),
    dict(
        slug='ion-exchange-softener', name='Ion-exchange softener',
        kind='ion_exchange',
        description='Sodium-form resin that swaps Ca²⁺/Mg²⁺ for '
                    'Na⁺. Reduces hardness and traps some heavy '
                    'metals but raises TDS slightly.',
        removal={'lead': 0.70, 'iron': 0.85},
        flow_lpm=12.0, energy_watts=5.0,
        cost_eur=18.0, maintenance_days=365,
    ),
    dict(
        slug='chlorination', name='Inline chlorine dose',
        kind='chemical',
        description='Small-dose sodium hypochlorite feeder. Powerful '
                    'disinfection but adds residual chlorine the next '
                    'carbon stage has to remove.',
        removal={'bacteria': 0.9999, 'viruses': 4.0 / 6.0},
        flow_lpm=10.0, energy_watts=8.0,
        cost_eur=3.0, maintenance_days=30,
    ),
]


SOURCE_PROFILES = [
    dict(
        slug='eu-tap-typical', name='EU municipal tap (typical)',
        scope='source',
        notes='Treated municipal water meeting the EU Drinking Water '
              'Directive. Low baseline contamination; residual '
              'chlorine and taste are the usual complaints.',
        values={
            'turbidity': 0.3, 'tds': 250.0, 'bacteria': 0.0,
            'chlorine': 0.4, 'lead': 2.0, 'nitrate': 4.0,
            'fluoride': 0.6, 'voc': 0.5, 'pfas': 15.0,
        },
    ),
    dict(
        slug='rural-well', name='Rural well (unconditioned)',
        scope='source',
        notes='Groundwater from a private drilled well in an '
              'agricultural area. Hard, iron-rich, nitrate elevated '
              'from fertiliser runoff; sporadic coliforms.',
        values={
            'turbidity': 2.5, 'tds': 550.0, 'bacteria': 50.0,
            'lead': 5.0, 'nitrate': 35.0, 'iron': 1.2,
            'arsenic': 8.0, 'protozoa': 4.0,
        },
    ),
    dict(
        slug='surface-creek', name='Surface water (creek)',
        scope='source',
        notes='Untreated surface water — what you would collect '
              'from a clean-looking stream. High turbidity and '
              'biological load; assume the worst.',
        values={
            'turbidity': 15.0, 'tds': 180.0, 'bacteria': 5000.0,
            'viruses': 5.0, 'protozoa': 200.0, 'voc': 3.0,
        },
    ),
    dict(
        slug='greywater', name='Household greywater',
        scope='source',
        notes='Shower / sink greywater for reuse (irrigation, toilet '
              'flushing). Organic-heavy, bacteria-laden.',
        values={
            'turbidity': 40.0, 'tds': 600.0, 'bacteria': 100000.0,
            'voc': 20.0,
        },
    ),
]


TARGET_PROFILES = [
    dict(
        slug='eu-drinking', name='EU drinking water (DWD)',
        scope='target',
        notes='Summary limits from the EU Drinking Water Directive '
              '(2020/2184) — not a full legal substitute; just '
              'enough to bound a design.',
        values={
            'turbidity': 1.0, 'tds': 1500.0, 'bacteria': 0.0,
            'viruses': 0.0, 'protozoa': 0.0, 'lead': 5.0,
            'nitrate': 11.3, 'fluoride': 1.5, 'arsenic': 10.0,
            'pfas': 100.0,
        },
    ),
    dict(
        slug='aquarium-freshwater', name='Freshwater aquarium',
        scope='target',
        notes='Chlorine-free, low hardness, no heavy metals. Fish '
              'care about chlorine and ammonia more than EU limits.',
        values={
            'chlorine': 0.02, 'tds': 300.0, 'lead': 10.0,
            'bacteria': 100.0,
        },
    ),
    dict(
        slug='irrigation', name='Irrigation-grade',
        scope='target',
        notes='Forgiving target — used for the greywater-to-garden '
              'loop.',
        values={
            'turbidity': 10.0, 'bacteria': 1000.0,
        },
    ),
]


class Command(BaseCommand):
    help = 'Seed Naiad stage-type catalog + source / target water profiles.'

    def handle(self, *args, **opts):
        st_n = 0
        for spec in STAGE_TYPES:
            obj, created = StageType.objects.update_or_create(
                slug=spec['slug'], defaults=spec)
            st_n += 1
            self.stdout.write(
                f'  {"+" if created else "·"} stage_type {obj.slug}')
        wp_n = 0
        for spec in SOURCE_PROFILES + TARGET_PROFILES:
            obj, created = WaterProfile.objects.update_or_create(
                slug=spec['slug'], defaults=spec)
            wp_n += 1
            self.stdout.write(
                f'  {"+" if created else "·"} profile    {obj.scope}/{obj.slug}')

        # One sample system so the index isn't empty on fresh installs.
        source = WaterProfile.objects.get(slug='rural-well')
        target = WaterProfile.objects.get(slug='eu-drinking')
        system, created = System.objects.update_or_create(
            slug='well-to-drinking', defaults=dict(
                name='Well → Drinking (example)',
                description='A starter 5-stage chain sized for a '
                            'rural household well feeding a kitchen '
                            'tap. Use it as a reference and clone it '
                            'to tune for your own source water.',
                source=source, target=target,
            ))
        if created:
            for i, stype_slug in enumerate([
                'sediment-5um', 'sediment-1um',
                'carbon-block', 'reverse-osmosis', 'uv-sterilizer',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                from naiad.models import Stage
                Stage.objects.create(
                    system=system, stage_type=st, position=i)

        self.stdout.write(self.style.SUCCESS(
            f'Naiad seed done: {st_n} stage types, {wp_n} profiles. '
            f'{"Created" if created else "Found"} sample system '
            f'"{system.name}".'))

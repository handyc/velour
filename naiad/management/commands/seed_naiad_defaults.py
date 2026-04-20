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
                 'iron': 0.98, 'bacteria': 0.999,
                 'sodium': 0.95, 'potassium': 0.95,
                 'creatinine': 0.95, 'phosphate': 0.95,
                 'urea': 0.40, 'ammonia': 0.60,
                 'pharma': 0.85, 'hormones': 0.85},
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

    # --- Urine-treatment stage types ----------------------------------
    # Removal fractions are order-of-magnitude figures pulled from the
    # Eawag Vuna project, NASA UPA-style vapour-compression papers, and
    # decentralised-sanitation reviews. Real pilot data will refine these.
    dict(
        slug='urea-hydrolysis', name='Urea hydrolysis (enzymatic)',
        kind='biological',
        description='Biofilm reactor where urease-rich biomass converts '
                    'urea to ammonium carbonate. Not a removal stage on '
                    'its own — it stabilises the stream so downstream '
                    'ammonia / nitrification / struvite stages can act. '
                    'Consumes urea; generates ammonia.',
        removal={'urea': 0.98},
        # CO(NH2)2 (MW 60, 2 N) → 2 NH4+-N (14 g/mol N each).
        # Per 1 mg urea removed, 2 × 14 / 60 = 0.467 mg NH4-N produced.
        converts={'urea': {'ammonia': 0.467}},
        flow_lpm=1.5, energy_watts=2.0,
        cost_eur=15.0, maintenance_days=180,
    ),
    dict(
        slug='struvite-precipitation', name='Struvite precipitation (MAP)',
        kind='chemical',
        description='Dose Mg²⁺ (e.g. MgO) at pH ~9 to precipitate '
                    'magnesium-ammonium-phosphate crystals. Recovers ~90% '
                    'of phosphorus and a chunk of the ammonium as solid '
                    'fertiliser; little effect on urea.',
        removal={'phosphate': 0.90, 'ammonia': 0.35},
        flow_lpm=1.0, energy_watts=3.0,
        cost_eur=8.0, maintenance_days=60,
    ),
    dict(
        slug='ammonia-stripping', name='Ammonia stripping tower',
        kind='chemical',
        description='Raise pH to 10-11, counter-current air or steam to '
                    'volatilise NH₃. Classical industrial move; captures '
                    'NH₃ in an acid trap for fertiliser. Effective on '
                    'ammonia but dumps alkali that must be re-balanced.',
        removal={'ammonia': 0.95},
        flow_lpm=2.0, energy_watts=40.0,
        cost_eur=25.0, maintenance_days=180,
    ),
    dict(
        slug='nitrification-bioreactor',
        name='Nitrification bioreactor (MBBR)',
        kind='biological',
        description='Moving-bed biofilm oxidises residual NH₄⁺ to NO₃⁻ '
                    'at neutral pH. Pairs well with RO or ion-exchange '
                    'downstream since those reject the produced nitrate '
                    'cleanly — without that polish a nitrifier just '
                    'trades one regulated solute for another.',
        removal={'ammonia': 0.92},
        # N conservation: 1 mg NH4-N oxidises to 1 mg NO3-N.
        converts={'ammonia': {'nitrate': 1.0}},
        flow_lpm=1.5, energy_watts=12.0,
        cost_eur=30.0, maintenance_days=365,
    ),
    dict(
        slug='electrochem-oxidation',
        name='Electrochemical oxidation (BDD anode)',
        kind='chemical',
        description='Boron-doped diamond electrodes generate hydroxyl '
                    'radicals that mineralise urea, organics, hormones, '
                    'and pharmaceuticals — pricey on electrodes and '
                    'power but removes classes RO leaves behind.',
        removal={'urea': 0.90, 'pharma': 0.95, 'hormones': 0.95,
                 'creatinine': 0.90, 'voc': 0.80, 'bacteria': 0.999},
        flow_lpm=0.5, energy_watts=120.0,
        cost_eur=180.0, maintenance_days=365,
    ),

    # --- Low-budget / passive polish stages ---------------------------
    # Real-world appropriate-technology options: passive storage,
    # natural sorbents, constructed wetlands, sunlight. Near-zero power
    # and maintenance, meaningful but gentle removal per pass.
    dict(
        slug='urine-storage-tank',
        name='Long-term urine storage tank',
        kind='biological',
        description='Sealed tank holding urine 1-6 months at ambient. '
                    'Urease-rich biofilm converts urea to ammonium '
                    'carbonate; resulting high-pH stream inactivates '
                    'most pathogens. Eawag Vuna\'s pre-treatment — no '
                    'moving parts, no power.',
        removal={'urea': 0.97, 'bacteria': 0.99, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.99},
        converts={'urea': {'ammonia': 0.467}},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=50.0, maintenance_days=365,
    ),
    dict(
        slug='zeolite-ammonium',
        name='Zeolite (clinoptilolite) ammonium filter',
        kind='ion_exchange',
        description='Natural clinoptilolite selectively sorbs NH₄⁺. '
                    'Regenerable with brine; no power; cheap by the '
                    'kilo. Also grabs a fraction of K⁺. Common in '
                    'off-grid and emergency water-treatment kits.',
        removal={'ammonia': 0.80, 'potassium': 0.35},
        flow_lpm=4.0, energy_watts=0.0,
        cost_eur=15.0, maintenance_days=180,
    ),
    dict(
        slug='constructed-wetland',
        name='Constructed wetland (subsurface-flow)',
        kind='biological',
        description='Reed / gravel bed with long residence time. Plants '
                    'and rhizosphere microbiota take up nitrate, '
                    'phosphate, residual ammonia; anaerobic zones '
                    'denitrify; sunlight in the upper zones degrades '
                    'pharma and hormones. Passive polish, slow flow.',
        removal={'nitrate': 0.70, 'ammonia': 0.50, 'phosphate': 0.60,
                 'bacteria': 0.99, 'protozoa': 0.95, 'pharma': 0.40,
                 'hormones': 0.30, 'voc': 0.60, 'turbidity': 0.80},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=180,
    ),
    dict(
        slug='solar-disinfection',
        name='Solar disinfection (SODIS)',
        kind='uv',
        description='Sunlight-in-a-bottle: UV-A plus thermal '
                    'inactivation over 6 h. Endorsed by WHO for '
                    'household drinking water; costs only the bottle. '
                    'Batch process, clear water only — pair with a '
                    'sediment stage upstream.',
        removal={'bacteria': 0.999, 'viruses': 3.0 / 6.0,
                 'protozoa': 0.80},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=1.0, maintenance_days=0,
    ),

    dict(
        slug='vapor-distillation',
        name='Vapour-compression distillation',
        kind='physical',
        description='NASA-UPA-style: evaporate water from brine under '
                    'reduced pressure, recompress vapour to condense. '
                    'Separates water from essentially everything non-'
                    'volatile — salts, creatinine, pharma residues — '
                    'at the cost of high energy use.',
        removal={'tds': 0.99, 'sodium': 0.99, 'potassium': 0.99,
                 'creatinine': 0.99, 'phosphate': 0.99,
                 'pharma': 0.95, 'hormones': 0.95, 'urea': 0.80,
                 'lead': 0.99, 'arsenic': 0.99,
                 'bacteria': 0.9999, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.9999},
        flow_lpm=0.2, energy_watts=200.0,
        cost_eur=220.0, maintenance_days=730,
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
    dict(
        slug='human-urine-fresh', name='Human urine (fresh)',
        scope='source',
        notes='Freshly voided adult urine, no storage. Urea still '
              'intact, ammonia low, bacteria near-sterile at the '
              'meatus. Values are population averages — individual '
              'urine varies with hydration, diet, health, and drugs.',
        values={
            'turbidity':   20.0,        # NTU — colloidal
            'tds':       25000.0,       # mg/L — yes, that salty
            'urea':      20000.0,       # mg/L — the big one
            'ammonia':      50.0,       # mg/L as N — low in fresh urine
            'creatinine':  1500.0,      # mg/L
            'phosphate':    800.0,      # mg/L as P
            'potassium':   2000.0,      # mg/L
            'sodium':      3500.0,      # mg/L
            'chlorine':       0.0,
            'nitrate':        5.0,      # mg/L
            'bacteria':      10.0,      # CFU/100mL — near-sterile
            'voc':           50.0,      # µg/L
            'pharma':     10000.0,      # ng/L — highly variable
            'hormones':    2000.0,      # ng/L — estrogens, etc.
        },
    ),
    dict(
        slug='human-urine-stored', name='Human urine (stored / hydrolysed)',
        scope='source',
        notes='Urine stored >1 week at ambient temperature: urea has '
              'largely hydrolysed to ammonium carbonate, pH has risen '
              'to ~9, most pathogens are inactivated by alkalinity. '
              'This is what Eawag-style source-separating toilets '
              'actually feed to a treatment train.',
        values={
            'turbidity':   25.0,
            'tds':       28000.0,
            'urea':         200.0,      # mostly hydrolysed away
            'ammonia':     9000.0,      # mg/L as N — massive
            'creatinine':  1500.0,
            'phosphate':    800.0,
            'potassium':   2000.0,
            'sodium':      3500.0,
            'nitrate':        3.0,
            'bacteria':       1.0,      # inactivated by high pH
            'voc':           40.0,
            'pharma':     10000.0,
            'hormones':    2000.0,
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
    dict(
        slug='eu-drinking-urine-reuse',
        name='EU drinking water (urine-reuse bounds)',
        scope='target',
        notes='Same spirit as eu-drinking but with explicit caps on '
              'urine-derived solutes (urea, ammonia, creatinine, '
              'sodium, potassium, phosphate, hormones, pharma). WHO '
              'and Dutch potable-reuse guidance were the anchor. Use '
              'this as the pass/fail spec for urine-to-drinking '
              'systems instead of eu-drinking — which silently ignores '
              'these keys.',
        values={
            'turbidity':  1.0,
            'tds':     1500.0,
            'bacteria':   0.0,
            'viruses':    0.0,
            'protozoa':   0.0,
            'lead':       5.0,
            'nitrate':   11.3,
            'fluoride':   1.5,
            'arsenic':   10.0,
            'pfas':     100.0,
            'urea':       2.0,          # mg/L — conservative ceiling
            'ammonia':    0.5,          # mg/L as N — WHO taste limit
            'creatinine': 1.0,          # mg/L
            'phosphate': 10.0,          # mg/L as P
            'potassium': 12.0,          # mg/L — WHO provisional
            'sodium':   200.0,          # mg/L — EU DWD taste param
            'hormones':   1.0,          # ng/L — EU watchlist band
            'pharma':    10.0,          # ng/L — WHO insignificant level
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

        # Reference urine-to-drinking chain. Not guaranteed to pass on
        # day one — the point is to have something concrete to tune
        # against. Based loosely on Vuna (Eawag) + vapour-compression
        # distillation + AOP polish. Run a TestRun from the UI to see
        # where it leaks.
        urine_src = WaterProfile.objects.get(slug='human-urine-stored')
        urine_tgt = WaterProfile.objects.get(slug='eu-drinking-urine-reuse')
        urine_system, urine_created = System.objects.update_or_create(
            slug='urine-to-drinking', defaults=dict(
                name='Urine → Drinking (reference chain)',
                description='Source-separated urine, stored until urea '
                            'hydrolyses, then: sediment → struvite → '
                            'ammonia stripping → nitrification → GAC → '
                            'vapour distillation → electrochemical '
                            'polish → UV. A starting point — refine '
                            'the order and swap stages based on lab '
                            'results.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'sediment-5um',
                'struvite-precipitation',
                'ammonia-stripping',
                'nitrification-bioreactor',
                'granular-carbon',
                'vapor-distillation',
                'electrochem-oxidation',
                'uv-sterilizer',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_system, stage_type=st, position=i)

        # Evolved counterparts — both from naiad_evolve seed=42 but with
        # different cost/watt caps, giving two snapshots of the design
        # landscape: a balanced passing chain (v2) and a minimum-budget
        # passing chain (v3) showing how far the low-budget passive
        # stages can take you when they're in the catalog.
        urine_v2, urine_v2_created = System.objects.update_or_create(
            slug='urine-to-drinking-v2', defaults=dict(
                name='Urine → Drinking (GA-tuned v2)',
                description='GA-evolved passing chain (seed 42, urine-scale '
                            'caps €1200 / 700 W). No vapour-compression, no '
                            'ammonia stripping — three RO passes plus three '
                            'nitrification stages do the same job at roughly '
                            'half the power draw.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v2_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'sediment-1um',
                'nitrification-bioreactor',
                'urea-hydrolysis',
                'reverse-osmosis',
                'nitrification-bioreactor',
                'nitrification-bioreactor',
                'slow-sand',
                'reverse-osmosis',
                'reverse-osmosis',
                'electrochem-oxidation',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v2, stage_type=st, position=i)

        # v3 — minimum-budget variant using the new passive stages
        # (zeolite ammonium, constructed wetland). naiad_evolve seed=42,
        # pop=120, gens=400, --cost-cap 800 --watt-cap 400. ~€455 /
        # 134 W: 4× RO + 2× zeolite + 2× wetland + urea hydrolysis +
        # nitrification; no electrochem, no distillation.
        urine_v3, urine_v3_created = System.objects.update_or_create(
            slug='urine-to-drinking-v3', defaults=dict(
                name='Urine → Drinking (minimum-budget v3)',
                description='GA-evolved minimum-budget passing chain. '
                            'Leans on passive stages (zeolite, constructed '
                            'wetland) in place of electrochemical oxidation '
                            'and vapour distillation. ~€455 / 134 W — a '
                            'proof-of-concept that urine-to-potable is '
                            'reachable without the industrial power draw '
                            'of the reference catalog.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v3_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'zeolite-ammonium',
                'reverse-osmosis',
                'reverse-osmosis',
                'constructed-wetland',
                'urea-hydrolysis',
                'zeolite-ammonium',
                'reverse-osmosis',
                'nitrification-bioreactor',
                'constructed-wetland',
                'reverse-osmosis',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v3, stage_type=st, position=i)

        self.stdout.write(self.style.SUCCESS(
            f'Naiad seed done: {st_n} stage types, {wp_n} profiles. '
            f'Sample systems: "{system.name}", '
            f'"{urine_system.name}", "{urine_v2.name}", '
            f'"{urine_v3.name}".'))

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
                 'pharma': 0.95, 'hormones': 0.95,
                 'urea': 0.80, 'ammonia': 0.90,
                 'lead': 0.99, 'arsenic': 0.99,
                 'turbidity': 0.99,
                 'bacteria': 0.9999, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.9999},
        flow_lpm=0.2, energy_watts=200.0,
        cost_eur=220.0, maintenance_days=730,
    ),

    # --- Kitchen-grade / MacGyver tier --------------------------------
    # Soda bottles, coffee filters, vinegar, wood ash, BBQ briquettes,
    # household bleach, a black-painted basin under clear plastic. WHO
    # / Peace Corps / disaster-prep canon. Real removal numbers, but
    # throughputs are batch-tiny and many stages are setup-helpers
    # rather than removal stages on their own. Pair acidification with
    # a thermal step for the urea/ammonia trick.
    dict(
        slug='bucket-settling',
        name='Settling bucket (24 h)',
        kind='physical',
        description='Five-gallon bucket with a lid. Let urine sit for '
                    '24 h, then decant the supernatant. Drops coarse '
                    'solids and a chunk of bacteria with the sediment '
                    'cake. The simplest pre-stage there is.',
        removal={'turbidity': 0.50, 'bacteria': 0.20, 'protozoa': 0.30},
        flow_lpm=0.05, energy_watts=0.0,
        cost_eur=5.0, maintenance_days=30,
    ),
    dict(
        slug='cloth-coffee-filter',
        name='Cloth + coffee-filter drip',
        kind='physical',
        description='Bandana-grade prefilter: bandana over a funnel '
                    'with a paper coffee filter inside. Catches '
                    'colloids and big organic flakes before they '
                    'foul a downstream charcoal column.',
        removal={'turbidity': 0.70, 'protozoa': 0.30,
                 'bacteria': 0.10},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=1.0, maintenance_days=7,
    ),
    dict(
        slug='vinegar-acidify',
        name='Vinegar acidification (pH ~4)',
        kind='chemical',
        description='Dose white vinegar (acetic acid) until pH drops '
                    'to ~4. Free ammonia disappears into non-volatile '
                    'ammonium acetate; the salt then drops out in any '
                    'downstream physical or thermal stage. Modelled '
                    'as 95 % ammonia removal because that is what '
                    'reaches a downstream still — not gone, but '
                    'durably bound.',
        removal={'ammonia': 0.95},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=3.0, maintenance_days=14,
    ),
    dict(
        slug='wood-ash-lye',
        name='Wood-ash potash dose (pH ~10)',
        kind='chemical',
        description='Wood-ash leachate (potash) raises pH well into '
                    'the alkaline band, tipping the NH₄⁺/NH₃ '
                    'equilibrium toward gaseous NH₃. Pair with an '
                    'open settle vessel or counter-current air strip '
                    'to actually offgas it. Free if you have a fire.',
        removal={'ammonia': 0.30, 'bacteria': 0.50},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=0.0, maintenance_days=14,
    ),
    dict(
        slug='alum-coagulation',
        name='Alum coagulant + settle',
        kind='chemical',
        description='Potassium aluminum sulfate (pickling alum) '
                    'coagulates colloids into pin-flocs that settle '
                    'in 30 minutes. Garden-store bag, lasts '
                    'effectively forever per bag.',
        removal={'turbidity': 0.85, 'bacteria': 0.50,
                 'pharma': 0.30, 'hormones': 0.20},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=5.0, maintenance_days=30,
    ),
    dict(
        slug='bleach-dose',
        name='Household bleach (NaOCl)',
        kind='chemical',
        description='Four drops of unscented 8.25 % bleach per gallon '
                    'and a 30-minute hold. Drives chlorine residual '
                    'high enough to kill bacteria and most viruses. '
                    'Crypto and other resistant protozoa survive — '
                    'pair upstream with settling or filtration.',
        removal={'bacteria': 0.9999, 'viruses': 4.0 / 6.0,
                 'protozoa': 0.50},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=2.0, maintenance_days=90,
    ),
    dict(
        slug='briquette-charcoal',
        name='BBQ-briquette charcoal column',
        kind='adsorption',
        description='Crushed lump charcoal (rinse first to drop the '
                    'starch binder) packed into a soda bottle. Real '
                    'adsorption capacity but well below activated '
                    'carbon — fine for taste/odor and a fraction of '
                    'organics. The "ten dollar carbon stage."',
        removal={'voc': 0.50, 'chlorine': 0.60,
                 'pharma': 0.40, 'hormones': 0.30,
                 'ammonia': 0.10},
        flow_lpm=0.4, energy_watts=0.0,
        cost_eur=3.0, maintenance_days=14,
    ),
    dict(
        slug='diy-gac-bottle',
        name='DIY granular activated carbon (PET bottle)',
        kind='adsorption',
        description='Aquarium-grade GAC (~€5/lb) in an inverted PET '
                    'soda bottle, with a coffee filter as a holder. '
                    'A real activated-carbon stage at field-kit '
                    'price, slower than a pro carbon block but '
                    'meaningful contact time at gravity flow.',
        removal={'voc': 0.85, 'chlorine': 0.95, 'pfas': 0.30,
                 'pharma': 0.80, 'hormones': 0.75,
                 'ammonia': 0.20, 'urea': 0.20},
        flow_lpm=0.4, energy_watts=0.0,
        cost_eur=8.0, maintenance_days=60,
    ),
    dict(
        slug='solar-still',
        name='Solar still (single-effect)',
        kind='physical',
        description='Black-painted basin in a sloped clear-plastic '
                    'tent; vapor condenses on the underside of the '
                    'film and runs to a collection bottle. The '
                    'workhorse of cheap urine-to-water — leaves urea, '
                    'salts, hormones, pharma, and metals in the '
                    'dregs. Pair upstream with vinegar acidification '
                    'or you carry NH₃ into the distillate. ~1 L/m²/'
                    'day temperate; quoted flow assumes ~5 m² array. '
                    'Removal numbers below assume an acidified feed; '
                    'without vinegar upstream, urea and ammonia '
                    'carry-over is much higher.',
        removal={'tds': 0.99, 'sodium': 0.99, 'potassium': 0.99,
                 'creatinine': 0.99, 'phosphate': 0.99,
                 'lead': 0.99, 'arsenic': 0.99,
                 'turbidity': 0.99,
                 'urea': 0.70, 'ammonia': 0.80,
                 'pharma': 0.95, 'hormones': 0.95,
                 'bacteria': 0.999, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.999},
        flow_lpm=0.005, energy_watts=0.0,
        cost_eur=25.0, maintenance_days=60,
    ),
    dict(
        slug='boiling-pot',
        name='Boil + condense (kettle/pot)',
        kind='physical',
        description='Bring water to a rolling boil for ≥1 minute. '
                    'Wood- or propane-fired in field use, so '
                    'electrical draw is zero — but the fuel-handling '
                    'cadence shows up as high maintenance. Disinfects '
                    'thoroughly; does nothing to dissolved solutes '
                    'unless you also condense the vapor (next stage).',
        removal={'bacteria': 0.9999, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.999},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=30.0, maintenance_days=7,
    ),
    dict(
        slug='stovetop-still',
        name='Stovetop still (kettle + condenser tube)',
        kind='physical',
        description='Pressure-cooker or kettle with a copper-coil '
                    'condenser running through a cold-water bucket. '
                    '"Moonshine still" geometry, food-grade build. '
                    'Gives you full distillation throughput at the '
                    'cost of running an electric stove (or a wood '
                    'fire with maintenance going up instead). '
                    'Like the solar still, removal numbers assume an '
                    'acidified feed.',
        removal={'tds': 0.99, 'sodium': 0.99, 'potassium': 0.99,
                 'creatinine': 0.99, 'phosphate': 0.99,
                 'lead': 0.99, 'arsenic': 0.99,
                 'turbidity': 0.99,
                 'urea': 0.85, 'ammonia': 0.85,
                 'pharma': 0.95, 'hormones': 0.95,
                 'bacteria': 0.9999, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.9999},
        flow_lpm=0.4, energy_watts=1500.0,
        cost_eur=60.0, maintenance_days=180,
    ),

    # --- Field / camping tier ----------------------------------------
    # Where backpacker filters, ceramic candles, NaDCC tablets, and
    # gravity multi-element filters live. Real engineering, off-the-
    # shelf at a sporting-goods store; €20-300.
    dict(
        slug='ceramic-pot-filter',
        name='Ceramic pot filter (Potters-for-Peace)',
        kind='physical',
        description='Clay-and-sawdust ceramic candle, optionally '
                    'silver-impregnated. Pore size ~0.2 µm — bacteria '
                    'and protozoa stay on the outer surface; viruses '
                    'are partially captured by absorption. Slow '
                    'gravity flow, near-zero maintenance.',
        removal={'bacteria': 0.9999, 'protozoa': 0.9999,
                 'viruses': 0.85, 'turbidity': 0.95},
        flow_lpm=0.05, energy_watts=0.0,
        cost_eur=25.0, maintenance_days=365,
    ),
    dict(
        slug='hollow-fiber-filter',
        name='Hollow-fiber backpacker filter',
        kind='membrane',
        description='Sawyer / Lifestraw-class 0.1 µm hollow-fiber '
                    'membrane. Bacteria and protozoa stop dead; '
                    'viruses partially leak through. Backflush keeps '
                    'it alive for 100k+ litres.',
        removal={'bacteria': 0.99999, 'protozoa': 0.99999,
                 'viruses': 0.50, 'turbidity': 0.95},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=30.0, maintenance_days=365,
    ),
    dict(
        slug='nadcc-tablets',
        name='NaDCC chlorine tablets (Aquatabs)',
        kind='chemical',
        description='Sodium dichloroisocyanurate tablets — slower-'
                    'release chlorine than bleach with a more '
                    'predictable residual. WHO-recommended for '
                    'household disinfection. Crypto still survives.',
        removal={'bacteria': 0.99999, 'viruses': 0.9999,
                 'protozoa': 0.50},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=10.0, maintenance_days=180,
    ),
    dict(
        slug='diy-uv-cfl',
        name='DIY germicidal UV reactor (CFL)',
        kind='uv',
        description='25 W germicidal CFL bulb in a foil-lined PVC '
                    'tube with a quartz sleeve. Less polished than a '
                    'real UV-C sterilizer (uneven dose, shorter lamp '
                    'life), but real 254 nm UV nonetheless.',
        removal={'bacteria': 0.99, 'viruses': 0.60,
                 'protozoa': 0.95},
        flow_lpm=0.3, energy_watts=25.0,
        cost_eur=30.0, maintenance_days=365,
    ),
    dict(
        slug='countertop-distiller',
        name='Countertop electric distiller',
        kind='physical',
        description='Megahome-class consumer distiller — 1 gal per '
                    '4-5 hours, kills everything biological, leaves '
                    'all dissolved solutes in the boiling chamber. '
                    'Same urea/ammonia carry-over caveat as any '
                    'thermal stage.',
        removal={'tds': 0.99, 'sodium': 0.99, 'potassium': 0.99,
                 'creatinine': 0.99, 'phosphate': 0.99,
                 'lead': 0.99, 'arsenic': 0.99,
                 'turbidity': 0.99,
                 'urea': 0.60, 'ammonia': 0.40,
                 'pharma': 0.97, 'hormones': 0.97,
                 'bacteria': 0.9999, 'viruses': 5.0 / 6.0,
                 'protozoa': 0.9999},
        flow_lpm=0.06, energy_watts=800.0,
        cost_eur=200.0, maintenance_days=365,
    ),
    dict(
        slug='tpms-ceramic-microfilter',
        name='3D-printed ceramic TPMS microfilter',
        kind='physical',
        description='Stereolithography-printed ceramic with a triply '
                    'periodic minimal surface (gyroid / Schwarz-P / '
                    'Schwarz-D) geometry, then kiln-fired. The '
                    'hierarchical pores give 3-5× the surface-area-to-'
                    'volume of a Potters-for-Peace candle at '
                    'comparable removal, with tunable pore size from '
                    '5 µm down to ~0.2 µm. Indefinite life if '
                    'periodically baked to burn off biofilm. Research-'
                    'emerging (ETH Zurich / MIT / Lithoz / Tethon3D); '
                    'achievable price assumes maker-space access to a '
                    'ceramic SLA printer + resin per cartridge.',
        removal={'bacteria': 0.99999, 'viruses': 0.95,
                 'protozoa': 0.99999, 'turbidity': 0.99},
        flow_lpm=0.5, energy_watts=0.0,
        cost_eur=40.0, maintenance_days=730,
    ),
    dict(
        slug='berkey-gravity',
        name='Berkey-style gravity multi-element filter',
        kind='adsorption',
        description='Stacked stainless dispensers with black '
                    'carbon-block candles (and optional fluoride '
                    'PF-2 elements). High flow for gravity, broad '
                    'removal across organics, metals, and pathogens '
                    '— but does nothing to salts or urea.',
        removal={'bacteria': 0.999999, 'viruses': 0.99,
                 'protozoa': 0.99999, 'lead': 0.95,
                 'voc': 0.95, 'chlorine': 0.99, 'fluoride': 0.95,
                 'pharma': 0.80, 'hormones': 0.70},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=250.0, maintenance_days=730,
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

        # v4 — kitchen MacGyver (all-passive, soda-bottle tier).
        # Validated by simulator: passes the urine-reuse target on
        # stored urine. Total ~€121 / 0 W. The trick the GA found
        # is re-acidifying with vinegar between distillation passes,
        # so each successive still strips ammonia from a feed that's
        # been re-locked as ammonium acetate.
        urine_v4, urine_v4_created = System.objects.update_or_create(
            slug='urine-to-drinking-v4-kitchen', defaults=dict(
                name='Urine → Drinking (v4 kitchen MacGyver)',
                description='Soda-bottle tier — all-passive, zero '
                            'electricity. A 5-gal bucket, a paper '
                            'coffee filter, white vinegar, four '
                            'solar stills, a DIY granular-carbon '
                            'column in a PET bottle, and a few '
                            'drops of household bleach. The trick: '
                            're-dose vinegar between distillation '
                            'passes so each still gets a fresh '
                            'acidified feed. ~€121 total, no power, '
                            '~1 L/day per m² of solar still area.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v4_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'bucket-settling',
                'vinegar-acidify',
                'solar-still',
                'solar-still',
                'vinegar-acidify',
                'solar-still',
                'solar-still',
                'diy-gac-bottle',
                'bleach-dose',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v4, stage_type=st, position=i)

        # v5 — field / camping kit. Uses stovetop distillation for
        # higher throughput than solar at the cost of stove fuel,
        # plus urea-hydrolysis to knock out urea biologically before
        # the thermal step. ~€187 / 3 kW peak (one element on at a
        # time in practice; Naiad sums simultaneously-flowing stages).
        urine_v5, urine_v5_created = System.objects.update_or_create(
            slug='urine-to-drinking-v5-field', defaults=dict(
                name='Urine → Drinking (v5 field / camping)',
                description='Field-kit tier — stovetop kettle-and-'
                            'condenser still, alum coagulant, urea '
                            'hydrolysis biofilm, vinegar, zeolite '
                            'polish, two DIY GAC bottles, NaDCC '
                            'tabs. Faster throughput than v4 at '
                            'the cost of an electric stove (or a '
                            'wood fire, which the model treats as '
                            'high-maintenance instead of high-watt).',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v5_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'alum-coagulation',
                'urea-hydrolysis',
                'vinegar-acidify',
                'stovetop-still',
                'vinegar-acidify',
                'stovetop-still',
                'zeolite-ammonium',
                'diy-gac-bottle',
                'diy-gac-bottle',
                'nadcc-tablets',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v5, stage_type=st, position=i)

        # v6 — consumer mid-tier. Vapour-compression + electrochem +
        # zeolite + GAC + UV. Heavy on commercial gear; ~€743 /
        # 579 W. The reference chain (urine-to-drinking) and v2 cover
        # the higher-cost "industrial" end.
        urine_v6, urine_v6_created = System.objects.update_or_create(
            slug='urine-to-drinking-v6-consumer', defaults=dict(
                name='Urine → Drinking (v6 consumer mid-tier)',
                description='Off-the-shelf consumer gear — twin '
                            'vapour-compression distillers, BDD '
                            'electrochemical polish, zeolite '
                            'ammonium trap, granular-activated '
                            'carbon, whole-house UV. The "buy this '
                            'on Amazon" tier; ~€743 / 579 W.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v6_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'urea-hydrolysis',
                'urea-hydrolysis',
                'vinegar-acidify',
                'vapor-distillation',
                'vinegar-acidify',
                'vapor-distillation',
                'electrochem-oxidation',
                'zeolite-ammonium',
                'granular-carbon',
                'uv-sterilizer',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v6, stage_type=st, position=i)

        # v7 — fully passive, no chemicals, no electricity. Trades
        # vinegar's acidification trick for more zeolite + more solar
        # stills; trades bleach + UV for the 3D-printed ceramic TPMS
        # microfilter as a final pathogen polish. The honest cost of
        # going chemical-free is ~€198 (vs v4's €121 with vinegar +
        # bleach) — chemicals were doing real work; pulling them out
        # demands more passes through the still.
        urine_v7, urine_v7_created = System.objects.update_or_create(
            slug='urine-to-drinking-v7-zero-input', defaults=dict(
                name='Urine → Drinking (v7 zero-input passive)',
                description='No additives, no electricity. Three '
                            'beds of clinoptilolite zeolite trap '
                            'ammonium; four solar still passes '
                            'remove residual urea, salts, pharma, '
                            'and hormones; a DIY GAC bottle picks '
                            'up tail-end organics; a 3D-printed '
                            'ceramic TPMS microfilter is the final '
                            'pathogen polish. Roughly €198 of '
                            'rocks, plastic, and ceramic; 0 W; 0 '
                            'consumables.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v7_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'bucket-settling',
                'zeolite-ammonium',
                'zeolite-ammonium',
                'zeolite-ammonium',
                'solar-still',
                'solar-still',
                'solar-still',
                'solar-still',
                'diy-gac-bottle',
                'tpms-ceramic-microfilter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v7, stage_type=st, position=i)

        self.stdout.write(self.style.SUCCESS(
            f'Naiad seed done: {st_n} stage types, {wp_n} profiles. '
            f'Sample systems: "{system.name}", '
            f'"{urine_system.name}", "{urine_v2.name}", '
            f'"{urine_v3.name}", "{urine_v4.name}", '
            f'"{urine_v5.name}", "{urine_v6.name}", '
            f'"{urine_v7.name}".'))

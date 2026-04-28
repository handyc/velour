"""Seed Naiad with a representative stage-type catalog and a few
source / target water profiles.

Removal fractions are order-of-magnitude rough and pulled from
commodity spec sheets (residential-scale treatment gear). Refine
them over time as experimental data comes in from the lab.

Idempotent — re-running upserts rows by slug.
"""

from django.core.management.base import BaseCommand

from naiad.models import StageType, System, WaterProfile


# Physical bounding boxes per stage slug (width × depth × height in
# mm). A bucket settles at 300³, a 2 L PET soda bottle at 100×100×200,
# a small solar still at 500×500×300, an industrial RO/distiller at
# 300-400 mm a side. These drive the GA's volume penalty and the
# per-system 1 m³ shelf-pack visualisation.
STAGE_DIMENSIONS = {
    # Existing kitchen / hardware-store filters
    'sediment-5um':            (100, 100, 250),
    'sediment-1um':            (100, 100, 250),
    'carbon-block':            (100, 100, 350),
    'granular-carbon':         (200, 200, 350),
    'reverse-osmosis':         (300, 200, 400),
    'uv-sterilizer':           (300,  80, 400),
    'slow-sand':               (500, 500, 400),
    'ion-exchange-softener':   (250, 250, 500),
    'chlorination':            (200, 200, 200),
    # Urine-treatment industrial
    'urea-hydrolysis':         (300, 300, 350),
    'struvite-precipitation':  (300, 300, 300),
    'ammonia-stripping':       (300, 300, 900),
    'nitrification-bioreactor':(400, 400, 350),
    'electrochem-oxidation':   (300, 300, 250),
    # Low-budget passive
    'urine-storage-tank':      (600, 600, 500),
    'zeolite-ammonium':        (200, 200, 300),
    'constructed-wetland':     (800, 500, 500),
    'solar-disinfection':      (200, 100, 100),
    'vapor-distillation':      (400, 400, 400),
    # Kitchen / MacGyver tier
    'bucket-settling':         (300, 300, 300),
    'cloth-coffee-filter':     (150, 150, 200),
    'vinegar-acidify':         (200, 200, 250),
    'wood-ash-lye':            (200, 200, 250),
    'alum-coagulation':        (200, 200, 250),
    'bleach-dose':             (100, 100, 200),
    'briquette-charcoal':      (100, 100, 200),
    'diy-gac-bottle':          (100, 100, 250),
    'solar-still':             (500, 500, 300),
    'boiling-pot':             (250, 250, 250),
    'stovetop-still':          (400, 400, 400),
    # Field / camping tier
    'ceramic-pot-filter':      (250, 250, 350),
    'hollow-fiber-filter':     (100,  50, 150),
    'nadcc-tablets':           (50,   50, 100),
    'diy-uv-cfl':              (200, 100, 250),
    'countertop-distiller':    (300, 300, 400),
    'berkey-gravity':          (300, 300, 550),
    # 3D-printed ceramic
    'tpms-ceramic-microfilter':(100, 100, 150),
    # Soda-can scale micro-stages (each <66 mm × <66 mm × <168 mm,
    # i.e. fits inside a 500 mL aluminum can)
    'micro-hollow-fiber':       (25,  25, 130),
    'micro-mixed-bed-ix':       (40,  40, 100),
    'micro-gac-cartridge':      (30,  30, 100),
    'forward-osmosis-pouch':    (50,  35, 160),
    'micro-urea-hydrolysis':    (30,  30,  80),
    'ammonia-electrolyzer':     (60,  60,  30),
    'mabr-cartridge':           (50,  40,  60),
    'anammox-cartridge':        (60,  40,  80),
    'forward-osmosis-spiral':   (40,  30, 100),
    'micro-electrochem-polish': (60,  60,  40),
    # Permaculture / regenerative tier — plants and animals turning
    # contaminants into harvestable biomass.
    'comfrey-pot':              (300, 300, 500),
    'vermifilter':              (300, 300, 300),
    'duckweed-tray':            (500, 300, 100),
    'aquaponic-bed':            (600, 400, 400),
    'brine-shrimp-tank':        (300, 300, 400),
    # Ecosystem-style stages
    'oyster-mushroom-bed':      (400, 300, 400),  # mycoremediation
    'banana-ring':              (600, 600, 800),  # tropical canopy
    'papaya-tree':              (500, 500, 800),  # tropical fruit
    'salicornia-bed':           (600, 400, 200),  # halophyte
    'algae-photobioreactor':    (400, 100, 800),  # vertical tube
    'bsf-larvae-bin':           (400, 300, 200),  # insect protein
    'nettle-patch':             (400, 400, 600),  # cool-temperate accumulator
    'mediterranean-herb-bed':   (500, 400, 300),  # dry-tolerant
    # Apartment-wall scale (compact ecosystem)
    'micro-vermifilter':        (200, 200, 200),
    'microgreens-tray':         (400, 200, 100),
    'mini-algae-tube':          (200, 100, 800),
}


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
    # --- Soda-can-scale micro stages ---------------------------------
    # Each fits inside a standard 500 mL aluminium can (~66 mm Ø ×
    # 168 mm). Useful as a thought-experiment for "what's the smallest
    # urine-to-something-drinkable system?" The honest answer for
    # EU-potable: none of these alone, and 500 mL of total assembly
    # volume is below the physical floor for that target.
    dict(
        slug='micro-hollow-fiber',
        name='Micro hollow-fiber filter (LifeStraw-class)',
        kind='membrane',
        description='25 mm × 130 mm 0.1 µm hollow-fiber cartridge. '
                    'Removes bacteria, protozoa, and ~half of viruses '
                    'by size exclusion. Backflushable, multi-thousand-'
                    'litre lifetime. Does nothing for dissolved '
                    'solutes — salts, urea, ammonia, hormones all pass '
                    'straight through.',
        removal={'bacteria': 0.99999, 'protozoa': 0.99999,
                 'viruses': 0.50, 'turbidity': 0.95},
        flow_lpm=0.4, energy_watts=0.0,
        cost_eur=15.0, maintenance_days=365,
    ),
    dict(
        slug='micro-mixed-bed-ix',
        name='Micro mixed-bed ion-exchange column',
        kind='ion_exchange',
        description='40 mm × 100 mm column packed with mixed-bed '
                    'cation/anion resin. Captures NH₄⁺, Na⁺, K⁺, '
                    'and some nitrate; saturates fast (~50 bed '
                    'volumes for ammonium). Single-use at this size '
                    '— pop the cartridge, regenerate with brine + '
                    'caustic, reload.',
        removal={'ammonia': 0.95, 'sodium': 0.60, 'potassium': 0.60,
                 'nitrate': 0.50, 'lead': 0.80, 'creatinine': 0.40},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=25.0, maintenance_days=14,
    ),
    dict(
        slug='micro-gac-cartridge',
        name='Micro activated-carbon cartridge',
        kind='adsorption',
        description='30 mm × 100 mm coconut-shell GAC cartridge. '
                    'Catches organics — VOC, hormones, pharma, '
                    'chlorine. Limited capacity at this size; good '
                    'for a few litres before breakthrough. No effect '
                    'on dissolved inorganics or urea.',
        removal={'voc': 0.85, 'chlorine': 0.95,
                 'pharma': 0.75, 'hormones': 0.80, 'pfas': 0.30},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=12.0, maintenance_days=30,
    ),
    dict(
        slug='forward-osmosis-pouch',
        name='Forward-osmosis pouch (sugar draw)',
        kind='membrane',
        description='LifeStraw-HydroPack-class semi-permeable pouch '
                    'with a concentrated sugar draw solution inside. '
                    'Water moves osmotically across the TFC membrane '
                    'into the draw, leaving most solutes behind. The '
                    'output is dilute sugar water, drinkable in '
                    'emergencies but not pure water — and not EU-'
                    'compliant. Single-use; the pouch fills then '
                    'becomes the rehydration drink. Urea passes more '
                    'than salts (small, uncharged), so a kidney-load '
                    'flag is appropriate downstream.',
        removal={'tds': 0.99, 'sodium': 0.99, 'potassium': 0.99,
                 'creatinine': 0.98, 'phosphate': 0.99,
                 'lead': 0.99, 'arsenic': 0.99,
                 'urea': 0.40, 'ammonia': 0.60, 'nitrate': 0.92,
                 'pharma': 0.95, 'hormones': 0.92,
                 'bacteria': 0.9999999, 'viruses': 0.99999,
                 'protozoa': 0.9999999, 'turbidity': 0.99},
        flow_lpm=0.05, energy_watts=0.0,
        cost_eur=30.0, maintenance_days=1,
    ),
    dict(
        slug='forward-osmosis-spiral',
        name='Forward-osmosis spiral cartridge (compact, multi-use)',
        kind='membrane',
        description='Spiral-wound TFC FO module — same selective '
                    'membrane as a HydroPack but rolled into a 40×30×'
                    '100 mm cartridge with continuous-flow draw '
                    'circuit (concentrated salt or sugar regenerated '
                    'in a side bottle). 50 % smaller than the '
                    'single-use pouch with the same membrane area; '
                    'multi-use, indefinitely refillable. The compact-'
                    'system equivalent of the pouch when you have '
                    'capacity to recharge the draw.',
        removal={'tds': 0.99, 'sodium': 0.99, 'potassium': 0.99,
                 'creatinine': 0.98, 'phosphate': 0.99,
                 'lead': 0.99, 'arsenic': 0.99,
                 'urea': 0.40, 'ammonia': 0.60, 'nitrate': 0.92,
                 'pharma': 0.95, 'hormones': 0.92,
                 'bacteria': 0.9999999, 'viruses': 0.99999,
                 'protozoa': 0.9999999, 'turbidity': 0.99},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=60.0, maintenance_days=365,
    ),
    dict(
        slug='micro-electrochem-polish',
        name='Compact BDD electrochemical polish',
        kind='chemical',
        description='60×60×40 mm boron-doped-diamond electrode cell. '
                    'Generates hydroxyl radicals at the anode that '
                    'mineralise organics — pharma, hormones, '
                    'creatinine, residual urea. Same chemistry as '
                    'the bench-scale electrochem-oxidation stage at '
                    '1/150th the volume, lower per-pass removal '
                    'because contact time drops with the housing. '
                    '8 W; expensive electrodes (€140).',
        removal={'pharma': 0.95, 'hormones': 0.95, 'creatinine': 0.92,
                 'urea': 0.85, 'ammonia': 0.50,
                 'voc': 0.85, 'bacteria': 0.999},
        flow_lpm=0.15, energy_watts=8.0,
        cost_eur=140.0, maintenance_days=365,
    ),
    dict(
        slug='ammonia-electrolyzer',
        name='Compact ammonia electrolyzer (Pt/Ir anode)',
        kind='chemical',
        description='Anodic oxidation of NH₄⁺ → ½ N₂ at platinum-iridium '
                    'electrodes. The nitrogen leaves the system as inert '
                    'gas — the only mechanism here that physically '
                    'removes N rather than redistributing it. ~1 Wh/g '
                    'NH₄-N; 5 W draw at urine flow. 60×60×30 mm coin-'
                    'cell stack with TU-Delft / Magneto-Anodes-class '
                    'electrochemistry. Expensive electrodes (€60+).',
        removal={'ammonia': 0.99},
        flow_lpm=0.1, energy_watts=5.0,
        cost_eur=60.0, maintenance_days=365,
    ),
    dict(
        slug='mabr-cartridge',
        name='Membrane-aerated biofilm reactor (MABR)',
        kind='biological',
        description='Hollow-fiber membranes carry O₂ inside; '
                    'nitrifying biofilm grows on the outer surface and '
                    'oxidises NH₄⁺ → NO₃⁻. Passive air diffusion → '
                    'zero electrical draw. The N stays in the water '
                    'as nitrate, but the EU nitrate limit is 11.3 mg/L '
                    '(as N), 22× more forgiving than ammonia\'s '
                    '0.5 mg/L — useful when paired with an FO/RO that '
                    'rejects nitrate well. Slow startup (1-2 weeks for '
                    'biofilm to mature).',
        removal={'ammonia': 0.95},
        # Mass-conserving: 1 mg NH4-N → 1 mg NO3-N (just speciation).
        converts={'ammonia': {'nitrate': 1.0}},
        flow_lpm=0.2, energy_watts=0.0,
        cost_eur=40.0, maintenance_days=180,
    ),
    dict(
        slug='anammox-cartridge',
        name='Anammox biofilm cartridge',
        kind='biological',
        description='Anaerobic ammonium oxidation: NH₄⁺ + NO₂⁻ → N₂ '
                    'gas. Same N-leaves-the-system trick as the '
                    'electrolyzer, biological flavour. Real wastewater '
                    'tech (Paques\' ANAMMOX®) miniaturised to a '
                    '60×40×80 mm cartridge. Zero power, zero '
                    'consumables. Slow startup — 4-8 weeks for the '
                    'biomass to establish — then steady-state N₂ '
                    'venting indefinitely. Needs a partial-nitrite '
                    'partner stream upstream (handled by a small '
                    'aerated side-stream, baked into cost). The biofilm '
                    'also hosts heterotrophic denitrifiers that consume '
                    'incoming nitrate → N₂ — useful chained downstream '
                    'of an MABR (which speciates ammonia to nitrate).',
        removal={'ammonia': 0.85, 'nitrate': 0.80},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=50.0, maintenance_days=180,
    ),
    dict(
        slug='micro-urea-hydrolysis',
        name='Micro urease biofilm cartridge',
        kind='biological',
        description='30 mm × 80 mm column packed with urease-immobilised '
                    'beads — same chemistry as the bench-scale Vuna '
                    'biofilm reactor, miniaturised for inline use. '
                    'Hydrolyses urea to ammonium carbonate; the '
                    'liberated NH₄⁺ then needs a downstream IX trap '
                    'or thermal pass to remove. Real research uses '
                    'urease-bead cartridges in clinical blood-urea '
                    'sensors; the same scale works for trickle '
                    'urine flow.',
        removal={'urea': 0.95},
        # 1 mg urea → 14×2/60 = 0.467 mg NH4-N (same as the bench
        # urea-hydrolysis reactor — N is conserved, just speciated).
        converts={'urea': {'ammonia': 0.467}},
        flow_lpm=0.2, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=60,
    ),

    # --- Permaculture / regenerative tier ---------------------------
    # Live plants and animals turning contaminants into harvestable
    # biomass. Per-pass removal is modest because contact time is
    # short relative to plant uptake kinetics — the strength of these
    # stages is the BYPRODUCT stream (food, fertilizer, fish, worms).
    # Sized for a "garden corner" of a lab; assumes recirculating
    # flow over days, not single-pass minutes.
    dict(
        slug='comfrey-pot',
        name='Comfrey pot (potted phytoremediation)',
        kind='biological',
        description='Symphytum officinale in a 30×30×50 cm pot, fed '
                    'on a slow trickle of pre-hydrolysed urine. '
                    'Comfrey is a famous "dynamic accumulator" — '
                    'taproot mines NPK and trace minerals; rhizosphere '
                    'microbes degrade some pharma + hormones. Harvest '
                    'leaves weekly for compost tea or chop-and-drop '
                    'mulch. Per-pass removal modest (kinetics-limited '
                    'on a single pass) but biomass output is real: '
                    '~50 g N + 80 g K + 15 g P captured per kg of '
                    'leaf harvested.',
        removal={'nitrate': 0.20, 'ammonia': 0.15, 'phosphate': 0.30,
                 'potassium': 0.20, 'hormones': 0.20,
                 'bacteria': 0.80, 'turbidity': 0.85},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=15.0, maintenance_days=14,
    ),
    dict(
        slug='vermifilter',
        name='Vermifilter (earthworm bed)',
        kind='biological',
        description='30×30×30 cm bin packed with coir + Eisenia '
                    'fetida (red wigglers). Water trickles through '
                    'the bed; worms ingest organic load + '
                    'microorganisms; vermicasts coat the substrate '
                    'and continue degrading hormones, pharma, and '
                    'pathogens. Harvest castings monthly — premium '
                    'fertilizer (N-P-K + humic acids); excess worms '
                    'feed chickens, fish, or amphibians. Real '
                    'wastewater technology (vermifiltration in '
                    'India, Kenya, Brazil pilots).',
        removal={'voc': 0.50, 'bacteria': 0.95, 'protozoa': 0.90,
                 'turbidity': 0.90, 'hormones': 0.30, 'pharma': 0.20},
        flow_lpm=0.3, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=30,
    ),
    dict(
        slug='duckweed-tray',
        name='Duckweed tray (Lemna minor)',
        kind='biological',
        description='Shallow 50×30×10 cm tray covered in a floating '
                    'mat of Lemna minor — the world\'s fastest-'
                    'growing flowering plant, doubles biomass every '
                    '24-48 h on N-rich water. Skim the mat weekly: '
                    'high-protein animal feed (chickens, fish, '
                    'rabbits, biogas substrate). Surface coverage '
                    'also blocks sunlight → suppresses algae and '
                    'mosquito larvae.',
        removal={'nitrate': 0.40, 'ammonia': 0.30, 'phosphate': 0.40,
                 'potassium': 0.20},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=10.0, maintenance_days=7,
    ),
    dict(
        slug='aquaponic-bed',
        name='Aquaponic bed (tilapia + leafy greens)',
        kind='biological',
        description='60×40×40 cm tank with tilapia or carp + a media '
                    'bed of leafy greens (lettuce, kale, basil) '
                    'grown hydroponically on the fish-tank water. '
                    'Fish convert dissolved organics and trickled-in '
                    'pre-hydrolysed urine into more fish; nitrifying '
                    'biofilm in the gravel converts NH₄⁺ → NO₃⁻ for '
                    'the plants. Small recirculation pump (5 W) '
                    'keeps the loop oxygenated. Outputs: edible '
                    'fish (~kg/month), edible greens (daily), '
                    'spent gravel as garden mulch.',
        removal={'nitrate': 0.50, 'ammonia': 0.40, 'phosphate': 0.40,
                 'potassium': 0.30,
                 'bacteria': 0.95, 'turbidity': 0.90},
        flow_lpm=0.5, energy_watts=5.0,
        cost_eur=60.0, maintenance_days=14,
    ),
    dict(
        slug='brine-shrimp-tank',
        name='Brine shrimp tank (FO reject sidestream)',
        kind='biological',
        description='30×30×40 cm tank for Artemia salina, fed on the '
                    'concentrated reject brine from a downstream FO '
                    'or RO stage (the brine is high-TDS — perfect '
                    'for shrimp). Not a treatment stage on the main '
                    'flow; this is a SIDESTREAM that turns the '
                    'system\'s waste concentrate into harvestable '
                    'live protein for fish food, aquarium feed, or '
                    'amphibian husbandry. ~20 g of dried brine '
                    'shrimp per litre of brine treated.',
        removal={'tds': 0.05, 'phosphate': 0.10, 'pharma': 0.10},
        flow_lpm=0.05, energy_watts=2.0,
        cost_eur=25.0, maintenance_days=14,
    ),
    dict(
        slug='oyster-mushroom-bed',
        name='Oyster mushroom mycoremediation bed',
        kind='biological',
        description='Pleurotus ostreatus on a 40×30×40 cm bed of '
                    'urine-soaked straw + cardboard. Mycelium '
                    'enzymatically degrades hormones, pharma, '
                    'aromatic organics — real research at the BlueTech '
                    'and Stamets labs. Fruiting flushes every 14 days '
                    'produce edible mushrooms (~200 g/flush). After '
                    '4-5 flushes, spent substrate goes to vermifilter '
                    'or directly to the garden as fungal mulch.',
        removal={'voc': 0.70, 'pharma': 0.40, 'hormones': 0.50,
                 'bacteria': 0.85, 'turbidity': 0.70,
                 'ammonia': 0.20, 'nitrate': 0.20},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=25.0, maintenance_days=14,
    ),
    dict(
        slug='banana-ring',
        name='Banana ring (tropical canopy crop)',
        kind='biological',
        description='Classic permaculture banana circle — a 60×60×80 cm '
                    'pit lined with mulch and ringed with 3-4 banana '
                    'plants (Musa spp.). Bananas are heavy K demanders '
                    'and tolerate high-N greywater inputs; tropical '
                    'wastewater treatment in Hawaii, Cuba, Sri Lanka. '
                    'Yields ~5-15 kg fruit per plant per year + '
                    'leaves for compost / wraps / animal fodder.',
        removal={'nitrate': 0.30, 'ammonia': 0.25, 'phosphate': 0.40,
                 'potassium': 0.50, 'bacteria': 0.80, 'turbidity': 0.85},
        flow_lpm=0.2, energy_watts=0.0,
        cost_eur=40.0, maintenance_days=60,
    ),
    dict(
        slug='papaya-tree',
        name='Papaya tree (fast tropical fruit)',
        kind='biological',
        description='Carica papaya in a 50×50×80 cm half-barrel. '
                    'Reaches productive size in 6-9 months from seed; '
                    'fruits within a year. Nitrogen-hungry, heat-'
                    'loving. Pairs naturally with the banana ring in '
                    'tropical climates. Yields ~30-50 fruits per '
                    'tree per year.',
        removal={'nitrate': 0.30, 'ammonia': 0.25, 'phosphate': 0.30,
                 'potassium': 0.20, 'bacteria': 0.75, 'turbidity': 0.80},
        flow_lpm=0.15, energy_watts=0.0,
        cost_eur=25.0, maintenance_days=60,
    ),
    dict(
        slug='salicornia-bed',
        name='Salicornia bed (sea asparagus on FO brine)',
        kind='biological',
        description='Salicornia europaea (samphire / sea asparagus) — '
                    'a salt-loving halophyte that thrives on the '
                    'reject brine from a downstream FO/RO stage. '
                    'Edible succulent stems harvested weekly for '
                    'salads and pickling; pioneer-stage tolerates '
                    'salinity up to seawater. Real saline-aquaculture '
                    'integration in coastal pilots (Eritrea, Mexico, '
                    'India).',
        removal={'tds': 0.40, 'sodium': 0.50, 'potassium': 0.30,
                 'nitrate': 0.40, 'ammonia': 0.30, 'phosphate': 0.30,
                 'bacteria': 0.70},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=14,
    ),
    dict(
        slug='algae-photobioreactor',
        name='Algae photobioreactor (Spirulina / Chlorella)',
        kind='biological',
        description='Vertical 40×10×80 cm clear-acrylic tube '
                    'cultivating Arthrospira platensis (spirulina) '
                    'or Chlorella vulgaris on hydrolysed urine. '
                    'High-protein single-cell biomass — spirulina is '
                    '60-70 % protein by dry weight. Harvest by '
                    'filter-decant weekly; dried powder is human-'
                    'edible (or feeds fish, chickens). NASA / Eden '
                    'Project research.',
        removal={'nitrate': 0.70, 'ammonia': 0.60, 'phosphate': 0.60,
                 'potassium': 0.30, 'bacteria': 0.90,
                 'turbidity': 0.50},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=60.0, maintenance_days=14,
    ),
    dict(
        slug='bsf-larvae-bin',
        name='Black soldier fly larvae bin',
        kind='biological',
        description='Hermetia illucens larvae in a 40×30×20 cm '
                    'cascade bin, fed on protein-rich byproducts '
                    'from the chain (vermifilter overflow, spent '
                    'algae, mushroom substrate). Larvae self-harvest '
                    'by crawling out the angled drain when ready to '
                    'pupate; 40-45 % protein, 30 % fat — premium '
                    'feed for fish, chickens, reptiles. Real '
                    'circular-economy tech (Kenya, Indonesia, EU '
                    'pilots).',
        removal={'voc': 0.70, 'hormones': 0.40, 'pharma': 0.30,
                 'turbidity': 0.85, 'bacteria': 0.95,
                 'ammonia': 0.20},
        flow_lpm=0.2, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=14,
    ),
    dict(
        slug='nettle-patch',
        name='Stinging nettle patch (Urtica dioica)',
        kind='biological',
        description='Cool-temperate counterpart to comfrey — a '
                    'patch of Urtica dioica in a 40×40×60 cm bed. '
                    'Even more aggressive N + Fe accumulator than '
                    'comfrey; cut-and-come-again 4-6 times per '
                    'season for soup, tea, fermented liquid '
                    'fertilizer, or chicken fodder (cooked). '
                    'Self-spreads via rhizomes; tolerates partial '
                    'shade.',
        removal={'nitrate': 0.25, 'ammonia': 0.20, 'phosphate': 0.30,
                 'potassium': 0.25, 'iron': 0.60,
                 'bacteria': 0.80, 'turbidity': 0.80},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=10.0, maintenance_days=21,
    ),
    dict(
        slug='mediterranean-herb-bed',
        name='Mediterranean herb bed (rosemary / thyme / lavender)',
        kind='biological',
        description='Drought-tolerant aromatic herb bed in a 50×40×30 '
                    'cm raised planter — Rosmarinus officinalis, '
                    'Thymus vulgaris, Lavandula angustifolia, Salvia '
                    'officinalis. Lower N uptake than nettle or '
                    'comfrey but the byproducts are essential oils '
                    '(steam-distill the cuttings) and culinary herbs. '
                    'Pollinator-supporting. Survives on diluted urine '
                    'inputs that would burn leafier plants.',
        removal={'nitrate': 0.15, 'ammonia': 0.10, 'phosphate': 0.20,
                 'potassium': 0.15, 'hormones': 0.15,
                 'bacteria': 0.75, 'turbidity': 0.80},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=20.0, maintenance_days=30,
    ),
    dict(
        slug='micro-vermifilter',
        name='Under-sink micro vermifilter',
        kind='biological',
        description='8 L bin packed with Eisenia fetida — same '
                    'biology as the full-size vermifilter, scaled '
                    'down to fit under a kitchen sink. Smaller worm '
                    'population means smaller monthly castings '
                    'harvest (~50 g of vermicompost) but the per-'
                    'pass biology is identical. Top up bedding '
                    'every 6-8 weeks.',
        removal={'voc': 0.50, 'bacteria': 0.95, 'protozoa': 0.90,
                 'turbidity': 0.90, 'hormones': 0.30, 'pharma': 0.20},
        flow_lpm=0.15, energy_watts=0.0,
        cost_eur=10.0, maintenance_days=45,
    ),
    dict(
        slug='microgreens-tray',
        name='Microgreens hydroponic tray',
        kind='biological',
        description='Shallow 40×20×10 cm tray for fast-growing '
                    'microgreens — radish, pea shoots, sunflower '
                    'sprouts, mustard, basil. 7-14 day harvest '
                    'cycle; 200-300 g of greens per cycle per tray. '
                    'Stackable for vertical wall mounting. Lower '
                    'N uptake than full-size aquaponic but the '
                    'culinary value per gram is high.',
        removal={'nitrate': 0.30, 'ammonia': 0.25, 'phosphate': 0.30,
                 'potassium': 0.20, 'bacteria': 0.85, 'turbidity': 0.85},
        flow_lpm=0.1, energy_watts=0.0,
        cost_eur=5.0, maintenance_days=14,
    ),
    dict(
        slug='mini-algae-tube',
        name='Wall-mounted mini algae tube',
        kind='biological',
        description='Slim 20×10×80 cm clear-acrylic vertical tube '
                    'cultivating spirulina or chlorella. Wall-mount '
                    'orientation maximises light collection while '
                    'minimising floor footprint. Half the throughput '
                    'of the full photobioreactor (~6 g protein per '
                    'L treated) but designed to share a sunny '
                    'kitchen window with herbs. Weekly harvest by '
                    'filter-decant.',
        removal={'nitrate': 0.50, 'ammonia': 0.40, 'phosphate': 0.40,
                 'potassium': 0.20, 'bacteria': 0.85,
                 'turbidity': 0.40},
        flow_lpm=0.08, energy_watts=0.0,
        cost_eur=25.0, maintenance_days=14,
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
        slug='field-emergency-drinkable',
        name='Field-emergency drinkable (not EU-potable)',
        scope='target',
        notes='Relaxed survival-mode target — single-dose, "this won\'t '
              'kill you in 24 hours," not a long-term ration. '
              'Pathogens still strict (sterile water); dissolved '
              'solute limits 100-1000× looser than EU. Use this as '
              'the pass/fail spec for soda-can-scale systems where '
              'the EU urine-reuse target is physically unreachable.',
        values={
            'turbidity':   5.0,
            'tds':      3000.0,
            'bacteria':    0.0,
            'viruses':     0.0,
            'protozoa':    0.0,
            'urea':      200.0,         # kidney burden, but single-dose tolerable
            'ammonia':   200.0,         # tastes terrible, not acutely toxic
            'creatinine': 100.0,
            'phosphate': 100.0,
            'sodium':   1000.0,
            'potassium': 500.0,
            'hormones':  500.0,
            'pharma':   5000.0,
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
            spec = dict(spec)
            dims = STAGE_DIMENSIONS.get(spec['slug'])
            if dims:
                spec.setdefault('width_mm',  dims[0])
                spec.setdefault('depth_mm',  dims[1])
                spec.setdefault('height_mm', dims[2])
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

        # v8 — soda-can-scale chain. Forward-osmosis pouch with sugar
        # draw + a mixed-bed ion-exchange micro-column = 440 mL total
        # (fits inside a 500 mL aluminium can with margin). Output
        # passes the field-emergency target (drinkable in a survival
        # context, not long-term ration); does NOT meet EU spec —
        # urea, hormones, and ammonia all sit well above EU limits.
        # The honest physical floor for can-scale urine treatment.
        urine_v8_target = WaterProfile.objects.get(
            slug='field-emergency-drinkable')
        urine_v8, urine_v8_created = System.objects.update_or_create(
            slug='urine-to-drinking-v8-soda-can', defaults=dict(
                name='Urine → Drinkable (v8 soda-can emergency)',
                description='Smallest possible urine-to-drinkable '
                            'assembly: a forward-osmosis pouch (sugar '
                            'draw, water moves osmotically into a '
                            'concentrated solution) followed by a '
                            'mixed-bed ion-exchange cartridge. 440 mL '
                            'total, fits inside a 500 mL aluminium '
                            'can. Output is dilute sugar water with '
                            'residual urea, ammonia, and hormones at '
                            '100× the EU drinking limit but inside '
                            'the field-emergency window. NOT EU-'
                            'potable; survival-mode only.',
                source=urine_src, target=urine_v8_target,
            ))
        if urine_v8_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'forward-osmosis-pouch',
                'micro-mixed-bed-ix',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v8, stage_type=st, position=i)

        # v9 — tall-can scale (~700 mL envelope). Adds a urease
        # biofilm cartridge upstream of the FO pouch (knocks urea
        # before it gets to the membrane) plus a GAC polish + a
        # hollow-fiber pathogen redundancy stage. ~683 mL total —
        # fits in a 24 oz (710 mL) tall can. Closer to "habitual-use
        # drinkable" than v8: still NOT EU-potable (urea, ammonia,
        # hormones remain above EU caps) but order-of-magnitude
        # better than v8 on most residuals.
        urine_v9, urine_v9_created = System.objects.update_or_create(
            slug='urine-to-drinking-v9-tall-can', defaults=dict(
                name='Urine → Drinkable (v9 tall-can enhanced)',
                description='Urease cartridge → forward-osmosis pouch '
                            '→ mixed-bed IX → activated-carbon polish '
                            '→ hollow-fiber pathogen backstop. ~683 mL '
                            'total, fits in a 24 oz tall can. '
                            'Significantly cleaner than v8 — urea '
                            'pre-hydrolysed before the membrane, '
                            'pharma/hormones knocked back by GAC, '
                            'pathogens get a second-line membrane '
                            'after FO. Still not EU-potable on urea '
                            'and ammonia residuals; closer to '
                            '"habitual-use drinkable" than emergency.',
                source=urine_src, target=urine_v8_target,
            ))
        if urine_v9_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'forward-osmosis-pouch',
                'micro-mixed-bed-ix',
                'micro-gac-cartridge',
                'micro-hollow-fiber',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v9, stage_type=st, position=i)

        # v10 — smallest EU-compliant urine→drinking chain. Adds two
        # ammonia electrolyzers (the only mechanism in the catalog
        # that physically removes N from the can — Pt/Ir anodic
        # oxidation to N₂ gas) plus a second FO pouch and double
        # GAC polish for hormones / pharma. ~1.34 L envelope (think
        # tall thermos), ~10 W draw (small Li-ion battery), €277.
        # Fully passes the EU urine-reuse target.
        urine_v10, urine_v10_created = System.objects.update_or_create(
            slug='urine-to-drinking-v10-electrolytic', defaults=dict(
                name='Urine → Drinking (v10 thermos electrolytic)',
                description='Smallest EU-potable urine system. Two '
                            'urease cartridges convert all the urea; '
                            'two ammonia electrolyzers vent the '
                            'liberated N₂ (the trick — N actually '
                            'leaves the can rather than being moved '
                            'around); two forward-osmosis pouches '
                            'separate the bulk dissolved solutes; '
                            'mixed-bed IX traps residual ammonium; '
                            'two micro-GAC cartridges polish '
                            'hormones and pharma below EU detection; '
                            'hollow-fiber backstop on pathogens. '
                            '~1.34 L envelope, 10 W (battery-'
                            'powered), passes the full EU urine-'
                            'reuse target.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v10_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'ammonia-electrolyzer',
                'ammonia-electrolyzer',
                'forward-osmosis-pouch',
                'micro-mixed-bed-ix',
                'forward-osmosis-pouch',
                'micro-gac-cartridge',
                'micro-gac-cartridge',
                'micro-hollow-fiber',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v10, stage_type=st, position=i)

        # v11 — sub-litre EU-potable. Three improvements over v10:
        # (a) compact spiral-wound FO cartridges replace the bulky
        # single-use pouches (saves 80 mL each); (b) a third
        # electrolyzer pass eliminates the IX stage entirely (the
        # third electrolyzer brings ammonia to 90 µg/L on its own,
        # then the downstream FO pair finishes the job); (c) drop
        # the hollow-fiber backstop — two FO cartridges with TFC
        # membranes already drive bacteria below detection (1e-14
        # CFU). 888 mL, fits in a 1 L Nalgene with 100 mL of head
        # space. €364, 15 W (small Li-ion battery). Passes the full
        # EU urine-reuse target with comfortable margin.
        urine_v11, urine_v11_created = System.objects.update_or_create(
            slug='urine-to-drinking-v11-nalgene', defaults=dict(
                name='Urine → Drinking (v11 sub-litre Nalgene)',
                description='Smallest known EU-compliant chain. Two '
                            'urease cartridges, three ammonia '
                            'electrolyzers (the third replaces v10\'s '
                            'IX stage at lower volume cost), two '
                            'compact spiral-wound FO cartridges (50 % '
                            'smaller than the single-use pouches at '
                            'the same membrane area), two micro-GAC '
                            'polishes for hormones and pharma. No '
                            'pathogen backstop needed — two FO passes '
                            'with TFC membranes already drive '
                            'bacteria 14 orders below detection. '
                            '888 mL (fits in a 1 L Nalgene), 15 W '
                            '(small Li-ion battery), passes the full '
                            'EU urine-reuse target.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v11_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'ammonia-electrolyzer',
                'ammonia-electrolyzer',
                'ammonia-electrolyzer',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'micro-gac-cartridge',
                'micro-gac-cartridge',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v11, stage_type=st, position=i)

        # v12 — under three-quarter litre. The compact BDD electro-
        # chemical polish does the work of v11's two GACs in a
        # single stage (mineralises hormones, pharma, creatinine,
        # residual urea via hydroxyl radicals); BDD also removes
        # ~50 % of ammonia per pass, so v11's third electrolyzer is
        # no longer needed. Net 7 stages, 744 mL — fits in a 750 mL
        # wine bottle. €420, 18 W. Passes the full EU urine-reuse
        # target.
        urine_v12, urine_v12_created = System.objects.update_or_create(
            slug='urine-to-drinking-v12-wine-bottle', defaults=dict(
                name='Urine → Drinking (v12 wine-bottle compact)',
                description='Two urease cartridges, two ammonia '
                            'electrolyzers, one BDD electrochemical '
                            'polish (handles pharma + hormones + '
                            'creatinine + residual ammonia via '
                            'hydroxyl-radical mineralisation), two '
                            'spiral-wound FO cartridges. 744 mL, '
                            'fits in a 750 mL wine bottle. 7 stages, '
                            '€420, 18 W. The BDD anode replaces both '
                            'GAC polishes and one electrolyzer at '
                            'lower total volume.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v12_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'ammonia-electrolyzer',
                'ammonia-electrolyzer',
                'micro-electrochem-polish',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v12, stage_type=st, position=i)

        # v13 — under 700 mL. Drop one urea-hydrolysis cartridge and
        # let the BDD electrochem mop up the residual urea (10 mg/L
        # after one urea-hyd, then × 0.15 in electrochem, then × 0.36
        # through the FO pair = 0.54 mg/L, comfortably under EU 2).
        # 6 stages, 672 mL — fits in a 24 oz tall can or a small
        # thermos. €380, 18 W. Smallest known urine-to-EU-potable
        # configuration in the catalog.
        urine_v13, urine_v13_created = System.objects.update_or_create(
            slug='urine-to-drinking-v13-minimal', defaults=dict(
                name='Urine → Drinking (v13 minimal EU-compliant)',
                description='Smallest EU-potable urine system in the '
                            'catalog. Single urease cartridge, two '
                            'ammonia electrolyzers, one BDD electro-'
                            'chemical polish, two compact spiral FO '
                            'cartridges. 672 mL, 6 stages, €380, '
                            '18 W. Fits inside a 24 oz tall can. '
                            'The BDD anode is doing four jobs at '
                            'once: residual-urea mineralisation, '
                            'pharma + hormones + creatinine '
                            'oxidation, and ~50 % of remaining '
                            'ammonia.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v13_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'ammonia-electrolyzer',
                'ammonia-electrolyzer',
                'micro-electrochem-polish',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v13, stage_type=st, position=i)

        # v14 — sub-1L EU-potable with ZERO electricity. Trades the
        # battery-powered electrolyzers for passive membrane-aerated
        # biofilm reactors (MABR) — these convert NH₄⁺ → NO₃⁻
        # biologically. Three MABR passes drop ammonia to <1 mg/L;
        # the FO TFC membrane then rejects both residual ammonia and
        # the produced nitrate (~92 % per pass). Three FO passes
        # finish the dissolved-solute knockdown; one micro-GAC for
        # the hormone tail. 9 stages, 954 mL, €352, 0 W. Caveat:
        # 1-2 weeks for the biofilm to mature on first deployment.
        urine_v14, urine_v14_created = System.objects.update_or_create(
            slug='urine-to-drinking-v14-zero-power-litre', defaults=dict(
                name='Urine → Drinking (v14 zero-power 1 L)',
                description='Zero-electricity EU-potable urine system. '
                            'Two urease cartridges, three MABR '
                            'cartridges (passive nitrification: O₂ '
                            'diffuses through hollow-fiber membranes, '
                            'biofilm oxidises NH₄⁺ to NO₃⁻), three '
                            'spiral-wound FO cartridges (reject '
                            'residual ammonia + the produced '
                            'nitrate), one micro-GAC for hormone '
                            'polish. 954 mL — fits in a 1 L bottle. '
                            '9 stages, €352, 0 W. Slow startup (1-2 '
                            'weeks for the MABR biofilm to mature) '
                            'then steady-state forever after. The '
                            'off-grid counterpart to v13.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v14_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'mabr-cartridge',
                'mabr-cartridge',
                'mabr-cartridge',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'micro-gac-cartridge',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v14, stage_type=st, position=i)

        # v15 — anammox-hybrid alternative to v14. Two MABRs do the
        # bulk NH4 → NO3 conversion (fast, compact), then a single
        # anammox cartridge with a co-cultured denitrifying biofilm
        # vents the nitrogen as N₂ gas — leaving the system instead
        # of being concentrated in the FO reject brine. Two FO passes
        # finish the job. 8 stages, 1026 mL — slightly over 1 L, the
        # cost of the anammox path. €352, 0 W. The differentiator vs
        # v14 isn't volume but waste-stream chemistry: v15's brine is
        # essentially nitrogen-free, useful for closed-loop systems
        # or where the brine gets reused (struvite, fertilizer).
        urine_v15, urine_v15_created = System.objects.update_or_create(
            slug='urine-to-drinking-v15-anammox-hybrid', defaults=dict(
                name='Urine → Drinking (v15 anammox N₂-vent hybrid)',
                description='Zero-power EU-potable with nitrogen '
                            'leaving as N₂ gas instead of '
                            'concentrating in the FO reject brine. '
                            'Two urease cartridges, two MABRs (NH₄⁺ '
                            '→ NO₃⁻), one anammox cartridge with '
                            'denitrifying co-population (NH₄⁺ + NO₃⁻ '
                            '→ N₂ gas), three FO cartridges, one '
                            'GAC. 1026 mL, 9 stages, €352, 0 W. '
                            'Costs +72 mL vs v14, gains a clean '
                            'reject-brine stream. Slow biofilm '
                            'startup (3-6 weeks for MABR + 6-8 for '
                            'anammox to mature in series).',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v15_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'mabr-cartridge',
                'mabr-cartridge',
                'anammox-cartridge',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'micro-gac-cartridge',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v15, stage_type=st, position=i)

        # v16 — the "garden corner" ecosystem. Urine → fish + greens
        # + worm castings + duckweed feed + comfrey mulch + clean
        # irrigation water. Output water is irrigation/aquaponic-
        # grade (NOT EU-potable: ammonia residual ~600 mg/L; for
        # drinking-grade output, follow with v14's polish train).
        # The point isn't compactness — it's that the urine pipeline
        # becomes a productive permaculture system rather than a
        # waste-destruction one.
        irrig_target = WaterProfile.objects.get(slug='irrigation')
        urine_v16, urine_v16_created = System.objects.update_or_create(
            slug='urine-to-garden-v16-ecosystem', defaults=dict(
                name='Urine → Garden Ecosystem (v16 productive cycle)',
                description='Urine becomes biomass. Two urease '
                            'cartridges → vermifilter (red wigglers, '
                            'monthly castings harvest) → aquaponic '
                            'bed (tilapia + leafy greens) → duckweed '
                            'tray (skimmed weekly for animal feed) → '
                            'comfrey pot (leaf harvest for compost '
                            'tea) → ceramic pot filter (final '
                            'pathogen polish). Output: '
                            'irrigation-grade water + ~kg/month '
                            'fish, daily greens, weekly comfrey '
                            'mulch + duckweed, monthly vermicompost. '
                            '~210 L assembly volume — closer to a '
                            'garden corner than a kitchen counter, '
                            'but every gram of nitrogen leaves as '
                            'something edible or useful instead of '
                            'as brine.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v16_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'vermifilter',
                'aquaponic-bed',
                'duckweed-tray',
                'comfrey-pot',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v16, stage_type=st, position=i)

        # v17 — v16's productive ecosystem with v14's EU-polish tail
        # bolted on. The biology takes the bulk of the urine's
        # nitrogen / phosphorus / potassium and turns it into fish,
        # greens, worm castings, comfrey, and duckweed. Whatever the
        # plants and animals couldn't reach (residual ammonia, the
        # last of the hormones / pharma, dissolved salts) gets
        # finished off by 3× MABR + 3× FO-spiral + 1× GAC. Output is
        # full EU-potable drinking water AND the ecosystem
        # byproducts on the same pipeline. ~200 L assembly volume,
        # 13 stages, €457, 5 W (the aquaponic pump). The "have it
        # both ways" tier.
        urine_v17, urine_v17_created = System.objects.update_or_create(
            slug='urine-to-drinking-v17-garden-plus-polish', defaults=dict(
                name='Urine → Drinking + Garden (v17 ecosystem + polish)',
                description='Full-circle system: v16\'s permaculture '
                            'front-end (vermifilter → aquaponics → '
                            'duckweed → comfrey → ceramic candle) '
                            'pulls most of the nitrogen / phosphate / '
                            'potassium out as harvestable biomass; '
                            'three MABR cartridges plus three '
                            'spiral-wound FO cartridges plus a GAC '
                            'polish on the back end finish off '
                            'whatever the biology left behind. '
                            'Output: EU-potable drinking water AND '
                            'fish, greens, vermicompost, duckweed, '
                            'comfrey leaves on the same pipeline. '
                            '~200 L (a garden corner), €457, 5 W. '
                            'Slow startup (weeks for biofilm + fish '
                            'maturation) then steady-state forever.',
                source=urine_src, target=urine_tgt,
            ))
        if urine_v17_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'vermifilter',
                'aquaponic-bed',
                'duckweed-tray',
                'comfrey-pot',
                'mabr-cartridge',
                'mabr-cartridge',
                'mabr-cartridge',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'forward-osmosis-spiral',
                'micro-gac-cartridge',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v17, stage_type=st, position=i)

        # v18 — mycoremediation ecosystem. Mushrooms are the
        # decomposers; oyster mycelium does the heavy work on
        # hormones, pharma, and aromatic organics that plants don't
        # touch. Pair with nettle (cool-temperate N accumulator) and
        # vermifilter to close the cycle. Produces mushrooms +
        # nettle (soup, tea, fertilizer) + vermicompost; output
        # water is irrigation-grade.
        urine_v18, urine_v18_created = System.objects.update_or_create(
            slug='urine-to-garden-v18-fungal', defaults=dict(
                name='Urine → Garden (v18 fungal mycoremediation)',
                description='Mushroom-led ecosystem. Two urease '
                            'cartridges → vermifilter → oyster-'
                            'mushroom bed (mycelium degrades '
                            'hormones, pharma, aromatics) → nettle '
                            'patch (cool-temperate N accumulator) '
                            '→ duckweed → ceramic candle. Outputs: '
                            'mushrooms (~200 g/flush, 4-5 flushes), '
                            'nettle cuttings (soup, tea, liquid '
                            'fertilizer), worm castings, duckweed. '
                            'For temperate climates that can\'t '
                            'support tropical fruit. 6 stages, '
                            '~80 L, €92, 0 W.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v18_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'vermifilter',
                'oyster-mushroom-bed',
                'nettle-patch',
                'duckweed-tray',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v18, stage_type=st, position=i)

        # v19 — tropical fruit forest. Banana ring + papaya tree
        # carry the bulk N/P/K demand; comfrey + duckweed polish.
        # Highest biomass yield of any ecosystem in the catalog —
        # bananas are ~5-15 kg/plant/year, papaya ~30-50 fruits.
        # Suited to greenhouse, conservatory, or actual tropical
        # climate. Output water is irrigation-grade.
        urine_v19, urine_v19_created = System.objects.update_or_create(
            slug='urine-to-garden-v19-tropical', defaults=dict(
                name='Urine → Garden (v19 tropical fruit forest)',
                description='Banana ring + papaya canopy on the '
                            'bulk N/P/K stream. Two urease '
                            'cartridges → vermifilter → banana '
                            'ring (heavy K demander, ~5-15 kg fruit '
                            'per plant per year) → papaya tree '
                            '(N-hungry, ~30-50 fruits per year) → '
                            'comfrey pot → duckweed → ceramic '
                            'candle. Greenhouse / conservatory / '
                            'actual-tropics. ~610 L (a real corner '
                            'of a sunroom), 8 stages, €175, 0 W.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v19_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'vermifilter',
                'banana-ring',
                'papaya-tree',
                'comfrey-pot',
                'duckweed-tray',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v19, stage_type=st, position=i)

        # v20 — saline / coastal ecosystem. Built around the FO
        # reject brine: salicornia (sea asparagus) + brine shrimp
        # turn high-TDS waste into edible succulents and live
        # aquaculture feed. The freshwater main flow gets the
        # standard biology (vermifilter + duckweed); pair with v14
        # downstream if drinking-water output is needed.
        urine_v20, urine_v20_created = System.objects.update_or_create(
            slug='urine-to-garden-v20-coastal', defaults=dict(
                name='Urine → Garden (v20 coastal halophyte)',
                description='Salt-tolerant ecosystem. Two urease '
                            'cartridges → vermifilter → forward-'
                            'osmosis pouch (the FO reject brine '
                            'feeds the next two stages — salicornia '
                            'bed (edible sea asparagus) and brine-'
                            'shrimp tank (live aquarium feed)). '
                            'Main freshwater stream: duckweed → '
                            'ceramic candle. Suited to arid/coastal '
                            'use where salinity is plentiful and '
                            'salt-tolerant crops have a market. '
                            '7 stages, ~115 L, €164, 2 W.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v20_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'vermifilter',
                'forward-osmosis-pouch',
                'salicornia-bed',
                'brine-shrimp-tank',
                'duckweed-tray',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v20, stage_type=st, position=i)

        # v21 — protein factory. Algae + black soldier fly larvae
        # convert the urine stream into single-cell protein
        # (spirulina, ~60-70 % protein) and insect protein (BSF
        # larvae, ~40-45 % protein, harvested as live or dried fish/
        # chicken feed). Vermifilter recycles the algae harvest
        # residue. The most calorie-dense ecosystem option —
        # designed for off-grid food security rather than fresh
        # produce.
        urine_v21, urine_v21_created = System.objects.update_or_create(
            slug='urine-to-garden-v21-protein', defaults=dict(
                name='Urine → Garden (v21 algae + insect protein)',
                description='High-protein output ecosystem. Two '
                            'urease cartridges → algae photo-'
                            'bioreactor (Spirulina ~60-70 % protein) '
                            '→ vermifilter (processes algae harvest '
                            'residue) → BSF larvae bin (~40-45 % '
                            'protein, fish/chicken feed) → duckweed '
                            'tray → comfrey pot → ceramic candle. '
                            'Vertically-oriented stages keep the '
                            'footprint small. 8 stages, ~155 L, '
                            '€212, 0 W.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v21_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'algae-photobioreactor',
                'vermifilter',
                'bsf-larvae-bin',
                'duckweed-tray',
                'comfrey-pot',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v21, stage_type=st, position=i)

        # v22 — Mediterranean dry-tolerant ecosystem. Lower water-
        # uptake plants (rosemary, thyme, lavender, comfrey) for
        # arid or warm-temperate regions where intensive irrigation
        # isn't practical. Output: aromatic herbs, essential oils,
        # honey-supporting flowers, and irrigation-grade water.
        urine_v22, urine_v22_created = System.objects.update_or_create(
            slug='urine-to-garden-v22-mediterranean', defaults=dict(
                name='Urine → Garden (v22 Mediterranean herb)',
                description='Aromatic, dry-climate ecosystem. Two '
                            'urease cartridges → vermifilter → '
                            'mediterranean herb bed (rosemary, '
                            'thyme, lavender, sage — pollinator-'
                            'supporting, low water demand) → '
                            'comfrey pot (the leafy outlier, '
                            'tolerates higher N) → duckweed (a '
                            'small shaded tray) → ceramic candle. '
                            'Outputs: culinary herbs daily, '
                            'essential oils (steam-distill the '
                            'cuttings), bee fodder. Warmer / drier '
                            'counterpart to v18. 7 stages, ~115 L, '
                            '€102, 0 W.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v22_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'vermifilter',
                'mediterranean-herb-bed',
                'comfrey-pot',
                'duckweed-tray',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v22, stage_type=st, position=i)

        # v23 — apartment-wall scale ecosystem (~70 L). Compact
        # variants of the bigger stages: under-sink worm bin,
        # wall-mounted algae tube, stackable microgreens tray,
        # small duckweed tray, ceramic candle. Designed for an
        # urban kitchen — the algae tube on a sunny wall, the
        # microgreens stacked on a cabinet, the worm bin under the
        # sink. Output: irrigation-grade water + spirulina powder
        # weekly + microgreens cycles + small worm compost.
        urine_v23, urine_v23_created = System.objects.update_or_create(
            slug='urine-to-garden-v23-apartment', defaults=dict(
                name='Urine → Garden (v23 apartment-wall compact)',
                description='Vertical / urban ecosystem — fits in a '
                            'kitchen corner. Two micro-urease '
                            'cartridges → under-sink micro-'
                            'vermifilter → wall-mounted mini-algae '
                            'tube (spirulina) → stacked microgreens '
                            'tray → small duckweed tray → ceramic '
                            'candle. Outputs: spirulina powder '
                            '(~6 g/L of treated urine), microgreens '
                            '(7-14 day cycles), small monthly worm '
                            'castings, duckweed for aquarium feed. '
                            '~64 L assembly volume — about the size '
                            'of a wine fridge. €92, 0 W.',
                source=urine_src, target=irrig_target,
            ))
        if urine_v23_created:
            from naiad.models import Stage
            for i, stype_slug in enumerate([
                'micro-urea-hydrolysis',
                'micro-urea-hydrolysis',
                'micro-vermifilter',
                'mini-algae-tube',
                'microgreens-tray',
                'duckweed-tray',
                'ceramic-pot-filter',
            ]):
                st = StageType.objects.get(slug=stype_slug)
                Stage.objects.create(
                    system=urine_v23, stage_type=st, position=i)

        self.stdout.write(self.style.SUCCESS(
            f'Naiad seed done: {st_n} stage types, {wp_n} profiles. '
            f'Sample systems: "{system.name}", '
            f'"{urine_system.name}", "{urine_v2.name}", '
            f'"{urine_v3.name}", "{urine_v4.name}", '
            f'"{urine_v5.name}", "{urine_v6.name}", '
            f'"{urine_v7.name}", "{urine_v8.name}", '
            f'"{urine_v9.name}", "{urine_v10.name}", '
            f'"{urine_v11.name}", "{urine_v12.name}", '
            f'"{urine_v13.name}", "{urine_v14.name}", '
            f'"{urine_v15.name}", "{urine_v16.name}", '
            f'"{urine_v17.name}", "{urine_v18.name}", '
            f'"{urine_v19.name}", "{urine_v20.name}", '
            f'"{urine_v21.name}", "{urine_v22.name}", '
            f'"{urine_v23.name}".'))

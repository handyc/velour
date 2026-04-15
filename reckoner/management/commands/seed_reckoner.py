"""Seed Reckoner with ~25 compute tasks and ~25 energy signposts.

All numbers are rough order-of-magnitude public estimates. Re-run
idempotently — existing rows are updated in place.
"""

from django.core.management.base import BaseCommand

from reckoner.models import ComputeTask, EnergyComparable


# ── Energy signposts ─────────────────────────────────────────
# (slug, name, icon, joules, note)
COMPARABLES = [
    ('neuron-spike',   'One neuron firing once',      '🧠',  5e-11,
     'A single action potential dissipates ~5 × 10⁻¹¹ J.'),
    ('mosquito-wing',  'One mosquito wingbeat',       '🦟',  1e-7,
     'Aerodynamic work per wing cycle at ~400 Hz.'),
    ('ant-step',       'One ant taking a step',       '🐜',  1e-5,
     'Rough muscular work of a fire-ant stride.'),
    ('eye-blink',      'A single eye blink',          '👁',  1e-2,
     'Levator palpebrae fires for ~300 ms; negligible but non-zero.'),
    ('keystroke',      'One keystroke',               '⌨',  1e-1,
     'Finger muscle plus mechanical switch.'),
    ('heartbeat',      'One human heartbeat',         '💓',  1.0,
     'About 1 J of mechanical work per beat.'),
    ('push-up',        'One push-up',                 '💪',  3e2,
     'Lifting a 70 kg torso ~40 cm.'),
    ('match-burned',   'A wooden match burned',       '🔥',  1e3,
     'Roughly 1 kJ of chemical energy.'),
    ('aa-battery',     'A fresh AA alkaline cell',    '🔋',  9e3,
     'About 2.5 Wh of stored energy.'),
    ('phone-charge',   'A full smartphone charge',    '📱',  5e4,
     '~14 Wh in a modern phone battery.'),
    ('kettle-boil',    'One kettle of water boiled',  '🫖',  3e5,
     'About 83 Wh to bring 1 L from 20 °C to boiling.'),
    ('candy-bar',      'One chocolate bar eaten',     '🍫',  1e6,
     '~240 kcal of food energy.'),
    ('hot-shower',     'A 10-minute hot shower',      '🚿',  5e6,
     'Heating ~80 L of water by 30 °C.'),
    ('daily-food',     "A human's daily food",        '🍽',  1e7,
     '~2,400 kcal; one day of eating.'),
    ('gallon-gas',     'One gallon of gasoline',      '⛽',  1.3e8,
     'The canonical chemical-energy reference.'),
    ('house-daily',    'A home, one day of power',    '🏠',  1.1e8,
     'About 30 kWh for a typical Western household.'),
    ('car-100km',      'A car driven 100 km',         '🚗',  3e8,
     'Gasoline engine at ~8 L/100 km.'),
    ('lightning',      'One lightning strike',        '⚡',  1e9,
     'A few hundred kWh dumped in milliseconds.'),
    ('jet-fuel-ton',   'One tonne of jet fuel',       '🛢',  4.3e10,
     'Aviation kerosene, ~43 MJ/kg.'),
    ('transat-flight', 'A transatlantic flight',      '✈',   2.5e11,
     'Per passenger, one-way AMS→JFK in a wide-body.'),
    ('small-town-day', 'A small town for a day',      '🏙',  1e12,
     '~300 MWh across ~10,000 homes.'),
    ('shuttle-launch', 'A space-shuttle launch',      '🚀',  1.3e13,
     'Total propellant energy of the SSMEs + SRBs.'),
    ('hiroshima',      'Hiroshima atomic bomb (1945)', '💥',  6.3e13,
     'Little Boy yield: ~15 kilotons of TNT.'),
    ('power-plant-yr', 'A 1 GW power plant, one year', '🏭',  3.2e16,
     'One nominal gigawatt-year of electricity.'),
    ('volcano',        'A moderate volcanic eruption', '🌋',  1e17,
     'Roughly the thermal output of a VEI-5 event.'),
    ('hurricane-day',  'A hurricane, one day',        '🌀',  5e17,
     'Latent-heat release of a mature tropical cyclone.'),
    ('sun-second',     'Sunlight reaching Earth, 1 s', '☀',  1.7e17,
     'Solar constant × disk area, per second.'),
]


# ── Compute tasks ────────────────────────────────────────────
# Each entry is a dict. `scores` is (env, pol, eco, soc).
TASKS = [
    dict(
        slug='add-two-ints', name='Adding two integers',
        category='arithmetic', energy_joules=4e-11,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='A single 64-bit integer addition on a modern CPU '
                    'consumes roughly 40 picojoules — the literal floor '
                    'of all computing.',
        environmental_note='Essentially nil. One addition in isolation '
                           'vanishes into background noise.',
        political_note='Neutral. Arithmetic itself is apolitical.',
        economic_note='Free, for all practical purposes.',
        social_note='Underpins every human activity that involves a '
                    'computer. Small but universal benefit.',
    ),
    dict(
        slug='multiply-two-floats', name='Multiplying two floats',
        category='arithmetic', energy_joules=1e-10,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='A single IEEE-754 double-precision multiply — '
                    'a few times the cost of an add, still picojoules.',
        environmental_note='Negligible.',
        political_note='Neutral.',
        economic_note='Free.',
        social_note='Backbone of graphics, science, finance.',
    ),
    dict(
        slug='hash-one-string', name='Hashing a short string',
        category='arithmetic', energy_joules=5e-8,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='A SHA-256 of a 32-byte string is a few thousand '
                    'ops — still measured in nanojoules.',
        environmental_note='Negligible.',
        political_note='Cryptographic primitive; protects dissidents '
                       'and enables authoritarian surveillance in '
                       'roughly equal measure.',
        economic_note='Free.',
        social_note='Load-bearing for modern security.',
    ),
    dict(
        slug='bash-echo', name='Running `echo hello` in bash',
        category='scripting', energy_joules=1e-3,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='Fork, exec, print, exit. About a millisecond of '
                    'CPU time plus kernel bookkeeping.',
        environmental_note='Negligible.',
        political_note='Neutral.',
        economic_note='Free.',
        social_note='The atom of shell automation.',
    ),
    dict(
        slug='python-hello', name='Running `python hello.py`',
        category='scripting', energy_joules=5e-1,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='Python startup dominates: ~200 ms of interpreter '
                    'spin-up on a 5 W laptop core.',
        environmental_note='Negligible per invocation. Matters at CI '
                           'scale: millions of runs a day add up.',
        political_note='Neutral.',
        economic_note='Free.',
        social_note='Gateway to programming for millions.',
    ),
    dict(
        slug='python-pandas', name='A small pandas script',
        category='scripting', energy_joules=2e1,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 2),
        description='Read a CSV, group-by, write a plot. A few seconds '
                    'of a laptop at 20 W.',
        environmental_note='Negligible per run.',
        political_note='Neutral.',
        economic_note='Free.',
        social_note='Daily bread for science and journalism.',
    ),
    dict(
        slug='sql-select', name='A simple SQL SELECT',
        category='db', energy_joules=5e-1,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='An indexed lookup in a warm database — microseconds '
                    'of CPU plus a little disk.',
        environmental_note='Negligible.',
        political_note='Neutral.',
        economic_note='Fractions of a cent at cloud scale.',
        social_note='Queries underlie every modern service.',
    ),
    dict(
        slug='sql-heavy', name='A heavy analytical SQL query',
        category='db', energy_joules=5e2,
        cost_eur=0.01, cost_usd=0.011, scores=(1, 0, 1, 2),
        description='A full-table scan over a few GB, a couple of joins, '
                    'a GROUP BY. Tens of seconds on a big warehouse node.',
        environmental_note='A coffee-spoon of coal per run at scale.',
        political_note='Neutral.',
        economic_note='Pennies per query, euros per dashboard refresh.',
        social_note='Drives the BI dashboards leaders rely on.',
    ),
    dict(
        slug='php-request', name='Serving one PHP request',
        category='web', energy_joules=2.0,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='A classical LAMP page render: parse, a couple of '
                    'DB calls, render, send. Sub-second on a shared host.',
        environmental_note='Negligible.',
        political_note='Neutral.',
        economic_note='Free at this scale.',
        social_note='Powers half the web; quietly essential.',
    ),
    dict(
        slug='django-request', name='Serving one Django request',
        category='web', energy_joules=5.0,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='A Python WSGI request with ORM, templating, and '
                    'middleware. A few joules per hit.',
        environmental_note='Negligible.',
        political_note='Neutral.',
        economic_note='Cents per thousand requests.',
        social_note='Velour itself runs on this.',
    ),
    dict(
        slug='webpage-light', name='Loading a plain web page',
        category='web', energy_joules=30.0,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 1),
        description='HTML, CSS, one image. Counts network, server, and '
                    'your own screen.',
        environmental_note='Negligible.',
        political_note='Neutral.',
        economic_note='Trivial.',
        social_note='The open web: the global commons.',
    ),
    dict(
        slug='webpage-heavy', name='Loading a heavy modern page',
        category='web', energy_joules=5e2,
        cost_eur=0.0, cost_usd=0.0, scores=(1, 1, 0, 0),
        description='Megabytes of JS, trackers, ads, video previews. '
                    'Orders of magnitude heavier than 1995.',
        environmental_note='Tracker-heavy pages measurably increase '
                           'end-user device energy and server fanout.',
        political_note='Ad-surveillance stack concentrates attentional '
                       'and political power.',
        economic_note='Externalises cost onto the viewer.',
        social_note='Accessibility suffers; low-end devices choke.',
    ),
    dict(
        slug='email-check', name='Checking an email inbox',
        category='web', energy_joules=50.0,
        cost_eur=0.0, cost_usd=0.0, scores=(0, 0, 0, 2),
        description='IMAP IDLE plus a sync of new messages. Seconds of '
                    'a small server plus the client render.',
        environmental_note='Small, but multiplied by billions of daily '
                           'checks.',
        political_note='Email remains a relatively federated medium.',
        economic_note='Free at the margin.',
        social_note='A critical infrastructure for coordination.',
    ),
    dict(
        slug='google-search', name='One Google search',
        category='web', energy_joules=1080.0,
        cost_eur=0.0, cost_usd=0.0, scores=(1, 2, 0, 2),
        description="Google's own figure: roughly 0.3 Wh per query, "
                    'all-in (datacenter + network share).',
        environmental_note='Small per search; enormous in aggregate.',
        political_note='Ranking power shapes discourse; a handful of '
                       'firms decide what billions find.',
        economic_note='Advertisers pay, users pay in attention.',
        social_note='The default on-ramp to human knowledge.',
    ),
    dict(
        slug='stream-1080p-min', name='Streaming 1 minute of 1080p video',
        category='media', energy_joules=3000.0,
        cost_eur=0.0, cost_usd=0.0, scores=(1, 1, 0, 1),
        description='CDN, ISP, and home router costs plus the viewing '
                    'device itself. ~1 Wh per minute.',
        environmental_note='Streaming is a double-digit share of '
                           'residential internet energy.',
        political_note='Platform gatekeeping of creators is structural.',
        economic_note='Cheap for viewer; capital-intensive for platform.',
        social_note='Common culture has partly moved here.',
    ),
    dict(
        slug='llm-small-query', name='One query to a small LLM',
        category='llm', energy_joules=500.0,
        cost_eur=0.0002, cost_usd=0.00025, scores=(1, 1, 1, 2),
        description='A mid-sized model (GPT-4o-mini / Haiku class) '
                    'answering a short prompt — hundreds of joules.',
        environmental_note='Small per query, non-trivial at billions '
                           'per day.',
        political_note='Model providers sit in a few jurisdictions.',
        economic_note='Fractions of a cent per call.',
        social_note='Broad productivity boost, uneven access.',
    ),
    dict(
        slug='llm-large-query', name='One query to a frontier LLM',
        category='llm', energy_joules=1.1e4,
        cost_eur=0.04, cost_usd=0.045, scores=(2, 2, 2, 2),
        description='GPT-4 / Claude Opus-scale inference: ~3 Wh per '
                    'non-trivial prompt.',
        environmental_note='Order of magnitude more water and power '
                           'per answer than a web search.',
        political_note='Frontier-model access concentrates epistemic '
                       'authority in very few companies.',
        economic_note='Pennies per call; hundreds of millions of users.',
        social_note='Genuine uplift for many; displacement risk for '
                    'knowledge workers.',
    ),
    dict(
        slug='llm-image-gen', name='Generating one image',
        category='llm', energy_joules=4e4,
        cost_eur=0.03, cost_usd=0.035, scores=(2, 3, 2, 0),
        description='A diffusion model producing a single 1024×1024 '
                    'image — roughly 0.01 kWh.',
        environmental_note='~10× the cost of a text answer per output.',
        political_note='Deepfake capacity erodes shared reality.',
        economic_note='Cheaper than a stock photo.',
        social_note='Creative tool; also supercharges harassment '
                    'and fraud.',
    ),
    dict(
        slug='llm-video-gen', name='Generating a 5-second video clip',
        category='llm', energy_joules=2e6,
        cost_eur=1.5, cost_usd=1.65, scores=(3, 3, 2, -1),
        description='Sora-class text-to-video for a few seconds of '
                    'footage — roughly 500 Wh.',
        environmental_note='Per-second output rivals a house-hour of '
                           'electricity.',
        political_note='Political deepfakes at industrial scale.',
        economic_note='Prices are dropping fast; disruption is near.',
        social_note='Creative possibilities; trust-in-media collapse.',
    ),
    dict(
        slug='fine-tune-small', name='Fine-tuning a small model (LoRA)',
        category='training', energy_joules=5e8,
        cost_eur=25.0, cost_usd=27.0, scores=(2, 1, 2, 2),
        description='A LoRA pass over a 7B-parameter model on modest '
                    'hardware — a few GPU-hours.',
        environmental_note='Roughly one household-day of electricity.',
        political_note='Low barrier for niche-specialised models — '
                       'both civic and malicious use cases.',
        economic_note='Hobbyist-affordable.',
        social_note='Democratises domain adaptation.',
    ),
    dict(
        slug='fine-tune-large', name='Fine-tuning a large model',
        category='training', energy_joules=1e11,
        cost_eur=8000.0, cost_usd=8800.0, scores=(3, 2, 3, 2),
        description='A full-rank fine-tune of a 70B model: tens of '
                    'thousands of GPU-hours.',
        environmental_note='Hundreds of megajoules; a transatlantic '
                           'flight in CO₂e.',
        political_note='Regional fine-tunes aligned to local norms — '
                       'both desirable and weaponisable.',
        economic_note='Five-figure sum; corporate-scale.',
        social_note='Domain-adapted assistants in medicine, law.',
    ),
    dict(
        slug='train-gpt3', name='Pre-training a GPT-3-scale model',
        category='training', energy_joules=4.6e12,
        cost_eur=4_500_000.0, cost_usd=4_900_000.0, scores=(4, 3, 4, 2),
        description='Patterson et al. 2021: 1287 MWh to train GPT-3 '
                    'on ~10,000 V100s for ~14 days.',
        environmental_note='Lifetime emissions of ~100 cars.',
        political_note='At this scale only a handful of states or '
                       'corporations can play.',
        economic_note='Multi-million-euro capital outlay.',
        social_note='The first broadly useful base models came from '
                    'this tier.',
    ),
    dict(
        slug='train-gpt4', name='Pre-training a GPT-4-scale model',
        category='training', energy_joules=2e14,
        cost_eur=75_000_000.0, cost_usd=82_000_000.0, scores=(5, 4, 5, 1),
        description='Public estimates: ~50 GWh, ~100 M USD, tens of '
                    'thousands of H100s for months.',
        environmental_note='A small town-year of electricity per run.',
        political_note='Capability concentration at a civilisational '
                       'level; geopolitical trigger.',
        economic_note='Only a handful of firms globally can afford it.',
        social_note='Benefits are broad but diffuse; risks are '
                    'concrete and concentrated.',
    ),
    dict(
        slug='frontier-cluster-year',
        name='Running a frontier cluster for a year',
        category='industrial', energy_joules=8e17,
        cost_eur=3_000_000_000.0, cost_usd=3_300_000_000.0,
        scores=(5, 5, 5, 0),
        description='A 100k-GPU campus at ~70 MW, running continuously '
                    'for 12 months.',
        environmental_note='Rivals a mid-size country. Fresh-water '
                           'cooling load is itself a regional issue.',
        political_note='AI sovereignty becomes a defining axis of '
                       'state power; export-control wars follow.',
        economic_note='Investment at the scale of national '
                      'infrastructure programmes.',
        social_note='Outcomes radically path-dependent on governance.',
    ),
]


class Command(BaseCommand):
    help = 'Seed Reckoner with signpost comparables and compute tasks.'

    def handle(self, *args, **options):
        for slug, name, icon, j, note in COMPARABLES:
            EnergyComparable.objects.update_or_create(
                slug=slug,
                defaults=dict(
                    name=name, icon=icon, energy_joules=j, note=note,
                ),
            )
        self.stdout.write(self.style.SUCCESS(
            f'  comparables: {EnergyComparable.objects.count()}'
        ))

        for t in TASKS:
            env, pol, eco, soc = t['scores']
            ComputeTask.objects.update_or_create(
                slug=t['slug'],
                defaults=dict(
                    name=t['name'],
                    description=t['description'],
                    category=t['category'],
                    energy_joules=t['energy_joules'],
                    cost_eur=t.get('cost_eur', 0.0),
                    cost_usd=t.get('cost_usd', 0.0),
                    environmental_score=env,
                    political_score=pol,
                    economic_score=eco,
                    social_score=soc,
                    environmental_note=t['environmental_note'],
                    political_note=t['political_note'],
                    economic_note=t['economic_note'],
                    social_note=t['social_note'],
                ),
            )
        self.stdout.write(self.style.SUCCESS(
            f'  tasks: {ComputeTask.objects.count()}'
        ))
        self.stdout.write(self.style.SUCCESS('Reckoner seeded.'))

"""Planet feature generator.

Given a random seed, generates a dictionary of procedural features
sufficient for the client's three.js scene to construct a planet
with ring(s), moons, satellites, and an atmospheric halo. The
generator is deterministic given a seed so we can resurrect any
planet later from its seed alone.

Planet types loosely correspond to classes in the exoplanet
literature (rocky / ocean / gas-giant / ice / lava / desert /
toxic). Colour ranges and feature probabilities are tuned per
type, not globally — gas giants tend to have rings, ice worlds
tend to have subtle atmospheres, etc.
"""

import random


PLANET_TYPES = [
    # name,         (R lo,hi),   (G lo,hi),   (B lo,hi),   roughness,   atm,  ring
    ('rocky',       (90, 180),   (70, 140),   (50, 120),   (0.85, 0.95), 0.15, 0.08),
    ('ocean',       (40, 110),   (100, 170),  (150, 220),  (0.30, 0.55), 0.85, 0.05),
    ('gas_giant',   (150, 220),  (130, 200),  (90, 170),   (0.90, 1.00), 0.00, 0.55),
    ('ice',         (180, 230),  (200, 240),  (220, 255),  (0.60, 0.80), 0.40, 0.25),
    ('lava',        (180, 240),  (50, 110),   (10, 60),    (0.70, 0.90), 0.25, 0.04),
    ('desert',      (180, 230),  (120, 170),  (60, 110),   (0.85, 0.95), 0.10, 0.08),
    ('toxic',       (140, 210),  (180, 230),  (60, 130),   (0.70, 0.90), 0.70, 0.10),
    ('shattered',   (80, 140),   (70, 130),   (70, 140),   (0.95, 1.00), 0.05, 0.35),
]

ATM_COLOR_RANGES = [
    (80, 200), (120, 220), (180, 255),     # blue/teal
]
RING_COLOR_RANGES = [
    (150, 240), (120, 200), (80, 170),     # beige/golden
]
MOON_COLOR_RANGES = [
    (90, 210), (90, 210), (90, 210),       # neutral gray-ish
]

STAR_CATALOGUES = [
    'Kepler', 'Gliese', 'Trappist', 'Proxima', 'HD', 'HR',
    'Ross', 'Wolf', 'Luyten', 'Teegarden', 'Barnard', 'Tabby',
    'LHS', 'LP',
]

SUFFIX_LETTERS = 'bcdefghijk'

TAU = 6.283185307179586

# ── civilization parameters ───────────────────────────────
# Modified Kardashev-ish scale. "uninhabited" and "primordial"
# short-circuit the rest of the civilization data.
CIV_LEVELS = [
    # (level, weight, descriptor)
    ('uninhabited',     30, 'no sentient life detected'),
    ('primordial',      10, 'microbial / proto-biological'),
    ('tribal',           8, 'pre-agricultural tribes'),
    ('agrarian',         9, 'agricultural, pre-industrial'),
    ('industrial',       9, 'steam + electrical'),
    ('atomic',           9, 'fission + early computing'),
    ('information',      8, 'networked digital society'),
    ('interplanetary',   7, 'system-wide expansion'),
    ('interstellar',     5, 'multi-system civilization'),
    ('post-scarcity',    3, 'energy and matter abundant'),
    ('transcendent',     2, 'beyond biological substrate'),
]

GOVERNMENTS = [
    'hereditary monarchy', 'parliamentary democracy',
    'direct democracy', 'technocracy', 'theocracy',
    'military junta', 'corporate hegemony', 'feudal lordships',
    'tribal council', 'anarcho-syndicalist', 'one-party state',
    'AI-governed', 'hive-mind consensus', 'guild federation',
    'clan confederation', 'plutocracy', 'stratocracy',
    'caliphate', 'magocracy', 'noocracy',
]

ECONOMY_STYLES = [
    'agrarian', 'resource-extraction', 'manufacturing',
    'financial / trade hub', 'mercantile', 'command',
    'gift economy', 'barter', 'post-scarcity',
    'tourism-dependent', 'piracy-tolerated', 'knowledge-export',
    'genetic-engineering', 'antimatter-refining',
    'information', 'artisan / craft',
]

ECONOMY_HEALTH = [
    'collapsing', 'stagnant', 'recovering', 'stable',
    'booming', 'overheated', 'restructuring',
]

RESOURCES = [
    'helium-3', 'deuterium', 'rare-earth metals',
    'iridium', 'platinum-group metals', 'tritium',
    'antimatter catalyst', 'water ice', 'crystalline silicates',
    'biopolymers', 'exotic spores', 'singing crystals',
    'nitrogen', 'ammonia', 'methane clathrates',
    'uranium ore', 'thorium', 'graphene sheets',
    'quantum ink', 'dark-matter traces', 'zero-point modules',
    'bacterial pharma', 'bioluminescent algae',
    'nacre', 'gemstone fungi', 'void-silk', 'aerogels',
    'prion textiles', 'temporal resins', 'glacial salts',
    'superconductor wire', 'gravity lenses', 'meditation stones',
    'psionic crystals', 'ritual incense',
]

DISPOSITIONS = [
    ('friendly',       25),
    ('neutral',        35),
    ('wary',           15),
    ('xenophobic',     10),
    ('opportunistic',   7),
    ('hostile',         5),
    ('unknown',         3),
]

LANG_SYL = [
    'thal', 'zor', 'vex', 'qua', 'rin', 'lon', 'mer', 'tri',
    'ka', 'sil', 'mar', 'dun', 'ae', 'ol', 'ith', 'ven', 'xa',
    'shi', 'yun', 'om', 'eb', 'ur', 'glo', 'nym', 'pel',
]

NOTABLE_FEATURES = [
    'tidal-locked day side hosts the only habitable band',
    'orbital elevator links surface to a ring-anchor station',
    'entire population migrates seasonally across one continent',
    'civilization lives exclusively in high-altitude airships',
    'global lingua franca is mathematical, not phonetic',
    'religious festival every 73 days halts all commerce',
    'art is the primary export, valued for pheromone content',
    'sentient flora co-governs with the mammalian population',
    'climate stabilized by a 2,000-year-old orbital mirror net',
    'cultural memory is genetically encoded, not written',
    'death by duel is a legally recognized career exit',
    'children are raised communally until age 14',
    'heavy-industry is entirely offworld on captured asteroids',
    'all buildings are grown, not built',
    "the planet's magnetic reversal is imminent and tracked",
    'a subterranean ocean hosts a separate, older civilization',
    'ritual silence observed for 8 hours at every dusk',
    'name of the polity changes each generation',
    'three moons govern a three-tier religious calendar',
    'a derelict ancestor-ship still orbits the planet',
    'low population, very high per-capita wealth',
    'citizenship requires 5 years of off-world military service',
    'philosophy is constitutionally favored over law',
    'global network is entirely biological — fungal mycelia',
]

POP_BRACKETS = {
    'tribal':         (3, 5),
    'agrarian':       (5, 7),
    'industrial':     (7, 9),
    'atomic':         (8, 10),
    'information':    (9, 11),
    'interplanetary': (9, 11),
    'interstellar':   (10, 12),
    'post-scarcity':  (9, 12),
    'transcendent':   (6, 10),
}

CIV_AGE_BRACKETS = {
    'tribal':         (500, 20000),
    'agrarian':       (1000, 30000),
    'industrial':     (150, 500),
    'atomic':         (60, 250),
    'information':    (40, 300),
    'interplanetary': (100, 800),
    'interstellar':   (500, 5000),
    'post-scarcity':  (300, 4000),
    'transcendent':   (2000, 200000),
}


def _hex(r, g, b):
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f'#{r:02x}{g:02x}{b:02x}'


def _rand_color(ranges, rng):
    """ranges: ((r_lo, r_hi), (g_lo, g_hi), (b_lo, b_hi))."""
    return _hex(
        rng.randint(ranges[0][0], ranges[0][1]),
        rng.randint(ranges[1][0], ranges[1][1]),
        rng.randint(ranges[2][0], ranges[2][1]),
    )


def _weighted(rng, pairs):
    """pairs = [(value, weight), ...] — return one value."""
    total = sum(w for _, w in pairs)
    pick = rng.uniform(0, total)
    acc = 0
    for v, w in pairs:
        acc += w
        if pick <= acc:
            return v
    return pairs[-1][0]


def _civ_name(rng):
    syl = rng.sample(LANG_SYL, rng.randint(2, 3))
    # capitalize first syllable
    parts = [syl[0].capitalize()] + syl[1:]
    name = ''.join(parts)
    # occasionally suffix with -an, -ids, -iri
    if rng.random() < 0.5:
        name += rng.choice(['-an', 'an', 'ids', 'iri', '-kin', 'ae'])
    return name


def _format_population(log10_val):
    n = 10 ** log10_val
    if n < 1e3:
        return f'~{int(n)}'
    if n < 1e6:
        return f'~{n/1e3:.1f}K'
    if n < 1e9:
        return f'~{n/1e6:.1f}M'
    if n < 1e12:
        return f'~{n/1e9:.1f}B'
    return f'~{n/1e12:.1f}T'


def _generate_civilization(rng, ptype, radius):
    """Populate civilization data for a planet.

    Biasing: lava + shattered + toxic rarely host life. Ocean and
    rocky are common habitats. Very small bodies skew toward lower
    civ levels.
    """
    # type-based civ level reweighting
    weighted = [(name, w) for name, w, _ in CIV_LEVELS]
    bias = {
        'lava':      {'uninhabited': 6.0, 'primordial': 0.5},
        'shattered': {'uninhabited': 4.0, 'primordial': 0.4},
        'toxic':     {'uninhabited': 2.0, 'primordial': 1.5},
        'gas_giant': {'uninhabited': 2.5, 'primordial': 0.5},
        'ice':       {'uninhabited': 1.5, 'primordial': 1.2},
        'ocean':     {'uninhabited': 0.6, 'information': 1.4, 'industrial': 1.3},
        'rocky':     {'uninhabited': 0.5},
        'desert':    {'uninhabited': 0.8},
    }.get(ptype, {})
    weighted = [
        (name, w * bias.get(name, 1.0))
        for name, w in weighted
    ]
    level = _weighted(rng, weighted)
    descriptor = dict((n, d) for n, _, d in CIV_LEVELS)[level]

    civ = {
        'level':      level,
        'descriptor': descriptor,
    }

    if level in ('uninhabited', 'primordial'):
        civ['population']  = None
        civ['government']  = None
        civ['economy']     = None
        civ['exports']     = []
        civ['imports']     = []
        civ['disposition'] = None
        civ['language']    = None
        civ['polity']      = None
        civ['civ_age_years'] = None
        # still interesting notes for lifeless worlds
        if level == 'primordial':
            civ['notes'] = rng.choice([
                'extremophile mats dominate equatorial springs',
                'atmospheric oxygenation event in progress',
                'single-celled precursors to photosynthesis detected',
                'iron-rich oceans; early stromatolite formations',
            ])
        else:
            civ['notes'] = rng.choice([
                'no biosignatures in atmosphere',
                'surface irradiated beyond habitability',
                'crust sterilized by recent asteroid impacts',
                'planet is too young for life — <200 Myr',
            ])
        return civ

    # inhabited — fill the rest
    lo, hi = POP_BRACKETS.get(level, (6, 9))
    pop_log = rng.uniform(lo, hi)
    age_lo, age_hi = CIV_AGE_BRACKETS.get(level, (100, 1000))

    exports = rng.sample(RESOURCES, rng.randint(1, 3))
    # imports — pick from a separate draw so overlap is rare
    import_pool = [r for r in RESOURCES if r not in exports]
    imports = rng.sample(import_pool, rng.randint(1, 3))

    tax = rng.choice(['flat', 'progressive', 'tribute-based',
                      'negligible', 'confiscatory', 'land-value'])

    civ.update({
        'polity':       _civ_name(rng),
        'population':   _format_population(pop_log),
        'population_log10': round(pop_log, 2),
        'civ_age_years': rng.randint(int(age_lo), int(age_hi)),
        'government':   rng.choice(GOVERNMENTS),
        'economy': {
            'style':  rng.choice(ECONOMY_STYLES),
            'health': rng.choice(ECONOMY_HEALTH),
            'tax':    tax,
            'index':  round(rng.uniform(0.3, 3.5), 2),  # per-capita output idx
        },
        'exports':      exports,
        'imports':      imports,
        'disposition':  _weighted(rng, DISPOSITIONS),
        'language':     _civ_name(rng) + rng.choice([' Standard', ' Creole', ' High Speech', ' Cant', 'ese']),
        'notes':        rng.choice(NOTABLE_FEATURES),
    })
    return civ


def generate_planet(seed=None):
    """Return a dict describing one procedurally-generated planet."""
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    rng = random.Random(seed)

    # ── class + colours ───────────────────────────────────
    ptype = rng.choice(PLANET_TYPES)
    type_name, r_range, g_range, b_range, rough_range, atm_p, ring_p = ptype
    color = _rand_color((r_range, g_range, b_range), rng)
    roughness = rng.uniform(*rough_range)
    metalness = rng.uniform(0.0, 0.18)

    # ── radius ────────────────────────────────────────────
    if type_name == 'gas_giant':
        radius = rng.uniform(130, 210)
    elif type_name == 'shattered':
        radius = rng.uniform(50, 110)
    else:
        radius = rng.uniform(60, 130)

    # ── atmosphere ────────────────────────────────────────
    atmosphere = None
    if rng.random() < atm_p:
        atmosphere = {
            'color':   _rand_color(ATM_COLOR_RANGES, rng),
            'opacity': round(rng.uniform(0.10, 0.32), 3),
        }

    # ── ring system ───────────────────────────────────────
    ring = None
    if rng.random() < ring_p:
        inner = radius * rng.uniform(1.30, 1.55)
        outer = inner * rng.uniform(1.25, 1.75)
        ring = {
            'inner':   round(inner, 2),
            'outer':   round(outer, 2),
            'color':   _rand_color(RING_COLOR_RANGES, rng),
            'tilt':    round(rng.uniform(0.05, 0.55), 3),
            'roll':    round(rng.uniform(-0.6, 0.6), 3),
            'opacity': round(rng.uniform(0.35, 0.75), 3),
        }

    # ── moons ─────────────────────────────────────────────
    if type_name == 'gas_giant':
        moon_count = rng.choices([1, 2, 3, 4, 5], weights=[10, 20, 30, 25, 15])[0]
    elif type_name == 'shattered':
        moon_count = rng.choices([0, 1, 2, 3], weights=[15, 30, 30, 25])[0]
    else:
        moon_count = rng.choices([0, 1, 2, 3], weights=[25, 40, 25, 10])[0]

    moons = []
    for i in range(moon_count):
        base = radius * 1.6 + i * radius * 0.7
        moons.append({
            'radius':      round(rng.uniform(4, 22), 2),
            'color':       _rand_color(MOON_COLOR_RANGES, rng),
            'orbit_r':     round(base + rng.uniform(10, 50), 2),
            'orbit_speed': round(rng.uniform(0.08, 0.28)
                                 * (1 if rng.random() > 0.2 else -1), 3),
            'tilt':        round(rng.uniform(-0.5, 0.5), 3),
            'phase':       round(rng.uniform(0, TAU), 3),
        })

    # ── artificial satellites ────────────────────────────
    sat_count = rng.choices(
        [0, 1, 2, 3, 4, 5, 6],
        weights=[15, 14, 16, 18, 15, 12, 10],
    )[0]
    satellites = []
    for _ in range(sat_count):
        satellites.append({
            'orbit_r':     round(radius * rng.uniform(1.10, 1.38), 2),
            'orbit_speed': round(rng.uniform(0.9, 2.4)
                                 * (1 if rng.random() > 0.3 else -1), 3),
            'tilt':        round(rng.uniform(-0.9, 0.9), 3),
            'phase':       round(rng.uniform(0, TAU), 3),
            'color':       rng.choice(
                ['#c0c0c0', '#d7d7d7', '#8ea8c0', '#59d0ff', '#ffd79b']
            ),
        })

    # ── name ──────────────────────────────────────────────
    prefix = rng.choice(STAR_CATALOGUES)
    number = rng.randint(100, 9999)
    suffix = rng.choice(SUFFIX_LETTERS)
    name = f'{prefix}-{number}{suffix}'

    # ── civilization / alien society ────────────────────
    civilization = _generate_civilization(rng, type_name, radius)

    return {
        'name':         name,
        'seed':         seed,
        'type':         type_name,
        'radius':       round(radius, 2),
        'color':        color,
        'roughness':    round(roughness, 3),
        'metalness':    round(metalness, 3),
        'atmosphere':   atmosphere,
        'ring':         ring,
        'moons':        moons,
        'satellites':   satellites,
        'civilization': civilization,
    }

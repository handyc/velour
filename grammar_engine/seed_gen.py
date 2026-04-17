"""Server-side spec generator — Python mirror of engine.mjs `generateFresh`.

Produces the same shape of spec the browser engine would build from a
seed (particles / subwords / words / grammars). Used by the Evolution
Engine's "populate languages" action to give auto-speciated Languages
a full Grammar Engine stack without having to open them in a browser.

Determinism is per-Python-RNG, not bit-compatible with the JS
`mulberry32`. A spec built here at seed X will not match a spec built
in the browser at seed X — but once stored it's frozen, so consumers
get a stable, cohesive language either way.
"""
import random


VOWEL_FORMANTS = [
    (300, 870),    # /u/
    (390, 2300),   # /i/
    (730, 1100),   # /ɑ/
    (570, 1700),   # /e/
    (440, 1020),   # /ʌ/
    (500, 1500),   # neutral
]

PARTICLE_DUR = {
    'V': (0.055, 0.090), 'v': (0.028, 0.055),
    'C': (0.020, 0.038), 's': (0.015, 0.032),
    'n': (0.028, 0.055), 'l': (0.025, 0.050),
    'p': (0.010, 0.022),
}

PARTICLE_TYPE_BAG = 'VVVVVvvvnnllCCsp'
SYMS = 'VvCsnlp'

DEFAULTS = {
    'PARTICLE_SEED': 140,
    'SUBWORD_SEED':  300,
    'WORD_COUNT':    10000,
}

SUB_TEMPLATES = [
    'CV', 'VC', 'CVC', 'nV', 'Vn', 'lV', 'Vl', 'pV', 'Vp', 'sV', 'Vs',
    'CVn', 'nVC', 'lVn', 'nVl', 'VnV', 'VlV', 'CVl', 'lVC',
    'Cv', 'vC', 'vCv', 'nv', 'vn', 'lv', 'vl',
    'pVC', 'CVs', 'sVn', 'nVs',
]

DEFAULT_SPEECH_GRAMMARS = {
    'greeting': {
        'note': 'Short two-word exchange. Soft onsets, trailing breath.',
        'axiom': 'S', 'iterations': 4,
        'variants': {
            'cheerful': {'S': 'W.W,', 'W': 'XX', 'X': 'ON',
                         'O': ['C', 'n', 'l', ''], 'N': 'V'},
            'tired':    {'S': 'W,W,', 'W': 'X',  'X': 'ON',
                         'O': ['n', 'l', ''], 'N': 'v'},
            'formal':   {'S': 'W.W.W,', 'W': 'XX', 'X': 'OND',
                         'O': ['Cl', 'Cn', 'C'], 'N': 'V', 'D': ['n', 's', '']},
        },
    },
    'command': {
        'note': 'Short, clipped, plosive-heavy; one or two words.',
        'axiom': 'S', 'iterations': 4,
        'variants': {
            'short':         {'S': 'W',          'W': 'XX', 'X': 'pVs'},
            'double':        {'S': 'W.W',        'W': 'XX', 'X': ['pVC', 'CVp', 'pVp']},
            'barked':        {'S': 'W',          'W': 'X',  'X': 'pVp'},
            'declarative':   {'S': 'W.W',        'W': 'XX', 'X': ['CVC', 'pVC', 'pVp']},
            'warning':       {'S': 'W.W,',       'W': 'XX', 'X': ['pV', 'sV']},
        },
    },
    'casual': {
        'note': 'Open, vowelly, conversational.',
        'axiom': 'S', 'iterations': 4,
        'variants': {
            'relaxed': {'S': 'W.W.W,', 'W': 'XX',
                        'X': ['CV', 'VC', 'CVC', 'nV', 'Vn', 'lV', 'V']},
            'musing':  {'S': 'W,W,',   'W': 'XXX',
                        'X': ['Vv', 'nVv', 'VnV', 'VlV']},
        },
    },
    'question': {
        'note': 'Pitch contour rises to the final "?".',
        'axiom': 'S', 'iterations': 4,
        'variants': {
            'plain':   {'S': 'W.Wv?', 'W': 'XX', 'X': ['CV', 'nV', 'Vn', 'CVC', 'lV']},
            'curious': {'S': 'W.W.Wv?', 'W': 'XX', 'X': ['lV', 'nV', 'VnV']},
            'brief':   {'S': 'Wv?',   'W': 'XXX', 'X': ['CV', 'nV']},
        },
    },
}


def _seed_pop(R):
    r = R.random()
    if r < 0.70:
        return 2 + R.randint(0, 3)
    if r < 0.95:
        return 6 + R.randint(0, 7)
    return 15 + R.randint(0, 19)


def _make_particle(R, pid, ptype):
    d_lo, d_hi = PARTICLE_DUR[ptype]
    pp = {
        'id': pid, 'type': ptype,
        'dur': R.uniform(d_lo, d_hi),
        'offsetFrac': R.random() * 0.9 + 0.02,
        'useCount': 0, 'born': 0,
    }
    if ptype in ('V', 'v'):
        f1, f2 = R.choice(VOWEL_FORMANTS)
        pp['bp1Freq'] = f1; pp['bp1Q'] = 10
        pp['bp2Freq'] = f2; pp['bp2Q'] = 12
        if ptype == 'V' and R.random() < 0.28:
            g1, g2 = R.choice(VOWEL_FORMANTS)
            pp['bp1End'] = g1; pp['bp2End'] = g2
        else:
            pp['bp1End'] = pp['bp1Freq'] * R.uniform(0.95, 1.08)
            pp['bp2End'] = pp['bp2Freq'] * R.uniform(0.92, 1.10)
        pp['gain'] = 0.9; pp['shape'] = 'vowel'; pp['voiced'] = True
    elif ptype == 'n':
        pp['bp1Freq'] = 260; pp['bp1End'] = 260 * R.uniform(0.96, 1.04); pp['bp1Q'] = 12
        pp['bp2Freq'] = 2100; pp['bp2End'] = 2100 * R.uniform(0.94, 1.08); pp['bp2Q'] = 8
        pp['gain'] = 0.55; pp['shape'] = 'nasal'; pp['voiced'] = True
    elif ptype == 'l':
        pp['bp1Freq'] = 360; pp['bp1End'] = 330; pp['bp1Q'] = 9
        pp['bp2Freq'] = 1100; pp['bp2End'] = 1400; pp['bp2Q'] = 8
        pp['gain'] = 0.6; pp['shape'] = 'liquid'; pp['voiced'] = True
    elif ptype == 'C':
        pp['bp1Freq'] = R.uniform(1200, 2400); pp['bp1Q'] = 3
        pp['bp2Freq'] = R.uniform(2800, 4500); pp['bp2Q'] = 3
        pp['gain'] = 0.55; pp['shape'] = 'consonant'; pp['voiced'] = False
    elif ptype == 's':
        pp['bp1Freq'] = R.uniform(3800, 6500); pp['bp1Q'] = 2
        pp['bp2Freq'] = R.uniform(5000, 8000); pp['bp2Q'] = 2
        pp['gain'] = 0.5; pp['shape'] = 'sibilant'; pp['voiced'] = False
    elif ptype == 'p':
        pp['bp1Freq'] = R.uniform(400, 800); pp['bp1Q'] = 1.5
        pp['bp2Freq'] = R.uniform(1200, 2000); pp['bp2Q'] = 1.5
        pp['gain'] = 0.7; pp['shape'] = 'plosive'; pp['voiced'] = False
    return pp


def _gen_sub_pattern(R):
    if R.random() < 0.7:
        return R.choice(SUB_TEMPLATES)
    n = 2 + R.randint(0, 2)
    return ''.join(R.choice(SYMS) for _ in range(n))


def _pick_pop_of_type(R, particles, ptype):
    pool = [p for p in particles if p['type'] == ptype]
    if not pool:
        return None
    best, best_score = None, -1.0
    for _ in range(5):
        pp = R.choice(pool)
        sc = pp['useCount'] + R.random() * 0.8
        if sc > best_score:
            best_score = sc; best = pp
    return best


def _pick_pop_sub(R, subs):
    if not subs:
        return None
    best, best_score = None, -1.0
    for _ in range(5):
        s = R.choice(subs)
        sc = s['useCount'] + R.random() * 0.8
        if sc > best_score:
            best_score = sc; best = s
    return best


def generate_spec(seed, limits=None, preserve_grammars=None):
    """Build a Grammar Engine spec deterministically from `seed`.

    `limits` overrides DEFAULTS keys; `preserve_grammars` if set is
    merged on top of DEFAULT_SPEECH_GRAMMARS so callers (e.g. speciate)
    can keep their evolved L-system variant.
    """
    R = random.Random(int(seed) & 0x7fffffff)
    lim = dict(DEFAULTS)
    if limits:
        lim.update(limits)

    particles = []
    while len(particles) < lim['PARTICLE_SEED']:
        t = R.choice(PARTICLE_TYPE_BAG)
        particles.append(_make_particle(R, len(particles), t))
    for pp in particles:
        pp['useCount'] = _seed_pop(R)

    subwords = []
    while len(subwords) < lim['SUBWORD_SEED']:
        pattern = _gen_sub_pattern(R)
        particle_ids = []
        for ch in pattern:
            if ch not in PARTICLE_DUR:
                continue
            pp = _pick_pop_of_type(R, particles, ch)
            if pp is None:
                pp = _make_particle(R, len(particles), ch)
                particles.append(pp)
            particle_ids.append(pp['id'])
        if not particle_ids:
            continue
        pat = ''.join(particles[i]['type'] for i in particle_ids)
        subwords.append({
            'id': len(subwords),
            'particleIds': particle_ids,
            'pattern': pat,
            'useCount': _seed_pop(R),
            'born': 0,
        })

    words = []
    while len(words) < lim['WORD_COUNT']:
        n = (1 + R.randint(0, 4)) if R.random() < 0.85 else (6 + R.randint(0, 4))
        sub_ids = []
        for _ in range(n):
            s = _pick_pop_sub(R, subwords)
            sub_ids.append(s['id'] if s else R.randrange(len(subwords)))
        words.append({
            'id': len(words), 'subIds': sub_ids,
            'useCount': _seed_pop(R), 'born': 0,
        })

    import copy
    grammars = copy.deepcopy(DEFAULT_SPEECH_GRAMMARS)
    if preserve_grammars:
        for k, v in preserve_grammars.items():
            grammars[k] = v

    return {
        'seed': int(seed),
        'particles': particles,
        'subwords': subwords,
        'words': words,
        'grammars': grammars,
    }

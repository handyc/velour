"""Seed data for the Sanskrit-based concept system.

Three tables form the alphabet of meaning:

  VERB_ROOTS  — ~50 representative dhātus (a full classical list has
                ~2000; we ship a curated seed and a CSV importer for
                the rest).  Each entry: (root, gloss, semantic_class).

  PREVERBS    — the 20 traditional upasargas.  Each modifies a verb's
                meaning along a spatial / aspectual / intensifying
                axis.

  KRIT_SUFFIXES — 16 common nominalising affixes (kṛt-pratyaya).
                  Each turns a verb (with or without preverb) into a
                  noun: agent, action, instrument, location, etc.

A *concept* is a tuple (preverb_id, verb_id, suffix_id).  Any field
may be 0 (= "none"), so the system can express:

  bare verb root                    (preverb_id=0, suffix_id=0)
  preverb-modified verb             (preverb_id≠0, suffix_id=0)
  nominalised verb                  (preverb_id=0, suffix_id≠0)
  nominalised preverb-modified verb (all three non-zero)

The grammar:  preverb + verb + suffix → surface form

The seed below uses IAST romanisation throughout.  Devanagari can be
added later as a parallel column without changing IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# ─── Verb roots ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerbRoot:
    id: int                       # 1..N (0 reserved for "no verb")
    root: str                     # IAST form, e.g. 'gam'
    gloss: str                    # short English
    semantic_class: str           # rough category for browsing


# Seed of 64 verbs covering motion / cognition / action / being /
# speech / perception / change.  IDs are 1-based; 0 is reserved.
VERB_ROOTS: tuple[VerbRoot, ...] = (
    # ── motion ───────────────────────────────────────────────────
    VerbRoot( 1, 'gam',  'go',          'motion'),
    VerbRoot( 2, 'i',    'go',          'motion'),
    VerbRoot( 3, 'car',  'move, walk',  'motion'),
    VerbRoot( 4, 'sṛp',  'creep',       'motion'),
    VerbRoot( 5, 'dru',  'run',         'motion'),
    VerbRoot( 6, 'tṝ',   'cross',       'motion'),
    VerbRoot( 7, 'pat',  'fall, fly',   'motion'),
    VerbRoot( 8, 'plu',  'float, swim', 'motion'),
    # ── being / state ────────────────────────────────────────────
    VerbRoot( 9, 'bhū',  'be, become',  'being'),
    VerbRoot(10, 'as',   'be',          'being'),
    VerbRoot(11, 'sthā', 'stand, stay', 'being'),
    VerbRoot(12, 'vas',  'dwell',       'being'),
    VerbRoot(13, 'śī',   'lie, sleep',  'being'),
    # ── cognition / mind ─────────────────────────────────────────
    VerbRoot(14, 'jñā',  'know',        'cognition'),
    VerbRoot(15, 'vid',  'know, find',  'cognition'),
    VerbRoot(16, 'man',  'think',       'cognition'),
    VerbRoot(17, 'cit',  'perceive',    'cognition'),
    VerbRoot(18, 'budh', 'awake, know', 'cognition'),
    VerbRoot(19, 'smṛ',  'remember',    'cognition'),
    VerbRoot(20, 'śru',  'hear',        'cognition'),
    VerbRoot(21, 'paś',  'see',         'cognition'),
    # ── speech ───────────────────────────────────────────────────
    VerbRoot(22, 'vad',  'speak',       'speech'),
    VerbRoot(23, 'vac',  'say',         'speech'),
    VerbRoot(24, 'brū',  'speak',       'speech'),
    VerbRoot(25, 'kath', 'tell',        'speech'),
    VerbRoot(26, 'gṝ',   'praise',      'speech'),
    # ── action / making ──────────────────────────────────────────
    VerbRoot(27, 'kṛ',   'do, make',    'action'),
    VerbRoot(28, 'kḷp',  'arrange',     'action'),
    VerbRoot(29, 'racch', 'compose',    'action'),
    VerbRoot(30, 'yuj',  'join, yoke',  'action'),
    VerbRoot(31, 'srj',  'create',      'action'),
    VerbRoot(32, 'nī',   'lead, take',  'action'),
    VerbRoot(33, 'hṛ',   'take, carry', 'action'),
    VerbRoot(34, 'dā',   'give',        'action'),
    VerbRoot(35, 'grah', 'grasp',       'action'),
    VerbRoot(36, 'lup',  'cut, sever',  'action'),
    VerbRoot(37, 'han',  'strike, kill','action'),
    # ── perception / sensation ───────────────────────────────────
    VerbRoot(38, 'dṛś',  'see',         'perception'),
    VerbRoot(39, 'spṛś', 'touch',       'perception'),
    VerbRoot(40, 'svad', 'taste',       'perception'),
    VerbRoot(41, 'ghra', 'smell',       'perception'),
    # ── change / process ─────────────────────────────────────────
    VerbRoot(42, 'pac',  'cook, ripen', 'change'),
    VerbRoot(43, 'svap', 'sleep',       'change'),
    VerbRoot(44, 'jīv',  'live',        'change'),
    VerbRoot(45, 'mṛ',   'die',         'change'),
    VerbRoot(46, 'jan',  'be born',     'change'),
    VerbRoot(47, 'vṛdh', 'grow',        'change'),
    VerbRoot(48, 'śuṣ',  'dry',         'change'),
    # ── emotion / volition ───────────────────────────────────────
    VerbRoot(49, 'iṣ',   'wish, want',  'volition'),
    VerbRoot(50, 'kāṅkṣ','desire',      'volition'),
    VerbRoot(51, 'tuṣ',  'be pleased',  'emotion'),
    VerbRoot(52, 'rud',  'weep',        'emotion'),
    VerbRoot(53, 'hṛṣ',  'rejoice',     'emotion'),
    VerbRoot(54, 'krudh','be angry',    'emotion'),
    VerbRoot(55, 'bhī',  'fear',        'emotion'),
    # ── giving / exchange ────────────────────────────────────────
    VerbRoot(56, 'labh', 'obtain',      'exchange'),
    VerbRoot(57, 'mā',   'measure',     'exchange'),
    VerbRoot(58, 'krī',  'buy',         'exchange'),
    VerbRoot(59, 'pā',   'drink, protect','sustenance'),
    VerbRoot(60, 'ad',   'eat',         'sustenance'),
    VerbRoot(61, 'sev',  'serve',       'social'),
    VerbRoot(62, 'pūj',  'honour',      'social'),
    VerbRoot(63, 'svaj', 'embrace',     'social'),
    VerbRoot(64, 'lup',  'lose, deprive','exchange'),
    # ── body / physical action (65–80) ───────────────────────────
    VerbRoot(65, 'bhuj', 'eat, enjoy',  'sustenance'),
    VerbRoot(66, 'snā',  'bathe',       'body'),
    VerbRoot(67, 'sad',  'sit',         'body'),
    VerbRoot(68, 'tan',  'stretch, extend','body'),
    VerbRoot(69, 'dhā',  'place, hold', 'action'),
    VerbRoot(70, 'pad',  'go, fall',    'motion'),
    VerbRoot(71, 'kṣip', 'throw',       'action'),
    VerbRoot(72, 'hā',   'abandon, give up','action'),
    VerbRoot(73, 'pīḍ',  'press, pain', 'body'),
    VerbRoot(74, 'bhañj','break',       'action'),
    VerbRoot(75, 'bhid', 'split, pierce','action'),
    VerbRoot(76, 'naś',  'perish',      'change'),
    VerbRoot(77, 'kram', 'step, march', 'motion'),
    VerbRoot(78, 'spand','tremble',     'body'),
    VerbRoot(79, 'jval', 'blaze',       'change'),
    VerbRoot(80, 'tap',  'heat, suffer','change'),
    # ── time / temporal (81–88) ──────────────────────────────────
    VerbRoot(81, 'div',  'play, shine', 'change'),
    VerbRoot(82, 'cint', 'think, worry','cognition'),
    VerbRoot(83, 'śaṁs', 'praise, recite','speech'),
    VerbRoot(84, 'likh', 'write, scratch','action'),
    VerbRoot(85, 'paṭh', 'read, recite','action'),
    VerbRoot(86, 'gai',  'sing',        'speech'),
    VerbRoot(87, 'nṛt',  'dance',       'body'),
    VerbRoot(88, 'krīḍ', 'play',        'action'),
    # ── exchange / number (89–96) ───────────────────────────────
    VerbRoot(89, 'gaṇ',  'count',       'cognition'),
    VerbRoot(90, 'tul',  'weigh',       'cognition'),
    VerbRoot(91, 'mil',  'meet, mix',   'social'),
    VerbRoot(92, 'cyu',  'depart, fall away','motion'),
    VerbRoot(93, 'arh',  'deserve, be worthy','being'),
    VerbRoot(94, 'śak',  'be able',     'being'),
    VerbRoot(95, 'nind', 'blame',       'speech'),
    VerbRoot(96, 'stu',  'praise',      'speech'),
    # ── perception / nature (97–112) ─────────────────────────────
    VerbRoot( 97, 'jñap','make known',  'cognition'),
    VerbRoot( 98, 'śuc', 'shine, grieve','emotion'),
    VerbRoot( 99, 'bhaj','share, worship','social'),
    VerbRoot(100, 'sah', 'endure',      'being'),
    VerbRoot(101, 'kṣam','forgive',     'emotion'),
    VerbRoot(102, 'dīp', 'shine',       'change'),
    VerbRoot(103, 'śam', 'be calm',     'emotion'),
    VerbRoot(104, 'sphar','spread',     'motion'),
    VerbRoot(105, 'klam','be tired',    'body'),
    VerbRoot(106, 'mlech','speak wrongly','speech'),
    VerbRoot(107, 'majj','sink, bathe', 'motion'),
    VerbRoot(108, 'kṣar','flow away',   'motion'),
    VerbRoot(109, 'sic', 'pour, sprinkle','action'),
    VerbRoot(110, 'mṛj', 'wipe, clean', 'action'),
    VerbRoot(111, 'duh', 'milk, draw',  'action'),
    VerbRoot(112, 'piś', 'shape, adorn','action'),
    # ── exchange / domestic (113–128) ────────────────────────────
    VerbRoot(113, 'vap', 'sow, scatter','action'),
    VerbRoot(114, 'lūṣ', 'cut, lop',    'action'),
    VerbRoot(115, 'gup', 'guard',       'social'),
    VerbRoot(116, 'rakṣ','protect',     'social'),
    VerbRoot(117, 'aś',  'eat, attain', 'sustenance'),
    VerbRoot(118, 'yāc', 'beg, ask',    'speech'),
    VerbRoot(119, 'prach','ask',        'speech'),
    VerbRoot(120, 'val', 'turn, return','motion'),
    VerbRoot(121, 'prīṇ','please',      'emotion'),
    VerbRoot(122, 'ruh', 'grow, rise',  'change'),
    VerbRoot(123, 'jus', 'enjoy',       'emotion'),
    VerbRoot(124, 'klid','wet, moisten','change'),
    VerbRoot(125, 'śri', 'take refuge, lean','being'),
    VerbRoot(126, 'mūrch','swoon',      'body'),
    VerbRoot(127, 'syand','flow, run',  'motion'),
    VerbRoot(128, 'cha', 'cut off, sever','action'),
)


# ─── Preverbs (upasargas) ──────────────────────────────────────────


@dataclass(frozen=True)
class Preverb:
    id: int               # 1..N (0 reserved for "no preverb")
    form: str             # IAST form
    gloss: str            # short directional / aspectual sense


PREVERBS: tuple[Preverb, ...] = (
    Preverb( 1, 'ā',     'toward, hither'),
    Preverb( 2, 'pra',   'forth, forward'),
    Preverb( 3, 'parā',  'away, off'),
    Preverb( 4, 'apa',   'away, off'),
    Preverb( 5, 'sam',   'together, with'),
    Preverb( 6, 'ni',    'down, into'),
    Preverb( 7, 'ava',   'down, away'),
    Preverb( 8, 'anu',   'after, along'),
    Preverb( 9, 'nis',   'out, forth'),
    Preverb(10, 'dus',   'badly, ill'),
    Preverb(11, 'ut',    'up, out'),
    Preverb(12, 'pari',  'around, about'),
    Preverb(13, 'vi',    'apart, dis-'),
    Preverb(14, 'ati',   'beyond, over'),
    Preverb(15, 'adhi',  'over, above'),
    Preverb(16, 'prati', 'towards, against'),
    Preverb(17, 'su',    'well, easily'),
    Preverb(18, 'abhi',  'towards, around'),
    Preverb(19, 'ud',    'up, away'),
    Preverb(20, 'upa',   'near, sub-'),
)


# ─── kṛt suffixes (nominalisers) ───────────────────────────────────


@dataclass(frozen=True)
class KritSuffix:
    id: int               # 1..N (0 reserved for "stay verbal")
    form: str             # IAST form
    sense: str            # what kind of noun
    example: str          # quick example


KRIT_SUFFIXES: tuple[KritSuffix, ...] = (
    KritSuffix( 1, '-a',    'action / agent / abstract',
                            'gama (going), kara (doing/maker)'),
    KritSuffix( 2, '-ana',  'action / instrument / place',
                            'gamana (going), karaṇa (instrument)'),
    KritSuffix( 3, '-ya',   'gerundive / what-must-be',
                            'kārya (to-be-done, duty)'),
    KritSuffix( 4, '-tṛ',   'agent (one who Xs)',
                            'gantṛ (goer), kartṛ (doer)'),
    KritSuffix( 5, '-ti',   'action / state (feminine abstract)',
                            'gati (going, motion), kṛti (deed)'),
    KritSuffix( 6, '-aka',  'agent (-er, less formal)',
                            'gamaka (one who causes to go)'),
    KritSuffix( 7, '-in',   'agent / possessor',
                            'gāmin (going, mover)'),
    KritSuffix( 8, '-man',  'abstract noun (-ness, -hood)',
                            'karman (action, deed)'),
    KritSuffix( 9, '-ja',   'born of, produced from',
                            'kṛtaja (made from)'),
    KritSuffix(10, '-ta',   'past passive participle',
                            'gata (gone), kṛta (done)'),
    KritSuffix(11, '-tum',  'infinitive',
                            'gantum (to go), kartum (to do)'),
    KritSuffix(12, '-tvā',  'gerund / having-Xed',
                            'gatvā (having gone)'),
    KritSuffix(13, '-itva', 'state / -hood',
                            'kartṛtva (agency, doership)'),
    KritSuffix(14, '-tavya','what should be Xed',
                            'kartavya (to-be-done)'),
    KritSuffix(15, '-ana',  'place where',
                            'śayanam (resting-place, bed)'),
    KritSuffix(16, '-ya',   'product of action',
                            'kāryam (work, task)'),
)


# ─── Lookup helpers ────────────────────────────────────────────────


def verb_by_id(i: int) -> VerbRoot | None:
    if i <= 0 or i > len(VERB_ROOTS):
        return None
    return VERB_ROOTS[i - 1]


def preverb_by_id(i: int) -> Preverb | None:
    if i <= 0 or i > len(PREVERBS):
        return None
    return PREVERBS[i - 1]


def suffix_by_id(i: int) -> KritSuffix | None:
    if i <= 0 or i > len(KRIT_SUFFIXES):
        return None
    return KRIT_SUFFIXES[i - 1]


def verb_by_root(root: str) -> VerbRoot | None:
    for v in VERB_ROOTS:
        if v.root == root:
            return v
    return None


def preverb_by_form(form: str) -> Preverb | None:
    for p in PREVERBS:
        if p.form == form:
            return p
    return None


def suffix_by_form(form: str) -> KritSuffix | None:
    for s in KRIT_SUFFIXES:
        if s.form == form:
            return s
    return None


# ─── Bit-budget summary ────────────────────────────────────────────


def bit_budget() -> dict:
    """How many bits each component needs, and how many concepts the
    full cross-product encodes.  Useful for sanity-checking the
    "fits in 4 KB" claim."""
    import math
    nv = len(VERB_ROOTS)
    np = len(PREVERBS)
    ns = len(KRIT_SUFFIXES)
    verb_bits = max(1, math.ceil(math.log2(nv + 1)))  # +1 for "none"
    preverb_bits = max(1, math.ceil(math.log2(np + 1)))
    suffix_bits = max(1, math.ceil(math.log2(ns + 1)))
    total_bits = verb_bits + preverb_bits + suffix_bits
    return {
        'n_verbs':      nv,
        'n_preverbs':   np,
        'n_suffixes':   ns,
        'verb_bits':    verb_bits,
        'preverb_bits': preverb_bits,
        'suffix_bits':  suffix_bits,
        'bits_per_concept':  total_bits,
        'bytes_per_concept': (total_bits + 7) // 8,
        'concepts_in_full_space': (nv + 1) * (np + 1) * (ns + 1),
    }

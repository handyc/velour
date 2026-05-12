"""Hindi vocabulary + sentence generator for the bagīcā app.

Every WORDS entry is keyed by a romanization (ASCII, URL-safe) and carries
its Devanagari surface, gloss, and the morphological detail the templates
need to inflect it correctly. The five SENTENCES generators each pick
compatible vocab and emit a token list with proper gender + number
agreement.

Scope filter (per stakeholder request): no yellow colour, no orange
colour, and no fruit whose canonical image is yellow (banana, lemon,
mango, papaya, pineapple) or orange (saṅtarā). Marigold and sunflower
are likewise omitted from the flower set.
"""

from __future__ import annotations

import random
import re
from urllib.parse import quote


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
#
# Each entry's romanization key is what shows up in /bagicha/word/<key>/.
# The 'dev' field is the canonical Devanagari lemma; inflected surface
# forms are computed by inflect_adj / inflect_noun below.

WORDS: dict[str, dict] = {
    # --- Fruits (no yellow, no orange) ------------------------------------
    'seb': {
        'dev': 'सेब', 'translit': 'seb', 'gloss': 'apple',
        'pos': 'noun', 'gender': 'm', 'category': 'fruit',
        'plural_direct': 'सेब',  'plural_direct_translit': 'seb',
        'plural_oblique': 'सेबों', 'plural_oblique_translit': 'seboṅ',
        'note': 'Native to Kashmir; the prototypical North-Indian fruit.',
    },
    'anar': {
        'dev': 'अनार', 'translit': 'anār', 'gloss': 'pomegranate',
        'pos': 'noun', 'gender': 'm', 'category': 'fruit',
        'plural_direct': 'अनार',  'plural_direct_translit': 'anār',
        'plural_oblique': 'अनारों', 'plural_oblique_translit': 'anāroṅ',
        'note': 'Persian loan (anār); a fertility symbol from Persia to the Deccan.',
    },
    'angur': {
        'dev': 'अंगूर', 'translit': 'aṅgūr', 'gloss': 'grape',
        'pos': 'noun', 'gender': 'm', 'category': 'fruit',
        'plural_direct': 'अंगूर',  'plural_direct_translit': 'aṅgūr',
        'plural_oblique': 'अंगूरों', 'plural_oblique_translit': 'aṅgūroṅ',
        'note': 'Often used as a mass noun; the bare form covers a bunch.',
    },
    'tarbuz': {
        'dev': 'तरबूज़', 'translit': 'tarbūz', 'gloss': 'watermelon',
        'pos': 'noun', 'gender': 'm', 'category': 'fruit',
        'plural_direct': 'तरबूज़',  'plural_direct_translit': 'tarbūz',
        'plural_oblique': 'तरबूज़ों', 'plural_oblique_translit': 'tarbūzoṅ',
        'note': 'Persian tar-būza "wet melon"; the nuqta marks the loan.',
    },
    'amrud': {
        'dev': 'अमरूद', 'translit': 'amrūd', 'gloss': 'guava',
        'pos': 'noun', 'gender': 'm', 'category': 'fruit',
        'plural_direct': 'अमरूद',  'plural_direct_translit': 'amrūd',
        'plural_oblique': 'अमरूदों', 'plural_oblique_translit': 'amrūdoṅ',
        'note': 'Cool-season North-Indian favourite, green-skinned and pink-fleshed.',
    },
    'cherry': {
        'dev': 'चेरी', 'translit': 'cherī', 'gloss': 'cherry',
        'pos': 'noun', 'gender': 'f', 'category': 'fruit',
        'plural_direct': 'चेरियाँ',  'plural_direct_translit': 'cheriyāṅ',
        'plural_oblique': 'चेरियों', 'plural_oblique_translit': 'cheriyoṅ',
        'note': 'English loan; feminine because of the final -ī ending.',
    },
    'alubukhara': {
        'dev': 'आलूबुख़ारा', 'translit': 'ālū-bukhārā', 'gloss': 'plum',
        'pos': 'noun', 'gender': 'm', 'category': 'fruit',
        'plural_direct': 'आलूबुख़ारे',  'plural_direct_translit': 'ālū-bukhāre',
        'plural_oblique': 'आलूबुख़ारों', 'plural_oblique_translit': 'ālū-bukhāroṅ',
        'note': 'Literally "Bukhara potato"; Persian-derived, dark-purple skin.',
    },

    # --- Flowers (no marigold / sunflower) --------------------------------
    'gulab': {
        'dev': 'गुलाब', 'translit': 'gulāb', 'gloss': 'rose',
        'pos': 'noun', 'gender': 'm', 'category': 'flower',
        'plural_direct': 'गुलाब',  'plural_direct_translit': 'gulāb',
        'plural_oblique': 'गुलाबों', 'plural_oblique_translit': 'gulāboṅ',
        'note': 'Persian gulāb "rose-water"; gives Hindi गुलाबी "pink".',
    },
    'kamal': {
        'dev': 'कमल', 'translit': 'kamal', 'gloss': 'lotus',
        'pos': 'noun', 'gender': 'm', 'category': 'flower',
        'plural_direct': 'कमल',  'plural_direct_translit': 'kamal',
        'plural_oblique': 'कमलों', 'plural_oblique_translit': 'kamaloṅ',
        'note': 'India\'s national flower; richly Sanskritic.',
    },
    'chameli': {
        'dev': 'चमेली', 'translit': 'camelī', 'gloss': 'jasmine',
        'pos': 'noun', 'gender': 'f', 'category': 'flower',
        'plural_direct': 'चमेलियाँ',  'plural_direct_translit': 'cameliyāṅ',
        'plural_oblique': 'चमेलियों', 'plural_oblique_translit': 'cameliyoṅ',
        'note': 'Feminine -ī stem; the canonical evening-scented flower.',
    },
    'gudhal': {
        'dev': 'गुड़हल', 'translit': 'guṛhal', 'gloss': 'hibiscus',
        'pos': 'noun', 'gender': 'm', 'category': 'flower',
        'plural_direct': 'गुड़हल',  'plural_direct_translit': 'guṛhal',
        'plural_oblique': 'गुड़हलों', 'plural_oblique_translit': 'guṛhaloṅ',
        'note': 'Sacred to the goddess Kālī; deep-red five-petalled flower.',
    },
    'rajanigandha': {
        'dev': 'रजनीगंधा', 'translit': 'rajanīgandhā', 'gloss': 'tuberose',
        'pos': 'noun', 'gender': 'f', 'category': 'flower',
        'plural_direct': 'रजनीगंधाएँ',  'plural_direct_translit': 'rajanīgandhāeṅ',
        'plural_oblique': 'रजनीगंधाओं', 'plural_oblique_translit': 'rajanīgandhāoṅ',
        'note': 'Sanskrit compound "night-fragrance"; opens after dusk.',
    },
    'kaner': {
        'dev': 'कनेर', 'translit': 'kaner', 'gloss': 'oleander',
        'pos': 'noun', 'gender': 'm', 'category': 'flower',
        'plural_direct': 'कनेर',  'plural_direct_translit': 'kaner',
        'plural_oblique': 'कनेरों', 'plural_oblique_translit': 'kaneroṅ',
        'note': 'Nerium oleander — a common pink-flowered Indian garden shrub.',
    },

    # --- Adjectives: colour (no yellow / orange) --------------------------
    'lal': {
        'dev': 'लाल', 'translit': 'lāl', 'gloss': 'red',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'One of a small set of invariable adjectives; from Persian lāl "ruby".',
    },
    'safed': {
        'dev': 'सफ़ेद', 'translit': 'safed', 'gloss': 'white',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'Persian safīd "white"; invariable for gender and number.',
    },
    'hara': {
        'dev': 'हरा', 'translit': 'harā', 'gloss': 'green',
        'pos': 'adj', 'inflection': 'aa-ending',
        'forms': {'m_sg': 'हरा', 'm_pl': 'हरे', 'f': 'हरी'},
        'forms_translit': {'m_sg': 'harā', 'm_pl': 'hare', 'f': 'harī'},
        'note': 'Variable -ā adjective: agrees with the noun in gender and number.',
    },
    'gulabi': {
        'dev': 'गुलाबी', 'translit': 'gulābī', 'gloss': 'pink',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'Derived: gulāb "rose" + adjectival -ī. Always invariable.',
    },
    'baingani': {
        'dev': 'बैंगनी', 'translit': 'baiṅganī', 'gloss': 'purple',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'From baiṅgan "aubergine" + -ī.',
    },
    'nila': {
        'dev': 'नीला', 'translit': 'nīlā', 'gloss': 'blue',
        'pos': 'adj', 'inflection': 'aa-ending',
        'forms': {'m_sg': 'नीला', 'm_pl': 'नीले', 'f': 'नीली'},
        'forms_translit': {'m_sg': 'nīlā', 'm_pl': 'nīle', 'f': 'nīlī'},
        'note': 'Variable -ā adjective; Sanskrit nīla-.',
    },

    # --- Adjectives: quality ----------------------------------------------
    'mitha': {
        'dev': 'मीठा', 'translit': 'mīṭhā', 'gloss': 'sweet',
        'pos': 'adj', 'inflection': 'aa-ending',
        'forms': {'m_sg': 'मीठा', 'm_pl': 'मीठे', 'f': 'मीठी'},
        'forms_translit': {'m_sg': 'mīṭhā', 'm_pl': 'mīṭhe', 'f': 'mīṭhī'},
        'note': 'Variable -ā adjective.',
    },
    'taaza': {
        'dev': 'ताज़ा', 'translit': 'tāzā', 'gloss': 'fresh',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'Persian tāza; the nuqta marks the borrowed z. Invariable.',
    },
    'sundar': {
        'dev': 'सुंदर', 'translit': 'sundar', 'gloss': 'beautiful',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'Sanskritic and high-register; invariable.',
    },
    'sugandhit': {
        'dev': 'सुगंधित', 'translit': 'sugandhit', 'gloss': 'fragrant',
        'pos': 'adj', 'inflection': 'invariable',
        'note': 'Past participle of su-gandh- "well-scented"; literary.',
    },
    'bada': {
        'dev': 'बड़ा', 'translit': 'baṛā', 'gloss': 'big',
        'pos': 'adj', 'inflection': 'aa-ending',
        'forms': {'m_sg': 'बड़ा', 'm_pl': 'बड़े', 'f': 'बड़ी'},
        'forms_translit': {'m_sg': 'baṛā', 'm_pl': 'baṛe', 'f': 'baṛī'},
        'note': 'Variable -ā adjective; retroflex ṛ.',
    },
    'chota': {
        'dev': 'छोटा', 'translit': 'choṭā', 'gloss': 'small',
        'pos': 'adj', 'inflection': 'aa-ending',
        'forms': {'m_sg': 'छोटा', 'm_pl': 'छोटे', 'f': 'छोटी'},
        'forms_translit': {'m_sg': 'choṭā', 'm_pl': 'choṭe', 'f': 'choṭī'},
        'note': 'Variable -ā adjective.',
    },

    # --- Demonstratives / determiner --------------------------------------
    'yah': {
        'dev': 'यह', 'translit': 'yah', 'gloss': 'this',
        'pos': 'pron', 'number': 'sg',
        'note': 'Proximal demonstrative — used with singular nouns in direct case.',
    },
    'vah': {
        'dev': 'वह', 'translit': 'vah', 'gloss': 'that',
        'pos': 'pron', 'number': 'sg',
        'note': 'Distal demonstrative — singular.',
    },
    'ye': {
        'dev': 'ये', 'translit': 'ye', 'gloss': 'these',
        'pos': 'pron', 'number': 'pl',
        'note': 'Proximal demonstrative — plural.',
    },
    've': {
        'dev': 'वे', 'translit': 've', 'gloss': 'those',
        'pos': 'pron', 'number': 'pl',
        'note': 'Distal demonstrative — plural.',
    },
    'ek': {
        'dev': 'एक', 'translit': 'ek', 'gloss': 'one / a',
        'pos': 'det',
        'note': 'Cardinal "1" that also serves as the indefinite article.',
    },

    # --- Copulas & verbs --------------------------------------------------
    'hai': {
        'dev': 'है', 'translit': 'hai', 'gloss': 'is',
        'pos': 'verb', 'tense': 'present', 'person': '3', 'number': 'sg',
        'note': 'Present copula, 3sg. Descends from Sanskrit asti.',
    },
    'hain': {
        'dev': 'हैं', 'translit': 'haiṅ', 'gloss': 'are',
        'pos': 'verb', 'tense': 'present', 'person': '3', 'number': 'pl',
        'note': 'Present copula, 3pl. The bindu over है marks the nasal.',
    },
    'khilna': {
        'dev': 'खिलना', 'translit': 'khilnā', 'gloss': 'to bloom',
        'pos': 'verb', 'tense': 'infinitive',
        'forms': {'m_sg': 'खिलता', 'm_pl': 'खिलते', 'f': 'खिलती'},
        'forms_translit': {'m_sg': 'khiltā', 'm_pl': 'khilte', 'f': 'khiltī'},
        'note': 'Intransitive verb; the habitual participle agrees with its subject.',
    },

    # --- Location & function words ----------------------------------------
    'baagicha': {
        'dev': 'बग़ीचा', 'translit': 'bagīcā', 'gloss': 'garden',
        'pos': 'noun', 'gender': 'm', 'category': 'place',
        'oblique_sg': 'बग़ीचे', 'oblique_sg_translit': 'bagīce',
        'plural_direct': 'बग़ीचे',  'plural_direct_translit': 'bagīce',
        'plural_oblique': 'बग़ीचों', 'plural_oblique_translit': 'bagīcoṅ',
        'note': 'Persian bāghīcha "little garden"; oblique form appears after में.',
    },
    'mein': {
        'dev': 'में', 'translit': 'meṅ', 'gloss': 'in',
        'pos': 'postp',
        'note': 'Locative postposition; forces its noun into the oblique case.',
    },
    'aur': {
        'dev': 'और', 'translit': 'aur', 'gloss': 'and',
        'pos': 'conj',
        'note': 'Coordinator joining noun phrases or clauses.',
    },
}


# ---------------------------------------------------------------------------
# Selection lists (derived once)
# ---------------------------------------------------------------------------

FRUITS_AND_FLOWERS = [k for k, w in WORDS.items()
                      if w['pos'] == 'noun' and w.get('category') in {'fruit', 'flower'}]
FLOWERS = [k for k, w in WORDS.items()
           if w['pos'] == 'noun' and w.get('category') == 'flower']
COLOUR_ADJS = ['lal', 'safed', 'hara', 'gulabi', 'baingani', 'nila']
QUALITY_ADJS = ['mitha', 'taaza', 'sundar', 'sugandhit', 'bada', 'chota']


# ---------------------------------------------------------------------------
# Inflection
# ---------------------------------------------------------------------------

def inflect_adj(adj_key: str, noun_key: str, plural: bool = False) -> tuple[str, str]:
    """(devanagari, romanisation) of the adjective that agrees with noun_key.

    Invariable adjectives return the lemma forms; -ā adjectives pick the
    matching cell of {m_sg, m_pl, f} from forms / forms_translit.
    """
    adj = WORDS[adj_key]
    if adj['inflection'] == 'invariable':
        return adj['dev'], adj['translit']
    noun = WORDS[noun_key]
    slot = 'f' if noun.get('gender') == 'f' else ('m_pl' if plural else 'm_sg')
    return adj['forms'][slot], adj['forms_translit'][slot]


def inflect_verb_habitual(verb_key: str, noun_key: str, plural: bool) -> tuple[str, str]:
    verb = WORDS[verb_key]
    noun = WORDS[noun_key]
    slot = 'f' if noun.get('gender') == 'f' else ('m_pl' if plural else 'm_sg')
    return verb['forms'][slot], verb['forms_translit'][slot]


def noun_plural(noun_key: str, oblique: bool = False) -> tuple[str, str]:
    n = WORDS[noun_key]
    if oblique:
        return n['plural_oblique'], n['plural_oblique_translit']
    return n['plural_direct'], n['plural_direct_translit']


def tok(key: str, surface: str | None = None,
        translit: str | None = None, label: str | None = None) -> dict:
    """Build a sentence token. surface/translit default to the lemma."""
    w = WORDS[key]
    return {
        'key': key,
        'surface': surface or w['dev'],
        'translit': translit or w['translit'],
        'gloss': w['gloss'],
        'pos': w['pos'],
        'label': label,
    }


# ---------------------------------------------------------------------------
# Sentence templates
# ---------------------------------------------------------------------------

def s_dem_noun_colour():
    """[यह/वह] [noun-sg] [colour-agree] है — 'This/that X is COLOUR.'"""
    dem_key = random.choice(['yah', 'vah'])
    noun_key = random.choice(FRUITS_AND_FLOWERS)
    colour_key = random.choice(COLOUR_ADJS)
    noun = WORDS[noun_key]
    c_dev, c_tr = inflect_adj(colour_key, noun_key, plural=False)
    label = _agree_label(WORDS[colour_key], noun, plural=False)
    tokens = [
        tok(dem_key),
        tok(noun_key, label=f"{noun['gender']}.sg, direct"),
        tok(colour_key, c_dev, c_tr, label=label),
        tok('hai'),
    ]
    gloss = f"{WORDS[dem_key]['gloss'].capitalize()} {noun['gloss']} is {WORDS[colour_key]['gloss']}."
    return tokens, gloss


def s_noun_quality():
    """[noun-sg] [quality-agree] है — 'The X is QUALITY.'"""
    noun_key = random.choice(FRUITS_AND_FLOWERS)
    adj_key = random.choice(QUALITY_ADJS)
    noun = WORDS[noun_key]
    a_dev, a_tr = inflect_adj(adj_key, noun_key, plural=False)
    label = _agree_label(WORDS[adj_key], noun, plural=False)
    tokens = [
        tok(noun_key, label=f"{noun['gender']}.sg, direct"),
        tok(adj_key, a_dev, a_tr, label=label),
        tok('hai'),
    ]
    gloss = f"The {noun['gloss']} is {WORDS[adj_key]['gloss']}."
    return tokens, gloss


def s_plural_quality():
    """[ये/वे] [noun-pl] [adj-pl] हैं — 'These/those Xs are QUALITY.'"""
    dem_key = random.choice(['ye', 've'])
    noun_key = random.choice(FRUITS_AND_FLOWERS)
    adj_key = random.choice(QUALITY_ADJS + COLOUR_ADJS)
    noun = WORDS[noun_key]
    n_dev, n_tr = noun_plural(noun_key, oblique=False)
    a_dev, a_tr = inflect_adj(adj_key, noun_key, plural=True)
    tokens = [
        tok(dem_key),
        tok(noun_key, n_dev, n_tr, label=f"{noun['gender']}.pl, direct"),
        tok(adj_key, a_dev, a_tr,
            label=_agree_label(WORDS[adj_key], noun, plural=True)),
        tok('hain'),
    ]
    pl = noun['gloss'] + ('es' if noun['gloss'].endswith(('h', 's')) else 's')
    gloss = f"{WORDS[dem_key]['gloss'].capitalize()} {pl} are {WORDS[adj_key]['gloss']}."
    return tokens, gloss


def s_in_garden_bloom():
    """बग़ीचे में [flower-pl] [खिलते/खिलती] हैं — 'In the garden, the Xs bloom.'"""
    flower_key = random.choice(FLOWERS)
    flower = WORDS[flower_key]
    f_dev, f_tr = noun_plural(flower_key, oblique=False)
    v_dev, v_tr = inflect_verb_habitual('khilna', flower_key, plural=True)
    verb_label = ('f' if flower['gender'] == 'f' else 'm.pl') + ' habitual participle'
    tokens = [
        tok('baagicha',
            WORDS['baagicha']['oblique_sg'],
            WORDS['baagicha']['oblique_sg_translit'],
            label='m.sg, oblique (under में)'),
        tok('mein'),
        tok(flower_key, f_dev, f_tr, label=f"{flower['gender']}.pl, direct"),
        tok('khilna', v_dev, v_tr, label=verb_label),
        tok('hain'),
    ]
    pl = flower['gloss'] + ('es' if flower['gloss'].endswith(('h', 's')) else 's')
    gloss = f"In the garden the {pl} bloom."
    return tokens, gloss


def s_this_is_a_quality_noun():
    """यह एक [adj-agree] [noun-sg] है — 'This is a QUALITY X.'"""
    noun_key = random.choice(FRUITS_AND_FLOWERS)
    adj_key = random.choice(QUALITY_ADJS)
    noun = WORDS[noun_key]
    a_dev, a_tr = inflect_adj(adj_key, noun_key, plural=False)
    tokens = [
        tok('yah'),
        tok('ek'),
        tok(adj_key, a_dev, a_tr,
            label=_agree_label(WORDS[adj_key], noun, plural=False)),
        tok(noun_key, label=f"{noun['gender']}.sg, direct"),
        tok('hai'),
    ]
    article = 'an' if WORDS[adj_key]['gloss'][0] in 'aeiou' else 'a'
    gloss = f"This is {article} {WORDS[adj_key]['gloss']} {noun['gloss']}."
    return tokens, gloss


TEMPLATES = [
    ('Demonstrative + noun + colour', s_dem_noun_colour),
    ('Noun + quality adjective', s_noun_quality),
    ('Plural demonstrative + plural noun + adjective', s_plural_quality),
    ('Locative — flowers bloom in the garden', s_in_garden_bloom),
    ('Indefinite — "this is a … "', s_this_is_a_quality_noun),
]


def _agree_label(adj: dict, noun: dict, plural: bool) -> str:
    if adj['inflection'] == 'invariable':
        return 'invariable'
    if noun.get('gender') == 'f':
        return 'f, agrees with noun'
    return ('m.pl' if plural else 'm.sg') + ', agrees with noun'


def generate(n: int = 6) -> list[dict]:
    """Generate n sentences, cycling through the templates."""
    sentences = []
    order = list(TEMPLATES)
    random.shuffle(order)
    for i in range(n):
        label, fn = order[i % len(order)]
        tokens, gloss = fn()
        sentences.append({
            'template': label,
            'tokens': tokens,
            'devanagari': ' '.join(t['surface'] for t in tokens) + '।',
            'translit': ' '.join(t['translit'] for t in tokens) + '.',
            'gloss': gloss,
        })
    return sentences


# ---------------------------------------------------------------------------
# External dictionary links
# ---------------------------------------------------------------------------

def dictionary_links(word: dict) -> list[dict]:
    """Resolve a word to its canonical dictionary pages.

    Wiktionary is the primary lookup (Devanagari URL). Rekhta and Platts
    handle the lexicographic backstop for Perso-Arabic and historical
    forms.
    """
    dev = quote(word['dev'])
    translit_ascii = ''.join(c for c in word['translit'].lower()
                             if c.isascii() and (c.isalnum() or c in '-_'))
    return [
        {
            'name': 'Wiktionary (Hindi)',
            'url': f'https://en.wiktionary.org/wiki/{dev}#Hindi',
            'why': 'Etymology, declension tables, and IPA — keyed by Devanagari.',
        },
        {
            'name': 'Rekhta Dictionary',
            'url': f'https://www.rekhtadictionary.com/meaning-of-{translit_ascii}',
            'why': 'Hindi–Urdu meanings with usage examples and audio.',
        },
        {
            'name': 'Platts (1884) at DSAL Chicago',
            'url': f'https://dsal.uchicago.edu/cgi-bin/app/platts_query.py?qs={dev}',
            'why': 'Authoritative historical dictionary of Urdu, Classical Hindi & English.',
        },
    ]


# ---------------------------------------------------------------------------
# Bibliography & learning resources
# ---------------------------------------------------------------------------

BIBLIOGRAPHY = [
    {
        'author': 'McGregor, R. S.',
        'year': '1995',
        'title': 'Outline of Hindi Grammar',
        'publisher': 'Oxford University Press',
        'edition': '3rd edn',
        'note': 'The standard concise reference grammar in English. Compact, dense, durable.',
    },
    {
        'author': 'Snell, Rupert & Simon Weightman',
        'year': '2017',
        'title': 'Complete Hindi',
        'publisher': 'Hodder (Teach Yourself)',
        'edition': '6th edn',
        'note': 'The most widely-used self-study course; balances script, grammar, and dialogue.',
    },
    {
        'author': 'Shapiro, Michael C.',
        'year': '1989',
        'title': 'A Primer of Modern Standard Hindi',
        'publisher': 'Motilal Banarsidass, Delhi',
        'edition': '',
        'note': 'A university-classroom primer with thorough morphology coverage.',
    },
    {
        'author': 'Kachru, Yamuna',
        'year': '2006',
        'title': 'Hindi',
        'publisher': 'John Benjamins (London Oriental and African Language Library 12)',
        'edition': '',
        'note': 'Theoretically-informed reference grammar; rich syntax sections.',
    },
    {
        'author': 'Kellogg, S. H.',
        'year': '1893',
        'title': 'A Grammar of the Hindi Language',
        'publisher': 'Kegan Paul, London',
        'edition': '3rd edn',
        'note': 'The 19th-century missionary grammar — still cited for its dialect data.',
    },
    {
        'author': 'Bhatia, Tej K.',
        'year': '2007',
        'title': 'Colloquial Hindi',
        'publisher': 'Routledge',
        'edition': '2nd edn',
        'note': 'Conversation-first introductory course with audio.',
    },
    {
        'author': 'Platts, John T.',
        'year': '1884',
        'title': 'A Dictionary of Urdu, Classical Hindi, and English',
        'publisher': 'W. H. Allen, London',
        'edition': '',
        'note': 'Public-domain Perso-Arabic & Hindi lexicon; the historical workhorse.',
    },
]


LEARNING_LINKS = [
    {
        'name': 'Rekhta Dictionary',
        'url': 'https://www.rekhtadictionary.com/',
        'kind': 'dictionary',
        'note': 'Modern Hindi–Urdu lexicon with examples and pronunciation audio.',
    },
    {
        'name': 'Wiktionary — Hindi entries',
        'url': 'https://en.wiktionary.org/wiki/Category:Hindi_lemmas',
        'kind': 'dictionary',
        'note': 'Crowd-sourced but solid for declension and etymology.',
    },
    {
        'name': 'Hindi WordNet (IIT Bombay)',
        'url': 'https://www.cfilt.iitb.ac.in/wordnet/webhwn/',
        'kind': 'corpus',
        'note': 'Synset-based lexical database; useful for sense disambiguation.',
    },
    {
        'name': 'A Door Into Hindi (Afroz Taj, UNC)',
        'url': 'https://taj.oasis.unc.edu/',
        'kind': 'course',
        'note': 'Free 20-lesson video course with film clips and grammar notes.',
    },
    {
        'name': 'Learning Hindi! (learninghindi.com)',
        'url': 'https://www.learninghindi.com/',
        'kind': 'course',
        'note': 'Beginner-friendly lessons with romanisation alongside Devanagari.',
    },
    {
        'name': 'BBC Learning Hindi (archive)',
        'url': 'https://www.bbc.co.uk/languages/other/hindi/',
        'kind': 'course',
        'note': 'Short archived introduction; still good for survival phrases.',
    },
    {
        'name': 'NCPUL — National Council for Promotion of Urdu Language',
        'url': 'https://www.urducouncil.nic.in/',
        'kind': 'institution',
        'note': 'Government council for the sibling Urdu register; shared lexicon.',
    },
    {
        'name': 'Digital Dictionaries of South Asia (Chicago)',
        'url': 'https://dsal.uchicago.edu/dictionaries/list_pri.html#hin',
        'kind': 'dictionary',
        'note': 'Scanned Platts, Bahri, Caturvedi & McGregor — the historical stack.',
    },
]


# ---------------------------------------------------------------------------
# Translation (closed-vocabulary, word-by-word)
# ---------------------------------------------------------------------------
#
# This is not a full MT system — it's a pedagogical lookup. The reverse
# index covers every inflected surface that the generator can emit, so
# any sentence the generator produces round-trips perfectly. Free text
# falls back to "unmatched" on unknown tokens.

DEVANAGARI_RE = re.compile(r'[ऀ-ॿ]')
TOKEN_RE = re.compile(r"[^\s।.,!?;:'\"()\[\]]+")


def _build_indices():
    surface: dict[str, tuple[str, str]] = {}
    gloss: dict[str, tuple[str, str]] = {}
    for key, w in WORDS.items():
        surface[w['dev']] = (key, 'lemma')
        # Order matters under setdefault — registering oblique_sg first
        # means it wins the bagīce ambiguity (oblique.sg ≡ plural.direct).
        for slot in ('oblique_sg', 'plural_direct', 'plural_oblique'):
            if slot in w:
                surface.setdefault(w[slot], (key, slot.replace('_', '.')))
        if 'forms' in w:
            for s, form in w['forms'].items():
                surface.setdefault(form, (key, f'agree.{s}'))
        g_main = w['gloss'].split(' / ')[0].split('(')[0].strip().lower()
        gloss.setdefault(g_main, (key, 'lemma'))
        if w['gloss'] != g_main:
            gloss.setdefault(w['gloss'].lower(), (key, 'lemma'))
    # Hand-rolled English aliases that fall outside the canonical gloss.
    for alias, target in {
        'a': 'ek', 'an': 'ek',
        'the': None,
        'roses': 'gulab', 'lotuses': 'kamal', 'jasmines': 'chameli',
        'hibiscuses': 'gudhal', 'tuberoses': 'rajanigandha', 'oleanders': 'kaner',
        'apples': 'seb', 'pomegranates': 'anar', 'grapes': 'angur',
        'watermelons': 'tarbuz', 'guavas': 'amrud', 'cherries': 'cherry',
        'plums': 'alubukhara',
        'bloom': 'khilna', 'blooms': 'khilna', 'blossoms': 'khilna',
        'fragrant': 'sugandhit', 'beautiful': 'sundar',
    }.items():
        if target is None:
            gloss.setdefault(alias, ('', 'function-word'))
        else:
            gloss.setdefault(alias, (target, 'alias'))
    return surface, gloss


_SURFACE_INDEX, _GLOSS_INDEX = _build_indices()


def translate(text: str) -> dict:
    """Word-by-word translation of free-form Hindi or English input.

    Direction is auto-detected from script. Each emitted token records
    the input form, the matched lemma (if any), the inflectional role
    of the matched surface, and full grammar metadata.
    """
    raw_tokens = TOKEN_RE.findall(text)
    is_hindi = any(DEVANAGARI_RE.search(t) for t in raw_tokens)
    direction = 'hi→en' if is_hindi else 'en→hi'

    out = []
    matched_count = 0
    for tok_text in raw_tokens:
        hit = (_SURFACE_INDEX.get(tok_text) if is_hindi
               else _GLOSS_INDEX.get(tok_text.lower()))
        if hit and hit[0]:
            key, role = hit
            w = WORDS[key]
            matched_count += 1
            out.append({
                'token':    tok_text,
                'matched':  True,
                'key':      key,
                'role':     role,
                'dev':      w['dev'],
                'translit': w['translit'],
                'gloss':    w['gloss'],
                'pos':      w['pos'],
                'gender':   w.get('gender', ''),
                'note':     w.get('note', ''),
            })
        elif hit and hit[1] == 'function-word':
            out.append({
                'token': tok_text, 'matched': False,
                'note': 'English function word with no direct Hindi counterpart.',
            })
        else:
            out.append({'token': tok_text, 'matched': False})

    return {
        'direction': direction,
        'is_hindi':  is_hindi,
        'tokens':    out,
        'matched':   matched_count,
        'total':     len(out),
    }

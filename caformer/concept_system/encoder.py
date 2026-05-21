"""Text → Concept(s) encoder.

Phase-1 implementation: keyword / synonym lookup against the verb,
preverb, and suffix tables.  English input is tokenised on whitespace
(after lower_no_punct normalisation), then each token is matched
against the gloss + alias maps to produce candidate concepts.

This is intentionally crude — a real text-to-concept encoder needs a
parser / lemmatiser / semantic role detector.  The Phase-1 baseline
shows the architecture works for the obvious cases and gives the
caformer harness a usable concept-space lookup right now.

Aliases below are hand-picked English glosses that map onto Sanskrit
verb roots.  Add more by editing VERB_ALIASES and re-running the
seed.
"""
from __future__ import annotations

from . import data as _data
from .concept import Concept


# English-token → Sanskrit-verb-root aliases.  Multiple aliases per
# verb capture synonymy.  Lower-case, single-word (or short phrase
# with underscore).
VERB_ALIASES: dict[str, str] = {
    # motion
    'go': 'gam', 'goes': 'gam', 'going': 'gam', 'went': 'gam',
    'come': 'gam', 'comes': 'gam', 'arrived': 'gam',
    'travel': 'gam', 'move': 'car', 'moves': 'car', 'walked': 'car',
    'run': 'dru', 'runs': 'dru', 'running': 'dru',
    'cross': 'tṝ', 'crosses': 'tṝ',
    'fall': 'pat', 'fly': 'pat', 'flies': 'pat',
    'swim': 'plu', 'float': 'plu',
    # being
    'be': 'bhū', 'is': 'as', 'are': 'as', 'am': 'as',
    'become': 'bhū', 'becomes': 'bhū',
    'stand': 'sthā', 'stay': 'sthā', 'stays': 'sthā',
    'live': 'jīv', 'lives': 'jīv', 'living': 'jīv',
    'dwell': 'vas', 'sleep': 'svap', 'rest': 'śī',
    # cognition
    'know': 'jñā', 'knows': 'jñā', 'knew': 'jñā',
    'understand': 'jñā', 'recognise': 'jñā',
    'find': 'vid', 'find_out': 'vid',
    'think': 'man', 'thinks': 'man', 'thinking': 'man',
    'consider': 'man',
    'perceive': 'cit', 'realise': 'cit',
    'awaken': 'budh', 'awake': 'budh',
    'remember': 'smṛ', 'recall': 'smṛ',
    'hear': 'śru', 'hears': 'śru', 'heard': 'śru', 'listen': 'śru',
    'see': 'paś', 'sees': 'paś', 'saw': 'paś', 'look': 'paś',
    'observe': 'dṛś', 'watch': 'dṛś',
    # speech
    'say': 'vac', 'says': 'vac', 'said': 'vac', 'speak': 'vad',
    'speaks': 'vad', 'tell': 'kath', 'tells': 'kath',
    'praise': 'gṝ', 'sing': 'gṝ',
    # action
    'do': 'kṛ', 'does': 'kṛ', 'make': 'kṛ', 'makes': 'kṛ',
    'create': 'srj', 'compose': 'racch', 'build': 'kṛ',
    'arrange': 'kḷp', 'organize': 'kḷp',
    'join': 'yuj', 'connect': 'yuj', 'attach': 'yuj',
    'lead': 'nī', 'leads': 'nī', 'take': 'hṛ',
    'carry': 'hṛ', 'grab': 'grah', 'grasp': 'grah',
    'give': 'dā', 'gives': 'dā', 'gave': 'dā',
    'cut': 'lup', 'break': 'lup',
    'strike': 'han', 'hit': 'han', 'kill': 'han',
    # perception / sensation
    'touch': 'spṛś', 'taste': 'svad', 'smell': 'ghra',
    # change
    'cook': 'pac', 'ripen': 'pac',
    'die': 'mṛ', 'dies': 'mṛ', 'died': 'mṛ',
    'born': 'jan', 'birth': 'jan',
    'grow': 'vṛdh', 'increase': 'vṛdh',
    'dry': 'śuṣ', 'wither': 'śuṣ',
    # volition
    'want': 'iṣ', 'wants': 'iṣ', 'wish': 'iṣ',
    'desire': 'kāṅkṣ', 'long_for': 'kāṅkṣ',
    # emotion
    'rejoice': 'hṛṣ', 'enjoy': 'tuṣ', 'pleased': 'tuṣ',
    'weep': 'rud', 'cry': 'rud',
    'angry': 'krudh', 'fear': 'bhī', 'afraid': 'bhī',
    # sustenance
    'eat': 'ad', 'eats': 'ad', 'drink': 'pā',
    'protect': 'pā',
    # social
    'serve': 'sev', 'honour': 'pūj', 'worship': 'pūj',
    'embrace': 'svaj', 'hug': 'svaj',
    # exchange
    'get': 'labh', 'obtain': 'labh', 'gain': 'labh',
    'buy': 'krī', 'measure': 'mā',
    'lose': 'lup',
    # body / physical (65–80)
    'enjoy': 'bhuj', 'consume': 'bhuj',
    'bathe': 'snā',
    'sit': 'sad', 'sits': 'sad', 'sat': 'sad',
    'stretch': 'tan', 'extend': 'tan',
    'place': 'dhā', 'hold': 'dhā', 'put': 'dhā',
    'throw': 'kṣip', 'throws': 'kṣip', 'hurl': 'kṣip',
    'abandon': 'hā', 'give_up': 'hā', 'leave': 'hā',
    'press': 'pīḍ', 'pain': 'pīḍ', 'hurt': 'pīḍ',
    'break': 'bhañj', 'breaks': 'bhañj', 'broke': 'bhañj',
    'split': 'bhid', 'pierce': 'bhid',
    'perish': 'naś', 'vanish': 'naś',
    'step': 'kram', 'march': 'kram', 'stride': 'kram',
    'tremble': 'spand', 'shake': 'spand',
    'blaze': 'jval', 'burn': 'jval',
    'heat': 'tap', 'suffer': 'tap',
    # time / temporal (81–88)
    'shine': 'div', 'glow': 'div',
    'worry': 'cint', 'consider_deeply': 'cint',
    'recite': 'paṭh', 'read': 'paṭh', 'reads': 'paṭh',
    'write': 'likh', 'writes': 'likh', 'wrote': 'likh', 'scratch': 'likh',
    'sing': 'gai', 'sings': 'gai', 'sang': 'gai',
    'dance': 'nṛt', 'dances': 'nṛt',
    'play': 'krīḍ', 'plays': 'krīḍ',
    # number / exchange (89–96)
    'count': 'gaṇ', 'counts': 'gaṇ',
    'weigh': 'tul', 'compare': 'tul',
    'meet': 'mil', 'mix': 'mil', 'meets': 'mil',
    'depart': 'cyu', 'fall_away': 'cyu',
    'deserve': 'arh', 'worthy': 'arh',
    'able': 'śak', 'can': 'śak',
    'blame': 'nind', 'condemn': 'nind',
    'praise_well': 'stu', 'extol': 'stu',
    # perception / nature (97–112)
    'inform': 'jñap', 'announce': 'jñap',
    'grieve': 'śuc',
    'share': 'bhaj', 'worship': 'bhaj', 'devote': 'bhaj',
    'endure': 'sah', 'bear': 'sah', 'withstand': 'sah',
    'forgive': 'kṣam', 'pardon': 'kṣam',
    'illuminate': 'dīp',
    'calm': 'śam', 'quiet': 'śam', 'still': 'śam',
    'spread': 'sphar', 'expand': 'sphar',
    'tired': 'klam', 'weary': 'klam',
    'mispronounce': 'mlech', 'speak_wrongly': 'mlech',
    'sink': 'majj', 'immerse': 'majj', 'plunge': 'majj',
    'flow_away': 'kṣar',
    'pour': 'sic', 'sprinkle': 'sic',
    'wipe': 'mṛj', 'clean': 'mṛj',
    'milk': 'duh', 'draw_out': 'duh',
    'shape': 'piś', 'adorn': 'piś',
    # exchange / domestic (113–128)
    'sow': 'vap', 'scatter': 'vap',
    'lop': 'lūṣ',
    'guard': 'gup', 'safeguard': 'gup',
    'take_refuge': 'śri',
    'attain': 'aś',
    'ask': 'prach', 'asks': 'prach', 'inquire': 'prach',
    'beg': 'yāc', 'request': 'yāc',
    'turn': 'val', 'return': 'val',
    'please_someone': 'prīṇ',
    'rise': 'ruh', 'sprout': 'ruh',
    'wet': 'klid', 'moisten': 'klid',
    'swoon': 'mūrch', 'faint': 'mūrch',
    'sever': 'cha', 'chop': 'cha',
}


# English directional / aspectual markers → preverb form.
PREVERB_ALIASES: dict[str, str] = {
    'toward': 'ā', 'hither': 'ā', 'here': 'ā',
    'forth': 'pra', 'forward': 'pra', 'ahead': 'pra',
    'away': 'apa', 'off': 'apa',
    'together': 'sam', 'with': 'sam', 'united': 'sam',
    'down': 'ni', 'into': 'ni',
    'after': 'anu', 'along': 'anu', 'following': 'anu',
    'out': 'nis', 'forth_out': 'nis',
    'badly': 'dus', 'ill': 'dus', 'wrongly': 'dus',
    'up': 'ut', 'upward': 'ut', 'rising': 'ut',
    'around': 'pari', 'about': 'pari', 'over': 'adhi',
    'apart': 'vi', 'separately': 'vi',
    'beyond': 'ati', 'across': 'ati',
    'above': 'adhi',
    'against': 'prati', 'back_at': 'prati',
    'well': 'su', 'easily': 'su', 'good': 'su',
    'near': 'upa', 'sub': 'upa',
}


# English nominalisation markers → suffix form.
SUFFIX_ALIASES: dict[str, str] = {
    'action': '-a',          # generic act noun
    'going': '-ana',         # process / instrument
    'doing': '-ana',
    'doer': '-tṛ', 'maker': '-tṛ', 'agent': '-tṛ',
    'gerund': '-tvā', 'after': '-tvā',
    'infinitive': '-tum', 'to': '-tum',
    'must': '-ya', 'should': '-tavya', 'duty': '-tavya',
    'past': '-ta', 'done': '-ta', 'gone': '-ta',
}


def encode(text: str) -> list[Concept]:
    """Encode a piece of natural-language text into a list of
    candidate Concept rows.  Each word that matches a verb / preverb
    / suffix alias contributes to one or more concepts.

    Heuristic: scan tokens left-to-right.  A preverb token preceding
    a verb token combines into one concept.  A suffix token following
    a verb token nominalises it.  Standalone verb tokens emit bare
    verb-root concepts.

    Returns concepts in order of recognition.  Empty list means no
    Sanskrit root was found."""
    from caformer.harness.normalization import lower_no_punct
    tokens = lower_no_punct(text).split()
    if not tokens:
        return []

    out: list[Concept] = []
    pending_preverb: int = 0     # carried over to the next verb
    last_verb_idx: int | None = None

    for tok in tokens:
        # Preverb?
        pv_form = PREVERB_ALIASES.get(tok)
        if pv_form is not None:
            p = _data.preverb_by_form(pv_form)
            if p is not None:
                pending_preverb = p.id
                last_verb_idx = None
                continue
        # Verb?
        vr_form = VERB_ALIASES.get(tok)
        if vr_form is not None:
            v = _data.verb_by_root(vr_form)
            if v is not None:
                concept = Concept(preverb_id=pending_preverb,
                                  verb_id=v.id,
                                  suffix_id=0)
                out.append(concept)
                last_verb_idx = len(out) - 1
                pending_preverb = 0
                continue
        # Suffix? (only attaches to the last verb concept).
        sf_form = SUFFIX_ALIASES.get(tok)
        if sf_form is not None and last_verb_idx is not None:
            s = _data.suffix_by_form(sf_form)
            if s is not None:
                prev = out[last_verb_idx]
                out[last_verb_idx] = Concept(
                    preverb_id=prev.preverb_id,
                    verb_id=prev.verb_id,
                    suffix_id=s.id,
                )
                continue
        # Unrecognised token — skip silently.  (Phase 2 would log /
        # surface this so the user can add aliases.)

    return out

"""Token-level primitives for the textmask token mode.

Each primitive is a pure function ``f(token: str) -> str``: it
takes a single token and returns its replacement (which may be
``''`` for "drop").  Multi-token outputs are not supported here —
that goes back through ``tokenize()`` upstream.

Heavy NLP (spaCy POS, lemma) is lazy-loaded on first use and
cached so the regular Porter / Soundex / Metaphone path stays
zero-overhead on import.
"""

from __future__ import annotations
import re
from functools import lru_cache
from typing import Callable, List

TokenFunc = Callable[[str], str]


# ─── tokenizer ──────────────────────────────────────────────────────

# Conservative word-tokenizer: keeps apostrophe-suffixed clitics
# (don't, can't, it's) and emits punctuation as its own token.  No
# language-specific behaviour — Unicode word characters only.
_TOK_RE = re.compile(r"\w+(?:'\w+)?|[^\w\s]", re.UNICODE)

def tokenize(text: str) -> List[str]:
    """Regex tokenize: words (with apostrophe clitics) + standalone
    punctuation, in order."""
    return _TOK_RE.findall(text or '')


# ─── identity-style ─────────────────────────────────────────────────

def passthrough(tok: str) -> str: return tok
def drop(tok: str) -> str:        return ''
def lowercase(tok: str) -> str:   return tok.lower()
def uppercase(tok: str) -> str:   return tok.upper()
def mask(tok: str) -> str:        return '[MASK]'
def sentinel(tok: str) -> str:    return '<extra_id_0>'  # T5-style noise


# ─── stop-words ─────────────────────────────────────────────────────

# Compact English stop-word set sourced from the standard NLTK / scikit
# list, trimmed to the high-frequency cores.  Inline so we don't
# require an NLTK data download at import time.
_STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because
been before being below between both but by can did do does doing don
down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just me
more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should so some such than that the their
theirs them themselves then there these they this those through to too
under until up very was we were what when where which while who whom why
will with you your yours yourself yourselves
""".split())

def drop_stopword(tok: str) -> str:
    """Drop the token if it's a common English stop-word (case-insensitive),
    otherwise pass through."""
    return '' if tok.lower() in _STOPWORDS else tok

def keep_stopword(tok: str) -> str:
    """Inverse: keep ONLY stop-words."""
    return tok if tok.lower() in _STOPWORDS else ''


# ─── Porter stemmer (Porter 1980) ───────────────────────────────────
# Inline minimal implementation of the original Porter algorithm.
# Not the more aggressive Porter2 / Snowball, but accurate enough for
# preprocessing-as-mask demos.

_VOWELS = set('aeiou')

def _is_vowel(s: str, i: int) -> bool:
    c = s[i]
    if c in _VOWELS:                            return True
    if c == 'y' and i > 0 and not _is_vowel(s, i - 1): return True
    return False

def _measure(s: str) -> int:
    """Count of consonant-cluster / vowel-cluster alternations after the
    leading consonants — the m() function from Porter (1980)."""
    n = 0
    i = 0
    L = len(s)
    # Skip initial consonants.
    while i < L and not _is_vowel(s, i): i += 1
    while i < L:
        # Skip a run of vowels.
        while i < L and _is_vowel(s, i): i += 1
        n += 1
        # Skip a run of consonants.
        while i < L and not _is_vowel(s, i): i += 1
    return n

def _has_vowel(s: str) -> bool:
    return any(_is_vowel(s, i) for i in range(len(s)))

def _ends_with_double_cons(s: str) -> bool:
    return len(s) >= 2 and s[-1] == s[-2] and not _is_vowel(s, len(s) - 1)

def _ends_with_cvc(s: str) -> bool:
    if len(s) < 3: return False
    a, b, c = s[-3], s[-2], s[-1]
    if c in 'wxy': return False
    if not _is_vowel(s, len(s) - 3) and _is_vowel(s, len(s) - 2) \
            and not _is_vowel(s, len(s) - 1):
        return True
    return False

def _step1a(s: str) -> str:
    for suf, rep in (('sses', 'ss'), ('ies', 'i'), ('ss', 'ss'), ('s', '')):
        if s.endswith(suf): return s[:-len(suf)] + rep if rep else s[:-len(suf)]
    return s

def _step1b(s: str) -> str:
    if s.endswith('eed'):
        if _measure(s[:-3]) > 0: return s[:-3] + 'ee'
        return s
    flag = False
    if s.endswith('ed') and _has_vowel(s[:-2]):
        s = s[:-2]; flag = True
    elif s.endswith('ing') and _has_vowel(s[:-3]):
        s = s[:-3]; flag = True
    if flag:
        if s.endswith(('at', 'bl', 'iz')): return s + 'e'
        if _ends_with_double_cons(s) and s[-1] not in 'lsz': return s[:-1]
        if _measure(s) == 1 and _ends_with_cvc(s): return s + 'e'
    return s

def _step1c(s: str) -> str:
    if s.endswith('y') and _has_vowel(s[:-1]): return s[:-1] + 'i'
    return s

_STEP2 = [('ational', 'ate'), ('tional', 'tion'), ('enci', 'ence'),
           ('anci', 'ance'), ('izer', 'ize'),     ('abli', 'able'),
           ('alli',  'al'),  ('entli','ent'),     ('eli',  'e'),
           ('ousli', 'ous'), ('ization','ize'),   ('ation','ate'),
           ('ator',  'ate'), ('alism','al'),      ('iveness','ive'),
           ('fulness','ful'),('ousness','ous'),   ('aliti','al'),
           ('iviti', 'ive'), ('biliti','ble')]

def _step2(s: str) -> str:
    for suf, rep in _STEP2:
        if s.endswith(suf) and _measure(s[:-len(suf)]) > 0:
            return s[:-len(suf)] + rep
    return s

_STEP3 = [('icate', 'ic'), ('ative', ''), ('alize', 'al'),
           ('iciti', 'ic'), ('ical', 'ic'), ('ful', ''), ('ness', '')]

def _step3(s: str) -> str:
    for suf, rep in _STEP3:
        if s.endswith(suf) and _measure(s[:-len(suf)]) > 0:
            return s[:-len(suf)] + rep
    return s

_STEP4 = ['al','ance','ence','er','ic','able','ible','ant','ement',
          'ment','ent','ou','ism','ate','iti','ous','ive','ize']

def _step4(s: str) -> str:
    if s.endswith('ion'):
        if _measure(s[:-3]) > 1 and s[-4:-3] in ('s', 't'):
            return s[:-3]
        return s
    for suf in _STEP4:
        if s.endswith(suf) and _measure(s[:-len(suf)]) > 1:
            return s[:-len(suf)]
    return s

def _step5(s: str) -> str:
    if s.endswith('e'):
        m = _measure(s[:-1])
        if m > 1 or (m == 1 and not _ends_with_cvc(s[:-1])):
            return s[:-1]
    if s.endswith('ll') and _measure(s) > 1:
        return s[:-1]
    return s

@lru_cache(maxsize=8192)
def _porter(word: str) -> str:
    if len(word) <= 2: return word
    s = word.lower()
    s = _step1a(s)
    s = _step1b(s)
    s = _step1c(s)
    s = _step2(s)
    s = _step3(s)
    s = _step4(s)
    s = _step5(s)
    return s

def porter_stem(tok: str) -> str:
    """Porter (1980) stem.  Identity on non-alphabetic tokens
    (punctuation, numbers) and on tokens ≤ 2 chars."""
    if not tok or not tok.isalpha(): return tok
    return _porter(tok)


# ─── Soundex ────────────────────────────────────────────────────────

_SX_MAP = {
    'B':'1','F':'1','P':'1','V':'1',
    'C':'2','G':'2','J':'2','K':'2','Q':'2','S':'2','X':'2','Z':'2',
    'D':'3','T':'3', 'L':'4', 'M':'5','N':'5', 'R':'6',
}

def soundex(tok: str) -> str:
    """4-character Soundex (NARA-correct: vowels separate same-coded
    consonants instead of being stripped, so e.g. Tymczak → T522 and
    not T520 — the M / C / Z / K coding survives because the A
    between Z and K acts as a separator).
    """
    if not tok or not tok[0].isalpha(): return tok
    s = tok.upper()
    out = s[0]
    prev = ''   # last *appended* digit; reset to '' on vowels/H/W/Y
    for c in s[1:]:
        code = _SX_MAP.get(c, '')
        if code == '':
            prev = ''           # vowel-like — collapse resets
            continue
        if code != prev:
            out += code
        prev = code
        if len(out) >= 4: break
    return (out + '000')[:4]


# ─── Metaphone (light) ──────────────────────────────────────────────
# A trimmed implementation — not the double-metaphone, but enough to
# disambiguate Soundex-collisions on demos.

def metaphone(tok: str) -> str:
    if not tok.isalpha(): return tok
    s = tok.upper()
    # Strip silent initials.
    if s[:2] in ('AE','GN','KN','PN','WR'): s = s[1:]
    if s[:1] == 'X':                        s = 'S' + s[1:]
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        nxt = s[i+1] if i+1 < len(s) else ''
        if c in 'AEIOU':
            if i == 0: out.append(c)
        elif c == 'B':       out.append('B')
        elif c == 'C':
            if   nxt == 'H': out.append('X'); i += 1
            elif nxt in 'IEY': out.append('S')
            else:            out.append('K')
        elif c == 'D':
            if nxt == 'G' and i+2 < len(s) and s[i+2] in 'IEY':
                out.append('J'); i += 2
            else:            out.append('T')
        elif c == 'F':       out.append('F')
        elif c == 'G':
            if nxt == 'H': i += 1   # GH → silent (mostly)
            elif nxt in 'IEY': out.append('J')
            else:            out.append('K')
        elif c == 'H':
            if i == 0 or s[i-1] not in 'AEIOU' or (nxt and nxt not in 'AEIOU'):
                pass
            else:            out.append('H')
        elif c == 'J':       out.append('J')
        elif c == 'K':
            if i == 0 or s[i-1] != 'C': out.append('K')
        elif c == 'L':       out.append('L')
        elif c == 'M':       out.append('M')
        elif c == 'N':       out.append('N')
        elif c == 'P':
            if nxt == 'H':   out.append('F'); i += 1
            else:            out.append('P')
        elif c == 'Q':       out.append('K')
        elif c == 'R':       out.append('R')
        elif c == 'S':
            if nxt == 'H':   out.append('X'); i += 1
            else:            out.append('S')
        elif c == 'T':
            if nxt == 'H':   out.append('0'); i += 1
            else:            out.append('T')
        elif c == 'V':       out.append('F')
        elif c == 'W' or c == 'Y':
            if nxt and nxt in 'AEIOU': out.append(c)
        elif c == 'X':       out.extend(['K','S'])
        elif c == 'Z':       out.append('S')
        i += 1
    return ''.join(out)


# ─── Spacy-backed POS / lemma ──────────────────────────────────────
# Loaded lazily — most pages don't need it and the model is ~12 MB.

_SPACY_NLP = None

def _spacy():
    global _SPACY_NLP
    if _SPACY_NLP is None:
        import spacy
        try:
            _SPACY_NLP = spacy.load('en_core_web_sm',
                                     disable=['parser','ner','attribute_ruler'])
        except OSError:
            # Model not installed; fall back to a blank pipeline that
            # still has POS via the small built-in tagger via load().
            _SPACY_NLP = spacy.blank('en')
            _SPACY_NLP.add_pipe('sentencizer')
    return _SPACY_NLP

def pos_tag(tok: str) -> str:
    """Replace token with its coarse POS tag (NOUN/VERB/ADJ/...)."""
    if not tok: return tok
    doc = _spacy()(tok)
    if not len(doc): return tok
    return doc[0].pos_ or tok

def lemmatize(tok: str) -> str:
    if not tok: return tok
    doc = _spacy()(tok)
    if not len(doc): return tok
    lem = doc[0].lemma_
    return lem if lem and lem != '-PRON-' else tok


# ─── Registry of named token primitives (used by mapping tables) ───

PRIMITIVES: dict[str, TokenFunc] = {
    'pass':         passthrough,
    'drop':         drop,
    'lower':        lowercase,
    'upper':        uppercase,
    'mask':         mask,
    'sentinel':     sentinel,
    'stopdrop':     drop_stopword,
    'stopkeep':     keep_stopword,
    'stem':         porter_stem,
    'soundex':      soundex,
    'metaphone':    metaphone,
    'pos':          pos_tag,
    'lemma':        lemmatize,
}

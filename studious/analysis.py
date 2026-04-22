"""Deterministic text analysis for Studious.

Nothing here calls out to an LLM. Everything is plain-Python arithmetic
on the corpus you've actually ingested. The three entry points:

* :func:`analyze_work` — scores distinguishing terms for one Work via
  TF-IDF against the rest of the Studious corpus.
* :func:`extract_candidate_claims` — heuristic sentence picker: prefers
  sentences that pattern-match known claim markers ("we argue that",
  "the central thesis is", …) and penalizes things that look like
  section headings or footnote debris.
* :func:`build_argument_scaffold` — given N :class:`Claim` objects,
  returns ``(premises_text, tension_text)`` filled with attributions and
  a shared-vocabulary hint; the user writes the synthesis themselves.

The extraction heuristics are intentionally boring — they should be
wrong-but-useful, not wrong-and-confident. The user always gets to edit
the output before it's used.
"""

from __future__ import annotations

import math
import re

from collections import Counter


_TOKEN_RE = re.compile(r"[a-z][a-z'\-]{2,}")

STOPWORDS = set("""
    the a an and or but if then than so that this these those there here their
    is am are was were be been being have has had do does did done doing
    not no nor of in to for on with by at from as about into through over under
    i you he she it we they me him her us them my mine your yours his hers
    its ours theirs self itself themselves
    what which who whom whose when where why how whether
    very much many more most less least some any each every one two three
    would should could may might must can will shall ought
    also only just yet still even ever never however moreover furthermore
    thus hence therefore because since while whereas although though
    such said say says like upon same other another either neither both
""".split())


_CLAIM_MARKERS = [
    'we argue', 'i argue', 'argues that', 'argue that',
    'we claim', 'i claim', 'claims that',
    'we propose', 'propose that', 'proposes that',
    'we maintain', 'maintains that',
    'we contend', 'contends that',
    'we hold', 'holds that',
    'we show', 'we demonstrate', 'we prove', 'we establish',
    'the thesis', 'central thesis', 'main thesis', 'our thesis',
    'the central claim', 'the main claim', 'the core claim',
    'the argument is', 'our argument', 'this paper argues',
    'this article argues', 'i will argue',
]

_HEDGE_MARKERS = [
    'unclear', 'not clear', 'uncertain', 'perhaps', 'possibly',
    'might be', 'may be', 'seems to', 'appears to', 'arguably',
    'tentatively', 'in some sense',
]

_QUESTION_MARKERS = ('?',)


def tokenize(text):
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def token_counts(text):
    counts = Counter()
    for tok in tokenize(text):
        if tok in STOPWORDS or len(tok) < 4:
            continue
        counts[tok] += 1
    return counts


def tf_idf_top(target_text, corpus_texts, k=40):
    """Score terms in ``target_text`` by TF-IDF against ``corpus_texts``.

    Returns a list of ``[term, weight, tf, df]`` sorted by weight desc.
    Weights use the smoothed formula ``tf * (log((1+N)/(1+df)) + 1)``
    so a term that only appears in the target still gets a finite lift.
    """
    target = token_counts(target_text)
    if not target:
        return []
    n = max(1, len(corpus_texts))
    doc_seen = []
    for text in corpus_texts:
        doc_seen.append(set(tokenize(text)))
    results = []
    for term, tf in target.items():
        df = sum(1 for seen in doc_seen if term in seen)
        idf = math.log((1 + n) / (1 + df)) + 1.0
        results.append([term, round(tf * idf, 3), tf, df])
    results.sort(key=lambda r: -r[1])
    return results[:k]


def analyze_work(work, corpus_qs=None, k=40):
    """Update ``work.analysis_json`` with TF-IDF scores + token stats."""
    from .models import Work
    text = (work.full_text or work.abstract or '').strip()
    if corpus_qs is None:
        corpus_qs = Work.objects.exclude(pk=work.pk)
    corpus_texts = []
    for w in corpus_qs.only('full_text', 'abstract'):
        corpus_texts.append(w.full_text or w.abstract or '')
    top = tf_idf_top(text, corpus_texts, k=k)
    counts = token_counts(text)
    work.analysis_json = {
        'top_terms': top,
        'n_tokens':  sum(counts.values()),
        'n_unique':  len(counts),
        'corpus_size': len(corpus_texts),
    }
    work.save(update_fields=['analysis_json'])
    return work.analysis_json


_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])[\s\n]+(?=[A-Z"\'\(])')


def split_sentences(text):
    if not text:
        return []
    squished = re.sub(r'\s+', ' ', text).strip()
    return [s.strip() for s in _SENTENCE_SPLIT.split(squished) if s.strip()]


def _classify_sentence(sent):
    """Return (kind, score, keep?) for a sentence. Score is 0..1-ish."""
    low = sent.lower()
    length = len(sent)
    if length < 40 or length > 500:
        return ('claim', 0.0, False)
    if any(m in low for m in _QUESTION_MARKERS) and sent.rstrip().endswith('?'):
        return ('question', 0.55, True)
    # Reject obvious non-claims: citations, references, section headings.
    if re.search(r'\([12]\d{3}\)', sent) and length < 120:
        return ('claim', 0.0, False)
    if low.startswith(('figure ', 'table ', 'fig. ', 'cf. ')):
        return ('claim', 0.0, False)
    score = 0.12
    kind = 'claim'
    for marker in _CLAIM_MARKERS:
        if marker in low:
            score += 0.55
            break
    for hint in (' is ', ' are ', ' must ', ' cannot ', ' therefore ',
                 ' thus ', ' hence ', ' because ', ' implies '):
        if hint in low:
            score += 0.07
    for hedge in _HEDGE_MARKERS:
        if hedge in low:
            kind = 'hedge'
            score += 0.20
            break
    if score < 0.25:
        return (kind, score, False)
    return (kind, min(1.0, score), True)


def extract_candidate_claims(text, max_candidates=40):
    """Return a list of ``(sentence, kind, score)`` candidates."""
    picked = []
    seen = set()
    for sent in split_sentences(text):
        kind, score, keep = _classify_sentence(sent)
        if not keep:
            continue
        key = sent[:120]
        if key in seen:
            continue
        seen.add(key)
        picked.append((sent, kind, round(score, 3)))
    picked.sort(key=lambda t: -t[2])
    return picked[:max_candidates]


def build_argument_scaffold(claims):
    """Render premises + tension blocks for an Argument from a list of Claims.

    Premises: one bullet per claim with scholar / work / year attribution.
    Tension: shared-vocabulary hint — which non-stopword terms appear in
    multiple claims, ordered by multiplicity. The user always edits or
    replaces this before publishing.
    """
    premises = []
    per_tokens = []
    for c in claims:
        scholar = c.work.scholar.name
        work = c.work.title
        year = f', {c.work.year}' if c.work.year else ''
        premises.append(f'— {scholar} — “{work}”{year}:\n  {c.text.strip()}')
        per_tokens.append({
            t for t in tokenize(c.text)
            if t not in STOPWORDS and len(t) >= 4
        })

    shared = Counter()
    for toks in per_tokens:
        shared.update(toks)
    multi = [(t, n) for t, n in shared.items() if n >= 2]
    multi.sort(key=lambda x: (-x[1], x[0]))
    top_shared = ', '.join(t for t, _ in multi[:12])

    if not claims:
        tension = 'No claims selected yet.'
    elif len(claims) == 1:
        tension = ('Only one claim selected — the tension block is '
                   'more useful when you braid at least two. '
                   f'Key terms in this claim: {top_shared or "—"}.')
    else:
        tension = (
            f'Shared vocabulary across {len(claims)} claims '
            f'(appearing in ≥2): {top_shared or "—"}.\n\n'
            'Points of apparent agreement: [name them yourself].\n\n'
            'Points of tension: [name them yourself — the shared terms '
            'above are a hint, not a finding].'
        )

    return ('\n\n'.join(premises), tension)


# ── PDF + URL helpers ──────────────────────────────────────────────
# Ingestion uses the same stack as Aggregator (trafilatura) plus pypdf
# for local PDFs. Both are optional — if a dep is missing the caller
# gets an empty string back and can fall back to raw paste.

def extract_pdf_text(file_obj):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ''
    try:
        reader = PdfReader(file_obj)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or '')
            except Exception:
                continue
        return '\n\n'.join(parts).strip()
    except Exception:
        return ''


def extract_url_text(url):
    try:
        import trafilatura
    except ImportError:
        return ''
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ''
        return trafilatura.extract(
            downloaded, include_comments=False,
            include_tables=False, favor_recall=True,
        ) or ''
    except Exception:
        return ''

"""Deterministic PHP sensitive-string scanner.

The privacy premise of ``datalift.site_lifter`` is that files shown
to an assistant must not carry row data or secrets. HTML/JS/CSS are
low-risk because they're structural; PHP is high-risk because it
mixes structure with inline DB calls, credentials, API keys, and
occasionally fixture data.

This module scans a PHP source string and returns a list of
:class:`Finding` records. The management command
:mod:`datalift.management.commands.liftphp` uses those records to:

* populate a security section of the worklist (categories + counts,
  line numbers, masked snippets — never the full secret)
* optionally write redacted copies of each file to a parallel tree,
  safe to hand to an assistant for conversion guidance
* exit nonzero under ``--strict`` so CI / pre-share gates can refuse
  the lift until a human has cleared findings

No LLM, no subprocess, no network. Pure regex + rules.

What it detects is deliberately a conservative superset. False
positives are cheaper than false negatives because a human reviews
every flagged file anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── Finding model ──────────────────────────────────────────────────

@dataclass
class Finding:
    category: str          # stable tag; used for grouping + redaction label
    severity: str          # 'critical' | 'high' | 'medium'
    line: int              # 1-based
    col: int               # 1-based (start of the match)
    length: int            # chars the finding covers in the source
    snippet: str           # a masked one-line excerpt for worklist display
    start: int = 0         # 0-based offset into source (for redaction)


_MASK = '█' * 8


def _mask_value(s: str) -> str:
    """Mask all but the first and last char of a secret, if long enough."""
    if len(s) <= 4:
        return _MASK
    return f'{s[0]}{_MASK}{s[-1]}'


def _line_col(text: str, offset: int) -> tuple[int, int]:
    prefix = text[:offset]
    line = prefix.count('\n') + 1
    col = offset - (prefix.rfind('\n') + 1 if '\n' in prefix else 0) + 1
    return line, col


def _excerpt(text: str, start: int, end: int, radius: int = 24) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    raw = text[a:b].replace('\n', ' ')
    # Trim to one line-ish, remove control chars.
    raw = re.sub(r'\s+', ' ', raw).strip()
    return raw


# ── Patterns ───────────────────────────────────────────────────────

# DB-connect call with literal args. We only flag when the 2nd or 3rd
# positional literal string is present — that's when a password is
# actually baked into the source. Variables/constants are handled by
# the password-const / password-var rules instead.
_DB_CONNECT_RE = re.compile(
    r"""
    \b(?P<fn>mysql_connect|mysqli_connect|pg_connect|odbc_connect)
    \s*\(\s*
    (?P<args>[^)]*)
    \)
    """,
    re.VERBOSE | re.IGNORECASE,
)

_PDO_RE = re.compile(
    r"""\bnew\s+PDO\s*\(\s*(?P<args>[^)]*)\)""",
    re.VERBOSE | re.IGNORECASE,
)

_STRING_LITERAL_RE = re.compile(
    r"""(?P<q>['"])(?P<val>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
    re.DOTALL,
)

# define('DB_PASSWORD', '...') — the classic config-file pattern.
_DEFINE_SECRET_RE = re.compile(
    r"""
    \bdefine\s*\(\s*
    (?P<qk>['"])(?P<key>[^'"]*(?:pass(?:word|wd)?|secret|api[_-]?key|token|
        auth[_-]?key|private[_-]?key|access[_-]?key)[^'"]*)(?P=qk)
    \s*,\s*
    (?P<qv>['"])(?P<val>[^'"]*)(?P=qv)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# $password = '...' / $api_key = "..."
_VAR_SECRET_RE = re.compile(
    r"""
    \$(?P<name>[A-Za-z_][A-Za-z0-9_]*
        (?:pass(?:word|wd)?|secret|api[_-]?key|token|
           auth[_-]?key|private[_-]?key|access[_-]?key|db[_-]?user)
       [A-Za-z0-9_]*)
    \s*=\s*
    (?P<q>['"])(?P<val>[^'"]*)(?P=q)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Cloud-key shapes (hard evidence, not heuristic).
_CLOUD_KEYS: list[tuple[str, re.Pattern]] = [
    ('aws-access-key',   re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('aws-secret',       re.compile(r'(?i)aws.{0,20}[\'"][0-9a-zA-Z/+]{40}[\'"]')),
    ('github-token',     re.compile(r'\bghp_[A-Za-z0-9]{36}\b')),
    ('github-pat-fine',  re.compile(r'\bgithub_pat_[A-Za-z0-9_]{82}\b')),
    ('slack-token',      re.compile(r'\bxox[bpoas]-[A-Za-z0-9-]{10,}\b')),
    ('stripe-key',       re.compile(r'\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{20,}\b')),
    ('google-api-key',   re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b')),
]

# PEM private-key block.
_PRIVATE_KEY_RE = re.compile(
    r'-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----'
    r'.*?'
    r'-----END (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----',
    re.DOTALL,
)

# http[s]://user:pass@host — classic basic-auth URL leak.
_BASIC_AUTH_URL_RE = re.compile(
    r'\bhttps?://[^\s:/@]+:[^\s:/@]+@[^\s/]+',
    re.IGNORECASE,
)

# Real-looking email, excluding placeholder-like domains.
_EMAIL_RE = re.compile(
    r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
)
_PLACEHOLDER_EMAIL_DOMAINS = {
    'example.com', 'example.org', 'example.net',
    'test.com', 'invalid', 'localhost',
    'foo.com', 'bar.com',
}

# Inline fixture SQL — a PHP script with literal INSERT VALUES in it
# is almost always ingesting seed data, and those values may be PII.
_INLINE_INSERT_RE = re.compile(
    r'INSERT\s+INTO\s+[`"]?\w+[`"]?\s*(?:\([^)]*\))?\s*VALUES\s*\(',
    re.IGNORECASE,
)


# ── Scan entrypoint ────────────────────────────────────────────────

def scan(text: str) -> list[Finding]:
    """Return findings for a single PHP source string, sorted by offset."""
    findings: list[Finding] = []

    # --- DB connect calls ---
    for m in _DB_CONNECT_RE.finditer(text):
        args = m.group('args')
        lits = list(_STRING_LITERAL_RE.finditer(args))
        # Flag whenever 2+ string literals are present (host, user, and
        # likely password) — that's when secrets are inline.
        if len(lits) >= 3:
            start = m.start()
            line, col = _line_col(text, start)
            findings.append(Finding(
                category='db-credentials',
                severity='critical',
                line=line,
                col=col,
                length=m.end() - m.start(),
                snippet=f'{m.group("fn")}(..., ..., {_MASK!s})',
                start=start,
            ))

    # --- PDO constructor ---
    for m in _PDO_RE.finditer(text):
        args = m.group('args')
        lits = list(_STRING_LITERAL_RE.finditer(args))
        if len(lits) >= 2:  # DSN + user, likely password follows
            start = m.start()
            line, col = _line_col(text, start)
            findings.append(Finding(
                category='db-credentials',
                severity='critical',
                line=line,
                col=col,
                length=m.end() - m.start(),
                snippet=f'new PDO(..., ..., {_MASK!s})',
                start=start,
            ))

    # --- define('DB_PASSWORD', '...') ---
    for m in _DEFINE_SECRET_RE.finditer(text):
        start = m.start()
        line, col = _line_col(text, start)
        findings.append(Finding(
            category='password-const',
            severity='critical',
            line=line,
            col=col,
            length=m.end() - m.start(),
            snippet=f"define('{m.group('key')}', {_mask_value(m.group('val'))})",
            start=start,
        ))

    # --- $password = '...' ---
    for m in _VAR_SECRET_RE.finditer(text):
        start = m.start()
        line, col = _line_col(text, start)
        findings.append(Finding(
            category='password-var',
            severity='high',
            line=line,
            col=col,
            length=m.end() - m.start(),
            snippet=f"${m.group('name')} = {_mask_value(m.group('val'))}",
            start=start,
        ))

    # --- Cloud keys ---
    for label, pat in _CLOUD_KEYS:
        for m in pat.finditer(text):
            start = m.start()
            line, col = _line_col(text, start)
            findings.append(Finding(
                category=label,
                severity='critical',
                line=line,
                col=col,
                length=m.end() - m.start(),
                snippet=_mask_value(m.group(0)),
                start=start,
            ))

    # --- PEM block ---
    for m in _PRIVATE_KEY_RE.finditer(text):
        start = m.start()
        line, col = _line_col(text, start)
        findings.append(Finding(
            category='private-key-block',
            severity='critical',
            line=line,
            col=col,
            length=m.end() - m.start(),
            snippet='-----BEGIN PRIVATE KEY----- … END …',
            start=start,
        ))

    # --- Basic-auth URL ---
    for m in _BASIC_AUTH_URL_RE.finditer(text):
        start = m.start()
        line, col = _line_col(text, start)
        findings.append(Finding(
            category='basic-auth-url',
            severity='critical',
            line=line,
            col=col,
            length=m.end() - m.start(),
            snippet=re.sub(r'://[^@]+@', f'://user:{_MASK}@', m.group(0)),
            start=start,
        ))

    # --- Emails (PII) ---
    for m in _EMAIL_RE.finditer(text):
        addr = m.group(0)
        domain = addr.rsplit('@', 1)[-1].lower()
        if any(domain == d or domain.endswith('.' + d)
               for d in _PLACEHOLDER_EMAIL_DOMAINS):
            continue
        start = m.start()
        line, col = _line_col(text, start)
        findings.append(Finding(
            category='email-pii',
            severity='medium',
            line=line,
            col=col,
            length=m.end() - m.start(),
            snippet=f'…@{domain}',
            start=start,
        ))

    # --- Inline INSERT fixture ---
    for m in _INLINE_INSERT_RE.finditer(text):
        start = m.start()
        line, col = _line_col(text, start)
        findings.append(Finding(
            category='inline-sql-insert',
            severity='high',
            line=line,
            col=col,
            length=m.end() - m.start(),
            snippet='INSERT INTO … VALUES (…)',
            start=start,
        ))

    findings.sort(key=lambda f: f.start)
    return findings


# ── Redaction ──────────────────────────────────────────────────────

def redact(text: str, findings: list[Finding]) -> str:
    """Return ``text`` with each finding replaced by a category marker.

    Replacements use the form ``/*<<CATEGORY>>*/`` so PHP syntax stays
    at least shallowly parseable (the comment form is valid in code
    and in string contexts with surrounding quotes intact — which
    isn't sufficient to guarantee the result parses, but it's safer
    than dropping raw bytes).

    Overlapping findings are coalesced by picking the outermost span
    per region.
    """
    if not findings:
        return text
    spans = sorted(
        ((f.start, f.start + f.length, f.category) for f in findings),
        key=lambda s: (s[0], -s[1]),
    )
    # Drop spans fully covered by an earlier (outer) span.
    coalesced: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, cat in spans:
        if s < last_end:
            continue
        coalesced.append((s, e, cat))
        last_end = e

    out: list[str] = []
    cursor = 0
    for s, e, cat in coalesced:
        out.append(text[cursor:s])
        marker = f'/*<<REDACTED_{cat.upper().replace("-", "_")}>>*/'
        out.append(marker)
        cursor = e
    out.append(text[cursor:])
    return ''.join(out)

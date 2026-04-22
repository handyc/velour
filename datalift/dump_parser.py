"""mysqldump text parser — pure Python, no database connection.

Two public iterators:

* :func:`iter_create_tables` yields ``(table_name, ddl_block)`` tuples from
  the ``CREATE TABLE ...;`` blocks in a mysqldump file.
* :func:`iter_inserts` yields ``(table_name, columns_or_none, rows)``
  tuples from ``INSERT INTO`` statements. Each row is a tuple of
  Python values (``str``, ``int``, ``float``, ``bytes``, ``None``).

The parser is pragmatic, not a full MySQL grammar. It is designed for
the default output of ``mysqldump`` (one statement per logical unit,
backslash-escaped strings, optional extended INSERT). It handles:

* ``NULL``, integers, decimals, scientific floats, negatives
* Single-quoted strings with ``\\\\ \\' \\" \\n \\r \\t \\0 \\Z`` escapes
* ``0xDEADBEEF`` hex literals (returned as ``bytes``)
* ``_binary 'foo'`` binary-string prefixes
* Multi-row extended INSERTs: ``INSERT ... VALUES (...), (...), (...);``
* ``AUTO_INCREMENT=<n>`` in CREATE TABLE (stripped by the schema tool)

It does **not** try to handle: multi-statement hex blobs split across
lines with custom delimiters, stored procedures, triggers, views, or
anything that relies on ``DELIMITER`` redefinition.
"""

from __future__ import annotations

import re
from typing import Iterator


# ── CREATE TABLE extraction ────────────────────────────────────────

# A CREATE TABLE block runs until a semicolon on a line where the
# paren-depth is back at zero. mysqldump wraps the whole definition in
# one statement with comments/spacing, so a simple parse works.

_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(?P<name>[^\s`\"(]+)[`\"]?\s*\(",
    re.IGNORECASE,
)


def iter_create_tables(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(table_name, full_ddl_block)`` for every CREATE TABLE.

    The DDL block is returned verbatim, terminated by ``;``. Callers
    that want to strip MySQL-isms (engine, charset, auto-increment
    counters) should do so themselves — this parser stays neutral.
    """
    i = 0
    n = len(text)
    while i < n:
        m = _CREATE_RE.search(text, i)
        if not m:
            break
        name = m.group('name')
        start = m.start()
        # Walk forward tracking paren depth + quoted strings until we
        # see the semicolon at depth 0.
        j = m.end() - 1  # position at the opening '('
        depth = 0
        in_s = False  # inside '...' or "..."
        quote_ch = ''
        while j < n:
            ch = text[j]
            if in_s:
                if ch == '\\' and j + 1 < n:
                    j += 2
                    continue
                if ch == quote_ch:
                    in_s = False
                j += 1
                continue
            if ch in ("'", '"'):
                in_s = True
                quote_ch = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ';' and depth == 0:
                yield name, text[start : j + 1]
                j += 1
                break
            j += 1
        i = j


# ── INSERT parsing ─────────────────────────────────────────────────

_INSERT_HEAD_RE = re.compile(
    r"INSERT\s+INTO\s+[`\"]?(?P<name>[^\s`\"]+)[`\"]?"
    r"\s*(?:\((?P<cols>[^)]*)\))?\s*VALUES\s*",
    re.IGNORECASE,
)

_COL_RE = re.compile(r"[`\"]?([A-Za-z_][A-Za-z0-9_]*)[`\"]?")


_ESCAPES = {
    '0':  '\0',
    'b':  '\b',
    'n':  '\n',
    'r':  '\r',
    't':  '\t',
    'Z':  '\x1a',
    '\\': '\\',
    "'":  "'",
    '"':  '"',
    '%':  '%',
    '_':  '_',
}


def iter_inserts(text: str) -> Iterator[tuple[str, list[str] | None, list[tuple]]]:
    """Yield ``(table_name, columns_or_None, rows)`` per INSERT statement.

    ``rows`` is a list of tuples of scalar Python values. If the INSERT
    had no explicit column list, ``columns_or_None`` is ``None`` and the
    caller should consult the CREATE TABLE for column order.
    """
    i = 0
    n = len(text)
    while i < n:
        m = _INSERT_HEAD_RE.search(text, i)
        if not m:
            break
        table = m.group('name')
        cols_raw = m.group('cols')
        columns = None
        if cols_raw is not None:
            columns = _COL_RE.findall(cols_raw)
        rows: list[tuple] = []
        j = m.end()
        while j < n:
            j = _skip_ws(text, j)
            if text[j] != '(':
                break
            row, j = _parse_tuple(text, j)
            rows.append(row)
            j = _skip_ws(text, j)
            if j < n and text[j] == ',':
                j += 1
                continue
            if j < n and text[j] == ';':
                j += 1
                break
            break
        yield table, columns, rows
        i = j


def _skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i] in ' \t\r\n':
        i += 1
    return i


def _parse_tuple(s: str, i: int) -> tuple[tuple, int]:
    assert s[i] == '('
    i += 1
    values: list = []
    while True:
        i = _skip_ws(s, i)
        v, i = _parse_value(s, i)
        values.append(v)
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == ',':
            i += 1
            continue
        if i < len(s) and s[i] == ')':
            i += 1
            return tuple(values), i
        raise ValueError(f'bad tuple at offset {i}: {s[i-10:i+10]!r}')


def _parse_value(s: str, i: int):
    n = len(s)
    # NULL
    if s[i:i+4].upper() == 'NULL':
        return None, i + 4
    # _binary 'xxx' prefix — treat as bytes
    if s[i:i+7].lower() == '_binary':
        i = _skip_ws(s, i + 7)
        v, j = _parse_string(s, i)
        return v.encode('latin-1', 'replace'), j
    # hex literal 0xDEADBEEF  → bytes
    if s[i] == '0' and i + 1 < n and s[i+1] in ('x', 'X'):
        j = i + 2
        while j < n and s[j] in '0123456789abcdefABCDEF':
            j += 1
        try:
            return bytes.fromhex(s[i+2:j]), j
        except ValueError:
            return s[i:j], j
    # Quoted string
    if s[i] == "'" or s[i] == '"':
        return _parse_string(s, i)
    # Numeric literal (int / float)
    j = i
    if s[j] in '+-':
        j += 1
    has_digit = False
    has_dot = False
    has_exp = False
    while j < n:
        ch = s[j]
        if ch.isdigit():
            has_digit = True
            j += 1
        elif ch == '.' and not has_dot and not has_exp:
            has_dot = True
            j += 1
        elif ch in 'eE' and has_digit and not has_exp:
            has_exp = True
            j += 1
            if j < n and s[j] in '+-':
                j += 1
        else:
            break
    if has_digit:
        token = s[i:j]
        try:
            if has_dot or has_exp:
                return float(token), j
            return int(token), j
        except ValueError:
            return token, j
    # Bareword (e.g. CURRENT_TIMESTAMP) — rare in mysqldump data rows,
    # but handle gracefully as a string.
    bw_re = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
    m = bw_re.match(s, i)
    if m:
        return m.group(0), m.end()
    raise ValueError(f'cannot parse value at offset {i}: {s[i:i+20]!r}')


def _parse_string(s: str, i: int) -> tuple[str, int]:
    quote = s[i]
    assert quote in ("'", '"')
    j = i + 1
    out = []
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == '\\':
            if j + 1 >= n:
                raise ValueError('truncated backslash escape')
            nxt = s[j + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            j += 2
            continue
        if ch == quote:
            # MySQL allows doubled quote as an escape: '' or ""
            if j + 1 < n and s[j + 1] == quote:
                out.append(quote)
                j += 2
                continue
            return ''.join(out), j + 1
        out.append(ch)
        j += 1
    raise ValueError('unterminated string')


# ── Convenience ────────────────────────────────────────────────────

def strip_auto_increment(ddl: str) -> str:
    """Remove ``AUTO_INCREMENT=<n>`` table options — those are row counts."""
    return re.sub(r'\s+AUTO_INCREMENT=\d+', '', ddl)

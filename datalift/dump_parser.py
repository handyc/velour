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


def _strip_table_prefix_placeholders(name: str) -> str:
    """Normalise a captured table name by stripping source-embedded
    placeholders that frameworks substitute at install time:

    * ``/*_*/table`` — MediaWiki table-prefix macro.
    * ``$wpdb->table``, ``${wpdb}->table`` — WordPress PHP variable.
    * ``#__table`` — Joomla installer prefix.
    * ``PREFIX_table`` / ``DB_PREFIX_table`` — PrestaShop / osCommerce
      literal-uppercase prefix, substituted at install time with e.g.
      ``ps_`` / ``osc_``.
    * ``{PREFIX}_table`` — generic curly-brace placeholder.
    * ``public.table`` / ``dbo.table`` / ``mydb.table`` — database /
      schema qualifier (pg_dump default, SQL Server dbo schema,
      mysqldump with explicit database). The final identifier wins.

    Returns the bare table name, or ``''`` if nothing survives (caller
    should skip the statement in that case).
    """
    # SQL comment blocks /* ... */
    name = re.sub(r'/\*[^*]*\*/', '', name)
    # PHP object-property placeholder: $wpdb-> / ${wpdb}-> / $wpdb->$foo->
    name = re.sub(r'\$\{?[A-Za-z_][\w.]*\}?->', '', name)
    # Joomla installer prefix: #__tablename → tablename
    name = re.sub(r'^#__', '', name)
    # PrestaShop / osCommerce literal uppercase prefix.
    # Require the trailing underscore to avoid chewing real table
    # names that merely happen to start with an uppercase run.
    name = re.sub(r'^(?:DB_PREFIX|PREFIX)_', '', name)
    # Generic curly-brace prefix ({PREFIX}_, {prefix}_)
    name = re.sub(r'\{[A-Za-z_][\w.]*\}_?', '', name)
    # Database/schema qualifier: keep only the last dotted segment.
    # Also strips double-quoted wrapping that pg_dump sometimes emits
    # around individual segments (e.g. `"public"."my_table"`).
    if '.' in name:
        name = name.rsplit('.', 1)[-1]
    name = name.strip('"\'` \t')
    return name.strip()


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
        name = _strip_table_prefix_placeholders(m.group('name'))
        if not name:
            # Degenerate: couldn't recover a usable name. Skip.
            i = m.end()
            continue
        start = m.start()
        # Walk forward tracking paren depth + quoted strings until we
        # see the semicolon at depth 0. SQL comments (`-- …`, `# …`,
        # `/* … */`) must be skipped cleanly — otherwise an apostrophe
        # in a French-language comment like `-- d'un element` flips
        # our string-state on and we swallow everything up to the
        # next apostrophe, typically losing dozens of tables.
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
            # Line comment: -- ...\n or # ...\n
            if (ch == '-' and j + 1 < n and text[j+1] == '-') or ch == '#':
                nl = text.find('\n', j)
                j = n if nl < 0 else nl + 1
                continue
            # Block comment: /* ... */
            if ch == '/' and j + 1 < n and text[j+1] == '*':
                close = text.find('*/', j + 2)
                j = n if close < 0 else close + 2
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
    # Exclude `(` from the name class so `INSERT INTO tbl(col1,col2)`
    # (no space before the paren, common in hand-authored dumps)
    # doesn't swallow the column list into the table name.
    r"INSERT\s+INTO\s+[`\"]?(?P<name>[^\s`\"(]+)[`\"]?"
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


def _strip_non_data_blocks(text: str) -> str:
    """Remove CREATE TRIGGER / CREATE VIEW / CREATE PROCEDURE /
    CREATE FUNCTION bodies before INSERT parsing.

    mysqldump wraps these in ``DELIMITER ;;`` blocks with ``BEGIN`` /
    ``END`` bodies that contain SQL statements — including
    ``INSERT INTO`` fragments that are trigger code, not data. The
    data parser would then try to evaluate trigger-scope references
    like ``new.film_id`` as literals and crash.

    Strategy: delete any ``DELIMITER ;;`` … ``DELIMITER ;`` block in
    its entirety, plus any bare ``CREATE VIEW`` / ``CREATE TRIGGER``
    / ``CREATE PROCEDURE`` / ``CREATE FUNCTION`` statement. Data
    INSERTs are never wrapped in DELIMITER blocks, so this is safe.
    """
    # 1. DELIMITER ;; … DELIMITER ; — mysqldump's wrapping
    text = re.sub(
        r'DELIMITER\s+;;\s.*?DELIMITER\s+;\s*',
        '\n',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # 2. Standalone CREATE VIEW / TRIGGER / PROCEDURE / FUNCTION (no
    #    DELIMITER wrap — terminates on semicolon at column 0).
    text = re.sub(
        r'CREATE\s+(?:ALGORITHM\s*=\s*\w+\s+)?'
        r'(?:DEFINER\s*=\s*[^\s]+\s+)?'
        r'(?:SQL\s+SECURITY\s+\w+\s+)?'
        r'(?:VIEW|TRIGGER|PROCEDURE|FUNCTION)\b[^;]*?;',
        '\n',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # 3. Inline MySQL version-gated value wrappers inside INSERTs —
    #    Sakila wraps BLOB columns as /*!50705 0x... */. We keep the
    #    inner payload so the value parser sees it as a plain hex
    #    literal. Only strip the /*!nnnnn  prefix and matching */.
    text = re.sub(r'/\*!\d+\s', '', text)
    text = text.replace('*/', '')
    # 4. SQL line comments: `-- …\n` and `# …\n`. Without this,
    #    Dolibarr's install SQL has shell-script snippets in
    #    comment lines with `echo "INSERT INTO …"` literals that
    #    our INSERT regex would otherwise match as real data.
    #    Preserve the newline so statement boundaries stay intact.
    text = re.sub(r'(^|\n)--[^\n]*', r'\1', text)
    text = re.sub(r'(^|\n)#[^\n]*', r'\1', text)
    return text


def iter_inserts(text: str) -> Iterator[tuple[str, list[str] | None, list[tuple]]]:
    """Yield ``(table_name, columns_or_None, rows)`` per INSERT statement.

    ``rows`` is a list of tuples of scalar Python values. If the INSERT
    had no explicit column list, ``columns_or_None`` is ``None`` and the
    caller should consult the CREATE TABLE for column order.

    Non-data blocks (CREATE VIEW / TRIGGER / PROCEDURE / FUNCTION, and
    anything inside a ``DELIMITER ;;`` wrap) are stripped up front so
    stray ``INSERT INTO`` fragments inside trigger bodies don't get
    parsed as data.
    """
    text = _strip_non_data_blocks(text)
    i = 0
    n = len(text)
    while i < n:
        m = _INSERT_HEAD_RE.search(text, i)
        if not m:
            break
        table = _strip_table_prefix_placeholders(m.group('name'))
        if not table:
            i = m.end()
            continue
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
    # MySQL version-gated value: /*!50705 <value> */  (BLOBs in Sakila
    # are wrapped this way). Peel the comment and parse what's inside.
    if s[i:i+2] == '/*' and i + 2 < n and s[i+2] == '!':
        end = s.find('*/', i + 3)
        if end > 0:
            inner = s[i+3:end].lstrip()
            # Skip past the version-digit prefix (e.g. "50705 ")
            k = 0
            while k < len(inner) and inner[k].isdigit():
                k += 1
            inner_val_start = i + 3 + (len(s[i+3:end]) - len(inner.lstrip())) + k
            # Simpler approach: parse the value from the start of the
            # significant content inside the comment.
            inner_start = i + 3
            while inner_start < end and s[inner_start] in ' \t':
                inner_start += 1
            while inner_start < end and s[inner_start].isdigit():
                inner_start += 1
            while inner_start < end and s[inner_start] in ' \t':
                inner_start += 1
            # Recurse on the cleaned substring
            val, _ = _parse_value(s, inner_start)
            return val, end + 2
    # NULL
    if s[i:i+4].upper() == 'NULL':
        return None, i + 4
    # _binary 'xxx' prefix — treat as bytes
    if s[i:i+7].lower() == '_binary':
        i = _skip_ws(s, i + 7)
        v, j = _parse_string(s, i)
        return v.encode('latin-1', 'replace'), j
    # SQL-Server-style Unicode string literal prefix: N'...'. MySQL
    # accepts this for utf8 literals; we've already normalised the
    # source to Python `str`, so just skip the N and parse as a
    # regular quoted string.
    if (s[i] in 'Nn' and i + 1 < n and s[i+1] == "'"):
        return _parse_string(s, i + 1)
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
    # Bareword / SQL-function call in INSERT VALUES.
    #
    # mysqldump's own output rarely embeds function calls in data
    # rows, but hand-authored installer SQL (Joomla, some custom
    # migrations) does. We consume a bareword and any immediately
    # following parenthesised argument list (`CURRENT_TIMESTAMP()`,
    # `DATE_FORMAT(...)`, etc.) to keep the tuple parser happy, then:
    #
    #   - For time-like functions, return a tz-aware "now" so
    #     DateTimeField happily accepts it.
    #   - For a bareword without parens, pass through as a string —
    #     this is the historical behaviour for `CURRENT_TIMESTAMP`
    #     without `()` and for things like NULL-adjacent tokens.
    #   - For any other function call, return None. Django's field
    #     default fills in from there; if the column is NOT NULL
    #     without a default, the user sees a clear IntegrityError
    #     instead of a mysterious string-coercion failure.
    bw_re = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
    m = bw_re.match(s, i)
    if m:
        j = m.end()
        token_name = m.group(0)
        is_function = j < n and s[j] == '('
        if is_function:
            depth = 1
            j += 1
            # Balance parens, respecting quoted strings.
            in_s = False
            quote_ch = ''
            while j < n and depth > 0:
                ch = s[j]
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
                    j += 1
                    continue
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                j += 1
        up = token_name.upper()
        TIMEY = {'CURRENT_TIMESTAMP', 'NOW', 'CURDATE', 'CURTIME',
                 'UTC_TIMESTAMP', 'LOCALTIME', 'LOCALTIMESTAMP',
                 'SYSDATE'}
        if up in TIMEY:
            from datetime import datetime, timezone
            return datetime.now(timezone.utc), j
        if is_function:
            # Unknown SQL function — treat as "let the DB / Django
            # fill in a default". NULL is the least-bad fallback.
            return None, j
        # Booleans are spelled as barewords in Postgres INSERTs:
        #     INSERT INTO … VALUES (…, true, false, …)
        # Return actual Python booleans so Django's BooleanField
        # doesn't reject the string "true".
        if up in ('TRUE', 'FALSE'):
            return (up == 'TRUE'), j
        # Installer-substituted placeholders: tokens like `__ENTITY__`
        # or `__DEPLOY_FOO__` appear in Dolibarr's seed SQL where
        # the installer swaps them for runtime values. We don't know
        # the replacement, so we return None — callers can map the
        # column to a default via value_maps if they need a specific
        # substitution. Recognised shape: `__UPPERCASE_WORDS__`.
        if re.fullmatch(r'__[A-Z][A-Z0-9_]*__', token_name):
            return None, j
        # Plain bareword: keep it as a string for back-compat.
        return token_name, j
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

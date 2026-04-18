"""Minimal BibTeX parser + citation formatting for Codex manuals.

`parse_bibtex(text)` returns a dict keyed by entry key:
    {'smith2020': {
        'type':    'article',
        'author':  [('Smith', 'John', '')],
        'year':    '2020',
        'title':   'The Title',
        'journal': 'Journal Name',
        # ...plus any other fields verbatim
    }}

Author lists are split on the word `and` and each name broken into
(last, first, middle) tuples. Braces around surnames survive
(`{van der Waals}` stays as one token).

`format_inline(entry, locator)` produces `(Smith 2020)` /
`(Smith & Jones 2021, p. 42)` / `(Alpha et al. 2019)`.

`format_reference(entry)` produces a single paragraph-worth of text
suitable for a References section. Three templates:
    article — Authors (Year). Title. Journal Vol(Issue), pp.
    book    — Authors (Year). *Title*. Publisher.
    default — Authors (Year). Title. (everything else).

Kept deliberately simple — BibTeX has fifteen years of edge cases
and we don't need to honour them. Anyone with a funky bibliography
can still write their References section by hand.
"""

import re


def parse_bibtex(text: str) -> dict:
    entries = {}
    for entry_type, key, body in _iter_entries(text):
        fields = _parse_fields(body)
        if 'author' in fields:
            fields['author'] = _split_names(fields['author'])
        if 'editor' in fields:
            fields['editor'] = _split_names(fields['editor'])
        fields['type'] = entry_type.lower()
        entries[key] = fields
    return entries


# --- tokenizer -------------------------------------------------------------

def _iter_entries(text):
    i = 0
    while i < len(text):
        at = text.find('@', i)
        if at < 0:
            return
        brace = text.find('{', at)
        if brace < 0:
            return
        entry_type = text[at + 1:brace].strip()
        if not entry_type or entry_type.lower() in ('comment', 'preamble', 'string'):
            # Skip non-entry blocks.
            end = _match_brace(text, brace)
            i = end + 1 if end > 0 else at + 1
            continue
        end = _match_brace(text, brace)
        if end < 0:
            return
        inner = text[brace + 1:end]
        comma = inner.find(',')
        if comma < 0:
            i = end + 1
            continue
        key = inner[:comma].strip()
        body = inner[comma + 1:]
        if key:
            yield entry_type, key, body
        i = end + 1


def _match_brace(text, start):
    """Return the index of the `}` matching the `{` at `start`, or -1."""
    depth = 0
    for j in range(start, len(text)):
        c = text[j]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return j
    return -1


def _parse_fields(body: str) -> dict:
    """body is everything after the entry key + comma, before the closing
    brace. Walk it looking for `key = value,` pairs."""
    fields = {}
    i = 0
    n = len(body)
    while i < n:
        # Skip whitespace + stray commas.
        while i < n and body[i] in ' \t\n\r,':
            i += 1
        if i >= n:
            break
        eq = body.find('=', i)
        if eq < 0:
            break
        key = body[i:eq].strip().lower()
        j = eq + 1
        while j < n and body[j] in ' \t\n\r':
            j += 1
        if j >= n:
            break
        value, j = _read_value(body, j)
        if key:
            fields[key] = value.strip()
        i = j
    return fields


def _read_value(body, i):
    n = len(body)
    if i >= n:
        return '', i
    c = body[i]
    if c == '{':
        end = _match_brace(body, i)
        if end < 0:
            return body[i + 1:], n
        return _strip_braces(body[i + 1:end]), end + 1
    if c == '"':
        j = i + 1
        while j < n and body[j] != '"':
            j += 1
        return body[i + 1:j], j + 1
    # Bare token (number, @string reference): up to the next comma.
    j = i
    while j < n and body[j] != ',':
        j += 1
    return body[i:j].strip(), j


_BRACE_RUN_RE = re.compile(r'\{([^{}]*)\}')


def _strip_braces(s):
    """Collapse single-level brace groups: `{van der Waals}` → `van der Waals`.
    Outer braces have already been stripped by the caller; what remains is
    inner grouping that BibTeX uses to preserve capitalization or keep
    multi-word names together. For our purposes, flatten it."""
    prev = None
    while prev != s:
        prev = s
        s = _BRACE_RUN_RE.sub(r'\1', s)
    return s


# --- author names ----------------------------------------------------------

def _split_names(s):
    """Split a BibTeX author/editor field on the word `and` and parse
    each name into a (last, first, middle) tuple.

    Supports `Last, First` as well as `First Middle Last`. Braced
    surnames `{van der Waals}` stay intact."""
    # `and` as a whole word, case-insensitive, only outside braces.
    parts = []
    depth = 0
    cur = []
    tokens = re.split(r'(\s+and\s+)', s, flags=re.IGNORECASE)
    # Easier path: split with brace awareness by walking.
    parts = []
    cur = []
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '{':
            depth += 1
            cur.append(c)
            i += 1
        elif c == '}':
            depth -= 1
            cur.append(c)
            i += 1
        elif depth == 0 and s[i:i + 5].lower() == ' and ':
            parts.append(''.join(cur).strip())
            cur = []
            i += 5
        else:
            cur.append(c)
            i += 1
    if cur:
        parts.append(''.join(cur).strip())

    return [_parse_name(p) for p in parts if p]


def _parse_name(name):
    name = _strip_braces(name.strip())
    if ',' in name:
        last, rest = name.split(',', 1)
        rest = rest.strip()
        first, _, middle = rest.partition(' ')
        return (last.strip(), first, middle.strip())
    # Space-separated: last name is the final token.
    toks = name.split()
    if not toks:
        return ('', '', '')
    if len(toks) == 1:
        return (toks[0], '', '')
    return (toks[-1], toks[0], ' '.join(toks[1:-1]))


# --- formatters ------------------------------------------------------------

def _author_year_label(entry):
    authors = entry.get('author') or entry.get('editor') or []
    year = str(entry.get('year', '')).strip()
    if not authors:
        return year or '?'
    if len(authors) == 1:
        return f'{authors[0][0]} {year}'.strip()
    if len(authors) == 2:
        return f'{authors[0][0]} & {authors[1][0]} {year}'.strip()
    return f'{authors[0][0]} et al. {year}'.strip()


def format_inline(entry, locator=''):
    label = _author_year_label(entry)
    if locator:
        return f'({label}, {locator})'
    return f'({label})'


def _full_authors(authors):
    out = []
    for last, first, middle in authors:
        initials = ''
        if first:
            initials += first[0].upper() + '.'
        if middle:
            initials += ' ' + ' '.join(t[0].upper() + '.' for t in middle.split() if t)
        if initials:
            out.append(f'{last}, {initials.strip()}')
        else:
            out.append(last)
    if not out:
        return ''
    if len(out) == 1:
        return out[0]
    return ', '.join(out[:-1]) + ' & ' + out[-1]


def format_reference(entry):
    """Return a single paragraph for the References section.

    Doesn't escape or italicize — the renderer handles emphasis via its
    normal `*italic*` markdown inline syntax. Book titles get wrapped
    in `*...*` so they render italicized.
    """
    authors = entry.get('author') or entry.get('editor') or []
    year = entry.get('year', '').strip()
    title = entry.get('title', '').strip()
    kind = entry.get('type', '')
    parts = []
    author_str = _full_authors(authors)
    if author_str:
        parts.append(author_str)
    if year:
        parts.append(f'({year})')
    head = ' '.join(parts).rstrip()
    if head:
        head += '. '

    if kind in ('book', 'phdthesis', 'mastersthesis'):
        core = f'*{title}*.' if title else ''
        pub = entry.get('publisher', '').strip()
        addr = entry.get('address', '').strip()
        tail = ': '.join(t for t in [addr, pub] if t)
        if tail:
            core = (core + ' ' if core else '') + tail + '.'
        return head + core

    if kind == 'article':
        journal = entry.get('journal', '').strip()
        vol = entry.get('volume', '').strip()
        num = entry.get('number', '').strip()
        pages = entry.get('pages', '').strip()
        core = title + '. ' if title else ''
        if journal:
            vol_bit = f' *{vol}*' if vol else ''
            num_bit = f'({num})' if num else ''
            page_bit = f', {pages}' if pages else ''
            core += f'*{journal}*{vol_bit}{num_bit}{page_bit}.'
        return head + core.rstrip()

    if kind == 'inproceedings' or kind == 'incollection':
        booktitle = entry.get('booktitle', '').strip()
        pages = entry.get('pages', '').strip()
        core = title + '. ' if title else ''
        if booktitle:
            core += f'In *{booktitle}*'
            if pages:
                core += f', {pages}'
            core += '.'
        return head + core.rstrip()

    # Misc / techreport / online / unknown: just title + note + url.
    core = title + '.' if title else ''
    url = entry.get('url', '').strip()
    if url:
        core = (core + ' ' if core else '') + url
    return head + core

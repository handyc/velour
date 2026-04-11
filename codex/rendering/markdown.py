"""Tiny markdown parser tailored to the Codex renderer.

Block syntax:
  # ## ### Heading
  - bullet item            (consecutive lines collapse into one list)
  > quote                  (consecutive lines collapse)
  !fig:slug                (figure reference)
  !figs cols=N a b c d ... (small multiples grid of figure slugs)
  !slope:Left,Right        (slope graph; data lines follow as `name: v1,v2`)
  ```                      (fenced code block; opens until next ```)
  | a | b |                (markdown table; needs separator row of |---|)
  :::note ... :::          (callout / admonition; kinds: note tip warn danger)
  blank line               (paragraph break)
  anything else            (paragraph)

Inline syntax:
  **bold**
  *italic*
  ^[note text]             (inline sidenote — Pandoc style)
  [text](url)              (link; rendered as text + a sidenote with the URL)
  [[spark:DATA|OPTS]]      (inline Tufte sparkline)

Sparkline forms:
    [[spark:1,2,3,4,5]]
    [[spark:1,2,3,4,5 | end]]
    [[spark:1,2,3,4,5 | end min max]]
    [[spark:1,2,3,4,5 | end band(2,4)]]
    [[spark:1,2,3,4,5 | bar]]

Output: list of (kind, payload) tuples consumed by the renderer.

Block kinds and payloads:
  h1 / h2 / h3   payload = heading text (str)
  p              payload = list of inline runs
  ul             payload = list of inline-runs lists
  quote          payload = list of inline runs
  blank          payload = None
  fig            payload = slug str
  figs           payload = {'cols': int, 'slugs': list[str]}
  slope          payload = {'left_label', 'right_label', 'series'}
  code           payload = source str (untouched, monospace)
  table          payload = {'header': list[runs], 'rows': list[list[runs]]}
  callout        payload = {'kind': str, 'blocks': list[block]}

Inline run tags:
  ('text', style, text)   style is '' / 'B' / 'I'
  ('note', text)
  ('spark', spec_dict)
  ('link', text, url)     renderer typically prints the text and queues
                          a sidenote containing the url
"""

import re


# Tokenizer regex: longest/most-specific patterns first.
_TOKEN_RE = re.compile(
    r'(\[\[spark:[^\]]+\]\]'
    r'|\^\[[^\]]+\]'
    r'|\[[^\]]+\]\([^)]+\)'
    r'|\*\*[^*\n]+\*\*'
    r'|\*[^*\n]+\*)'
)

_BAND_RE = re.compile(r'band\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)')

_LINK_RE = re.compile(r'^\[([^\]]+)\]\(([^)]+)\)$')


def _parse_spark(body):
    if '|' in body:
        data_str, opts_str = body.split('|', 1)
    else:
        data_str, opts_str = body, ''

    try:
        data = [float(x.strip()) for x in data_str.split(',') if x.strip()]
    except ValueError:
        return None
    if len(data) < 2:
        return None

    options = set()
    band = None
    for token in opts_str.replace(',', ' ').split():
        token = token.strip()
        if token in ('end', 'min', 'max', 'bar'):
            options.add(token)
            continue
        m = _BAND_RE.match(token)
        if m:
            band = (float(m.group(1)), float(m.group(2)))
            continue
    if band is None:
        m = _BAND_RE.search(opts_str)
        if m:
            band = (float(m.group(1)), float(m.group(2)))

    return {'data': data, 'options': options, 'band': band}


def parse_inline(text):
    runs = []
    for piece in _TOKEN_RE.split(text):
        if not piece:
            continue
        if piece.startswith('[[spark:') and piece.endswith(']]'):
            spec = _parse_spark(piece[len('[[spark:'):-2])
            if spec:
                runs.append(('spark', spec))
            else:
                runs.append(('text', '', piece))
        elif piece.startswith('^[') and piece.endswith(']'):
            runs.append(('note', piece[2:-1]))
        elif piece.startswith('[') and ')' in piece:
            m = _LINK_RE.match(piece)
            if m:
                runs.append(('link', m.group(1), m.group(2)))
            else:
                runs.append(('text', '', piece))
        elif piece.startswith('**') and piece.endswith('**'):
            runs.append(('text', 'B', piece[2:-2]))
        elif piece.startswith('*') and piece.endswith('*'):
            runs.append(('text', 'I', piece[1:-1]))
        else:
            runs.append(('text', '', piece))
    return runs


# --- block-level parsers ---------------------------------------------------

_CALLOUT_KINDS = {'note', 'tip', 'warn', 'warning', 'danger', 'info'}


def _parse_table_lines(lines, start):
    """Try to parse a markdown pipe-syntax table starting at lines[start].

    Returns (table_block, next_index) on success, or (None, start) if
    the lines don't form a valid table.
    """
    first = lines[start].strip()
    if not first.startswith('|') or not first.endswith('|'):
        return None, start
    if start + 1 >= len(lines):
        return None, start
    sep = lines[start + 1].strip()
    if not sep.startswith('|') or not all(c in ' |-:' for c in sep):
        return None, start

    def _split_row(row):
        return [c.strip() for c in row.strip().strip('|').split('|')]

    header = [parse_inline(c) for c in _split_row(first)]
    rows = []
    i = start + 2
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip().startswith('|'):
            break
        rows.append([parse_inline(c) for c in _split_row(ln)])
        i += 1
    return ('table', {'header': header, 'rows': rows}), i


def _parse_slope(lines, start):
    """Parse a slope graph block.

    Format:
        !slope:LeftLabel,RightLabel
        SeriesName: leftValue, rightValue
        OtherSeries: leftValue, rightValue
        (blank line ends)
    """
    head = lines[start].strip()
    if not head.startswith('!slope'):
        return None, start
    after = head[len('!slope'):].lstrip(':').strip()
    if ',' in after:
        left_label, right_label = [s.strip() for s in after.split(',', 1)]
    else:
        left_label, right_label = '', after

    series = []
    i = start + 1
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            break
        if ':' not in ln:
            break
        name, vals = ln.split(':', 1)
        try:
            parts = [float(x.strip()) for x in vals.split(',')]
        except ValueError:
            break
        if len(parts) != 2:
            break
        series.append((name.strip(), parts[0], parts[1]))
        i += 1

    if not series:
        return None, start
    return ('slope', {
        'left_label': left_label,
        'right_label': right_label,
        'series': series,
    }), i


def _parse_figs(line):
    """Parse `!figs cols=N slug1 slug2 ...` into a small-multiples block."""
    rest = line[len('!figs'):].strip()
    cols = 2
    slugs = []
    for tok in rest.split():
        if tok.startswith('cols='):
            try:
                cols = max(1, int(tok[5:]))
            except ValueError:
                pass
        else:
            slugs.append(tok)
    if not slugs:
        return None
    return ('figs', {'cols': cols, 'slugs': slugs})


def _parse_callout(lines, start):
    """Parse a `:::kind ... :::` block. Content is recursively parsed."""
    head = lines[start].strip()
    if not head.startswith(':::'):
        return None, start
    kind = head[3:].strip().lower() or 'note'
    if kind not in _CALLOUT_KINDS:
        return None, start

    inner = []
    i = start + 1
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.strip() == ':::':
            i += 1
            break
        inner.append(lines[i])
        i += 1

    inner_blocks = parse('\n'.join(inner))
    return ('callout', {'kind': kind, 'blocks': inner_blocks}), i


def _parse_code_fence(lines, start):
    """Parse a ```...``` fenced code block. Returns the source untouched."""
    if not lines[start].strip().startswith('```'):
        return None, start
    code_lines = []
    i = start + 1
    while i < len(lines):
        if lines[i].strip().startswith('```'):
            i += 1
            break
        code_lines.append(lines[i])
        i += 1
    return ('code', '\n'.join(code_lines)), i


def parse(body):
    blocks = []
    lines = body.replace('\r\n', '\n').split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            blocks.append(('blank', None))
            i += 1
            continue

        # Headings
        if line.startswith('### '):
            blocks.append(('h3', line[4:].strip()))
            i += 1
            continue
        if line.startswith('## '):
            blocks.append(('h2', line[3:].strip()))
            i += 1
            continue
        if line.startswith('# '):
            blocks.append(('h1', line[2:].strip()))
            i += 1
            continue

        # Code fence
        if stripped.startswith('```'):
            blk, ni = _parse_code_fence(lines, i)
            if blk:
                blocks.append(blk)
                i = ni
                continue

        # Callout
        if stripped.startswith(':::'):
            blk, ni = _parse_callout(lines, i)
            if blk:
                blocks.append(blk)
                i = ni
                continue

        # Slope graph
        if stripped.startswith('!slope'):
            blk, ni = _parse_slope(lines, i)
            if blk:
                blocks.append(blk)
                i = ni
                continue

        # Small multiples
        if stripped.startswith('!figs'):
            blk = _parse_figs(stripped)
            if blk:
                blocks.append(blk)
                i += 1
                continue

        # Single figure
        if stripped.startswith('!fig:'):
            blocks.append(('fig', stripped[5:].strip()))
            i += 1
            continue

        # Table
        if stripped.startswith('|'):
            blk, ni = _parse_table_lines(lines, i)
            if blk:
                blocks.append(blk)
                i = ni
                continue

        # Bullet list
        if line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].rstrip().startswith('- '):
                items.append(parse_inline(lines[i].rstrip()[2:]))
                i += 1
            blocks.append(('ul', items))
            continue

        # Blockquote
        if line.startswith('> '):
            quoted_lines = []
            while i < len(lines) and lines[i].rstrip().startswith('> '):
                quoted_lines.append(lines[i].rstrip()[2:])
                i += 1
            joined = ' '.join(quoted_lines)
            blocks.append(('quote', parse_inline(joined)))
            continue

        # Plain paragraph
        para_lines = []
        while i < len(lines):
            ln = lines[i].rstrip()
            if not ln.strip():
                break
            ls = ln.lstrip()
            if (ln.startswith('# ') or ln.startswith('## ') or
                ln.startswith('### ') or ln.startswith('- ') or
                ln.startswith('> ') or ls.startswith('```') or
                ls.startswith(':::') or ls.startswith('!') or
                ls.startswith('|')):
                break
            para_lines.append(ln)
            i += 1
        joined = ' '.join(para_lines)
        blocks.append(('p', parse_inline(joined)))

    # Strip leading/trailing/duplicate blanks.
    cleaned = []
    for blk in blocks:
        if blk[0] == 'blank':
            if cleaned and cleaned[-1][0] != 'blank':
                cleaned.append(blk)
        else:
            cleaned.append(blk)
    while cleaned and cleaned[-1][0] == 'blank':
        cleaned.pop()
    return cleaned

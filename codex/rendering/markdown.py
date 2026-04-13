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
  :::chart TYPE ... :::    (quantitative chart block)
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
    [[spark:1,2,3,4,5 | area]]
    [[spark:1,2,3,4,5 | dot]]
    [[spark:1,1,-1,1,-1 | winloss]]

Chart block forms:
    :::chart bar
    title: Server response times (ms)
    data: API=120, Web=95, WS=340, DB=42
    :::

    :::chart bullet
    title: CPU load
    actual: 72
    target: 80
    ranges: 50,80,100
    :::

    :::chart sparkstrip
    title: Weekly trends
    Disk: 40,42,45,43,48,52,55
    CPU:  12,15,14,18,22,19,16
    :::

    :::chart line
    title: Requests per hour
    data: 120,135,142,138,156,170,165,180,192,188
    :::

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
  chart          payload = {'chart_type': str, ...spec keys}

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
        if token in ('end', 'min', 'max', 'bar', 'area', 'dot', 'winloss'):
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

_CHART_TYPES = {'bar', 'line', 'bullet', 'scatter', 'histogram',
                'sparkstrip', 'column'}


def _parse_table_lines(lines, start, options=None):
    """Try to parse a markdown pipe-syntax table starting at lines[start].

    `options` is a set of flags ('bordered', 'noheader') that affect
    rendering. Returns (table_block, next_index) on success, or
    (None, start) if the lines don't form a valid table.
    """
    options = options or set()
    first = lines[start].strip()
    if not first.startswith('|') or not first.endswith('|'):
        return None, start

    def _split_row(row):
        return [c.strip() for c in row.strip().strip('|').split('|')]

    if 'noheader' in options:
        # All rows are data; there's no separator line.
        rows = []
        i = start
        while i < len(lines):
            ln = lines[i].rstrip()
            if not ln.strip().startswith('|'):
                break
            rows.append([parse_inline(c) for c in _split_row(ln)])
            i += 1
        return ('table', {
            'header': None, 'rows': rows,
            'bordered': 'bordered' in options,
        }), i

    if start + 1 >= len(lines):
        return None, start
    sep = lines[start + 1].strip()
    if not sep.startswith('|') or not all(c in ' |-:' for c in sep):
        return None, start

    header = [parse_inline(c) for c in _split_row(first)]
    rows = []
    i = start + 2
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip().startswith('|'):
            break
        rows.append([parse_inline(c) for c in _split_row(ln)])
        i += 1
    return ('table', {
        'header': header, 'rows': rows,
        'bordered': 'bordered' in options,
    }), i


def _parse_table_directive(lines, start):
    """Handle `!table:options` followed by a markdown table."""
    head = lines[start].strip()
    if not head.startswith('!table'):
        return None, start
    rest = head[len('!table'):].lstrip(':').strip()
    options = {tok.strip() for tok in rest.split() if tok.strip()}
    # The actual table starts on the next non-blank line.
    i = start + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not lines[i].strip().startswith('|'):
        return None, start
    return _parse_table_lines(lines, i, options=options)


def _parse_def_block(lines, start):
    """Parse a `:::def ... :::` definition list block.

    Each line inside is a `Label: value` pair. Empty lines are
    skipped. The output payload is a list of (label, runs) tuples.
    """
    head = lines[start].strip()
    if head not in (':::def', ':::deflist'):
        return None, start

    pairs = []
    i = start + 1
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.strip() == ':::':
            i += 1
            break
        if not ln.strip():
            i += 1
            continue
        if ':' in ln:
            label, value = ln.split(':', 1)
            pairs.append((label.strip(), parse_inline(value.strip())))
        else:
            # No colon → treat as a label-only entry.
            pairs.append((ln.strip(), []))
        i += 1
    if not pairs:
        return None, start
    return ('def', {'pairs': pairs}), i


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


def _parse_chart(lines, start):
    """Parse a `:::chart TYPE ... :::` block into a chart spec.

    Supports these key formats inside the block:
      title: Chart Title
      data: Label=Value, Label=Value, ...      (for bar/column)
      data: 1,2,3,4,5                          (for line/histogram)
      actual: 72                               (for bullet)
      target: 80                               (for bullet)
      ranges: 50,80,100                        (for bullet)
      label: Some Label                        (for bullet)
      bins: 10                                 (for histogram)
      highlight: 2                             (for bar)
      Label: 1,2,3,4                           (for sparkstrip — unnamed key = series)
      series: Name=1,2,3;Other=4,5,6           (for line multi-series)
    """
    head = lines[start].strip()
    if not head.startswith(':::chart'):
        return None, start

    rest = head[len(':::chart'):].strip()
    parts = rest.split(None, 1)
    chart_type = parts[0].lower() if parts else ''
    if chart_type not in _CHART_TYPES:
        return None, start

    spec = {'chart_type': chart_type}
    sparkstrip_series = []
    i = start + 1

    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.strip() == ':::':
            i += 1
            break
        if not ln.strip():
            i += 1
            continue

        if ':' in ln:
            key, val = ln.split(':', 1)
            key = key.strip()
            val = val.strip()
            key_lower = key.lower()

            if key_lower == 'title':
                spec['title'] = val
            elif key_lower == 'data':
                if '=' in val:
                    # Label=Value pairs
                    pairs = []
                    for item in val.split(','):
                        item = item.strip()
                        if '=' in item:
                            k, v = item.split('=', 1)
                            try:
                                pairs.append((k.strip(), float(v.strip())))
                            except ValueError:
                                pass
                    spec['data'] = pairs
                else:
                    # Plain numeric list
                    try:
                        spec['data'] = [float(x.strip())
                                        for x in val.split(',') if x.strip()]
                    except ValueError:
                        pass
            elif key_lower == 'actual':
                try:
                    spec['actual'] = float(val)
                except ValueError:
                    pass
            elif key_lower == 'target':
                try:
                    spec['target'] = float(val)
                except ValueError:
                    pass
            elif key_lower == 'ranges':
                try:
                    spec['ranges'] = [float(x.strip())
                                      for x in val.split(',') if x.strip()]
                except ValueError:
                    pass
            elif key_lower == 'label':
                spec['label'] = val
            elif key_lower == 'bins':
                try:
                    spec['bins'] = int(val)
                except ValueError:
                    pass
            elif key_lower == 'highlight':
                try:
                    spec['highlight'] = int(val)
                except ValueError:
                    pass
            elif key_lower == 'labels':
                spec['labels'] = [x.strip() for x in val.split(',')]
            elif key_lower == 'series':
                # Multi-series: Name=1,2,3;Other=4,5,6
                series_list = []
                for part in val.split(';'):
                    part = part.strip()
                    if '=' in part:
                        sname, svals = part.split('=', 1)
                        try:
                            series_list.append((
                                sname.strip(),
                                [float(x.strip()) for x in svals.split(',')
                                 if x.strip()]
                            ))
                        except ValueError:
                            pass
                spec['series'] = series_list
            else:
                # Unknown key — if chart_type is sparkstrip, treat as
                # a named series (e.g. "CPU: 12,15,14")
                if chart_type == 'sparkstrip':
                    try:
                        values = [float(x.strip())
                                  for x in val.split(',') if x.strip()]
                        if values:
                            sparkstrip_series.append((key, values))
                    except ValueError:
                        pass
        i += 1

    if chart_type == 'sparkstrip' and sparkstrip_series:
        spec['series'] = sparkstrip_series

    return ('chart', spec), i


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

        # Chart block (:::chart TYPE ... :::) — check before callout
        if stripped.startswith(':::chart'):
            blk, ni = _parse_chart(lines, i)
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

        # Definition list (:::def ... :::)
        if stripped in (':::def', ':::deflist'):
            blk, ni = _parse_def_block(lines, i)
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

        # Table directive (!table:bordered etc) followed by | rows
        if stripped.startswith('!table'):
            blk, ni = _parse_table_directive(lines, i)
            if blk:
                blocks.append(blk)
                i = ni
                continue

        # Plain pipe table
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
                ls.startswith('|') or ls.startswith('!table')):
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

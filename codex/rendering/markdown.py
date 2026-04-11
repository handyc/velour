"""Tiny markdown parser tailored to the Codex renderer.

Supports a deliberately small subset:
  - `# Heading`     → H1 block
  - `## Heading`    → H2 block
  - `### Heading`   → H3 block
  - `- item`        → bullet list item (consecutive lines collapse into one list)
  - `> quote`       → blockquote line (consecutive lines collapse)
  - `!fig:slug`     → figure reference (looks up Figure with that slug in section)
  - blank line      → paragraph break
  - everything else → paragraph block

Inline:
  - `**bold**` and `*italic*`
  - `^[note text]` — inline sidenote (Pandoc syntax). The renderer
    emits a small raised number at the anchor point and hangs the
    note in the right margin.

The parser output is a list of (kind, payload) tuples. For paragraph
and quote blocks the payload is a list of "runs" — each run is a tuple
where the first element is a tag ('text' / 'note') and the rest depend
on the tag:
  - ('text', style, text) — style is '' / 'B' / 'I'
  - ('note', text)        — sidenote text; renderer assigns a number

Figure blocks: ('fig', slug)
"""

import re


# Tokenizer regex: match either an inline sidenote ^[...] (allows nested
# brackets via simple non-greedy matching), or **bold**, or *italic*.
# Order matters — the sidenote alternative is tried first.
_TOKEN_RE = re.compile(
    r'(\^\[[^\]]+\]|\*\*[^*\n]+\*\*|\*[^*\n]+\*)'
)


def parse_inline(text):
    """Convert a string with formatting markers into a list of runs.

    Each run is one of:
      ('text', style, text) — style is '' / 'B' / 'I'
      ('note', text)         — inline sidenote
    """
    runs = []
    for piece in _TOKEN_RE.split(text):
        if not piece:
            continue
        if piece.startswith('^[') and piece.endswith(']'):
            runs.append(('note', piece[2:-1]))
        elif piece.startswith('**') and piece.endswith('**'):
            runs.append(('text', 'B', piece[2:-2]))
        elif piece.startswith('*') and piece.endswith('*'):
            runs.append(('text', 'I', piece[1:-1]))
        else:
            runs.append(('text', '', piece))
    return runs


def parse(body):
    """Parse a markdown body into a list of blocks.

    Each block is a (kind, payload) tuple. `kind` is one of:
      'h1' / 'h2' / 'h3' — payload is the heading text (str)
      'p'                — payload is a list of (style, text) runs
      'ul'               — payload is a list of inline-runs lists
      'quote'            — payload is a list of (style, text) runs
      'blank'            — payload is None
    """
    blocks = []
    lines = body.replace('\r\n', '\n').split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            blocks.append(('blank', None))
            i += 1
            continue

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

        # Figure reference: !fig:slug-of-figure
        if line.startswith('!fig:'):
            blocks.append(('fig', line[5:].strip()))
            i += 1
            continue

        # Bullet list — collect consecutive "- " lines
        if line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].rstrip().startswith('- '):
                items.append(parse_inline(lines[i].rstrip()[2:]))
                i += 1
            blocks.append(('ul', items))
            continue

        # Blockquote — collect consecutive "> " lines
        if line.startswith('> '):
            quoted_lines = []
            while i < len(lines) and lines[i].rstrip().startswith('> '):
                quoted_lines.append(lines[i].rstrip()[2:])
                i += 1
            joined = ' '.join(quoted_lines)
            blocks.append(('quote', parse_inline(joined)))
            continue

        # Plain paragraph — collect consecutive non-special non-blank lines
        para_lines = []
        while i < len(lines):
            ln = lines[i].rstrip()
            if not ln.strip():
                break
            if (ln.startswith('# ') or ln.startswith('## ') or
                ln.startswith('### ') or ln.startswith('- ') or
                ln.startswith('> ')):
                break
            para_lines.append(ln)
            i += 1
        joined = ' '.join(para_lines)
        blocks.append(('p', parse_inline(joined)))

    # Strip leading/trailing/duplicate blanks for cleaner rendering.
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

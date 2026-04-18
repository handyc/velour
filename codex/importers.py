"""Manuscript importers — feed external documents into Codex.

Each importer converts a source blob into plain markdown that Section.body
can take verbatim. The job stops at "text that looks like our markdown"
— figures, tables, and footnotes get degraded to prose; operators can
upgrade them by hand afterwards.

Formats:
  .txt  .md        — passthrough (txt gets stripped of trailing whitespace).
  .html .htm       — BeautifulSoup → markdown (headings, paragraphs,
                     lists, emphasis, inline code, code blocks).
  .docx            — zipfile + lxml over word/document.xml; headings come
                     from paragraph style (Heading1..6), lists from
                     numPr, emphasis from rPr.
  .odt .rtf .tex .epub
                    — gated on pandoc being on PATH. If it isn't, the
                      importer raises ImportError with install guidance.

After conversion, `split_sections(md)` carves the markdown at H1/H2
boundaries so each chunk becomes a Section row.
"""

import re
import shutil
import subprocess
import zipfile
from pathlib import Path


# --- dispatcher ------------------------------------------------------------

_NATIVE = {'.txt', '.md', '.markdown', '.html', '.htm', '.docx'}
_PANDOC_ONLY = {'.odt', '.rtf', '.tex', '.latex', '.epub', '.org', '.rst'}


def supported_extensions():
    extra = sorted(_PANDOC_ONLY) if shutil.which('pandoc') else []
    return sorted(_NATIVE) + extra


def import_bytes(data: bytes, filename: str) -> str:
    """Convert an uploaded file's bytes to markdown.

    Raises ValueError for unsupported extensions and ImportError when
    a pandoc-gated format is requested but pandoc isn't installed.
    """
    ext = Path(filename).suffix.lower()
    if ext in ('.txt',):
        return _txt_to_md(data)
    if ext in ('.md', '.markdown'):
        return data.decode('utf-8', errors='replace')
    if ext in ('.html', '.htm'):
        return _html_to_md(data.decode('utf-8', errors='replace'))
    if ext == '.docx':
        return _docx_to_md(data)
    if ext in _PANDOC_ONLY:
        if not shutil.which('pandoc'):
            raise ImportError(
                f'{ext} import needs pandoc on PATH. Install with '
                f'`sudo apt install pandoc` (or equivalent).')
        return _pandoc_to_md(data, ext)
    raise ValueError(f'Unsupported file type: {ext or "(no extension)"}')


# --- txt / html ------------------------------------------------------------

def _txt_to_md(data: bytes) -> str:
    text = data.decode('utf-8', errors='replace')
    # Collapse >2 blank lines but keep paragraph breaks.
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


_BLOCK_TAGS = {'p', 'div', 'section', 'article'}


def _html_to_md(html: str) -> str:
    from bs4 import BeautifulSoup, NavigableString

    soup = BeautifulSoup(html, 'html.parser')
    # Strip non-content wrappers.
    for tag in soup(['script', 'style', 'nav', 'footer', 'aside']):
        tag.decompose()
    root = soup.body or soup

    def walk(node, depth=0):
        if isinstance(node, NavigableString):
            return _inline_text(str(node))
        name = node.name or ''
        if name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            level = int(name[1])
            return '\n\n' + ('#' * level) + ' ' + _inline_children(node) + '\n\n'
        if name in _BLOCK_TAGS:
            return '\n\n' + ''.join(walk(c, depth) for c in node.children).strip() + '\n\n'
        if name == 'br':
            return '\n'
        if name == 'hr':
            return '\n\n---\n\n'
        if name == 'pre':
            return '\n\n```\n' + node.get_text() + '\n```\n\n'
        if name == 'blockquote':
            inner = ''.join(walk(c, depth) for c in node.children).strip()
            return '\n\n' + '\n'.join('> ' + ln for ln in inner.splitlines()) + '\n\n'
        if name in {'ul', 'ol'}:
            marker_iter = _list_markers(name)
            out = ['']
            for li in node.find_all('li', recursive=False):
                out.append(next(marker_iter) + ' ' + _inline_children(li).strip())
            out.append('')
            return '\n'.join(out)
        if name in {'strong', 'b'}:
            return '**' + _inline_children(node) + '**'
        if name in {'em', 'i'}:
            return '*' + _inline_children(node) + '*'
        if name == 'code':
            return '`' + node.get_text() + '`'
        if name == 'a':
            href = node.get('href', '')
            text = _inline_children(node)
            return f'[{text}]({href})' if href else text
        # Default: concatenate children.
        return ''.join(walk(c, depth) for c in node.children)

    def _inline_children(node):
        return ''.join(walk(c) for c in node.children)

    md = walk(root)
    return _collapse_blanks(md).strip() + '\n'


def _list_markers(name):
    if name == 'ol':
        n = 1
        while True:
            yield f'{n}.'
            n += 1
    while True:
        yield '-'


def _inline_text(s):
    # Collapse runs of whitespace inside text nodes; HTML treats them as one.
    return re.sub(r'\s+', ' ', s)


def _collapse_blanks(s):
    return re.sub(r'\n{3,}', '\n\n', s)


# --- docx ------------------------------------------------------------------

_W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _docx_to_md(data: bytes) -> str:
    import io
    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        with z.open('word/document.xml') as f:
            tree = etree.parse(f)

    body = tree.getroot().find(_W_NS + 'body')
    out = []
    in_list = False
    for p in body.findall(_W_NS + 'p'):
        style = _docx_paragraph_style(p)
        text = _docx_paragraph_text(p)
        if not text.strip() and not style.startswith('heading'):
            if in_list:
                out.append('')
                in_list = False
            out.append('')
            continue
        if style.startswith('heading'):
            level = int(style[7:] or '1')
            out.append('\n' + ('#' * level) + ' ' + text.strip() + '\n')
            in_list = False
        elif style == 'list':
            out.append('- ' + text.strip())
            in_list = True
        else:
            if in_list:
                out.append('')
                in_list = False
            out.append(text.strip())
    return _collapse_blanks('\n'.join(out)).strip() + '\n'


def _docx_paragraph_style(p):
    ppr = p.find(_W_NS + 'pPr')
    if ppr is None:
        return ''
    pstyle = ppr.find(_W_NS + 'pStyle')
    if pstyle is not None:
        val = (pstyle.get(_W_NS + 'val') or '').lower()
        m = re.match(r'heading(\d+)', val)
        if m:
            return 'heading' + m.group(1)
    if ppr.find(_W_NS + 'numPr') is not None:
        return 'list'
    return ''


def _docx_paragraph_text(p):
    parts = []
    for r in p.findall(_W_NS + 'r'):
        rpr = r.find(_W_NS + 'rPr')
        bold   = rpr is not None and rpr.find(_W_NS + 'b') is not None
        italic = rpr is not None and rpr.find(_W_NS + 'i') is not None
        text = ''.join(t.text or '' for t in r.findall(_W_NS + 't'))
        if bold:
            text = f'**{text}**'
        if italic:
            text = f'*{text}*'
        parts.append(text)
    return ''.join(parts)


# --- pandoc ----------------------------------------------------------------

def _pandoc_to_md(data: bytes, ext: str) -> str:
    fmt = {'.tex': 'latex', '.latex': 'latex'}.get(ext, ext.lstrip('.'))
    result = subprocess.run(
        ['pandoc', '-f', fmt, '-t', 'gfm', '--wrap=none'],
        input=data, capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f'pandoc failed: {result.stderr.decode("utf-8", "replace")[:400]}')
    return result.stdout.decode('utf-8', errors='replace')


# --- section splitter ------------------------------------------------------

def split_sections(markdown: str):
    """Slice markdown into (title, body) pairs at H1/H2 boundaries.

    Content before the first heading becomes a leading "Preamble" section
    (skipped if empty). If there are no headings at all, the whole blob
    is one untitled section the caller can name.
    """
    lines = markdown.splitlines()
    sections = []
    current_title = None
    current_body = []

    for line in lines:
        m = re.match(r'^(#{1,2})\s+(.+?)\s*$', line)
        if m:
            if current_title is not None or any(l.strip() for l in current_body):
                sections.append((current_title, '\n'.join(current_body).strip()))
            current_title = m.group(2).strip()
            current_body = []
        else:
            current_body.append(line)

    if current_title is not None or any(l.strip() for l in current_body):
        sections.append((current_title, '\n'.join(current_body).strip()))

    return sections

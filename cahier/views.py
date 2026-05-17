"""Cahier views — list and render notebooks via nbconvert when available,
falling back to a structural preview built from the raw .ipynb JSON so
the page works even on a fresh checkout without the convert toolchain."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import (FileResponse, Http404, HttpResponse,
                            JsonResponse)
from django.shortcuts import get_object_or_404, render

from .models import NotebookProject


def _notebook_path(project: NotebookProject) -> Optional[Path]:
    """Resolve the notebook's path; return None if it's missing."""
    p = Path(settings.BASE_DIR) / project.path
    return p if p.exists() else None


def _structural_preview(nb_json: dict) -> str:
    """Render a notebook to minimal HTML using only its raw JSON — no
    nbconvert dependency.  Code cells become <pre>; markdown cells
    become escaped markdown (raw, no rendering — just lets you read it).
    Outputs (text/plain, text/html) are shown when present."""
    from html import escape
    parts: list[str] = []
    for i, cell in enumerate(nb_json.get('cells', [])):
        kind = cell.get('cell_type', '')
        src = cell.get('source', '')
        if isinstance(src, list):
            src = ''.join(src)
        if kind == 'markdown':
            parts.append(
                f'<div class="cell md">'
                f'<pre class="cell-source">{escape(src)}</pre>'
                f'</div>')
        elif kind == 'code':
            count = cell.get('execution_count')
            count_s = f'In [{count}]' if count else 'In [ ]'
            parts.append(
                f'<div class="cell code">'
                f'<div class="prompt">{escape(count_s)}</div>'
                f'<pre class="cell-source"><code>{escape(src)}</code></pre>')
            for out in cell.get('outputs', []):
                ot = out.get('output_type', '')
                if ot == 'stream':
                    text = out.get('text', '')
                    if isinstance(text, list):
                        text = ''.join(text)
                    parts.append(
                        f'<pre class="output stream">{escape(text)}</pre>')
                elif ot in ('execute_result', 'display_data'):
                    data = out.get('data', {})
                    txt = data.get('text/plain', '')
                    if isinstance(txt, list):
                        txt = ''.join(txt)
                    if txt:
                        parts.append(
                            f'<pre class="output result">{escape(txt)}</pre>')
                elif ot == 'error':
                    tb = out.get('traceback', [])
                    parts.append(
                        f'<pre class="output error">'
                        f'{escape("".join(tb))}</pre>')
            parts.append('</div>')
        else:
            parts.append(
                f'<div class="cell unknown"><i>(cell {i}: {kind})</i></div>')
    return '\n'.join(parts)


@login_required
def index(request):
    """Catalogue of every NotebookProject."""
    qs = NotebookProject.objects.all()
    tag_filter = (request.GET.get('tag') or '').strip()
    if tag_filter:
        qs = [p for p in qs if tag_filter in p.tag_list()]
    rows = []
    for p in qs:
        path = _notebook_path(p)
        rows.append({
            'project':  p,
            'exists':   path is not None,
            'size_kb':  (path.stat().st_size / 1024) if path else None,
        })
    return render(request, 'cahier/index.html', {
        'rows':       rows,
        'tag_filter': tag_filter,
    })


@login_required
def detail(request, slug):
    project = get_object_or_404(NotebookProject, slug=slug)
    path = _notebook_path(project)
    if path is None:
        return render(request, 'cahier/detail.html', {
            'project': project,
            'missing': True,
        })
    nb = json.loads(path.read_text())
    cells = nb.get('cells', [])
    return render(request, 'cahier/detail.html', {
        'project':       project,
        'path':          str(path),
        'n_cells':       len(cells),
        'n_code':        sum(1 for c in cells if c.get('cell_type') == 'code'),
        'n_markdown':    sum(1 for c in cells
                              if c.get('cell_type') == 'markdown'),
        'preview_html':  _structural_preview(nb),
    })


@login_required
def raw(request, slug):
    """Serve the raw .ipynb JSON for download / external rendering."""
    project = get_object_or_404(NotebookProject, slug=slug)
    path = _notebook_path(project)
    if path is None:
        raise Http404
    return JsonResponse(json.loads(path.read_text()))


@login_required
def html(request, slug):
    """Render via nbconvert when available; otherwise fall back to the
    structural preview rendered as a standalone HTML page."""
    project = get_object_or_404(NotebookProject, slug=slug)
    path = _notebook_path(project)
    if path is None:
        raise Http404
    nb = json.loads(path.read_text())
    try:
        import nbconvert
        from nbformat import reads
        body, _resources = nbconvert.HTMLExporter().from_notebook_node(
            reads(json.dumps(nb), as_version=4))
        return HttpResponse(body, content_type='text/html; charset=utf-8')
    except Exception:
        body = (
            '<!doctype html><meta charset="utf-8">'
            f'<title>{project.title}</title>'
            '<style>body{font-family:ui-monospace,monospace;'
            'background:#0d1117;color:#c9d1d9;max-width:50em;'
            'margin:1em auto;padding:0 1em}.cell{margin:1em 0}'
            '.prompt{color:#79c0ff;font-size:.75rem}'
            '.cell-source{background:#161b22;padding:.6em;'
            'border-radius:4px;white-space:pre-wrap}'
            '.output{background:#0a0d12;padding:.6em;'
            'border-left:3px solid #2da44e;white-space:pre-wrap}'
            '.output.error{border-left-color:#f85149;color:#ff7b72}'
            '</style>'
            f'<h1>{project.title}</h1>'
            f'{_structural_preview(nb)}')
        return HttpResponse(body, content_type='text/html; charset=utf-8')


@login_required
def download(request, slug):
    project = get_object_or_404(NotebookProject, slug=slug)
    path = _notebook_path(project)
    if path is None:
        raise Http404
    return FileResponse(open(path, 'rb'),
                            as_attachment=True,
                            filename=path.name,
                            content_type='application/x-ipynb+json')

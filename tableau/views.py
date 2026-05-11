"""Tableau views.

Two pages — an index listing worlds, and a per-world editor that pairs
an isometric canvas (JS-driven) with a live FOL sentence panel.

The editor talks back through three JSON endpoints:
  • ``world_state``     — current World + Blocks + Sentences, called on
                          page load and after any mutation
  • ``blocks_post``     — POST {action: place|remove|clear, …}
  • ``sentences_post``  — POST {action: upsert|delete|reorder, …}
  • ``evaluate_all``    — server-side parse + eval, returns per-row T/F

JSON-only API on the backend means the same renderer is reused for
"build a world from scratch" and (later) "solve a puzzle".
"""
from __future__ import annotations

import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import logic
from .models import Block, Sentence, World


# ── pages ───────────────────────────────────────────────────────────


def index(request):
    worlds = World.objects.all()
    return render(request, 'tableau/index.html', {'worlds': worlds})


def world_new(request):
    if request.method != 'POST':
        return render(request, 'tableau/new.html')
    name = (request.POST.get('name') or 'untitled').strip()[:80]
    mode = request.POST.get('mode')
    if mode not in (World.MODE_SQUARE, World.MODE_HEX):
        return HttpResponseBadRequest('bad mode')
    try:
        dim = int(request.POST.get('dim') or 8)
    except ValueError:
        return HttpResponseBadRequest('bad dim')
    dim = max(1, min(12, dim))
    w = World.objects.create(name=name, mode=mode, dim=dim)
    return redirect('tableau:world_detail', pk=w.pk)


def world_detail(request, pk):
    w = get_object_or_404(World, pk=pk)
    return render(request, 'tableau/detail.html', {'world': w})


@require_POST
def world_delete(request, pk):
    w = get_object_or_404(World, pk=pk)
    w.delete()
    return redirect('tableau:index')


# ── JSON ────────────────────────────────────────────────────────────


def _serialise_world(w):
    blocks = list(w.blocks.all().values('id', 'shape', 'size', 'name', 'x', 'y'))
    sentences = list(w.sentences.all().values(
        'id', 'text', 'target_mode', 'position', 'parsed', 'parse_error'))
    return {
        'id': w.id,
        'name': w.name,
        'mode': w.mode,
        'dim':  w.dim,
        'blocks': blocks,
        'sentences': sentences,
    }


def world_state(request, pk):
    w = get_object_or_404(World, pk=pk)
    return JsonResponse(_serialise_world(w))


@csrf_exempt
@require_POST
def blocks_post(request, pk):
    """Mutate blocks on a world.

    Body: ``{"action": "place", "shape": …, "size": …, "name": "a",
              "x": 3, "y": 4}`` — atomic: removes any existing block at
              (x, y), then inserts the new one.  Also removes any other
              block sharing the supplied name (Tarski names are unique
              per world).
    Body: ``{"action": "remove", "x": 3, "y": 4}``
    Body: ``{"action": "clear"}``
    """
    w = get_object_or_404(World, pk=pk)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('bad json')
    action = payload.get('action')

    if action == 'clear':
        w.blocks.all().delete()
        return JsonResponse(_serialise_world(w))

    if action == 'remove':
        x = int(payload.get('x', 0))
        y = int(payload.get('y', 0))
        w.blocks.filter(x=x, y=y).delete()
        return JsonResponse(_serialise_world(w))

    if action == 'place':
        shape = payload.get('shape')
        size  = payload.get('size')
        name  = (payload.get('name') or '').strip()[:8]
        try:
            x = int(payload['x']); y = int(payload['y'])
        except (KeyError, ValueError, TypeError):
            return HttpResponseBadRequest('bad coords')
        if shape not in dict(Block.SHAPE_CHOICES):
            return HttpResponseBadRequest('bad shape')
        if size not in dict(Block.SIZE_CHOICES):
            return HttpResponseBadRequest('bad size')
        if not w.in_bounds(x, y):
            return HttpResponseBadRequest('out of bounds')
        # Atomic replace: remove existing at this cell + any other with
        # the same name (Tarski names are unique per world).
        w.blocks.filter(x=x, y=y).delete()
        if name:
            w.blocks.filter(name=name).delete()
        Block.objects.create(world=w, shape=shape, size=size, name=name,
                             x=x, y=y)
        return JsonResponse(_serialise_world(w))

    return HttpResponseBadRequest('bad action')


def _reparse(sentence: Sentence):
    """Re-derive parsed AST + parse_error from the current text."""
    try:
        ast = logic.parse(sentence.text)
        sentence.parsed = ast
        sentence.parse_error = ''
    except (logic.ParseError, ValueError) as e:
        sentence.parsed = None
        sentence.parse_error = str(e)


@csrf_exempt
@require_POST
def sentences_post(request, pk):
    """Mutate sentences on a world.

    Body shapes:
      • ``{"action": "upsert", "id": null, "text": "...",
            "target_mode": "both"}``  — create new (id null) or update (id set)
      • ``{"action": "delete", "id": 7}``
      • ``{"action": "reorder", "ids": [3, 1, 2]}``
    """
    w = get_object_or_404(World, pk=pk)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('bad json')
    action = payload.get('action')

    if action == 'upsert':
        text = (payload.get('text') or '').strip()
        target = payload.get('target_mode') or 'both'
        if target not in dict(Sentence.TARGET_CHOICES):
            return HttpResponseBadRequest('bad target')
        sid = payload.get('id')
        if sid:
            try:
                s = w.sentences.get(pk=sid)
            except Sentence.DoesNotExist:
                return HttpResponseBadRequest('not found')
            s.text = text
            s.target_mode = target
            _reparse(s)
            s.save()
        else:
            pos = (w.sentences.count())
            s = Sentence(world=w, text=text, target_mode=target, position=pos)
            _reparse(s)
            s.save()
        return JsonResponse(_serialise_world(w))

    if action == 'delete':
        sid = payload.get('id')
        w.sentences.filter(pk=sid).delete()
        return JsonResponse(_serialise_world(w))

    if action == 'reorder':
        ids = payload.get('ids') or []
        for pos, sid in enumerate(ids):
            w.sentences.filter(pk=sid).update(position=pos)
        return JsonResponse(_serialise_world(w))

    return HttpResponseBadRequest('bad action')


def evaluate_all(request, pk):
    """Evaluate every sentence on a world against its current blocks.

    Returns ``{"results": [{"id": n, "ok": bool, "value": bool|null,
                            "error": str}, ...]}``.
    """
    w = get_object_or_404(World, pk=pk)
    blocks = list(w.blocks.all())
    results = []
    for s in w.sentences.all().order_by('position', 'id'):
        if s.parsed is None:
            results.append({
                'id': s.id, 'ok': False, 'value': None,
                'error': s.parse_error or 'parse error',
            })
            continue
        # JSON-serialised AST comes back with lists; the evaluator
        # accepts either tuples or lists, but normalise to be safe.
        ast = _astify(s.parsed)
        try:
            v = logic.evaluate(ast, w, blocks=blocks)
            results.append({
                'id': s.id, 'ok': True, 'value': bool(v), 'error': '',
            })
        except logic.EvalError as e:
            results.append({
                'id': s.id, 'ok': False, 'value': None,
                'error': f'eval error: {e}',
            })
    return JsonResponse({'results': results})


def _astify(node):
    """Recursively convert JSON-decoded lists back into tuples so the
    evaluator's structural pattern matches.  Lists at arg-positions
    (e.g. predicate args) stay as lists."""
    if not isinstance(node, list):
        return node
    if not node:
        return node
    kind = node[0]
    if kind == 'pred':
        return ('pred', node[1], list(node[2]))
    if kind == 'eq':
        return ('eq', node[1], node[2])
    if kind == 'not':
        return ('not', _astify(node[1]))
    if kind in ('and', 'or', 'impl', 'iff'):
        return (kind, _astify(node[1]), _astify(node[2]))
    if kind in ('all', 'exists'):
        return (kind, node[1], _astify(node[2]))
    return tuple(node)

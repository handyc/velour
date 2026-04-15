"""Legolith views.

list: recent worlds with thumbnails.
detail: single world with a full-detail isometric render.
generate: form to roll a new world (biome + seed + counts).
png: render a world as PNG on the fly (thumbnail or detail).
pdf_math_book: printable N-page mixed math worksheet PDF.
pdf_worlds_gallery: 4-up gallery of the N most recent worlds.
pdf_worlds_detailed: one-per-page detailed booklet of the N most recent worlds.
"""

from __future__ import annotations

import io
import json
import os
import random
import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import worlds as W
from . import lsystem as L
from .brick_render import Brick, new_scene, draw_group, PLATE_H
from .models import BIOME_CHOICES, KIND_CHOICES, LegoModel, LegoWorld


# ---------------------------------------------------------------------------
# list + detail + generate
# ---------------------------------------------------------------------------
@login_required
def world_list(request):
    worlds = LegoWorld.objects.all()[:120]
    return render(request, 'legolith/list.html', {
        'worlds': worlds,
        'total_count': LegoWorld.objects.count(),
        'biomes': [b for b, _ in BIOME_CHOICES],
    })


@login_required
def world_detail(request, slug):
    world = get_object_or_404(LegoWorld, slug=slug)
    return render(request, 'legolith/detail.html', {
        'world': world,
    })


@login_required
def world_generate(request):
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        biome = request.POST.get('biome') or 'plains'
        seed_raw = (request.POST.get('seed') or '').strip()

        def _i(key, default, lo=0, hi=16):
            try:
                v = int(request.POST.get(key) or default)
            except ValueError:
                v = default
            return max(lo, min(hi, v))

        if not seed_raw:
            seed = random.randint(1, 999999)
        else:
            try:
                seed = int(seed_raw)
            except ValueError:
                seed = abs(hash(seed_raw)) % 999999

        nb = _i('n_buildings', 2)
        nt = _i('n_trees', 4)
        nf = _i('n_flowers', 4)
        np_ = _i('n_people', 2)
        nh = _i('n_hills', 0, hi=4)
        nl = _i('n_lamps', 0, hi=8)
        nr = _i('n_rocks', 0, hi=8)

        if not name:
            name = f'world-{seed}'

        world = W.build_world(
            name=slugify(name)[:80] or 'world', biome=biome, seed=seed,
            n_buildings=nb, n_trees=nt, n_flowers=nf, n_people=np_,
            n_hills=nh, n_lamps=nl, n_rocks=nr,
        )
        row = LegoWorld(
            name=name, biome=biome, seed=seed,
            baseplate_color=world.baseplate_color,
            n_buildings=world.n_buildings, n_trees=world.n_trees,
            n_flowers=world.n_flowers, n_people=world.n_people,
            n_hills=world.n_hills, n_lamps=world.n_lamps,
            n_rocks=world.n_rocks,
            payload=json.loads(world.to_json()),
        )
        row.save()
        messages.success(request, f'Built "{row.name}" (seed {seed}).')
        return redirect('legolith:detail', slug=row.slug)

    return render(request, 'legolith/generate.html', {
        'biomes': [b for b, _ in BIOME_CHOICES],
    })


@login_required
@require_POST
def world_delete(request, slug):
    world = get_object_or_404(LegoWorld, slug=slug)
    name = world.name
    world.delete()
    messages.success(request, f'Removed "{name}".')
    return redirect('legolith:list')


# ---------------------------------------------------------------------------
# PNG rendering
# ---------------------------------------------------------------------------
@login_required
def world_png(request, slug):
    """Render a LegoWorld as a PNG. ?thumb=1 uses the fast (studless) path."""
    world_row = get_object_or_404(LegoWorld, slug=slug)
    thumb = request.GET.get('thumb') == '1'
    world = world_row.to_world()

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from .brick_render import new_scene, draw_group

    if thumb:
        from .worlds_gallery import _fast_draw_group
        fig, ax = new_scene(3.6, 3.4, dpi=110)
        _fast_draw_group(ax, W.world_to_bricks(world))
    else:
        fig, ax = new_scene(7.2, 6.4, dpi=160)
        draw_group(ax, W.world_to_bricks(world))

    ax.relim(); ax.autoscale_view()
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    cw, ch = (x1 - x0) * 1.04, (y1 - y0) * 1.04
    aspect = (x1 - x0) / max(y1 - y0, 1e-6)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ax.set_xlim(cx - cw / 2, cx + cw / 2)
    ax.set_ylim(cy - ch / 2, cy + ch / 2)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', transparent=False,
                dpi=110 if thumb else 160)
    plt.close(fig)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=3600'
    return resp


# ---------------------------------------------------------------------------
# PDF streamers — all three run the generator inside a tmpdir so relative
# filenames don't pollute the project root.
# ---------------------------------------------------------------------------
def _stream_pdf_from_tmp(builder, out_name: str):
    tmp = tempfile.mkdtemp(prefix='legolith-')
    prev = os.getcwd()
    try:
        os.chdir(tmp)
        pdf_path = builder()
        if not os.path.isabs(pdf_path):
            pdf_path = os.path.join(tmp, pdf_path)
        if not os.path.exists(pdf_path):
            raise Http404(f'PDF not produced: {pdf_path}')
        resp = FileResponse(
            open(pdf_path, 'rb'),
            content_type='application/pdf',
        )
        resp['Content-Disposition'] = f'inline; filename="{out_name}"'
        return resp
    finally:
        os.chdir(prev)


@login_required
def pdf_math_book(request):
    """Random N-page math worksheet book.

    Query: ?pages=50&seed=42   (defaults: 50 pages, random seed)
    """
    try:
        n_pages = max(1, min(2000, int(request.GET.get('pages') or 50)))
    except ValueError:
        n_pages = 50
    try:
        seed = int(request.GET.get('seed') or random.randint(1, 999999))
    except ValueError:
        seed = random.randint(1, 999999)

    from . import random_worksheets as RW

    def _build():
        return RW.build(n_pages=n_pages, seed=seed)

    return _stream_pdf_from_tmp(
        _build, f'legolith-math-{n_pages}p-s{seed}.pdf')


@login_required
def pdf_worlds_gallery(request):
    """4-up gallery PDF of N freshly-rolled worlds.

    Query: ?count=500&seed_start=10001
    """
    try:
        count = max(1, min(2000, int(request.GET.get('count') or 100)))
    except ValueError:
        count = 100
    try:
        seed_start = int(request.GET.get('seed_start') or 10001)
    except ValueError:
        seed_start = 10001

    from .worlds_gallery import build_gallery

    def _build():
        pdf, _saved = build_gallery(count=count, seed_start=seed_start)
        return pdf

    return _stream_pdf_from_tmp(
        _build, f'legolith-gallery-{count}.pdf')


@login_required
def pdf_worlds_detailed(request):
    """One-per-page detailed booklet of N freshly-rolled worlds.

    Query: ?count=32&seed_start=30001
    """
    try:
        count = max(1, min(256, int(request.GET.get('count') or 16)))
    except ValueError:
        count = 16
    try:
        seed_start = int(request.GET.get('seed_start') or 30001)
    except ValueError:
        seed_start = 30001

    from .worlds_detailed import build as build_detailed

    def _build():
        pdf, _saved = build_detailed(count=count, seed_start=seed_start)
        return pdf

    return _stream_pdf_from_tmp(
        _build, f'legolith-detailed-{count}.pdf')


# ---------------------------------------------------------------------------
# Library of reusable Lego models
# ---------------------------------------------------------------------------
@login_required
def library_list(request):
    kind = (request.GET.get('kind') or '').strip()
    qs = LegoModel.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    return render(request, 'legolith/library_list.html', {
        'models': qs,
        'kinds': [k for k, _ in KIND_CHOICES],
        'current_kind': kind,
        'total': LegoModel.objects.count(),
    })


def _parse_rules_text(text: str) -> dict:
    """Parse a rules textarea: one rule per line, 'SYMBOL -> REPLACEMENT'."""
    out = {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        for sep in ('->', '=>', ':'):
            if sep in line:
                sym, repl = line.split(sep, 1)
                sym = sym.strip()
                repl = repl.strip()
                if sym:
                    out[sym] = repl
                break
    return out


def _rules_text(rules: dict) -> str:
    return '\n'.join(f'{k} -> {v}' for k, v in (rules or {}).items())


def _apply_form(model: LegoModel, post) -> list[str]:
    """Copy POST fields onto model; return list of validation errors."""
    errors = []
    model.name = (post.get('name') or '').strip()[:120]
    if not model.name:
        errors.append('Name is required.')

    model.kind = post.get('kind') or 'other'
    if model.kind not in dict(KIND_CHOICES):
        model.kind = 'other'
    model.description = (post.get('description') or '').strip()
    model.axiom = (post.get('axiom') or 'X').strip()[:200] or 'X'
    model.rules = _parse_rules_text(post.get('rules') or '')

    def _int(name, default, lo=1, hi=32):
        try:
            return max(lo, min(hi, int(post.get(name) or default)))
        except (TypeError, ValueError):
            return default

    model.iterations = _int('iterations', 2, lo=1, hi=8)
    model.init_shape_w = _int('init_shape_w', 1)
    model.init_shape_d = _int('init_shape_d', 1)
    model.init_shape_plates = _int('init_shape_plates', 3, lo=1, hi=30)
    model.footprint_w = _int('footprint_w', 2, lo=1)
    model.footprint_d = _int('footprint_d', 2, lo=1)

    color = (post.get('init_color') or '#888888').strip()
    if not color.startswith('#') or len(color) != 7:
        color = '#888888'
    model.init_color = color
    return errors


@login_required
def library_new(request):
    if request.method == 'POST':
        model = LegoModel()
        errors = _apply_form(model, request.POST)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            try:
                # Try rendering so we fail early on a broken L-System.
                L.make_from_spec(model.as_spec())
            except Exception as exc:
                messages.error(request, f'L-System render error: {exc}')
            else:
                model.save()
                messages.success(request, f'Created "{model.name}".')
                return redirect('legolith:library_detail', slug=model.slug)
        return render(request, 'legolith/library_form.html', {
            'model': model, 'kinds': [k for k, _ in KIND_CHOICES],
            'rules_text': request.POST.get('rules') or '',
            'is_new': True,
        })

    # GET: show empty form with a minimal starting spec.
    starter = LegoModel(
        name='', kind='other', axiom='X',
        rules={'X': '{C:c8a868}F[>L][<L][^L][&L]F{C:2d6b2a}L'},
        iterations=2, init_color='#c8a868',
        init_shape_w=1, init_shape_d=1, init_shape_plates=3,
        footprint_w=2, footprint_d=2,
    )
    return render(request, 'legolith/library_form.html', {
        'model': starter, 'kinds': [k for k, _ in KIND_CHOICES],
        'rules_text': _rules_text(starter.rules),
        'is_new': True,
    })


@login_required
def library_detail(request, slug):
    model = get_object_or_404(LegoModel, slug=slug)
    return render(request, 'legolith/library_detail.html', {
        'model': model,
        'rules_text': _rules_text(model.rules),
    })


@login_required
def library_edit(request, slug):
    model = get_object_or_404(LegoModel, slug=slug)
    if request.method == 'POST':
        errors = _apply_form(model, request.POST)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            try:
                L.make_from_spec(model.as_spec())
            except Exception as exc:
                messages.error(request, f'L-System render error: {exc}')
            else:
                model.save()
                messages.success(request, f'Updated "{model.name}".')
                return redirect('legolith:library_detail', slug=model.slug)
        return render(request, 'legolith/library_form.html', {
            'model': model, 'kinds': [k for k, _ in KIND_CHOICES],
            'rules_text': request.POST.get('rules') or '',
            'is_new': False,
        })

    return render(request, 'legolith/library_form.html', {
        'model': model, 'kinds': [k for k, _ in KIND_CHOICES],
        'rules_text': _rules_text(model.rules),
        'is_new': False,
    })


@login_required
@require_POST
def library_random(request):
    """Roll a random L-System model into the library, redirect to its detail."""
    model = _roll_random_model(seed=random.randint(1, 10_000_000))
    model.save()
    messages.success(request, f'Rolled "{model.name}" from random rules.')
    return redirect('legolith:library_detail', slug=model.slug)


def _roll_random_model(seed: int) -> LegoModel:
    """Build a LegoModel with random L-System rules. Render-guarded: if the
    generated spec fails to render or produces nothing, retry with a fresh
    seed until it works (bounded).
    """
    import string
    rng = random.Random(seed)

    palette = [
        '#d01712', '#3b7fa8', '#f5cd30', '#2d6b2a', '#efdca2',
        '#b4b2ad', '#6b4a2e', '#d98bb4', '#8957e5', '#ffffff',
        '#222222', '#f08020', '#5ea04b', '#c8a868',
    ]
    kinds = ['tree', 'flower', 'building', 'rock', 'lamp', 'other']
    # Turtle-friendly terminals — these are interpreted by the turtle, not
    # production symbols. Brace-tokens get emitted as atomic chunks.
    terminals_advance = ['F', 'P', 'F', 'F']      # weight F higher
    terminals_static = ['L', 'L', 'L', 'R']
    steps = ['>', '<', '^', '&']

    def _brace_color():
        return '{C:' + rng.choice(palette).lstrip('#') + '}'

    def _brace_shape():
        w = rng.randint(1, 2)
        d = rng.randint(1, 2)
        h = rng.randint(1, 4)
        return '{S:' + f'{w},{d},{h}' + '}'

    def _branch_burst():
        # [>L][<L][^L][&L] style bursts — good for leafy/flowery objects.
        n = rng.randint(2, 4)
        choices = rng.sample(steps, n)
        return ''.join(f'[{s}L]' for s in choices)

    def _random_body(allow_branches=True):
        parts = []
        length = rng.randint(4, 10)
        for _ in range(length):
            r = rng.random()
            if r < 0.25:
                parts.append(_brace_color())
            elif r < 0.35:
                parts.append(_brace_shape())
            elif r < 0.55:
                parts.append(rng.choice(terminals_advance))
            elif r < 0.70:
                parts.append(rng.choice(terminals_static))
            elif r < 0.82:
                parts.append(rng.choice(steps))
            elif allow_branches and r < 0.94:
                parts.append(_branch_burst())
            else:
                # push/pop pair around a small motif
                motif = rng.choice(terminals_advance) + rng.choice(terminals_static)
                parts.append(f'[{motif}]')
        return ''.join(parts)

    # Try up to 6 random specs until one renders with at least 3 bricks.
    for attempt in range(6):
        axiom_sym = rng.choice(string.ascii_uppercase[:6])  # A..F
        rules = {axiom_sym: _random_body()}
        # Sometimes add a secondary production for recursion.
        if rng.random() < 0.5:
            sec = rng.choice(['G', 'H', 'J'])
            rules[sec] = _random_body(allow_branches=False)
            # splice the secondary into the primary
            rules[axiom_sym] = rules[axiom_sym] + sec

        spec = {
            'axiom': axiom_sym,
            'rules': rules,
            'iterations': rng.randint(1, 3),
            'init_color': rng.choice(palette),
            'init_shape': (rng.randint(1, 2), rng.randint(1, 2),
                           rng.randint(1, 3)),
        }
        try:
            placements = L.make_from_spec(spec)
        except Exception:
            continue
        if len(placements) < 3:
            continue
        break
    else:
        # Fall back to a safe spec that always renders.
        spec = {
            'axiom': 'X',
            'rules': {'X': '{C:f5cd30}FFL[>L][<L][^L][&L]'},
            'iterations': 2,
            'init_color': '#f5cd30',
            'init_shape': (1, 1, 3),
        }
        placements = L.make_from_spec(spec)

    # Pick a plausible footprint from where bricks actually landed.
    xs = [x for (_, (x, _, _)) in placements]
    ys = [y for (_, (_, y, _)) in placements]
    fp_w = max(1, min(8, (max(xs) - min(xs)) + 2)) if xs else 2
    fp_d = max(1, min(8, (max(ys) - min(ys)) + 2)) if ys else 2

    kind = rng.choice(kinds)
    adj = rng.choice(['Twisted', 'Gleaming', 'Sprouting', 'Stacked',
                      'Whispering', 'Jumbled', 'Pixelated', 'Rambling',
                      'Tiny', 'Lumbering', 'Lopsided'])
    noun = rng.choice(['Spire', 'Bramble', 'Totem', 'Sprig', 'Monolith',
                       'Clump', 'Thicket', 'Ziggurat', 'Nodule', 'Sculpture'])
    name = f'{adj} {noun} #{seed % 10000:04d}'

    return LegoModel(
        name=name, kind=kind,
        description=f'Random L-System model (seed {seed}).',
        axiom=spec['axiom'],
        rules=spec['rules'],
        iterations=spec['iterations'],
        init_color=spec['init_color'],
        init_shape_w=spec['init_shape'][0],
        init_shape_d=spec['init_shape'][1],
        init_shape_plates=spec['init_shape'][2],
        footprint_w=fp_w, footprint_d=fp_d,
    )


@login_required
@require_POST
def library_delete(request, slug):
    model = get_object_or_404(LegoModel, slug=slug)
    name = model.name
    model.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('legolith:library_list')


@login_required
def library_preview_png(request, slug):
    """Single-model render: draws the model on a tiny baseplate."""
    model = get_object_or_404(LegoModel, slug=slug)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    size = max(model.footprint_w, model.footprint_d, 4) + 2
    placements = [(
        Brick(size, size, 1, '#5ea04b'),
        (0, 0, -PLATE_H),
    )]
    try:
        origin = ((size - model.footprint_w) // 2,
                  (size - model.footprint_d) // 2, 0.0)
        placements.extend(L.make_from_spec(model.as_spec(), origin=origin))
    except Exception as exc:
        # Surface the error as a text PNG so the UI stays informative.
        fig, ax = plt.subplots(figsize=(4, 2))
        ax.text(0.5, 0.5, f'render error:\n{exc}', ha='center', va='center',
                fontsize=9, family='monospace')
        ax.axis('off')
    else:
        fig, ax = new_scene(4.2, 3.8, dpi=130)
        draw_group(ax, placements)
        ax.relim(); ax.autoscale_view()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=600'
    return resp


def library_bricks_json(request, slug):
    """Flattened brick payload in the Aether Legoworld format.

    Each brick is [w, d, plates, color, x, y, z, studs]. Consumers (e.g. the
    Aether legoworld-render script) can place this payload directly without
    knowing anything about the underlying L-System.
    """
    model = get_object_or_404(LegoModel, slug=slug)
    try:
        placements = L.make_from_spec(model.as_spec())
    except Exception as exc:
        return HttpResponse(f'render error: {exc}', status=500,
                            content_type='text/plain')
    bricks = []
    for b, (x, y, z) in placements:
        bricks.append([
            int(b.w), int(b.d), int(b.plates), b.color,
            float(x), float(y), float(z), 1 if b.studs else 0,
        ])
    return HttpResponse(
        json.dumps({
            'slug': model.slug, 'name': model.name, 'kind': model.kind,
            'footprint': [model.footprint_w, model.footprint_d],
            'bricks': bricks,
        }),
        content_type='application/json',
    )

"""Umbra views — phase 1 catalogue + experiment authoring.

No real ciphertext computation here yet; experiments save their code
as text.  When phase 2 lands, an execution runner will pipe the code
through a Pyfhel / Concrete subprocess and write back to
last_output / last_error / last_run_ms.
"""
import json

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from . import csvlab, corpuslab
from .csvlab import OP_CHOICES
from .corpuslab import (
    OP_CHOICES as CORPUS_OP_CHOICES,
    CLASS_CHOICES as CORPUS_CLASS_CHOICES,
    MAX_CELLS as CORPUS_MAX_CELLS,
    MAX_CELL_LEN as CORPUS_MAX_CELL_LEN,
)
from .models import Scheme, Reference, Experiment, CsvLabSession, CorpusLabSession
from .runner import run_experiment


SAMPLE_CODE = """\
# TenSEAL CKKS — element-wise multiply + encrypted dot product.
import tenseal as ts

ctx = ts.context(
    ts.SCHEME_TYPE.CKKS,
    poly_modulus_degree=8192,
    coeff_mod_bit_sizes=[60, 40, 40, 60],
)
ctx.global_scale = 2 ** 40
ctx.generate_galois_keys()

a = ts.ckks_vector(ctx, [1.0, 2.0, 3.0, 4.0])
b = ts.ckks_vector(ctx, [10.0, 20.0, 30.0, 40.0])

c = a * b                                # element-wise ciphertext multiply
print('a * b =', [round(x, 4) for x in c.decrypt()])

d = a.dot(b)                             # encrypted dot product
print('a . b =', round(d.decrypt()[0], 4))   # -> 300.0
"""


def _ctx():
    return {
        'app_name':   'Umbra',
        'app_tag':    'FHE workbench',
        'scheme_count':     Scheme.objects.count(),
        'reference_count':  Reference.objects.count(),
        'experiment_count': Experiment.objects.count(),
        'csvlab_count':     CsvLabSession.objects.count(),
        'corpuslab_count':  CorpusLabSession.objects.count(),
    }


def index(request):
    schemes  = Scheme.objects.all()
    libs     = Reference.objects.filter(kind=Reference.KIND_LIBRARY)[:8]
    awesome  = Reference.objects.filter(kind=Reference.KIND_AWESOME)
    recent   = Experiment.objects.all()[:5]
    ctx = _ctx()
    ctx.update(schemes=schemes, libs=libs, awesome=awesome, recent=recent)
    return render(request, 'umbra/index.html', ctx)


def scheme_list(request):
    schemes = Scheme.objects.all()
    ctx = _ctx(); ctx['schemes'] = schemes
    return render(request, 'umbra/schemes.html', ctx)


def scheme_detail(request, slug):
    scheme = get_object_or_404(Scheme, slug=slug)
    refs   = scheme.references.all()
    expts  = scheme.experiments.all()
    ctx = _ctx(); ctx.update(scheme=scheme, refs=refs, expts=expts)
    return render(request, 'umbra/scheme_detail.html', ctx)


def reference_list(request):
    by_kind = {}
    for r in Reference.objects.all():
        by_kind.setdefault(r.get_kind_display(), []).append(r)
    ordered = sorted(by_kind.items())
    ctx = _ctx(); ctx['ref_groups'] = ordered
    return render(request, 'umbra/references.html', ctx)


def experiment_list(request):
    expts = Experiment.objects.all()
    ctx = _ctx(); ctx['expts'] = expts
    return render(request, 'umbra/experiments.html', ctx)


def experiment_create(request):
    if request.method == 'POST':
        name        = (request.POST.get('name') or '').strip()
        scheme_slug = request.POST.get('scheme') or ''
        description = request.POST.get('description') or ''
        code        = request.POST.get('code') or SAMPLE_CODE
        if not name:
            messages.error(request, 'A name is required.')
            return redirect('umbra:experiment_create')
        scheme = None
        if scheme_slug:
            scheme = Scheme.objects.filter(slug=scheme_slug).first()
        e = Experiment.objects.create(
            name=name, scheme=scheme, description=description,
            code=code, status=Experiment.STATUS_SAVED,
        )
        messages.success(request, f'Saved experiment "{e.name}".')
        return redirect('umbra:experiment_detail', slug=e.slug)
    ctx = _ctx()
    ctx.update(schemes=Scheme.objects.all(), sample_code=SAMPLE_CODE)
    return render(request, 'umbra/experiment_form.html', ctx)


def experiment_detail(request, slug):
    e = get_object_or_404(Experiment, slug=slug)
    ctx = _ctx(); ctx['expt'] = e
    return render(request, 'umbra/experiment_detail.html', ctx)


def experiment_run(request, slug):
    if request.method != 'POST':
        return redirect('umbra:experiment_detail', slug=slug)
    e = get_object_or_404(Experiment, slug=slug)
    run_experiment(e)
    if e.status == Experiment.STATUS_DONE:
        messages.success(request, f'Ran "{e.name}" in {e.last_run_ms} ms.')
    else:
        messages.error(request, f'Run failed after {e.last_run_ms} ms.')
    return redirect('umbra:experiment_detail', slug=e.slug)


def experiment_edit(request, slug):
    e = get_object_or_404(Experiment, slug=slug)
    if request.method == 'POST':
        e.name        = (request.POST.get('name') or e.name).strip() or e.name
        scheme_slug   = request.POST.get('scheme') or ''
        e.scheme      = Scheme.objects.filter(slug=scheme_slug).first() if scheme_slug else None
        e.description = request.POST.get('description') or e.description
        e.code        = request.POST.get('code') or e.code
        e.status      = Experiment.STATUS_SAVED
        e.save()
        messages.success(request, 'Saved.')
        return redirect('umbra:experiment_detail', slug=e.slug)
    ctx = _ctx()
    ctx.update(expt=e, schemes=Scheme.objects.all(), edit_mode=True,
               sample_code=e.code or SAMPLE_CODE)
    return render(request, 'umbra/experiment_form.html', ctx)


SAMPLE_CSV = """name,score,bonus
Alice,10,1
Bob,7,2
Carol,3,0
"""


def csvlab_index(request):
    sessions = CsvLabSession.objects.all()[:20]
    ctx = _ctx(); ctx.update(sessions=sessions, sample_csv=SAMPLE_CSV,
                             max_numeric_cells=csvlab.MAX_NUMERIC_CELLS)
    return render(request, 'umbra/csvlab_index.html', ctx)


def csvlab_upload(request):
    if request.method != 'POST':
        return redirect('umbra:csvlab')
    name = (request.POST.get('name') or '').strip()
    csv_text = ''
    uploaded = request.FILES.get('file')
    if uploaded:
        try:
            csv_text = uploaded.read().decode('utf-8', errors='replace')
        except Exception as exc:
            messages.error(request, f'Could not read file: {exc!r}')
            return redirect('umbra:csvlab')
        if not name:
            name = uploaded.name
    else:
        csv_text = request.POST.get('csv_text') or ''
        if not name:
            name = 'pasted'
    csv_text = csv_text.strip()
    if not csv_text:
        messages.error(request, 'No CSV content provided.')
        return redirect('umbra:csvlab')
    grid, rows, cols = csvlab.parse_csv(csv_text)
    n_numeric = csvlab.count_numeric_cells(grid)
    if n_numeric > csvlab.MAX_NUMERIC_CELLS:
        messages.error(request,
            f'CSV has {n_numeric} numeric cells ({rows}×{cols} grid). '
            f'Cap is {csvlab.MAX_NUMERIC_CELLS} — each numeric cell '
            f'becomes its own ~330 KB CKKS ciphertext and takes ~7 ms '
            f'to encrypt, so larger inputs hang the request. Trim and '
            f'try again.')
        return redirect('umbra:csvlab')
    s = CsvLabSession.objects.create(name=name, original_csv=csv_text,
                                     ops_json='[]')
    return redirect('umbra:csvlab_session', slug=s.slug)


def csvlab_session(request, slug):
    s = get_object_or_404(CsvLabSession, slug=slug)
    grid, _, _ = csvlab.parse_csv(s.original_csv)
    try:
        ops = json.loads(s.ops_json or '[]')
    except Exception:
        ops = []
    # Pair the result_grid with a parallel mask of "(value, changed_bool)"
    # tuples so the template can highlight cells whose text differs from
    # the same coordinate in the original input.  For sort ops this lights
    # up every cell in every reordered row — exactly the visual cue that
    # makes a sort visible.
    result_grid_diff = []
    changed_cells = 0
    total_cells = 0
    if s.result_csv:
        result_grid, _, _ = csvlab.parse_csv(s.result_csv)
        for r, row in enumerate(result_grid):
            drow = []
            for c, val in enumerate(row):
                orig = grid[r][c] if r < len(grid) and c < len(grid[r]) else ''
                changed = (val != orig)
                if changed:
                    changed_cells += 1
                total_cells += 1
                drow.append((val, changed))
            result_grid_diff.append(drow)
    ctx = _ctx()
    ctx.update(session=s, grid=grid, ops=ops,
               result_grid_diff=result_grid_diff,
               changed_cells=changed_cells, total_cells=total_cells,
               op_choices=OP_CHOICES)
    return render(request, 'umbra/csvlab_session.html', ctx)


def _parse_op_form(post):
    """Build a single op dict from the form, or None if no op selected."""
    kind = post.get('op_kind') or ''
    if not kind:
        return None
    if kind == csvlab.OP_ADD_CONST or kind == csvlab.OP_MUL_CONST:
        return {
            'op':    kind,
            'row':   int(post.get('row') or 0),
            'col':   int(post.get('col') or 0),
            'value': float(post.get('value') or 0),
        }
    if kind == csvlab.OP_SUM_CELLS:
        return {
            'op':  kind,
            'a':   [int(post.get('a_row') or 0), int(post.get('a_col') or 0)],
            'b':   [int(post.get('b_row') or 0), int(post.get('b_col') or 0)],
            'dst': [int(post.get('dst_row') or 0), int(post.get('dst_col') or 0)],
        }
    if kind == csvlab.OP_COL_TOTAL:
        return {
            'op':  kind,
            'col': int(post.get('col') or 0),
            'dst': [int(post.get('dst_row') or 0), int(post.get('dst_col') or 0)],
            'skip_header': bool(post.get('skip_header')),
        }
    if kind == csvlab.OP_SORT_COL:
        return {
            'op':    kind,
            'col':   int(post.get('col') or 0),
            'order': (post.get('order') or 'asc').lower(),
            'skip_header': bool(post.get('skip_header')),
        }
    return None


def csvlab_add_op(request, slug):
    s = get_object_or_404(CsvLabSession, slug=slug)
    if request.method != 'POST':
        return redirect('umbra:csvlab_session', slug=slug)
    try:
        ops = json.loads(s.ops_json or '[]')
    except Exception:
        ops = []
    try:
        new_op = _parse_op_form(request.POST)
    except (TypeError, ValueError) as exc:
        messages.error(request, f'Bad op fields: {exc!r}')
        return redirect('umbra:csvlab_session', slug=slug)
    if new_op is None:
        messages.error(request, 'No op kind selected.')
        return redirect('umbra:csvlab_session', slug=slug)
    ops.append(new_op)
    s.ops_json = json.dumps(ops)
    s.save(update_fields=['ops_json', 'updated_at'])
    messages.success(request, f'Queued {new_op["op"]}.')
    return redirect('umbra:csvlab_session', slug=slug)


def csvlab_clear_ops(request, slug):
    s = get_object_or_404(CsvLabSession, slug=slug)
    if request.method != 'POST':
        return redirect('umbra:csvlab_session', slug=slug)
    s.ops_json   = '[]'
    s.result_csv = ''
    s.last_error = ''
    s.save(update_fields=['ops_json', 'result_csv', 'last_error', 'updated_at'])
    messages.success(request, 'Ops cleared.')
    return redirect('umbra:csvlab_session', slug=slug)


def csvlab_run(request, slug):
    s = get_object_or_404(CsvLabSession, slug=slug)
    if request.method != 'POST':
        return redirect('umbra:csvlab_session', slug=slug)
    csvlab.run_session(s)
    s.save()
    if s.last_error:
        messages.warning(request,
            f'Ran with {len(s.last_error.splitlines())} op error(s).')
    else:
        messages.success(request,
            f'Ran in {s.encrypt_ms + s.ops_ms + s.decrypt_ms} ms '
            f'({s.numeric_cells} cells, '
            f'{s.ciphertext_bytes // 1024} KB ciphertext).')
    return redirect('umbra:csvlab_session', slug=slug)


def csvlab_download(request, slug):
    s = get_object_or_404(CsvLabSession, slug=slug)
    if not s.result_csv:
        messages.error(request, 'No result yet — run the session first.')
        return redirect('umbra:csvlab_session', slug=slug)
    fname = slugify(s.name) or s.slug
    resp = HttpResponse(s.result_csv, content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{fname}.result.csv"'
    return resp


# ── Corpus Lab — TFHE sealed linguistic ops ─────────────────────────
# Linguistic CSVs (one form per cell), sealed under Concrete TFHE so
# per-cell character analyses run without the operator seeing the bytes.
# This is the Leiden humanities/area-studies/low-resource-language path.

SAMPLE_CORPUS_CSV = """form,gloss,language
guru,teacher,Sanskrit
shishya,student,Sanskrit
namaste,greetings,Hindi
panee,water,Hindi
ela,cow,Konso
heera,star,Konso
"""


def corpuslab_index(request):
    sessions = CorpusLabSession.objects.all()[:20]
    ctx = _ctx(); ctx.update(
        sessions=sessions,
        sample_csv=SAMPLE_CORPUS_CSV,
        max_cells=CORPUS_MAX_CELLS,
        max_cell_len=CORPUS_MAX_CELL_LEN,
    )
    return render(request, 'umbra/corpuslab_index.html', ctx)


def corpuslab_upload(request):
    if request.method != 'POST':
        return redirect('umbra:corpuslab')
    name = (request.POST.get('name') or '').strip()
    csv_text = ''
    uploaded = request.FILES.get('file')
    if uploaded:
        try:
            csv_text = uploaded.read().decode('utf-8', errors='replace')
        except Exception as exc:
            messages.error(request, f'Could not read file: {exc!r}')
            return redirect('umbra:corpuslab')
        if not name:
            name = uploaded.name
    else:
        csv_text = request.POST.get('csv_text') or ''
        if not name:
            name = 'pasted'
    csv_text = csv_text.strip()
    if not csv_text:
        messages.error(request, 'No CSV content provided.')
        return redirect('umbra:corpuslab')
    grid, rows, cols = corpuslab.parse_csv(csv_text)
    if rows <= 1:
        messages.error(request, 'CSV needs a header row plus data rows.')
        return redirect('umbra:corpuslab')
    s = CorpusLabSession.objects.create(name=name, original_csv=csv_text,
                                        ops_json='[]')
    return redirect('umbra:corpuslab_session', slug=s.slug)


def corpuslab_session(request, slug):
    s = get_object_or_404(CorpusLabSession, slug=slug)
    grid, _, _ = corpuslab.parse_csv(s.original_csv)
    try:
        ops = json.loads(s.ops_json or '[]')
    except Exception:
        ops = []
    result_grid_diff = []
    changed_cells = 0
    total_cells = 0
    if s.result_csv:
        result_grid, _, _ = corpuslab.parse_csv(s.result_csv)
        for r, row in enumerate(result_grid):
            drow = []
            for c, val in enumerate(row):
                orig = grid[r][c] if r < len(grid) and c < len(grid[r]) else ''
                changed = (val != orig)
                if changed:
                    changed_cells += 1
                total_cells += 1
                drow.append((val, changed))
            result_grid_diff.append(drow)
    ctx = _ctx()
    ctx.update(session=s, grid=grid, ops=ops,
               result_grid_diff=result_grid_diff,
               changed_cells=changed_cells, total_cells=total_cells,
               op_choices=CORPUS_OP_CHOICES,
               class_choices=CORPUS_CLASS_CHOICES,
               max_cells=CORPUS_MAX_CELLS,
               max_cell_len=CORPUS_MAX_CELL_LEN)
    return render(request, 'umbra/corpuslab_session.html', ctx)


def _parse_corpus_op_form(post):
    kind = post.get('op_kind') or ''
    if not kind:
        return None
    if kind == corpuslab.OP_CHAR_CLASS_MAP:
        return {'op': kind, 'col': int(post.get('col') or 0)}
    if kind == corpuslab.OP_COUNT_CLASS:
        dst = post.get('dst_col')
        return {
            'op':     kind,
            'col':    int(post.get('col') or 0),
            'target': int(post.get('target') or corpuslab.CLASS_VOWEL),
            'dst_col': int(dst) if (dst not in (None, '', 'null')) else None,
        }
    if kind == corpuslab.OP_LENGTH:
        dst = post.get('dst_col')
        return {
            'op':     kind,
            'col':    int(post.get('col') or 0),
            'dst_col': int(dst) if (dst not in (None, '', 'null')) else None,
        }
    return None


def corpuslab_add_op(request, slug):
    s = get_object_or_404(CorpusLabSession, slug=slug)
    if request.method != 'POST':
        return redirect('umbra:corpuslab_session', slug=slug)
    try:
        ops = json.loads(s.ops_json or '[]')
    except Exception:
        ops = []
    try:
        new_op = _parse_corpus_op_form(request.POST)
    except (TypeError, ValueError) as exc:
        messages.error(request, f'Bad op fields: {exc!r}')
        return redirect('umbra:corpuslab_session', slug=slug)
    if new_op is None:
        messages.error(request, 'No op kind selected.')
        return redirect('umbra:corpuslab_session', slug=slug)
    ops.append(new_op)
    s.ops_json = json.dumps(ops)
    s.save(update_fields=['ops_json', 'updated_at'])
    messages.success(request, f'Queued {new_op["op"]}.')
    return redirect('umbra:corpuslab_session', slug=slug)


def corpuslab_clear_ops(request, slug):
    s = get_object_or_404(CorpusLabSession, slug=slug)
    if request.method != 'POST':
        return redirect('umbra:corpuslab_session', slug=slug)
    s.ops_json   = '[]'
    s.result_csv = ''
    s.last_error = ''
    s.save(update_fields=['ops_json', 'result_csv', 'last_error', 'updated_at'])
    messages.success(request, 'Ops cleared.')
    return redirect('umbra:corpuslab_session', slug=slug)


def corpuslab_run(request, slug):
    s = get_object_or_404(CorpusLabSession, slug=slug)
    if request.method != 'POST':
        return redirect('umbra:corpuslab_session', slug=slug)
    corpuslab.run_session(s)
    s.save()
    if s.last_error:
        messages.warning(request,
            f'Ran with {len(s.last_error.splitlines())} op error(s).')
    else:
        messages.success(request,
            f'Ran in {s.compile_ms + s.ops_ms} ms '
            f'({s.cells} cells, {s.chars_total} encrypted bytes).')
    return redirect('umbra:corpuslab_session', slug=slug)


def corpuslab_download(request, slug):
    s = get_object_or_404(CorpusLabSession, slug=slug)
    if not s.result_csv:
        messages.error(request, 'No result yet — run the session first.')
        return redirect('umbra:corpuslab_session', slug=slug)
    fname = slugify(s.name) or s.slug
    resp = HttpResponse(s.result_csv, content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{fname}.result.csv"'
    return resp

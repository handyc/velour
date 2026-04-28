"""Ledger views — workbook list / sheet view / single-cell update API."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .engine import build_sheet_context, evaluate_cell
from .forms import NewWorkbookForm
from .models import Cell, FormulaLanguage, Sheet, Workbook, col_to_letter


@login_required
def list_view(request):
    workbooks = Workbook.objects.all()
    return render(request, 'ledger/list.html', {'workbooks': workbooks})


@login_required
def new(request):
    if request.method == 'POST':
        form = NewWorkbookForm(request.POST)
        if form.is_valid():
            wb = form.save(commit=False)
            wb.owner = request.user
            wb.formula_language = FormulaLanguage.objects.filter(slug='excel').first()
            wb.save()
            Sheet.objects.create(workbook=wb, name='Sheet1', order=0)
            messages.success(request, f'Created "{wb.title}".')
            return redirect('ledger:detail', slug=wb.slug)
    else:
        form = NewWorkbookForm()
    return render(request, 'ledger/new.html', {'form': form})


@login_required
def detail(request, slug):
    wb = get_object_or_404(Workbook, slug=slug)
    sheet = wb.sheets.first()
    if sheet is None:
        sheet = Sheet.objects.create(workbook=wb, name='Sheet1', order=0)
    grid = sheet.cells_as_grid()
    rows = []
    for r in range(sheet.rows):
        cols = []
        for c in range(sheet.cols):
            cell = grid.get((r, c))
            cols.append({
                'a1': col_to_letter(c) + str(r + 1),
                'row': r, 'col': c,
                'value': cell.value if cell else '',
                'computed': cell.computed_value if cell else '',
                'is_formula': bool(cell and cell.is_formula()),
            })
        rows.append({'r': r, 'cells': cols})
    col_letters = [col_to_letter(c) for c in range(sheet.cols)]
    return render(request, 'ledger/detail.html', {
        'workbook': wb,
        'sheet': sheet,
        'rows': rows,
        'col_letters': col_letters,
    })


@login_required
@require_POST
def delete(request, slug):
    wb = get_object_or_404(Workbook, slug=slug)
    title = wb.title
    wb.delete()
    messages.success(request, f'Deleted "{title}".')
    return redirect('ledger:list')


@login_required
@require_POST
def api_set_cell(request, slug, sheet_pk):
    """Update one cell's value, recompute its formula (if any), and
    return the new computed value. Phase 1 recomputes only the touched
    cell — dependent-cell propagation is Phase 2."""
    wb = get_object_or_404(Workbook, slug=slug)
    sheet = get_object_or_404(Sheet, pk=sheet_pk, workbook=wb)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'invalid json'}, status=400)

    try:
        row = int(payload['row'])
        col = int(payload['col'])
        value = str(payload.get('value', ''))
    except (KeyError, ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'row/col required'}, status=400)

    cell, _ = Cell.objects.get_or_create(sheet=sheet, row=row, col=col)
    cell.value = value
    cell.formula = value[1:].strip() if value.startswith('=') else ''
    cell.computed_value = ''
    error = None
    if cell.is_formula():
        ctx = build_sheet_context(sheet)
        # Strip the cell's own A1 from the context so it doesn't see its
        # stale prior value when self-referencing (we'll catch real
        # cycles in Phase 2).
        ctx.pop(cell.a1, None)
        lang_slug = (wb.formula_language.slug if wb.formula_language else 'excel')
        result, error = evaluate_cell(cell.formula, ctx, language_slug=lang_slug)
        cell.computed_value = '' if result is None else str(result)
    cell.save()
    # Save() bumps Workbook.updated_at indirectly — touch it too.
    wb.save(update_fields=['updated_at'])

    return JsonResponse({
        'ok': error is None,
        'a1': cell.a1,
        'value': cell.value,
        'computed': cell.computed_value,
        'error': error,
    })

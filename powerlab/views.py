import base64
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Circuit, Part, PartPriceSnapshot


def _render_diagram(circuit):
    """Render circuit.diagram_source via codex Kroki helper. Returns
    base64 PNG string or None."""
    if not circuit.diagram_kind or not circuit.diagram_source:
        return None
    try:
        from codex.rendering.diagrams import render_diagram_to_png
        png = render_diagram_to_png(
            circuit.diagram_source, kind=circuit.diagram_kind,
        )
    except Exception:
        return None
    if not png:
        return None
    return base64.b64encode(png).decode('ascii')


def index(request):
    circuits = list(Circuit.objects.all())
    parts_count = Part.objects.count()
    priced_count = Part.objects.exclude(
        est_unit_price_usd__isnull=True
    ).count()
    return render(request, 'powerlab/index.html', {
        'circuits':     circuits,
        'parts_count':  parts_count,
        'priced_count': priced_count,
    })


def detail(request, slug):
    circuit = get_object_or_404(Circuit, slug=slug)
    bom = list(circuit.bom.select_related('part').all())
    return render(request, 'powerlab/circuit_detail.html', {
        'circuit':      circuit,
        'bom':          bom,
        'diagram_b64':  _render_diagram(circuit),
    })


def compare(request, slug):
    """Per-vendor BOM comparison: rows = BOM lines, columns = vendors.

    Relevant when purchasing is restricted to one supplier (Conrad for
    university orders) and we need to know the delta vs. Mouser /
    AliExpress at a glance."""
    from powerlab import sources as psources

    circuit = get_object_or_404(Circuit, slug=slug)
    bom = list(circuit.bom.select_related('part').all())

    # Collect the union of vendors seen on any BOM part, plus every
    # registered source — so columns stay stable even if a part has no
    # snapshot from (say) Conrad yet.
    seen = set()
    per_line_prices = []   # list of {vendor: Decimal unit_price}
    for line in bom:
        prices = line.part.avg_price_by_vendor()
        per_line_prices.append(prices)
        seen.update(prices.keys())
    for s in psources.SOURCES:
        seen.add(s['vendor_label'])

    # Preferred column order: registered sources first in registration
    # order, then anything else alphabetically. Keeps Mouser/Conrad/
    # AliExpress on the left, rando manual vendor names on the right.
    registered = [s['vendor_label'] for s in psources.SOURCES]
    trailing = sorted(v for v in seen if v not in registered)
    vendors = [v for v in registered if v in seen] + trailing

    rows = []
    vendor_totals = {v: Decimal('0') for v in vendors}
    vendor_missing = {v: 0 for v in vendors}
    cheapest_total = Decimal('0')
    cheapest_missing = 0

    for line, prices in zip(bom, per_line_prices):
        cells = []
        available = [(v, prices[v]) for v in vendors if v in prices]
        cheapest = min((p for _, p in available), default=None)
        for v in vendors:
            unit = prices.get(v)
            if unit is None:
                cells.append({'unit': None, 'line': None, 'is_min': False})
                vendor_missing[v] += 1
                continue
            line_total = (unit * line.qty).quantize(Decimal('0.01'))
            vendor_totals[v] += line_total
            cells.append({
                'unit':   unit,
                'line':   line_total,
                'is_min': (cheapest is not None and unit == cheapest),
            })
        if cheapest is not None:
            cheapest_total += (cheapest * line.qty).quantize(Decimal('0.01'))
        else:
            cheapest_missing += 1
        rows.append({'line': line, 'cells': cells})

    vendor_columns = [
        {
            'name':    v,
            'total':   vendor_totals[v].quantize(Decimal('0.01')),
            'missing': vendor_missing[v],
            'partial': vendor_missing[v] > 0,
        }
        for v in vendors
    ]

    return render(request, 'powerlab/circuit_compare.html', {
        'circuit':          circuit,
        'vendors':          vendors,
        'vendor_columns':   vendor_columns,
        'rows':             rows,
        'cheapest_total':   cheapest_total.quantize(Decimal('0.01')),
        'cheapest_missing': cheapest_missing,
        'bom_count':        len(bom),
    })


def parts(request):
    all_parts = list(Part.objects.all())
    return render(request, 'powerlab/parts.html', {'parts': all_parts})


def part_detail(request, slug):
    part = get_object_or_404(Part, slug=slug)
    snapshots = list(part.price_snapshots.all())
    uses = list(part.circuit_uses.select_related('circuit').all())

    # Build a tiny sparkline polyline of unit_price_usd over observed_at,
    # oldest → newest so the line reads left-to-right.
    spark = None
    if len(snapshots) >= 2:
        chrono = sorted(snapshots, key=lambda s: s.observed_at)
        prices = [float(s.unit_price_usd) for s in chrono]
        lo, hi = min(prices), max(prices)
        span = (hi - lo) or 1.0
        W, H = 180, 32
        n = len(prices)
        pts = []
        for i, p in enumerate(prices):
            x = (i / (n - 1)) * (W - 2) + 1
            y = H - 2 - ((p - lo) / span) * (H - 4)
            pts.append(f"{x:.1f},{y:.1f}")
        spark = {
            'w':     W,
            'h':     H,
            'points': ' '.join(pts),
            'first': prices[0],
            'last':  prices[-1],
            'min':   lo,
            'max':   hi,
        }

    return render(request, 'powerlab/part_detail.html', {
        'part':      part,
        'snapshots': snapshots,
        'uses':      uses,
        'spark':     spark,
    })


@login_required
@require_POST
def part_record_price(request, slug):
    """Record a manual price snapshot from the part_detail form, then
    recompute the rolling-average price."""
    part = get_object_or_404(Part, slug=slug)
    vendor = (request.POST.get('vendor') or '').strip()[:100]
    src    = (request.POST.get('source_url') or '').strip()[:500]

    try:
        unit_price = Decimal(request.POST.get('unit_price_usd') or '')
    except (InvalidOperation, TypeError):
        messages.error(request, 'unit price must be a number')
        return redirect('powerlab:part_detail', slug=part.slug)

    if unit_price <= 0:
        messages.error(request, 'unit price must be positive')
        return redirect('powerlab:part_detail', slug=part.slug)
    if not vendor:
        messages.error(request, 'vendor required')
        return redirect('powerlab:part_detail', slug=part.slug)

    try:
        qty_break = int(request.POST.get('qty_break') or '1')
    except ValueError:
        qty_break = 1
    if qty_break < 1:
        qty_break = 1

    PartPriceSnapshot.objects.create(
        part=part, vendor=vendor, unit_price_usd=unit_price,
        qty_break=qty_break, source_url=src,
    )
    part.recompute_avg_price()
    messages.success(request, f'recorded {vendor} @ ${unit_price}')
    return redirect('powerlab:part_detail', slug=part.slug)

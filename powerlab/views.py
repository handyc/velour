import base64

from django.shortcuts import get_object_or_404, render

from .models import Circuit, Part


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


def parts(request):
    all_parts = list(Part.objects.all())
    return render(request, 'powerlab/parts.html', {'parts': all_parts})


def part_detail(request, slug):
    part = get_object_or_404(Part, slug=slug)
    snapshots = list(part.price_snapshots.all())
    uses = list(part.circuit_uses.select_related('circuit').all())
    return render(request, 'powerlab/part_detail.html', {
        'part':      part,
        'snapshots': snapshots,
        'uses':      uses,
    })

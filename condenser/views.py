from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Distillation


@login_required
def condenser_home(request):
    distillations = Distillation.objects.all()[:20]
    return render(request, 'condenser/home.html', {
        'distillations': distillations,
    })


@login_required
@require_POST
def distill_tiles(request):
    """Run the Tiles → JS distillation and save the result."""
    from .distill_tiles import distill

    d = Distillation(
        name='Tiles → JS (browser)',
        source_app='tiles',
        source_tier='django',
        target_tier='js',
        status='running',
    )
    d.save()

    try:
        output = distill()
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        messages.success(request,
            f'Distilled Tiles → JS: {d.output_size_bytes} bytes.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')

    return redirect('condenser:home')


@login_required
@require_POST
def distill_velour(request):
    """Run the Velour → JS self-distillation."""
    from .distill_velour import distill

    d = Distillation(
        name='Velour → JS (self-distillation)',
        source_app='velour',
        source_tier='django',
        target_tier='js',
        status='running',
    )
    d.save()

    try:
        output = distill()
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        messages.success(request,
            f'Distilled Velour → JS: {d.output_size_bytes} bytes.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')

    return redirect('condenser:home')


@login_required
def distillation_view(request, slug):
    """View a distillation's output."""
    d = get_object_or_404(Distillation, slug=slug)
    return render(request, 'condenser/detail.html', {'d': d})


@login_required
def distillation_raw(request, slug):
    """Serve the raw distilled output as HTML (for preview in iframe)."""
    d = get_object_or_404(Distillation, slug=slug)
    return HttpResponse(d.output, content_type='text/html; charset=utf-8')


@login_required
def distillation_download(request, slug):
    """Download the distilled output as a file."""
    d = get_object_or_404(Distillation, slug=slug)
    ext = {'js': 'html', 'esp': 'html', 'attiny': 'c', 'circuit': 'txt'}.get(d.target_tier, 'txt')
    resp = HttpResponse(d.output, content_type='application/octet-stream')
    resp['Content-Disposition'] = f'attachment; filename="{d.slug}.{ext}"'
    return resp


def _extract_annotations(html):
    """Pull CONDENSER comments from the output."""
    lines = []
    for line in html.split('\n'):
        stripped = line.strip()
        if 'CONDENSER:' in stripped:
            # Extract just the condenser text
            idx = stripped.index('CONDENSER:')
            text = stripped[idx + 10:].rstrip(' ->').rstrip(' */')
            lines.append(text.strip())
    return '\n'.join(lines)

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
        _record_insight(d)
        messages.success(request, f'Distilled Tiles → JS: {d.output_size_bytes} bytes.')
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
        
        _record_insight(d)
        messages.success(request, f'Distilled Velour → JS: {d.output_size_bytes} bytes.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')

    return redirect('condenser:home')


@login_required
@require_POST
def distill_tiles_esp(request):
    """Tiles JS → ESP8266 distillation."""
    from .distill_esp import distill as esp_distill
    from .distill_tiles import distill as tiles_distill

    # First get the Tier 2 output
    tier2 = tiles_distill()

    d = Distillation(
        name='Tiles → ESP8266 (Tier 2→3)',
        source_app='tiles', source_tier='js', target_tier='esp',
        status='running',
    )
    d.save()
    try:
        output = esp_distill(tier2)
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        
        _record_insight(d)
        messages.success(request, f'Distilled Tiles → ESP: {d.output_size_bytes} bytes.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')
    return redirect('condenser:home')


@login_required
@require_POST
def distill_tiles_attiny(request):
    """Tiles → ATTiny13a distillation."""
    from .distill_attiny import distill as attiny_distill

    d = Distillation(
        name='Tiles → ATTiny13a (Tier 3→4)',
        source_app='tiles', source_tier='esp', target_tier='attiny',
        status='running',
    )
    d.save()
    try:
        output = attiny_distill()
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        
        _record_insight(d)
        messages.success(request, f'Distilled Tiles → ATTiny: {d.output_size_bytes} bytes.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')
    return redirect('condenser:home')


@login_required
@require_POST
def distill_tiles_circuit(request):
    """Tiles → 555 timer circuit distillation."""
    from .distill_circuit import distill as circuit_distill

    d = Distillation(
        name='Tiles → 555 circuit (Tier 4→5)',
        source_app='tiles', source_tier='attiny', target_tier='circuit',
        status='running',
    )
    d.save()
    try:
        output = circuit_distill()
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        
        _record_insight(d)
        messages.success(request, f'Distilled Tiles → 555: {d.output_size_bytes} bytes.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')
    return redirect('condenser:home')


@login_required
@require_POST
def distill_full_chain(request):
    """Run the entire Tiles distillation chain: Django→JS→ESP→ATTiny→555."""
    from .distill_tiles import distill as tiles_distill
    from .distill_esp import distill as esp_distill
    from .distill_attiny import distill as attiny_distill
    from .distill_circuit import distill as circuit_distill

    results = []
    tiers = [
        ('Tiles → JS', 'django', 'js', lambda: tiles_distill()),
        ('Tiles → ESP', 'js', 'esp', lambda: esp_distill(results[-1].output)),
        ('Tiles → ATTiny', 'esp', 'attiny', lambda: attiny_distill()),
        ('Tiles → 555', 'attiny', 'circuit', lambda: circuit_distill()),
    ]

    for name, src, tgt, fn in tiers:
        d = Distillation(name=name, source_app='tiles',
                         source_tier=src, target_tier=tgt, status='running')
        d.save()
        try:
            output = fn()
            d.output = output
            d.output_size_bytes = len(output.encode('utf-8'))
            d.status = 'completed'
            d.completed_at = timezone.now()
            d.annotations = _extract_annotations(output)
            d.save()
            results.append(d)
        except Exception as e:
            d.status = 'error'
            d.error_detail = str(e)
            d.save()
            messages.error(request, f'{name} failed: {e}')
            break

    if len(results) == 4:
        sizes = ' → '.join(f'{d.output_size_bytes}B' for d in results)
        
        _record_insight(d)
        messages.success(request, f'Full chain complete: {sizes}')
    return redirect('condenser:home')


@login_required
def live_condense(request, app_label):
    """Generate and serve a condensed app on the fly.
    Visit /condenser/live/tiles/ to see the tiles app condensed to JS."""
    from .parser import parse_app
    from .gen_js import generate as gen_js
    ir = parse_app(app_label)
    if not ir:
        return HttpResponse(f'App "{app_label}" not found.', status=404)
    return HttpResponse(gen_js(ir), content_type='text/html; charset=utf-8')


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


def _record_insight(d):
    """Record a reflection on the distillation in the Dream Journal."""
    try:
        from .recursive_insight import record_distillation_in_journal
        record_distillation_in_journal(d)
    except Exception:
        pass


@login_required
@require_POST
def distill_aether_stereokit(request, slug):
    """Distill an Aether world → StereoKit C# project for Quest 3."""
    import io
    import zipfile
    from .aether_parser import parse_world
    from .gen_stereokit import generate

    scene_ir = parse_world(slug)
    if not scene_ir:
        messages.error(request, f'World "{slug}" not found.')
        return redirect('condenser:home')

    d = Distillation(
        name=f'Aether "{scene_ir.title}" → StereoKit (Quest 3)',
        source_app='aether',
        source_tier='django',
        target_tier='stereokit',
        status='running',
    )
    d.save()

    try:
        files = generate(scene_ir)

        # Concatenate all files as the stored output (for viewing)
        output_parts = []
        for path, content in sorted(files.items()):
            output_parts.append(f'// === {path} ===\n{content}')
        output = '\n\n'.join(output_parts)

        d.output = output
        d.output_size_bytes = sum(len(c.encode('utf-8')) for c in files.values())
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        _record_insight(d)

        # Return as downloadable ZIP
        buf = io.BytesIO()
        project_dir = f'Aether_{slug.replace("-", "_")}'
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path, content in files.items():
                zf.writestr(f'{project_dir}/{path}', content)
        buf.seek(0)

        response = HttpResponse(buf.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{project_dir}.zip"'
        messages.success(
            request,
            f'Distilled "{scene_ir.title}" → StereoKit: '
            f'{d.output_size_bytes} bytes, {len(files)} files.',
        )
        return response

    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'StereoKit distillation failed: {e}')
        return redirect('condenser:home')


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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
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
@xframe_options_sameorigin
def distillation_raw(request, slug):
    """Serve the raw distilled output as HTML (for preview in iframe).

    Default `XFrameOptionsMiddleware` sends `X-Frame-Options: DENY`,
    which blocks the iframe in detail.html even on same-origin
    pages. The decorator overrides DENY → SAMEORIGIN so the embed
     works without weakening the global default for other views.

    JS-tier outputs are real HTML and pass through unchanged.
    ATTiny / ESP / circuit tiers emit plain C / text; wrap those in
    a minimal hacker-green shell so the iframe (which sits on a dark
    background) doesn't render dark text on dark.
    """
    d = get_object_or_404(Distillation, slug=slug)
    body = d.output
    head = body.lstrip()[:32].lower()
    is_html = head.startswith('<!doctype') or head.startswith('<html')
    if not is_html:
        from django.utils.html import escape
        body = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>html,body{margin:0;background:#0d1117}'
            'pre{margin:0;padding:1rem;color:#3fb950;'
            'font:0.78rem/1.45 ui-monospace,Menlo,Consolas,monospace;'
            'white-space:pre-wrap;word-wrap:break-word}</style>'
            f'</head><body><pre>{escape(d.output)}</pre></body></html>'
        )
    return HttpResponse(body, content_type='text/html; charset=utf-8')


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


def _distill_and_save(request, *, name, source_tier, target_tier, build,
                      source_app='det',
                      success_fmt='Distilled: {size} bytes.'):
    """Shared scaffolding — create Distillation row, run `build()`, save,
    extract annotations, record insight, redirect to detail."""
    d = Distillation(name=name, source_app=source_app, source_tier=source_tier,
                     target_tier=target_tier, status='running')
    d.save()
    try:
        output = build()
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        _record_insight(d)
        messages.success(request, success_fmt.format(size=d.output_size_bytes))
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Distillation failed: {e}')
    return redirect('condenser:detail', slug=d.slug)


@login_required
@require_POST
def emulate_attiny(request, slug):
    """Push an attiny-tier distillation into bodymap's in-browser emulator.

    Creates a fresh AttinyDesign with the distilled C, invokes bodymap's
    avr-gcc pipeline, and redirects to the emulator view. Only t13a is
    supported — the emulator is t13a-only; a t85 distillation lands in
    the editor instead."""
    from bodymap.attiny_views import _compile_design, _next_i2c_address, _unique_design_slug
    from bodymap.models import AttinyDesign

    d = get_object_or_404(Distillation, slug=slug)
    if d.target_tier != 'attiny' or not d.output:
        messages.error(request, 'Only ATTiny distillations can be emulated.')
        return redirect('condenser:detail', slug=slug)

    # Infer MCU from the distillation source. The t13a output explicitly
    # names "ATTiny13a" in its header; the t85 output names "ATTiny85".
    src = d.output
    mcu = 'attiny85' if ('ATTiny85' in src or 'attiny85' in src) else 'attiny13a'

    design = AttinyDesign.objects.create(
        slug=_unique_design_slug(f'{d.slug}-emu'),
        name=f'{d.name} (emulator)',
        mcu=mcu,
        c_source=src,
        description=f'Auto-created from Condenser distillation "{d.name}".',
        i2c_address=_next_i2c_address(),
    )
    _compile_design(design)
    design.save()

    if not design.compile_ok:
        messages.error(request,
            f'Compile failed — opening the editor so you can see the log. '
            f'(Snippet: {design.compile_log[-200:]})')
        return redirect('bodymap:attiny_design', slug=design.slug)

    if mcu != 'attiny13a':
        messages.warning(request,
            'The in-browser emulator is t13a-only. Opened this design '
            'in the editor — flash it to real hardware to run it.')
        return redirect('bodymap:attiny_design', slug=design.slug)

    return redirect('bodymap:attiny_emulate_slug', slug=design.slug)


@login_required
@require_POST
def distill_det_attiny13a(request):
    """Det ancestor → ATTiny13a: Rule 110 in 1KB."""
    from .distill_det import distill_attiny13a
    return _distill_and_save(
        request,
        name='Det → ATTiny13a (Rule 110 ancestor)',
        source_tier='django', target_tier='attiny',
        build=distill_attiny13a,
        success_fmt='Det → ATTiny13a: {size} bytes of Rule 110.',
    )


@login_required
@require_POST
def distill_det_attiny85(request):
    """Det → ATTiny85: one baked hex ruleset."""
    from .distill_det import distill_attiny85
    n_colors = max(2, min(4, int(request.POST.get('n_colors', 2))))
    n_rules = max(4, min(64, int(request.POST.get('n_rules', 24))))
    wildcard_pct = max(0, min(80, int(request.POST.get('wildcard_pct', 20))))
    seed_raw = request.POST.get('seed', '').strip()
    seed = int(seed_raw) if seed_raw.isdigit() else None
    return _distill_and_save(
        request,
        name=f'Det → ATTiny85 (1 baked ruleset, {n_colors}c×{n_rules}r)',
        source_tier='django', target_tier='attiny',
        build=lambda: distill_attiny85(n_colors=n_colors, n_rules=n_rules,
                                       wildcard_pct=wildcard_pct, seed=seed),
        success_fmt='Det → ATTiny85: {size} bytes.',
    )


@login_required
@require_POST
def distill_det_esp8266(request):
    """Det → ESP8266: baked candidates + web scoreboard."""
    from .distill_det import distill_esp8266
    n_candidates = max(1, min(6, int(request.POST.get('n_candidates', 3))))
    n_rules = max(20, min(200, int(request.POST.get('n_rules', 80))))
    n_colors = max(2, min(4, int(request.POST.get('n_colors', 3))))
    W = max(6, min(24, int(request.POST.get('W', 12))))
    H = max(4, min(20, int(request.POST.get('H', 8))))
    horizon = max(10, min(120, int(request.POST.get('horizon', 30))))
    ssid = request.POST.get('wifi_ssid', 'YOUR_WIFI').strip() or 'YOUR_WIFI'
    pwd = request.POST.get('wifi_pass', 'YOUR_PASS').strip() or 'YOUR_PASS'
    return _distill_and_save(
        request,
        name=f'Det → ESP8266 ({n_candidates} cand × {n_rules} rules, {W}×{H})',
        source_tier='django', target_tier='esp',
        build=lambda: distill_esp8266(n_candidates=n_candidates, n_rules=n_rules,
                                      n_colors=n_colors, W=W, H=H, horizon=horizon,
                                      wifi_ssid=ssid, wifi_pass=pwd),
        success_fmt='Det → ESP8266: {size} bytes.',
    )


@login_required
@require_POST
def distill_det_esp32s3(request):
    """Det → ESP32-S3 SuperMini: on-chip search + web UI."""
    from .distill_det import distill_esp32s3
    n_candidates = max(2, min(48, int(request.POST.get('n_candidates', 12))))
    n_rules = max(20, min(250, int(request.POST.get('n_rules', 100))))
    n_colors = max(2, min(4, int(request.POST.get('n_colors', 4))))
    W = max(8, min(32, int(request.POST.get('W', 16))))
    H = max(6, min(24, int(request.POST.get('H', 12))))
    horizon = max(10, min(200, int(request.POST.get('horizon', 40))))
    wildcard_pct = max(0, min(80, int(request.POST.get('wildcard_pct', 25))))
    ssid = request.POST.get('wifi_ssid', 'YOUR_WIFI').strip() or 'YOUR_WIFI'
    pwd = request.POST.get('wifi_pass', 'YOUR_PASS').strip() or 'YOUR_PASS'
    return _distill_and_save(
        request,
        name=f'Det → ESP32-S3 ({n_candidates}×{n_rules}, {W}×{H}, on-chip search)',
        source_tier='django', target_tier='esp',
        build=lambda: distill_esp32s3(W=W, H=H, horizon=horizon, n_colors=n_colors,
                                      n_candidates=n_candidates, n_rules=n_rules,
                                      wildcard_pct=wildcard_pct,
                                      wifi_ssid=ssid, wifi_pass=pwd),
        success_fmt='Det → ESP32-S3: {size} bytes.',
    )


@login_required
@require_POST
def distill_hexnn_esp32s3(request):
    """HexNN → ESP32-S3 SuperMini: full pipeline (genome + hunt + run)."""
    from .distill_hexnn import distill_hexnn_esp32s3 as build
    K        = max(2, min(64,    int(request.POST.get('K', 4))))
    n_log2   = max(8, min(14,    int(request.POST.get('n_log2', 11))))
    W        = max(8, min(32,    int(request.POST.get('W', 16))))
    H        = max(6, min(24,    int(request.POST.get('H', 16))))
    horizon  = max(20, min(200,  int(request.POST.get('horizon', 80))))
    burn_in  = max(4, min(80,    int(request.POST.get('burn_in', 20))))
    pop_size = max(2, min(16,    int(request.POST.get('pop_size', 8))))
    gens     = max(5, min(120,   int(request.POST.get('generations', 30))))
    rate_raw = request.POST.get('mutation_rate', '0.0008').strip()
    try:    rate = max(0.0, min(0.05, float(rate_raw)))
    except ValueError: rate = 0.0008
    run_hunt = request.POST.get('run_hunt', 'on') in ('on', '1', 'true')
    tick_ms  = max(40, min(2000, int(request.POST.get('tick_ms', 200))))
    ssid     = request.POST.get('wifi_ssid', 'YOUR_WIFI').strip() or 'YOUR_WIFI'
    pwd      = request.POST.get('wifi_pass', 'YOUR_PASS').strip() or 'YOUR_PASS'
    label = (f'HexNN → ESP32-S3 (K={K}, N=2^{n_log2}, '
             f'{W}×{H}, pop {pop_size}×{gens})')
    return _distill_and_save(
        request,
        name=label,
        source_app='hexnn',
        source_tier='django', target_tier='esp',
        build=lambda: build(K=K, n_log2=n_log2, W=W, H=H, horizon=horizon,
                            burn_in=burn_in, pop_size=pop_size,
                            generations=gens, mutation_rate=rate,
                            run_hunt=run_hunt, tick_ms=tick_ms,
                            wifi_ssid=ssid, wifi_pass=pwd),
        success_fmt='HexNN → ESP32-S3: {size} bytes.',
    )


@login_required
def decision_tree_555(request):
    """Information page: decision trees built from 555 timer ICs."""
    return render(request, 'condenser/decision_tree_555.html', {})


@login_required
def decision_tree_form(request):
    """Form for defining a decision tree for ATTiny13a + picoUART."""
    if request.method == 'POST':
        return _distill_decision_tree(request)
    return render(request, 'condenser/decision_tree.html', {})


@login_required
@require_POST
def _distill_decision_tree(request):
    """Generate ATTiny13a decision tree C code from form data."""
    from .distill_decision_tree import distill

    # Parse rules from form
    channels = request.POST.getlist('channel')
    thresholds = request.POST.getlist('threshold')
    labels = request.POST.getlist('label')
    values = request.POST.getlist('value')

    rules = []
    for ch, thr, label, val in zip(channels, thresholds, labels, values):
        thr = thr.strip()
        val = val.strip()
        if not thr or not val:
            continue
        try:
            v = int(val)
        except ValueError:
            v = ord(val[0]) if val else 0
        rules.append({
            'channel': int(ch),
            'threshold': int(thr),
            'label': label.strip(),
            'value': v,
        })

    if not rules:
        messages.error(request, 'No valid rules provided.')
        return redirect('condenser:decision_tree')

    name = request.POST.get('name', 'sensor_decision').strip() or 'sensor_decision'
    baud = int(request.POST.get('baud', 9600))
    loop_delay = int(request.POST.get('loop_delay', 500))
    median_filter = 'median_filter' in request.POST
    framed = 'framed' in request.POST
    goedel = 'goedel' in request.POST
    led = 'led' in request.POST
    bytebeat = 'bytebeat' in request.POST

    d = Distillation(
        name=f'Decision Tree → ATTiny13a: {name}',
        source_app='condenser',
        source_tier='django',
        target_tier='attiny',
        status='running',
    )
    d.save()

    try:
        output = distill(
            rules=rules,
            baud=baud,
            loop_delay_ms=loop_delay,
            name=name,
            median_filter=median_filter,
            framed=framed,
            goedel=goedel,
            led=led,
            bytebeat=bytebeat,
        )
        d.output = output
        d.output_size_bytes = len(output.encode('utf-8'))
        d.status = 'completed'
        d.completed_at = timezone.now()
        d.annotations = _extract_annotations(output)
        d.save()
        _record_insight(d)
        messages.success(
            request,
            f'Decision tree "{name}": {d.output_size_bytes} bytes C code, '
            f'{len(rules)} rules, fits ATTiny13a 1KB flash.')
    except Exception as e:
        d.status = 'error'
        d.error_detail = str(e)
        d.save()
        messages.error(request, f'Decision tree generation failed: {e}')

    return redirect('condenser:detail', slug=d.slug)


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

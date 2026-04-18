"""ATtiny workshop — browse templates, fork into designs, edit, compile.

Flashing is phase 2 (USBasp + avrdude) — not wired here yet.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import AttinyDesign, AttinyTemplate


# --- Compile helpers ------------------------------------------------------
def _avr_size_text(elf_path):
    """Return the .text section size in bytes, or None if avr-size fails."""
    try:
        r = subprocess.run(
            ['avr-size', '-A', str(elf_path)],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return None
    m = re.search(r'^\.text\s+(\d+)\s', r.stdout, re.MULTILINE)
    return int(m.group(1)) if m else None


def _compile_design(design: AttinyDesign):
    """Run avr-gcc + avr-objcopy on the design's C source. Mutates the
    design's compile_* fields in place. Does NOT call save() — caller
    does that so we get a single DB write."""
    log_parts = []
    tmp = Path(tempfile.mkdtemp(prefix='attiny_'))
    c_path   = tmp / 'design.c'
    elf_path = tmp / 'design.elf'
    hex_path = tmp / 'design.hex'
    c_path.write_text(design.c_source)

    # avr-gcc compile+link in one shot.
    cc = subprocess.run(
        [
            'avr-gcc',
            f'-mmcu={design.mcu}',
            '-Os', '-Wall', '-Wextra',
            '-o', str(elf_path),
            str(c_path),
        ],
        capture_output=True, text=True, timeout=15,
    )
    log_parts.append(f'$ avr-gcc -mmcu={design.mcu} -Os -Wall ...')
    if cc.stdout: log_parts.append(cc.stdout.rstrip())
    if cc.stderr: log_parts.append(cc.stderr.rstrip())

    if cc.returncode != 0:
        design.compile_ok    = False
        design.compile_log   = '\n'.join(log_parts)
        design.compiled_at   = timezone.now()
        design.compiled_hex  = ''
        design.program_bytes = None
        return

    text_bytes = _avr_size_text(elf_path)
    log_parts.append(f'.text = {text_bytes} bytes'
                     f' (budget {design.flash_limit_bytes})')

    oc = subprocess.run(
        ['avr-objcopy', '-O', 'ihex', '-R', '.eeprom',
         str(elf_path), str(hex_path)],
        capture_output=True, text=True, timeout=5,
    )
    log_parts.append('$ avr-objcopy -O ihex ...')
    if oc.stdout: log_parts.append(oc.stdout.rstrip())
    if oc.stderr: log_parts.append(oc.stderr.rstrip())

    if oc.returncode != 0:
        design.compile_ok    = False
        design.compile_log   = '\n'.join(log_parts)
        design.compiled_at   = timezone.now()
        design.compiled_hex  = ''
        design.program_bytes = text_bytes
        return

    hex_text = hex_path.read_text()
    design.compile_ok    = True
    design.compile_log   = '\n'.join(log_parts)
    design.compiled_at   = timezone.now()
    design.compiled_hex  = hex_text
    design.program_bytes = text_bytes


def _next_i2c_address():
    """Next free 7-bit I2C slave address, starting at 0x08."""
    used = set(
        AttinyDesign.objects.values_list('i2c_address', flat=True)
    )
    for addr in range(0x08, 0x78):
        if addr not in used:
            return addr
    return 0x08  # wrap — user edits manually if a real conflict arises


def _unique_design_slug(seed):
    base = slugify(seed)[:72] or 'design'
    slug = base
    n = 2
    while AttinyDesign.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


# --- Views ---------------------------------------------------------------
@login_required
def attiny_index(request):
    templates = AttinyTemplate.objects.all()
    designs   = AttinyDesign.objects.select_related('template').all()
    return render(request, 'bodymap/attiny/index.html', {
        'templates': templates,
        'designs':   designs,
    })


@login_required
def attiny_template_detail(request, slug):
    tpl = get_object_or_404(AttinyTemplate, slug=slug)
    return render(request, 'bodymap/attiny/template_detail.html', {
        'template': tpl,
    })


@login_required
@require_POST
def attiny_fork_template(request, slug):
    """Clone a template into a fresh AttinyDesign and send the user
    straight to the editor."""
    tpl = get_object_or_404(AttinyTemplate, slug=slug)
    name_seed = f'{tpl.name} copy'
    design = AttinyDesign.objects.create(
        slug=_unique_design_slug(name_seed),
        name=name_seed,
        template=tpl,
        mcu=tpl.mcu,
        c_source=tpl.c_source,
        description=f'Forked from template "{tpl.name}".',
        i2c_address=_next_i2c_address(),
    )
    messages.success(request, f'Forked "{tpl.name}" into {design.slug}.')
    return redirect('bodymap:attiny_design', slug=design.slug)


@login_required
def attiny_design_detail(request, slug):
    design = get_object_or_404(AttinyDesign, slug=slug)
    return render(request, 'bodymap/attiny/design.html', {
        'design':   design,
        'template': design.template,
    })


@login_required
@require_POST
def attiny_design_save(request, slug):
    design = get_object_or_404(AttinyDesign, slug=slug)
    design.name        = (request.POST.get('name') or design.name).strip()[:80]
    design.description = (request.POST.get('description') or '').strip()
    design.c_source    = request.POST.get('c_source') or design.c_source
    try:
        addr = int(request.POST.get('i2c_address') or design.i2c_address)
        if 0x08 <= addr <= 0x77:
            design.i2c_address = addr
    except (TypeError, ValueError):
        pass
    mcu = (request.POST.get('mcu') or design.mcu).strip()
    if mcu in ('attiny85', 'attiny13a'):
        design.mcu = mcu
    # Changing source invalidates prior compile.
    design.compile_ok   = False
    design.compiled_hex = ''
    design.compile_log  = ''
    design.compiled_at  = None
    design.save()
    return JsonResponse({
        'ok':   True,
        'slug': design.slug,
        'i2c_address': design.i2c_address,
    })


@login_required
@require_POST
def attiny_design_build(request, slug):
    design = get_object_or_404(AttinyDesign, slug=slug)
    # Pick up any in-flight textarea contents before compiling so the
    # user doesn't have to click Save first.
    source = request.POST.get('c_source')
    if source is not None:
        design.c_source = source
    mcu = (request.POST.get('mcu') or design.mcu).strip()
    if mcu in ('attiny85', 'attiny13a'):
        design.mcu = mcu
    _compile_design(design)
    design.save()
    return JsonResponse({
        'ok':            design.compile_ok,
        'log':           design.compile_log,
        'program_bytes': design.program_bytes,
        'flash_limit':   design.flash_limit_bytes,
        'has_hex':       bool(design.compiled_hex),
    })


@login_required
def attiny_design_hex(request, slug):
    design = get_object_or_404(AttinyDesign, slug=slug)
    if not design.compiled_hex:
        raise Http404('not built')
    resp = HttpResponse(design.compiled_hex, content_type='text/plain')
    resp['Content-Disposition'] = f'attachment; filename="{design.slug}.hex"'
    return resp


@login_required
@require_POST
def attiny_design_delete(request, slug):
    design = get_object_or_404(AttinyDesign, slug=slug)
    name = design.name
    design.delete()
    messages.success(request, f'Deleted design "{name}".')
    return redirect('bodymap:attiny_index')


# --- Emulator ------------------------------------------------------------
@login_required
def attiny_emulate(request, slug=None):
    """In-browser ATtiny13a virtual panel. All execution happens client-
    side in static/js/attiny_emu.js; the server just serves the hex.
    Also accepts templates (slug points at an AttinyTemplate) by
    compiling on-the-fly into an ephemeral AttinyDesign-like shape."""
    # Designs with a built hex are the primary picker.
    designs = (AttinyDesign.objects
               .filter(mcu='attiny13a', compile_ok=True)
               .exclude(compiled_hex='')
               .select_related('template')
               .order_by('-compiled_at'))

    active = None
    active_hex = ''
    active_source = ''
    if slug:
        # Try design first, then template (we compile template on demand).
        active = AttinyDesign.objects.filter(slug=slug, mcu='attiny13a').first()
        if active and active.compiled_hex:
            active_hex = active.compiled_hex
            active_source = active.c_source
        else:
            tpl = AttinyTemplate.objects.filter(slug=slug, mcu='attiny13a').first()
            if tpl is None:
                raise Http404('No t13a design/template with that slug.')
            # Compile template into a temporary design-like shape.
            tmp = AttinyDesign(
                slug=tpl.slug, name=tpl.name, mcu='attiny13a',
                c_source=tpl.c_source,
            )
            _compile_design(tmp)
            if not tmp.compile_ok:
                messages.error(request,
                    f'Template "{tpl.name}" failed to compile for the emulator.')
            active_hex = tmp.compiled_hex
            active_source = tmp.c_source
            active = tmp

    # Also offer all t13a templates as quick-load options.
    templates = AttinyTemplate.objects.filter(mcu='attiny13a').order_by('name')

    return render(request, 'bodymap/attiny/emulator.html', {
        'designs':       designs,
        'templates':     templates,
        'active':        active,
        'active_hex':    active_hex,
        'active_source': active_source,
    })

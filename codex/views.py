from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .importers import import_bytes, split_sections, supported_extensions
from .models import (
    CAPTION_POSITION_CHOICES, FIGURE_KIND_CHOICES, FORMAT_CHOICES,
    Figure, Manual, Section, Volume, VolumeManual,
)
from .rendering import render_manual_to_pdf, render_volume_to_pdf, wrap_print_ready


# --- Manual CRUD ----------------------------------------------------------

@login_required
def manual_list(request):
    manuals = Manual.objects.all()
    return render(request, 'codex/list.html', {'manuals': manuals})


_MANUAL_TEXT_FIELDS = (
    'title', 'subtitle', 'author', 'version', 'abstract',
    'edition', 'isbn', 'doi', 'publisher', 'publisher_city',
    'copyright_year', 'copyright_holder', 'license',
)


def _apply_manual_post(m, post):
    for f in _MANUAL_TEXT_FIELDS:
        setattr(m, f, post.get(f, '').strip())
    m.format = post.get('format', 'short')
    m.double_spaced = bool(post.get('double_spaced'))
    m.bibliography = post.get('bibliography', '')
    raw_date = post.get('publication_date', '').strip()
    if raw_date:
        from datetime import date
        try:
            y, mo, d = raw_date.split('-')
            m.publication_date = date(int(y), int(mo), int(d))
        except (ValueError, TypeError):
            m.publication_date = None
    else:
        m.publication_date = None


@login_required
def manual_add(request):
    m = Manual()
    if request.method == 'POST':
        _apply_manual_post(m, request.POST)
        if not m.title:
            messages.error(request, 'Title is required.')
        else:
            m.save()
            messages.success(request, f'Created "{m.title}".')
            return redirect('codex:manual_detail', slug=m.slug)
    return render(request, 'codex/manual_form.html', {
        'manual': m, 'action': 'New', 'format_choices': FORMAT_CHOICES,
    })


@login_required
def manual_edit(request, slug):
    m = get_object_or_404(Manual, slug=slug)
    if request.method == 'POST':
        _apply_manual_post(m, request.POST)
        if not m.title:
            messages.error(request, 'Title is required.')
        else:
            m.save()
            messages.success(request, f'Updated "{m.title}".')
            return redirect('codex:manual_detail', slug=m.slug)
    return render(request, 'codex/manual_form.html', {
        'manual': m, 'action': 'Edit', 'format_choices': FORMAT_CHOICES,
    })


@login_required
@require_POST
def manual_delete(request, slug):
    m = get_object_or_404(Manual, slug=slug)
    title = m.title
    m.delete()
    messages.success(request, f'Removed "{title}".')
    return redirect('codex:list')


@login_required
def manual_import(request):
    """Create a new Manual from an uploaded file or pasted text.

    Sections are cut at H1/H2 boundaries in the converted markdown. A
    chunk of content before the first heading becomes a leading
    "Preamble" section. If the source has no headings at all, the
    whole thing lands in one section named after the manual.
    """
    title = subtitle = pasted = ''
    fmt = 'short'
    if request.method == 'POST':
        title    = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        fmt      = request.POST.get('format', 'short')
        pasted   = request.POST.get('pasted', '')
        upload   = request.FILES.get('source_file')

        if not title:
            messages.error(request, 'Title is required.')
        elif not upload and not pasted.strip():
            messages.error(request, 'Upload a file or paste some text.')
        else:
            try:
                if upload:
                    md = import_bytes(upload.read(), upload.name)
                else:
                    md = pasted
            except (ValueError, ImportError, RuntimeError) as e:
                messages.error(request, f'Import failed: {e}')
                md = None

            if md is not None:
                m = Manual(title=title, subtitle=subtitle, format=fmt)
                m.save()
                pairs = split_sections(md) or [(None, md)]
                for i, (sec_title, body) in enumerate(pairs):
                    name = sec_title or ('Preamble' if i == 0 else m.title)
                    Section.objects.create(
                        manual=m, title=name[:200],
                        body=body, sort_order=i * 10,
                    )
                messages.success(
                    request,
                    f'Imported "{m.title}" with {len(pairs)} section'
                    f'{"" if len(pairs) == 1 else "s"}.',
                )
                return redirect('codex:manual_detail', slug=m.slug)

    return render(request, 'codex/manual_import.html', {
        'title': title, 'subtitle': subtitle, 'pasted': pasted,
        'format': fmt, 'format_choices': FORMAT_CHOICES,
        'extensions': supported_extensions(),
    })


@login_required
def manual_detail(request, slug):
    m = get_object_or_404(Manual, slug=slug)
    return render(request, 'codex/detail.html', {
        'manual': m,
        'sections': m.sections.all().order_by('sort_order', 'pk'),
    })


@login_required
def manual_pdf(request, slug):
    m = get_object_or_404(Manual, slug=slug)
    pdf_bytes = render_manual_to_pdf(m)
    m.last_built_at = timezone.now()
    m.save(update_fields=['last_built_at'])
    if request.GET.get('print') == '1':
        bleed = _parse_bleed(request.GET.get('bleed'))
        pdf_bytes = wrap_print_ready(pdf_bytes, bleed_mm=bleed)
        filename = f'{m.slug}-print.pdf'
    else:
        filename = f'{m.slug}.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


def _parse_bleed(raw):
    try:
        v = float(raw) if raw else 3.0
    except (ValueError, TypeError):
        return 3.0
    return max(0.0, min(v, 10.0))


# --- Section CRUD ---------------------------------------------------------

_SECTION_TEXT_FIELDS = ('title', 'body', 'sidenotes')


def _apply_section_post(s, post):
    for f in _SECTION_TEXT_FIELDS:
        setattr(s, f, post.get(f, ''))
    raw = post.get('sort_order', '0').strip()
    try:
        s.sort_order = int(raw)
    except ValueError:
        s.sort_order = 0


@login_required
def section_add(request, manual_slug):
    m = get_object_or_404(Manual, slug=manual_slug)
    s = Section(manual=m)
    if request.method == 'POST':
        _apply_section_post(s, request.POST)
        if not s.title:
            messages.error(request, 'Section title is required.')
        else:
            # Auto-place at the end of the manual.
            if not request.POST.get('sort_order', '').strip():
                last = m.sections.order_by('-sort_order').first()
                s.sort_order = ((last.sort_order + 10) if last else 0)
            s.save()
            messages.success(request, f'Added section "{s.title}".')
            return redirect('codex:manual_detail', slug=m.slug)
    return render(request, 'codex/section_form.html', {
        'manual': m, 'section': s, 'action': 'New',
    })


@login_required
def section_edit(request, manual_slug, section_slug):
    m = get_object_or_404(Manual, slug=manual_slug)
    s = get_object_or_404(Section, manual=m, slug=section_slug)
    if request.method == 'POST':
        _apply_section_post(s, request.POST)
        if not s.title:
            messages.error(request, 'Section title is required.')
        else:
            s.save()
            messages.success(request, f'Updated section "{s.title}".')
            return redirect('codex:section_edit', manual_slug=m.slug, section_slug=s.slug)
    return render(request, 'codex/section_form.html', {
        'manual': m, 'section': s, 'action': 'Edit',
        'figures': s.figures.all(),
    })


@login_required
@require_POST
def section_delete(request, manual_slug, section_slug):
    m = get_object_or_404(Manual, slug=manual_slug)
    s = get_object_or_404(Section, manual=m, slug=section_slug)
    title = s.title
    s.delete()
    messages.success(request, f'Removed section "{title}".')
    return redirect('codex:manual_detail', slug=m.slug)


# --- Figure CRUD ----------------------------------------------------------

def _apply_figure_post(f, post, files):
    raw_slug = post.get('slug', '').strip()
    f.slug = slugify(raw_slug)[:120] if raw_slug else slugify(f.section.title + '-fig')[:120]
    f.kind = post.get('kind', 'image')
    f.source = post.get('source', '')
    f.caption = post.get('caption', '').strip()
    f.caption_position = post.get('caption_position', 'margin')
    raw = post.get('sort_order', '0').strip()
    try:
        f.sort_order = int(raw)
    except ValueError:
        f.sort_order = 0
    if 'image' in files:
        f.image = files['image']


@login_required
def figure_add(request, manual_slug, section_slug):
    m = get_object_or_404(Manual, slug=manual_slug)
    s = get_object_or_404(Section, manual=m, slug=section_slug)
    f = Figure(section=s)
    if request.method == 'POST':
        _apply_figure_post(f, request.POST, request.FILES)
        if not f.slug:
            messages.error(request, 'Slug is required.')
        elif f.kind == 'image' and not f.image:
            messages.error(request, 'Upload an image, or pick a diagram kind.')
        elif f.kind != 'image' and not f.source.strip():
            messages.error(request, f'{f.get_kind_display()} source is required.')
        else:
            try:
                if not request.POST.get('sort_order', '').strip():
                    last = s.figures.order_by('-sort_order').first()
                    f.sort_order = ((last.sort_order + 10) if last else 0)
                f.save()
                if f.kind != 'image' and not f.image:
                    messages.warning(request, f'Saved "{f.slug}", but {f.get_kind_display()} render via Kroki failed (network or bad source). Edit and re-save to retry.')
                else:
                    messages.success(request, f'Added figure "{f.slug}".')
                return redirect('codex:section_edit', manual_slug=m.slug, section_slug=s.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'codex/figure_form.html', {
        'manual': m, 'section': s, 'figure': f,
        'action': 'New', 'kind_choices': FIGURE_KIND_CHOICES,
        'position_choices': CAPTION_POSITION_CHOICES,
    })


@login_required
def figure_edit(request, manual_slug, section_slug, figure_slug):
    m = get_object_or_404(Manual, slug=manual_slug)
    s = get_object_or_404(Section, manual=m, slug=section_slug)
    f = get_object_or_404(Figure, section=s, slug=figure_slug)
    if request.method == 'POST':
        _apply_figure_post(f, request.POST, request.FILES)
        if not f.slug:
            messages.error(request, 'Slug is required.')
        else:
            try:
                f.save()
                if f.kind != 'image' and not f.image:
                    messages.warning(request, f'Saved "{f.slug}", but {f.get_kind_display()} render failed.')
                else:
                    messages.success(request, f'Updated figure "{f.slug}".')
                return redirect('codex:section_edit', manual_slug=m.slug, section_slug=s.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'codex/figure_form.html', {
        'manual': m, 'section': s, 'figure': f,
        'action': 'Edit', 'kind_choices': FIGURE_KIND_CHOICES,
        'position_choices': CAPTION_POSITION_CHOICES,
    })


@login_required
@require_POST
def figure_delete(request, manual_slug, section_slug, figure_slug):
    m = get_object_or_404(Manual, slug=manual_slug)
    s = get_object_or_404(Section, manual=m, slug=section_slug)
    f = get_object_or_404(Figure, section=s, slug=figure_slug)
    slug = f.slug
    f.delete()
    messages.success(request, f'Removed figure "{slug}".')
    return redirect('codex:section_edit', manual_slug=m.slug, section_slug=s.slug)


# --- Volume CRUD ----------------------------------------------------------

_VOLUME_TEXT_FIELDS = ('title', 'subtitle', 'author', 'version', 'abstract')


def _apply_volume_post(v, post):
    for f in _VOLUME_TEXT_FIELDS:
        setattr(v, f, post.get(f, '').strip())


@login_required
def volume_list(request):
    return render(request, 'codex/volume_list.html', {
        'volumes': Volume.objects.all(),
    })


@login_required
def volume_add(request):
    v = Volume()
    if request.method == 'POST':
        _apply_volume_post(v, request.POST)
        if not v.title:
            messages.error(request, 'Title is required.')
        else:
            v.save()
            messages.success(request, f'Created Volume "{v.title}".')
            return redirect('codex:volume_detail', slug=v.slug)
    return render(request, 'codex/volume_form.html', {
        'volume': v, 'action': 'New',
    })


@login_required
def volume_edit(request, slug):
    v = get_object_or_404(Volume, slug=slug)
    if request.method == 'POST':
        _apply_volume_post(v, request.POST)
        if not v.title:
            messages.error(request, 'Title is required.')
        else:
            v.save()
            messages.success(request, f'Updated "{v.title}".')
            return redirect('codex:volume_detail', slug=v.slug)
    return render(request, 'codex/volume_form.html', {
        'volume': v, 'action': 'Edit',
    })


@login_required
@require_POST
def volume_delete(request, slug):
    v = get_object_or_404(Volume, slug=slug)
    title = v.title
    v.delete()
    messages.success(request, f'Removed Volume "{title}".')
    return redirect('codex:volume_list')


@login_required
def volume_detail(request, slug):
    v = get_object_or_404(Volume, slug=slug)
    entries = v.entries.select_related('manual').order_by('sort_order', 'pk')
    # Manuals not yet in this volume (for the add picker).
    in_ids = {e.manual_id for e in entries}
    candidates = Manual.objects.exclude(pk__in=in_ids).order_by('title')
    return render(request, 'codex/volume_detail.html', {
        'volume': v, 'entries': entries, 'candidates': candidates,
    })


@login_required
@require_POST
def volume_add_manual(request, slug):
    v = get_object_or_404(Volume, slug=slug)
    manual_id = request.POST.get('manual_id')
    m = get_object_or_404(Manual, pk=manual_id)
    last = v.entries.order_by('-sort_order').first()
    sort_order = (last.sort_order + 10) if last else 0
    VolumeManual.objects.get_or_create(
        volume=v, manual=m, defaults={'sort_order': sort_order},
    )
    messages.success(request, f'Added "{m.title}" to volume.')
    return redirect('codex:volume_detail', slug=v.slug)


@login_required
@require_POST
def volume_remove_manual(request, slug, entry_pk):
    v = get_object_or_404(Volume, slug=slug)
    entry = get_object_or_404(VolumeManual, pk=entry_pk, volume=v)
    entry.delete()
    messages.success(request, 'Removed from volume.')
    return redirect('codex:volume_detail', slug=v.slug)


@login_required
@require_POST
def volume_reorder(request, slug):
    """Accepts a `order` POST field: CSV of VolumeManual PKs in new order."""
    v = get_object_or_404(Volume, slug=slug)
    raw = request.POST.get('order', '')
    for i, pk in enumerate(p.strip() for p in raw.split(',') if p.strip()):
        VolumeManual.objects.filter(volume=v, pk=pk).update(sort_order=i * 10)
    messages.success(request, 'Reordered.')
    return redirect('codex:volume_detail', slug=v.slug)


@login_required
def volume_pdf(request, slug):
    v = get_object_or_404(Volume, slug=slug)
    if not v.entries.exists():
        messages.error(request, 'Add at least one manual before building.')
        return redirect('codex:volume_detail', slug=v.slug)
    pdf_bytes = render_volume_to_pdf(v)
    v.last_built_at = timezone.now()
    v.save(update_fields=['last_built_at'])
    if request.GET.get('print') == '1':
        bleed = _parse_bleed(request.GET.get('bleed'))
        pdf_bytes = wrap_print_ready(pdf_bytes, bleed_mm=bleed)
        filename = f'{v.slug}-print.pdf'
    else:
        filename = f'{v.slug}.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response

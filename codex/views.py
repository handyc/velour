from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import FIGURE_KIND_CHOICES, FORMAT_CHOICES, Figure, Manual, Section
from .rendering import render_manual_to_pdf


# --- Manual CRUD ----------------------------------------------------------

@login_required
def manual_list(request):
    manuals = Manual.objects.all()
    return render(request, 'codex/list.html', {'manuals': manuals})


_MANUAL_TEXT_FIELDS = ('title', 'subtitle', 'author', 'version', 'abstract')


def _apply_manual_post(m, post):
    for f in _MANUAL_TEXT_FIELDS:
        setattr(m, f, post.get(f, '').strip())
    m.format = post.get('format', 'short')
    m.double_spaced = bool(post.get('double_spaced'))


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
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{m.slug}.pdf"'
    return response


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
            messages.error(request, 'Upload an image, or switch kind to Mermaid.')
        elif f.kind == 'mermaid' and not f.source.strip():
            messages.error(request, 'Mermaid source is required.')
        else:
            try:
                if not request.POST.get('sort_order', '').strip():
                    last = s.figures.order_by('-sort_order').first()
                    f.sort_order = ((last.sort_order + 10) if last else 0)
                f.save()
                if f.kind == 'mermaid' and not f.image:
                    messages.warning(request, f'Saved "{f.slug}", but Mermaid render via Kroki failed (network or bad source). Edit and re-save to retry.')
                else:
                    messages.success(request, f'Added figure "{f.slug}".')
                return redirect('codex:section_edit', manual_slug=m.slug, section_slug=s.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'codex/figure_form.html', {
        'manual': m, 'section': s, 'figure': f,
        'action': 'New', 'kind_choices': FIGURE_KIND_CHOICES,
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
                if f.kind == 'mermaid' and not f.image:
                    messages.warning(request, f'Saved "{f.slug}", but Mermaid render failed.')
                else:
                    messages.success(request, f'Updated figure "{f.slug}".')
                return redirect('codex:section_edit', manual_slug=m.slug, section_slug=s.slug)
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'codex/figure_form.html', {
        'manual': m, 'section': s, 'figure': f,
        'action': 'Edit', 'kind_choices': FIGURE_KIND_CHOICES,
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

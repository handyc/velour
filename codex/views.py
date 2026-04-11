from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import FORMAT_CHOICES, Manual, Section
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
            return redirect('codex:manual_detail', slug=m.slug)
    return render(request, 'codex/section_form.html', {
        'manual': m, 'section': s, 'action': 'Edit',
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

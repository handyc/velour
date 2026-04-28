"""Quill views — list / detail / section CRUD / style add.

The detail page is the editor surface for Phase 1: an outline of
sections with inline edit links. Section editing is a separate page
with a contenteditable textarea for body HTML — ProseMirror will slot
in here in Phase 2 without disturbing the URLs or the data model.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import NewDocumentForm, SectionForm, StyleForm
from .models import Document, Section, Style


@login_required
def list_view(request):
    documents = Document.objects.all()
    return render(request, 'quill/list.html', {'documents': documents})


@login_required
def new(request):
    if request.method == 'POST':
        form = NewDocumentForm(request.POST)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.owner = request.user
            doc.save()
            # Seed the document with a default Body style and one empty
            # introduction section so the editor is non-blank on entry.
            Style.objects.create(
                document=doc, name='Body', kind='paragraph',
                css_rules={
                    'font_family': 'Charter, Georgia, serif',
                    'font_size': '11pt',
                    'line_height': '1.55',
                },
            )
            Style.objects.create(
                document=doc, name='Heading 1', kind='paragraph',
                css_rules={
                    'font_family': 'Charter, Georgia, serif',
                    'font_size': '20pt',
                    'font_weight': '600',
                    'margin_top': '1em',
                    'margin_bottom': '0.4em',
                },
            )
            Section.objects.create(
                document=doc, order=0, level=1,
                title='Introduction', body='',
            )
            messages.success(request, f'Created "{doc.title}".')
            return redirect('quill:detail', slug=doc.slug)
    else:
        form = NewDocumentForm()
    return render(request, 'quill/new.html', {'form': form})


@login_required
def detail(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    return render(request, 'quill/detail.html', {
        'document': doc,
        'sections': doc.sections.all(),
        'styles': doc.styles.all(),
    })


@login_required
@require_POST
def delete(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    title = doc.title
    doc.delete()
    messages.success(request, f'Deleted "{title}".')
    return redirect('quill:list')


@login_required
def section_add(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    if request.method == 'POST':
        form = SectionForm(request.POST, document=doc)
        if form.is_valid():
            sec = form.save(commit=False)
            sec.document = doc
            # Append at end among root sections by default.
            last = doc.root_sections().order_by('-order').first()
            sec.order = (last.order + 1) if last else 0
            sec.save()
            return redirect('quill:detail', slug=doc.slug)
    else:
        form = SectionForm(document=doc, initial={'level': 1})
    return render(request, 'quill/section_edit.html', {
        'document': doc,
        'form': form,
        'mode': 'add',
    })


@login_required
def section_edit(request, slug, pk):
    doc = get_object_or_404(Document, slug=slug)
    sec = get_object_or_404(Section, pk=pk, document=doc)
    if request.method == 'POST':
        form = SectionForm(request.POST, instance=sec, document=doc)
        if form.is_valid():
            form.save()
            return redirect('quill:detail', slug=doc.slug)
    else:
        form = SectionForm(instance=sec, document=doc)
    return render(request, 'quill/section_edit.html', {
        'document': doc,
        'section': sec,
        'form': form,
        'mode': 'edit',
    })


@login_required
@require_POST
def section_delete(request, slug, pk):
    doc = get_object_or_404(Document, slug=slug)
    sec = get_object_or_404(Section, pk=pk, document=doc)
    sec.delete()
    messages.success(request, 'Section deleted.')
    return redirect('quill:detail', slug=doc.slug)


@login_required
def style_add(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    if request.method == 'POST':
        form = StyleForm(request.POST)
        if form.is_valid():
            style = form.save(commit=False)
            style.document = doc
            style.save()
            messages.success(request, f'Added style "{style.name}".')
            return redirect('quill:detail', slug=doc.slug)
    else:
        form = StyleForm()
    return render(request, 'quill/style_edit.html', {
        'document': doc,
        'form': form,
    })

"""Quill views — paged WYSIWYG editor with multilingual support.

The detail page IS the editor: every section is a contenteditable
block on a "page" surface, autosaving on blur. A language toolbar
above the page lets the writer switch script + direction mid-flow,
Mellel-style — clicked-language inserts a `<span lang="..." dir="...">`
at the cursor and following keystrokes flow into it.

Configure-languages page picks which languages from the global
registry appear in the toolbar (and in what order, with hotkeys
Cmd/Ctrl+1..9 mapped to the first nine).
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import NewDocumentForm, SectionForm, StyleForm
from .models import Document, DocumentLanguage, Language, Section, Style


# ─── Default starter language set ────────────────────────────────────
# These are the slugs auto-enabled on a new document — a sensible
# starting palette for a Buddhist studies / general philological user.
# Users tune the list via /quill/<slug>/languages/.
DEFAULT_DOCUMENT_LANGUAGES = ['en', 'nl', 'sa', 'bo', 'zh-hans']


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
            # Default primary language — English if seeded, else first
            # available, else None (and the editor renders as plain LTR).
            doc.primary_language = (
                Language.objects.filter(slug='en').first()
                or Language.objects.first()
            )
            doc.save()

            # Seed the document with reasonable default styles + an
            # introduction section so the editor opens non-blank.
            Style.objects.create(
                document=doc, name='Body', kind='paragraph',
                css_rules={
                    'font_size': '12pt',
                    'line_height': '1.65',
                },
            )
            Style.objects.create(
                document=doc, name='Heading 1', kind='paragraph',
                css_rules={
                    'font_size': '20pt',
                    'font_weight': '600',
                    'margin_top': '1em',
                    'margin_bottom': '0.4em',
                },
            )
            Style.objects.create(
                document=doc, name='Quote', kind='paragraph',
                css_rules={
                    'font_size': '11pt',
                    'font_style': 'italic',
                    'margin_left': '2em',
                    'margin_right': '2em',
                    'color': '#3a3a3a',
                },
            )

            # Auto-enable a starter palette of languages.
            for i, slug in enumerate(DEFAULT_DOCUMENT_LANGUAGES):
                lang = Language.objects.filter(slug=slug).first()
                if lang:
                    DocumentLanguage.objects.create(
                        document=doc, language=lang, order=i,
                    )

            Section.objects.create(
                document=doc, order=0, level=1,
                title='Introduction', body='',
                primary_language=doc.primary_language,
                paragraph_direction=(
                    doc.primary_language.direction if doc.primary_language else 'ltr'
                ),
            )
            messages.success(request, f'Created "{doc.title}".')
            return redirect('quill:detail', slug=doc.slug)
    else:
        form = NewDocumentForm()
    return render(request, 'quill/new.html', {'form': form})


@login_required
def detail(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    enabled_langs = list(
        DocumentLanguage.objects
        .filter(document=doc)
        .select_related('language')
        .order_by('order', 'pk')
    )
    return render(request, 'quill/detail.html', {
        'document': doc,
        'sections': doc.sections.all().select_related('style', 'primary_language'),
        'styles': doc.styles.all(),
        'enabled_langs': enabled_langs,  # list of DocumentLanguage rows
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
            last = doc.root_sections().order_by('-order').first()
            sec.order = (last.order + 1) if last else 0
            if sec.primary_language is None:
                sec.primary_language = doc.primary_language
            if not sec.paragraph_direction or sec.paragraph_direction == 'ltr':
                sec.paragraph_direction = (
                    sec.primary_language.direction if sec.primary_language else 'ltr'
                )
            sec.save()
            return redirect('quill:detail', slug=doc.slug)
    else:
        form = SectionForm(document=doc, initial={
            'level': 1,
            'primary_language': doc.primary_language,
            'paragraph_direction': (
                doc.primary_language.direction if doc.primary_language else 'ltr'
            ),
        })
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
@require_POST
def api_section_save(request, slug, pk):
    """Autosave a section's body (and optionally title) from the
    paged editor. Returns ok/err JSON; the editor uses the response
    to flash a 'saved' indicator."""
    doc = get_object_or_404(Document, slug=slug)
    sec = get_object_or_404(Section, pk=pk, document=doc)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'invalid json'}, status=400)

    if 'body' in payload:
        sec.body = str(payload['body'])
    if 'title' in payload:
        sec.title = str(payload['title'])[:300]
    if 'paragraph_direction' in payload:
        d = str(payload['paragraph_direction'])
        if d in ('ltr', 'rtl', 'auto'):
            sec.paragraph_direction = d
    sec.save()
    doc.save(update_fields=['updated_at'])
    return JsonResponse({
        'ok': True,
        'pk': sec.pk,
        'updated_at': doc.updated_at.isoformat(),
    })


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


@login_required
def document_languages(request, slug):
    """Configure which Languages appear in this document's toolbar,
    and in what order. Mellel-style language palette."""
    doc = get_object_or_404(Document, slug=slug)
    if request.method == 'POST':
        # Two ops: (a) reorder/remove existing, (b) add new.
        # Form fields: lang_<id>_order (number, blank to remove),
        #              add_language (slug),
        #              primary_language (slug).
        existing = {dl.language_id: dl for dl in DocumentLanguage.objects
                    .filter(document=doc)}
        for lang_id, dl in existing.items():
            raw = request.POST.get(f'lang_{lang_id}_order', '').strip()
            if raw == '':
                dl.delete()
                continue
            try:
                dl.order = int(raw)
                dl.save()
            except ValueError:
                pass

        add_slug = request.POST.get('add_language', '').strip()
        if add_slug:
            new_lang = Language.objects.filter(slug=add_slug).first()
            if new_lang and not DocumentLanguage.objects.filter(
                    document=doc, language=new_lang).exists():
                next_order = (
                    DocumentLanguage.objects.filter(document=doc)
                    .order_by('-order').values_list('order', flat=True)
                    .first()
                )
                next_order = (next_order or 0) + 1
                DocumentLanguage.objects.create(
                    document=doc, language=new_lang, order=next_order,
                )

        primary_slug = request.POST.get('primary_language', '').strip()
        if primary_slug:
            new_primary = Language.objects.filter(slug=primary_slug).first()
            if new_primary:
                doc.primary_language = new_primary
                doc.save(update_fields=['primary_language'])

        messages.success(request, 'Languages updated.')
        return redirect('quill:document_languages', slug=doc.slug)

    enabled = list(DocumentLanguage.objects.filter(document=doc)
                   .select_related('language').order_by('order', 'pk'))
    enabled_ids = {dl.language_id for dl in enabled}
    available = Language.objects.exclude(id__in=enabled_ids)
    return render(request, 'quill/languages.html', {
        'document': doc,
        'enabled': enabled,
        'available': available,
        'all_languages': Language.objects.all(),
    })

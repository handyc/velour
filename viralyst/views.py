from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from .models import Corpus, Language, Sample, KIND_CHOICES


def index(request):
    """Landing — corpora list + language list + recent samples.

    Filtering: ?kind=virus|quine|… narrows the sample list. ?lang=<slug>
    narrows by language. Both are query-string-light so the URL is
    bookmarkable."""
    kind = request.GET.get('kind') or ''
    lang_slug = request.GET.get('lang') or ''
    samples = Sample.objects.filter(is_quarantined=False)
    if kind:
        samples = samples.filter(kind=kind)
    if lang_slug:
        samples = samples.filter(language__slug=lang_slug)
    samples = samples.select_related('corpus', 'language')[:200]

    corpora = Corpus.objects.filter(is_quarantined=False).order_by('name')
    languages = Language.objects.all()

    return render(request, 'viralyst/index.html', {
        'corpora':   corpora,
        'languages': languages,
        'samples':   samples,
        'kinds':     KIND_CHOICES,
        'kind':      kind,
        'lang':      lang_slug,
        'total':     Sample.objects.filter(is_quarantined=False).count(),
    })


def corpus_detail(request, slug):
    corpus = get_object_or_404(Corpus, slug=slug, is_quarantined=False)
    samples = corpus.samples.filter(is_quarantined=False).select_related(
        'language').order_by('name')
    return render(request, 'viralyst/corpus_detail.html', {
        'corpus':  corpus,
        'samples': samples,
    })


def language_detail(request, slug):
    language = get_object_or_404(Language, slug=slug)
    samples = language.samples.filter(is_quarantined=False).select_related(
        'corpus').order_by('name')
    return render(request, 'viralyst/language_detail.html', {
        'language': language,
        'samples':  samples,
    })


def sample_detail(request, slug):
    sample = get_object_or_404(
        Sample.objects.select_related('corpus', 'language'),
        slug=slug, is_quarantined=False)
    lines = sample.source_code.splitlines() or ['']
    # Pre-compute (line_number, content, length) so the template stays simple.
    rows = [(i + 1, line, len(line)) for i, line in enumerate(lines)]
    return render(request, 'viralyst/sample_detail.html', {
        'sample': sample,
        'rows':   rows,
    })


def sample_raw(request, slug):
    """Raw source download — text/plain, no chrome."""
    sample = get_object_or_404(Sample, slug=slug, is_quarantined=False)
    return HttpResponse(sample.source_code, content_type='text/plain; charset=utf-8')

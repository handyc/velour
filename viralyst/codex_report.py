"""Daily Codex digest for viralyst."""

from .models import Corpus, Language, Sample


def report() -> dict:
    n_samples = Sample.objects.filter(is_quarantined=False).count()
    n_corpora = Corpus.objects.filter(is_quarantined=False).count()
    n_langs = Language.objects.count()

    by_kind = {}
    for slug, label in Sample.objects.values_list('kind', 'kind').distinct():
        by_kind[slug] = Sample.objects.filter(
            kind=slug, is_quarantined=False).count()
    kind_lines = '\n'.join(
        f'- **{k}**: {v}' for k, v in sorted(by_kind.items())
        if v)

    body = (f'**{n_samples}** samples across **{n_corpora}** corpora, '
            f'**{n_langs}** languages.\n\n')
    if kind_lines:
        body += kind_lines

    return {
        'title':     'Viralyst',
        'sort_hint': 65,
        'body_md':   body,
    }

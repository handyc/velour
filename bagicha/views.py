from django.http import Http404
from django.shortcuts import render

from . import grammar


def index(request):
    try:
        n = max(1, min(12, int(request.GET.get('n', 6))))
    except ValueError:
        n = 6
    sentences = grammar.generate(n)
    return render(request, 'bagicha/index.html', {
        'sentences': sentences,
        'n': n,
        'word_count': len(grammar.WORDS),
    })


def word_detail(request, key):
    word = grammar.WORDS.get(key)
    if not word:
        raise Http404(f"No vocabulary entry for '{key}'.")
    related = []
    if word['pos'] == 'noun':
        cat = word.get('category')
        related = [(k, w) for k, w in grammar.WORDS.items()
                   if w.get('category') == cat and k != key]
    elif word['pos'] == 'adj':
        related = [(k, w) for k, w in grammar.WORDS.items()
                   if w['pos'] == 'adj' and k != key]
    return render(request, 'bagicha/word.html', {
        'key': key,
        'word': word,
        'links': grammar.dictionary_links(word),
        'related': related[:8],
    })


def bibliography(request):
    return render(request, 'bagicha/bibliography.html', {
        'entries': grammar.BIBLIOGRAPHY,
    })


def resources(request):
    return render(request, 'bagicha/resources.html', {
        'links': grammar.LEARNING_LINKS,
    })

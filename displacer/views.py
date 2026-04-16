"""Public views for the Displacement site.

Lean views: filter for `published=True`, hand the queryset to the
template. The chrome (nav + footer + asset paths) is in base.html.
"""

import io
import re

from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import Article, HomeBlock, MediaAsset, Page, SiteSettings, Theme


# --- Helpers --------------------------------------------------------


def _menu_pages():
    return Page.objects.filter(published=True, show_in_menu=True)


def _footer_pages():
    return Page.objects.filter(published=True, show_in_footer=True)


def _ctx(extra=None):
    """Common context: settings, menu, footer."""
    base = {
        'site': SiteSettings.load(),
        'menu_pages': _menu_pages(),
        'footer_pages': _footer_pages(),
    }
    if extra:
        base.update(extra)
    return base


# --- Public views ---------------------------------------------------


def home(request):
    featured = (Article.objects
                .filter(published=True, featured=True)
                .order_by('featured_order', '-published_at')[:6])
    home_blocks = HomeBlock.objects.all()
    return render(request, 'displacer/home.html', _ctx({
        'featured_articles': featured,
        'home_blocks': home_blocks,
    }))


def theme_list(request):
    themes = Theme.objects.filter(published=True)
    return render(request, 'displacer/theme_list.html', _ctx({
        'themes': themes,
    }))


def theme_detail(request, slug):
    theme = get_object_or_404(Theme, slug=slug, published=True)
    articles = (theme.articles.filter(published=True)
                .order_by('-published_at', '-created_at'))
    return render(request, 'displacer/theme_detail.html', _ctx({
        'theme': theme,
        'articles': articles,
    }))


def article_list(request):
    # Honour Article Meta.ordering — display_order carries the
    # curated source order for the first N featured stories; the
    # rest fall back to -zotonic_id (newest on the original site first).
    articles = Article.objects.filter(published=True)
    return render(request, 'displacer/article_list.html', _ctx({
        'articles': articles,
    }))


def article_detail(request, slug):
    article = get_object_or_404(Article, slug=slug, published=True)
    return render(request, 'displacer/article_detail.html', _ctx({
        'article': article,
        'categories': article.categories.all(),
        'themes': article.themes.all(),
    }))


def page_detail(request, slug):
    page = get_object_or_404(Page, slug=slug, published=True)
    return render(request, 'displacer/page_detail.html', _ctx({
        'page': page,
    }))


@staff_member_required
@require_http_methods(['GET', 'POST'])
def verify(request):
    """Staff-only console for the verify_displace management command.

    GET shows the button + a quick inventory. POST runs the command,
    captures stdout, and re-renders with the report inline.
    """
    counts = {
        'articles': Article.objects.exclude(zotonic_id__isnull=True).count(),
        'themes':   Theme.objects.exclude(zotonic_id__isnull=True).count(),
        'pages':    Page.objects.exclude(zotonic_id__isnull=True).count(),
        'assets':   MediaAsset.objects.count(),
    }
    counts['total'] = counts['articles'] + counts['themes'] + counts['pages']

    output = None
    summary = None
    ran = False
    if request.method == 'POST':
        ran = True
        buf = io.StringIO()
        # The command sys.exit(1)s when any page is flagged so it's
        # CI-friendly. Inside a request that would tear down the
        # worker — swallow it and use the captured output instead.
        try:
            call_command('verify_displace',
                         quiet=True, delay=0.1,
                         stdout=buf, stderr=buf)
        except SystemExit:
            pass
        except Exception as e:  # noqa: BLE001 — surface any error in the UI
            buf.write(f'\n[error] {type(e).__name__}: {e}\n')
        output = buf.getvalue()
        m = re.search(r'Verified (\d+): (\d+) ok, (\d+) with issues', output)
        if m:
            summary = {
                'total':  int(m.group(1)),
                'ok':     int(m.group(2)),
                'issues': int(m.group(3)),
            }

    return render(request, 'displacer/verify.html', _ctx({
        'counts':  counts,
        'output':  output,
        'summary': summary,
        'ran':     ran,
    }))


def legacy_zotonic(request, zotonic_id):
    """Redirect a legacy /id/<n>/ URL to the appropriate slug-based URL."""
    for model, urlname in [(Article, 'displacer:article_detail'),
                           (Theme,   'displacer:theme_detail'),
                           (Page,    'displacer:page_detail')]:
        try:
            obj = model.objects.get(zotonic_id=zotonic_id, published=True)
            return redirect(urlname, slug=obj.slug)
        except model.DoesNotExist:
            continue
    raise Http404

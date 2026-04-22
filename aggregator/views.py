from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Article, Feed, Newspaper


@login_required
def index(request):
    feeds = Feed.objects.all().order_by('name')
    recent = (Article.objects
              .select_related('feed')
              .order_by('-published_at', '-fetched_at')[:40])
    issues = Newspaper.objects.filter(user=request.user)[:10]
    return render(request, 'aggregator/index.html', {
        'feeds':   feeds,
        'recent':  recent,
        'issues':  issues,
        'now':     timezone.now(),
    })


@login_required
@require_POST
def feed_add(request):
    name = (request.POST.get('name') or '').strip()
    url = (request.POST.get('url') or '').strip()
    topics = (request.POST.get('topics') or '').strip()
    if not name or not url:
        messages.error(request, 'Name and URL are both required.')
        return redirect('aggregator:index')
    Feed.objects.create(name=name[:120], url=url[:500], topics=topics[:240])
    messages.success(request, f'Added feed "{name}".')
    return redirect('aggregator:index')


@login_required
@require_POST
def feed_toggle(request, pk):
    f = get_object_or_404(Feed, pk=pk)
    f.active = not f.active
    f.save(update_fields=['active'])
    return redirect('aggregator:index')


@login_required
@require_POST
def feed_delete(request, pk):
    f = get_object_or_404(Feed, pk=pk)
    name = f.name
    f.delete()
    messages.success(request, f'Deleted feed "{name}".')
    return redirect('aggregator:index')


@login_required
@require_POST
def fetch_now(request):
    """Pull all active feeds once, then bounce back to the index."""
    total_new = 0
    total_upd = 0
    errors = []
    for f in Feed.objects.filter(active=True):
        new, upd, err = f.fetch_once()
        total_new += new
        total_upd += upd
        if err:
            errors.append(f'{f.name}: {err}')
    msg = f'Fetched {total_new} new / {total_upd} updated articles.'
    if errors:
        messages.warning(request, msg + ' Errors: ' + '; '.join(errors[:3]))
    else:
        messages.success(request, msg)
    return redirect('aggregator:index')


@login_required
@require_POST
def compose(request):
    """Snapshot a fresh newspaper. If ?fetch=1, pulls feeds first."""
    if request.POST.get('fetch') == '1':
        for f in Feed.objects.filter(active=True):
            f.fetch_once()
    try:
        window = max(1, min(168, int(request.POST.get('window_hours') or 24)))
    except (TypeError, ValueError):
        window = 24
    title = (request.POST.get('title') or '').strip() or None
    issue = Newspaper.compose(user=request.user, window_hours=window,
                              title=title)
    if issue.article_count == 0:
        messages.warning(request,
            "No articles in window — try fetching first or widening the window.")
    return redirect('aggregator:issue', slug=issue.slug)


@login_required
def issue(request, slug):
    issue = get_object_or_404(Newspaper, slug=slug, user=request.user)
    items = (issue.items.select_related('article', 'article__feed')
                        .order_by('order'))
    return render(request, 'aggregator/issue.html', {
        'issue': issue,
        'items': items,
    })


@login_required
def issues(request):
    issues = Newspaper.objects.filter(user=request.user)
    return render(request, 'aggregator/issues.html', {'issues': issues})


@login_required
@require_POST
def issue_delete(request, slug):
    issue = get_object_or_404(Newspaper, slug=slug, user=request.user)
    issue.delete()
    messages.success(request, 'Issue deleted.')
    return redirect('aggregator:issues')


@login_required
def articles(request):
    """All scraped articles, paginated. Optional ?feed=<pk> and ?q=<text>."""
    qs = (Article.objects.select_related('feed')
          .order_by('-published_at', '-fetched_at'))
    feed_pk = request.GET.get('feed') or ''
    q = (request.GET.get('q') or '').strip()
    feed = None
    if feed_pk:
        try:
            feed = Feed.objects.get(pk=int(feed_pk))
            qs = qs.filter(feed=feed)
        except (ValueError, Feed.DoesNotExist):
            feed = None
    if q:
        qs = qs.filter(title__icontains=q) | qs.filter(summary__icontains=q)
        qs = qs.distinct()
    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    return render(request, 'aggregator/articles.html', {
        'page':      page,
        'feed':      feed,
        'feeds':     Feed.objects.order_by('name'),
        'q':         q,
        'total':     qs.count(),
    })


@login_required
def article(request, pk):
    art = get_object_or_404(Article.objects.select_related('feed'), pk=pk)
    return render(request, 'aggregator/article.html', {'article': art})

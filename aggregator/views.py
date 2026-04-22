from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import FEED_KIND_CHOICES, Article, Feed, Newspaper


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
def feed_edit(request, pk):
    f = get_object_or_404(Feed, pk=pk)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        url = (request.POST.get('url') or '').strip()
        if not name or not url:
            messages.error(request, 'Name and URL are both required.')
        else:
            f.name = name[:120]
            f.url = url[:500]
            f.topics = (request.POST.get('topics') or '').strip()[:240]
            kind = (request.POST.get('kind') or 'rss').strip()
            if kind in dict(FEED_KIND_CHOICES):
                f.kind = kind
            f.active = request.POST.get('active') == '1'
            f.save()
            messages.success(request, f'Saved feed "{f.name}".')
            return redirect('aggregator:index')
    return render(request, 'aggregator/feed_edit.html', {
        'feed':  f,
        'kinds': FEED_KIND_CHOICES,
        'article_count': f.articles.count(),
    })


@login_required
@require_POST
def feed_fetch(request, pk):
    """Fetch just this one feed — useful after editing the URL or when
    only one source is stale and you don't want to pound every feed."""
    f = get_object_or_404(Feed, pk=pk)
    new, upd, err = f.fetch_once()
    if err:
        messages.warning(request, f'{f.name}: {err}')
    else:
        messages.success(request,
            f'{f.name}: {new} new / {upd} updated.')
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
    """Snapshot a fresh newspaper. If ?fetch=1, pulls feeds first.
    If ?scrape=1, also pulls reader-mode bodies for chosen articles."""
    if request.POST.get('fetch') == '1':
        for f in Feed.objects.filter(active=True):
            f.fetch_once()
    try:
        window = max(1, min(168, int(request.POST.get('window_hours') or 24)))
    except (TypeError, ValueError):
        window = 24
    title = (request.POST.get('title') or '').strip() or None
    scrape = request.POST.get('scrape') == '1'
    issue = Newspaper.compose(user=request.user, window_hours=window,
                              title=title, scrape_bodies=scrape)
    if issue.article_count == 0:
        messages.warning(request,
            "No articles in window — try fetching first or widening the window.")
    return redirect('aggregator:issue', slug=issue.slug)


@login_required
def issue(request, slug):
    issue = get_object_or_404(Newspaper, slug=slug, user=request.user)
    items = (issue.items.select_related('article', 'article__feed')
                        .order_by('order'))
    full = request.GET.get('full') == '1'
    return render(request, 'aggregator/issue.html', {
        'issue': issue,
        'items': items,
        'full':  full,
    })


@login_required
@require_POST
def issue_scrape(request, slug):
    """Fetch reader-mode bodies for every article in this issue that
    doesn't already have one. Caps at 60 to bound request time."""
    issue = get_object_or_404(Newspaper, slug=slug, user=request.user)
    items = (issue.items.select_related('article')
                        .order_by('order')[:60])
    scraped = 0
    failed = 0
    for it in items:
        art = it.article
        if art.body_fetched_at and not art.body_error:
            continue
        ok = art.fetch_content()
        if ok:
            scraped += 1
        else:
            failed += 1
    if scraped or failed:
        messages.success(request,
            f'Scraped {scraped} bodies ({failed} failed).')
    else:
        messages.info(request, 'All bodies already scraped.')
    return redirect('aggregator:issue', slug=issue.slug)


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
        qs = (qs.filter(title__icontains=q)
              | qs.filter(summary__icontains=q)
              | qs.filter(body_text__icontains=q))
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
    if not art.body_fetched_at and not art.body_error:
        art.fetch_content()
    return render(request, 'aggregator/article.html', {'article': art})


@login_required
@require_POST
def article_refetch(request, pk):
    """Force re-extraction of the article body."""
    art = get_object_or_404(Article, pk=pk)
    ok = art.fetch_content()
    if ok:
        messages.success(request, 'Re-extracted article body.')
    else:
        messages.warning(request, f'Re-fetch failed: {art.body_error or "unknown"}')
    return redirect('aggregator:article', pk=pk)

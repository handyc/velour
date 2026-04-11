import os
import platform
from datetime import datetime

from django.shortcuts import get_object_or_404, render

from .models import Article, Section, SiteSettings


def _safe_system_info():
    """Return only publicly-safe system info."""
    return {
        'hostname': platform.node(),
        'os': f'{platform.system()} {platform.release()}',
        'python': platform.python_version(),
        'time': datetime.now().strftime('%I:%M %p'),
        'uptime_days': _uptime_days(),
    }


def _uptime_days():
    try:
        with open('/proc/uptime') as f:
            return int(float(f.read().split()[0]) / 86400)
    except Exception:
        return 0


def landing(request):
    settings = SiteSettings.get()
    featured = Article.objects.filter(is_featured=True, is_published=True).first()
    recent = Article.objects.filter(is_published=True, is_featured=False)[:8]
    sections = Section.objects.filter(visible=True)

    section_articles = {}
    for section in sections:
        arts = Article.objects.filter(section=section, is_published=True)[:4]
        if arts.exists():
            section_articles[section] = arts

    return render(request, 'landingpage/landing.html', {
        'settings': settings,
        'featured': featured,
        'recent': recent,
        'section_articles': section_articles,
        'system_info': _safe_system_info(),
        'now': datetime.now(),
    })


def article_detail(request, pk):
    article = get_object_or_404(Article, pk=pk, is_published=True)
    settings = SiteSettings.get()
    related = Article.objects.filter(
        section=article.section, is_published=True
    ).exclude(pk=pk)[:3]
    return render(request, 'landingpage/article.html', {
        'article': article,
        'settings': settings,
        'related': related,
        'now': datetime.now(),
    })


def section_view(request, slug):
    section = get_object_or_404(Section, slug=slug, visible=True)
    articles = Article.objects.filter(section=section, is_published=True)
    settings = SiteSettings.get()
    return render(request, 'landingpage/section.html', {
        'section': section,
        'articles': articles,
        'settings': settings,
        'now': datetime.now(),
    })

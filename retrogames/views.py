"""retrogames views — browse the catalogue."""

from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from .models import Platform, Game


def index(request):
    platforms = (Platform.objects
                 .annotate(game_count=Count('games'))
                 .order_by('year_release', 'name'))
    return render(request, 'retrogames/index.html', {
        'platforms':  platforms,
        'game_total': Game.objects.count(),
    })


def platform(request, slug):
    plat = get_object_or_404(Platform, slug=slug)
    games = plat.games.order_by('year', 'name')
    return render(request, 'retrogames/platform.html', {
        'platform': plat,
        'games':    games,
    })


def game(request, pid, slug):
    g = get_object_or_404(Game, platform_id=pid, slug=slug)
    return render(request, 'retrogames/game.html', {'game': g})

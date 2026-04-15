from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import gubify as G
from .models import GubiWorld


SORTS = {
    'updated':  '-updated_at',
    'created':  '-created_at',
    'title':    'title',
    '-title':   '-title',
}


@login_required
def index(request):
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'updated')
    order = SORTS.get(sort, '-updated_at')

    worlds = GubiWorld.objects.all()
    if q:
        worlds = worlds.filter(Q(title__icontains=q) | Q(text__icontains=q))
    worlds = worlds.order_by(order)

    return render(request, 'screen_gubi/index.html', {
        'worlds': worlds,
        'q': q,
        'sort': sort,
    })


@login_required
def detail(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    vars_ = world.gubified()
    scene = G.lsystem_scene(vars_)
    return render(request, 'screen_gubi/detail.html', {
        'world': world,
        'shared': vars_['regions']['shared'],
        'scene': scene,
    })


@login_required
def scene_json(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    return JsonResponse(world.scene())


@login_required
def new(request):
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip() or 'Untitled world'
        text = request.POST.get('text') or ''
        world = GubiWorld(title=title, text=text)
        world.save()
        return redirect('screen_gubi:detail', slug=world.slug)
    # blank 80x25 screen (spaces)
    blank = '\n'.join([' ' * 80] * 25)
    return render(request, 'screen_gubi/edit.html', {
        'world': None,
        'text': blank,
        'title': '',
        'is_new': True,
    })


@login_required
def edit(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    if request.method == 'POST':
        world.title = (request.POST.get('title') or world.title).strip() or world.title
        world.text = request.POST.get('text') or ''
        world.save()
        return redirect('screen_gubi:detail', slug=world.slug)
    return render(request, 'screen_gubi/edit.html', {
        'world': world,
        'text': world.text,
        'title': world.title,
        'is_new': False,
    })


@login_required
def delete(request, slug):
    world = get_object_or_404(GubiWorld, slug=slug)
    if request.method == 'POST':
        world.delete()
        return redirect('screen_gubi:index')
    return redirect('screen_gubi:detail', slug=slug)

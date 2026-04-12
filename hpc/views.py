from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import HPCCluster


_TEXT_FIELDS = ('nickname', 'slug', 'hostname', 'ssh_user',
                'institution', 'grant_code', 'description', 'notes')


def _apply_post(cluster, post):
    for f in _TEXT_FIELDS:
        setattr(cluster, f, post.get(f, '').strip())
    cluster.scheduler = post.get('scheduler', 'slurm')
    try:
        cluster.ssh_port = int(post.get('ssh_port', 22))
    except ValueError:
        cluster.ssh_port = 22
    cluster.is_active = bool(post.get('is_active'))


@login_required
def cluster_list(request):
    clusters = HPCCluster.objects.all()
    return render(request, 'hpc/list.html', {
        'clusters': clusters,
        'active_count': clusters.filter(is_active=True).count(),
        'total_count': clusters.count(),
    })


@login_required
def cluster_add(request):
    cluster = HPCCluster()
    if request.method == 'POST':
        _apply_post(cluster, request.POST)
        if not cluster.nickname or not cluster.hostname:
            messages.error(request, 'Nickname and hostname are required.')
        else:
            cluster.save()
            messages.success(request, f'Added cluster "{cluster.nickname}".')
            return redirect('hpc:detail', slug=cluster.slug)
    return render(request, 'hpc/form.html', {
        'cluster': cluster,
        'action': 'Add',
        'scheduler_choices': HPCCluster.SCHEDULER_CHOICES,
    })


@login_required
def cluster_detail(request, slug):
    cluster = get_object_or_404(HPCCluster, slug=slug)
    return render(request, 'hpc/detail.html', {'cluster': cluster})


@login_required
def cluster_edit(request, slug):
    cluster = get_object_or_404(HPCCluster, slug=slug)
    if request.method == 'POST':
        _apply_post(cluster, request.POST)
        if not cluster.nickname or not cluster.hostname:
            messages.error(request, 'Nickname and hostname are required.')
        else:
            cluster.save()
            messages.success(request, f'Updated "{cluster.nickname}".')
            return redirect('hpc:detail', slug=cluster.slug)
    return render(request, 'hpc/form.html', {
        'cluster': cluster,
        'action': 'Edit',
        'scheduler_choices': HPCCluster.SCHEDULER_CHOICES,
    })


@login_required
@require_POST
def cluster_delete(request, slug):
    cluster = get_object_or_404(HPCCluster, slug=slug)
    nickname = cluster.nickname
    cluster.delete()
    messages.success(request, f'Removed "{nickname}".')
    return redirect('hpc:list')

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import HostPoll, RemoteHost
from .polling import poll, record_poll


@login_required
def host_list(request):
    hosts = RemoteHost.objects.all()
    return render(request, 'hosts/list.html', {'hosts': hosts})


@login_required
def host_add(request):
    if request.method == 'POST':
        name  = request.POST.get('name', '').strip()
        url   = request.POST.get('url', '').strip()
        token = request.POST.get('token', '').strip()
        enabled = bool(request.POST.get('enabled'))
        if not name or not url or not token:
            messages.error(request, 'Name, URL, and token are all required.')
        else:
            host = RemoteHost.objects.create(
                name=name, url=url, token=token, enabled=enabled,
            )
            messages.success(request, f'Added {host.name}.')
            return redirect('hosts:list')
    return render(request, 'hosts/form.html', {
        'host': None,
        'action': 'Add',
    })


@login_required
def host_edit(request, pk):
    host = get_object_or_404(RemoteHost, pk=pk)
    if request.method == 'POST':
        host.name  = request.POST.get('name', '').strip()
        host.url   = request.POST.get('url', '').strip()
        new_token  = request.POST.get('token', '').strip()
        if new_token:
            host.token = new_token
        host.enabled = bool(request.POST.get('enabled'))
        if not host.name or not host.url or not host.token:
            messages.error(request, 'Name, URL, and token are all required.')
        else:
            host.save()
            messages.success(request, f'Updated {host.name}.')
            return redirect('hosts:list')
    return render(request, 'hosts/form.html', {
        'host': host,
        'action': 'Edit',
    })


@login_required
@require_POST
def host_delete(request, pk):
    host = get_object_or_404(RemoteHost, pk=pk)
    name = host.name
    host.delete()
    messages.success(request, f'Removed {name}.')
    return redirect('hosts:list')


SPARK_BARS = '▁▂▃▄▅▆▇█'


def _spark(values, width=24):
    """Render a sequence of floats (0..max) as a Unicode sparkline.
    Empty cells render as ` `. Width is the target character count;
    longer inputs are sub-sampled to fit."""
    clean = [v for v in values if v is not None]
    if not clean:
        return ''
    if len(values) > width:
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]
    lo = min(clean)
    hi = max(clean)
    span = (hi - lo) or 1.0
    out = []
    for v in values:
        if v is None:
            out.append(' ')
            continue
        idx = int(((v - lo) / span) * (len(SPARK_BARS) - 1))
        out.append(SPARK_BARS[max(0, min(idx, len(SPARK_BARS) - 1))])
    return ''.join(out)


@login_required
def host_detail(request, pk):
    host = get_object_or_404(RemoteHost, pk=pk)
    polls = list(host.polls.all()[:60])  # most recent first
    spark = polls[::-1]  # chronological for spark rendering
    sparklines = {
        'cpu':  _spark([p.cpu_load for p in spark]),
        'mem':  _spark([p.mem_pct  for p in spark]),
        'disk': _spark([p.disk_pct for p in spark]),
    }
    return render(request, 'hosts/detail.html', {
        'host':       host,
        'polls':      polls[:10],
        'poll_count': host.polls.count(),
        'sparklines': sparklines,
    })


@login_required
@require_POST
def host_refresh(request, pk):
    host = get_object_or_404(RemoteHost, pk=pk)
    poll(host)
    host.save()
    record_poll(host)
    if host.last_error:
        messages.error(request, f'{host.name}: {host.last_error}')
    else:
        messages.success(request, f'Refreshed {host.name}: {host.last_status}.')
    return redirect('hosts:list')


@login_required
@require_POST
def host_refresh_all(request):
    hosts = RemoteHost.objects.filter(enabled=True)
    if not hosts:
        messages.info(request, 'No enabled hosts to refresh.')
        return redirect('hosts:list')
    results = {'green': 0, 'yellow': 0, 'red': 0, 'unreachable': 0}
    for host in hosts:
        poll(host)
        host.save()
        record_poll(host)
        results[host.last_status] = results.get(host.last_status, 0) + 1
    parts = [f'{v} {k}' for k, v in results.items() if v]
    messages.success(request, 'Refreshed all hosts — ' + ', '.join(parts) + '.')
    return redirect('hosts:list')

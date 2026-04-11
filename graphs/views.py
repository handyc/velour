import io
import json
import os
import subprocess
import time
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from fpdf import FPDF

from .models import GraphSnapshot


GRAPH_TYPE_LABELS = {
    'cpu_history': 'CPU Usage (Live Sampled)',
    'memory_history': 'Memory Breakdown',
    'disk_usage': 'Disk Usage by Mount Point',
    'network_io': 'Network I/O by Interface',
    'process_tree': 'Process Tree (3D Network)',
    'load_average': 'Load Average',
    'swap_usage': 'Swap Usage',
    'disk_io': 'Disk I/O by Device',
    'top_processes': 'Top 15 Processes',
    'filesystem_tree': 'Filesystem Usage (Treemap)',
    'user_sessions': 'Active User Sessions',
    'entropy': 'Kernel Entropy Pool',
}


@login_required
def graphs_home(request):
    history = GraphSnapshot.objects.all()[:50]
    return render(request, 'graphs/home.html', {'history': history})


@login_required
def graph_data(request):
    """Return real system data for the requested graph type."""
    graph_type = request.GET.get('type', 'cpu_history')
    data = {}

    if graph_type == 'cpu_history':
        data = _cpu_history()
    elif graph_type == 'memory_history':
        data = _memory_history()
    elif graph_type == 'disk_usage':
        data = _disk_usage()
    elif graph_type == 'network_io':
        data = _network_io()
    elif graph_type == 'process_tree':
        data = _process_tree()
    elif graph_type == 'load_average':
        data = _load_average()
    elif graph_type == 'swap_usage':
        data = _swap_usage()
    elif graph_type == 'disk_io':
        data = _disk_io()
    elif graph_type == 'top_processes':
        data = _top_processes()
    elif graph_type == 'filesystem_tree':
        data = _filesystem_tree()
    elif graph_type == 'user_sessions':
        data = _user_sessions()
    elif graph_type == 'entropy':
        data = _entropy()

    return JsonResponse(data, safe=False)


def _run(cmd, default=''):
    try:
        return subprocess.check_output(cmd, text=True, timeout=5).strip()
    except Exception:
        return default


def _cpu_history():
    """Sample CPU usage over a few seconds to build a mini time series."""
    samples = []
    try:
        for i in range(20):
            with open('/proc/stat') as f:
                line = f.readline()
            parts = line.split()[1:]
            vals = [int(v) for v in parts]
            idle = vals[3]
            total = sum(vals)
            samples.append((total, idle))
            if i < 19:
                time.sleep(0.15)

        labels = []
        values = []
        for i in range(1, len(samples)):
            dt = samples[i][0] - samples[i-1][0]
            di = samples[i][1] - samples[i-1][1]
            usage = round((1 - di / max(dt, 1)) * 100, 1)
            labels.append(f'{i * 150}ms')
            values.append(usage)
        return {'labels': labels, 'values': values, 'ylabel': 'CPU %', 'title': 'CPU Usage (Live Sampled)'}
    except Exception:
        return {'labels': [f'{i}s' for i in range(10)], 'values': [0]*10, 'ylabel': 'CPU %', 'title': 'CPU Usage'}


def _memory_history():
    """Current memory breakdown."""
    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            if ':' in line:
                k, v = line.split(':', 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get('MemTotal', 0)
        free = mem.get('MemFree', 0)
        buffers = mem.get('Buffers', 0)
        cached = mem.get('Cached', 0)
        used = total - free - buffers - cached
        return {
            'labels': ['Used', 'Buffers', 'Cached', 'Free'],
            'values': [round(used/1024), round(buffers/1024), round(cached/1024), round(free/1024)],
            'ylabel': 'MB',
            'title': 'Memory Breakdown',
        }
    except Exception:
        return {'labels': ['N/A'], 'values': [0], 'ylabel': 'MB', 'title': 'Memory'}


def _disk_usage():
    """Disk usage per mount point."""
    raw = _run(['df', '-h', '--output=target,size,used,avail,pcent'])
    lines = raw.splitlines()[1:]
    labels, used_vals, avail_vals = [], [], []
    for line in lines:
        parts = line.split()
        if len(parts) >= 4:
            mount = parts[0]
            if mount.startswith('/') and not mount.startswith('/snap'):
                labels.append(mount)
                used_str = parts[2].replace('G','').replace('M','').replace('K','').replace('T','')
                avail_str = parts[3].replace('G','').replace('M','').replace('K','').replace('T','')
                try:
                    used_vals.append(float(used_str))
                    avail_vals.append(float(avail_str))
                except ValueError:
                    used_vals.append(0)
                    avail_vals.append(0)
    return {
        'labels': labels,
        'datasets': [
            {'label': 'Used', 'values': used_vals},
            {'label': 'Available', 'values': avail_vals},
        ],
        'ylabel': 'Size',
        'title': 'Disk Usage by Mount Point',
    }


def _network_io():
    """Network bytes in/out per interface."""
    labels, rx_vals, tx_vals = [], [], []
    try:
        with open('/proc/net/dev') as f:
            lines = f.readlines()[2:]
        for line in lines:
            parts = line.split()
            iface = parts[0].rstrip(':')
            if iface == 'lo':
                continue
            rx = int(parts[1]) / (1024*1024)
            tx = int(parts[9]) / (1024*1024)
            labels.append(iface)
            rx_vals.append(round(rx, 1))
            tx_vals.append(round(tx, 1))
    except Exception:
        pass
    return {
        'labels': labels,
        'datasets': [
            {'label': 'RX (MB)', 'values': rx_vals},
            {'label': 'TX (MB)', 'values': tx_vals},
        ],
        'ylabel': 'MB',
        'title': 'Network I/O by Interface',
    }


def _process_tree():
    """Process tree as a network graph (nodes + links)."""
    nodes = []
    links = []
    try:
        raw = _run(['ps', '-eo', 'pid,ppid,comm', '--no-headers'])
        seen = set()
        entries = []
        for line in raw.splitlines()[:80]:
            parts = line.split(None, 2)
            if len(parts) >= 3:
                pid, ppid, comm = parts[0], parts[1], parts[2][:20]
                entries.append((pid, ppid, comm))
                seen.add(pid)

        for pid, ppid, comm in entries:
            nodes.append({'id': pid, 'label': f'{comm} ({pid})', 'group': comm})
            if ppid in seen:
                links.append({'source': ppid, 'target': pid})
    except Exception:
        nodes = [{'id': '1', 'label': 'init', 'group': 'init'}]

    return {'nodes': nodes, 'links': links, 'title': 'Process Tree (3D Network)'}


def _load_average():
    """Load average history (simulated from current snapshots)."""
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().split()
        l1, l5, l15 = float(parts[0]), float(parts[1]), float(parts[2])
        cores = os.cpu_count() or 1
        return {
            'labels': ['15 min', '10 min', '5 min', '1 min', 'Now'],
            'values': [round(l15, 2), round((l15+l5)/2, 2), round(l5, 2), round((l5+l1)/2, 2), round(l1, 2)],
            'threshold': cores,
            'ylabel': 'Load',
            'title': f'Load Average (cores: {cores})',
        }
    except Exception:
        return {'labels': [], 'values': [], 'ylabel': 'Load', 'title': 'Load Average'}


def _swap_usage():
    """Swap usage breakdown."""
    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            if ':' in line:
                k, v = line.split(':', 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get('SwapTotal', 0)
        free = mem.get('SwapFree', 0)
        cached = mem.get('SwapCached', 0)
        used = total - free
        return {
            'labels': ['Used', 'Cached', 'Free'],
            'values': [round(used/1024), round(cached/1024), round(free/1024)],
            'ylabel': 'MB',
            'title': 'Swap Usage',
        }
    except Exception:
        return {'labels': ['N/A'], 'values': [0], 'ylabel': 'MB', 'title': 'Swap'}


def _disk_io():
    """Disk I/O reads/writes per device."""
    labels, reads, writes = [], [], []
    try:
        with open('/proc/diskstats') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    name = parts[2]
                    if name.startswith('loop') or name.startswith('ram'):
                        continue
                    rd = int(parts[5]) * 512 / (1024*1024)
                    wr = int(parts[9]) * 512 / (1024*1024)
                    if rd > 0 or wr > 0:
                        labels.append(name)
                        reads.append(round(rd, 1))
                        writes.append(round(wr, 1))
    except Exception:
        pass
    return {
        'labels': labels,
        'datasets': [
            {'label': 'Read (MB)', 'values': reads},
            {'label': 'Write (MB)', 'values': writes},
        ],
        'ylabel': 'MB',
        'title': 'Disk I/O by Device',
    }


def _top_processes():
    """Top 15 processes by memory usage."""
    labels, mem_vals, cpu_vals = [], [], []
    try:
        raw = _run(['ps', 'aux', '--sort=-rss'])
        lines = raw.splitlines()[1:16]
        for line in lines:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                comm = parts[10][:25]
                cpu = float(parts[2])
                mem = float(parts[3])
                labels.append(comm)
                cpu_vals.append(cpu)
                mem_vals.append(mem)
    except Exception:
        pass
    return {
        'labels': labels,
        'datasets': [
            {'label': 'Memory %', 'values': mem_vals},
            {'label': 'CPU %', 'values': cpu_vals},
        ],
        'ylabel': '%',
        'title': 'Top 15 Processes (by Memory)',
    }


def _filesystem_tree():
    """Filesystem usage as a treemap."""
    items = []
    try:
        raw = _run(['du', '-d', '1', '-m', '/home'], default='')
        for line in raw.splitlines():
            parts = line.split('\t')
            if len(parts) == 2:
                size = int(parts[0])
                path = parts[1]
                if size > 0:
                    items.append({'path': path, 'size': size})
    except Exception:
        pass
    if not items:
        try:
            raw = _run(['du', '-d', '1', '-m', '/tmp'], default='')
            for line in raw.splitlines():
                parts = line.split('\t')
                if len(parts) == 2:
                    items.append({'path': parts[1], 'size': int(parts[0])})
        except Exception:
            items = [{'path': '/unknown', 'size': 1}]
    return {'items': items, 'title': 'Filesystem Usage (Treemap)'}


def _user_sessions():
    """Logged in users over time (current snapshot)."""
    users = {}
    try:
        raw = _run(['who'])
        for line in raw.splitlines():
            parts = line.split()
            if parts:
                name = parts[0]
                users[name] = users.get(name, 0) + 1
    except Exception:
        pass
    if not users:
        users = {os.environ.get('USER', 'unknown'): 1}
    return {
        'labels': list(users.keys()),
        'values': list(users.values()),
        'ylabel': 'Sessions',
        'title': 'Active User Sessions',
    }


def _entropy():
    """Available entropy (randomness pool)."""
    samples = []
    try:
        for i in range(20):
            with open('/proc/sys/kernel/random/entropy_avail') as f:
                samples.append(int(f.read().strip()))
            if i < 19:
                time.sleep(0.1)
    except Exception:
        samples = [0] * 20
    return {
        'labels': [f'{i*100}ms' for i in range(len(samples))],
        'values': samples,
        'ylabel': 'Bits',
        'title': 'Kernel Entropy Pool (Live Sampled)',
    }


# --------------- Snapshot save / history / PDF ---------------

def _get_graph_data(graph_type):
    """Get data for a graph type by name."""
    funcs = {
        'cpu_history': _cpu_history,
        'memory_history': _memory_history,
        'disk_usage': _disk_usage,
        'network_io': _network_io,
        'process_tree': _process_tree,
        'load_average': _load_average,
        'swap_usage': _swap_usage,
        'disk_io': _disk_io,
        'top_processes': _top_processes,
        'filesystem_tree': _filesystem_tree,
        'user_sessions': _user_sessions,
        'entropy': _entropy,
    }
    func = funcs.get(graph_type)
    return func() if func else {}


@login_required
@require_POST
def graph_save(request):
    """Save current graph data as a historical snapshot."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    graph_type = body.get('type', '')
    data = body.get('data')

    if not data:
        data = _get_graph_data(graph_type)

    title = data.get('title', GRAPH_TYPE_LABELS.get(graph_type, graph_type))

    snap = GraphSnapshot.objects.create(
        graph_type=graph_type,
        title=title,
        data_json=json.dumps(data),
        created_by=request.user,
    )
    return JsonResponse({'id': snap.id, 'message': f'Snapshot saved: {title}'})


@login_required
def graph_history(request):
    """List all saved snapshots."""
    snapshots = GraphSnapshot.objects.all()[:200]
    return render(request, 'graphs/history.html', {'snapshots': snapshots})


@login_required
def graph_history_detail(request, pk):
    """View a specific historical snapshot."""
    snap = get_object_or_404(GraphSnapshot, pk=pk)
    return render(request, 'graphs/history_detail.html', {'snapshot': snap})


@login_required
def graph_history_data(request, pk):
    """Return JSON data for a historical snapshot (used by the chart renderer)."""
    snap = get_object_or_404(GraphSnapshot, pk=pk)
    return JsonResponse(snap.data, safe=False)


@login_required
def graph_pdf(request):
    """Generate an A4 PDF of the current graph data."""
    graph_type = request.GET.get('type', 'memory_history')

    # If snapshot ID is provided, use that data
    snap_id = request.GET.get('snapshot')
    if snap_id:
        snap = get_object_or_404(GraphSnapshot, pk=snap_id)
        data = snap.data
        timestamp = snap.created_at.strftime('%Y-%m-%d %H:%M:%S')
    else:
        data = _get_graph_data(graph_type)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    title = data.get('title', graph_type)

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Header
    pdf.set_font('Helvetica', 'B', 18)
    pdf.set_text_color(30, 80, 160)
    pdf.cell(0, 12, title, align='C')
    pdf.ln(14)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f'Generated: {timestamp}', align='C')
    pdf.ln(6)
    pdf.cell(0, 6, f'Type: {GRAPH_TYPE_LABELS.get(graph_type, graph_type)}', align='C')
    pdf.ln(12)

    # Draw separator
    pdf.set_draw_color(200, 200, 200)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(8)

    # Render data as table/text depending on type
    if 'datasets' in data:
        # Multi-series (bar charts)
        _pdf_table_multi(pdf, data)
    elif 'nodes' in data:
        # Network graph - list nodes
        _pdf_node_list(pdf, data)
    elif 'items' in data:
        # Treemap
        _pdf_treemap_table(pdf, data)
    elif 'labels' in data and 'values' in data:
        # Simple label-value (line/pie)
        _pdf_table_simple(pdf, data)

    # ASCII chart for simple value series
    if 'values' in data and 'labels' in data and len(data['values']) > 1:
        pdf.ln(8)
        _pdf_ascii_chart(pdf, data)

    # Footer
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, 'Velour - Graphs Report', align='C')

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    safe_title = title.replace(' ', '_').replace('/', '-')[:40]
    filename = f'graph_{safe_title}_{timestamp[:10]}.pdf'

    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _pdf_table_simple(pdf, data):
    """Render a simple label-value table."""
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(90, 8, 'Label', border=1)
    pdf.cell(80, 8, data.get('ylabel', 'Value'), border=1)
    pdf.ln()

    pdf.set_font('Helvetica', '', 10)
    for label, val in zip(data['labels'], data['values']):
        pdf.cell(90, 7, str(label), border=1)
        pdf.cell(80, 7, str(val), border=1)
        pdf.ln()


def _pdf_table_multi(pdf, data):
    """Render a multi-dataset table."""
    datasets = data.get('datasets', [])
    labels = data.get('labels', [])
    n_cols = len(datasets)

    # Header
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(30, 30, 30)
    label_w = 60
    col_w = min(40, (170 - label_w) // max(n_cols, 1))

    pdf.cell(label_w, 8, 'Label', border=1)
    for ds in datasets:
        pdf.cell(col_w, 8, ds.get('label', '')[:15], border=1)
    pdf.ln()

    pdf.set_font('Helvetica', '', 9)
    for i, label in enumerate(labels):
        pdf.cell(label_w, 6, str(label)[:30], border=1)
        for ds in datasets:
            vals = ds.get('values', [])
            v = vals[i] if i < len(vals) else ''
            pdf.cell(col_w, 6, str(v), border=1)
        pdf.ln()


def _pdf_node_list(pdf, data):
    """Render process tree nodes as a list."""
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(0, 8, f'Nodes: {len(data.get("nodes", []))}  |  Links: {len(data.get("links", []))}')
    pdf.ln(10)

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(30, 7, 'PID', border=1)
    pdf.cell(80, 7, 'Process', border=1)
    pdf.cell(50, 7, 'Group', border=1)
    pdf.ln()

    pdf.set_font('Helvetica', '', 9)
    for node in data.get('nodes', [])[:60]:
        pdf.cell(30, 6, str(node.get('id', '')), border=1)
        pdf.cell(80, 6, str(node.get('label', ''))[:40], border=1)
        pdf.cell(50, 6, str(node.get('group', ''))[:25], border=1)
        pdf.ln()


def _pdf_treemap_table(pdf, data):
    """Render treemap items as a table."""
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(120, 8, 'Path', border=1)
    pdf.cell(40, 8, 'Size (MB)', border=1)
    pdf.ln()

    pdf.set_font('Helvetica', '', 9)
    for item in sorted(data.get('items', []), key=lambda x: -x.get('size', 0)):
        pdf.cell(120, 6, str(item.get('path', ''))[:60], border=1)
        pdf.cell(40, 6, str(item.get('size', '')), border=1)
        pdf.ln()


def _pdf_ascii_chart(pdf, data):
    """Draw a simple ASCII-style bar chart in the PDF."""
    values = data.get('values', [])
    labels = data.get('labels', [])
    if not values:
        return

    max_val = max(values) if values else 1
    if max_val == 0:
        max_val = 1

    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(30, 80, 160)
    pdf.cell(0, 7, 'Chart')
    pdf.ln(8)

    pdf.set_font('Courier', '', 8)
    pdf.set_text_color(30, 30, 30)
    bar_max_w = 80  # chars

    for i, (label, val) in enumerate(zip(labels, values)):
        bar_len = int((val / max_val) * bar_max_w) if max_val > 0 else 0
        bar = '#' * bar_len
        line = f'{str(label):>12s} | {bar} {val}'
        pdf.cell(0, 4, line[:100])
        pdf.ln()

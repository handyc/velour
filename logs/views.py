import io
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from fpdf import FPDF


# Log sources to scan (readable without sudo on most systems)
LOG_SOURCES = [
    {'id': 'syslog', 'name': 'Syslog', 'paths': ['/var/log/syslog', '/var/log/messages']},
    {'id': 'auth', 'name': 'Auth Log', 'paths': ['/var/log/auth.log', '/var/log/secure']},
    {'id': 'kern', 'name': 'Kernel Log', 'paths': ['/var/log/kern.log']},
    {'id': 'dpkg', 'name': 'Package Manager', 'paths': ['/var/log/dpkg.log', '/var/log/yum.log']},
    {'id': 'boot', 'name': 'Boot Log', 'paths': ['/var/log/boot.log']},
    {'id': 'cron', 'name': 'Cron Log', 'paths': ['/var/log/cron.log', '/var/log/cron']},
    {'id': 'nginx_access', 'name': 'Nginx Access', 'paths': ['/var/log/nginx/access.log']},
    {'id': 'nginx_error', 'name': 'Nginx Error', 'paths': ['/var/log/nginx/error.log']},
    {'id': 'supervisor', 'name': 'Supervisor', 'paths': ['/var/log/supervisor/supervisord.log']},
    {'id': 'dmesg', 'name': 'Dmesg (Kernel Ring)', 'paths': ['__dmesg__']},
    {'id': 'journalctl', 'name': 'Systemd Journal', 'paths': ['__journalctl__']},
]


def _run(cmd, default=''):
    try:
        return subprocess.check_output(cmd, text=True, timeout=10, stderr=subprocess.STDOUT).strip()
    except Exception:
        return default


def _read_log(source_id, lines=200, grep_filter='', level_filter=''):
    """Read the last N lines from a log source."""
    source = next((s for s in LOG_SOURCES if s['id'] == source_id), None)
    if not source:
        return [], f'Unknown log source: {source_id}'

    raw_lines = []
    source_path = None

    for path in source['paths']:
        if path == '__dmesg__':
            raw = _run(['dmesg', '--time-format=iso', '-T'], default='')
            if not raw:
                raw = _run(['dmesg'], default='')
            raw_lines = raw.splitlines()
            source_path = 'dmesg'
            break
        elif path == '__journalctl__':
            raw = _run(['journalctl', '--no-pager', '-n', str(lines), '--output=short-iso'])
            raw_lines = raw.splitlines()
            source_path = 'journalctl'
            break
        elif os.path.isfile(path):
            try:
                with open(path) as f:
                    all_lines = f.readlines()
                raw_lines = all_lines[-lines:]
                source_path = path
                break
            except PermissionError:
                continue

    if not raw_lines:
        return [], f'No readable log file found for {source["name"]}'

    # Apply grep filter
    if grep_filter:
        try:
            pattern = re.compile(grep_filter, re.IGNORECASE)
            raw_lines = [l for l in raw_lines if pattern.search(l)]
        except re.error:
            raw_lines = [l for l in raw_lines if grep_filter.lower() in l.lower()]

    # Apply level filter
    if level_filter:
        level_map = {
            'error': ['error', 'err', 'crit', 'alert', 'emerg', 'fatal', 'panic'],
            'warning': ['warning', 'warn'],
            'info': ['info', 'notice'],
        }
        keywords = level_map.get(level_filter, [level_filter])
        raw_lines = [l for l in raw_lines if any(kw in l.lower() for kw in keywords)]

    # Classify lines by severity
    result = []
    for line in raw_lines:
        line = line.rstrip('\n')
        lower = line.lower()
        if any(kw in lower for kw in ['error', 'err]', 'crit', 'fatal', 'panic', 'emerg']):
            severity = 'error'
        elif any(kw in lower for kw in ['warn', 'warning']):
            severity = 'warning'
        else:
            severity = 'info'
        result.append({'text': line, 'severity': severity})

    return result, source_path


def _analyze_log(source_id, lines=2000):
    """Analyze a log for visualization data."""
    log_lines, _ = _read_log(source_id, lines=lines)
    if not log_lines:
        return {}

    # Count by severity
    severity_counts = Counter(l['severity'] for l in log_lines)

    # Count by hour (try to parse timestamps)
    hourly = defaultdict(int)
    error_hourly = defaultdict(int)
    for line in log_lines:
        # Try common timestamp formats
        match = re.match(r'(\w{3}\s+\d+\s+\d+:\d+)', line['text'])
        if match:
            try:
                ts = datetime.strptime(f'{datetime.now().year} {match.group(1)}', '%Y %b %d %H:%M')
                hour = ts.strftime('%H:00')
                hourly[hour] += 1
                if line['severity'] == 'error':
                    error_hourly[hour] += 1
                continue
            except ValueError:
                pass
        # ISO format
        match = re.match(r'(\d{4}-\d{2}-\d{2}[T ]\d{2})', line['text'])
        if match:
            hour = match.group(1)[-2:] + ':00'
            hourly[hour] += 1
            if line['severity'] == 'error':
                error_hourly[hour] += 1

    # Top repeated messages (normalize numbers out)
    msg_counter = Counter()
    for line in log_lines:
        # Strip timestamp and normalize numbers
        cleaned = re.sub(r'\d+', 'N', line['text'][20:80] if len(line['text']) > 20 else line['text'])
        msg_counter[cleaned] += 1
    top_messages = msg_counter.most_common(10)

    # Sort hours
    hours = sorted(set(list(hourly.keys()) + list(error_hourly.keys())))

    return {
        'severity': {
            'labels': list(severity_counts.keys()),
            'values': list(severity_counts.values()),
        },
        'hourly': {
            'labels': hours,
            'all': [hourly.get(h, 0) for h in hours],
            'errors': [error_hourly.get(h, 0) for h in hours],
        },
        'top_messages': [{'msg': m[:80], 'count': c} for m, c in top_messages],
        'total_lines': len(log_lines),
    }


@login_required
def logs_home(request):
    # Check which sources are available
    available = []
    for source in LOG_SOURCES:
        readable = False
        for path in source['paths']:
            if path.startswith('__'):
                readable = True
                break
            if os.path.isfile(path):
                try:
                    with open(path) as f:
                        f.read(1)
                    readable = True
                    break
                except PermissionError:
                    pass
        available.append({**source, 'readable': readable})

    return render(request, 'logs/home.html', {'sources': available})


@login_required
def logs_view(request):
    """View log lines with filtering."""
    source_id = request.GET.get('source', 'syslog')
    lines = min(int(request.GET.get('lines', 200)), 5000)
    grep_filter = request.GET.get('grep', '')
    level_filter = request.GET.get('level', '')

    log_lines, source_path = _read_log(source_id, lines=lines,
                                        grep_filter=grep_filter, level_filter=level_filter)

    source_name = next((s['name'] for s in LOG_SOURCES if s['id'] == source_id), source_id)

    error_count = sum(1 for l in log_lines if l['severity'] == 'error')
    warn_count = sum(1 for l in log_lines if l['severity'] == 'warning')
    info_count = sum(1 for l in log_lines if l['severity'] == 'info')

    return render(request, 'logs/view.html', {
        'log_lines': log_lines,
        'source_id': source_id,
        'source_name': source_name,
        'source_path': source_path,
        'lines': lines,
        'grep_filter': grep_filter,
        'level_filter': level_filter,
        'error_count': error_count,
        'warn_count': warn_count,
        'info_count': info_count,
    })


@login_required
def logs_analyze(request):
    """Return analysis data for charts."""
    source_id = request.GET.get('source', 'syslog')
    data = _analyze_log(source_id)
    return JsonResponse(data, safe=False)


@login_required
def logs_viz(request):
    """Visualization page for a log source."""
    source_id = request.GET.get('source', 'syslog')
    source_name = next((s['name'] for s in LOG_SOURCES if s['id'] == source_id), source_id)
    return render(request, 'logs/viz.html', {
        'source_id': source_id,
        'source_name': source_name,
    })


@login_required
def logs_pdf(request):
    """Export log view as A4 PDF."""
    source_id = request.GET.get('source', 'syslog')
    lines = min(int(request.GET.get('lines', 200)), 2000)
    grep_filter = request.GET.get('grep', '')
    level_filter = request.GET.get('level', '')

    log_lines, source_path = _read_log(source_id, lines=lines,
                                        grep_filter=grep_filter, level_filter=level_filter)

    source_name = next((s['name'] for s in LOG_SOURCES if s['id'] == source_id), source_id)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(30, 80, 160)
    pdf.cell(0, 10, f'Log Report: {source_name}', align='C')
    pdf.ln(12)

    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f'Generated: {now}  |  Source: {source_path or "N/A"}  |  Lines: {len(log_lines)}', align='C')
    if grep_filter:
        pdf.ln(5)
        pdf.cell(0, 5, f'Filter: "{grep_filter}"', align='C')
    if level_filter:
        pdf.ln(5)
        pdf.cell(0, 5, f'Level: {level_filter}', align='C')
    pdf.ln(8)

    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # Summary stats
    error_count = sum(1 for l in log_lines if l['severity'] == 'error')
    warn_count = sum(1 for l in log_lines if l['severity'] == 'warning')
    info_count = sum(1 for l in log_lines if l['severity'] == 'info')

    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 6, f'Summary:  Errors: {error_count}  |  Warnings: {warn_count}  |  Info: {info_count}')
    pdf.ln(8)

    # Log lines
    pdf.set_font('Courier', '', 6)
    for line in log_lines:
        if line['severity'] == 'error':
            pdf.set_text_color(200, 40, 40)
        elif line['severity'] == 'warning':
            pdf.set_text_color(180, 130, 0)
        else:
            pdf.set_text_color(40, 40, 40)

        # Truncate long lines for PDF
        text = line['text'][:150]
        # Replace non-latin chars
        text = text.encode('latin-1', errors='replace').decode('latin-1')
        pdf.cell(0, 3.5, text)
        pdf.ln()

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    filename = f'log_{source_id}_{now[:10]}.pdf'
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def logs_viz_pdf(request):
    """Export log analysis/visualization as A4 PDF."""
    source_id = request.GET.get('source', 'syslog')
    source_name = next((s['name'] for s in LOG_SOURCES if s['id'] == source_id), source_id)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    data = _analyze_log(source_id)
    if not data:
        return HttpResponse('No data available for this log source.', status=404)

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(30, 80, 160)
    pdf.cell(0, 10, f'Log Analysis: {source_name}', align='C')
    pdf.ln(12)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f'Generated: {now}  |  Total lines analyzed: {data.get("total_lines", 0)}', align='C')
    pdf.ln(10)

    # Severity breakdown
    sev = data.get('severity', {})
    if sev.get('labels'):
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, 'Severity Breakdown')
        pdf.ln(8)
        pdf.set_font('Helvetica', '', 10)
        for label, val in zip(sev['labels'], sev['values']):
            if label == 'error':
                pdf.set_text_color(200, 40, 40)
            elif label == 'warning':
                pdf.set_text_color(180, 130, 0)
            else:
                pdf.set_text_color(60, 60, 60)
            pdf.cell(50, 6, label.capitalize(), border=1)
            pdf.cell(30, 6, str(val), border=1)
            pdf.ln()
        pdf.ln(6)

    # Hourly distribution
    hourly = data.get('hourly', {})
    if hourly.get('labels'):
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, 'Hourly Distribution')
        pdf.ln(8)
        pdf.set_font('Courier', '', 8)
        pdf.set_text_color(30, 30, 30)
        max_val = max(hourly.get('all', [1]))
        if max_val == 0:
            max_val = 1
        for i, hour in enumerate(hourly['labels']):
            count = hourly['all'][i]
            errors = hourly['errors'][i]
            bar_len = int((count / max_val) * 60)
            bar = '#' * bar_len
            line = f'{hour:>5s} | {bar} {count}'
            if errors:
                line += f' ({errors} errors)'
            pdf.cell(0, 4, line[:120])
            pdf.ln()
        pdf.ln(6)

    # Top messages
    top = data.get('top_messages', [])
    if top:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, 'Top Repeated Patterns')
        pdf.ln(8)
        pdf.set_font('Courier', '', 7)
        for item in top:
            pdf.set_text_color(30, 30, 30)
            msg = item['msg'].encode('latin-1', errors='replace').decode('latin-1')
            pdf.cell(0, 4, f'[{item["count"]:>4d}x] {msg[:100]}')
            pdf.ln()

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    filename = f'log_analysis_{source_id}_{now[:10]}.pdf'
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

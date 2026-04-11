import json
import time
from dataclasses import asdict

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render

from .checks import CHECK_REGISTRY, CATEGORIES
from .platform import detect_platform


@login_required
def security_home(request):
    pinfo = detect_platform()
    return render(request, 'security/home.html', {
        'checks': CHECK_REGISTRY,
        'categories': CATEGORIES,
        'platform': pinfo,
    })


@login_required
def security_audit(request):
    """Render the audit page (results load via SSE stream)."""
    pinfo = detect_platform()

    # JSON API: run all checks synchronously and return results
    if request.headers.get('Accept') == 'application/json':
        findings = []
        for check in CHECK_REGISTRY:
            try:
                results = check['fn'](pinfo)
                for f in results:
                    f.setdefault('category', check['category'])
                findings.extend(results)
            except Exception as exc:
                findings.append({
                    'name': f'{check["name"]}: Error',
                    'status': 'unknown',
                    'detail': f'Check failed: {exc}',
                    'severity': 'info',
                    'fix': None,
                    'category': check['category'],
                })

        counts = {'pass': 0, 'fail': 0, 'warn': 0, 'info': 0, 'unknown': 0, 'skip': 0}
        for f in findings:
            counts[f.get('status', 'unknown')] = counts.get(f.get('status', 'unknown'), 0) + 1

        return JsonResponse({
            'findings': findings,
            'summary': counts,
            'platform': asdict(pinfo),
        })

    # HTML: render the page shell — JS will connect to the stream endpoint
    return render(request, 'security/audit.html', {
        'platform': pinfo,
        'categories': CATEGORIES,
        'checks': CHECK_REGISTRY,
    })


@login_required
def security_audit_stream(request):
    """Server-Sent Events endpoint that streams audit progress and results."""

    def event_stream():
        pinfo = detect_platform()
        total = len(CHECK_REGISTRY)
        all_findings = []
        counts = {'pass': 0, 'fail': 0, 'warn': 0, 'info': 0, 'unknown': 0, 'skip': 0}

        # Send platform info
        yield _sse('platform', {
            'platform': asdict(pinfo),
            'total_checks': total,
        })

        for i, check in enumerate(CHECK_REGISTRY):
            # Notify which check is starting
            yield _sse('progress', {
                'index': i,
                'total': total,
                'check_id': check['id'],
                'check_name': check['name'],
                'category': check['category'],
                'percent': round(i / total * 100),
            })

            t0 = time.monotonic()
            try:
                results = check['fn'](pinfo)
                for f in results:
                    f.setdefault('category', check['category'])
            except Exception as exc:
                results = [{
                    'name': f'{check["name"]}: Error',
                    'status': 'unknown',
                    'detail': f'Check failed: {exc}',
                    'severity': 'info',
                    'fix': None,
                    'category': check['category'],
                }]
            elapsed = round(time.monotonic() - t0, 2)

            # Update counts
            for f in results:
                status = f.get('status', 'unknown')
                counts[status] = counts.get(status, 0) + 1

            all_findings.extend(results)

            # Send findings for this check
            yield _sse('findings', {
                'check_id': check['id'],
                'check_name': check['name'],
                'category': check['category'],
                'elapsed': elapsed,
                'findings': results,
                'summary': dict(counts),
                'index': i + 1,
                'total': total,
                'percent': round((i + 1) / total * 100),
            })

        # Send completion event
        yield _sse('complete', {
            'summary': counts,
            'total_findings': len(all_findings),
        })

    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event message."""
    payload = json.dumps(data, default=str)
    return f'event: {event}\ndata: {payload}\n\n'

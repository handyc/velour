from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
@login_required
def index(request):
    """In-browser emulator for the ESP32-S3 hex-CA + ST7735S + GPIO setup.

    All compute (engine, GA, render, GPIO) runs in the browser. The
    Django side just serves the page and static assets. The
    ``ensure_csrf_cookie`` decorator makes the "→ Automaton" export
    button work — without it Django never writes the csrftoken cookie
    on this page (no form), so the JS-side X-CSRFToken header is
    empty and the POST to /automaton/import-from-s3lab/ 403s.
    """
    return render(request, 's3lab/index.html', {})

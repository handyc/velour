from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):
    """In-browser emulator for the ESP32-S3 hex-CA + ST7735S + GPIO setup.

    All compute (engine, GA, render, GPIO) runs in the browser. The
    Django side just serves the page and static assets.
    """
    return render(request, 's3lab/index.html', {})

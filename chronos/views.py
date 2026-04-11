"""Chronos views — world clocks page, prefs editor, sync endpoint."""

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import ClockPrefs, WatchedTimezone


def _all_tz_names():
    """Sorted IANA timezone names from the stdlib zoneinfo database."""
    return sorted(available_timezones())


def _tz_snapshot(tz_name, format_24h, show_seconds):
    """Return a dict describing the current moment in `tz_name` ready
    for template rendering. Falls back to UTC if the name is unknown."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo('UTC')
        tz_name = 'UTC (fallback)'
    now = datetime.now(tz)
    if format_24h:
        time_str = now.strftime('%H:%M:%S' if show_seconds else '%H:%M')
    else:
        time_str = now.strftime('%I:%M:%S %p' if show_seconds else '%I:%M %p').lstrip('0')
    return {
        'tz_name': tz_name,
        'date_str': now.strftime('%a %d %b %Y'),
        'time_str': time_str,
        'iso': now.isoformat(),
        'epoch_ms': int(now.timestamp() * 1000),
        'utc_offset': now.strftime('%z'),
    }


@login_required
def home(request):
    """Wall of clocks: home tz first, then every WatchedTimezone."""
    prefs = ClockPrefs.load()
    home_clock = _tz_snapshot(prefs.home_tz, prefs.format_24h, prefs.show_seconds)
    watched = []
    for w in WatchedTimezone.objects.all():
        snap = _tz_snapshot(w.tz_name, prefs.format_24h, prefs.show_seconds)
        snap['label'] = w.label
        snap['pk'] = w.pk
        snap['notes'] = w.notes
        snap['color'] = w.color
        watched.append(snap)
    return render(request, 'chronos/home.html', {
        'prefs': prefs,
        'home_clock': home_clock,
        'watched': watched,
    })


@login_required
def settings_view(request):
    prefs = ClockPrefs.load()
    if request.method == 'POST':
        tz = request.POST.get('home_tz', '').strip()
        if tz not in available_timezones():
            messages.error(request, f'Unknown timezone: {tz}')
        else:
            prefs.home_tz = tz
            prefs.format_24h = bool(request.POST.get('format_24h'))
            prefs.show_seconds = bool(request.POST.get('show_seconds'))
            try:
                prefs.auto_sync_seconds = max(0, int(request.POST.get('auto_sync_seconds', '600')))
            except ValueError:
                prefs.auto_sync_seconds = 600
            prefs.save()
            messages.success(request, 'Clock preferences saved.')
            return redirect('chronos:home')
    return render(request, 'chronos/settings.html', {
        'prefs': prefs,
        'tz_names': _all_tz_names(),
    })


@login_required
def watched_add(request):
    w = WatchedTimezone()
    if request.method == 'POST':
        w.label = request.POST.get('label', '').strip()
        w.tz_name = request.POST.get('tz_name', '').strip()
        w.notes = request.POST.get('notes', '').strip()
        w.color = request.POST.get('color', '').strip()
        try:
            w.sort_order = int(request.POST.get('sort_order', '0'))
        except ValueError:
            w.sort_order = 0
        if not w.label or w.tz_name not in available_timezones():
            messages.error(request, 'Label is required and timezone must be a valid IANA name.')
        else:
            w.save()
            messages.success(request, f'Added {w.label}.')
            return redirect('chronos:home')
    return render(request, 'chronos/watched_form.html', {
        'watched': w,
        'action': 'Add',
        'tz_names': _all_tz_names(),
    })


@login_required
def watched_edit(request, pk):
    w = get_object_or_404(WatchedTimezone, pk=pk)
    if request.method == 'POST':
        w.label = request.POST.get('label', '').strip()
        w.tz_name = request.POST.get('tz_name', '').strip()
        w.notes = request.POST.get('notes', '').strip()
        w.color = request.POST.get('color', '').strip()
        try:
            w.sort_order = int(request.POST.get('sort_order', '0'))
        except ValueError:
            w.sort_order = 0
        if not w.label or w.tz_name not in available_timezones():
            messages.error(request, 'Label is required and timezone must be a valid IANA name.')
        else:
            w.save()
            messages.success(request, f'Updated {w.label}.')
            return redirect('chronos:home')
    return render(request, 'chronos/watched_form.html', {
        'watched': w,
        'action': 'Edit',
        'tz_names': _all_tz_names(),
    })


@login_required
@require_POST
def watched_delete(request, pk):
    w = get_object_or_404(WatchedTimezone, pk=pk)
    label = w.label
    w.delete()
    messages.success(request, f'Removed {label}.')
    return redirect('chronos:home')


def now_json(request):
    """Server time sync endpoint for the JS clock.

    Public (no login_required) so the topbar partial can call it from
    any page including the login screen. Returns server time in the
    user's home tz so JS doesn't need to do tz math itself.
    """
    prefs = ClockPrefs.load()
    snap = _tz_snapshot(prefs.home_tz, prefs.format_24h, prefs.show_seconds)
    snap['format_24h'] = prefs.format_24h
    snap['show_seconds'] = prefs.show_seconds
    snap['auto_sync_ms'] = prefs.auto_sync_seconds * 1000
    return JsonResponse(snap)

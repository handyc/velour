"""Chronos views — world clocks, prefs editor, sync endpoint, calendar."""

import calendar as pycal
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, available_timezones

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as djtz
from django.views.decorators.http import require_POST

from .models import CalendarEvent, ClockPrefs, WatchedTimezone


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


# --- Calendar views (Phase 2a) -------------------------------------------


def _home_tz():
    return ZoneInfo(ClockPrefs.load().home_tz)


def _events_in_window(start_dt, end_dt):
    """Return events whose [start, end] window overlaps the given range."""
    qs = CalendarEvent.objects.filter(start__lt=end_dt)
    return qs.filter(
        models_q_overlap_end(end_dt)
    ).order_by('start')


def models_q_overlap_end(end_dt):
    from django.db.models import Q
    return Q(end__isnull=True) | Q(end__gte=end_dt - timedelta(days=370))


def _events_for_month(year, month, tz):
    """Return all events that touch any day of the given month, in tz."""
    first_day = date(year, month, 1)
    days_in = pycal.monthrange(year, month)[1]
    last_day = date(year, month, days_in)
    start_dt = datetime.combine(first_day, time.min, tzinfo=tz)
    end_dt = datetime.combine(last_day, time.max, tzinfo=tz)
    qs = CalendarEvent.objects.filter(start__lte=end_dt)
    from django.db.models import Q
    qs = qs.filter(Q(end__isnull=True, start__gte=start_dt) | Q(end__gte=start_dt))
    return list(qs.order_by('start'))


def _events_on_day(target, tz):
    """Return all events that touch `target` (a date) in tz."""
    day_start = datetime.combine(target, time.min, tzinfo=tz)
    day_end = datetime.combine(target, time.max, tzinfo=tz)
    from django.db.models import Q
    qs = CalendarEvent.objects.filter(
        Q(start__lte=day_end) & (Q(end__isnull=True, start__gte=day_start) | Q(end__gte=day_start))
    )
    return list(qs.order_by('start'))


@login_required
def calendar_month(request, year=None, month=None):
    """Month grid: 7 columns (days of week), 5–6 rows of week-cells.

    Each cell shows the day number and any events that touch it. Clicking
    a cell goes to the day-detail view.
    """
    tz = _home_tz()
    today = datetime.now(tz).date()
    if year is None:
        year, month = today.year, today.month
    else:
        year, month = int(year), int(month)

    cal = pycal.Calendar(firstweekday=0)  # Monday-first
    weeks = cal.monthdatescalendar(year, month)

    events = _events_for_month(year, month, tz)
    by_day = {}
    for ev in events:
        ev_start_local = ev.start.astimezone(tz).date()
        ev_end_local = (ev.end.astimezone(tz).date()
                        if ev.end else ev_start_local)
        d = ev_start_local
        while d <= ev_end_local:
            by_day.setdefault(d, []).append(ev)
            d += timedelta(days=1)

    # Build rows for the template — each cell is (date, in_month, events).
    rows = []
    for week in weeks:
        row = []
        for d in week:
            row.append({
                'date': d,
                'in_month': d.month == month,
                'is_today': d == today,
                'events': by_day.get(d, []),
            })
        rows.append(row)

    prev_month = (date(year, month, 1) - timedelta(days=1))
    next_month = (date(year, month, 28) + timedelta(days=10)).replace(day=1)

    return render(request, 'chronos/calendar_month.html', {
        'year': year,
        'month': month,
        'month_name': pycal.month_name[month],
        'rows': rows,
        'prev_year': prev_month.year,
        'prev_month': prev_month.month,
        'next_year': next_month.year,
        'next_month': next_month.month,
        'today': today,
        'event_count': len(events),
    })


@login_required
def calendar_day(request, year, month, day):
    """All events touching a single date, plus quick-add button."""
    tz = _home_tz()
    try:
        target = date(int(year), int(month), int(day))
    except ValueError:
        raise Http404('Bad date')
    events = _events_on_day(target, tz)
    return render(request, 'chronos/calendar_day.html', {
        'date': target,
        'events': events,
        'tz': tz,
    })


_EVENT_TEXT_FIELDS = ('title', 'notes', 'tags', 'color')


def _apply_event_post(ev, post, tz):
    for f in _EVENT_TEXT_FIELDS:
        setattr(ev, f, post.get(f, '').strip())
    ev.all_day = bool(post.get('all_day'))

    start_str = post.get('start', '').strip()
    end_str = post.get('end', '').strip()

    def _parse(s):
        if not s:
            return None
        # Accept HTML datetime-local: "YYYY-MM-DDTHH:MM"
        try:
            naive = datetime.fromisoformat(s)
        except ValueError:
            return None
        if naive.tzinfo is None:
            naive = naive.replace(tzinfo=tz)
        return naive

    parsed_start = _parse(start_str)
    if parsed_start:
        ev.start = parsed_start
    ev.end = _parse(end_str) if end_str else None


@login_required
def event_add(request):
    tz = _home_tz()
    ev = CalendarEvent(start=djtz.now())

    initial_date = request.GET.get('date', '')
    if initial_date and not request.POST:
        try:
            d = date.fromisoformat(initial_date)
            ev.start = datetime.combine(d, time(9, 0), tzinfo=tz)
        except ValueError:
            pass

    if request.method == 'POST':
        _apply_event_post(ev, request.POST, tz)
        if not ev.title:
            messages.error(request, 'Title is required.')
        elif not ev.start:
            messages.error(request, 'Start datetime is required.')
        else:
            ev.save()
            messages.success(request, f'Added "{ev.title}".')
            local = ev.start.astimezone(tz).date()
            return redirect('chronos:calendar_day',
                            year=local.year, month=local.month, day=local.day)
    return render(request, 'chronos/event_form.html', {
        'event': ev, 'action': 'New', 'tz': tz,
    })


@login_required
def event_edit(request, slug):
    tz = _home_tz()
    ev = get_object_or_404(CalendarEvent, slug=slug)
    if request.method == 'POST':
        _apply_event_post(ev, request.POST, tz)
        if not ev.title:
            messages.error(request, 'Title is required.')
        elif not ev.start:
            messages.error(request, 'Start datetime is required.')
        else:
            ev.save()
            messages.success(request, f'Updated "{ev.title}".')
            local = ev.start.astimezone(tz).date()
            return redirect('chronos:calendar_day',
                            year=local.year, month=local.month, day=local.day)
    return render(request, 'chronos/event_form.html', {
        'event': ev, 'action': 'Edit', 'tz': tz,
    })


@login_required
@require_POST
def event_delete(request, slug):
    tz = _home_tz()
    ev = get_object_or_404(CalendarEvent, slug=slug)
    title = ev.title
    local = ev.start.astimezone(tz).date()
    ev.delete()
    messages.success(request, f'Removed "{title}".')
    return redirect('chronos:calendar_day',
                    year=local.year, month=local.month, day=local.day)

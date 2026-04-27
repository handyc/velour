"""Chronos views — world clocks, prefs editor, sync endpoint, calendar."""

import calendar as pycal
import io
import re
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, available_timezones

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as djtz
from django.views.decorators.http import require_POST

from .models import (
    CalendarEvent, ClockPrefs, Measurement, Task, TrackedObject,
    WatchedTimezone,
)
from .planets import mars_snapshots, venus_snapshot


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
        'mars_clocks': mars_snapshots(),
        'venus_clock': venus_snapshot(),
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
            for fld, lo, hi in [('home_lat', -90, 90),
                                ('home_lon', -180, 180),
                                ('home_elev_m', -500, 9000)]:
                raw = request.POST.get(fld)
                if raw not in (None, ''):
                    try:
                        v = float(raw)
                        if lo <= v <= hi:
                            setattr(prefs, fld, v)
                    except ValueError:
                        pass
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


# --- Deep-time browsing (Phase 2d) ----------------------------------------


def _events_in_range(start_dt, end_dt):
    """Return all events whose start falls within the half-open range."""
    return CalendarEvent.objects.filter(
        start__gte=start_dt, start__lt=end_dt,
    ).order_by('start')


@login_required
def calendar_year(request, year):
    """12 mini-month grids on one page."""
    tz = _home_tz()
    year = int(year)
    today = datetime.now(tz).date()

    cal = pycal.Calendar(firstweekday=0)
    months = []
    year_start = datetime(year, 1, 1, tzinfo=tz)
    year_end = datetime(year + 1, 1, 1, tzinfo=tz)
    all_events = list(_events_in_range(year_start, year_end))

    by_day = {}
    for ev in all_events:
        d = ev.start.astimezone(tz).date()
        by_day.setdefault(d, []).append(ev)

    for m in range(1, 13):
        weeks = cal.monthdatescalendar(year, m)
        rows = []
        for week in weeks:
            row = []
            for d in week:
                row.append({
                    'date': d,
                    'in_month': d.month == m,
                    'is_today': d == today,
                    'event_count': len(by_day.get(d, [])),
                })
            rows.append(row)
        months.append({
            'month': m,
            'name': pycal.month_name[m],
            'rows': rows,
        })

    return render(request, 'chronos/calendar_year.html', {
        'year': year,
        'months': months,
        'today': today,
        'event_count': len(all_events),
        'prev_year': year - 1,
        'next_year': year + 1,
        'decade_start': (year // 10) * 10,
    })


@login_required
def calendar_decade(request, decade_start):
    """10 year cells with event counts. decade_start is e.g. 2020."""
    tz = _home_tz()
    decade_start = int(decade_start)
    today = datetime.now(tz).date()
    years = []
    for y in range(decade_start, decade_start + 10):
        s = datetime(y, 1, 1, tzinfo=tz)
        e = datetime(y + 1, 1, 1, tzinfo=tz)
        count = CalendarEvent.objects.filter(start__gte=s, start__lt=e).count()
        years.append({
            'year': y,
            'count': count,
            'is_current': y == today.year,
        })

    return render(request, 'chronos/calendar_decade.html', {
        'decade_start': decade_start,
        'decade_end': decade_start + 9,
        'years': years,
        'prev_decade': decade_start - 10,
        'next_decade': decade_start + 10,
        'century_start': (decade_start // 100) * 100,
    })


@login_required
def calendar_century(request, century_start):
    """10 decade cells with event counts."""
    tz = _home_tz()
    century_start = int(century_start)
    today = datetime.now(tz).date()
    decades = []
    for d in range(century_start, century_start + 100, 10):
        s = datetime(d, 1, 1, tzinfo=tz)
        e = datetime(d + 10, 1, 1, tzinfo=tz)
        count = CalendarEvent.objects.filter(start__gte=s, start__lt=e).count()
        decades.append({
            'decade_start': d,
            'decade_end': d + 9,
            'count': count,
            'is_current': d <= today.year < d + 10,
        })

    return render(request, 'chronos/calendar_century.html', {
        'century_start': century_start,
        'century_end': century_start + 99,
        'decades': decades,
        'prev_century': century_start - 100,
        'next_century': century_start + 100,
        'millennium_start': (century_start // 1000) * 1000,
    })


def _count_in_year_range(y_from, y_until, tz):
    """Count CalendarEvents whose start is in [y_from, y_until). Clamps
    to the datetime year range — events can't physically be stored
    outside [1, 9999] so out-of-range cells show zero. The boundary
    datetimes use UTC so astimezone() in Django's SQLite backend
    doesn't slide year=1 into year=0 via the home-tz offset."""
    y0 = max(y_from, 2)  # leave a year of headroom for UTC shifts
    y1 = min(y_until, 9999)
    if y1 <= y0:
        return 0
    s = datetime(y0, 1, 1, tzinfo=dt_timezone.utc)
    e = datetime(y1, 1, 1, tzinfo=dt_timezone.utc)
    return CalendarEvent.objects.filter(start__gte=s, start__lt=e).count()


@login_required
def calendar_millennium(request, millennium_start):
    """10 century cells. At this scale astronomical events dominate."""
    tz = _home_tz()
    start = int(millennium_start)
    today = datetime.now(tz).date()
    cells = []
    for c in range(start, start + 1000, 100):
        cells.append({
            'label': f'{c}s',
            'count': _count_in_year_range(c, c + 100, tz),
            'is_current': c <= today.year < c + 100,
            'url': reverse('chronos:calendar_century', args=[c]),
        })
    ten_ky_start = (start // 10000) * 10000
    return render(request, 'chronos/calendar_century_grid.html', {
        'scale_name': 'millennium',
        'unit_name': 'century',
        'span_label': f'{start}–{start + 999}',
        'cells': cells,
        'prev_url': reverse('chronos:calendar_millennium',
                            args=[max(0, start - 1000)]),
        'next_url': reverse('chronos:calendar_millennium', args=[start + 1000]),
        'up_url': reverse('chronos:calendar_ten_ky', args=[ten_ky_start]),
        'up_label': '10-millennium',
    })


@login_required
def calendar_ten_ky(request, start):
    """10 millennium cells spanning 10,000 years. Mostly a navigation
    scaffold — only astronomical events carry weight at this scale."""
    tz = _home_tz()
    start = int(start)
    today = datetime.now(tz).date()
    cells = []
    for m in range(start, start + 10000, 1000):
        cells.append({
            'label': f'{m}s',
            'count': _count_in_year_range(m, m + 1000, tz),
            'is_current': m <= today.year < m + 1000,
            'url': reverse('chronos:calendar_millennium', args=[m]),
        })
    hundred_ky_start = (start // 100000) * 100000
    return render(request, 'chronos/calendar_century_grid.html', {
        'scale_name': '10-millennium',
        'unit_name': 'millennium',
        'span_label': f'{start}–{start + 9999}',
        'cells': cells,
        'prev_url': reverse('chronos:calendar_ten_ky',
                            args=[max(0, start - 10000)]),
        'next_url': reverse('chronos:calendar_ten_ky', args=[start + 10000]),
        'up_url': reverse('chronos:calendar_hundred_ky',
                          args=[hundred_ky_start]),
        'up_label': '100-millennium',
    })


@login_required
def calendar_hundred_ky(request, start):
    """10 10-millennium cells spanning 100,000 years. Pure deep-time
    browsing — paleoanthropological scale. Event density is near zero
    without a historical seed layer we don't have; the view exists so
    the navigation ladder reaches human-genus horizons."""
    tz = _home_tz()
    start = int(start)
    today = datetime.now(tz).date()
    cells = []
    for tk in range(start, start + 100000, 10000):
        cells.append({
            'label': f'{tk}–{tk + 9999}',
            'count': _count_in_year_range(tk, tk + 10000, tz),
            'is_current': tk <= today.year < tk + 10000,
            'url': reverse('chronos:calendar_ten_ky', args=[tk]),
        })
    return render(request, 'chronos/calendar_century_grid.html', {
        'scale_name': '100-millennium',
        'unit_name': '10-millennium',
        'span_label': f'{start}–{start + 99999}',
        'cells': cells,
        'prev_url': reverse('chronos:calendar_hundred_ky',
                            args=[max(0, start - 100000)]),
        'next_url': reverse('chronos:calendar_hundred_ky',
                            args=[start + 100000]),
        'up_url': None,
        'up_label': '',
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


@login_required
@require_POST
def resync_calendar(request):
    """Manually re-run seed_holidays + seed_astronomy for the current
    year through +2. Both commands are idempotent. Used by the "Resync"
    button in the calendar toolbar.

    Optional POST params:
      year, month — redirect target (defaults to today's month).
      reset       — '1' to delete existing rows for those sources first.
    """
    today = datetime.now(_home_tz()).date()
    y_from = today.year
    y_to = today.year + 2
    reset = request.POST.get('reset') == '1'

    buf = io.StringIO()
    summary = []
    for cmd in ('seed_holidays', 'seed_astronomy'):
        try:
            call_command(cmd, year_from=y_from, year_to=y_to,
                         reset=reset, stdout=buf, stderr=buf)
            tail = buf.getvalue().rstrip().splitlines()[-1]
            m = re.search(r'Created (\d+), updated (\d+)', tail)
            if m:
                summary.append(f'{cmd}: +{m.group(1)} new, {m.group(2)} updated')
            else:
                summary.append(f'{cmd}: ran')
        except Exception as e:
            messages.error(request, f'{cmd} failed: {type(e).__name__}: {e}')
            break
    else:
        messages.success(
            request,
            f'Resynced {y_from}–{y_to}. ' + ' · '.join(summary),
        )

    try:
        y = int(request.POST.get('year') or today.year)
        m = int(request.POST.get('month') or today.month)
        return redirect('chronos:calendar_month', year=y, month=m)
    except (TypeError, ValueError):
        return redirect('chronos:calendar')


# --- Tasks (Phase 2e) ----------------------------------------------------


def _parse_due(s, tz):
    if not s:
        return None
    try:
        naive = datetime.fromisoformat(s)
    except ValueError:
        return None
    if naive.tzinfo is None:
        naive = naive.replace(tzinfo=tz)
    return naive


def _apply_task_post(task, post, tz):
    task.title = post.get('title', '').strip()
    task.notes = post.get('notes', '').strip()
    task.source_app = post.get('source_app', '').strip()
    task.source_url = post.get('source_url', '').strip()
    task.priority = post.get('priority', Task.PRIORITY_NORMAL)
    if task.priority not in dict(Task.PRIORITY_CHOICES):
        task.priority = Task.PRIORITY_NORMAL
    new_status = post.get('status', task.status or Task.STATUS_OPEN)
    if new_status not in dict(Task.STATUS_CHOICES):
        new_status = Task.STATUS_OPEN
    if new_status != task.status and new_status != Task.STATUS_OPEN:
        task.closed_at = djtz.now()
    elif new_status == Task.STATUS_OPEN:
        task.closed_at = None
    task.status = new_status
    task.due_at = _parse_due(post.get('due_at', '').strip(), tz)


@login_required
def task_list(request):
    """All tasks. Default: open + overdue first, then upcoming, then
    closed at the bottom. Operator can filter via ?status=."""
    show = request.GET.get('status', 'open')
    qs = Task.objects.all()
    if show in dict(Task.STATUS_CHOICES):
        qs = qs.filter(status=show)
    tz = _home_tz()
    now = datetime.now(tz)
    counts = {
        s: Task.objects.filter(status=s).count()
        for s, _ in Task.STATUS_CHOICES
    }
    return render(request, 'chronos/tasks.html', {
        'tasks': list(qs),
        'show': show,
        'now': now,
        'counts': counts,
    })


@login_required
def task_add(request):
    tz = _home_tz()
    task = Task()
    if request.method == 'POST':
        _apply_task_post(task, request.POST, tz)
        if not task.title:
            messages.error(request, 'Title is required.')
        else:
            task.save()
            messages.success(request, f'Added task "{task.title}".')
            return redirect('chronos:task_list')
    return render(request, 'chronos/task_form.html', {
        'task': task, 'action': 'New', 'tz': tz,
    })


@login_required
def task_edit(request, pk):
    tz = _home_tz()
    task = get_object_or_404(Task, pk=pk)
    if request.method == 'POST':
        _apply_task_post(task, request.POST, tz)
        if not task.title:
            messages.error(request, 'Title is required.')
        else:
            task.save()
            messages.success(request, f'Updated "{task.title}".')
            return redirect('chronos:task_list')
    return render(request, 'chronos/task_form.html', {
        'task': task, 'action': 'Edit', 'tz': tz,
    })


@login_required
@require_POST
def task_done(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.status = Task.STATUS_DONE
    task.closed_at = djtz.now()
    task.save(update_fields=['status', 'closed_at', 'updated_at'])
    messages.success(request, f'Marked done: "{task.title}".')
    return redirect(request.POST.get('next') or 'chronos:task_list')


@login_required
@require_POST
def task_reopen(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.status = Task.STATUS_OPEN
    task.closed_at = None
    task.save(update_fields=['status', 'closed_at', 'updated_at'])
    messages.success(request, f'Reopened "{task.title}".')
    return redirect(request.POST.get('next') or 'chronos:task_list')


@login_required
@require_POST
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    title = task.title
    task.delete()
    messages.success(request, f'Deleted "{title}".')
    return redirect('chronos:task_list')


# --- Briefing ------------------------------------------------------------


def _briefing_context(tz):
    """Compose the morning-briefing payload: mood + concerns from
    Identity, today's CalendarEvents, open Tasks (sorted)."""
    now = datetime.now(tz)
    today = now.date()

    identity = {'available': False}
    try:
        from identity.models import Concern, Tick
        tick = Tick.objects.order_by('-at').first()
        if tick:
            age_min = int((djtz.now() - tick.at).total_seconds() / 60)
            identity = {
                'available':  True,
                'mood':       tick.mood,
                'intensity':  tick.mood_intensity,
                'because':    getattr(tick, 'rule_label', '') or '',
                'mood_age':   age_min,
            }
        else:
            identity = {'available': True, 'mood': None}
        identity['concerns'] = list(
            Concern.objects.filter(closed_at=None).order_by('-opened_at')[:5]
        )
        identity['concern_count'] = (
            Concern.objects.filter(closed_at=None).count()
        )
    except Exception:
        pass

    events = _events_on_day(today, tz)
    # Annotate satellite-pass events (source='feed', tags contain
    # 'satellite') with the cloud-cover forecast for the pass window.
    for ev in events:
        if ev.source == 'feed' and 'satellite' in (ev.tags or '') and ev.end:
            ev.pass_weather = pass_weather(ev.start, ev.end)
        else:
            ev.pass_weather = None

    next_visible_pass = _next_clear_sky_pass(now)

    open_tasks = list(Task.objects.filter(status=Task.STATUS_OPEN)[:10])
    overdue = [t for t in open_tasks
               if t.due_at and t.due_at.astimezone(tz).date() < today]
    due_today = [t for t in open_tasks
                 if t.due_at and t.due_at.astimezone(tz).date() == today]
    upcoming = [t for t in open_tasks if t not in overdue
                and t not in due_today]

    environs = _briefing_environs()
    upcoming_transits = _briefing_upcoming_transits(now)

    return {
        'now':         now,
        'today':       today,
        'identity':    identity,
        'events':      events,
        'overdue':     overdue,
        'due_today':   due_today,
        'upcoming':    upcoming,
        'open_count':  Task.objects.filter(status=Task.STATUS_OPEN).count(),
        'environs':    environs,
        'next_visible_pass': next_visible_pass,
        'upcoming_transits': upcoming_transits,
    }


def _briefing_upcoming_transits(now, days=14):
    """Pull next-N-days transits + appulses into a small list for the
    briefing's "Sun/Moon transits ahead" pin. Includes pre-cooked
    photo rating from transit_conditions().
    """
    import re as _re
    horizon = now + timedelta(days=days)
    qs = CalendarEvent.objects.filter(
        source='feed', tradition__slug='sat-transits',
        start__gte=now, start__lte=horizon,
    ).order_by('start')[:5]
    out = []
    for ev in qs:
        tags = ev.tags or ''
        kind = 'transit' if 'kind:transit' in tags else 'appulse'
        body = ('sun' if 'body:sun' in tags
                else 'moon' if 'body:moon' in tags else '')
        m_sep = _re.search(r"sep\s+([\d.]+)'", ev.title)
        m_dur = _re.search(r"·\s+([\d.]+)\s*s\s*$", ev.title)
        m_balt = _re.search(r'altitude at peak:\s*([\d.\-]+)°', ev.notes or '')
        sep = float(m_sep.group(1)) if m_sep else None
        dur = float(m_dur.group(1)) if m_dur else None
        balt = float(m_balt.group(1)) if m_balt else None
        cond = transit_conditions(ev, body=body, kind=kind,
                                  body_alt_deg=balt,
                                  sep_arcmin=sep, duration_s=dur)
        out.append({
            'event': ev, 'kind': kind, 'body': body,
            'sep_arcmin': sep, 'duration_s': dur, 'cond': cond,
        })
    return out


def transit_conditions(event, body, kind, body_alt_deg, sep_arcmin,
                       duration_s):
    """Compose a "go/no-go" view for a satellite transit/appulse.

    Inputs are the parsed fields the per-sat detail page already
    extracts. Returns a dict the template can render directly:

        {'cloud_pct':       float | None,
         'cloud_label':     'clear' | 'partly cloudy' | ... | None,
         'forecast_status': 'covered' | 'pending' | 'past',
         'moon_phase_name': str | None  (lunar transits only),
         'moon_illuminated': float | None  (0..1),
         'body_alt_deg':    float | None,
         'sep_arcmin':      float | None,
         'duration_s':      float | None,
         'photo_rating':    'excellent' | 'good' | 'marginal' | 'poor',
         'rating_score':    0..100,
         'rating_reasons':  list of strings,
         'safety_notes':    list of strings  (solar filter, etc.)}

    Photo rating heuristics (informal):
      * altitude > 30° + clear + central transit  → excellent
      * any of: cloud > 60%, alt < 10°, sep > body radius (appulse) → poor
      * forecast not yet covering the transit  → 'pending' (rating still
        gives a no-weather best-case)
    """
    from .astro_sources.weather import wmo_label  # noqa: F401 — implicit

    now = djtz.now()
    horizon_forecast = now + timedelta(days=5, hours=12)
    cloud_pct = None
    cloud_label = None
    forecast_status = 'past' if event.start < now else 'pending'

    if event.start >= now and event.start <= horizon_forecast:
        wx = pass_weather(event.start, event.end or event.start + timedelta(seconds=60))
        if wx:
            cloud_pct = wx['cloud_pct']
            cloud_label = wx['label']
            forecast_status = 'covered'

    moon_phase_name = None
    moon_illuminated = None
    if body == 'moon':
        # Read the latest solar_system snapshot — Moon's illuminated_frac
        # is roughly stable over a couple of days, so we use the most
        # recent computed value rather than re-running skyfield. For
        # transits more than a few days out this is approximate.
        try:
            from .astro_sources.solar_system import current_state
            from .models import ClockPrefs
            prefs = ClockPrefs.load()
            ss = current_state(prefs.home_lat, prefs.home_lon, prefs.home_elev_m)
            if ss and ss.get('moon'):
                # Better: estimate moon phase at the transit time.
                # For events within ~7 days, the current phase is a
                # reasonable proxy (moon illumination changes ~3.4%/day).
                days_off = (event.start - now).total_seconds() / 86400
                # Synodic month is 29.5 days; phase angle advances
                # 360°/29.5 = 12.2°/day. Skip detailed computation here
                # and just report current.
                moon_phase_name = ss['moon']['phase_name']
                moon_illuminated = ss['moon']['illuminated_frac']
        except Exception:
            pass

    rating_score = 50
    rating_reasons = []

    if kind == 'transit':
        # Centrality bonus
        body_radius_arcmin = (0.266 if body == 'sun' else 0.259) * 60
        if sep_arcmin is not None:
            centrality = max(0.0, 1.0 - sep_arcmin / body_radius_arcmin)
            rating_score += int(centrality * 25)
            if centrality > 0.7:
                rating_reasons.append('near-central transit')
        if duration_s is not None and duration_s > 1.0:
            rating_score += 5
            rating_reasons.append(f'duration {duration_s:.1f} s')
    else:
        rating_score -= 25
        rating_reasons.append('appulse — close miss, not a silhouette')

    if body_alt_deg is not None:
        if body_alt_deg > 30:
            rating_score += 15
            rating_reasons.append(f'body high in sky ({body_alt_deg:.0f}°)')
        elif body_alt_deg < 10:
            rating_score -= 25
            rating_reasons.append(f'body very low ({body_alt_deg:.0f}°)')

    if cloud_pct is not None:
        if cloud_pct < 30:
            rating_score += 15
            rating_reasons.append(f'forecast clear ({cloud_pct:.0f}% cloud)')
        elif cloud_pct < 60:
            rating_reasons.append(f'forecast partly cloudy ({cloud_pct:.0f}%)')
        else:
            rating_score -= 30
            rating_reasons.append(f'forecast cloudy ({cloud_pct:.0f}%)')

    rating_score = max(0, min(100, rating_score))
    if forecast_status == 'pending':
        rating_label = 'pending'
    elif rating_score >= 80:
        rating_label = 'excellent'
    elif rating_score >= 60:
        rating_label = 'good'
    elif rating_score >= 40:
        rating_label = 'marginal'
    else:
        rating_label = 'poor'

    safety_notes = []
    if body == 'sun' and kind == 'transit':
        safety_notes.append(
            'NEVER look directly at the Sun — use a solar filter '
            '(rated optical density 5+) on lens AND viewfinder.'
        )
    if duration_s is not None and duration_s < 1.0 and kind == 'transit':
        safety_notes.append(
            f'Sub-second event ({duration_s:.1f} s) — use burst mode '
            'or video at high frame rate to catch the silhouette.'
        )

    return {
        'cloud_pct':        cloud_pct,
        'cloud_label':      cloud_label,
        'forecast_status':  forecast_status,
        'moon_phase_name':  moon_phase_name,
        'moon_illuminated': moon_illuminated,
        'body_alt_deg':     body_alt_deg,
        'sep_arcmin':       sep_arcmin,
        'duration_s':       duration_s,
        'photo_rating':     rating_label,
        'rating_score':     rating_score,
        'rating_reasons':   rating_reasons,
        'safety_notes':     safety_notes,
    }


def top_viewable_passes(now, days=7, limit=20):
    """Rank the next `days` days of satellite-pass CalendarEvents
    by viewing quality.

    Score = max_alt_deg × duration_s × (100 - cloud_pct) / 100, so a
    higher arc + longer duration + clearer sky scores higher. Returns
    list of dicts:

        [{'event': <CalendarEvent>, 'weather': {...}, 'score': float,
          'max_alt': int, 'duration_s': int, 'when_local': datetime},
         ...]

    Only viewable (cloud<60%, no rain) passes are scored. Pass
    duration and max altitude are extracted from the existing event
    title/notes which refresh_satellites already wrote in a stable
    format ("ISS (ZARYA) pass · max 84°", notes contain "Duration N s").
    """
    import re as _re
    horizon = now + timedelta(days=days)
    qs = CalendarEvent.objects.filter(
        source='feed', tradition__slug='satellites',
        start__gte=now, start__lte=horizon,
    ).order_by('start')

    out = []
    for ev in qs:
        if not ev.end:
            continue
        wx = pass_weather(ev.start, ev.end)
        if not wx or not wx['viewable']:
            continue
        m_alt = _re.search(r'max\s+(\d+)°', ev.title)
        max_alt = int(m_alt.group(1)) if m_alt else 0
        m_dur = _re.search(r'Duration\s+(\d+)\s*s', ev.notes or '')
        duration_s = int(m_dur.group(1)) if m_dur else 0
        score = max_alt * duration_s * (100 - wx['cloud_pct']) / 100
        out.append({
            'event':       ev,
            'weather':     wx,
            'score':       score,
            'max_alt':     max_alt,
            'duration_s':  duration_s,
        })
    out.sort(key=lambda r: -r['score'])
    return out[:limit]


def _next_clear_sky_pass(now):
    """Find the next satellite-pass CalendarEvent in the next 48 h
    where the cloud-cover forecast averages < 60% over the pass.

    48 h is the window that catches "tonight + tomorrow night + the
    morning after"; widen if a future feature needs further-out
    look-aheads (forecast quality drops past ~5 days anyway).

    Returns dict {event, weather} or None.
    """
    horizon = now + timedelta(hours=48)
    qs = CalendarEvent.objects.filter(
        source='feed', tradition__slug='satellites',
        start__gte=now, start__lte=horizon,
    ).order_by('start')
    for ev in qs:
        if not ev.end:
            continue
        wx = pass_weather(ev.start, ev.end)
        if wx and wx.get('viewable'):
            return {'event': ev, 'weather': wx}
    return None


def _briefing_environs():
    """Compose the morning briefing's environs strip — current weather,
    today's UV peak, current air quality band, and any open
    threshold-Concerns from the env_threshold__ family. Cheap reads
    from chronos.Measurement; degrades gracefully when there's no data
    yet (fresh install or sources offline).

    `at__lte=now` everywhere — Open-Meteo ships forecast data along
    with observations, so the latest row is in the future unless we
    constrain.
    """
    from .astro_sources.weather import wmo_label
    from .astro_sources.local_environment import (
        european_aqi_band, uv_band,
    )

    now = djtz.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    def _latest(source, metric):
        return Measurement.objects.filter(
            source=source, metric=metric, at__lte=now,
        ).order_by('-at').first()

    def _today(source, metric):
        # Daily metrics are stamped at local midnight in UTC; for
        # uv_index_max we want today's specifically (not yesterday's).
        return Measurement.objects.filter(
            source=source, metric=metric,
            at__gte=today_start - timedelta(hours=24),
            at__lt=today_end,
        ).order_by('-at').first()

    code = _latest('open-meteo-weather', 'weather_code')
    weather_label, weather_emoji = wmo_label(code.value if code else None)
    temp = _latest('open-meteo-weather', 'temperature_2m')
    cloud = _latest('open-meteo-weather', 'cloud_cover')
    uv_today_max = _today('open-meteo-weather', 'uv_index_max')

    aqi = _latest('open-meteo', 'european_aqi')
    o3 = _latest('open-meteo', 'ozone')

    # Open threshold concerns from Phase 7 (env_threshold__*).
    try:
        from identity.models import Concern
        env_concerns = list(Concern.objects.filter(
            aspect__startswith='env_threshold__', closed_at__isnull=True,
        )[:5])
    except Exception:
        env_concerns = []

    return {
        'available':      bool(code or aqi),
        'weather_label':  weather_label,
        'weather_emoji':  weather_emoji,
        'temp_c':         temp.value if temp else None,
        'cloud_pct':      cloud.value if cloud else None,
        'uv_today_max':   uv_today_max.value if uv_today_max else None,
        'uv_today_band':  uv_band(uv_today_max.value if uv_today_max else None),
        'aqi':            aqi.value if aqi else None,
        'aqi_band':       european_aqi_band(aqi.value if aqi else None),
        'ozone':          o3.value if o3 else None,
        'env_concerns':   env_concerns,
    }


@login_required
def briefing(request):
    """Today's briefing: mood + concerns + calendar + tasks on one page."""
    tz = _home_tz()
    djtz.activate(tz)
    return render(request, 'chronos/briefing.html', _briefing_context(tz))


# --- Sky tracking (Phase 2f) ---------------------------------------------


@login_required
def sky_table(request):
    """Tabular sky view — alt/az + upcoming NEO close approaches.

    Drill-down from the dome at /chronos/sky/table/. Server renders
    the initial snapshot; client polls /chronos/sky.json every 5 s.
    """
    prefs = ClockPrefs.load()
    rows = _sky_snapshot(prefs)
    djtz.activate(_home_tz())
    return render(request, 'chronos/sky.html', {
        'prefs': prefs,
        'rows':  rows,
        'tracked_count': TrackedObject.objects.filter(is_watched=True).count(),
        'neo_approaches': _upcoming_neo_approaches(60),
    })


def _upcoming_neo_approaches(days_ahead):
    """Pull future NEO close-approach CalendarEvents for the sky page.

    Re-parses the structured fields out of the event's notes (which
    refresh_neos writes in a stable format) so the template can render
    proper columns. Returns at most 50 rows.
    """
    horizon = djtz.now() + timedelta(days=days_ahead)
    qs = CalendarEvent.objects.filter(
        source='feed', tradition__slug='neos',
        start__gte=djtz.now(), start__lte=horizon,
    ).order_by('start')[:50]

    rows = []
    for ev in qs:
        meta = _parse_neo_notes(ev.notes)
        rows.append({
            'event':       ev,
            'when':        ev.start,
            'designation': meta.get('designation', ev.title.split(' · ')[0]),
            'dist_ld':     meta.get('dist_ld'),
            'v_km_s':      meta.get('v_km_s'),
            'h':           meta.get('h'),
            'size_label':  meta.get('size_label', ''),
            't_uncertain': meta.get('t_uncertain', ''),
        })
    return rows


_NEO_NOTE_PATTERNS = {
    'designation': re.compile(r'Designation:\s*(\S+(?:\s\S+)?)'),
    'dist_ld':     re.compile(r'=\s*([\d.]+)\s*lunar distances'),
    'v_km_s':      re.compile(r'velocity:\s*([\d.]+)\s*km/s'),
    'h':           re.compile(r'magnitude\s*H\s*=\s*([\d.]+)'),
    'size_label':  re.compile(r'estimated diameter\s*(\S+\s*\S+)\s*\)'),
    't_uncertain': re.compile(r'Time uncertainty\s*\(1σ\):\s*(\S+(?:\s\S+)?)'),
}


def _parse_neo_notes(notes):
    out = {}
    for key, pat in _NEO_NOTE_PATTERNS.items():
        m = pat.search(notes or '')
        if m:
            v = m.group(1).strip()
            if key in ('dist_ld', 'v_km_s', 'h'):
                try:
                    v = float(v)
                except ValueError:
                    continue
            out[key] = v
    return out


@login_required
def sky(request):
    """Sky home — 3D hemisphere view from the observer location.

    The dome is the primary sky view; the structured table lives at
    /chronos/sky/table/. Pulls from /chronos/sky.json?track=1 every
    few seconds — server does the SGP4 work, the client just paints.
    Self-contained scene, not an Aether World.
    """
    prefs = ClockPrefs.load()
    return render(request, 'chronos/sky_dome.html', {
        'prefs': prefs,
    })


@login_required
def space_weather(request):
    """Solar + geomagnetic activity dashboard, fed by NOAA SWPC.

    Reads the Measurement time-series this app already populates via
    refresh_space_weather. Renders headline cards (current value +
    Kp colour band) and per-metric SVG sparklines.
    """
    prefs = ClockPrefs.load()
    djtz.activate(_home_tz())

    def _series(metric, hours):
        cutoff = djtz.now() - timedelta(hours=hours)
        return list(
            Measurement.objects.filter(
                source='noaa-swpc', metric=metric, at__gte=cutoff,
            ).order_by('at')
        )

    def _latest(metric):
        return Measurement.objects.filter(
            source='noaa-swpc', metric=metric,
        ).order_by('-at').first()

    from .astro_sources.space_weather import xray_class, aurora_visible_at

    latest_xray = _latest('xray_flux')
    latest_kp = _latest('kp_index')
    latest_wind = _latest('wind_speed')
    latest_sunspot = _latest('sunspot_number')
    latest_aurora = _latest('aurora_max_pct')

    aurora_oval_summary = (latest_aurora.extra
                           if latest_aurora and latest_aurora.extra else {})
    aurora_visible = aurora_visible_at(prefs.home_lat, aurora_oval_summary)

    return render(request, 'chronos/space_weather.html', {
        'prefs': prefs,
        'kp_now':       latest_kp,
        'wind_now':     latest_wind,
        'xray_now':     latest_xray,
        'xray_class':   xray_class(latest_xray.value) if latest_xray else '',
        'sunspot_now':  latest_sunspot,
        'aurora_now':   latest_aurora,
        'aurora_visible_from_observer': aurora_visible,
        'kp_24h':       _series('kp_index', 24),
        'kp_7d':        _series('kp_index', 24 * 7),
        'wind_24h':     _series('wind_speed', 24),
        'wind_density_24h': _series('wind_density', 24),
        'xray_6h':      _series('xray_flux', 6),
        'sunspot_24mo': _series('sunspot_number', 24 * 30 * 24),
        'aurora_30d_min_lat': _series('aurora_north_min_lat', 24 * 30),
        # Pre-cooked SVG polylines so the template doesn't do math.
        'kp_24h_svg':       _sparkline_polyline(_series('kp_index', 24),
                                                lo=0, hi=9, w=200, h=40),
        'wind_24h_svg':     _sparkline_polyline(_series('wind_speed', 24),
                                                w=200, h=40),
        'xray_6h_svg':      _sparkline_polyline(_series('xray_flux', 6),
                                                log=True, w=200, h=40),
        'sunspot_24mo_svg': _sparkline_polyline(_series('sunspot_number', 24 * 30 * 24),
                                                lo=0, w=200, h=40),
    })


def _sparkline_polyline(samples, lo=None, hi=None, log=False, w=200, h=40, pad=2):
    """Reduce a Measurement list to an SVG polyline `points` string.

    Auto-fits y-range from data if lo/hi not given. With log=True the
    y-axis is log10 of value (clamped at 1e-12 to avoid -inf for X-ray).
    Returns '' if there are fewer than two samples.
    """
    if len(samples) < 2:
        return ''
    import math
    raw_y = [s.value for s in samples]
    if log:
        ys = [math.log10(max(v, 1e-12)) for v in raw_y]
    else:
        ys = list(raw_y)
    y_lo = min(ys) if lo is None else (math.log10(max(lo, 1e-12)) if log else lo)
    y_hi = max(ys) if hi is None else (math.log10(max(hi, 1e-12)) if log else hi)
    if y_hi - y_lo < 1e-9:
        y_hi = y_lo + 1
    plot_h = h - 2 * pad
    plot_w = w - 2 * pad
    n = len(ys)
    pts = []
    for i, y in enumerate(ys):
        x = pad + plot_w * (i / (n - 1))
        py = pad + plot_h * (1 - (y - y_lo) / (y_hi - y_lo))
        pts.append(f'{x:.1f},{py:.1f}')
    return ' '.join(pts)


@login_required
def local_environment(request):
    """Air quality + UV + pollen dashboard, fed by Open-Meteo.

    Same time-series substrate as space_weather (chronos.Measurement),
    same card-and-sparkline layout pattern.
    """
    from .astro_sources.local_environment import (
        european_aqi_band, uv_band, pollen_band,
    )

    prefs = ClockPrefs.load()
    djtz.activate(_home_tz())
    now = djtz.now()

    def _series(metric, hours):
        cutoff = now - timedelta(hours=hours)
        return list(
            Measurement.objects.filter(
                source='open-meteo', metric=metric,
                at__gte=cutoff, at__lte=now,
            ).order_by('at')
        )

    def _latest(metric):
        return Measurement.objects.filter(
            source='open-meteo', metric=metric, at__lte=now,
        ).order_by('-at').first()

    def _next_24h(metric):
        return list(
            Measurement.objects.filter(
                source='open-meteo', metric=metric,
                at__gte=now, at__lte=now + timedelta(hours=24),
            ).order_by('at')
        )

    pollen_metrics = ['alder_pollen', 'birch_pollen', 'grass_pollen',
                      'mugwort_pollen', 'olive_pollen', 'ragweed_pollen']
    pollens = []
    for m in pollen_metrics:
        latest = _latest(m)
        if not latest:
            continue
        pollens.append({
            'metric':     m,
            'name':       m.replace('_pollen', '').title(),
            'value':      latest.value,
            'band':       pollen_band(latest.value),
            'unit':       latest.unit,
            'at':         latest.at,
            'spark':      _sparkline_polyline(_series(m, 24 * 7),
                                              lo=0, w=200, h=40),
        })
    # Sort: highest first so allergens you'd actually feel rise to the top
    pollens.sort(key=lambda p: -p['value'])

    aqi_now = _latest('european_aqi')
    return render(request, 'chronos/local_environment.html', {
        'prefs': prefs,
        'aqi_now':         aqi_now,
        'aqi_band':        european_aqi_band(aqi_now.value if aqi_now else None),
        'pm25_now':        _latest('pm2_5'),
        'pm10_now':        _latest('pm10'),
        'no2_now':         _latest('nitrogen_dioxide'),
        'o3_now':          _latest('ozone'),
        'uv_now':          _latest('uv_index'),
        'uv_band':         uv_band(getattr(_latest('uv_index'), 'value', None)),
        'pollens':         pollens,
        'aqi_24h_svg':     _sparkline_polyline(_series('european_aqi', 24),
                                               lo=0, w=200, h=40),
        'aqi_7d_svg':      _sparkline_polyline(_series('european_aqi', 24 * 7),
                                               lo=0, w=200, h=40),
        'pm25_24h_svg':    _sparkline_polyline(_series('pm2_5', 24),
                                               lo=0, w=200, h=40),
        'pm10_24h_svg':    _sparkline_polyline(_series('pm10', 24),
                                               lo=0, w=200, h=40),
        'no2_24h_svg':     _sparkline_polyline(_series('nitrogen_dioxide', 24),
                                               lo=0, w=200, h=40),
        'o3_24h_svg':      _sparkline_polyline(_series('ozone', 24),
                                               lo=0, w=200, h=40),
        'uv_next24_svg':   _sparkline_polyline(_next_24h('uv_index'),
                                               lo=0, hi=11, w=200, h=40),
    })


@login_required
def weather(request):
    """Weather forecast dashboard — current + 24-h hourly + 7-day daily."""
    from .astro_sources.weather import wmo_label

    prefs = ClockPrefs.load()
    home_tz = _home_tz()
    djtz.activate(home_tz)
    now = djtz.now()
    SOURCE = 'open-meteo-weather'

    def _latest(metric):
        return Measurement.objects.filter(
            source=SOURCE, metric=metric, at__lte=now,
        ).order_by('-at').first()

    def _hourly(metric, hours_ahead=24):
        return list(Measurement.objects.filter(
            source=SOURCE, metric=metric,
            at__gte=now, at__lte=now + timedelta(hours=hours_ahead),
        ).order_by('at'))

    def _past(metric, hours):
        return list(Measurement.objects.filter(
            source=SOURCE, metric=metric,
            at__gte=now - timedelta(hours=hours), at__lte=now,
        ).order_by('at'))

    # 7-day daily forecast: pull each daily metric and align by date.
    daily = {}
    daily_qs = Measurement.objects.filter(
        source=SOURCE, metric__in=[m for m, _ in _DAILY_METRICS_LIST],
        at__gte=now - timedelta(days=1),
        at__lte=now + timedelta(days=8),
    ).order_by('at')
    for m in daily_qs:
        # Use the date_local in extra when available (weather_code_daily
        # carries it), else derive from at + tz offset.
        if m.extra and m.extra.get('date_local'):
            date_key = date.fromisoformat(m.extra['date_local'])
        else:
            date_key = m.at.astimezone(home_tz).date()
        daily.setdefault(date_key, {})[m.metric] = m

    daily_rows = []
    for date_key in sorted(daily.keys()):
        if date_key < now.astimezone(home_tz).date():
            continue
        row = daily[date_key]
        wc = row.get('weather_code_daily')
        wmo = wmo_label(wc.value) if wc else ('—', '')
        sunrise_local = sunset_local = None
        if wc and wc.extra:
            sunrise_local = wc.extra.get('sunrise_local')
            sunset_local  = wc.extra.get('sunset_local')
        daily_rows.append({
            'date': date_key,
            'high': row.get('temperature_2m_max'),
            'low':  row.get('temperature_2m_min'),
            'precip_mm': row.get('precipitation_sum'),
            'sunshine_s': row.get('sunshine_duration'),
            'uv_max': row.get('uv_index_max'),
            'label': wmo[0],
            'emoji': wmo[1],
            'sunrise_local': sunrise_local,
            'sunset_local':  sunset_local,
        })

    # Hourly forecast strip: build a pre-cooked list of (hour, temp, cloud, code, emoji, precip_pct)
    hourly_strip = []
    temps = _hourly('temperature_2m', 24)
    clouds_by_at = {m.at: m.value for m in _hourly('cloud_cover', 24)}
    codes_by_at = {m.at: m.value for m in _hourly('weather_code', 24)}
    pp_by_at = {m.at: m.value for m in _hourly('precipitation_probability', 24)}
    for m in temps:
        wmo = wmo_label(codes_by_at.get(m.at))
        hourly_strip.append({
            'at_local':    m.at.astimezone(home_tz),
            'temp':        m.value,
            'cloud':       clouds_by_at.get(m.at),
            'precip_pct':  pp_by_at.get(m.at),
            'label':       wmo[0],
            'emoji':       wmo[1],
        })

    temp_now = _latest('temperature_2m')
    cloud_now = _latest('cloud_cover')
    code_now = _latest('weather_code')
    wind_now = _latest('wind_speed_10m')
    precip_now = _latest('precipitation')
    humidity_now = _latest('relative_humidity_2m')
    visibility_now = _latest('visibility')
    code_label, code_emoji = wmo_label(code_now.value if code_now else None)

    return render(request, 'chronos/weather.html', {
        'prefs':         prefs,
        'temp_now':      temp_now,
        'cloud_now':     cloud_now,
        'code_now':      code_now,
        'code_label':    code_label,
        'code_emoji':    code_emoji,
        'wind_now':      wind_now,
        'precip_now':    precip_now,
        'humidity_now':  humidity_now,
        'visibility_now': visibility_now,
        'temp_24h_svg':  _sparkline_polyline(_past('temperature_2m', 24)
                                             + _hourly('temperature_2m', 24),
                                             w=200, h=40),
        'cloud_24h_svg': _sparkline_polyline(_hourly('cloud_cover', 24),
                                             lo=0, hi=100, w=200, h=40),
        'precip_24h_svg':_sparkline_polyline(_hourly('precipitation_probability', 24),
                                             lo=0, hi=100, w=200, h=40),
        'wind_24h_svg':  _sparkline_polyline(_past('wind_speed_10m', 12)
                                             + _hourly('wind_speed_10m', 24),
                                             lo=0, w=200, h=40),
        'hourly_strip':  hourly_strip,
        'daily_rows':    daily_rows,
    })


# Local copy of weather.py's DAILY_METRICS list to avoid an import cycle
# when this view is composed before astro_sources is fully imported.
_DAILY_METRICS_LIST = [
    ('temperature_2m_max',     '°C'),
    ('temperature_2m_min',     '°C'),
    ('sunshine_duration',      's'),
    ('precipitation_sum',      'mm'),
    ('uv_index_max',           ''),
    ('weather_code_daily',     ''),
]


@login_required
def sky_digest(request):
    """The next 7 days of viewable satellite passes, ranked.

    The same ranking that compose_pass_digest writes to a Codex
    Manual weekly. This view is the live reading.
    """
    prefs = ClockPrefs.load()
    home_tz = _home_tz()
    djtz.activate(home_tz)
    now = djtz.now()
    rows = top_viewable_passes(now, days=7)
    # Group by local date so the page reads as a multi-night plan.
    from collections import defaultdict
    by_night = defaultdict(list)
    for r in rows:
        local = r['event'].start.astimezone(home_tz)
        # "Pre-dawn" passes belong to the previous evening conceptually;
        # group anything before noon under the previous date.
        night_key = local.date() if local.hour >= 12 else (local - timedelta(days=1)).date()
        by_night[night_key].append({**r, 'when_local': local})
    nights = []
    for date_key in sorted(by_night.keys()):
        nights.append({
            'date': date_key,
            'passes': sorted(by_night[date_key],
                             key=lambda p: p['when_local']),
        })
    return render(request, 'chronos/sky_digest.html', {
        'prefs':  prefs,
        'now':    now,
        'rows':   rows,
        'nights': nights,
        'days':   7,
    })


@login_required
def sky_transits(request):
    """Consolidated overview of upcoming transits across every watched
    satellite, with photo conditions per event.
    """
    import re as _re
    djtz.activate(_home_tz())
    qs = CalendarEvent.objects.filter(
        source='feed', tradition__slug='sat-transits',
        start__gte=djtz.now(),
    ).order_by('start')

    rows = []
    for ev in qs:
        tags = ev.tags or ''
        kind = 'transit' if 'kind:transit' in tags else 'appulse'
        body = ('sun' if 'body:sun' in tags
                else 'moon' if 'body:moon' in tags else '')
        m_sep = _re.search(r"sep\s+([\d.]+)'", ev.title)
        m_dur = _re.search(r"·\s+([\d.]+)\s*s\s*$", ev.title)
        m_balt = _re.search(r'(?:Sun|Moon) altitude at peak:\s*([\d.\-]+)°',
                            ev.notes or '')
        sep = float(m_sep.group(1)) if m_sep else None
        dur = float(m_dur.group(1)) if m_dur else None
        balt = float(m_balt.group(1)) if m_balt else None
        # Pull sat slug from tags
        m_slug = _re.search(r'sat-transit:([\w-]+)', tags)
        sat_slug = m_slug.group(1) if m_slug else ''
        rows.append({
            'event':       ev,
            'kind':        kind,
            'body':        body,
            'sat_slug':    sat_slug,
            'sep_arcmin':  sep,
            'duration_s':  dur,
            'body_alt_deg': balt,
            'cond':        transit_conditions(
                ev, body=body, kind=kind,
                body_alt_deg=balt, sep_arcmin=sep, duration_s=dur,
            ),
        })

    return render(request, 'chronos/sky_transits.html', {
        'rows': rows,
    })


@login_required
def sky_object(request, slug):
    """Per-object detail: facts + next-14-days passes + ground track."""
    obj = get_object_or_404(TrackedObject, slug=slug)
    prefs = ClockPrefs.load()
    djtz.activate(_home_tz())

    ctx = {
        'obj':     obj,
        'prefs':   prefs,
        'tle':     None,
        'altaz':   None,
        'passes':  [],
        'track':   [],
    }

    if obj.kind == TrackedObject.KIND_SATELLITE:
        from .astro_sources.satellites import (
            altaz_now, compute_passes, ground_track,
        )
        tle = obj.elements_json or {}
        ctx['tle'] = tle if tle.get('line1') else None
        if ctx['tle']:
            aa = altaz_now(tle, prefs.home_lat, prefs.home_lon,
                           prefs.home_elev_m)
            if aa:
                alt, az, dist = aa
                ctx['altaz'] = {'alt_deg': alt, 'az_deg': az,
                                'distance_km': dist}
            passes = compute_passes(
                tle, prefs.home_lat, prefs.home_lon, prefs.home_elev_m,
                days=14, visible_only=False,
            )
            for p in passes:
                p['weather'] = pass_weather(p['rise'], p['set'])
            ctx['passes'] = passes
            ctx['track'] = ground_track(tle, minutes=180, step_seconds=30)
            ctx['track_svg_paths'] = _ground_track_svg(ctx['track'])
            # Pull persisted transits + appulses for this sat (emitted
            # weekly by compute_sat_transits) and pre-cook the columns
            # so the template stays clean.
            import re as _re
            transit_qs = CalendarEvent.objects.filter(
                source='feed', tradition__slug='sat-transits',
                tags__contains=f'sat-transit:{obj.slug}',
                start__gte=djtz.now(),
            ).order_by('start')[:20]
            transits_rich = []
            for t in transit_qs:
                tags = t.tags or ''
                kind = 'transit' if 'kind:transit' in tags else 'appulse'
                body = ('sun' if 'body:sun' in tags
                        else 'moon' if 'body:moon' in tags else '')
                m_sep = _re.search(r"sep\s+([\d.]+)'", t.title)
                m_dur = _re.search(r"·\s+([\d.]+)\s*s\s*$", t.title)
                m_balt = _re.search(r'(?:Sun|Moon) altitude at peak:\s*([\d.\-]+)°',
                                    t.notes or '')
                row = {
                    'event':       t,
                    'kind':        kind,
                    'body':        body,
                    'sep_arcmin':  float(m_sep.group(1)) if m_sep else None,
                    'duration_s':  float(m_dur.group(1)) if m_dur else None,
                    'body_alt_deg': float(m_balt.group(1)) if m_balt else None,
                }
                row['cond'] = transit_conditions(
                    t, body=body, kind=kind,
                    body_alt_deg=row['body_alt_deg'],
                    sep_arcmin=row['sep_arcmin'],
                    duration_s=row['duration_s'],
                )
                transits_rich.append(row)
            ctx['transits'] = transits_rich
            if ctx['track']:
                lat0, lon0, _ = ctx['track'][0]
                ctx['track_now_xy'] = (
                    (lon0 + 180) * 2.0,
                    (90 - lat0) * 2.0,
                )
            ctx['observer_xy'] = (
                (prefs.home_lon + 180) * 2.0,
                (90 - prefs.home_lat) * 2.0,
            )

    return render(request, 'chronos/sky_object.html', ctx)


def _ground_track_svg(track):
    """Convert a ground track into a list of SVG-ready polyline strings.

    The track wraps at the international date line (lon -180/+180).
    We split the polyline whenever consecutive points jump > 180° in
    longitude, so the rendered path doesn't zigzag across the map.

    SVG canvas: 720x360 (2 px per degree). Lon -180→+180 maps to
    x 0→720; lat +90→-90 maps to y 0→360 (north on top).
    """
    if not track:
        return []
    paths = []
    cur = []
    prev_lon = None
    for lat, lon, _t in track:
        x = (lon + 180) * 2.0
        y = (90 - lat) * 2.0
        if prev_lon is not None and abs(lon - prev_lon) > 180:
            if len(cur) >= 2:
                paths.append(' '.join(f'{px:.1f},{py:.1f}'
                                      for px, py in cur))
            cur = []
        cur.append((x, y))
        prev_lon = lon
    if len(cur) >= 2:
        paths.append(' '.join(f'{px:.1f},{py:.1f}' for px, py in cur))
    return paths


def sky_json(request):
    """JSON snapshot for the sky table's auto-refresh.

    `track=1` adds per-sat ±10-minute alt/az samples (used by the
    sky dome to draw fading past-trails and bright future-arcs). The
    table view doesn't ask for it because it'd triple the payload.
    """
    prefs = ClockPrefs.load()
    rows = _sky_snapshot(prefs)
    if request.GET.get('track') == '1':
        from .astro_sources.satellites import altaz_track
        for row in rows:
            obj = TrackedObject.objects.filter(slug=row['slug']).first()
            if obj and obj.kind == TrackedObject.KIND_SATELLITE:
                tle = obj.elements_json or {}
                if tle.get('line1'):
                    row['track'] = altaz_track(
                        tle, prefs.home_lat, prefs.home_lon,
                        prefs.home_elev_m,
                        minutes_back=10, minutes_ahead=15,
                        step_seconds=30,
                    )
    payload = {
        'rows':        rows,
        'neos':        _neos_for_dome(),
        'observer':    {
            'lat': prefs.home_lat,
            'lon': prefs.home_lon,
            'elev_m': prefs.home_elev_m,
        },
        'computed_at': djtz.now().isoformat(),
    }
    if request.GET.get('track') == '1':
        from .astro_sources.solar_system import current_state
        payload['solar_system'] = current_state(
            prefs.home_lat, prefs.home_lon, prefs.home_elev_m,
        )
        payload['aurora'] = _aurora_for_dome(prefs)
        payload['weather'] = _weather_for_dome()
        nxt = _next_clear_sky_pass(djtz.now())
        if nxt:
            payload['next_pass'] = {
                'title':       nxt['event'].title,
                'start_iso':   nxt['event'].start.isoformat(),
                'cloud_pct':   nxt['weather']['cloud_pct'],
                'label':       nxt['weather']['label'],
            }
    return JsonResponse(payload)


def pass_weather(start_utc, end_utc):
    """Aggregate the weather forecast over a satellite pass window.

    Pulls hourly cloud_cover and precipitation_probability Measurements
    that fall within (or near) the pass window and averages them.
    Returns None when there's no forecast covering this time (e.g.
    pass is more than 7 days out, or refresh_weather hasn't run yet).

    Result:
        {'cloud_pct': float,
         'precip_pct': float | None,
         'label': 'clear' | 'partly cloudy' | 'mostly cloudy' | 'overcast'
                   (+ ' · rain likely' when precip_pct > 50),
         'viewable': bool — True iff cloud_pct < 60 and rain unlikely}
    """
    SOURCE = 'open-meteo-weather'
    pad = timedelta(minutes=30)
    cloud_qs = Measurement.objects.filter(
        source=SOURCE, metric='cloud_cover',
        at__gte=start_utc - pad, at__lte=end_utc + pad,
    )
    cloud_values = [m.value for m in cloud_qs]
    if not cloud_values:
        return None
    cloud_pct = sum(cloud_values) / len(cloud_values)

    pp_qs = Measurement.objects.filter(
        source=SOURCE, metric='precipitation_probability',
        at__gte=start_utc - pad, at__lte=end_utc + pad,
    )
    pp_values = [m.value for m in pp_qs]
    precip_pct = sum(pp_values) / len(pp_values) if pp_values else None

    if cloud_pct < 30:
        label = 'clear'
    elif cloud_pct < 60:
        label = 'partly cloudy'
    elif cloud_pct < 90:
        label = 'mostly cloudy'
    else:
        label = 'overcast'
    rain_likely = bool(precip_pct and precip_pct > 50)
    if rain_likely:
        label += ' · rain likely'
    return {
        'cloud_pct':  cloud_pct,
        'precip_pct': precip_pct,
        'label':      label,
        'viewable':   cloud_pct < 60 and not rain_likely,
    }


def _weather_for_dome():
    """Latest hourly snapshot for the dome HUD: temp, cloud cover,
    weather code (with emoji), wind. Returns None if no recent data.

    `at__lte=now` is critical — Open-Meteo returns forecast data
    alongside observations, so an unbounded latest() would jump
    forward to whatever the last forecast hour is.
    """
    from .astro_sources.weather import wmo_label
    SOURCE = 'open-meteo-weather'
    now = djtz.now()

    def _latest(metric):
        return Measurement.objects.filter(
            source=SOURCE, metric=metric, at__lte=now,
        ).order_by('-at').first()

    code = _latest('weather_code')
    if not code:
        return None
    label, emoji = wmo_label(code.value)
    temp = _latest('temperature_2m')
    cloud = _latest('cloud_cover')
    wind = _latest('wind_speed_10m')
    return {
        'observed_at':   code.at.isoformat(),
        'weather_label': label,
        'weather_emoji': emoji,
        'temp_c':        temp.value if temp else None,
        'cloud_pct':     cloud.value if cloud else None,
        'wind_km_h':     wind.value if wind else None,
    }


def _aurora_for_dome(prefs):
    """Latest Ovation oval summary, tagged with whether it reaches
    down to the observer's latitude. Returns None if no recent data.
    """
    from .astro_sources.space_weather import aurora_visible_at
    latest = Measurement.objects.filter(
        source='noaa-swpc', metric='aurora_max_pct',
    ).order_by('-at').first()
    if not latest:
        return None
    summary = latest.extra or {}
    north_lats = [v for v in (summary.get('north_boundary_by_lon') or {}).values()
                  if v is not None]
    south_lats = [v for v in (summary.get('south_boundary_by_lon') or {}).values()
                  if v is not None]
    return {
        'observation_time': latest.at.isoformat(),
        'max_intensity_pct': float(latest.value),
        'equatorward_lat_north': min(north_lats) if north_lats else None,
        'equatorward_lat_south': max(south_lats) if south_lats else None,
        'visible_from_observer': aurora_visible_at(prefs.home_lat, summary),
    }


def _neos_for_dome(limit=5):
    """Return the next N upcoming NEO close approaches as a flat list
    for the dome's HUD overlay. Each row is the structured fields the
    template / JS already use, plus an ISO timestamp for client-side
    countdowns.
    """
    horizon = djtz.now() + timedelta(days=60)
    qs = CalendarEvent.objects.filter(
        source='feed', tradition__slug='neos',
        start__gte=djtz.now(), start__lte=horizon,
    ).order_by('start')[:limit]
    out = []
    for ev in qs:
        meta = _parse_neo_notes(ev.notes)
        out.append({
            'designation': meta.get('designation', ''),
            'when_iso':    ev.start.isoformat(),
            'dist_ld':     meta.get('dist_ld'),
            'v_km_s':      meta.get('v_km_s'),
            'h':           meta.get('h'),
            'size_label':  meta.get('size_label', ''),
        })
    return out


def _sky_snapshot(prefs):
    """Compute current alt/az/distance for every watched TrackedObject.

    Returns a list of plain dicts ordered by altitude descending —
    above-horizon objects first, then below-horizon.
    """
    from .astro_sources.satellites import altaz_now

    out = []
    for obj in TrackedObject.objects.filter(is_watched=True):
        row = {
            'slug':        obj.slug,
            'name':        obj.name,
            'kind':        obj.kind,
            'kind_label':  obj.get_kind_display(),
            'designation': obj.designation,
            'magnitude':   obj.magnitude,
            'alt_deg':     None,
            'az_deg':      None,
            'distance_km': None,
            'above_horizon': False,
            'elements_age_h': obj.elements_age_hours,
        }
        if obj.kind == TrackedObject.KIND_SATELLITE:
            tle = obj.elements_json or {}
            if tle.get('line1') and tle.get('line2'):
                aa = altaz_now(tle, prefs.home_lat, prefs.home_lon,
                               prefs.home_elev_m)
                if aa:
                    alt, az, dist = aa
                    row['alt_deg'] = alt
                    row['az_deg'] = az
                    row['distance_km'] = dist
                    row['above_horizon'] = alt > 0
        out.append(row)

    out.sort(key=lambda r: (
        0 if r['above_horizon'] else 1,
        -(r['alt_deg'] if r['alt_deg'] is not None else -999),
    ))
    return out

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

from .models import CalendarEvent, ClockPrefs, Task, WatchedTimezone
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
    open_tasks = list(Task.objects.filter(status=Task.STATUS_OPEN)[:10])
    overdue = [t for t in open_tasks
               if t.due_at and t.due_at.astimezone(tz).date() < today]
    due_today = [t for t in open_tasks
                 if t.due_at and t.due_at.astimezone(tz).date() == today]
    upcoming = [t for t in open_tasks if t not in overdue
                and t not in due_today]

    return {
        'now':         now,
        'today':       today,
        'identity':    identity,
        'events':      events,
        'overdue':     overdue,
        'due_today':   due_today,
        'upcoming':    upcoming,
        'open_count':  Task.objects.filter(status=Task.STATUS_OPEN).count(),
    }


@login_required
def briefing(request):
    """Today's briefing: mood + concerns + calendar + tasks on one page."""
    tz = _home_tz()
    return render(request, 'chronos/briefing.html', _briefing_context(tz))

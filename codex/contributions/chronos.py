"""Chronos contribution — calendar event summary for the period."""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from chronos.models import CalendarEvent
    except ImportError:
        return []

    qs = CalendarEvent.objects.filter(
        start__gte=start_dt, start__lt=end_dt,
    )
    total = qs.count()
    if total == 0:
        return [SectionContribution(
            title='Calendar',
            body=f'No calendar events fell in the period **{start_dt.date()}** to **{end_dt.date()}**.',
        )]

    user_evs = qs.filter(source='user').count()
    holidays = qs.filter(source='holiday').count()
    astro = qs.filter(source='astro').count()

    # Pick out the major events to list (user-scheduled + astronomical
    # events take precedence; holidays are too numerous to enumerate).
    notable = list(qs.filter(source__in=['user', 'astro']).order_by('start')[:10])
    notable_lines = []
    for ev in notable:
        notable_lines.append(f'- {ev.start.date():%d %b}: **{ev.title}**')

    body = f"""During this period the calendar held {total} events: {user_evs} user-scheduled, {holidays} religious / civic holidays, and {astro} astronomical events."""

    if notable_lines:
        body += '\n\nNotable events:\n\n' + '\n'.join(notable_lines)

    return [SectionContribution(
        title='Calendar',
        body=body,
        sidenotes='Holidays and astronomical events come from the chronos seed_holidays and seed_astronomy commands.',
    )]

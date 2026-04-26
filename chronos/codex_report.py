"""Chronos' contribution to the daily app-status manual.

Reports task counts and the next upcoming event."""

from __future__ import annotations

from django.utils import timezone


def report() -> dict:
    from .models import Task

    open_tasks = Task.objects.exclude(status='done').count()
    overdue = Task.objects.exclude(status='done').filter(
        due_at__lt=timezone.now()).count()
    today_done = Task.objects.filter(
        status='done',
        closed_at__date=timezone.localdate()).count()

    lines = [
        f'**Open tasks:** {open_tasks}',
        f'**Overdue:** {overdue}',
        f'**Completed today:** {today_done}',
    ]

    next_due = (Task.objects.exclude(status='done')
                .filter(due_at__isnull=False)
                .order_by('due_at').first())
    if next_due:
        lines.append('')
        lines.append(
            f'Next due: *{next_due.title}* '
            f'({next_due.due_at:%Y-%m-%d %H:%M})')

    return {
        'title':     'Chronos',
        'sort_hint': 20,
        'body_md':   '\n'.join(lines),
    }

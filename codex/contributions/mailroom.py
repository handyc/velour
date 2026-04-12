"""Mailroom contribution — inbound mail volume for the period."""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from mail.models import InboundMessage
    except ImportError:
        return []

    in_period = InboundMessage.objects.filter(
        received_at__gte=start_dt, received_at__lt=end_dt,
    )
    count = in_period.count()
    total = InboundMessage.objects.count()

    if count == 0 and total == 0:
        return []

    body_lines = [
        f'**{count}** inbound messages during this period. **{total}** in the inbox total.',
    ]

    if count > 0:
        # Per-day breakdown for the inline sparkline.
        from collections import OrderedDict
        from datetime import timedelta
        days = (end_dt.date() - start_dt.date()).days + 1
        per_day = OrderedDict()
        for i in range(days):
            d = start_dt.date() + timedelta(days=i)
            per_day[d] = 0
        for msg in in_period:
            d = msg.received_at.date()
            if d in per_day:
                per_day[d] += 1
        spark_data = ','.join(str(v) for v in per_day.values())
        if len(per_day) >= 2:
            body_lines.append('')
            body_lines.append(f'Daily volume: [[spark:{spark_data} | end max bar]]')

    return [SectionContribution(
        title='Inbox',
        body='\n'.join(body_lines),
        sidenotes='The mailroom app polls IMAP accounts. The poll cadence is set by the operator\'s cron schedule.',
    )]

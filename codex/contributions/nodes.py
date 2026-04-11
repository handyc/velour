"""Nodes contribution — fleet status summary."""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from nodes.models import Node, SensorReading
    except ImportError:
        return []

    total = Node.objects.count()
    if total == 0:
        return [SectionContribution(
            title='Fleet',
            body='_No nodes registered. Add some via /nodes/add/._',
        )]

    recent = Node.objects.filter(last_seen_at__gte=start_dt).count()
    silent = total - recent
    readings_in_period = SensorReading.objects.filter(
        received_at__gte=start_dt, received_at__lt=end_dt,
    ).count()

    body_lines = [
        f'The lab fleet has **{total}** nodes registered. **{recent}** reported in during this period; **{silent}** were silent.',
        '',
        f'Total sensor readings received during the period: **{readings_in_period}**.',
    ]

    if silent > 0:
        silent_nodes = list(
            Node.objects.exclude(last_seen_at__gte=start_dt).values_list('nickname', flat=True)[:10]
        )
        if silent_nodes:
            body_lines.append('')
            body_lines.append(f'Silent during this period: {", ".join(silent_nodes)}.')

    return [SectionContribution(
        title='Fleet',
        body='\n'.join(body_lines),
        sidenotes='A node is "silent" if its last_seen_at is older than the start of the report period. Solar nodes that go dark at night are expected to be silent at some times.',
    )]

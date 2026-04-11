"""Attic contribution — media library volume for the period."""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from attic.models import MediaItem
    except ImportError:
        return []

    total = MediaItem.objects.count()
    new = MediaItem.objects.filter(uploaded_at__gte=start_dt, uploaded_at__lt=end_dt).count()
    if total == 0:
        return []

    by_kind = {}
    for k in ('image', 'video', 'audio', 'document', 'other'):
        by_kind[k] = MediaItem.objects.filter(kind=k).count()
    breakdown = '\n'.join(f'{k}: {v}' for k, v in by_kind.items() if v)

    body = f"""**{total}** items in the media library; **{new}** uploaded during this period.

By kind:

:::def
{breakdown}
:::"""

    return [SectionContribution(
        title='Attic',
        body=body,
    )]

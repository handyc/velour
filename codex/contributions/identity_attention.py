"""Identity attention engine contribution — mood intensity sparkline.

The Identity Phase 2 tick engine writes a Mood row each time it fires.
Over a one-week period there should be ~1000 ticks if cron fires it
every 10 minutes. We sample down to 50 points for the sparkline.
"""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from identity.models import Mood
    except ImportError:
        return []

    qs = Mood.objects.filter(
        timestamp__gte=start_dt, timestamp__lt=end_dt,
    ).order_by('timestamp')
    moods = list(qs)
    if not moods:
        return [SectionContribution(
            title='Attention',
            body='_No attention ticks recorded during this period. The Identity tick engine may not be running on a cron schedule yet._',
        )]

    # Down-sample to 50 points for the inline sparkline.
    n = len(moods)
    target = 50
    if n > target:
        step = n // target
        sampled = [moods[i] for i in range(0, n, step)][:target]
    else:
        sampled = moods

    spark_data = ','.join(f'{m.intensity:.2f}' for m in sampled)

    counts = {}
    for m in moods:
        counts[m.mood] = counts.get(m.mood, 0) + 1
    breakdown = '\n'.join(
        f'{name}: {n} tick{"s" if n != 1 else ""}'
        for name, n in sorted(counts.items(), key=lambda x: -x[1])
    )

    body = f"""My attention engine ticked {len(moods)} times during this period. Mood intensity over time: [[spark:{spark_data} | end min max]]

Mood breakdown:

:::def
{breakdown}
:::"""

    return [SectionContribution(
        title='Attention',
        body=body,
        sidenotes='The intensity sparkline shows mood intensity 0-1 over the report period. Min and max markers flag the extremes.',
    )]

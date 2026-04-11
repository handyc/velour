"""Identity's contribution to a periodic report — the byline section."""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from identity.models import Identity
    except ImportError:
        return []

    i = Identity.get_self()
    body_lines = [
        f'> {i.tagline}' if i.tagline else '',
        '',
        f'This is the periodic status report for the lab, written automatically by velour.',
        '',
        f'The period covered runs from **{start_dt.date():%a %d %b %Y}** to **{end_dt.date():%a %d %b %Y}** ({(end_dt - start_dt).days} days).',
    ]
    if i.mood:
        body_lines.append('')
        intensity_pct = int((i.mood_intensity or 0.5) * 100)
        body_lines.append(f'My current mood is *{i.mood}* at {intensity_pct}%.')
    return [SectionContribution(
        title=f'From the desk of {i.name}',
        body='\n'.join(body_lines),
        sidenotes='Identity is the singleton that holds Velour\'s sense of self.',
    )]

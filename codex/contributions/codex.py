"""Codex contribution — meta. Documentation about itself."""

from . import SectionContribution


def contribute(start_dt, end_dt, **opts):
    try:
        from codex.models import Manual, Section
    except ImportError:
        return []

    manuals = Manual.objects.count()
    sections = Section.objects.count()
    new_or_updated = Section.objects.filter(updated_at__gte=start_dt).count()

    body = f"""There are **{manuals}** manuals in the codex covering **{sections}** sections in total. **{new_or_updated}** sections were added or updated during this period."""

    return [SectionContribution(
        title='Documentation',
        body=body,
        sidenotes='Including this report itself.',
    )]

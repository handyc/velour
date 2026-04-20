"""Pick the right `JobTarget` for a `Job`.

Phase 1 is intentionally dumb: for a given `Job.kind`, find eligible
`JobTarget` kinds, filter to enabled targets, respect an explicit
`requested_target` override, and break ties by priority then slug.

No capacity modelling, no queue-depth awareness, no cost estimation —
that lives in Phase 2 once we have enough dispatched jobs to learn
from.
"""

from __future__ import annotations

from .models import Job, JobTarget


# Job.kind → tuple of eligible JobTarget.kind values, most-preferred first.
ELIGIBLE: dict[str, tuple[str, ...]] = {
    'shell':          ('local', 'vps'),
    'slurm_script':   ('slurm', 'slurm_manual'),
    'http':           ('http', 'local'),
    'agent_task':     ('agent',),
    'sensor_read':    ('esp', 'pi', 'attiny'),
    'firmware_flash': ('local', 'pi'),
}


class RoutingError(Exception):
    """No eligible target for this job."""


def route(job: Job) -> JobTarget:
    """Return the best `JobTarget` for `job`. Does NOT save.

    Precedence: explicit `requested_target` (if enabled + eligible) >
    highest-priority enabled target of the most-preferred kind.
    """
    allowed_kinds = ELIGIBLE.get(job.kind, ())
    if not allowed_kinds:
        raise RoutingError(f'No routing rule for job kind {job.kind!r}')

    if job.requested_target and job.requested_target.enabled \
            and job.requested_target.kind in allowed_kinds:
        return job.requested_target

    qs = JobTarget.objects.filter(enabled=True, kind__in=allowed_kinds)
    # Order by kind preference first (index in allowed_kinds), then priority.
    candidates = list(qs)
    if not candidates:
        raise RoutingError(
            f'No enabled JobTarget of kinds {allowed_kinds} for job '
            f'{job.slug!r}')

    def sort_key(t: JobTarget):
        return (allowed_kinds.index(t.kind), -t.priority, t.slug)

    candidates.sort(key=sort_key)
    return candidates[0]

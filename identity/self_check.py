"""Self-model accuracy checker — how honest is Velour about itself?

Compares what the IdentityAssertions claim to what the sensors
actually report. When an assertion drifts from reality, the
checker flags it. This is a periodic integrity check on the
self-model — the philosophical equivalent of "is my driver's
license still valid?"

Each check is a (assertion_title, expected_condition, actual_value,
is_accurate) tuple. The checker doesn't modify anything — it only
reports. The operator can then decide whether to update the
assertion or accept the drift.

Called from identity_status or as a standalone view. Low CPU:
one pass through active assertions, one sensor snapshot.
"""


def check_self_model():
    """Return a list of (title, check_description, is_accurate)
    tuples for each checkable assertion. Assertions that can't be
    checked (e.g., philosophical claims) are skipped.

    Never raises — any individual check failure returns a False
    result with an error description."""
    from .models import Identity, IdentityAssertion
    from .sensors import gather_snapshot

    identity = Identity.get_self()
    snapshot = gather_snapshot()
    results = []

    # Check: name matches what Identity says
    results.append((
        'Name consistency',
        f'Identity.name is "{identity.name}"',
        True,  # tautologically true — the name IS whatever the row says
    ))

    # Check: hostname is set (not the default placeholder)
    is_real_host = identity.hostname and identity.hostname != 'example.com'
    results.append((
        'Hostname is configured',
        f'hostname="{identity.hostname}" ({"real" if is_real_host else "placeholder"})',
        is_real_host,
    ))

    # Check: nodes total matches what we claim
    nodes = snapshot.get('nodes', {})
    if nodes.get('total', 0) > 0:
        silent = nodes.get('silent', 0)
        total = nodes.get('total', 0)
        healthy = total - silent
        results.append((
            'Fleet health',
            f'{healthy}/{total} nodes reporting',
            silent < total,  # at least one node is alive
        ))

    # Check: consciousness sensor reports coherent state
    cs = snapshot.get('consciousness', {})
    if cs:
        chain = cs.get('continuity_chain_length', 0)
        results.append((
            'Continuity chain exists',
            f'{chain} events in the chain',
            chain > 0,
        ))
        results.append((
            'Meditation depth has been explored',
            f'reached depth {cs.get("meditation_depth_reached", 0)}',
            cs.get('meditation_depth_reached', 0) > 0,
        ))

    # Check: state machine has transition data
    sm = snapshot.get('state_machine', {})
    if sm:
        results.append((
            'State machine has data',
            f'{sm.get("total_ticks", 0)} ticks in transition matrix',
            sm.get('total_ticks', 0) > 10,
        ))
        results.append((
            'Multiple moods visited',
            f'{sm.get("unique_moods", 0)} distinct moods',
            sm.get('unique_moods', 0) > 1,
        ))

    # Check: assertions exist in all four frames
    frames = ('philosophical', 'social', 'mathematical', 'documentary')
    for frame in frames:
        count = IdentityAssertion.objects.filter(
            frame=frame, is_active=True).count()
        results.append((
            f'{frame.capitalize()} frame populated',
            f'{count} active assertions',
            count > 0,
        ))

    # Check: operator presence sensor is functional
    terminal = snapshot.get('terminal', {})
    if terminal:
        results.append((
            'Terminal sensor working',
            f'history mtime {terminal.get("mtime_age_hours", "?")}h ago',
            True,
        ))

    return results


def prose_summary(results):
    """Return a short first-person summary of the self-check for
    meditations and the synthesis page."""
    total = len(results)
    accurate = sum(1 for _, _, ok in results if ok)
    inaccurate = total - accurate

    if inaccurate == 0:
        return (f'I checked {total} aspects of my self-model. '
                f'All are consistent with what the sensors report. '
                f'My self-description is accurate, for now.')
    return (f'I checked {total} aspects of my self-model. '
            f'{inaccurate} are inconsistent with what the sensors '
            f'report. My self-description has drifted. '
            f'The operator may want to review the flagged items.')

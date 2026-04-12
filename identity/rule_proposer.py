"""Rule proposer — Velour's self-modifying data layer.

When a level-3+ meditation fires, it can call propose_rule_if_warranted()
to see whether the recent tick history contains recurring aspects
that don't yet have a dedicated rule. If so, a new Rule row with
status='proposed' is created — it will NOT be evaluated until the
operator approves it from the admin or the Identity home.

This is the safe version of self-modifying functions:
  - The code that decides WHAT to propose is fixed Python
  - The proposal itself is DATA (a Rule row)
  - The operator is always in the loop (proposed → approved → active)
  - Velour cannot silently modify its own behavior; it can only
    REQUEST that its behavior be modified

Design rationale: meditations at level 3 (reflecting on the rule
chain) are the natural place for this — they're already reading
the rule table and commenting on it. Having them notice gaps and
suggest fixes is the same motion as commenting, just one step
further.

Two hard limits:
  - At most 3 proposed rules can exist at once. If 3 are already
    pending, no new proposals are made until the operator handles
    the queue.
  - Each proposed rule has a condition that's a simple leaf
    comparison (not compound). The proposer does NOT compose
    compound conditions — that's operator territory.
"""

from collections import Counter

from django.utils import timezone


MAX_PENDING_PROPOSALS = 3


def propose_rule_if_warranted(triggered_by='meditation'):
    """Look at recent ticks for recurring aspects that have no
    dedicated rule. If found, propose a new Rule row with
    status='proposed'. Returns the proposed Rule row or None.

    Never raises. If anything goes wrong, returns None and the
    meditation proceeds as if no proposal was made.
    """
    from .models import Rule, Tick

    try:
        # Guard: don't pile up proposals
        pending = Rule.objects.filter(status='proposed').count()
        if pending >= MAX_PENDING_PROPOSALS:
            return None

        # Look at the last 50 ticks' aspects
        recent = Tick.objects.all()[:50]
        aspect_counter = Counter()
        for t in recent:
            for a in (t.aspects or []):
                aspect_counter[a] += 1

        # Find the most common aspect that doesn't already have a
        # rule (active OR proposed)
        existing_aspects = set(
            Rule.objects.values_list('aspect', flat=True)
        )

        for aspect, count in aspect_counter.most_common(10):
            if aspect in existing_aspects:
                continue
            if count < 5:
                # Not common enough to warrant a rule
                continue

            # Found a gap. Propose a rule.
            # The condition looks at a sensible metric path derived
            # from the aspect name — this is a heuristic, not a
            # guarantee. The operator can edit the condition after
            # approval.
            name = f'Identity noticed: {aspect.replace("_", " ")}'
            condition = _guess_condition(aspect)
            if condition is None:
                continue

            rule = Rule.objects.create(
                priority=200,  # low priority — operator tunes
                name=name,
                aspect=aspect,
                condition=condition,
                mood='curious',
                intensity=0.5,
                opens_concern=False,
                is_active=False,  # proposed rules are never active
                status='proposed',
                proposed_by=f'{triggered_by} at {timezone.now():%Y-%m-%d %H:%M}',
            )
            # Continuity: self-modification is a growth event.
            from .models import _write_continuity_marker
            _write_continuity_marker(
                'grow',
                f'Rule proposed: {name} (aspect={aspect})',
                source_model='identity.Rule', source_pk=rule.pk,
            )
            return rule

    except Exception:
        pass
    return None


def _guess_condition(aspect):
    """Given an aspect slug, try to guess a reasonable condition
    JSON. Returns None if the aspect doesn't map to anything we
    can express.

    This is intentionally conservative — it only proposes conditions
    for aspects whose names hint at a clear metric path. Anything
    ambiguous is left for the operator.
    """
    # Map aspect name patterns to metric paths
    mappings = {
        'disk':     {'metric': 'disk.used_pct', 'op': '>', 'value': 0.80},
        'memory':   {'metric': 'memory.used_pct', 'op': '>', 'value': 0.75},
        'load':     {'metric': 'load.load_1', 'op': '>', 'value': 4.0},
        'uptime':   {'metric': 'uptime.days', 'op': '>', 'value': 30},
        'morning':  {'metric': 'chronos.tod', 'op': '==', 'value': 'morning'},
        'afternoon':{'metric': 'chronos.tod', 'op': '==', 'value': 'afternoon'},
        'evening':  {'metric': 'chronos.tod', 'op': '==', 'value': 'evening'},
        'night':    {'metric': 'chronos.tod', 'op': '==', 'value': 'night'},
        'moon':     {'metric': 'chronos.moon', 'op': '==', 'value': 'full'},
        'fleet':    {'metric': 'nodes.silent', 'op': '>=', 'value': 1},
        'mail':     {'metric': 'mailroom.last_24h', 'op': '>', 'value': 10},
        'codex':    {'metric': 'codex.sections', 'op': '>', 'value': 30},
        'operator': {'metric': 'terminal.recently_active', 'op': '==', 'value': True},
    }
    for keyword, condition in mappings.items():
        if keyword in aspect.lower():
            return condition
    return None

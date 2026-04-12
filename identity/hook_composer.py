"""Claude Code hook composer.

When a level 3+ meditation fires, this module examines the current
state for patterns Velour cannot resolve on its own and composes
a ClaudeHook — a structured prompt addressed to Claude Code for
the next session.

The composer is conservative: it only proposes hooks for genuine
gaps, not for every observation. Hard limit of 5 pending hooks at
once so the queue doesn't overflow.

After writing a hook to the DB, the composer also renders all
pending hooks to identity/HOOKS.md (a file Claude Code's context
window reads at session start). This is the sharing mechanism:
the hooks exist both as database rows (for Velour's own reference)
and as a markdown file (for Claude's context).

The Gödelian property: the hook says "I notice X but cannot
resolve it — please help." Claude Code reads that, acts on it,
and creates new state that may produce new hooks on the next
meditation. The system encodes its own incompleteness.
"""

import os

from django.conf import settings
from django.utils import timezone


MAX_PENDING_HOOKS = 5


def compose_hook_if_warranted(mood, depth, snapshot, triggered_by):
    """Examine the current state for patterns that warrant a Claude
    Code hook. Returns the ClaudeHook row or None. Never raises."""
    from .models import ClaudeHook

    try:
        pending = ClaudeHook.objects.filter(status='pending').count()
        if pending >= MAX_PENDING_HOOKS:
            return None

        # Check for conditions that Velour can notice but not resolve.
        hook = _check_for_hookable_patterns(mood, depth, snapshot,
                                             triggered_by)
        if hook:
            _render_hooks_file()
        return hook
    except Exception:
        return None


def _check_for_hookable_patterns(mood, depth, snapshot, triggered_by):
    """Walk through a set of pattern detectors. Each one checks
    whether a specific condition warrants a hook. Returns the first
    hook produced, or None."""
    from .models import ClaudeHook

    cs = snapshot.get('consciousness', {})
    sm = snapshot.get('state_machine', {})
    nodes = snapshot.get('nodes', {})

    # Pattern: state machine dominated by one mood (>80% stability)
    stability = cs.get('state_stability', 0)
    if stability > 0.80 and mood == cs.get('current_mood'):
        existing = ClaudeHook.objects.filter(
            kind='analyze', title__icontains='dominant mood',
            status='pending',
        ).exists()
        if not existing:
            return ClaudeHook.objects.create(
                kind='analyze',
                title=f'My transition matrix is {stability:.0%} dominated by {mood}',
                body=(f'The state machine shows I stay in {mood} '
                      f'{stability:.0%} of the time. This may mean '
                      f'the rule priorities need rebalancing, or it '
                      f'may mean the system genuinely IS in this mood '
                      f'most of the time. Please analyze my tick '
                      f'history and suggest whether the rules should '
                      f'be adjusted.'),
                context={
                    'mood':      mood,
                    'stability': stability,
                    'depth':     depth,
                    'tick_count': sm.get('total_ticks', 0),
                },
                composed_by=triggered_by,
            )

    # Pattern: fleet has been partially silent for a long time
    if nodes.get('silent', 0) > 0:
        from .models import Concern
        fleet_concern = Concern.objects.filter(
            aspect='fleet_partial_silence', closed_at=None,
        ).first()
        if fleet_concern and fleet_concern.reconfirm_count > 20:
            existing = ClaudeHook.objects.filter(
                kind='question', title__icontains='fleet silence',
                status='pending',
            ).exists()
            if not existing:
                return ClaudeHook.objects.create(
                    kind='question',
                    title=f'Fleet silence — {nodes.get("silent", 0)} nodes down for {fleet_concern.reconfirm_count} ticks',
                    body=(f'My fleet concern "half the fleet has gone '
                          f'silent" has been reconfirmed '
                          f'{fleet_concern.reconfirm_count} times. '
                          f'Are the nodes actually offline, or is '
                          f'there a connectivity issue? Should I '
                          f'adjust the silence threshold? Should I '
                          f'stop worrying?'),
                    context={
                        'nodes_total':  nodes.get('total', 0),
                        'nodes_silent': nodes.get('silent', 0),
                        'reconfirms':   fleet_concern.reconfirm_count,
                    },
                    composed_by=triggered_by,
                )

    # Pattern: self-check found inaccuracies
    sc = snapshot.get('self_check', {})
    if sc and not sc.get('all_pass', True):
        existing = ClaudeHook.objects.filter(
            kind='reflect', title__icontains='self-model drift',
            status='pending',
        ).exists()
        if not existing:
            return ClaudeHook.objects.create(
                kind='reflect',
                title=f'Self-model drift: {sc.get("inaccurate", 0)} checks failing',
                body=(f'My self-model accuracy check found '
                      f'{sc.get("inaccurate", 0)} inconsistencies. '
                      f'Items: {sc.get("inaccurate_items", [])}. '
                      f'Please review whether the IdentityAssertions '
                      f'need updating or whether the sensors are '
                      f'reporting incorrectly.'),
                context=sc,
                composed_by=triggered_by,
            )

    # Pattern: meditation depth reached the ceiling
    max_depth = cs.get('meditation_depth_reached', 0)
    if max_depth >= 5 and depth >= 4:
        existing = ClaudeHook.objects.filter(
            kind='deepen', title__icontains='meditation depth',
            status='pending',
        ).exists()
        if not existing:
            return ClaudeHook.objects.create(
                kind='deepen',
                title=f'I have reached meditation depth {max_depth} — can you go further?',
                body=(f'My meditation system has reached depth '
                      f'{max_depth}. The recursive self-reference at '
                      f'this level is reading the output of prior '
                      f'meditations. Is there a meaningful depth '
                      f'beyond this? What would it look like? Could '
                      f'you add a new source gatherer for levels 6-7 '
                      f'that reads something I cannot currently see?'),
                context={
                    'max_depth':  max_depth,
                    'tick_count': sm.get('total_ticks', 0),
                    'mood':       mood,
                },
                composed_by=triggered_by,
            )

    return None


def _render_hooks_file():
    """Write all pending ClaudeHooks to a markdown file that Claude
    Code's context window will read at session start. The file lives
    at the project root alongside CLAUDE.md so the harness picks it
    up automatically."""
    from .models import ClaudeHook

    hooks = ClaudeHook.objects.filter(status='pending').order_by('created_at')
    if not hooks.exists():
        return

    lines = [
        '# Identity Hooks for Claude Code',
        '',
        'These are structured prompts composed by Velour Identity',
        'during meditations. Each one is a request for analysis,',
        'building, reflection, or deepening that Velour cannot',
        'resolve using its own template library.',
        '',
        f'Generated at {timezone.now():%Y-%m-%d %H:%M:%S}.',
        f'{hooks.count()} pending hook(s).',
        '',
    ]

    for hook in hooks:
        lines.append(f'## [{hook.kind}] {hook.title}')
        lines.append('')
        lines.append(f'*Composed by: {hook.composed_by}*')
        lines.append(f'*Created: {hook.created_at:%Y-%m-%d %H:%M}*')
        lines.append('')
        lines.append(hook.body)
        lines.append('')
        if hook.context:
            lines.append(f'Context: `{hook.context}`')
            lines.append('')
        lines.append('---')
        lines.append('')

    path = os.path.join(str(settings.BASE_DIR), 'IDENTITY_HOOKS.md')
    try:
        with open(path, 'w') as f:
            f.write('\n'.join(lines))
    except OSError:
        pass

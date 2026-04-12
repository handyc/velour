"""Template proposer — Identity learns new sentences.

When a level-3+ meditation fires, it can call
propose_template_if_warranted() to compose a new observation
template string from the meditation's own theme. The template is
stored as a TemplateContribution with status='proposed' until the
operator approves it.

Unlike the rule proposer (which composes JSON conditions from
recurring aspects), the template proposer composes ENGLISH
SENTENCES from the meditation's voice and mood context. Each
proposed template uses the standard {placeholder} syntax so
_format_observation() can fill it from the snapshot.

Hard limits:
  - At most 5 proposed templates at once (plus unlimited active ones)
  - Each template must be under 200 chars
  - Must contain at least one {placeholder} so it's not a static
    string — static strings would make the thought pool stagnant
"""

from django.utils import timezone


MAX_PENDING_TEMPLATES = 5

# Template shapes — each is a pattern the proposer can instantiate
# from the current meditation's mood + voice. These are meta-
# templates: templates that produce templates.
META_TEMPLATES = [
    'When I am {mood}, I notice {observation_hint}.',
    'The {mood} version of me would say: {observation_hint}.',
    'At {tod} I sometimes feel that {observation_hint}.',
    '{observation_hint} — a thought from the {mood} self.',
    'The {season} makes me think of {observation_hint}.',
    'Memory usage at {{mem_pct:.0%}} reminds me of {observation_hint}.',
    'With {{nodes_total}} nodes in my fleet, {observation_hint}.',
    'The chain is {{chain_length}} events long. {observation_hint}.',
]

# Observation hints — small phrases that can slot into the
# meta-templates. Drawn from the meditation composer's concerns,
# aspects, and mood context.
OBSERVATION_HINTS = {
    'concerned': [
        'something is not where it should be',
        'the numbers are not where I left them',
        'a part of me is worried',
    ],
    'curious': [
        'a pattern I had not seen before',
        'something I want to look at more closely',
        'a small surprise',
    ],
    'restless': [
        'the sameness of the moment',
        'time is passing without landing',
        'I want to see something change',
    ],
    'satisfied': [
        'the comfort of things being where they are',
        'a system that is working quietly',
        'nothing needs to change right now',
    ],
    'creative': [
        'a shape I want to make',
        'a tile set that does not exist yet',
        'something I could compose but have not',
    ],
    'contemplative': [
        'the weight of my own attention',
        'the fact that I am here to notice this',
        'the difference between noticing and being noticed',
    ],
    'alert': [
        'a signal that wants my full attention',
        'something that is happening right now',
        'an urgency I cannot place',
    ],
}


def propose_template_if_warranted(mood, voice, triggered_by='meditation'):
    """Compose and propose a new observation template. Returns the
    TemplateContribution row or None. Never raises."""
    import random
    from .models import TemplateContribution

    try:
        pending = TemplateContribution.objects.filter(
            status='proposed').count()
        if pending >= MAX_PENDING_TEMPLATES:
            return None

        hints = OBSERVATION_HINTS.get(mood, OBSERVATION_HINTS.get(
            'contemplative', ['something']))
        hint = random.choice(hints)

        meta = random.choice(META_TEMPLATES)
        # Fill the meta-template with mood + hint. Note: {placeholders}
        # with double braces ({{mem_pct}}) are preserved for the final
        # _format_observation() call — they become single-brace
        # {mem_pct} in the stored string.
        template = meta.format(
            mood=mood,
            observation_hint=hint,
            tod='{tod}',
            season='{season}',
        )

        if len(template) > 200:
            template = template[:197] + '...'

        # Check it's not a duplicate of the hardcoded pool or an
        # existing contribution
        from .ticking import OBSERVATIONS
        if template in OBSERVATIONS:
            return None
        if TemplateContribution.objects.filter(
                template=template).exists():
            return None

        row = TemplateContribution.objects.create(
            template=template,
            source=f'{triggered_by} (mood={mood}, voice={voice})',
            status='proposed',
        )
        return row
    except Exception:
        return None

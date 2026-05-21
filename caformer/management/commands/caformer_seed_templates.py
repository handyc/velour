"""Seed starter TemplatePattern rows for the four boardstack4 agents.

Each row is one slot-templated p → q mapping.  Patterns and outputs
use the same [SlotName] convention; on match, slot values are
substituted in.

Re-runnable: wipes existing rows per agent_color first so the seed
is the canonical set after re-run.  Hand-edited additions in the
admin will be erased — gate behind a separate command if you want
to preserve.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from caformer.models import TemplatePattern


# (agent_color, priority, pattern, output, confidence, notes)
TEMPLATES = [
    # ── 0 personality ─────────────────────────────────────────────
    (0, 3, 'thanks [X]',
        "You're welcome, [X].",
        0.7, ''),
    (0, 3, 'thank you [X]',
        "You're welcome, [X].",
        0.7, ''),
    (0, 3, 'hi [X]',
        'Hello, [X].',
        0.7, ''),
    (0, 3, 'hello [X]',
        'Hello, [X].',
        0.7, ''),
    (0, 3, 'bye [X]',
        'Goodbye, [X].',
        0.7, ''),
    (0, 5, 'my name is [X]',
        'Nice to meet you, [X].',
        0.6, ''),

    # ── 1 information ─────────────────────────────────────────────
    # Wikipedia-style lookup (the user's example).
    (1, 2, 'look up [X]',
        'https://en.wikipedia.org/wiki/[X]',
        0.85,
        'Default wikipedia lookup template — produces a real URL '
        'deterministically for any noun phrase.'),
    (1, 2, 'lookup [X]',
        'https://en.wikipedia.org/wiki/[X]',
        0.85, 'alias of look up [X]'),
    (1, 2, 'wiki [X]',
        'https://en.wikipedia.org/wiki/[X]',
        0.85, ''),
    (1, 2, 'wikipedia [X]',
        'https://en.wikipedia.org/wiki/[X]',
        0.85, ''),
    # Search-engine.
    (1, 3, 'search for [X]',
        'https://duckduckgo.com/?q=[X]',
        0.7, ''),
    (1, 3, 'search [X]',
        'https://duckduckgo.com/?q=[X]',
        0.7, ''),
    # Factual stems (no real store backing them yet — explicit stubs).
    (1, 4, 'what is [X]',
        '(no factual store wired — would describe [X])',
        0.30,
        'Stub: ack the question, surface that the answer source '
        'is missing.  Replace when a fact store lands.'),
    (1, 4, 'how many [X]',
        '(no factual store wired — would count [X])',
        0.30, 'stub'),
    (1, 4, 'how much [X]',
        '(no factual store wired — would measure [X])',
        0.30, 'stub'),
    (1, 4, 'when was [X]',
        '(no factual store wired — would date [X])',
        0.30, 'stub'),
    (1, 4, 'where is [X]',
        '(no factual store wired — would locate [X])',
        0.30, 'stub'),
    (1, 4, 'who is [X]',
        '(no factual store wired — would identify [X])',
        0.30, 'stub'),

    # ── 2 command ─────────────────────────────────────────────────
    (2, 2, 'run [X]',
        'Would execute: $ [X]  (executor not wired)',
        0.5,
        'Stub: surface the command we would run, do not actually run.'),
    (2, 2, 'execute [X]',
        'Would execute: $ [X]  (executor not wired)',
        0.5, ''),
    (2, 2, 'write a [X]',
        "I would draft a [X] — but the command agent doesn't have "
        "a writer wired yet.",
        0.4, ''),
    (2, 2, 'make a [X]',
        "I would build a [X] — but the command agent doesn't have "
        "an executor wired yet.",
        0.4, ''),
    (2, 2, 'create a [X]',
        "I would create a [X] — but the command agent doesn't have "
        "an executor wired yet.",
        0.4, ''),
    (2, 2, 'compose a [X]',
        "I would compose a [X] — but the command agent doesn't have "
        "a writer wired yet.",
        0.4, ''),
    (2, 3, 'show me [X]',
        "I would display: [X]  (display sink not wired)",
        0.4, ''),
    (2, 3, 'list [X]',
        "Would list: [X]  (no actual listing backend wired)",
        0.4, ''),

    # ── 3 meta ────────────────────────────────────────────────────
    (3, 3, 'reflect on [X]',
        'Reflecting on [X]: this is the harness layer wrapping the '
        'deterministic CA core.  [X] is registered to the meta '
        'agent for introspective response.',
        0.6,
        'Structured introspective response — emits as reply, not '
        'clarify, because the template gives a substantive answer.'),
    (3, 3, 'think about [X]',
        'Considering [X] in the context of this session.',
        0.5, ''),
    (3, 3, 'what does [X] mean',
        '(meaning store not wired — would resolve [X])',
        0.30, 'stub'),
    (3, 3, 'why [X]',
        '(no causal model wired — would reason about why [X])',
        0.30, 'stub'),
]


class Command(BaseCommand):
    help = 'Seed starter TemplatePattern rows for the 4 boardstack4 agents.'

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true',
                              help='delete existing rows per agent_color '
                                   'before seeding (default off — '
                                   'idempotent upsert by exact pattern).')

    def handle(self, *, wipe, **opts):
        from collections import Counter
        if wipe:
            n = TemplatePattern.objects.all().delete()[0]
            self.stdout.write(f'wiped {n} existing TemplatePattern rows')
        counts: Counter = Counter()
        for color, priority, pattern, output, confidence, notes in TEMPLATES:
            row, created = TemplatePattern.objects.update_or_create(
                agent_color=color,
                pattern=pattern,
                defaults={
                    'output':     output,
                    'priority':   priority,
                    'confidence': confidence,
                    'notes':      notes,
                    'is_active':  True,
                },
            )
            counts[(color, 'new' if created else 'upd')] += 1
        for color in (0, 1, 2, 3):
            new = counts.get((color, 'new'), 0)
            upd = counts.get((color, 'upd'), 0)
            label = ['personality', 'information', 'command', 'meta'][color]
            self.stdout.write(
                f'  {label:12s}  {new:>2} new  {upd:>2} updated')
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(TEMPLATES)} TemplatePattern rows.'))

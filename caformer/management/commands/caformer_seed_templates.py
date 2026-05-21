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


# (agent_color, priority, pattern, output, confidence, notes,
#  handler_name) — handler_name is empty for plain templates;
# templates may use [handler:name] markers in output regardless.
TEMPLATES_RAW = [
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


# Live-data templates — wired via handler_name (Option A) or
# [handler:name] markers in output (Option B).
TEMPLATES_LIVE = [
    # (color, priority, pattern, output, confidence, notes, handler_name)

    # Option A: handler_name set — output is replaced entirely.
    (3, 1, "what's my mood",
        '(replaced by mood handler)',
        0.90, 'live: identity.Tick mood', 'mood'),
    (3, 1, "what mood are you in",
        '(replaced by mood handler)',
        0.90, 'live: identity.Tick mood', 'mood'),
    (3, 1, 'how do you feel',
        '(replaced by mood handler)',
        0.85, 'live: identity.Tick mood', 'mood'),
    (1, 1, 'what time is it',
        '(replaced by now handler)',
        0.95, 'live: server clock', 'now'),
    (1, 1, "what's the date",
        '(replaced by today handler)',
        0.95, 'live: server date', 'today'),
    (1, 1, 'what branch',
        '(replaced by git_branch handler)',
        0.95, 'live: git branch', 'git_branch'),
    (1, 1, 'how many qrpairs',
        '(replaced by qrpair_count handler)',
        0.90, 'live: caformer QRPair count', 'qrpair_count'),

    # Option B: [handler:name] markers in output, composed with
    # literal text + slot fills.  No handler_name on the row.
    (0, 1, 'hi [X]',
        "Hi [X] — I'm feeling [handler:mood] today.",
        0.80, 'live mood + slot fill', ''),
    (1, 2, "what's up",
        "It's [handler:now] on [handler:today].  "
        "I'm in a [handler:mood] mood.  "
        "We have [handler:qrpair_count] in the corpus.",
        0.85, 'multi-handler composition', ''),
    (3, 2, 'status report',
        "Branch: [handler:git_branch]\n"
        "Mood:   [handler:mood]\n"
        "Time:   [handler:now]\n"
        "Corpus: [handler:qrpair_count]",
        0.85, 'multi-handler composition', ''),

    # ── Conditional command templates ('if X then Y') ────────────
    # The cond_act handler parses the cond slot against the live
    # handler registry, returns act when condition is true, an
    # explicit trace when false.
    (2, 2, 'if [cond] then [act]',
        '(resolved by cond_act handler)',
        0.80, 'conditional execution', 'cond_act'),
    (2, 2, 'when [cond] then [act]',
        '(resolved by cond_act handler)',
        0.80, 'conditional execution (synonym)', 'cond_act'),
    (2, 3, 'do [act] if [cond]',
        '(resolved by cond_act handler)',
        0.75, 'conditional execution (inverted order)', 'cond_act'),

    # ── Meta route templates: introspect the harness ────────────
    (3, 2, 'what tokens does [route] have',
        '(resolved by route_tokens handler)',
        0.85, 'meta: list PICM tokens', 'route_tokens'),
    (3, 2, 'show me [route] tokens',
        '(resolved by route_tokens handler)',
        0.85, 'meta synonym', 'route_tokens'),
    (3, 2, 'what templates does [route] have',
        '(resolved by route_templates handler)',
        0.85, 'meta: list templates', 'route_templates'),
    (3, 2, 'show [route] templates',
        '(resolved by route_templates handler)',
        0.85, 'meta synonym', 'route_templates'),
    (3, 1, 'list tree paths',
        'PICM tree: [handler:tree_paths]',
        0.85, 'meta: tree topology', ''),
    (3, 1, 'concept system size',
        '[handler:concept_count]',
        0.85, 'meta: concept system stats', ''),
    (3, 1, 'what concepts does [X] map to',
        '(resolved by recognised_concepts handler)',
        0.80, 'meta: text → Sanskrit concepts', 'recognised_concepts'),
    (3, 1, 'prefilter state',
        '[handler:prefilter_state]',
        0.85, 'meta: which prefilters loaded', ''),
    # Sanskrit concept system templates ──────────────────────────
    (1, 2, 'translate [X] to sanskrit',
        '(resolved by to_sanskrit handler)',
        0.85, 'sanskrit translation', 'to_sanskrit'),
    (1, 2, 'what does [X] mean in sanskrit',
        '(resolved by recognised_concepts handler)',
        0.85, 'sanskrit concept lookup', 'recognised_concepts'),
    (1, 2, 'sanskrit for [X]',
        '(resolved by to_sanskrit handler)',
        0.85, 'sanskrit shorthand', 'to_sanskrit'),
    (1, 3, 'gloss [X]',
        '(resolved by concept_gloss handler)',
        0.80, 'concept gloss only', 'concept_gloss'),

    (3, 1, 'what can you do',
        '(resolved by capabilities handler)',
        0.90, 'meta: enumerate handlers', 'capabilities'),
    (3, 1, 'list your handlers',
        '(resolved by capabilities handler)',
        0.90, 'meta synonym', 'capabilities'),
    (3, 1, 'describe yourself',
        '(resolved by describe_self handler)',
        0.90, 'meta: rich self-description', 'describe_self'),
    (0, 1, 'who are you',
        '(resolved by describe_self handler)',
        0.90, 'meta self-intro on personality route', 'describe_self'),

    (3, 1, 'self report',
        "Branch: [handler:git_branch]\n"
        "Mood: [handler:mood]\n"
        "Time: [handler:now]\n"
        "Corpus: [handler:qrpair_count]\n"
        "Prefilters: [handler:prefilter_state]\n"
        "PICM tree: [handler:tree_paths]\n"
        "Concept system: [handler:concept_count]",
        0.90, 'comprehensive introspection', ''),
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
        # Stage 1: legacy 6-tuple rows (no handler_name).
        for color, priority, pattern, output, confidence, notes in TEMPLATES_RAW:
            row, created = TemplatePattern.objects.update_or_create(
                agent_color=color,
                pattern=pattern,
                defaults={
                    'output':       output,
                    'priority':     priority,
                    'confidence':   confidence,
                    'notes':        notes,
                    'is_active':    True,
                    'handler_name': '',
                },
            )
            counts[(color, 'new' if created else 'upd')] += 1
        # Stage 2: live-data rows (with handler_name and/or
        # [handler:name] markers in output).
        n_live_new = 0
        n_live_upd = 0
        for (color, priority, pattern, output, confidence, notes,
                 handler_name) in TEMPLATES_LIVE:
            row, created = TemplatePattern.objects.update_or_create(
                agent_color=color,
                pattern=pattern,
                defaults={
                    'output':       output,
                    'priority':     priority,
                    'confidence':   confidence,
                    'notes':        notes,
                    'is_active':    True,
                    'handler_name': handler_name,
                },
            )
            counts[(color, 'new' if created else 'upd')] += 1
            if created: n_live_new += 1
            else:       n_live_upd += 1
        for color in (0, 1, 2, 3):
            new = counts.get((color, 'new'), 0)
            upd = counts.get((color, 'upd'), 0)
            label = ['personality', 'information', 'command', 'meta'][color]
            self.stdout.write(
                f'  {label:12s}  {new:>2} new  {upd:>2} updated')
        total = len(TEMPLATES_RAW) + len(TEMPLATES_LIVE)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {total} TemplatePattern rows '
            f'({len(TEMPLATES_LIVE)} live-data — '
            f'{n_live_new} new, {n_live_upd} updated).'))

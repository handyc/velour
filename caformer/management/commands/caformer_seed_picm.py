"""Seed the four PICMVocab rows with starter token lists.

Each routing colour gets its own vocabulary aligned with the agent's
job:

  0 personality — greetings / closings / social ("hi", "bye", "ty")
  1 information — query stems ("how", "what", "when", "many")
  2 command     — shell + C + bash ("ls", "grep", "void", "main")
  3 meta        — introspection ("self", "why", "ref", "uniq")

All tokens ≤ 4 ASCII chars so they pack cleanly into the default
1024-token × 4-byte board layout (128×128 K=4 cells).

Re-runnable: upserts by agent_color.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from caformer.models import PICMVocab


# Tokens are short by design — 4 bytes max.  Longer concepts use
# stems ('many' for "how many", 'what' for "what is" / "what does").
# Sorted to keep the data file diff-stable.

PERSONALITY_TOKENS = sorted(set([
    # greetings (≤ 4 chars)
    'hi', 'hey', 'yo', 'sup', 'morn', 'noon', 'nite', 'eve',
    # closings
    'bye', 'cya', 'l8r', 'gnit', 'tata',
    # gratitude
    'ty', 'thx', 'thnx', 'np',
    # affirmations
    'ok', 'yes', 'sure', 'cool', 'nice', 'yep', 'yup',
    # negatives
    'no', 'nah', 'nope',
    # affection / social
    'love', 'miss', 'hug', 'care', 'glad', 'sad',
    # exclamations
    'wow', 'oh', 'ah', 'hm', 'huh', 'eh', 'omg', 'lol',
    'haha', 'heh',
    # short you-tokens
    'pls', 'plz', 'rn', 'imo', 'tbh', 'ima',
    # courtesy nouns
    'name', 'help', 'time', 'day',
]))


INFORMATION_TOKENS = sorted(set([
    # question stems
    'how', 'what', 'when', 'who', 'why',
    # quantifiers
    'many', 'much', 'big', 'far', 'long', 'old',
    'tall', 'wide', 'high', 'fast',
    # be-verbs / copula stems
    'is', 'are', 'was', 'has', 'had',
    'does', 'did', 'will',
    # information markers
    'fact', 'info', 'data', 'list', 'name', 'date',
    'year', 'day', 'time',
    # comparative stems
    'more', 'less', 'most', 'best',
    # source indicators
    'from', 'into', 'of', 'in', 'on', 'by',
    # common topic stems (≤ 4 chars)
    'mars', 'moon', 'sun', 'star', 'sea', 'lake',
    'city', 'lang', 'word', 'book', 'song',
]))


COMMAND_TOKENS = sorted(set([
    # bash / unix (≤ 4 chars)
    'ls', 'cd', 'cp', 'mv', 'rm',
    'cat', 'less', 'tail', 'head', 'find', 'grep',
    'sed', 'awk', 'sort', 'uniq', 'wc', 'tee',
    'curl', 'wget', 'ssh', 'scp', 'tar', 'zip',
    'ps', 'top', 'kill', 'echo',
    'bash', 'sh', 'pwd', 'env', 'date', 'man',
    'git', 'sudo', 'pip', 'npm', 'make', 'gcc',
    'cc',
    # C tokens
    'int', 'void', 'char', 'long', 'enum', 'goto',
    'main', 'if', 'else', 'for', 'do', 'free',
    'NULL',
    # imperative verbs
    'make', 'fix', 'edit', 'open', 'save', 'load',
    'run', 'exec', 'show', 'list', 'log',
    'add', 'del',
]))


META_TOKENS = sorted(set([
    # introspection
    'self', 'me', 'us', 'we', 'mind',
    # uncertainty / hedging
    'why', 'how', 'whom',
    'sort', 'kind', 'seem',
    'feel', 'true', 'real', 'fake', 'unk',
    # process / system
    'tick', 'step', 'turn', 'walk', 'loop',
    'goal', 'plan', 'task',
    # reference / identity
    'id', 'ref', 'uniq', 'name', 'tag',
    'addr', 'pk', 'slug',
    # meta-cognition
    'know', 'note', 'mean', 'idea', 'view',
    'sure', 'lost', 'huh',
    # caformer-internal jargon (4-char max)
    'CA',   # cellular automaton
    'LUT',  # lookup table
    'GA',   # genetic algorithm
    'QR',   # qr-pair
    'DMN',  # default mode network
    'tier',
    'pact',
]))


def _assert_max_len(tokens, n):
    over = [t for t in tokens if len(t) > n]
    assert not over, f'tokens over {n} chars: {over}'

# Audit at import: catches future seed edits that drift past 4 chars.
_assert_max_len(PERSONALITY_TOKENS, 4)
_assert_max_len(INFORMATION_TOKENS, 4)
_assert_max_len(COMMAND_TOKENS, 4)
_assert_max_len(META_TOKENS, 4)


SEEDS = [
    (0, 'personality', PERSONALITY_TOKENS),
    (1, 'information', INFORMATION_TOKENS),
    (2, 'command',     COMMAND_TOKENS),
    (3, 'meta',        META_TOKENS),
]


class Command(BaseCommand):
    help = 'Seed the four PICMVocab rows for the boardstack4 agents.'

    def handle(self, *args, **opts):
        for color, name, tokens in SEEDS:
            row, created = PICMVocab.objects.update_or_create(
                agent_color=color,
                defaults={
                    'bytes_per_token': 4,
                    'token_count': 1024,
                    'tokens_json': list(tokens),
                },
            )
            self.stdout.write(
                f"  {'+' if created else '·'} {name:12s} "
                f"{len(tokens)} tokens "
                f"(longest: {max(len(t) for t in tokens)} chars)")
        self.stdout.write(self.style.SUCCESS(
            f'Seeded 4 PICMVocab rows.'))

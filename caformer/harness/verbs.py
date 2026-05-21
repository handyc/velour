"""Rotating spinner verbs.

Per the barding distillation plan: a varied verb pool while the model
"thinks" reads as a curious person at work, not a mechanical bot.
Trivial cost (≈256 B of strings) for a real magic-feel contribution.

The pool is structured by category so the harness can pick a verb
that fits the user's intent: a chatty "Mulling…" for personality
prompts, a focused "Looking that up…" for information queries, etc.

Pick logic lives in ``pick(category, rng)``; the harness's
``run_turn`` calls it once per turn.
"""
from __future__ import annotations

import random
from typing import Sequence

# Categories must match caformer.router_corpus integer codes:
# 0 PERSONALITY · 1 INFORMATION · 2 ACTION · 3 META
DEFAULT_VERBS: dict[int, Sequence[str]] = {
    0: (  # personality / chat
        'Pondering', 'Mulling', 'Considering', 'Musing',
        'Thinking it over', 'Settling in', 'Warming up',
    ),
    1: (  # information
        'Looking that up', 'Recalling', 'Checking',
        'Sifting through', 'Cross-referencing', 'Recollecting',
    ),
    2: (  # action
        'Getting to work', 'Setting up', 'Drafting',
        'Composing', 'Assembling', 'Laying it out',
    ),
    3: (  # meta / hard
        'Thinking carefully', 'Untangling',
        'Working through it', 'Reasoning it out',
        'Marinating', 'Letting it settle',
    ),
}


def pick(category: int,
         rng: random.Random | None = None,
         pool: dict[int, Sequence[str]] | None = None) -> str:
    """Choose one verb for the given category.  Unknown categories
    fall back to the META pool (broadest)."""
    rng = rng or random.Random()
    pool = pool or DEFAULT_VERBS
    bucket = pool.get(category) or pool.get(3) or ('Working',)
    return rng.choice(list(bucket))

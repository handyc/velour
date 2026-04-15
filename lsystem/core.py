"""Shared L-system expansion core for every Velour app.

One `Grammar` expands an axiom + rules over N iterations. Domain
interpreters — Gubi's three.js turtle, Legolith's brick-placement
walker, the lsystem app's Aether plant script — all consume the
expanded string in their own alphabet. Unknown symbols pass through
unchanged, so each domain's extra tokens (`L`, `P`, `W`, `R`, `{C:…}`,
`{S:…}`, `<`, `>`, `^`, `&`, `[`, `]`, …) are preserved.

Accepted rule shapes (all normalised internally to a list of dicts):

    dict[str, str]                 {'F': 'FF'}
    dict[str, list[str]]           {'F': ['FF', 'F[+F]']}
    list[dict[str, str]]           [{'F': 'FF'}, {'F': 'F[+F]'}]
    list[dict[str, list[str]]]     [{'F': ['FF', 'F[+F]']}, {'X': 'FX'}]

The list form is how the lsystem app stores rules in its JSONField —
each list entry is a stochastic branch chosen per expansion step. The
nested-list form lets a single rule set enumerate alternatives inline.

Brace tokens like `{C:rrggbb}` / `{S:w,d,h}` are preserved as single
literal terminals and never matched against rules. This is what lets
Legolith's inline color/shape pragmas ride through a shared engine.
"""
from __future__ import annotations

import random
from typing import Union


RuleValue = Union[str, list]
RuleDict = dict  # dict[str, RuleValue]
RulesArg = Union[RuleDict, list, None]


def normalise_rules(rules: RulesArg) -> list:
    """Return rules as a list of dicts (each dict is a stochastic branch).

    None / empty / malformed → [{}] (a no-op grammar where every symbol
    passes through). Single-dict inputs are wrapped in a 1-element list.
    """
    if rules is None:
        return [{}]
    if isinstance(rules, dict):
        return [rules]
    if isinstance(rules, list):
        cleaned = [r for r in rules if isinstance(r, dict)]
        return cleaned or [{}]
    return [{}]


class Grammar:
    """Deterministic-by-default L-system expander.

    With `seed=None` and no stochastic alternatives, expansion is
    fully deterministic. Pass a seed (or use stochastic rules) to get
    reproducible randomised grammars.
    """

    def __init__(self, axiom: str, rules: RulesArg = None,
                 iterations: int = 3, seed: int | None = None,
                 max_len: int = 200_000):
        self.axiom = axiom or ''
        self._rule_sets = normalise_rules(rules)
        self.iterations = max(0, int(iterations))
        self.max_len = max(1, int(max_len))
        self._rng = random.Random(seed)

    def _pick_rule(self, symbol: str) -> str | None:
        """Return a replacement for `symbol`, or None if no rule matches.

        If multiple rule-set dicts define the symbol, one is picked
        uniformly; if the chosen value is itself a list, an alternative
        is picked uniformly from it.
        """
        candidates = [rs for rs in self._rule_sets if symbol in rs]
        if not candidates:
            return None
        chosen = (candidates[0] if len(candidates) == 1
                  else self._rng.choice(candidates))
        value = chosen[symbol]
        if isinstance(value, list):
            return self._rng.choice(value) if value else None
        return str(value)

    def expand(self) -> str:
        s = self.axiom
        for _ in range(self.iterations):
            out: list[str] = []
            i, n = 0, len(s)
            while i < n:
                c = s[i]
                # Brace tokens are literal terminals — preserve verbatim.
                if c == '{':
                    j = s.find('}', i)
                    if j == -1:
                        out.append(s[i:])
                        break
                    out.append(s[i:j + 1])
                    i = j + 1
                    continue
                replacement = self._pick_rule(c)
                out.append(replacement if replacement is not None else c)
                i += 1
            s = ''.join(out)
            if len(s) >= self.max_len:
                s = s[:self.max_len]
                break
        return s


def expand(axiom: str, rules: RulesArg = None, iterations: int = 3,
           seed: int | None = None, max_len: int = 200_000) -> str:
    """Convenience wrapper for one-shot expansion."""
    return Grammar(axiom, rules, iterations=iterations, seed=seed,
                   max_len=max_len).expand()

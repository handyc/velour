"""Hex K=4 Wireworld rule.

Wireworld semantics:
    0 — empty (substrate, never fires)
    1 — wire / conductor (the layout of your circuit)
    2 — electron HEAD (signal pulse this tick)
    3 — electron TAIL (trailing edge, becomes wire next tick)

Transitions:
    self == 0 → 0   (empty stays empty)
    self == 2 → 3   (head becomes tail)
    self == 3 → 1   (tail becomes wire)
    self == 1 → 2 iff exactly 1 or 2 of the 6 neighbours are heads,
                   otherwise stays 1

These are the canonical wireworld rules ported to a 6-neighbourhood;
the threshold "1 or 2 heads" stays the same as Wireworld's original
8-neighbourhood version. With this rule a single "head + tail" pair
travels along a wire at one cell per tick, gates can be built from
junction patterns, and pulse trains compose linearly.

The rule is sha1-deduped via taxon.exporters when imported, so saving
forge circuits doesn't clutter automaton with duplicate RuleSets.
"""
from __future__ import annotations

from automaton.packed import PackedRuleset


WIREWORLD_NAME = 'wireworld-hex-k4'


def build_wireworld_rule() -> PackedRuleset:
    """Construct the canonical hex K=4 wireworld PackedRuleset."""
    pr = PackedRuleset(n_colors=4)
    K = 4
    K6 = K ** 6
    for self_c in range(K):
        for neigh_idx in range(K6):
            # decode 6 neighbours
            n = neigh_idx
            ns = []
            for _ in range(6):
                ns.append(n % K)
                n //= K
            heads = sum(1 for v in ns if v == 2)
            if self_c == 0:
                out = 0
            elif self_c == 2:
                out = 3
            elif self_c == 3:
                out = 1
            else:   # self_c == 1, wire
                out = 2 if (heads == 1 or heads == 2) else 1
            idx = self_c * K6 + neigh_idx
            pr.set_by_index(idx, out)
    return pr


# CSS palette aligned with the semantics: empty / wire / head / tail.
WIREWORLD_PALETTE = [
    '#0d1117',   # 0: empty (page background)
    '#888888',   # 1: wire (50% gray)
    '#f0c040',   # 2: head (electron yellow)
    '#a85020',   # 3: tail (cooled trail)
]

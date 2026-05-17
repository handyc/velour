"""caformer/component_fitness — per-component evolution metrics.

Each of the 8 caformer components gets a focused fitness function
that scores a candidate rule (or bundle of rules) on what that
component actually *needs to do*.  The four primitives already
covered by ``caformer.ga`` (norm, score, output, mlp) reuse those
fitnesses verbatim; the four remaining ones (embedding, projection,
self_attention, transformer) get new metrics defined here.

The autotournament loop (``caformer.component_tournament``) cycles
through these by component_slug, pulls the genome of the current
champion (or random if none exists), runs the GA for a budget, and
saves a new champion if it beat the parent.

Design principles for these metrics:

  * **Cheap**: a single fitness call should take ≤ ~50 ms so the GA
    can iterate hundreds of times per minute on a modest box.
  * **Aligned**: the metric should reward what makes the component
    useful in the wider transformer, not just abstract CA niceness.
  * **Non-degenerate**: penalise mono-colour collapse and other
    pathological local optima that a pure "be different" metric
    would reward.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

import numpy as np

from .ga import (
    Genome, FitnessFn, _FITNESS_RNG_SEED,
    NORM_FITNESS, ATTENTION_SCORE_FITNESS, OUTPUT_HEAD_FITNESS, MLP_FITNESS,
)
from .primitives import (
    hex_ca_step, ca_embedding, ca_qkv_project, ca_attention_score,
    ca_self_attention, ca_residual_merge, ca_layer_norm_iterative,
    ca_output_head_iterative, ca_bank_step,
)


# ── EMBED ────────────────────────────────────────────────────────────
#
# An embedding rule is good when:
#   1. Different token ids produce *visibly different* grids (token
#      identity is recoverable from the embedding).
#   2. The same token id always produces the same grid (determinism —
#      guaranteed by the LCG seed but penalise mono-collapse).
#   3. Grids are not mono-colour (the embedding has useful capacity).
#
# Score = mean pairwise Hamming distance across embedded grids
#       + nonlinearity bonus  − collapse penalty.

_EMBED_TOKENS = list(range(0, 256, 16))      # 16 well-spread byte ids
_EMBED_TICKS  = 4


def EMBED_FITNESS(g: Genome) -> float:
    rule = g['embed']
    grids = [ca_embedding(t, rule_table=rule, n_ticks=_EMBED_TICKS).flatten()
             for t in _EMBED_TOKENS]
    G = np.stack(grids, axis=0).astype(np.int16)
    # Pairwise Hamming, upper triangle only.
    n = len(grids)
    pair_dists = []
    for i in range(n):
        for j in range(i + 1, n):
            pair_dists.append(int((G[i] != G[j]).sum()))
    mean_hamming = float(np.mean(pair_dists)) / 256.0        # normalize → [0, 1]
    # Capacity = mean unique-colour count per grid (4 = full use of K=4).
    uniqueness  = float(np.mean([len(np.unique(g_)) for g_ in grids])) / 4.0
    # Collapse penalty: any grid that's all one colour costs a lot.
    n_collapsed = sum(1 for g_ in grids if len(np.unique(g_)) == 1)
    collapse_pen = 0.5 * (n_collapsed / n)
    return mean_hamming + 0.3 * uniqueness - collapse_pen


# ── PROJECTION (Q / K / V) ───────────────────────────────────────────
#
# A projection rule is good when:
#   1. Applied to two different inputs, it gives different outputs
#      (the rule isn't constant).
#   2. Applied to the same input twice (determinism), gives identical
#      outputs — guaranteed; only checked indirectly via the
#      collapse penalty.
#   3. The output preserves enough capacity to feed the next stage
#      (no mono-collapse).
#
# Note: by default this evolves the 'q' rule. The component-tournament
# loop sweeps q/k/v in turn and saves each as its own champion under
# component_slug='projection'.

def _projection_fitness_for(rule_name: str) -> FitnessFn:
    def _f(g: Genome) -> float:
        rule = g[rule_name]
        rng = np.random.default_rng(_FITNESS_RNG_SEED + 7 + ord(rule_name[0]))
        # 8 input grids; project each; score sensitivity + capacity.
        inputs = [rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
                  for _ in range(8)]
        outs = [ca_qkv_project(s, rule, k_ticks=2) for s in inputs]
        flats = [o.flatten().astype(np.int16) for o in outs]
        # Pairwise difference: rule must actually transform inputs.
        pair = []
        for i in range(8):
            for j in range(i + 1, 8):
                pair.append(int((flats[i] != flats[j]).sum()))
        sensitivity = float(np.mean(pair)) / 256.0
        # Identity-ish penalty: if output ≈ input (rule is no-op), score 0.
        no_op = float(np.mean([(s == o).mean()
                                  for s, o in zip(inputs, outs)]))
        # Capacity:
        capacity = float(np.mean([len(np.unique(o)) for o in outs])) / 4.0
        return sensitivity + 0.3 * capacity - 0.4 * no_op
    return _f


PROJECTION_FITNESS = _projection_fitness_for('q')
Q_PROJ_FITNESS    = _projection_fitness_for('q')
K_PROJ_FITNESS    = _projection_fitness_for('k')
V_PROJ_FITNESS    = _projection_fitness_for('v')


# ── MIX (solo) — pair-mixing rule ────────────────────────────────────
#
# The mix rule is applied to (V[best_j] XOR state[i]) inside
# self-attention's readout.  A good mix rule should:
#   1. Actually transform the XOR input (not be the identity).
#   2. Produce outputs that vary with both Q and V inputs.
#   3. Not collapse the grid.

def MIX_FITNESS(g: 'Genome') -> float:
    rule = g['mix']
    rng = np.random.default_rng(_FITNESS_RNG_SEED + 13)
    pairs = []
    for trial in range(6):
        a = rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
        b = rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
        xored = (a ^ b) & 3
        mixed = hex_ca_step(xored, rule)
        pairs.append((xored, mixed))
    # Sensitivity = mean Hamming(mixed) across pairs.
    flats = [m.flatten() for _, m in pairs]
    pair_diff = []
    for i in range(len(flats)):
        for j in range(i + 1, len(flats)):
            pair_diff.append(int((flats[i] != flats[j]).sum()))
    sensitivity = float(np.mean(pair_diff)) / 256.0
    # Non-identity = mixed should differ from xored input.
    work = float(np.mean([(x != m).mean() for x, m in pairs]))
    # Capacity = uses all 4 colours.
    capacity = float(np.mean([len(np.unique(m)) for _, m in pairs])) / 4.0
    # Collapse penalty.
    n_collapsed = sum(1 for _, m in pairs if len(np.unique(m)) == 1)
    collapse_pen = 0.3 * (n_collapsed / len(pairs))
    return sensitivity + 0.5 * work + 0.2 * capacity - collapse_pen


# ── MERGE (solo) — residual blend ────────────────────────────────────
#
# Merge takes (state_a stacked-vertically-with state_b) and runs one tick,
# returning the top half. A good merge rule should:
#   1. Mix info from both halves (not just copy one).
#   2. Sensitivity to swaps.
#   3. Capacity preserved.

# ── CA-BANK — routed-CA composition (selector + 4 sub-rules) ─────────
#
# 5 evolvable rules: bank_selector + bank_0..bank_3.  The bank is
# scored as a *unit* — what we want is a routed CA whose output is
# (a) sensitive to which input it sees, (b) different across inputs
# (the router actually routes), (c) non-collapsing.  And critically:
# (d) the router actually exercises all 4 banks across an input
# distribution — a router that always picks bank_0 isn't a router.

def CA_BANK_FITNESS(g: 'Genome') -> float:
    needed = ('bank_selector', 'bank_0', 'bank_1', 'bank_2', 'bank_3')
    for n in needed:
        if n not in g:
            raise ValueError(f'ca_bank genome missing {n!r}')
    rng = np.random.default_rng(_FITNESS_RNG_SEED + 31)
    bank = [g['bank_0'], g['bank_1'], g['bank_2'], g['bank_3']]
    sel  = g['bank_selector']
    # 4 random inputs; route each through the bank.
    inputs  = [rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
                for _ in range(4)]
    outs    = [ca_bank_step(s, sel, bank) for s in inputs]
    # (a) sensitivity: outputs differ.
    flats = [o.flatten() for o in outs]
    pair = []
    for i in range(4):
        for j in range(i + 1, 4):
            pair.append(int((flats[i] != flats[j]).sum()))
    sensitivity = float(np.mean(pair)) / 256.0
    # (b) bank-utilisation: count how many of the 4 banks actually
    #     contributed cells across the test inputs.  selector counts
    #     are 0..3 for each cell of each input.
    sel_counts = np.zeros(4, dtype=np.int64)
    for s in inputs:
        sg = hex_ca_step(s, sel)
        for c in range(4):
            sel_counts[c] += int((sg == c).sum())
    used = int((sel_counts > 0).sum())   # 1..4
    routing = used / 4.0                  # → 1.0 if all 4 banks used
    # (c) capacity + (d) collapse penalty.
    cap = float(np.mean([len(np.unique(o)) for o in outs])) / 4.0
    n_collapsed = sum(1 for o in outs if len(np.unique(o)) == 1)
    collapse_pen = 0.3 * (n_collapsed / 4.0)
    return sensitivity + 0.6 * routing + 0.2 * cap - collapse_pen


def MERGE_FITNESS(g: 'Genome') -> float:
    rule = g['merge']
    rng = np.random.default_rng(_FITNESS_RNG_SEED + 17)
    a = rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
    b = rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
    c = rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
    # merge(a, b) and merge(a, c): outputs should differ → b matters.
    stacked_ab = np.vstack([a, b])
    stacked_ac = np.vstack([a, c])
    out_ab = hex_ca_step(stacked_ab, rule)[:16]
    out_ac = hex_ca_step(stacked_ac, rule)[:16]
    b_matters = float((out_ab != out_ac).mean())   # 0..1
    # Asymmetry: merge(a, b) should differ from merge(b, a) — otherwise
    # the merge isn't really blending positionally.
    stacked_ba = np.vstack([b, a])
    out_ba = hex_ca_step(stacked_ba, rule)[:16]
    asym = float((out_ab != out_ba).mean())
    # Capacity.
    cap = len(np.unique(out_ab)) / 4.0
    # Collapse.
    coll = 0.5 if len(np.unique(out_ab)) == 1 else 0.0
    return b_matters + 0.3 * asym + 0.2 * cap - coll


# ── SELF_ATTENTION (composite: q + k + v + score + mix) ──────────────
#
# Composite metric.  Run the full self-attention forward pass on a
# 4-token sequence built from distinct token grids.  A good attention
# bundle:
#   1. Produces an output that's sensitive to position (token i's
#      attended output differs from token j's, for i ≠ j).
#   2. Produces an output that's sensitive to *content* — swapping
#      two tokens in the sequence changes the per-position outputs.
#   3. Doesn't collapse.

def _attention_random_states(seed: int, n: int = 4) -> List[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [rng.integers(0, 4, size=(16, 16)).astype(np.uint8)
            for _ in range(n)]


def SELF_ATTENTION_FITNESS(g: Genome) -> float:
    needed = ('q', 'k', 'v', 'score', 'mix')
    for n in needed:
        if n not in g:
            raise ValueError(f'self_attention genome missing {n!r}')
    states_a = _attention_random_states(_FITNESS_RNG_SEED + 11, n=4)
    states_b = [states_a[1], states_a[0], states_a[2], states_a[3]]
    # Forward both.
    out_a = ca_self_attention(
        states_a, q_rule=g['q'], k_rule=g['k'], v_rule=g['v'],
        score_rule=g['score'], mix_rule=g['mix'])
    out_b = ca_self_attention(
        states_b, q_rule=g['q'], k_rule=g['k'], v_rule=g['v'],
        score_rule=g['score'], mix_rule=g['mix'])
    # Per-position sensitivity within a sequence (position 0 vs 1).
    pos_diff = float((out_a[0] != out_a[1]).mean())
    # Content sensitivity: swapping tokens 0 and 1 should change at
    # least one of the attended outputs.
    content_diff = float(np.mean([
        (out_a[i] != out_b[i]).mean() for i in range(4)
    ]))
    # Capacity: don't collapse.
    capacity = float(np.mean([len(np.unique(o)) for o in out_a + out_b])) / 4.0
    # Collapse penalty: any single output mono-colour costs a lot.
    n_collapsed = sum(1 for o in out_a + out_b if len(np.unique(o)) == 1)
    collapse_pen = 0.3 * (n_collapsed / 8.0)
    return pos_diff + content_diff + 0.2 * capacity - collapse_pen


# ── TRANSFORMER BLOCK (composite: 7 rules q/k/v/score/mix/merge/mlp) ─
#
# Full single-block forward pass — composite metric.  Build a
# 4-token sequence, run through one block (with default embed/norm/
# output for unevolved rules), check the result is sensitive to
# the input and doesn't collapse.

def _block_forward_once(g: Genome, states: List[np.ndarray]) -> List[np.ndarray]:
    """One block: pre-norm + attention + residual_merge + pre-norm +
    mlp + residual_merge.  Uses g['norm'] for both pre-norms."""
    from .primitives import default_norm_rule
    norm = g.get('norm', default_norm_rule())
    out = []
    # Pre-norm each token, run attention.
    normed = [ca_layer_norm_iterative(s, norm_rule=norm) for s in states]
    attended = ca_self_attention(
        normed, q_rule=g['q'], k_rule=g['k'], v_rule=g['v'],
        score_rule=g['score'], mix_rule=g['mix'])
    # Residual 1.
    after_res1 = [ca_residual_merge(s, a, merge_rule=g['merge'])
                  for s, a in zip(states, attended)]
    # Pre-norm 2 + MLP + residual 2.
    from .primitives import ca_mlp
    for s in after_res1:
        normed_s = ca_layer_norm_iterative(s, norm_rule=norm)
        mlp_out  = ca_mlp(normed_s, rule_table=g['mlp'], k_ticks=2)
        out.append(ca_residual_merge(s, mlp_out, merge_rule=g['merge']))
    return out


def TRANSFORMER_FITNESS(g: Genome) -> float:
    needed = ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')
    for n in needed:
        if n not in g:
            raise ValueError(f'transformer genome missing {n!r}')
    states = _attention_random_states(_FITNESS_RNG_SEED + 23, n=4)
    out = _block_forward_once(g, states)
    # Sensitivity: outputs differ across positions.
    pos_diff = float(np.mean([(out[i] != out[j]).mean()
                                 for i in range(4) for j in range(i + 1, 4)]))
    # Input-tracking: outputs differ from inputs (block is doing work).
    work = float(np.mean([(s != o).mean() for s, o in zip(states, out)]))
    # Capacity.
    capacity = float(np.mean([len(np.unique(o)) for o in out])) / 4.0
    n_collapsed = sum(1 for o in out if len(np.unique(o)) == 1)
    collapse_pen = 0.3 * (n_collapsed / 4.0)
    return pos_diff + 0.5 * work + 0.2 * capacity - collapse_pen


# ── COMPONENT REGISTRY ──────────────────────────────────────────────
#
# For each of the 8 components: which rules it evolves (one or more)
# and the fitness function that scores a candidate genome.
#
# The autotournament loop in ``caformer.component_tournament`` is the
# single consumer of this dict.

@dataclass(frozen=True)
class ComponentSpec:
    slug:        str
    rules:       Tuple[str, ...]      # which rule names this component evolves
    fitness:     FitnessFn
    description: str


COMPONENT_SPECS: Dict[str, ComponentSpec] = {
    'embedding': ComponentSpec(
        slug='embedding', rules=('embed',), fitness=EMBED_FITNESS,
        description='Token ids → distinct, non-collapsed 16×16 grids.'),
    'layer_norm': ComponentSpec(
        slug='layer_norm', rules=('norm',), fitness=NORM_FITNESS,
        description='Unbalanced input → flatter colour histogram after ticks.'),
    'self_attention': ComponentSpec(
        slug='self_attention', rules=('q', 'k', 'v', 'score', 'mix'),
        fitness=SELF_ATTENTION_FITNESS,
        description='Attended output sensitive to position + content swap.'),
    'projection': ComponentSpec(
        slug='projection', rules=('q',), fitness=PROJECTION_FITNESS,
        description='Q projection map: different inputs → different outputs, '
                    'not the identity.'),
    'mlp': ComponentSpec(
        slug='mlp', rules=('mlp',), fitness=MLP_FITNESS,
        description='Changes state without collapsing to single colour.'),
    'transformer': ComponentSpec(
        slug='transformer',
        rules=('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp'),
        fitness=TRANSFORMER_FITNESS,
        description='Full block forward: sensitive to position + does work.'),
    'softmax': ComponentSpec(
        slug='softmax', rules=('output',), fitness=OUTPUT_HEAD_FITNESS,
        description='Logits peaked + responsive: argmax varies with input.'),
    'output': ComponentSpec(
        slug='output', rules=('output',), fitness=OUTPUT_HEAD_FITNESS,
        description='Final output head: distinct argmax across inputs.'),

    # ── Sub-CA component types ────────────────────────────────────
    # Each isolated projection rule gets its own focused fitness so
    # the library can include specialists, not just composite-evolved
    # bundles.  Use `_proj`/`_solo` suffix to distinguish from the
    # joint-evolved self_attention bundle's sub-rules.
    'q_proj':     ComponentSpec(
        slug='q_proj',     rules=('q',),     fitness=Q_PROJ_FITNESS,
        description='Q projection rule, evolved in isolation.'),
    'k_proj':     ComponentSpec(
        slug='k_proj',     rules=('k',),     fitness=K_PROJ_FITNESS,
        description='K projection rule, evolved in isolation.'),
    'v_proj':     ComponentSpec(
        slug='v_proj',     rules=('v',),     fitness=V_PROJ_FITNESS,
        description='V projection rule, evolved in isolation.'),
    'score_solo': ComponentSpec(
        slug='score_solo', rules=('score',), fitness=ATTENTION_SCORE_FITNESS,
        description='Attention-score rule alone (stddev across K panel).'),
    'mix_solo':   ComponentSpec(
        slug='mix_solo',   rules=('mix',),   fitness=MIX_FITNESS,
        description='Attention-mix rule alone (V⊕state → attended).'),
    'merge_solo': ComponentSpec(
        slug='merge_solo', rules=('merge',), fitness=MERGE_FITNESS,
        description='Residual-merge rule alone (blend two stacked halves).'),

    # ── CA-as-index composition ───────────────────────────────────
    # 5 rules together: a selector that picks which of 4 sub-CAs
    # applies per cell.  Evolves as a unit so the router and banks
    # co-tune.  Use cases: routed MLP, gated attention, "expert"
    # specialisations.  Each evolved bank instance is a *5-tuple*
    # the library can compose with elsewhere.
    'ca_bank':    ComponentSpec(
        slug='ca_bank',
        rules=('bank_selector', 'bank_0', 'bank_1', 'bank_2', 'bank_3'),
        fitness=CA_BANK_FITNESS,
        description='Routed-CA bank: 1 selector + 4 sub-CAs, '
                    'co-evolved so the router actually routes.'),
}

# Iteration order for the autotournament loop's round-robin.  Lighter
# (single-rule) components first so the first few cycles produce
# visible progress quickly; composite components last.  The sub-CA
# specialists (_proj / _solo / _bank) are interleaved so a default
# rotation hits every type without anyone starving.
COMPONENT_ROTATION = [
    'embedding', 'layer_norm', 'mlp', 'projection',
    'softmax',   'output',     'merge_solo',
    'q_proj',    'k_proj',     'v_proj',
    'score_solo','mix_solo',   'ca_bank',
    'self_attention', 'transformer',
]

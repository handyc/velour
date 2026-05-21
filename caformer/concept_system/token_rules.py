"""Phase-1 experiment: token-as-CA-ruleset.

User daydream 2026-05-21: instead of tokens being string identifiers
into a vocabulary, each token IS a K=4 CA rule.  Combining tokens
becomes a rule cascade.

This module ships the minimal substrate to test the idea:

- ``generate_rule(seed)`` — produce one K=4 7-neighbour LUT
  (16,384 entries) from a deterministic seed.
- ``fire(rule, init_state, n_ticks)`` — run the rule on a
  starting grid, return the final grid.
- ``fingerprint(state)`` — summarise the final grid as a stable
  4-int tuple (the count of each K=4 colour) + the 4 corner cells.
- ``cascade(rules_in_order, init_state, n_ticks_per)`` — fire
  multiple rules in sequence; each subsequent rule sees the
  previous one's final state.

No persistence yet — Phase 1 only generates rules from seeds
deterministically.  The management command
``caformer_token_rules_experiment`` exercises the full
distinctness / composition / decodability checks against the
first N Sanskrit verb roots.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from caformer.router import LUT_SIZE, SIDE
from caformer.primitives import hex_ca_step


# Canonical asymmetric initial state — breaks the symmetry that
# would otherwise let two distinct rules produce identical outputs
# from a uniform start.  Same shape used in byte_router._BASE_STATE
# so the experiment is comparable.
_BASE_STATE = (np.arange(SIDE * SIDE, dtype=np.uint8)
                   .reshape(SIDE, SIDE) & 3)


def generate_rule(seed: int) -> np.ndarray:
    """Produce a deterministic K=4 LUT for the given seed.
    Returns a numpy uint8 array of length LUT_SIZE (16,384)."""
    rng = random.Random(seed)
    arr = np.empty(LUT_SIZE, dtype=np.uint8)
    for i in range(LUT_SIZE):
        arr[i] = rng.randint(0, 3)
    return arr


def fire(rule: np.ndarray, init_state: np.ndarray | None = None,
              n_ticks: int = 4) -> np.ndarray:
    """Fire a rule for ``n_ticks`` on ``init_state`` (or _BASE_STATE
    if None).  Returns the final grid."""
    state = (init_state if init_state is not None else _BASE_STATE).copy()
    for _ in range(n_ticks):
        state = hex_ca_step(state, rule)
    return state


def cascade(rules: Sequence[np.ndarray],
                 init_state: np.ndarray | None = None,
                 n_ticks_per: int = 4) -> np.ndarray:
    """Apply ``rules`` in sequence — each rule sees the previous
    rule's final state as its initial state.  Non-commutative by
    construction."""
    state = (init_state if init_state is not None else _BASE_STATE).copy()
    for rule in rules:
        state = fire(rule, state, n_ticks=n_ticks_per)
    return state


@dataclass(frozen=True)
class Fingerprint:
    """Two stable summaries of a final state:

      histogram — (count_of_0, _1, _2, _3) over the grid.  Sums to
                   side² (64 for 8×8).  Stable across symmetric
                   rotations; not unique per state.
      corners   — (cell00, cell0R, cellC0, cellCR) where R=side-1
                   and C=side-1.  Position-sensitive.

    The combined tuple (histogram + corners) is the experiment's
    distinctness key."""
    histogram: tuple[int, int, int, int]
    corners:   tuple[int, int, int, int]

    def key(self) -> tuple:
        return self.histogram + self.corners


def fingerprint(state: np.ndarray) -> Fingerprint:
    """Compute the (histogram, corners) signature of a final state."""
    flat = state.flatten()
    hist = (int((flat == 0).sum()),
            int((flat == 1).sum()),
            int((flat == 2).sum()),
            int((flat == 3).sum()))
    h, w = state.shape
    corners = (int(state[0, 0]),
               int(state[0, w - 1]),
               int(state[h - 1, 0]),
               int(state[h - 1, w - 1]))
    return Fingerprint(histogram=hist, corners=corners)


# ─── Target encoding ───────────────────────────────────────────────


def string_to_cells(s: str, max_cells: int = SIDE * SIDE) -> np.ndarray:
    """Encode a string as K=4 cell values, MSB-first per byte
    (matches caformer.router.embed_prompt's layout).  4 cells per
    UTF-8 byte; truncated to fit max_cells."""
    raw = s.encode('utf-8')[: max_cells // 4]
    out = np.zeros(max_cells, dtype=np.uint8)
    for i, b in enumerate(raw):
        out[i * 4 + 0] = (b >> 6) & 3
        out[i * 4 + 1] = (b >> 4) & 3
        out[i * 4 + 2] = (b >> 2) & 3
        out[i * 4 + 3] =  b       & 3
    return out


def cells_to_string(cells: np.ndarray, n_bytes: int) -> str:
    """Inverse of string_to_cells: take the first 4*n_bytes K=4
    cells, reassemble bytes, decode as UTF-8 (latin-1 fallback)."""
    raw = bytearray(n_bytes)
    for i in range(n_bytes):
        raw[i] = ((int(cells[i * 4 + 0]) & 3) << 6
                  | (int(cells[i * 4 + 1]) & 3) << 4
                  | (int(cells[i * 4 + 2]) & 3) << 2
                  | (int(cells[i * 4 + 3]) & 3))
    try:
        return bytes(raw).decode('utf-8')
    except UnicodeDecodeError:
        return bytes(raw).decode('latin-1', errors='replace')


# ─── Per-token training ────────────────────────────────────────────


def _mutate_lut(lut: np.ndarray, rng: random.Random,
                     n_flips: int) -> np.ndarray:
    """Flip n_flips entries to a different K=4 value."""
    out = lut.copy()
    for _ in range(n_flips):
        idx = rng.randrange(out.size)
        cur = int(out[idx]) & 3
        nu = rng.randint(0, 3)
        while nu == cur:
            nu = rng.randint(0, 3)
        out[idx] = nu
    return out


def _fitness_self_name(rule: np.ndarray, target_cells: np.ndarray,
                            n_target_cells: int, n_ticks: int) -> int:
    """How many of the first n_target_cells in the fired grid match
    target_cells.  Range [0, n_target_cells].  Perfect = n_target_cells."""
    state = fire(rule, n_ticks=n_ticks)
    flat = state.flatten()
    return int((flat[:n_target_cells] == target_cells[:n_target_cells]).sum())


def train_rule_for_token(token_string: str, *,
                                iters: int = 2000,
                                flips_min: int = 4,
                                flips_max: int = 200,
                                n_ticks: int = 4,
                                seed: int = 0xCA4CA4) -> tuple[np.ndarray, int, int]:
    """Per-token GA: evolve a K=4 LUT so the first 4*len(token_string)
    cells of fire(LUT, base_state, n_ticks) match the token's string
    encoded as K=4 cells.

    Returns (best_rule, best_fit, n_target_cells)."""
    target_cells = string_to_cells(token_string)
    n_target = min(SIDE * SIDE, 4 * len(token_string.encode('utf-8')))
    if n_target == 0:
        return generate_rule(seed), 0, 0

    rng = random.Random(seed ^ hash(token_string) & 0xFFFFFFFF)
    # Seed population with a small set of variants to explore.
    pop = [generate_rule(seed ^ k) for k in range(8)]
    pop_fit = [_fitness_self_name(r, target_cells, n_target, n_ticks)
                for r in pop]
    best_idx = int(np.argmax(pop_fit))
    best_rule = pop[best_idx]
    best_fit  = pop_fit[best_idx]

    for it in range(iters):
        if best_fit >= n_target:
            break
        parent_idx = rng.randrange(len(pop))
        n_flips = rng.randint(flips_min, flips_max)
        child = _mutate_lut(pop[parent_idx], rng, n_flips)
        fit = _fitness_self_name(child, target_cells, n_target, n_ticks)
        # Replace worst on improvement.
        worst_idx = int(np.argmin(pop_fit))
        if fit > pop_fit[worst_idx]:
            pop[worst_idx] = child
            pop_fit[worst_idx] = fit
            if fit > best_fit:
                best_fit = fit
                best_rule = child
    return best_rule, best_fit, n_target


# ─── Persistence ───────────────────────────────────────────────────


import json
import threading
from pathlib import Path

DEFAULT_DIR = '.artifacts/token_rules_v1'


def save_rules(rules: dict[int, np.ndarray], names: dict[int, str],
                  fits: dict[int, tuple[int, int]],
                  model_dir: str | Path = DEFAULT_DIR,
                  merge: bool = True) -> Path:
    """Persist a token_id → rule mapping.  Layout:
      token_<ID>.lut         raw LUT bytes (16,384 each)
      meta.json              {token_id: {name, fit, n_target}}

    When ``merge`` is True (default), existing meta.json is loaded
    and the new entries are layered on top — useful for training
    verbs, preverbs, and suffixes in separate runs."""
    md = Path(model_dir).resolve()
    md.mkdir(parents=True, exist_ok=True)
    meta: dict[str, dict] = {}
    meta_path = md / 'meta.json'
    if merge and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            meta = {}
    for tid, rule in rules.items():
        (md / f'token_{tid:04d}.lut').write_bytes(bytes(rule))
        f, nt = fits.get(tid, (0, 0))
        meta[str(tid)] = {
            'name':     names.get(tid, ''),
            'fit':      int(f),
            'n_target': int(nt),
        }
    meta_path.write_text(json.dumps(meta, indent=2))
    return md


def load_rules(model_dir: str | Path = DEFAULT_DIR
                  ) -> tuple[dict[int, np.ndarray], dict]:
    md = Path(model_dir)
    meta_path = md / 'meta.json'
    if not meta_path.exists():
        raise FileNotFoundError(f'no token_rules meta at {md}')
    meta = json.loads(meta_path.read_text())
    rules: dict[int, np.ndarray] = {}
    for tid_str in meta:
        p = md / f'token_{int(tid_str):04d}.lut'
        if p.exists():
            rules[int(tid_str)] = (np.frombuffer(p.read_bytes(),
                                                  dtype=np.uint8).copy() & 3)
    return rules, meta


_CACHE: dict[str, tuple[dict[int, np.ndarray], dict]] = {}
_LOCK = threading.Lock()


def get_rules(model_dir: str | Path = DEFAULT_DIR):
    """Cached loader.  Returns (rules, meta).  Raises FileNotFoundError
    if no artifact exists yet."""
    key = str(model_dir)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        out = load_rules(model_dir)
        _CACHE[key] = out
        return out


# ─── Concept cascade (Phase 2 integration) ─────────────────────────


# ID offsets — must match the trainer's offsets so saved rules
# are reachable by (kind, original_id).  Kept here to decouple from
# the management-command module.
_ID_OFFSET_VERB    = 0
_ID_OFFSET_PREVERB = 10000
_ID_OFFSET_SUFFIX  = 20000


def cascade_concept(concept,
                          n_ticks: int = 4,
                          model_dir: str | Path = DEFAULT_DIR
                          ) -> dict:
    """Cascade a Sanskrit Concept's (preverb, verb, suffix) rules in
    order on a shared CA state.  Decode the first N cells of the
    final grid as a string — the "compositional surface form" the
    rule cascade produces.

    Returns: {
        surface_target:   '<preverb>-<verb>-<suffix>'    (what we'd want)
        surface_produced: '<decoded from cascade>'       (what the rules say)
        fingerprint:      ((histogram), (corners))
        steps:            list of per-step states (8x8 K=4 grids)
        rules_used:       [token_id, ...] (offset-encoded ids)
        rules_missing:    [token_id, ...] (couldn't load from disk)
    }
    """
    rules, _meta = get_rules(model_dir)
    sequence: list[tuple[int, str]] = []
    if concept.preverb_id:
        from . import preverb_by_id
        p = preverb_by_id(concept.preverb_id)
        if p is not None:
            sequence.append((_ID_OFFSET_PREVERB + p.id, p.form))
    if concept.verb_id:
        from . import verb_by_id
        v = verb_by_id(concept.verb_id)
        if v is not None:
            sequence.append((_ID_OFFSET_VERB + v.id, v.root))
    if concept.suffix_id:
        from . import suffix_by_id
        s = suffix_by_id(concept.suffix_id)
        if s is not None:
            sequence.append((_ID_OFFSET_SUFFIX + s.id,
                             s.form.lstrip('-')))

    surface_target = '-'.join(name for _tid, name in sequence)
    rules_used: list[int] = []
    rules_missing: list[int] = []
    steps: list[np.ndarray] = []

    state = _BASE_STATE.copy()
    for tid, _name in sequence:
        rule = rules.get(tid)
        if rule is None:
            rules_missing.append(tid)
            continue
        state = fire(rule, state, n_ticks=n_ticks)
        rules_used.append(tid)
        steps.append(state.copy())

    # Decode the final state.  Cascade target is the full concatenated
    # surface form (e.g. 'agama' = 5 chars = 20 K=4 cells).
    n_bytes = len(surface_target.replace('-', '').encode('utf-8'))
    n_bytes = max(1, min(n_bytes, SIDE * SIDE // 4))
    produced = cells_to_string(state.flatten(), n_bytes)

    fp = fingerprint(state)
    return {
        'surface_target':   surface_target,
        'surface_produced': produced,
        'fingerprint':      (fp.histogram, fp.corners),
        'rules_used':       rules_used,
        'rules_missing':    rules_missing,
        'n_steps':          len(rules_used),
    }

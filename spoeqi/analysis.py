"""Convergence analysis for spoeqi pacts.

Runs each component CA forward until it either bottoms out into a
uniform-colour state, settles into a period-1 fixed point with
internal structure, or hits ``max_steps`` while still moving.  The
output is the 8×8 grid of bottom-out colours (one per component) +
per-component step counts + status flags.

This is the diagnostic layer the user wanted before we commit to a
"nested image" / quine GA: it tells you, for any existing pact,
which components naturally bottom out and which keep cycling.  The
fitness function for the GA later layers on top of this.

Speed: the step is vectorised over all 64 components with numpy, so
128 steps on a 16×16 grid take ~20 ms on a laptop.  The hex
neighbour offsets are pre-computed once per ``side`` and cached.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

import numpy as np

from .models import COMPONENTS, RULE_TABLE_SIZE, Pact
from . import keystream


# ─── neighbour-index cache ───────────────────────────────────────────

_NBR_CACHE: dict[int, np.ndarray] = {}


def _hex_neighbour_indices(side: int) -> np.ndarray:
    """Return ``(side*side, 6)`` int32 array of flat neighbour indices
    for offset-r pointy-top hex with the same n0..n5 order
    ``keystream._step`` uses (TR, R, BR, BL, L, TL)."""
    if side in _NBR_CACHE:
        return _NBR_CACHE[side]
    H = W = side
    out = np.zeros((H * W, 6), dtype=np.int32)
    for y in range(H):
        shift = y & 1
        tlx_off = -1 + shift
        brx_off =  0 + shift
        yU = (y - 1) % H
        yD = (y + 1) % H
        for x in range(W):
            xL  = (x - 1) % W
            xR  = (x + 1) % W
            xTL = (x + tlx_off) % W
            xBR = (x + brx_off) % W
            i = y * W + x
            out[i, 0] = yU * W + xBR     # n0
            out[i, 1] = y  * W + xR      # n1
            out[i, 2] = yD * W + xBR     # n2
            out[i, 3] = yD * W + xTL     # n3
            out[i, 4] = y  * W + xL      # n4
            out[i, 5] = yU * W + xTL     # n5
    _NBR_CACHE[side] = out
    return out


# ─── step ────────────────────────────────────────────────────────────

def _step_all(state: np.ndarray, rules: np.ndarray,
               nbr_idx: np.ndarray) -> np.ndarray:
    """One generation of all 64 components in parallel.

    state    : (64, area)    uint8
    rules    : (64, 16384)   uint8
    nbr_idx  : (area, 6)     int32

    Returns  : (64, area)    uint8 — same shape as state.
    """
    self_ = state.astype(np.int32)                # (64, area)
    n = state[:, nbr_idx].astype(np.int32)         # (64, area, 6)
    key = ((self_ << 12)
            | (n[:, :, 0] << 10)
            | (n[:, :, 1] <<  8)
            | (n[:, :, 2] <<  6)
            | (n[:, :, 3] <<  4)
            | (n[:, :, 4] <<  2)
            |  n[:, :, 5])
    new = np.take_along_axis(rules, key, axis=1)  # (64, area)
    return new.astype(np.uint8)


# ─── fingerprint ─────────────────────────────────────────────────────

# Per-pact result cache so a reload of the detail page doesn't re-run
# the same 128 steps.  Keyed on (pact.pk, seed+rule fingerprint, side,
# max_steps) so any seal-affecting edit invalidates automatically.
_RESULT_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_RESULT_CACHE_LIMIT = 32


def _cache_key(pact: Pact, max_steps: int) -> tuple:
    h = hashlib.sha256()
    h.update(bytes(pact.seed_matrix or b''))
    h.update(bytes(pact.rule_snapshot or b''))
    if pact.rules_snapshot:
        h.update(bytes(pact.rules_snapshot))
    if pact.initial_grids:
        # JSON-serialised initial_grids change the gen-0 state, so they
        # change the fingerprint too.
        import json
        h.update(json.dumps(pact.initial_grids).encode())
    return (pact.pk, h.hexdigest(), pact.component_grid, max_steps)


def convergence_fingerprint(pact: Pact, *, max_steps: int = 128) -> dict:
    """Return the bottom-out fingerprint for ``pact``.

    Schema:

      {
        'components': [
            {'colour': 0..3 | None, 'status': 'uniform' | 'stable' | 'cycling',
             'step': int},
            ... × 64
        ],
        'bitmap':         [[entry, ...] × 8, ... × 8],
        'n_uniform':      int,
        'n_stable':       int,    # period-1 fixed points with structure
        'n_cycling':      int,    # neither uniform nor period-1 fixed
        'max_steps':      int,
      }

    ``components`` is in component-index order (0..63).  ``bitmap`` is
    the same 64 entries arranged as the 8×8 macro grid (row = c // 8,
    col = c % 8) the detail viewer uses.
    """
    key = _cache_key(pact, max_steps)
    cached = _RESULT_CACHE.get(key)
    if cached is not None:
        _RESULT_CACHE.move_to_end(key)
        return cached

    side = pact.component_grid
    area = side * side
    initial = np.frombuffer(
        keystream.initial_multi_grid(pact), dtype=np.uint8
    ).reshape(COMPONENTS, area).copy()
    rules = np.frombuffer(
        pact.per_component_rules(), dtype=np.uint8
    ).reshape(COMPONENTS, RULE_TABLE_SIZE)
    nbr_idx = _hex_neighbour_indices(side)

    state = initial
    converged = np.zeros(COMPONENTS, dtype=bool)
    stable    = np.zeros(COMPONENTS, dtype=bool)
    colours    = np.full(COMPONENTS, -1, dtype=np.int8)
    step_taken = np.full(COMPONENTS, max_steps, dtype=np.int32)

    # Initial uniformity check — some pacts (e.g. album with a flat
    # source) start already uniform; record step=0 in that case.
    init_uniform = (initial == initial[:, :1]).all(axis=1)
    for c in np.where(init_uniform)[0]:
        colours[c] = int(initial[c, 0])
        step_taken[c] = 0
        converged[c] = True

    for t in range(1, max_steps + 1):
        if converged.all():
            break
        new = _step_all(state, rules, nbr_idx)
        active = ~converged
        # Uniform: every cell in the component equals the first cell.
        unif = ((new == new[:, :1]).all(axis=1)) & active
        idx_unif = np.where(unif)[0]
        if idx_unif.size:
            colours[idx_unif] = new[idx_unif, 0]
            step_taken[idx_unif] = t
            converged[idx_unif] = True
        # Period-1 fixed point (state didn't change this step), but
        # not all-uniform.  We only record the first hit for each
        # component.
        same = ((new == state).all(axis=1)) & active & ~unif
        new_stable = same & ~stable
        if new_stable.any():
            idx_st = np.where(new_stable)[0]
            stable[idx_st] = True
            step_taken[idx_st] = t
        state = new

    n_uniform = int(converged.sum())
    n_stable  = int((stable & ~converged).sum())
    n_cycling = COMPONENTS - n_uniform - n_stable

    components = []
    for c in range(COMPONENTS):
        if converged[c]:
            status = 'uniform'
            colour = int(colours[c])
        elif stable[c]:
            status = 'stable'
            colour = None
        else:
            status = 'cycling'
            colour = None
        components.append({
            'component': c,
            'colour': colour,
            'status': status,
            'step': int(step_taken[c]),
        })

    # 8 × 8 macro grid: c = row*8 + col (matches detail.html's drawTile).
    bitmap = [[components[r * 8 + col] for col in range(8)] for r in range(8)]

    result = {
        'components': components,
        'bitmap':     bitmap,
        'n_uniform':  n_uniform,
        'n_stable':   n_stable,
        'n_cycling':  n_cycling,
        'max_steps':  max_steps,
    }

    _RESULT_CACHE[key] = result
    _RESULT_CACHE.move_to_end(key)
    while len(_RESULT_CACHE) > _RESULT_CACHE_LIMIT:
        _RESULT_CACHE.popitem(last=False)
    return result


def cache_clear() -> None:
    """Drop the analysis cache; tests use this to force recomputation."""
    _RESULT_CACHE.clear()

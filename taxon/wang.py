"""Wang-tile + CA buffer-band composition experiment.

Shared between the `wang_proto` management command and the
`/taxon/wang/` view. The runner is deterministic on (rule, params,
seed) — same inputs always produce the same trajectories.

Three modes correspond to the three branches of the composition
theorem:

    natural  — no boundary forcing. Tiles must keep the buffer band
               clean by virtue of the rule + initial state alone.
               Composition theorem holds iff the rule is permissive.
    pin_outer — after every step force the *outer* buffer of standalone
               and the outer ring of the 2x2 join back to zero. The
               internal seams of the join run free, so joined dynamics
               drift from standalone (which never saw a non-zero
               neighbor at its boundary).
    pin_all  — also pin the internal seams of the join. Restores
               standalone≡joined identity at the cost of zero
               cross-tile signal flow.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from automaton.packed import PackedRuleset
from .engine import _step


MODES = ('natural', 'pin_outer', 'pin_all')


@dataclass
class Params:
    size: int = 16
    buffer: int = 3
    steps: int = 12
    candidates: int = 200
    density: float = 0.10
    seed: int = 42
    stable_color: int | None = None
    mode: str = 'natural'

    def validate(self) -> None:
        if self.size < 6 or self.size > 64:
            raise ValueError('tile size must be between 6 and 64')
        if self.buffer < 1 or self.buffer * 2 >= self.size:
            raise ValueError('buffer must be ≥1 and < size/2')
        if self.steps < 1 or self.steps > 60:
            raise ValueError('steps must be between 1 and 60')
        if self.candidates < 1 or self.candidates > 2000:
            raise ValueError('candidates must be between 1 and 2000')
        if not (0.0 < self.density <= 1.0):
            raise ValueError('density must be in (0, 1]')
        if self.mode not in MODES:
            raise ValueError(f'mode must be one of {MODES}')


# ---------- low-level helpers ----------

def buffer_mask(size: int, buffer: int) -> np.ndarray:
    """Boolean mask of buffer-band cells in a single tile."""
    m = np.zeros((size, size), dtype=bool)
    m[:buffer, :] = True
    m[-buffer:, :] = True
    m[:, :buffer] = True
    m[:, -buffer:] = True
    return m


def make_tile(rng: np.random.Generator, size: int, buffer: int,
              density: float, n_colors: int = 4,
              stable_color: int | None = None) -> np.ndarray:
    g = np.zeros((size, size), dtype=np.uint8)
    inner = size - 2 * buffer
    if inner <= 0:
        return g
    if stable_color is None:
        interior = rng.integers(0, n_colors,
                                size=(inner, inner), dtype=np.uint8)
        mask = rng.random((inner, inner)) > density
        interior[mask] = 0
    else:
        interior = ((rng.random((inner, inner)) < density)
                    .astype(np.uint8) * stable_color)
    g[buffer:buffer + inner, buffer:buffer + inner] = interior
    return g


def simulate_with_pin(grid: np.ndarray, packed: PackedRuleset,
                      steps: int,
                      pin_mask: np.ndarray | None) -> np.ndarray:
    traj = np.zeros((steps + 1,) + grid.shape, dtype=np.uint8)
    traj[0] = grid
    g = grid
    for t in range(steps):
        g = _step(g, packed)
        if pin_mask is not None:
            g = g.copy()
            g[pin_mask] = 0
        traj[t + 1] = g
    return traj


def compose_2x2(tiles: list[np.ndarray]) -> np.ndarray:
    a, b, c, d = tiles
    return np.concatenate(
        [np.concatenate([a, b], axis=1),
         np.concatenate([c, d], axis=1)], axis=0)


def max_buffer_leak(traj: np.ndarray, mask: np.ndarray) -> int:
    leak = 0
    for t in range(traj.shape[0]):
        n = int(((traj[t] != 0) & mask).sum())
        if n > leak:
            leak = n
    return leak


# ---------- top-level runner ----------

def run_experiment(packed: PackedRuleset, params: Params) -> dict:
    """Run the experiment and return a JSON-friendly result dict.

    The dict contains:
        rule:       packed.n_colors, sha (caller adds), quiescent flag
        params:     echo of the input parameters
        candidates: total candidates evaluated
        clean:      number of buffer-clean candidates
        tiles:      list of 4 tile dicts: {initial, traj_standalone}
        joined:     {initial, traj}
        diffs:      list of 4 lists (per-step diff counts inside each tile)
        seam_leak:  total non-zero cells on internal seams across timesteps
        verdict:    'identical' | 'drift' | 'failed'
    """
    params.validate()
    if packed.get(0, [0] * 6) != 0 and params.mode == 'natural':
        # natural mode requires quiescent zero — otherwise even an
        # all-zero tile becomes non-zero on step 1.
        raise ValueError(
            'rule is not quiescent on zero — only pin_outer or '
            'pin_all modes will work for it.')

    size = params.size
    buffer = params.buffer
    steps = params.steps
    rng = np.random.default_rng(params.seed)
    bmask = buffer_mask(size, buffer)
    pin_mask = bmask if params.mode in ('pin_outer', 'pin_all') else None

    # --- 1. search for buffer-clean candidates ----------------------
    clean: list[tuple[int, int, np.ndarray, np.ndarray]] = []
    for i in range(params.candidates):
        tile = make_tile(rng, size, buffer, params.density,
                         n_colors=packed.n_colors,
                         stable_color=params.stable_color)
        traj = simulate_with_pin(tile, packed, steps, pin_mask=pin_mask)
        if max_buffer_leak(traj, bmask) == 0 and (tile != 0).any():
            motion = int((traj[steps] != traj[0]).sum())
            clean.append((i, motion, tile, traj))

    if len(clean) < 4:
        return {
            'ok': False,
            'reason': (f'only {len(clean)} buffer-clean tiles found in '
                       f'{params.candidates} candidates — try a different '
                       f'rule, higher --candidates, or --pin-buffer.'),
            'candidates': params.candidates,
            'clean': len(clean),
            'mode': params.mode,
        }

    clean.sort(key=lambda t: -t[1])
    chosen = clean[:4]
    tiles = [c[2] for c in chosen]
    standalone_trajs = [c[3] for c in chosen]
    motions = [c[1] for c in chosen]
    candidate_ids = [c[0] for c in chosen]

    # --- 2. compose 2x2 and simulate --------------------------------
    joined = compose_2x2(tiles)
    if pin_mask is not None:
        join_pin = np.zeros((2 * size, 2 * size), dtype=bool)
        join_pin[:buffer, :] = True
        join_pin[-buffer:, :] = True
        join_pin[:, :buffer] = True
        join_pin[:, -buffer:] = True
        if params.mode == 'pin_all':
            join_pin[size - buffer:size + buffer, :] = True
            join_pin[:, size - buffer:size + buffer] = True
    else:
        join_pin = None
    joined_traj = simulate_with_pin(joined, packed, steps, pin_mask=join_pin)

    # --- 3. measurements --------------------------------------------
    H = W = size
    offsets = [(0, 0), (0, W), (H, 0), (H, W)]
    diffs: list[list[int]] = []
    embedded_trajs: list[np.ndarray] = []
    for slot, (dr, dc) in enumerate(offsets):
        embedded = joined_traj[:, dr:dr + H, dc:dc + W]
        embedded_trajs.append(embedded)
        d = (embedded != standalone_trajs[slot]).sum(axis=(1, 2))
        diffs.append([int(x) for x in d])

    seam_total = 0
    for t in range(joined_traj.shape[0]):
        seam_total += int((joined_traj[t, :, W - 1] != 0).sum())
        seam_total += int((joined_traj[t, :, W] != 0).sum())
        seam_total += int((joined_traj[t, H - 1, :] != 0).sum())
        seam_total += int((joined_traj[t, H, :] != 0).sum())

    sum_diffs = sum(sum(row) for row in diffs)
    if sum_diffs == 0 and seam_total == 0:
        verdict = 'identical'
    elif sum_diffs == 0 and seam_total > 0:
        verdict = 'identical-with-seam-traffic'
    else:
        verdict = 'drift'

    return {
        'ok': True,
        'mode': params.mode,
        'size': size,
        'buffer': buffer,
        'steps': steps,
        'candidates': params.candidates,
        'clean': len(clean),
        'tiles': [
            {'initial': t.tolist(),
             'traj': st.tolist(),
             'motion': m,
             'candidate_id': cid}
            for t, st, m, cid in zip(tiles, standalone_trajs, motions,
                                     candidate_ids)
        ],
        'joined': {
            'initial': joined.tolist(),
            'traj': joined_traj.tolist(),
        },
        'diffs': diffs,
        'seam_total': seam_total,
        'verdict': verdict,
    }

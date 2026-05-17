"""spoeqi/metachain — Metapact core: rulesets that evolve rulesets.

The insight: a 128×128 K=4 hex CA state is exactly 16,384 cells of
4 colours each, which is exactly the bit count of a K=4 hex rule
table (4^7 = 16,384 entries, 2 bits each).  So the CA's *state* IS
a complete *rule* for the next CA — no encoding loss, no padding.

A Metapact is a small recipe (16,384 seed bytes + depth + a couple
knobs) that deterministically expands to a chain of CA rule tables.
At depth 10 the chain bottoms out as a full caformer model — both
pact-holders chat with the same model without ever shipping the
~160 KB of weights.

We classify each level with a cheap heuristic (~10 ms) and reward
GA solutions whose chains stay class-4 (edge of chaos) all the way
down AND whose leaf caformer actually predicts text above uniform.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from caformer.primitives import hex_ca_step


GRID_SIDE = 128
GRID_AREA = GRID_SIDE * GRID_SIDE
RULE_SIZE = 4 ** 7              # 16,384 entries
assert GRID_AREA == RULE_SIZE, 'metachain math relies on 128*128 == 4^7'


def _initial_grid(seed_state: bytes) -> np.ndarray:
    """Reshape 16,384 seed bytes into a 128×128 K=4 grid (mod 4)."""
    arr = np.frombuffer(seed_state, dtype=np.uint8).copy() & 3
    if arr.size != GRID_AREA:
        raise ValueError(
            f'seed_state must be {GRID_AREA} bytes; got {arr.size}')
    return arr.reshape(GRID_SIDE, GRID_SIDE)


def _run_ca(grid: np.ndarray, rule_bytes: bytes,
             ticks: int) -> Tuple[np.ndarray, list]:
    """Run rule on grid for `ticks` steps. Returns (final_grid, activity_log).
    activity_log[t] = fraction of cells that changed at step t."""
    rule_arr = np.frombuffer(rule_bytes, dtype=np.uint8)
    if rule_arr.size != RULE_SIZE:
        raise ValueError(
            f'rule must be {RULE_SIZE} bytes; got {rule_arr.size}')
    state = grid.copy() & 3
    activity = []
    for _ in range(ticks):
        prev = state
        state = hex_ca_step(state, rule_arr)
        activity.append(float((state != prev).sum()) / state.size)
    return state, activity


# ─── Cheap Wolfram-class estimator ────────────────────────────────────
#
# Goal: ~5-15 ms per rule so a GA can call this thousands of times.
# Trades accuracy for speed; finalists get re-classified with the
# full taxon classifier later.

_PROBE_INIT: Optional[bytes] = None


def _probe_init_grid() -> np.ndarray:
    """Fixed deterministic 128×128 init for classification — pure
    pseudo-random bytes from an LCG keyed by a fixed sentinel. We
    used to use a structured checker pattern, but that biased almost
    every rule toward "class 4" because the checker pre-seeded
    structure. Random init is the standard probe for Wolfram
    classification."""
    global _PROBE_INIT
    if _PROBE_INIT is None:
        state = np.uint32(0xCA1ED175)
        out = np.empty(GRID_AREA, dtype=np.uint8)
        for i in range(GRID_AREA):
            state = np.uint32(state * 1664525 + 1013904223)
            out[i] = (state >> np.uint32(16)) & np.uint8(3)
        _PROBE_INIT = bytes(out)
    return _initial_grid(_PROBE_INIT)


def classify_rule(rule_bytes: bytes, *,
                    probe_ticks: int = 24,
                    init_grid: Optional[np.ndarray] = None
                    ) -> Tuple[int, float]:
    """Cheap heuristic Wolfram class + continuous class-4-ness score.

    Returns (class_int, class4_score) where:
      class_int    ∈ {1, 2, 3, 4}     — discrete bucket for reporting
      class4_score ∈ [0, 1]            — continuous "how close to edge
                                          of chaos"; the GA optimises
                                          against this to escape the
                                          all-class-3 plateau of
                                          random K=4 hex rules.

    Class-4-ness is 1.0 for a structured, moderately-active rule with
    asymmetric colour distribution; 0.0 for purely chaotic noise or
    collapsed uniform states; intermediate values bridge the two —
    so even a "barely interesting" rule produces nonzero gradient
    for the GA to climb.
    """
    rule_arr = np.frombuffer(rule_bytes, dtype=np.uint8)
    if rule_arr.size != RULE_SIZE:
        raise ValueError(
            f'rule must be {RULE_SIZE} bytes; got {rule_arr.size}')

    state = (init_grid if init_grid is not None else _probe_init_grid()
              ).copy() & 3

    seen = {}
    activity = []
    cycle_period = 0
    for t in range(probe_ticks):
        prev = state
        state = hex_ca_step(state, rule_arr)
        h = hashlib.sha256(state.tobytes()).digest()[:16]
        if h in seen:
            cycle_period = t - seen[h]
            break
        seen[h] = t
        activity.append(float((state != prev).sum()) / state.size)

    counts = np.bincount(state.flatten(), minlength=4)
    max_dom_frac = counts.max() / state.size
    mean_act = float(np.mean(activity[len(activity)//2:])) if activity else 0.0
    color_entropy = float(
        -sum((c / state.size) * np.log2(max(c / state.size, 1e-9))
              for c in counts))

    # Discrete class for reporting.
    if max_dom_frac > 0.95 or mean_act < 0.005:
        cls = 1
    elif 0 < cycle_period <= 6:
        cls = 2
    elif cycle_period > 6:
        cls = 4
    elif mean_act > 0.70 and color_entropy > 1.95:
        cls = 3
    else:
        cls = 4

    # Continuous class-4-ness score: smooth approval for moderate
    # activity, asymmetric colour distribution, no short cycle.
    # Components in [0, 1], multiplied → score in [0, 1].
    def _bell(x, center, width):
        """Smooth bell ~1 at center, ~0 outside ±2·width."""
        return float(np.exp(-((x - center) / max(width, 1e-9)) ** 2))

    activity_score = _bell(mean_act, 0.45, 0.20)
    # max colour entropy = log2(4) = 2.  Class-4 rules sit a little
    # below max (asymmetric); class-3 rules sit at max (uniform-ish).
    entropy_score = _bell(color_entropy, 1.85, 0.20)
    cycle_score = 0.0 if 0 < cycle_period <= 6 else 1.0
    not_collapsed = 0.0 if max_dom_frac > 0.95 else 1.0

    score = (activity_score * entropy_score * cycle_score * not_collapsed)
    return cls, float(score)


def quick_class_estimate(rule_bytes: bytes, **kw) -> int:
    """Backwards-compat shim: just the discrete class."""
    return classify_rule(rule_bytes, **kw)[0]


def quick_class4_score(rule_bytes: bytes, **kw) -> float:
    """Just the continuous class-4-ness score (for GA fitness)."""
    return classify_rule(rule_bytes, **kw)[1]


# ─── Self-reproduction score ─────────────────────────────────────────
#
# 4^7 = 16,384 = 128² exactly, so a K=4 hex rule's 16,384-entry LUT
# lays out as a 128×128 grid with no padding.  Use that grid as the
# rule's own initial state, run the rule, see how much survives.  A
# rule that reproduces itself produces, by construction, an identical
# next level — so any class-4 self-reproducer is automatically a
# class-4 generator of a class-4 (the user's "dumb fix").


def self_reproduce_score(seed_state: bytes, *,
                           ticks: int = 64) -> float:
    """Return hamming similarity ∈ [0, 1] between the rule's LUT-as-
    image initial state and the grid after ``ticks`` CA steps of the
    rule applied to that initial state.  1.0 = perfect fixed point;
    random K=4 baseline = ~0.25.
    """
    rule_arr = np.frombuffer(seed_state, dtype=np.uint8).copy() & 3
    if rule_arr.size != RULE_SIZE:
        raise ValueError(
            f'seed_state must be {RULE_SIZE} bytes; got {rule_arr.size}')
    init = rule_arr.reshape(GRID_SIDE, GRID_SIDE)
    state = init.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, rule_arr)
    return float((state == init).sum() / state.size)


def walk_quine_surface(start_seed: bytes, *,
                         sr_ticks: int = 16,
                         sr_threshold: float = 0.99,
                         sample_size: int = 2048,
                         passes: int = 4,
                         rng_seed: int = 0xC51E_F00D,
                         on_step=None) -> dict:
    """Coordinate descent along the quine manifold.

    Starts from ``start_seed`` (typically the identity rule, which has
    SR=1.0 but is class-1).  For each pass, samples ``sample_size``
    LUT entries; for each entry tries all 3 alternative cell values
    and accepts a flip if it keeps ``self_reproduce_score >=
    sr_threshold`` AND raises ``classify_rule``'s class-4 score.

    Returns the walk summary: starting/final SR + class-4 score, the
    final seed, and the count of accepted flips per pass.

    Default sample_size=2048 × 3 flips × 4 passes × ~13ms/eval ≈ 5 min.
    Drop ``sr_threshold`` (eg 0.9) to permit larger surface area at
    the cost of weaker quine guarantee.
    """
    import time
    arr = bytearray(np.frombuffer(start_seed, dtype=np.uint8).copy() & 3)
    if len(arr) != RULE_SIZE:
        raise ValueError(
            f'start_seed must be {RULE_SIZE} bytes; got {len(arr)}')
    rng = np.random.default_rng(rng_seed)
    fire = on_step or (lambda *_a, **_kw: None)

    def _sr(rule_bytes: bytes) -> float:
        return self_reproduce_score(rule_bytes, ticks=sr_ticks)

    cur_seed = bytes(arr)
    cur_sr   = _sr(cur_seed)
    cur_cls, cur_score = classify_rule(cur_seed, probe_ticks=24)

    fire('begin', {'sr': cur_sr, 'class': cur_cls, 'class4': cur_score,
                     'sample_size': sample_size, 'passes': passes})

    history = []
    t0 = time.time()
    for p in range(passes):
        accepted = 0
        evaluated = 0
        idxs = rng.choice(RULE_SIZE, size=min(sample_size, RULE_SIZE),
                            replace=False)
        for k in idxs:
            original = arr[k]
            best_alt = None
            best_score = cur_score
            best_sr = cur_sr
            for alt in (0, 1, 2, 3):
                if alt == original:
                    continue
                arr[k] = alt
                cand = bytes(arr)
                sr = _sr(cand)
                evaluated += 1
                if sr < sr_threshold:
                    continue
                _, sc = classify_rule(cand, probe_ticks=16)
                if sc > best_score:
                    best_alt   = alt
                    best_score = sc
                    best_sr    = sr
            if best_alt is not None:
                arr[k]    = best_alt
                cur_score = best_score
                cur_sr    = best_sr
                accepted += 1
            else:
                arr[k] = original
        cur_seed = bytes(arr)
        cur_cls, _ = classify_rule(cur_seed, probe_ticks=24)
        history.append({'pass': p, 'accepted': accepted,
                          'evaluated': evaluated,
                          'sr': cur_sr, 'class': cur_cls,
                          'class4': cur_score,
                          'elapsed_s': time.time() - t0})
        fire('pass_end', history[-1])

    return {
        'final_seed':   cur_seed,
        'final_sr':     cur_sr,
        'final_class':  cur_cls,
        'final_class4': cur_score,
        'history':      history,
        'total_evals':  sum(h['evaluated'] for h in history),
        'total_accepts': sum(h['accepted'] for h in history),
        'elapsed_s':    time.time() - t0,
    }


# ─── Class-4 quine discovery toolkit ─────────────────────────────────
#
# Promoted from /tmp/quine_search/ scripts after the empirical finding
# (2026-05-16) that block-flip-from-identity + hill-climb reliably
# produces class-4 partial quines (SR≈0.42, c4≈0.85, probe-activity
# 0.35).  These helpers do the discovery + chain analysis end-to-end
# so the browser surface can call them without subprocess overhead.


def probe_activity(rule_bytes: bytes, *, ticks: int = 20) -> float:
    """Mean per-tick change rate on the standard probe init grid.
    Class-1 ~ 0; class-2 ~ 0.01-0.05; class-3 ~ 0.5+; class-4 ~ 0.1-0.5."""
    rule_arr = np.frombuffer(rule_bytes, dtype=np.uint8).copy() & 3
    probe = _probe_init_grid().copy()
    acts = []
    for _ in range(ticks):
        prev = probe.copy()
        probe = hex_ca_step(probe, rule_arr)
        acts.append(float((probe != prev).sum()) / probe.size)
    return float(np.mean(acts[len(acts)//2:]))


def sr_arbitrary_sigma(seed_bytes: bytes, *, ticks: int = 16) -> float:
    """Max-SR over all 16,384! position permutations σ.

    Closed form: ``Σᵥ min(h_init[v], h_final[v]) / N`` where h is the
    cell-value histogram of (initial, final) image.  Catches every
    histogram-preserving "quine modulo σ" — much more permissive than
    strict SR but useful for chain-of-quines hunting (see
    project_nested_class4_quines).
    """
    arr = np.frombuffer(seed_bytes, dtype=np.uint8) & 3
    init = arr.reshape(GRID_SIDE, GRID_SIDE)
    state = init.copy()
    for _ in range(ticks):
        state = hex_ca_step(state, arr)
    h_init = np.bincount(init.flatten(), minlength=4)
    h_final = np.bincount(state.flatten(), minlength=4)
    return float(np.minimum(h_init, h_final).sum()) / float(init.size)


def block_flip_search(*, n_trials: int = 300, sr_min: float = 0.30,
                        activity_band: Tuple[float, float] = (0.05, 0.5),
                        sr_ticks: int = 16, rng_seed: int = 0xDEADBEEF,
                        on_progress=None) -> List[dict]:
    """Block-flip-from-identity sweep that's the entry point to the
    class-4 partial-quine recipe.  For each trial:

    1. Start with the identity rule (LUT[k] = (k >> 12) & 3).
    2. Replace ``n_blocks`` contiguous chunks of ``block_size`` LUT
       entries with uniform random K=4 bytes; pick both from a small
       set per trial.
    3. Compute SR + class4-score + probe activity.
    4. Keep if SR > ``sr_min`` AND activity is in the class-4 band.

    Returns a list of dicts (sorted by composite ``2*sr + c4 + band``):
        {trial, block, n_blocks, sr, c4, act, seed}

    Reliable: ~10-15% of trials are keepers in the default range.
    Tunable knob: ``n_trials`` (default 300, ~5 s).
    """
    identity = ((np.arange(RULE_SIZE, dtype=np.uint16) >> 12) & 3).astype(np.uint8)
    rng = np.random.default_rng(rng_seed)
    keepers: List[dict] = []
    fire = on_progress or (lambda *_a, **_kw: None)
    for trial in range(n_trials):
        block_size = int(rng.choice([128, 256, 512, 1024, 2048, 4096]))
        n_blocks   = int(rng.choice([2, 4, 8, 16, 32]))
        rule = identity.copy()
        for _ in range(n_blocks):
            start = int(rng.integers(0, max(1, RULE_SIZE - block_size)))
            rule[start:start + block_size] = rng.integers(
                0, 4, size=block_size, dtype=np.uint8)
        seed = bytes(rule.tolist())
        sr = self_reproduce_score(seed, ticks=sr_ticks)
        if sr <= sr_min:
            continue
        act = probe_activity(seed, ticks=12)
        if not (activity_band[0] < act < activity_band[1]):
            continue
        _, c4 = classify_rule(seed, probe_ticks=16)
        keepers.append({
            'trial':    trial,
            'block':    block_size,
            'n_blocks': n_blocks,
            'sr':       sr,
            'c4':       c4,
            'act':      act,
            'seed':     seed,
        })
        fire(trial, len(keepers), n_trials)
    # Composite ranking: SR weighted, class-4 character bonus, in-band
    # bonus.  Same ordering used in the /tmp/quine_search/ scripts.
    def composite(k):
        band_bonus = 1.0 if 0.1 < k['act'] < 0.4 else 0.5
        return 2 * k['sr'] + k['c4'] + band_bonus
    keepers.sort(key=composite, reverse=True)
    return keepers


def hill_climb_quine(seed_bytes: bytes, *,
                       passes: int = 3, sample_size: int = 1024,
                       sr_weight: float = 2.0, c4_weight: float = 0.5,
                       activity_band: Tuple[float, float] = (0.05, 0.5),
                       rng_seed: int = 7,
                       on_pass=None) -> dict:
    """Single-byte coordinate descent that refines a block-flip
    starting point.  Composite objective:
        sr_weight * SR  +  c4_weight * c4_score  -  band_penalty

    Returns:
        {'seed': final bytes, 'sr': final SR, 'c4': ..., 'act': ...,
         'history': [{'pass': i, 'accepted': n, ...}, ...]}
    """
    import time
    arr = bytearray(np.frombuffer(seed_bytes, dtype=np.uint8).copy() & 3)
    rng = np.random.default_rng(rng_seed)

    def _score(arr_local):
        sb = bytes(arr_local)
        sr = self_reproduce_score(sb, ticks=16)
        _, c4 = classify_rule(sb, probe_ticks=16)
        act = probe_activity(sb, ticks=12)
        pen = 0.0
        if act < activity_band[0] or act > activity_band[1]:
            pen = 0.5
        return sr_weight * sr + c4_weight * c4 - pen, sr, c4, act

    best_score, best_sr, best_c4, best_act = _score(arr)
    history = []
    t0 = time.time()
    for p in range(passes):
        accepted = 0
        idxs = rng.choice(RULE_SIZE, size=min(sample_size, RULE_SIZE),
                            replace=False)
        for k in idxs:
            original = int(arr[k])
            local_best_score, local_best_alt = best_score, original
            for alt in range(4):
                if alt == original:
                    continue
                arr[k] = alt
                sc, _, _, _ = _score(arr)
                if sc > local_best_score:
                    local_best_score, local_best_alt = sc, alt
            arr[k] = local_best_alt
            if local_best_alt != original:
                accepted += 1
                best_score = local_best_score
        _, best_sr, best_c4, best_act = _score(arr)
        entry = {'pass': p, 'accepted': accepted,
                   'sr': best_sr, 'c4': best_c4, 'act': best_act,
                   'elapsed_s': time.time() - t0}
        history.append(entry)
        if on_pass is not None:
            on_pass(entry)
    return {
        'seed':    bytes(arr),
        'sr':      best_sr,
        'c4':      best_c4,
        'act':     best_act,
        'history': history,
    }


def walk_chain(seed_bytes: bytes, *, depth: int = 30,
                 ticks_per_level: int = 16) -> dict:
    """Walk the metachain from ``seed_bytes`` and report each level's
    SR (strict + arbitrary-σ), class, c4 score, and activity.  Detects
    cycles via short SHA-256 hashes.

    Returns:
        {'levels': [{'level': i, 'sr_strict': ..., 'sr_arbsigma': ...,
                       'class': ..., 'c4': ..., 'act': ...,
                       'histogram': '...', 'cycle_period': int|None},
                      ...],
         'final_seed':       bytes of the last level reached,
         'class4_run_length': max consecutive class-4 levels at start.}
    """
    import hashlib
    cur = seed_bytes
    levels = []
    seen = {}
    class4_run = 0
    streak_active = True
    for i in range(depth):
        sr_s = self_reproduce_score(cur, ticks=16)
        sr_arb = sr_arbitrary_sigma(cur, ticks=16)
        cls, c4 = classify_rule(cur, probe_ticks=16)
        act = probe_activity(cur, ticks=12)
        h = np.bincount(np.frombuffer(cur, dtype=np.uint8) & 3, minlength=4)
        h_str = '/'.join(str(int(x)) for x in h)
        digest = hashlib.sha256(cur).hexdigest()[:12]
        cycle = None
        if digest in seen:
            cycle = i - seen[digest]
            levels.append({'level': i, 'sr_strict': sr_s, 'sr_arbsigma': sr_arb,
                              'class': cls, 'c4': c4, 'act': act,
                              'histogram': h_str, 'cycle_period': cycle})
            break
        seen[digest] = i
        levels.append({'level': i, 'sr_strict': sr_s, 'sr_arbsigma': sr_arb,
                          'class': cls, 'c4': c4, 'act': act,
                          'histogram': h_str, 'cycle_period': None})
        # Class-4 streak from level 1 onward (skip L0 which is the seed,
        # often not a quine itself but generates a chain that is).
        if streak_active and i > 0:
            if cls == 4 and activity_band_ok(act):
                class4_run += 1
            else:
                streak_active = False
        # Next level
        rule_arr = np.frombuffer(cur, dtype=np.uint8).copy() & 3
        state = rule_arr.reshape(GRID_SIDE, GRID_SIDE).copy()
        for _ in range(ticks_per_level):
            state = hex_ca_step(state, rule_arr)
        cur = bytes(state.flatten().tolist())
    return {
        'levels':            levels,
        'final_seed':        cur,
        'class4_run_length': class4_run,
    }


def activity_band_ok(act: float) -> bool:
    return 0.05 < act < 0.7


def unpack_k4_bytes(packed: bytes) -> bytes:
    """Inverse of :func:`pack_k4_stream`.  Expands ``len(packed)`` dense
    bytes back into ``4 × len(packed)`` cell bytes ∈ {0, 1, 2, 3}.

    Same on-disk data, different *view*: when the spoeqi DB stores 16 KB
    of packed bytes you can read them as 16 KB of "file content" OR as
    65,536 K=4 cells for UI masks (visibility regions, palette indices,
    state machines with up to 4 states).  The unpacking is one numpy
    op, so doing it lazily on every read costs effectively nothing.
    """
    a = np.frombuffer(packed, dtype=np.uint8)
    out = np.empty(a.size * 4, dtype=np.uint8)
    out[0::4] =  a       & 3
    out[1::4] = (a >> 2) & 3
    out[2::4] = (a >> 4) & 3
    out[3::4] = (a >> 6) & 3
    return out.tobytes()


def pack_k4_stream(raw: bytes) -> bytes:
    """Pack a K=4 (2-bit) cell stream into dense 8-bit bytes.

    Each output byte carries four cells, low cell in bits 0-1 and high
    cell in bits 6-7.  Reduces the on-disk size by 4× and turns the
    output into "real" 8-bit data — every output bit varies, which is
    what a downstream consumer (compression dictionaries, key streams,
    Monte-Carlo seeds, etc.) actually wants.

    The unpacked encoding has 75% of every byte wasted (top six bits
    always zero).  A pack pass is essentially free and is the format
    that should be exposed to researchers by default.

    Input length must be a multiple of 4.  Pads the tail with zero
    cells if not.
    """
    a = np.frombuffer(raw, dtype=np.uint8) & 3
    if a.size % 4:
        a = np.concatenate([a, np.zeros(4 - (a.size % 4), dtype=np.uint8)])
    a = a.reshape(-1, 4)
    packed = (a[:, 0] | (a[:, 1] << 2) | (a[:, 2] << 4) | (a[:, 3] << 6))
    return packed.astype(np.uint8).tobytes()


def run_ca_stream(rule_bytes: bytes, *, init_seed: int,
                    ticks: int = 64,
                    packed: bool = False) -> bytes:
    """Run ``rule_bytes`` (16,384-byte K=4 hex CA LUT) on a 128×128
    grid for ``ticks`` ticks, starting from an LCG-seeded init grid.

    Default return is the concatenated post-tick states at one byte
    per cell — ``ticks × 16,384`` bytes.  Pass ``packed=True`` to get
    the dense 4-cells-per-byte form (``ticks × 4,096`` bytes), which
    is what researchers should use when treating the output as actual
    file data (every bit varies; no wasted high bits).
    Deterministic in ``(rule_bytes, init_seed, ticks, packed)``.
    """
    rule_arr = np.frombuffer(rule_bytes, dtype=np.uint8).copy() & 3
    if rule_arr.size != RULE_SIZE:
        raise ValueError(f'rule must be {RULE_SIZE} bytes; got {rule_arr.size}')
    # LCG-seeded init.  Matches the deterministic-probe pattern from
    # _probe_init_grid (numerically the same constants).
    s = np.uint32(init_seed & 0xFFFFFFFF)
    init = np.empty(GRID_AREA, dtype=np.uint8)
    for j in range(GRID_AREA):
        s = np.uint32(s * 1664525 + 1013904223)
        init[j] = (s >> np.uint32(16)) & np.uint8(3)
    state = init.reshape(GRID_SIDE, GRID_SIDE)
    out = bytearray()
    for _ in range(max(1, int(ticks))):
        state = hex_ca_step(state, rule_arr)
        out.extend(state.flatten().tolist())
    raw = bytes(out)
    return pack_k4_stream(raw) if packed else raw


def chain_seeds(seed_bytes: bytes, *, depth: int = 64,
                  ticks_per_level: int = 16) -> List[bytes]:
    """Return the per-level seed bytes for the first ``depth`` levels
    of the metachain.  Level 0 is the input seed; level i is produced
    by running level (i-1)'s rule on its own LUT-as-image for
    ``ticks_per_level`` ticks.

    If the chain cycles before reaching ``depth``, the returned list
    has fewer entries (the cycle-closing level is included once).
    Callers wanting exactly ``depth`` entries can wrap with
    cycle-extending logic.
    """
    import hashlib
    cur = seed_bytes
    out: List[bytes] = []
    seen = set()
    for _ in range(depth):
        digest = hashlib.sha256(cur).hexdigest()[:12]
        if digest in seen:
            out.append(cur)   # the cycle-closing level
            break
        seen.add(digest)
        out.append(cur)
        rule_arr = np.frombuffer(cur, dtype=np.uint8).copy() & 3
        state = rule_arr.reshape(GRID_SIDE, GRID_SIDE).copy()
        for _ in range(ticks_per_level):
            state = hex_ca_step(state, rule_arr)
        cur = bytes(state.flatten().tolist())
    return out


# ─── Metachain expansion ─────────────────────────────────────────────

@dataclass
class ChainResult:
    states:   List[bytes]        # 16,384 bytes per level
    classes:  List[int]          # 1..4 per level
    scores:   List[float]        # continuous class-4-ness per level [0,1]
    depth_class4: int            # consecutive class-4 prefix length

    @property
    def depth(self) -> int:
        return len(self.states)

    @property
    def chain_quality(self) -> float:
        """Sum of class-4 scores across levels — the GA's gradient
        signal. Higher = more levels stayed near edge-of-chaos."""
        return float(sum(self.scores))

    def as_bytes(self) -> bytes:
        """Flat byte stream: all levels concatenated.  Downstream apps
        (caframe, other metachains, caformer) slice this however they
        like."""
        return b''.join(self.states)


def metachain_expand(seed_state: bytes, *,
                       depth: int = 10,
                       chain_ticks: int = 32,
                       stop_on_non_class4: bool = False) -> ChainResult:
    """Expand a metachain from seed_state.

    Level 0: seed_state IS the rule.  Classify it.  Run it on a
             deterministic probe grid for chain_ticks steps to produce
             the next level's rule.
    Level i: previous level's output is the rule.  Classify, run,
             produce level i+1's rule.

    With stop_on_non_class4=True, we halt as soon as a non-class-4
    level appears.  Otherwise we always produce `depth` levels and
    the caller reads `depth_class4` (consecutive class-4 prefix) or
    `chain_quality` (sum of continuous scores, never zero) for the
    GA fitness.
    """
    if len(seed_state) != GRID_AREA:
        raise ValueError(
            f'seed_state must be {GRID_AREA} bytes; got {len(seed_state)}')

    cls0, sc0 = classify_rule(seed_state)
    states: List[bytes] = [seed_state]
    classes: List[int] = [cls0]
    scores: List[float] = [sc0]

    if stop_on_non_class4 and cls0 != 4:
        return ChainResult(states=states, classes=classes, scores=scores,
                             depth_class4=0)

    init = _probe_init_grid()
    for level in range(1, depth):
        current_rule = states[-1]
        final_grid, _ = _run_ca(init, current_rule, chain_ticks)
        new_state = final_grid.tobytes()
        cls, sc = classify_rule(new_state)
        states.append(new_state); classes.append(cls); scores.append(sc)
        if stop_on_non_class4 and cls != 4:
            break

    d4 = 0
    for c in classes:
        if c == 4:
            d4 += 1
        else:
            break
    return ChainResult(states=states, classes=classes, scores=scores,
                         depth_class4=d4)


# ─── Leaf adapter: chain bytes → caformer model ──────────────────────

CAFORMER_RULE_ORDER = [
    'q', 'k', 'v', 'score', 'mix', 'merge', 'mlp', 'norm', 'output', 'embed',
]


def metachain_to_caformer_genome(states: List[bytes]) -> dict:
    """Map the first 10 chain levels to caformer's 10 rule tables.

    Returns a dict {name: np.ndarray(uint8, size=16,384)} that
    `caformer.transformer.ca_forward_qkv` can accept directly via
    its block_rules / embed_rule / norm_rule / output_rule kwargs.

    If `states` has fewer than 10 entries, missing slots wrap from
    the start (so a depth-7 chain still produces *some* caformer
    model; the GA's job is to push depth up to 10).
    """
    if not states:
        raise ValueError('need at least one state')
    out = {}
    for i, name in enumerate(CAFORMER_RULE_ORDER):
        src = states[i % len(states)]
        out[name] = np.frombuffer(src, dtype=np.uint8).copy() & 3
    return out


def caformer_kwargs_from_chain(chain: ChainResult, *, n_blocks: int = 1):
    """Convenience: build ``ca_forward_qkv`` kwargs from a chain.
    The same block rules are reused for every block (matches what
    the TrainedModel loader does)."""
    g = metachain_to_caformer_genome(chain.states)
    block = {'q': g['q'], 'k': g['k'], 'v': g['v'],
              'score': g['score'], 'mix': g['mix'], 'merge': g['merge'],
              'mlp': g['mlp']}
    return {
        'embed_rule':  g['embed'],
        'block_rules': [block] * n_blocks,
        'norm_rule':   g['norm'],
        'output_rule': g['output'],
    }

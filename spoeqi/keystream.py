"""Python-side keystream tap for spoeqi pacts.

Mirrors the JS engine in templates/spoeqi/detail.html bit-for-bit so
the server can derive the same per-component CA state at any
generation the viewer can.  That's load-bearing for the Phase 1.5
"data pipe" idea: any operator that runs server-side (encrypt some
text, pick from a list, sample a Codex section, …) needs to read
deterministic bytes off a component's stream at a specified
generation, and Alice and Bob both have to be able to do that
independently.

What we expose:
- ``initial_multi_grid(pact)``    → 64 × side² bytes, the seed-expanded
                                     state of every component at gen 0
- ``advance(state, generations, pact)`` → step the CA forward
- ``tap(pact, component, generation, n_bytes)`` → deterministic bytes,
                                     SHA-256-chained for long taps

Implementation notes:
- splitmix64 + xoshiro128** mirror the JS in templates/spoeqi/detail.html
- Tick uses the same 14-bit lookup ``(self << 12) | (n0..5)`` with
  offset-r topology, same neighbour order [TR, R, BR, BL, L, TL].
- Single in-memory cache keyed by ``pact.id`` holds the latest
  multi-grid state.  Survives within a single dev-server process;
  fine for MVP, replace with persistent checkpoints if we ship.
"""

from __future__ import annotations
import hashlib
import struct
from collections import OrderedDict
from typing import Dict, Tuple

from .models import COMPONENTS, RULE_TABLE_SIZE, Pact


M32 = 0xFFFFFFFF
M64 = 0xFFFFFFFFFFFFFFFF


# ───────────────────── RNG primitives ──────────────────────────────

def _splitmix64(state: int) -> Tuple[int, int]:
    """One call of splitmix64.  Returns (new_state, output)."""
    state = (state + 0x9E3779B97F4A7C15) & M64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
    z = (z ^ (z >> 31)) & M64
    return state, z


def _make_xoshiro128ss(byte_seed: int) -> list:
    """Init xoshiro128** state by drawing 4 splitmix64 outputs and
    taking the low 32 bits of each.  Matches the JS init:
    ``var w0 = s[1], w1 = s[3], w2 = s[5], w3 = s[7];`` where the
    indexing exposed the low halves of four 64-bit outputs."""
    state = byte_seed & 0xFF
    words = []
    for _ in range(4):
        state, out = _splitmix64(state)
        words.append(out & M32)
    # Guard against an all-zero state (xoshiro fails on it).
    if not any(words):
        words = [0x9E3779B9, 0x7F4A7C15, 0, 0]
    return words


def _xoshiro_next(s: list) -> int:
    """One uniform 32-bit output from xoshiro128**.  Mutates `s`."""
    x = (s[1] * 5) & M32
    rotated = (((x << 7) & M32) | (x >> 25)) & M32
    result = (rotated * 9) & M32

    t = (s[1] << 9) & M32
    s[2] ^= s[0]
    s[3] ^= s[1]
    s[1] ^= s[2]
    s[0] ^= s[3]
    s[2] ^= t
    s[3] = (((s[3] << 11) & M32) | (s[3] >> 21)) & M32
    return result


def seed_grid(byte_seed: int, grid_side: int) -> bytes:
    """Expand one seed byte → ``grid_side²`` 4-state cells.  Matches
    the JS ``seedGrid()`` exactly: each xoshiro draw fills 4 cells
    (low → high bit pairs).
    """
    state = _make_xoshiro128ss(byte_seed)
    n = grid_side * grid_side
    g = bytearray(n)
    for i in range(0, n, 4):
        r = _xoshiro_next(state)
        g[i] = r & 3
        if i + 1 < n:
            g[i + 1] = (r >> 2) & 3
        if i + 2 < n:
            g[i + 2] = (r >> 4) & 3
        if i + 3 < n:
            g[i + 3] = (r >> 6) & 3
    return bytes(g)


# ───────────────────── CA tick ─────────────────────────────────────

def initial_multi_grid(pact: Pact) -> bytes:
    """64 × side² bytes — the state of every component at generation
    0.  Two paths:

    - Default: expand each ``seed_matrix[c]`` byte into ``side²`` cells
      via xoshiro128**.  This is what the JS viewer paints on first
      load.
    - Album-seeded pact: ``pact.initial_grids`` carries the explicit
      gen-0 cell state for each component (a list of 64 lists of
      ``side²`` ints in 0..3).  Used when the pact was created from
      a cover-image album so gen 0 literally renders as the album.
    """
    side = pact.component_grid
    area = side * side
    if pact.initial_grids:
        ig = pact.initial_grids
        if len(ig) != COMPONENTS:
            raise ValueError(
                f'initial_grids has {len(ig)} components, expected {COMPONENTS}')
        out = bytearray()
        for c, grid in enumerate(ig):
            if len(grid) != area:
                raise ValueError(
                    f'initial_grids[{c}] has {len(grid)} cells, expected {area}')
            for v in grid:
                if not 0 <= v < 4:
                    raise ValueError(
                        f'initial_grids[{c}] contains {v}; expected 0..3')
            out += bytes(grid)
        return bytes(out)
    seed = bytes(pact.seed_matrix)
    out = bytearray()
    for c in range(COMPONENTS):
        out += seed_grid(seed[c], side)
    return bytes(out)


def _step(state: bytes, side: int, rules_flat: bytes) -> bytes:
    """One generation of all 64 components, returned as a new bytes
    blob.  ``rules_flat`` is 64 × 16384 bytes."""
    out = bytearray(len(state))
    W = H = side
    area = W * H
    for c in range(COMPONENTS):
        base = c * area
        rule_base = c * RULE_TABLE_SIZE
        for y in range(H):
            shift = y & 1
            tlx_off = -1 + shift
            brx_off =  0 + shift
            yU = (y - 1) % H
            yD = (y + 1) % H
            for x in range(W):
                idx = base + y * W + x
                self_ = state[idx]
                xL  = (x - 1) % W
                xR  = (x + 1) % W
                xTL = (x + tlx_off) % W
                xBR = (x + brx_off) % W
                n0 = state[base + yU * W + xBR]
                n1 = state[base + y  * W + xR]
                n2 = state[base + yD * W + xBR]
                n3 = state[base + yD * W + xTL]
                n4 = state[base + y  * W + xL]
                n5 = state[base + yU * W + xTL]
                key = ((self_ << 12) | (n0 << 10) | (n1 << 8) | (n2 << 6)
                        | (n3 << 4) | (n4 << 2) | n5)
                out[idx] = rules_flat[rule_base + key]
    return bytes(out)


def advance(state: bytes, generations: int, pact: Pact) -> bytes:
    """Step `state` forward `generations` ticks.  Pure-Python loop —
    fine for the gen counts a single tap call needs (<= a few thousand)
    but the bottleneck if Phase 2 wants live streaming."""
    if generations <= 0:
        return state
    rules_flat = pact.per_component_rules()
    side = pact.component_grid
    for _ in range(generations):
        state = _step(state, side, rules_flat)
    return state


# ───────────────────── In-memory cache ─────────────────────────────

_CACHE_LIMIT = 32
_CACHE: "OrderedDict[int, Tuple[int, bytes]]" = OrderedDict()


def _cache_get(pact_id: int):
    if pact_id in _CACHE:
        _CACHE.move_to_end(pact_id)
        return _CACHE[pact_id]
    return None


def _cache_set(pact_id: int, gen: int, state: bytes) -> None:
    _CACHE[pact_id] = (gen, state)
    _CACHE.move_to_end(pact_id)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)


def cache_clear() -> None:
    _CACHE.clear()


# ───────────────────── Tap ─────────────────────────────────────────

# A safety budget so a single endpoint call can't pin the worker.  At
# 16×16 grid and pure-Python step ≈ 8 ms / tick, 2000 ticks ≈ 16 s.
# Endpoint rejects target_gen > current_cache + ADVANCE_CAP.
ADVANCE_CAP = 2000


class AdvanceCapExceeded(Exception):
    """Raised when a tap asks to step further than ADVANCE_CAP from
    the most recently cached state.  Caller can retry incrementally."""


def get_state_at(pact: Pact, target_gen: int) -> bytes:
    """Materialise the multi-grid state at exactly ``target_gen``,
    advancing from the cached state when possible.  Caches the result.
    """
    if target_gen < 0:
        raise ValueError('generation must be ≥ 0')
    cached = _cache_get(pact.id)
    if cached is None:
        state, gen = initial_multi_grid(pact), 0
    else:
        gen, state = cached
        if gen > target_gen:
            # Caller wants a generation we've already advanced past.
            # Restart from zero.
            state, gen = initial_multi_grid(pact), 0
    delta = target_gen - gen
    if delta == 0:
        _cache_set(pact.id, gen, state)
        return state
    if delta > ADVANCE_CAP:
        raise AdvanceCapExceeded(
            f'requested generation {target_gen} is {delta} ticks past the '
            f'cache (cap is {ADVANCE_CAP} per call); '
            f'retry with smaller generation, then again.')
    state = advance(state, delta, pact)
    _cache_set(pact.id, target_gen, state)
    return state


DOMAIN_DEFAULT  = b'spoeqi-tap/1'
DOMAIN_ROUTER   = b'spoeqi-tap/router/1'
DOMAIN_ENVELOPE = b'spoeqi-envelope/1'


def tap(pact: Pact, component: int, generation: int, n_bytes: int,
        domain: bytes = DOMAIN_DEFAULT) -> bytes:
    """Return `n_bytes` of deterministic keystream from component `c`
    at generation `g`.

    Construction:
        h_i = SHA-256(domain || component(LE u32) || generation(LE u64)
                     || counter(LE u32) || grid[component] )
        keystream = h_0 || h_1 || …  (truncated to n_bytes)

    Domains let callers carve disjoint output spaces from the same
    (component, generation) — e.g. ``DOMAIN_ROUTER`` for MoE router
    weights so they don't overlap with an expert's LoRA bytes when
    the router and the expert share a component index.
    """
    if not (0 <= component < COMPONENTS):
        raise ValueError(f'component must be 0..{COMPONENTS - 1}')
    if n_bytes < 0 or n_bytes > 1 << 20:
        raise ValueError('n_bytes must be 0..1048576')

    state = get_state_at(pact, generation)
    side = pact.component_grid
    area = side * side
    base = component * area
    grid_slice = state[base:base + area]

    out = bytearray()
    counter = 0
    while len(out) < n_bytes:
        h = hashlib.sha256()
        h.update(domain)
        h.update(struct.pack('<IQI', component, generation, counter))
        h.update(grid_slice)
        out.extend(h.digest())
        counter += 1
    return bytes(out[:n_bytes])

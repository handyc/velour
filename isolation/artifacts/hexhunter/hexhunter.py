"""Pure-Python port of libhexhunter.

Mirrors the C library byte-for-byte: same Park-Miller LCG, same
2-bit packing, same hex topology, same smooth-tent class-4 fitness,
same insertion-sort + tournament breeding.  A run with the same
config + rng_seed produces the *same* 4096-byte ruleset as the C
implementation (verified with `verify_against_c.py`).

Slow compared to C — pure-Python loops over a 14×14 grid for 25
ticks × population × generations.  Default config (POP=30, GENS=40)
takes ~30 s in CPython 3.12.  For larger sweeps, prefer the C
library; the Python port exists so the algorithm is portable to
any environment that runs Python — Jupyter notebooks, micropython
sketches, sandboxed REPLs.

Usage::

    from hexhunter import hexhunter, hexhunter_refine, fitness

    out = hexhunter()                     # all defaults
    out = hexhunter(population=8, generations=4, rng_seed=7)

    refined = hexhunter_refine(out, generations=10)
    print(fitness(refined))
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional

K              = 4
NSIT           = 16384
GENOME_BYTES   = 4096

DEF_POP                = 30
DEF_GENS               = 40
DEF_INIT_MUT_RATE      = 0.05
DEF_BREED_MUT_RATE     = 0.005
DEF_GRID_W             = 14
DEF_GRID_H             = 14
DEF_HORIZON            = 25
DEF_RNG_SEED           = 42

DY  = (-1, -1,  0,  0,  1,  1)
DXE = ( 0,  1, -1,  1, -1,  0)
DXO = (-1,  0, -1,  1,  0,  1)


# ── RNG (matches the C `hh_rng_t` / `lcg_state` exactly) ──────────────

class _Rng:
    """Park-Miller-style LCG bit-for-bit compatible with hexhunter.c."""
    __slots__ = ('state',)

    def __init__(self, seed: int):
        self.state = (seed if seed != 0 else 1) & 0xFFFFFFFF

    def u32(self) -> int:
        self.state = (self.state * 1103515245 + 12345) & 0xFFFFFFFF
        return self.state >> 16

    def rand(self) -> int:
        """Same shape as the C `hh_rand`: 0..0xFFFF."""
        return self.u32() & 0xFFFF

    def rand_unit(self) -> float:
        return self.rand() / 0xFFFF


_RAND_MAX = 0xFFFF


# ── Packed-genome helpers (2 bits per situation, K=4) ────────────────

def g_get(g: bytearray, idx: int) -> int:
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3

def g_set(g: bytearray, idx: int, v: int) -> None:
    b = idx >> 2
    o = (idx & 3) * 2
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o)

def _sit_idx(self_: int, n: list[int]) -> int:
    i = self_
    for k in range(6):
        i = i * K + n[k]
    return i


# ── Hex stepping ─────────────────────────────────────────────────────

def _step_grid(g: bytearray, src: bytearray, dst: bytearray,
               gw: int, gh: int) -> None:
    n = [0] * 6
    for y in range(gh):
        dx = DXO if (y & 1) else DXE
        for x in range(gw):
            self_ = src[y * gw + x]
            for k in range(6):
                yy = y + DY[k]
                xx = x + dx[k]
                if 0 <= yy < gh and 0 <= xx < gw:
                    n[k] = src[yy * gw + xx]
                else:
                    n[k] = 0
            dst[y * gw + x] = g_get(g, _sit_idx(self_, n))


def _seed_grid(grid: bytearray, gw: int, gh: int, seed: int) -> None:
    r = _Rng(seed)
    for i in range(gw * gh):
        grid[i] = r.u32() & 3


# ── Class-4 fitness ──────────────────────────────────────────────────

def _fitness(genome: bytearray, grid_seed: int,
             gw: int, gh: int, horizon: int) -> tuple[float, float]:
    n = gw * gh
    a = bytearray(n)
    b = bytearray(n)
    _seed_grid(a, gw, gh, grid_seed)
    act = [0.0] * horizon

    for t in range(horizon):
        _step_grid(genome, a, b, gw, gh)
        changed = sum(1 for i in range(n) if a[i] != b[i])
        act[t] = changed / n
        a[:] = b

    uniform = all(a[i] == a[0] for i in range(1, n))
    counts = [0] * K
    for i in range(n):
        counts[a[i]] += 1
    diversity = sum(1 for c in range(K) if counts[c] * 100 >= n)

    tail_n = max(1, horizon // 3)
    avg = sum(act[horizon - tail_n:]) / tail_n

    score = 0.0
    if not uniform:
        score += 1.0
    aperiodic = any(act[i] > 0.001 for i in range(horizon - tail_n, horizon))
    if aperiodic:
        score += 1.5

    if avg <= 0.12:
        activity_reward = avg / 0.12
    else:
        activity_reward = (0.75 - avg) / 0.63
    if activity_reward < 0:
        activity_reward = 0
    score += 2.0 * activity_reward

    if diversity >= 2:
        d = min(diversity, K)
        score += 0.25 * d

    return score, avg


# ── GA ops ───────────────────────────────────────────────────────────

def _mutate(dst: bytearray, src: bytearray, rate: float, r: _Rng) -> None:
    dst[:] = src
    for i in range(NSIT):
        if r.rand_unit() < rate:
            g_set(dst, i, r.rand() & 3)


def _cross(dst: bytearray, a: bytearray, b: bytearray, r: _Rng) -> None:
    cut = 1 + (r.rand() % (GENOME_BYTES - 1))
    dst[:cut] = a[:cut]
    dst[cut:] = b[cut:]


def identity_genome() -> bytearray:
    """Every situation → self colour (1024-byte blocks of 0x00, 0x55,
    0xAA, 0xFF for self ∈ {0,1,2,3})."""
    g = bytearray(GENOME_BYTES)
    g[      :1024] = b'\x00' * 1024
    g[1024  :2048] = b'\x55' * 1024
    g[2048  :3072] = b'\xAA' * 1024
    g[3072  :4096] = b'\xFF' * 1024
    return g


# ── Public API ───────────────────────────────────────────────────────

@dataclass
class HHConfig:
    population:           int   = DEF_POP
    generations:          int   = DEF_GENS
    init_mutation_rate:   float = DEF_INIT_MUT_RATE
    breed_mutation_rate:  float = DEF_BREED_MUT_RATE
    grid_w:               int   = DEF_GRID_W
    grid_h:               int   = DEF_GRID_H
    horizon:              int   = DEF_HORIZON
    rng_seed:             int   = DEF_RNG_SEED
    progress: Optional[Callable[[int, int, float, float, float], None]] = None


def _resolve(**kwargs) -> HHConfig:
    return HHConfig(**kwargs)


def _run_ga(cfg: HHConfig, seed_genome: bytes) -> bytes:
    pop, gens = cfg.population, cfg.generations
    if pop < 2 or gens < 1:
        raise ValueError('population must be >= 2 and generations >= 1')
    gw, gh, horizon = cfg.grid_w, cfg.grid_h, cfg.horizon
    if gw < 3 or gh < 3 or horizon < 3:
        raise ValueError('grid_w/grid_h/horizon must each be >= 3')

    r = _Rng(cfg.rng_seed)
    pool: list[bytearray] = [bytearray(seed_genome)]
    for _ in range(pop - 1):
        child = bytearray(GENOME_BYTES)
        _mutate(child, pool[0], cfg.init_mutation_rate, r)
        pool.append(child)

    fits = [0.0] * pop
    last_tail = 0.0

    def _score_all() -> None:
        nonlocal last_tail
        for i in range(pop):
            s, t = _fitness(pool[i], cfg.rng_seed, gw, gh, horizon)
            fits[i] = s
            last_tail = t   # tail of the last-scored genome; for hunter
                            # parity we care about pool[0]'s tail after
                            # the sort — handled below.

    def _sort_desc() -> None:
        # Insertion sort to match C memmove pattern (stable in practice).
        for i in range(1, pop):
            fv = fits[i]
            tmp = bytearray(pool[i])
            j = i - 1
            while j >= 0 and fits[j] < fv:
                fits[j + 1] = fits[j]
                pool[j + 1] = bytearray(pool[j])
                j -= 1
            fits[j + 1] = fv
            pool[j + 1] = tmp

    for gen in range(gens):
        _score_all()
        _sort_desc()
        if cfg.progress:
            mean_s = sum(fits) / pop
            best_tail = _fitness(pool[0], cfg.rng_seed, gw, gh, horizon)[1]
            cfg.progress(gen + 1, gens, fits[0], mean_s, best_tail)

        # Breed bottom half from top half.
        for i in range(pop // 2, pop):
            pa = r.rand() % (pop // 2)
            pb = r.rand() % (pop // 2)
            tmp = bytearray(GENOME_BYTES)
            _cross(tmp, pool[pa], pool[pb], r)
            child = bytearray(GENOME_BYTES)
            _mutate(child, tmp, cfg.breed_mutation_rate, r)
            pool[i] = child

    _score_all()
    _sort_desc()
    return bytes(pool[0])


def hexhunter(*, population: int = DEF_POP,
              generations: int = DEF_GENS,
              init_mutation_rate: float = DEF_INIT_MUT_RATE,
              breed_mutation_rate: float = DEF_BREED_MUT_RATE,
              grid_w: int = DEF_GRID_W,
              grid_h: int = DEF_GRID_H,
              horizon: int = DEF_HORIZON,
              rng_seed: int = DEF_RNG_SEED,
              progress: Optional[Callable] = None) -> bytes:
    """Run the GA from scratch.  All arguments are keyword-only and
    default to the original hunter.c constants — call ``hexhunter()``
    with no arguments for the unchanged original run.  Returns the
    best 4096-byte ruleset."""
    cfg = HHConfig(population=population, generations=generations,
                    init_mutation_rate=init_mutation_rate,
                    breed_mutation_rate=breed_mutation_rate,
                    grid_w=grid_w, grid_h=grid_h, horizon=horizon,
                    rng_seed=rng_seed, progress=progress)
    return _run_ga(cfg, identity_genome())


def hexhunter_refine(in_genome: bytes, *,
                     population: int = DEF_POP,
                     generations: int = DEF_GENS,
                     init_mutation_rate: float = DEF_INIT_MUT_RATE,
                     breed_mutation_rate: float = DEF_BREED_MUT_RATE,
                     grid_w: int = DEF_GRID_W,
                     grid_h: int = DEF_GRID_H,
                     horizon: int = DEF_HORIZON,
                     rng_seed: int = DEF_RNG_SEED,
                     progress: Optional[Callable] = None) -> bytes:
    """Continue the search around an existing 4096-byte ruleset.
    Same kwargs as ``hexhunter()``.  Returns the new best 4096-byte
    ruleset."""
    if len(in_genome) != GENOME_BYTES:
        raise ValueError(f'in_genome must be {GENOME_BYTES} bytes, '
                          f'got {len(in_genome)}')
    cfg = HHConfig(population=population, generations=generations,
                    init_mutation_rate=init_mutation_rate,
                    breed_mutation_rate=breed_mutation_rate,
                    grid_w=grid_w, grid_h=grid_h, horizon=horizon,
                    rng_seed=rng_seed, progress=progress)
    return _run_ga(cfg, bytes(in_genome))


def fitness(genome: bytes, *,
            grid_w: int = DEF_GRID_W, grid_h: int = DEF_GRID_H,
            horizon: int = DEF_HORIZON,
            rng_seed: int = DEF_RNG_SEED) -> float:
    """Score a single 4096-byte ruleset under the same regime."""
    if len(genome) != GENOME_BYTES:
        raise ValueError(f'genome must be {GENOME_BYTES} bytes, '
                          f'got {len(genome)}')
    s, _ = _fitness(bytearray(genome), rng_seed, grid_w, grid_h, horizon)
    return s


# ── Self-test / CLI ──────────────────────────────────────────────────

def _cli() -> int:
    """Tiny CLI mirroring hh_cli — for verification against the C build.
    Usage: python hexhunter.py [POP] [GENS] [SEED] [OUT_PATH] [IN_PATH]"""
    import sys
    args = sys.argv[1:]
    pop  = int(args[0]) if len(args) > 0 else DEF_POP
    gens = int(args[1]) if len(args) > 1 else DEF_GENS
    seed = int(args[2]) if len(args) > 2 else DEF_RNG_SEED
    out_path = args[3] if len(args) > 3 else 'winner_py.bin'
    in_path  = args[4] if len(args) > 4 else None

    def progress(gen, total, best, mean, tail):
        print(f'  gen {gen:2d}/{total}  best={best:.3f}  mean={mean:.3f}  '
              f'best_activity_tail={tail:.3f}', file=sys.stderr)

    if in_path:
        with open(in_path, 'rb') as f:
            in_genome = f.read()
        print(f'refining {in_path} ...', file=sys.stderr)
        out = hexhunter_refine(in_genome, population=pop, generations=gens,
                                rng_seed=seed, progress=progress)
    else:
        print('evolving from identity ...', file=sys.stderr)
        out = hexhunter(population=pop, generations=gens,
                         rng_seed=seed, progress=progress)

    with open(out_path, 'wb') as f:
        f.write(out)
    final = fitness(out, rng_seed=seed)
    print(f'wrote {out_path} ({len(out)} bytes)  fitness={final:.3f}',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())

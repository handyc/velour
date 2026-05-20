"""Stack-genome shape.

A genome is a dict-of-arrays describing one stack configuration:

    {
      'n_boards':      int — N, number of boards in the stack
      'board_side':    int — side length (each board is side×side cells)
      'rule_idx':      List[int] length N — index into the LUT pool
      'ticks':         List[int] length N — internal ticks per stack-step
                       (variable rates per board)
      'wiring':        List[(src_board, src_r, src_c)] length N
                       — for each board K, which (board, cell) provides
                         its input port.  Special src_board values:
                         -1 = read from external "prompt byte" register
                         -2..-5 = 4 personality constants (0/1/2/3)
      'output_cell':   (r, c) — where to read the final output byte
                                from board N-1 (4 cells: that one + 3
                                horizontal neighbours)
      'stack_ticks':   int — number of full stack-steps per inference
    }

The encoding is intentionally JSON-friendly so it can persist in
StackGenome.gene_json without a separate schema."""
from __future__ import annotations

import random
from typing import Dict


def random_genome(*, n_boards: int = 16, board_side: int = 64,
                       pool_size: int = 64, stack_ticks: int = 4,
                       seed: int = 0xB0A2D57AC) -> Dict:
    """A random valid genome.  Default sizes are small for fast
    iteration; scale up via the kwargs."""
    rng = random.Random(seed)
    rule_idx = [rng.randrange(pool_size) for _ in range(n_boards)]
    # Per-board ticks: 1..6 (varied rates).
    ticks = [1 + rng.randrange(6) for _ in range(n_boards)]
    # Wiring: board 0 always reads from prompt-byte register (-1);
    # other boards either read from a previous board's cell OR
    # from the prompt register / personality.
    wiring = []
    for k in range(n_boards):
        if k == 0:
            wiring.append((-1, 0, 0))     # board 0 ← prompt byte
        else:
            r = rng.random()
            if r < 0.6:
                # Read from a random earlier board's random cell.
                src = rng.randrange(k)
                rr, cc = (rng.randrange(board_side), rng.randrange(board_side))
                wiring.append((src, rr, cc))
            elif r < 0.8:
                # Read from prompt byte directly.
                wiring.append((-1, 0, 0))
            else:
                # Personality constant 0..3.
                wiring.append((-(2 + rng.randrange(4)), 0, 0))
    # Output cell on the last board: gene picks one.
    output_cell = (rng.randrange(board_side), rng.randrange(board_side))
    return {
        'n_boards':    n_boards,
        'board_side':  board_side,
        'rule_idx':    rule_idx,
        'ticks':       ticks,
        'wiring':      wiring,
        'output_cell': output_cell,
        'stack_ticks': stack_ticks,
    }


def naive_pipeline_genome(*, n_boards: int = 16, board_side: int = 32,
                                 pool_size: int = 64, stack_ticks: int = 4,
                                 seed: int = 0xB05A1EAF) -> Dict:
    """A deliberately sane "naive pipeline" seed gene.

    - All boards run 1 tick per stack-step (uniform rates).
    - Board 0 reads from prompt-byte register.
    - Each later board reads from the PREVIOUS board's top-left cell
      (0, 0).  Linear pipeline.
    - Output decoded from (0, 0) of last board.
    - rule_idx still random (the LUTs are class-4 from the pool, but
      WHICH class-4 LUT each board uses gets randomised).

    This gives the GA a "structured wiring + random rules" starting
    point — it can then mutate rules without simultaneously having
    to discover a sensible wiring topology.
    """
    rng = random.Random(seed)
    return {
        'n_boards':    n_boards,
        'board_side':  board_side,
        'rule_idx':    [rng.randrange(pool_size) for _ in range(n_boards)],
        'ticks':       [1] * n_boards,
        'wiring':      [(-1, 0, 0) if k == 0 else (k - 1, 0, 0)
                            for k in range(n_boards)],
        'output_cell': (0, 0),
        'stack_ticks': stack_ticks,
    }


def echo_seed_genome(*, n_boards: int = 16, board_side: int = 32,
                              pool_size: int = 64, stack_ticks: int = 4,
                              seed: int = 0xE0E0) -> Dict:
    """A seed gene aimed at the 'echo' task (output = input byte).

    Every board reads from the PROMPT-BYTE REGISTER directly (not
    from previous boards).  Output cell at (0, 0).  If any class-4
    rule turns out to map "prompt-bit-stream-in-port → identical-
    bit-stream-at-(0,0)", the GA finds it via rule_idx mutation.
    """
    rng = random.Random(seed)
    return {
        'n_boards':    n_boards,
        'board_side':  board_side,
        'rule_idx':    [rng.randrange(pool_size) for _ in range(n_boards)],
        'ticks':       [1] * n_boards,
        'wiring':      [(-1, 0, 0)] * n_boards,
        'output_cell': (0, 0),
        'stack_ticks': stack_ticks,
    }


def mutate_genome(g: Dict, *, mutation_rate: float = 0.05,
                       pool_size: int = 64, seed: int = 0) -> Dict:
    """Return a mutated copy of `g`.  Each gene-element has
    `mutation_rate` probability of being randomised."""
    rng = random.Random(seed)
    n   = g['n_boards']
    bs  = g['board_side']
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in g.items()}
    out['rule_idx'] = list(g['rule_idx'])
    out['ticks']    = list(g['ticks'])
    out['wiring']   = [tuple(w) for w in g['wiring']]
    for k in range(n):
        if rng.random() < mutation_rate:
            out['rule_idx'][k] = rng.randrange(pool_size)
        if rng.random() < mutation_rate:
            out['ticks'][k] = 1 + rng.randrange(6)
        if rng.random() < mutation_rate and k > 0:
            r = rng.random()
            if r < 0.6:
                src = rng.randrange(k)
                out['wiring'][k] = (src, rng.randrange(bs), rng.randrange(bs))
            elif r < 0.8:
                out['wiring'][k] = (-1, 0, 0)
            else:
                out['wiring'][k] = (-(2 + rng.randrange(4)), 0, 0)
    if rng.random() < mutation_rate:
        out['output_cell'] = (rng.randrange(bs), rng.randrange(bs))
    if rng.random() < mutation_rate * 0.3:    # stack_ticks rarely changes
        out['stack_ticks'] = max(1, g['stack_ticks'] + rng.choice([-1, 1]))
    return out

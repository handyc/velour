"""Pattern detection for hex cellular automata (Phase 3 of the CA
backlog).

Runs a Simulation forward in pure Python for a bounded number of
ticks and watches for repeating grid states. A repeat means the
trajectory has entered a cycle:

  - period 1       = still life (fixed point)
  - period 2..N    = oscillator
  - no repeat      = aperiodic (chaos, or a glider that never loops
                     within the horizon — we don't do translated
                     matching yet)

When the Simulation's RuleSet came from Identity (source='identity')
and the detected pattern is non-trivial, the caller wires in an
IdentityAssertion so Velour can observe its own creations. The
strange loop closes: mood → rules → pattern → observation → mood.

The step functions mirror `templates/automaton/run.html` exactly —
same hex neighbor order (N, NE, SE, S, SW, NW), same edge padding
(out-of-bounds = 0 for exact rules, skipped for count rules), same
first-match-wins priority.
"""

import random


def _hex_neighbors_padded(grid, r, c, W, H):
    """Six neighbors in canonical order with 0-padding for edges.
    Used by exact-match rules (which expect a fixed-length tuple)."""
    even = (c % 2) == 0
    positions = [
        (r - 1, c),                              # N
        (r - 1 if even else r, c + 1),           # NE
        (r if even else r + 1, c + 1),           # SE
        (r + 1, c),                              # S
        (r if even else r + 1, c - 1),           # SW
        (r - 1 if even else r, c - 1),           # NW
    ]
    out = []
    for (nr, nc) in positions:
        if 0 <= nr < H and 0 <= nc < W:
            out.append(grid[nr][nc])
        else:
            out.append(0)
    return out


def _hex_neighbors_valid(grid, r, c, W, H):
    """Six neighbors, skipping out-of-bounds. Used by count rules."""
    even = (c % 2) == 0
    positions = [
        (r - 1, c),
        (r - 1 if even else r, c + 1),
        (r if even else r + 1, c + 1),
        (r + 1, c),
        (r if even else r + 1, c - 1),
        (r - 1 if even else r, c - 1),
    ]
    return [grid[nr][nc] for (nr, nc) in positions
            if 0 <= nr < H and 0 <= nc < W]


def step_packed(grid, W, H, packed):
    """Advance the grid one tick using a ``PackedRuleset``.

    Equivalent result to ``step_exact`` when the packed ruleset was
    materialised from the same explicit rule list (see
    ``PackedRuleset.from_explicit``), but O(1) per cell with a single
    memory fetch — no hash, no wildcard walk. The packed blob fits
    entirely in L1 cache on any modern CPU.

    ``packed`` is an ``automaton.packed.PackedRuleset`` instance.
    """
    next_grid = [[0] * W for _ in range(H)]
    K = packed.n_colors
    # Precompute the K^i weights inline — marginal speedup on a hot loop.
    w0, w1, w2, w3, w4, w5 = (K**6, K**5, K**4, K**3, K**2, K**1)
    bits = packed.bits_per_cell
    mask = (1 << bits) - 1
    data = packed.data
    for r in range(H):
        for c in range(W):
            self_c = grid[r][c]
            nbs = _hex_neighbors_padded(grid, r, c, W, H)
            idx = (self_c * w0
                   + nbs[0] * w1 + nbs[1] * w2 + nbs[2] * w3
                   + nbs[3] * w4 + nbs[4] * w5 + nbs[5])
            bit_offset = idx * bits
            byte_i = bit_offset >> 3
            bit_i = bit_offset & 7
            next_grid[r][c] = (data[byte_i] >> bit_i) & mask
    return next_grid


def step_exact(grid, W, H, exact_rules):
    """Apply exact-match rules. `exact_rules` is a list of dicts with
    keys s (self color), n (6-tuple neighbor colors), r (result color);
    -1 anywhere means wildcard."""
    exact_map = {}
    wildcards = []
    for er in exact_rules:
        if er['s'] == -1 or any(x == -1 for x in er['n']):
            wildcards.append(er)
        else:
            exact_map[(er['s'], tuple(er['n']))] = er['r']

    next_grid = [[0] * W for _ in range(H)]
    for r in range(H):
        for c in range(W):
            self_c = grid[r][c]
            nbs = _hex_neighbors_padded(grid, r, c, W, H)
            key = (self_c, tuple(nbs))

            if key in exact_map:
                next_grid[r][c] = exact_map[key]
                continue

            result = self_c
            for er in wildcards:
                if er['s'] >= 0 and er['s'] != self_c:
                    continue
                matched = True
                for j in range(6):
                    if er['n'][j] >= 0 and er['n'][j] != nbs[j]:
                        matched = False
                        break
                if matched:
                    result = er['r']
                    break
            next_grid[r][c] = result
    return next_grid


def step_count(grid, W, H, rules, n_colors):
    """Apply count-based rules. `rules` is a list of dicts with keys
    self_color, neighbor_color, min_count, max_count, result_color."""
    next_grid = [[0] * W for _ in range(H)]
    for r in range(H):
        for c in range(W):
            self_c = grid[r][c]
            nbs = _hex_neighbors_valid(grid, r, c, W, H)
            ncount = [0] * n_colors
            for n in nbs:
                if 0 <= n < n_colors:
                    ncount[n] += 1

            result = self_c
            for rule in rules:
                if rule['self_color'] >= 0 and rule['self_color'] != self_c:
                    continue
                nc_idx = rule['neighbor_color']
                cnt = ncount[nc_idx] if 0 <= nc_idx < n_colors else 0
                if rule['min_count'] <= cnt <= rule['max_count']:
                    result = rule['result_color']
                    break
            next_grid[r][c] = result
    return next_grid


def _hash_grid(grid):
    """A stable hashable representation of the grid — tuples of tuples
    make good dict keys and avoid the cost of a cryptographic hash for
    a few-thousand-cell grid."""
    return tuple(tuple(row) for row in grid)


def _initial_grid(sim):
    """Return the starting grid for the analysis. If the Simulation's
    `grid_state` is empty, seed a deterministic random grid from the
    simulation's pk — so re-running detect_patterns on the same row
    always looks at the same trajectory."""
    if sim.grid_state and len(sim.grid_state):
        return [list(row) for row in sim.grid_state]
    rng = random.Random(f'sim-{sim.pk}')
    NC = max(1, sim.ruleset.n_colors)
    return [[rng.randrange(NC) for _ in range(sim.width)]
            for _ in range(sim.height)]


def detect(sim, horizon=40):
    """Run the simulation forward for up to `horizon` ticks and
    return a dict describing what happened. Shape:

      {
        'horizon':           int,   # ticks we looked at
        'pattern':           'still_life' | 'oscillator' | 'aperiodic',
        'period':            int | None,
        'entered_cycle_at':  int | None,  # tick index of first state that repeats
        'repeat_seen_at':    int | None,  # tick index where we noticed the repeat
        'uniform':           bool,        # all cells same color at horizon
      }
    """
    W, H = sim.width, sim.height
    NC = sim.ruleset.n_colors or 4
    grid = _initial_grid(sim)

    exact_rules = list(sim.ruleset.exact_rules.order_by('priority').values(
        'self_color', 'n0_color', 'n1_color', 'n2_color',
        'n3_color', 'n4_color', 'n5_color', 'result_color',
    ))
    count_rules = list(sim.ruleset.rules.order_by('priority').values(
        'self_color', 'neighbor_color',
        'min_count', 'max_count', 'result_color',
    ))
    use_exact = bool(exact_rules)
    if use_exact:
        prepared_exact = [{
            's': er['self_color'],
            'n': [er['n0_color'], er['n1_color'], er['n2_color'],
                  er['n3_color'], er['n4_color'], er['n5_color']],
            'r': er['result_color'],
        } for er in exact_rules]

    history = {_hash_grid(grid): 0}
    for t in range(1, horizon + 1):
        if use_exact:
            grid = step_exact(grid, W, H, prepared_exact)
        else:
            grid = step_count(grid, W, H, count_rules, NC)

        h = _hash_grid(grid)
        if h in history:
            entered = history[h]
            period = t - entered
            pattern = 'still_life' if period == 1 else 'oscillator'
            colors = {c for row in grid for c in row}
            return {
                'horizon':          horizon,
                'pattern':          pattern,
                'period':           period,
                'entered_cycle_at': entered,
                'repeat_seen_at':   t,
                'uniform':          len(colors) == 1,
            }
        history[h] = t

    colors = {c for row in grid for c in row}
    return {
        'horizon':          horizon,
        'pattern':          'aperiodic',
        'period':           None,
        'entered_cycle_at': None,
        'repeat_seen_at':   None,
        'uniform':          len(colors) == 1,
    }


def is_interesting(analysis):
    """Heuristic for the Identity-facing filter: does this pattern
    deserve an assertion? A still life of uniform color is boring
    (the grid just went flat); an oscillator is always worth noting;
    a non-uniform still life is interesting because the rules found
    a stable non-trivial configuration."""
    p = analysis.get('pattern')
    if p == 'oscillator':
        return True
    if p == 'still_life' and not analysis.get('uniform'):
        return True
    return False

"""Fetch a 2D fill array (CSS hex strings) from a CA-source.

Sources currently supported:
  - automaton:<sim_slug>  → Simulation.grid_state mapped via Simulation.palette
  - taxon:<rule_slug>     → simulate the rule for `ticks` steps from a seed,
                             return the final grid using the rule's palette

Returns a list[list[str]] of CSS colour strings; '' for "leave the cell
blank" (we use index 0 = '' so the substrate doesn't get a coloured fill).
"""
from __future__ import annotations


def _palette_to_fill(grid: list[list[int]],
                     palette: list[str],
                     blank_index: int = 0) -> list[list[str]]:
    out: list[list[str]] = []
    for row in grid:
        out.append([
            '' if v == blank_index else palette[int(v) % len(palette)]
            for v in row
        ])
    return out


def from_automaton(slug: str, *,
                   blank_index: int = 0) -> tuple[list[list[str]], dict]:
    """Pull the latest grid state from an automaton.Simulation."""
    from automaton.models import Simulation
    sim = Simulation.objects.filter(slug=slug).first()
    if sim is None:
        raise ValueError(f'automaton sim "{slug}" not found')
    grid = sim.grid_state or []
    palette = list(sim.palette or [])
    if not grid or not palette:
        raise ValueError(f'sim "{slug}" has no grid_state / palette yet')
    return _palette_to_fill(grid, palette, blank_index), {
        'source': 'automaton', 'slug': sim.slug, 'name': sim.name,
        'width': sim.width, 'height': sim.height,
        'palette': palette, 'tick': sim.tick_count,
    }


def from_taxon(slug: str, *,
               width: int = 16, height: int = 16,
               ticks: int = 24, seed: int = 42,
               blank_index: int = 0) -> tuple[list[list[str]], dict]:
    """Run a taxon Rule and return its `ticks`-step state."""
    from taxon.models import Rule
    from taxon.engine import simulate
    from automaton.packed import PackedRuleset, ansi256_to_hex

    rule = Rule.objects.filter(slug=slug).first()
    if rule is None:
        raise ValueError(f'taxon rule "{slug}" not found')
    if rule.kind != 'hex_k4_packed':
        raise ValueError(f'rule "{slug}" is not K=4 packed (kind={rule.kind})')

    packed = PackedRuleset(n_colors=rule.n_colors, data=bytes(rule.genome))
    traj, _hashes = simulate(packed, width, height, ticks, seed)
    grid = traj[-1].tolist()
    palette_ansi = list(bytes(rule.palette_ansi))[:rule.n_colors]
    palette = [ansi256_to_hex(p) for p in palette_ansi]
    return _palette_to_fill(grid, palette, blank_index), {
        'source': 'taxon', 'slug': rule.slug, 'name': rule.name or rule.slug,
        'width': width, 'height': height, 'palette': palette, 'ticks': ticks,
    }

"""Generate complete K-color hexagonal Wang tile sets.

Pipe model: a hex has 3 axes (V = north↔south, NE = NE↔SW, NW = NW↔SE).
Each axis carries one of K colours, so the tile set's size is K**3
(64 for K=4). Opposite edges share the axis colour, so a tile is
fully described by an (axis_v, axis_ne, axis_nw) triple.

The pipe model matches the user's "substrate / signal-1 / signal-2 /
combined" semantics — colour 0 along an axis means "no signal flows
on this axis", colour 1 means "signal-1 flows", etc.

The generator writes a tiles.TileSet with K**3 tiles. Each tile gets
its 6 edge colours filled in from its triple; the optional CA payload
(initial grid + ruleset) can be wired up later.
"""
from __future__ import annotations

from django.utils import timezone

from tiles.models import Tile, TileSet


# Pipe-model axis -> (edge1, edge2) pairs. A hex Wang tile in the
# tiles app has fields {n, ne, se, s, sw, nw}; we project the 3-axis
# colour triple onto those 6 fields here.
PIPE_AXES = [
    ('v',  ('n_color',  's_color')),    # vertical
    ('ne', ('ne_color', 'sw_color')),   # NE-SW diagonal
    ('nw', ('nw_color', 'se_color')),   # NW-SE diagonal
]


def enumerate_triples(k: int = 4):
    """Yield every (v, ne, nw) triple with each in 0..k-1.

    For k=4 this yields 64 triples in lexicographic order so the
    generated tiles render in a predictable grid (axis_v as the row
    of an 8-wide grid, etc.)."""
    for v in range(k):
        for ne in range(k):
            for nw in range(k):
                yield (v, ne, nw)


def triple_to_edges(triple, palette: list[str]) -> dict:
    """Map a (v, ne, nw) triple to the 6 edge-colour fields.

    palette[i] is the colour name written into the model (free-form
    string; the tiles app does not currently enforce membership).
    """
    v, ne, nw = triple
    cv, cne, cnw = palette[v], palette[ne], palette[nw]
    return {
        'n_color': cv, 's_color':  cv,
        'ne_color': cne, 'sw_color': cne,
        'nw_color': cnw, 'se_color': cnw,
    }


def tile_label(triple) -> str:
    """Short stable label like 'v0/ne0/nw0' for a triple."""
    v, ne, nw = triple
    return f'v{v}/ne{ne}/nw{nw}'


def _default_palette(k: int = 4) -> list[str]:
    """K=4 pipe-model defaults — colour 0 = substrate, 1 = signal-1,
    2 = signal-2, 3 = combined. CSS-friendly hex strings so the SVG
    renderer can use them directly without a name->hex lookup."""
    return ['#101010', '#2a8c5b', '#d8a93a', '#c04a4a'][:k]


def _ruleset_for_rule(rule):
    """Idempotently create / fetch an automaton.RuleSet for a taxon Rule.

    Reuses taxon.exporters.to_automaton, which is sha1-deduped, so
    re-running on the same rule never creates a second RuleSet.
    Returns None if `rule` is None or non-K=4.
    """
    if rule is None or rule.kind != 'hex_k4_packed' or rule.n_colors != 4:
        return None
    from . import exporters
    sim = exporters.to_automaton(rule)
    return sim.ruleset


def generate_complete_hex_tileset(
    *, name: str, description: str = '',
    k: int = 4, palette: list[str] | None = None,
    rule=None,
    source: str = 'operator',
    source_metadata: dict | None = None,
) -> TileSet:
    """Create a TileSet of k**3 hex Wang tiles in the pipe model.

    If `rule` (a taxon.Rule) is given, every tile's ca_ruleset is bound
    to the corresponding automaton.RuleSet so the tiles app's CA-Wang
    runner can animate them.

    If a TileSet with the same name exists it is replaced (delete +
    recreate) so re-runs are idempotent. Each Tile's name is the
    triple label, so they're unique within the set.
    """
    if k < 2 or k > 8:
        raise ValueError(f'k must be 2..8 (got {k})')
    palette = palette or _default_palette(k)
    if len(palette) < k:
        raise ValueError(f'palette has {len(palette)} colours, need ≥{k}')

    ca_ruleset = _ruleset_for_rule(rule)

    TileSet.objects.filter(name=name).delete()

    ts = TileSet.objects.create(
        tile_type='hex', name=name, description=description,
        palette=list(palette[:k]),
        source=source, source_metadata=source_metadata or {},
    )

    sort_order = 0
    rows = []
    for triple in enumerate_triples(k):
        edges = triple_to_edges(triple, palette)
        tile = Tile(
            tileset=ts, name=tile_label(triple),
            sort_order=sort_order,
            ca_ruleset=ca_ruleset,
            **edges,
        )
        rows.append(tile)
        sort_order += 1
    Tile.objects.bulk_create(rows)
    ts.updated_at = timezone.now()
    ts.save(update_fields=['updated_at'])
    return ts

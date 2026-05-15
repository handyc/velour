"""Optikon illusion registry.

Each illusion module exports the same shape:

    SLUG         = 'cafe-wall'
    NAME         = 'Café-wall'
    DESCRIPTION  = 'Staggered black/white hex bands appear sloped.'
    PARAMS       = [Param(...), ...]    # for the UI sliders
    PALETTE      = ['#000000', '#ffffff', ...]   # 1 colour per index
    def render(grid_w, grid_h, params) -> List[List[int]]:
        '''Return a grid_h × grid_w array of palette indices.'''

Adding a new illusion = drop a new file in this directory and
register it in REGISTRY below.  No DB migration, no view edits.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass(frozen=True)
class Param:
    """One slider/input on the illusion's playground page."""
    key:     str
    label:   str
    kind:    str             # 'int' | 'float' | 'choice' | 'color'
    default: Any
    min:     Any = None
    max:     Any = None
    step:    Any = None
    choices: List[Any] | None = None
    help:    str = ''

    def parse(self, raw: Any) -> Any:
        if self.kind == 'int':
            v = int(raw)
            if self.min is not None: v = max(self.min, v)
            if self.max is not None: v = min(self.max, v)
            return v
        if self.kind == 'float':
            v = float(raw)
            if self.min is not None: v = max(self.min, v)
            if self.max is not None: v = min(self.max, v)
            return v
        if self.kind == 'choice':
            s = str(raw)
            return s if (self.choices and s in self.choices) else self.default
        # color / fallback
        return str(raw)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_params(params_spec: List[Param], raw_dict: dict) -> dict:
    out = {}
    for p in params_spec:
        if p.key in raw_dict and raw_dict[p.key] not in ('', None):
            try: out[p.key] = p.parse(raw_dict[p.key])
            except (TypeError, ValueError): out[p.key] = p.default
        else:
            out[p.key] = p.default
    return out


# ─── Registry ─────────────────────────────────────────────────────
# Imported lazily so a syntax error in one illusion doesn't crash
# the catalogue page.

from . import (cafe_wall, hermann_grid, ehrenstein, bezold, munker_white,
                poggendorff, scintillating_grid, kanizsa_triangle,
                muller_lyer, zollner,
                autostereogram)   # noqa: E402

REGISTRY = {
    cafe_wall.SLUG:           cafe_wall,
    hermann_grid.SLUG:        hermann_grid,
    scintillating_grid.SLUG:  scintillating_grid,
    ehrenstein.SLUG:          ehrenstein,
    poggendorff.SLUG:         poggendorff,
    muller_lyer.SLUG:         muller_lyer,
    zollner.SLUG:             zollner,
    kanizsa_triangle.SLUG:    kanizsa_triangle,
    bezold.SLUG:              bezold,
    munker_white.SLUG:        munker_white,
    autostereogram.SLUG:      autostereogram,
}


def all_illusions():
    """Stable ordering for the catalogue page."""
    return [REGISTRY[k] for k in REGISTRY]


def get(slug: str):
    return REGISTRY.get(slug)

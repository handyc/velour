"""Browser-editable schematic — symbols, validation, server-side SVG render.

Schema (`Circuit.schematic_json`):

    {
        "nodes": [
            {"id": "n1", "kind": "resistor", "x": 120, "y": 80,
             "rot": 0, "label": "R1", "value": "10k"},
            ...
        ],
        "wires": [
            {"from": "n1.p2", "to": "n2.p1"},
            ...
        ],
        "version": 1
    }

Each symbol kind is registered below with its pin coordinates (in
local symbol space, before rotation). Pin ids are arbitrary string
keys — convention is "p1", "p2" for two-terminal devices, "g/d/s"
or "b/c/e" for transistors, "v/g" for power rails.

The renderer walks `nodes` and `wires`, applies node rotation, and
emits an inline `<svg>` element. No client-side libraries needed to
display a saved schematic.
"""

from __future__ import annotations

import math
from typing import Iterable


# (kind → {label, paths, pins})
#
# `paths`  is a list of SVG path-data strings drawn at the node origin.
# `pins`   maps pin id → (x, y) offsets in symbol-local space.
# `label`  is the human-friendly menu name.
SYMBOLS: dict = {
    'resistor': {
        'label': 'Resistor',
        'paths': [
            'M -30 0 L -15 0 L -12 -8 L -6 8 L 0 -8 L 6 8 L 12 -8 L 15 0 L 30 0',
        ],
        'pins':  {'p1': (-30, 0), 'p2': (30, 0)},
    },
    'capacitor': {
        'label': 'Capacitor',
        'paths': [
            'M -30 0 L -4 0',
            'M  4 0 L 30 0',
            'M -4 -12 L -4 12',
            'M  4 -12 L  4 12',
        ],
        'pins':  {'p1': (-30, 0), 'p2': (30, 0)},
    },
    'inductor': {
        'label': 'Inductor',
        'paths': [
            'M -30 0 L -20 0',
            'M -20 0 a 5 5 0 0 1 10 0',
            'M -10 0 a 5 5 0 0 1 10 0',
            'M   0 0 a 5 5 0 0 1 10 0',
            'M  10 0 a 5 5 0 0 1 10 0',
            'M  20 0 L 30 0',
        ],
        'pins':  {'p1': (-30, 0), 'p2': (30, 0)},
    },
    'diode': {
        'label': 'Diode',
        'paths': [
            'M -30 0 L -8 0',
            'M -8 -10 L -8 10 L 8 0 Z',
            'M  8 -10 L 8 10',
            'M  8 0 L 30 0',
        ],
        'pins':  {'p1': (-30, 0), 'p2': (30, 0)},  # p1=anode p2=cathode
    },
    'led': {
        'label': 'LED',
        'paths': [
            'M -30 0 L -8 0',
            'M -8 -10 L -8 10 L 8 0 Z',
            'M  8 -10 L 8 10',
            'M  8 0 L 30 0',
            'M 12 -14 L 18 -20 M 16 -20 L 18 -20 L 18 -18',
            'M 18 -10 L 24 -16 M 22 -16 L 24 -16 L 24 -14',
        ],
        'pins':  {'p1': (-30, 0), 'p2': (30, 0)},
    },
    'transistor_npn': {
        'label': 'NPN transistor',
        'paths': [
            'M -30 0 L -8 0',           # base
            'M -8 -16 L -8 16',          # body bar
            'M -8 -10 L 14 -22',         # collector slope
            'M -8  10 L 14  22',         # emitter slope
            'M 14 -22 L 14 -30',         # collector lead
            'M 14  22 L 14  30',         # emitter lead
            'M 12 16 L 14 22 L 8 18 Z',  # arrow
        ],
        'pins':  {'b': (-30, 0), 'c': (14, -30), 'e': (14, 30)},
    },
    'mosfet_n': {
        'label': 'N-MOSFET',
        'paths': [
            'M -30 0 L -10 0',           # gate
            'M -10 -16 L -10 16',         # gate bar
            'M  -4 -16 L  -4 -6',         # drain segment
            'M  -4   6 L  -4  16',        # source segment (gap = channel)
            'M  -4 -16 L 14 -16 L 14 -28',# drain to top pin
            'M  -4  16 L 14  16 L 14  28',# source to bottom pin
            'M   8 12 L 14 16 L 12 10 Z', # arrow into channel
        ],
        'pins':  {'g': (-30, 0), 'd': (14, -28), 's': (14, 28)},
    },
    'opamp': {
        'label': 'Op-amp',
        'paths': [
            'M -20 -22 L -20 22 L 22 0 Z',
            'M -22 -10 L -16 -10',         # plus tick (top)
            'M -19 -13 L -19 -7',
            'M -22 10 L -16 10',           # minus tick (bottom)
        ],
        'pins':  {'in_p': (-20, -10), 'in_m': (-20, 10), 'out': (22, 0)},
    },
    'ground': {
        'label': 'Ground',
        'paths': [
            'M 0 -16 L 0 0',
            'M -14 0 L 14 0',
            'M -10 6 L 10 6',
            'M -6 12 L 6 12',
        ],
        'pins':  {'g': (0, -16)},
    },
    'vcc': {
        'label': 'V+',
        'paths': [
            'M 0 16 L 0 0',
            'M -10 0 L 10 0 L 0 -12 Z',
        ],
        'pins':  {'v': (0, 16)},
    },
    'switch_spst': {
        'label': 'Switch (SPST)',
        'paths': [
            'M -30 0 L -12 0',
            'M -12 0 L 8 -12',  # open contact
            'M  12 0 L 30 0',
            'M -12 0 m -2 0 a 2 2 0 1 0 4 0 a 2 2 0 1 0 -4 0',
            'M  12 0 m -2 0 a 2 2 0 1 0 4 0 a 2 2 0 1 0 -4 0',
        ],
        'pins':  {'p1': (-30, 0), 'p2': (30, 0)},
    },
    'junction': {
        'label': 'Junction',
        'paths': [
            'M 0 0 m -3 0 a 3 3 0 1 0 6 0 a 3 3 0 1 0 -6 0',
        ],
        'pins':  {'j': (0, 0)},
    },
}


VALID_KINDS = set(SYMBOLS.keys())
VERSION = 1


def empty_doc() -> dict:
    return {'version': VERSION, 'nodes': [], 'wires': []}


def normalise(doc: dict) -> dict:
    """Coerce a possibly-malformed JSON blob into a safe shape.
    Drops any nodes with unknown kinds; rewrites wire endpoints whose
    referenced nodes / pins no longer exist.
    """
    if not isinstance(doc, dict):
        return empty_doc()

    out = {
        'version': VERSION,
        'nodes':   [],
        'wires':   [],
    }
    seen_ids: set = set()
    for raw in (doc.get('nodes') or []):
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get('id') or '').strip()
        kind = str(raw.get('kind') or '').strip()
        if not nid or kind not in VALID_KINDS or nid in seen_ids:
            continue
        seen_ids.add(nid)
        out['nodes'].append({
            'id':    nid,
            'kind':  kind,
            'x':     int(raw.get('x') or 0),
            'y':     int(raw.get('y') or 0),
            'rot':   int(raw.get('rot') or 0) % 360,
            'label': str(raw.get('label') or '')[:24],
            'value': str(raw.get('value') or '')[:24],
        })

    # Build a {node_id: pin_set} lookup so we can drop stale wires.
    pin_index = {}
    for n in out['nodes']:
        pin_index[n['id']] = set(SYMBOLS[n['kind']]['pins'].keys())

    for raw in (doc.get('wires') or []):
        if not isinstance(raw, dict):
            continue
        a = str(raw.get('from') or '')
        b = str(raw.get('to') or '')
        if not a or not b or a == b:
            continue
        if not _valid_endpoint(a, pin_index) or not _valid_endpoint(b, pin_index):
            continue
        out['wires'].append({'from': a, 'to': b})

    return out


def _valid_endpoint(ep: str, pin_index: dict) -> bool:
    if '.' not in ep:
        return False
    nid, pin = ep.split('.', 1)
    return nid in pin_index and pin in pin_index[nid]


def render_svg(doc: dict, *, width: int = 800, height: int = 600) -> str:
    """Return inline <svg>...</svg> markup for a saved schematic.
    Server-rendered, no JS. Used by circuit_detail.html.
    """
    if not doc or not doc.get('nodes'):
        return ''

    parts: list = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'class="pl-schematic-svg" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="schematic">'
    ]

    # Faint grid for orientation.
    parts.append(
        f'<defs><pattern id="pl-grid" width="20" height="20" '
        f'patternUnits="userSpaceOnUse">'
        f'<path d="M 20 0 L 0 0 0 20" fill="none" stroke="#1f2937" '
        f'stroke-width="0.5"/></pattern></defs>'
        f'<rect width="100%" height="100%" fill="url(#pl-grid)"/>'
    )

    # Pin lookup keyed by "node_id.pin" → (abs_x, abs_y) so wires can route.
    pin_xy = {}
    for n in doc['nodes']:
        sym = SYMBOLS.get(n['kind'])
        if not sym:
            continue
        for pin_id, (px, py) in sym['pins'].items():
            ax, ay = _rotate(px, py, n['rot'])
            pin_xy[f'{n["id"]}.{pin_id}'] = (n['x'] + ax, n['y'] + ay)

    # Wires under symbols so junctions sit on top.
    for w in (doc.get('wires') or []):
        a = pin_xy.get(w['from'])
        b = pin_xy.get(w['to'])
        if not a or not b:
            continue
        ax, ay = a
        bx, by = b
        # Manhattan elbow: horizontal first, then vertical.
        parts.append(
            f'<path d="M {ax} {ay} L {bx} {ay} L {bx} {by}" '
            f'fill="none" stroke="#c9d1d9" stroke-width="1.5"/>'
        )

    for n in doc['nodes']:
        sym = SYMBOLS.get(n['kind'])
        if not sym:
            continue
        parts.append(
            f'<g transform="translate({n["x"]},{n["y"]}) rotate({n["rot"]})" '
            f'fill="none" stroke="#c9d1d9" stroke-width="1.5">'
        )
        for d in sym['paths']:
            parts.append(f'<path d="{d}"/>')
        parts.append('</g>')
        # Labels stay un-rotated so they're always readable.
        if n.get('label') or n.get('value'):
            txt_parts = []
            if n.get('label'):
                txt_parts.append(n['label'])
            if n.get('value'):
                txt_parts.append(n['value'])
            label_y = n['y'] + 28
            parts.append(
                f'<text x="{n["x"]}" y="{label_y}" fill="#8b949e" '
                f'font-size="11" font-family="monospace" '
                f'text-anchor="middle">{" ".join(txt_parts)}</text>'
            )

    parts.append('</svg>')
    return ''.join(parts)


def _rotate(x: float, y: float, deg: int):
    if deg % 360 == 0:
        return x, y
    rad = math.radians(deg)
    c = math.cos(rad)
    s = math.sin(rad)
    return x * c - y * s, x * s + y * c


def palette_for_template() -> list:
    """List of {kind, label} dicts ordered as they appear in the menu."""
    order = ['resistor', 'capacitor', 'inductor', 'diode', 'led',
             'transistor_npn', 'mosfet_n', 'opamp', 'switch_spst',
             'vcc', 'ground', 'junction']
    return [{'kind': k, 'label': SYMBOLS[k]['label']} for k in order
            if k in SYMBOLS]

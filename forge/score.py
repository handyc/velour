"""Truth-table fitness for forge circuits.

Given a grid + ports + target, run one wireworld simulation per truth-
table row. For each row:
  - For inputs whose row-bit is 1, force the input cell to head (2)
    at tick 0 (single-shot pulse).
  - Step the rule for `ticks` ticks.
  - For each output cell, scan ticks within `eval_window` for a head;
    that's the observed bit.
  - Compare observed bits to the row's expected output bits.

Fitness = correct rows / total rows, ∈ [0, 1].

The single-pulse / scan-for-head encoding is deliberate for v1 because:
  - It matches "did a signal arrive at the output" semantics directly.
  - Wireworld pulses are stable + countable; you don't need phase or
    timing tricks to get a bit out.
  - GA fitness gradients on this metric are straightforward — a circuit
    that propagates *some* signal scores >0 even if it's not yet
    correct on every row.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from automaton.packed import PackedRuleset
from taxon.engine import _step

from .wireworld import build_wireworld_rule


_PACKED: PackedRuleset | None = None


def _packed() -> PackedRuleset:
    global _PACKED
    if _PACKED is None:
        _PACKED = build_wireworld_rule()
    return _PACKED


# Standard 2-input gate truth tables. Used by /score/ when the page
# sends preset='AND' etc. and lets the server generate the rows.
_GATES_2: dict[str, list[int]] = {
    'AND':  [0, 0, 0, 1],   # A=0,B=0 -> 0; ...; A=1,B=1 -> 1
    'OR':   [0, 1, 1, 1],
    'XOR':  [0, 1, 1, 0],
    'NAND': [1, 1, 1, 0],
    'NOR':  [1, 0, 0, 0],
    'XNOR': [1, 0, 0, 1],
}


def preset_truth_table(preset: str) -> list[dict[str, list[int]]] | None:
    """Generate a 2-input truth table for a preset gate name."""
    table = _GATES_2.get(preset.upper())
    if table is None:
        return None
    rows = []
    for i, out in enumerate(table):
        rows.append({'in': [(i >> 1) & 1, i & 1], 'out': [out]})
    return rows


def score_circuit(*, grid: list[list[int]],
                  ports: list[dict[str, Any]],
                  width: int, height: int,
                  target: dict[str, Any]) -> dict[str, Any]:
    """Run every truth-table row and return per-row + aggregate scores.

    target shape:
        {
          'inputs': ['A', 'B'],          # port names → bit columns
          'outputs': ['Q'],
          'rows': [{'in': [0,0], 'out': [0]}, …],
          'ticks': 30,                    # simulation horizon per row
          'eval_window': [5, 30],         # trajectory indices to scan
        }
    """
    inputs_by_name = {p['name']: p for p in ports
                      if p.get('role') == 'input'}
    outputs_by_name = {p['name']: p for p in ports
                       if p.get('role') == 'output'}

    in_names = list(target.get('inputs', []))
    out_names = list(target.get('outputs', []))
    missing_in = [n for n in in_names if n not in inputs_by_name]
    missing_out = [n for n in out_names if n not in outputs_by_name]
    if missing_in or missing_out:
        return {
            'ok': False,
            'reason': (f'missing ports — inputs: {missing_in or "—"}, '
                       f'outputs: {missing_out or "—"}'),
        }

    rows = list(target.get('rows', []))
    if not rows:
        return {'ok': False, 'reason': 'target has no truth-table rows'}

    ticks = max(1, min(200, int(target.get('ticks', 30))))
    ew = target.get('eval_window') or [0, ticks]
    t_lo = max(0, int(ew[0]))
    t_hi = min(ticks + 1, max(t_lo + 1, int(ew[1])))

    packed = _packed()
    base = np.array(grid, dtype=np.uint8)
    if base.shape != (height, width):
        return {
            'ok': False,
            'reason': (f'grid shape {tuple(base.shape)} != '
                       f'({height}, {width})'),
        }

    correct = 0
    row_results = []
    for row in rows:
        in_bits = list(row.get('in', []))
        out_expected = list(row.get('out', []))
        if (len(in_bits) != len(in_names)
                or len(out_expected) != len(out_names)):
            row_results.append({
                'ok': False, 'in': in_bits,
                'expected': out_expected, 'actual': [],
                'reason': 'row width mismatch',
            })
            continue

        g = base.copy()
        # Inject input pulses at t=0 for active inputs.
        for name, bit in zip(in_names, in_bits):
            if not bit:
                continue
            p = inputs_by_name[name]
            g[p['y'], p['x']] = 2

        traj = [g.copy()]
        for _ in range(ticks):
            g = _step(g, packed)
            traj.append(g.copy())

        actual = []
        for name in out_names:
            p = outputs_by_name[name]
            saw_head = any(int(traj[t][p['y'], p['x']]) == 2
                           for t in range(t_lo, min(t_hi, len(traj))))
            actual.append(1 if saw_head else 0)

        ok = actual == out_expected
        if ok:
            correct += 1
        row_results.append({
            'ok': ok, 'in': in_bits,
            'expected': out_expected, 'actual': actual,
        })

    total = len(rows)
    return {
        'ok': True,
        'inputs': in_names,
        'outputs': out_names,
        'ticks': ticks, 'eval_window': [t_lo, t_hi],
        'correct': correct, 'total': total,
        'fitness': correct / total if total else 0.0,
        'rows': row_results,
    }

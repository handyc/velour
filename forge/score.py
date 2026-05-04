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

from .sim import hex_step, wireworld_lookup


# Standard 2-input single-output gates. Output bit per row.
_GATES_2: dict[str, list[int]] = {
    'AND':  [0, 0, 0, 1],
    'OR':   [0, 1, 1, 1],
    'XOR':  [0, 1, 1, 0],
    'NAND': [1, 1, 1, 0],
    'NOR':  [1, 0, 0, 0],
    'XNOR': [1, 0, 0, 1],
}


# Multi-output presets. Each row gives input bits followed by expected
# output bits. Stored as (inputs, outputs) tuples per row.
_GATES_MULTI: dict[str, list[tuple[list[int], list[int]]]] = {
    # A, B → sum, carry
    'HALF_ADDER': [
        ([0, 0], [0, 0]),
        ([0, 1], [1, 0]),
        ([1, 0], [1, 0]),
        ([1, 1], [0, 1]),
    ],
    # A, B, Cin → sum, Cout
    'FULL_ADDER': [
        ([0, 0, 0], [0, 0]),
        ([0, 0, 1], [1, 0]),
        ([0, 1, 0], [1, 0]),
        ([0, 1, 1], [0, 1]),
        ([1, 0, 0], [1, 0]),
        ([1, 0, 1], [0, 1]),
        ([1, 1, 0], [0, 1]),
        ([1, 1, 1], [1, 1]),
    ],
    # 1-bit → 2-bit "1 hot": 0 → 10, 1 → 01
    'DECODE_1':   [([0], [1, 0]), ([1], [0, 1])],
    # 2-bit one-hot encoder: 00,01,10,11 → 0001,0010,0100,1000
    'DECODE_2':   [
        ([0, 0], [1, 0, 0, 0]),
        ([0, 1], [0, 1, 0, 0]),
        ([1, 0], [0, 0, 1, 0]),
        ([1, 1], [0, 0, 0, 1]),
    ],
}


# Preset metadata: preferred input/output port names.
PRESET_DEFAULTS: dict[str, dict[str, list[str]]] = {
    'AND':         {'inputs': ['A', 'B'],      'outputs': ['Q']},
    'OR':          {'inputs': ['A', 'B'],      'outputs': ['Q']},
    'XOR':         {'inputs': ['A', 'B'],      'outputs': ['Q']},
    'NAND':        {'inputs': ['A', 'B'],      'outputs': ['Q']},
    'NOR':         {'inputs': ['A', 'B'],      'outputs': ['Q']},
    'XNOR':        {'inputs': ['A', 'B'],      'outputs': ['Q']},
    'HALF_ADDER':  {'inputs': ['A', 'B'],      'outputs': ['Q', 'R']},
    'FULL_ADDER':  {'inputs': ['A', 'B', 'C'], 'outputs': ['Q', 'R']},
    'DECODE_1':    {'inputs': ['A'],           'outputs': ['Q', 'R']},
    'DECODE_2':    {'inputs': ['A', 'B'],      'outputs': ['Q', 'R', 'S', 'T']},
}


def preset_truth_table(preset: str) -> list[dict[str, list[int]]] | None:
    """Generate a truth table for a preset gate name."""
    p = preset.upper()
    if p in _GATES_2:
        table = _GATES_2[p]
        rows = []
        for i, out in enumerate(table):
            rows.append({'in': [(i >> 1) & 1, i & 1], 'out': [out]})
        return rows
    if p in _GATES_MULTI:
        return [{'in': list(in_), 'out': list(out_)}
                for (in_, out_) in _GATES_MULTI[p]]
    return None


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

    lut = wireworld_lookup()
    base = np.array(grid, dtype=np.uint8)
    if base.shape != (height, width):
        return {
            'ok': False,
            'reason': (f'grid shape {tuple(base.shape)} != '
                       f'({height}, {width})'),
        }

    # Heads-saturation thresholds for graded scoring. Picked empirically:
    # 3 heads of credit covers a clean pulse train under standard
    # wireworld dynamics (head→tail→wire takes 3 ticks) without
    # over-rewarding circuits that just spew pulses everywhere.
    SAT_HEADS = 3
    FALSE_POS_PENALTY = 0.2

    correct = 0
    graded_total = 0.0
    row_results = []
    for row in rows:
        in_bits = list(row.get('in', []))
        out_expected = list(row.get('out', []))
        if (len(in_bits) != len(in_names)
                or len(out_expected) != len(out_names)):
            row_results.append({
                'ok': False, 'score': 0.0, 'in': in_bits,
                'expected': out_expected, 'actual': [], 'heads': [],
                'reason': 'row width mismatch',
            })
            continue

        g = base.copy()
        for name, bit in zip(in_names, in_bits):
            if not bit:
                continue
            p = inputs_by_name[name]
            g[p['y'], p['x']] = 2

        traj = [g.copy()]
        for _ in range(ticks):
            g = hex_step(g, lut, n_colors=4)
            traj.append(g.copy())

        actual: list[int] = []
        head_counts: list[int] = []
        per_output_scores: list[float] = []
        t_max = min(t_hi, len(traj))
        for name, expected_bit in zip(out_names, out_expected):
            p = outputs_by_name[name]
            head_count = 0
            for t in range(t_lo, t_max):
                if int(traj[t][p['y'], p['x']]) == 2:
                    head_count += 1
            head_counts.append(head_count)
            saw = head_count > 0
            actual.append(1 if saw else 0)
            if expected_bit == 1:
                # Want a pulse — saturate at SAT_HEADS heads.
                per_output_scores.append(min(1.0, head_count / SAT_HEADS))
            else:
                # Want quiet — gentle decay with head count.
                per_output_scores.append(
                    max(0.0, 1.0 - head_count * FALSE_POS_PENALTY)
                )

        row_score = (sum(per_output_scores) / len(per_output_scores)
                     if per_output_scores else 0.0)
        # `ok` = exact bit match (used for the UI ✓/✗ and the
        # `correct` row counter); `score` = graded value driving the GA.
        # The two only diverge when a circuit gets the right pattern but
        # produces fewer heads than the saturation threshold (or extra
        # heads on a row that wanted silence).
        ok = (actual == out_expected)
        if ok:
            correct += 1
        graded_total += row_score
        row_results.append({
            'ok': ok, 'score': row_score,
            'in': in_bits,
            'expected': out_expected, 'actual': actual,
            'heads': head_counts,
        })

    total = len(rows)
    fitness = (graded_total / total) if total else 0.0
    return {
        'ok': True,
        'inputs': in_names,
        'outputs': out_names,
        'ticks': ticks, 'eval_window': [t_lo, t_hi],
        'correct': correct, 'total': total,
        'fitness': fitness,
        'rows': row_results,
    }

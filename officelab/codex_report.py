"""Daily Codex digest for officelab.

One-pager: latest fork's size against the 64 KB cap, headroom, the
biggest fork-to-fork jump in history, and the top-3 features by
code+data so the user knows where the budget is actually going."""

from __future__ import annotations


def report() -> dict:
    from .analyzer import analyse_all, BUDGET_BYTES

    versions, baseline = analyse_all()
    if not versions:
        return {
            'title':     'Officelab',
            'sort_hint': 70,
            'body_md':   '_no `*.dbg` artefacts found — '
                         'run `make dbg` in `isolation/artifacts/office/`._',
        }

    latest = versions[-1]
    pct = 100.0 * latest.binary_size / BUDGET_BYTES
    left = BUDGET_BYTES - latest.binary_size

    biggest = max(versions, key=lambda v: v.delta_vs_prev or 0)
    biggest_delta = biggest.delta_vs_prev or 0

    code_rows = sorted(
        ((b.text + b.data, n) for n, b in latest.features.items()),
        reverse=True,
    )
    top3 = code_rows[:3]

    lines = [
        f'Latest: **{latest.name}** — '
        f'{latest.binary_size:,} B ({pct:.1f}% of 64 KB), '
        f'{left:,} B headroom.',
        '',
        f'Biggest jump in history: **{biggest.name}** '
        f'(+{biggest_delta:,} B vs previous fork).',
        '',
        '**Top features in latest:**',
    ]
    for code, name in top3:
        lines.append(f'- `{name}` — {code:,} B')

    return {
        'title':     'Officelab',
        'sort_hint': 70,
        'body_md':   '\n'.join(lines),
    }

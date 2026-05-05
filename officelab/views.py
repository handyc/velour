"""Views for officelab.

The analyser shells out to nm/size on the .dbg binaries.  If those
don't exist, we render a hint to run `make dbg` in the office dir
rather than 500ing.
"""
from __future__ import annotations

from django.http import Http404
from django.shortcuts import render

from . import analyzer
from .analyzer import (
    BUDGET_BYTES,
    OFFICE_DIR,
    VersionAnalysis,
    analyse_all,
    analyse_one,
    feature_order,
)


def _features_sorted_by_size(va: VersionAnalysis) -> list[tuple[str, int, int, int, int]]:
    """Returns [(feature, text, data, bss, code_total), ...] descending by code_total."""
    rows = []
    for name, b in va.features.items():
        rows.append((name, b.text, b.data, b.bss, b.text + b.data))
    rows.sort(key=lambda r: -r[4])
    return rows


def _build_overview(versions: list[VersionAnalysis], baseline: VersionAnalysis | None):
    overview = []
    for v in versions:
        overhead = baseline.binary_size if baseline else 0
        useful = max(0, v.binary_size - overhead)
        overview.append({
            'name':           v.name,
            'binary_size':    v.binary_size,
            'delta':          v.delta_vs_prev or 0,
            'source_lines':   v.source_lines,
            'useful_bytes':   useful,
            'budget_pct':     min(100.0, 100.0 * v.binary_size / BUDGET_BYTES),
            'budget_left':    max(0, BUDGET_BYTES - v.binary_size),
            'over_budget':    v.binary_size > BUDGET_BYTES,
            'new_features':   v.new_features,
            'feature_count':  sum(
                1 for f, b in v.features.items() if b.text + b.data > 0
            ),
        })
    return overview


def _missing_dbg_context() -> dict:
    """Render a help message if the .dbg files aren't built yet."""
    return {
        'office_dir': str(OFFICE_DIR),
        'build_cmd':  'make dbg',
        'budget':     BUDGET_BYTES,
    }


def index(request):
    versions, baseline = analyse_all()
    if not versions:
        return render(request, 'officelab/needs_build.html',
                      _missing_dbg_context())

    rows = _build_overview(versions, baseline)

    # The two recent forks (office7) added the biggest jump — surface
    # that explicitly so the user knows where their budget went.
    biggest_jump = max(rows, key=lambda r: r['delta']) if rows else None

    return render(request, 'officelab/index.html', {
        'versions':     rows,
        'all_versions': [v.name for v in versions],
        'baseline':     baseline,
        'budget':       BUDGET_BYTES,
        'biggest':      biggest_jump,
        'latest':       rows[-1] if rows else None,
    })


def version_view(request, version: str):
    if version not in analyzer.VERSIONS + [analyzer.BASELINE]:
        raise Http404(f"unknown version: {version}")
    va = analyse_one(version)
    if va is None:
        return render(request, 'officelab/needs_build.html',
                      _missing_dbg_context())

    versions, baseline = analyse_all()
    overhead = baseline.binary_size if baseline else 0

    feature_rows = []
    code_total = 0
    bss_total = 0
    for name, text, data, bss, code in _features_sorted_by_size(va):
        feature_rows.append({
            'name':       name,
            'text':       text,
            'data':       data,
            'code':       code,
            'bss':        bss,
            'pct_binary': 100.0 * code / max(1, va.binary_size),
            'pct_useful': 100.0 * code / max(1, va.binary_size - overhead),
            'sym_count':  len(va.features[name].syms),
        })
        code_total += code
        bss_total += bss

    # bytes not pinned to a feature: ELF headers, program headers,
    # alignment padding, .rodata strings shared by ANSI escapes, the
    # .comment section if it stuck around, etc.  Compute as binary -
    # attributed - baseline; if > 0, label it "elf overhead".
    attributed_disk = code_total + overhead
    elf_overhead = max(0, va.binary_size - attributed_disk)

    return render(request, 'officelab/version.html', {
        'va':           va,
        'feature_rows': feature_rows,
        'code_total':   code_total,
        'bss_total':    bss_total,
        'baseline':     baseline,
        'overhead':     overhead,
        'useful_bytes': max(0, va.binary_size - overhead),
        'elf_overhead': elf_overhead,
        'budget':       BUDGET_BYTES,
        'budget_left':  max(0, BUDGET_BYTES - va.binary_size),
        'budget_pct':   min(100.0, 100.0 * va.binary_size / BUDGET_BYTES),
        'all_versions': [v.name for v in versions],
    })


def budget(request):
    versions, baseline = analyse_all()
    if not versions:
        return render(request, 'officelab/needs_build.html',
                      _missing_dbg_context())

    latest = versions[-1]
    overhead = baseline.binary_size if baseline else 0

    # bytes-per-feature ranking with a "bytes per source line" measure
    # so the user can see which features are *expensive* per line of
    # code (often a sign there's room to compress).
    feature_rows = []
    for name, text, data, bss, code in _features_sorted_by_size(latest):
        feature_rows.append({
            'name': name,
            'code': code,
            'bss':  bss,
            'syms': len(latest.features[name].syms),
        })

    return render(request, 'officelab/budget.html', {
        'latest':       latest,
        'feature_rows': feature_rows,
        'all_versions': [v.name for v in versions],
        'baseline':     baseline,
        'overhead':     overhead,
        'budget':       BUDGET_BYTES,
        'budget_left':  max(0, BUDGET_BYTES - latest.binary_size),
        'budget_pct':   min(100.0, 100.0 * latest.binary_size / BUDGET_BYTES),
        'over_budget':  latest.binary_size > BUDGET_BYTES,
    })

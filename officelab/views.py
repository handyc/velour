"""Views for officelab.

The analyser shells out to nm/size on the .dbg binaries.  If those
don't exist, we render a hint to run `make dbg` in the office dir
rather than 500ing.
"""
from __future__ import annotations

import subprocess
import time

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_POST

from . import analyzer
from .analyzer import (
    BUDGET_BYTES,
    BUDGET_TIERS,
    FAMILIES,
    OFFICE_DIR,
    VersionAnalysis,
    analyse_all,
    analyse_family,
    analyse_one,
    analyse_paths,
    feature_order,
    tier_for,
)


def _family(request) -> str:
    """Pick the active family from ?family=, defaulting to 'office'.
    Unknown values fall back to 'office' so old links keep working."""
    f = (request.GET.get('family') or 'office').strip()
    return f if f in FAMILIES else 'office'


def _family_context(family: str) -> dict:
    """Stamp every render with the tab-switch context: which family is
    active, the list of all families, and a `family_qs` string the
    nav links can splice into existing URLs (e.g. `?family=officerpgc`)
    so they stay on the same tab when navigating."""
    return {
        'family':     family,
        'families':   FAMILIES,
        'family_qs':  f"?family={family}" if family != 'office' else '',
    }


def _analyse_one_in_family(family: str, version: str):
    """Resolve a single VersionAnalysis inside `family`.  For the
    office family this is the existing analyse_one; for others it
    walks the family's version list."""
    if family == 'office':
        return analyse_one(version)
    versions, _ = analyse_family(family)
    for v in versions:
        if v.name == version:
            return v
    return None


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
            # Tier-1 budget metrics kept under the same keys for
            # back-compat; over_budget here means 'over the 64 KB
            # tier', not 'over every tier'.  Use .tier.over for the
            # 1 MB ceiling check.
            'budget_pct':     min(100.0, 100.0 * v.binary_size / BUDGET_BYTES),
            'budget_left':    max(0, BUDGET_BYTES - v.binary_size),
            'over_budget':    v.binary_size > BUDGET_BYTES,
            'tier':           tier_for(v.binary_size),
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
    family = _family(request)
    versions, baseline = analyse_family(family)
    if not versions:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})

    rows = _build_overview(versions, baseline)

    # Surface the fork that grew the binary most so the user knows
    # where their budget went.
    biggest_jump = max(rows, key=lambda r: r['delta']) if rows else None

    return render(request, 'officelab/index.html', {
        'versions':     rows,
        'all_versions': [v.name for v in versions],
        'baseline':     baseline,
        'budget':       BUDGET_BYTES,
        'budget_tiers': BUDGET_TIERS,
        'biggest':      biggest_jump,
        'latest':       rows[-1] if rows else None,
        **_family_context(family),
    })


def version_view(request, version: str):
    family = _family(request)
    versions, baseline = analyse_family(family)
    valid_names = [v.name for v in versions]
    if family == 'office':
        valid_names = analyzer.VERSIONS + [analyzer.BASELINE]
    if version not in valid_names:
        raise Http404(f"unknown version in family {family}: {version}")
    va = _analyse_one_in_family(family, version)
    if va is None:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})
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

    top_n, top_syms, top_size_max = _top_symbols(va, request)

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
        'top_syms':     top_syms,
        'top_n':        top_n,
        'top_size_max': top_size_max,
        **_family_context(family),
    })


_SECTION_LABEL = {
    't': 'text', 'T': 'text',
    'd': 'data', 'D': 'data',
    'r': 'rodata', 'R': 'rodata',
    'b': 'bss',  'B': 'bss',
}


def _top_symbols(va: VersionAnalysis, request):
    """Flatten every feature's symbol list and pick the top-N largest.

    A 'where did the bytes go' lens — closes the loop from feature
    totals down to the individual function/static that contributed.
    `n` is overridable via ?n= (clamped 5..200, default 40)."""
    try:
        top_n = int(request.GET.get('n', '40'))
    except ValueError:
        top_n = 40
    top_n = max(5, min(200, top_n))

    flat = []
    for fb in va.features.values():
        for s in fb.syms:
            flat.append({
                'name':    s.name,
                'feature': fb.name,
                'size':    s.size,
                'section': _SECTION_LABEL.get(s.section, s.section),
                'is_code': s.is_code,
                'is_bss':  s.is_bss,
                'pct':     100.0 * s.size / max(1, va.binary_size),
            })
    flat.sort(key=lambda r: -r['size'])
    top = flat[:top_n]
    size_max = top[0]['size'] if top else 1
    return top_n, top, size_max


def diff_view(request):
    """Compare two forks: per-feature delta + per-symbol churn.

    a/b come from ?a=&b=. Defaults: penultimate vs latest fork. The
    feature table renders bytes added/removed *and* moved (a feature
    that lost text but gained data still shows churn); the symbol
    churn list ranks raw |Δ| so the things that actually moved bubble
    up first, regardless of whether they were added, deleted, or
    just resized."""
    family = _family(request)
    versions, baseline = analyse_family(family)
    if len(versions) < 2:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})

    names = [v.name for v in versions]
    default_b = names[-1]
    default_a = names[-2]
    a = request.GET.get('a') or default_a
    b = request.GET.get('b') or default_b

    valid = set(names) | {analyzer.BASELINE}
    if a not in valid: a = default_a
    if b not in valid: b = default_b

    va_a = _analyse_one_in_family(family, a)
    va_b = _analyse_one_in_family(family, b)
    if va_a is None or va_b is None:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})

    feat_rows = _diff_features(va_a, va_b)
    sym_rows  = _diff_symbols(va_a, va_b, request)

    return render(request, 'officelab/diff.html', {
        'va_a': va_a,
        'va_b': va_b,
        'feat_rows':    feat_rows,
        'sym_rows':     sym_rows,
        'sym_n':        len(sym_rows),
        'all_versions': names + [analyzer.BASELINE],
        'binary_delta': va_b.binary_size - va_a.binary_size,
        'baseline':     baseline,
        'budget':       BUDGET_BYTES,
        'budget_pct_a': min(100.0, 100.0 * va_a.binary_size / BUDGET_BYTES),
        'budget_pct_b': min(100.0, 100.0 * va_b.binary_size / BUDGET_BYTES),
        **_family_context(family),
    })


def _diff_features(va_a, va_b):
    """Per-feature (text+data) delta sorted by |Δ| desc."""
    feats = set(va_a.features) | set(va_b.features)
    rows = []
    for f in feats:
        a_b = va_a.features.get(f)
        b_b = va_b.features.get(f)
        a_code = (a_b.text + a_b.data) if a_b else 0
        b_code = (b_b.text + b_b.data) if b_b else 0
        delta = b_code - a_code
        rows.append({
            'name':   f,
            'a':      a_code,
            'b':      b_code,
            'delta':  delta,
            'state':  'added' if a_code == 0 and b_code > 0
                      else 'removed' if b_code == 0 and a_code > 0
                      else 'unchanged' if delta == 0
                      else 'changed',
        })
    rows.sort(key=lambda r: -abs(r['delta']))
    return rows


def _diff_symbols(va_a, va_b, request):
    """Per-symbol churn sorted by |Δ| desc; default top-60 from ?n=."""
    try:
        n = int(request.GET.get('n', '60'))
    except ValueError:
        n = 60
    n = max(10, min(300, n))

    a_syms = {}
    for fb in va_a.features.values():
        for s in fb.syms:
            a_syms[s.name] = (s.size, fb.name, s.section)
    b_syms = {}
    for fb in va_b.features.values():
        for s in fb.syms:
            b_syms[s.name] = (s.size, fb.name, s.section)

    keys = set(a_syms) | set(b_syms)
    rows = []
    for k in keys:
        a_size, a_feat, _   = a_syms.get(k, (0, '—', ''))
        b_size, b_feat, sec = b_syms.get(k, (0, '—', ''))
        delta = b_size - a_size
        if delta == 0:
            continue
        rows.append({
            'name':    k,
            'feature': b_feat if b_size else a_feat,
            'section': _SECTION_LABEL.get(sec, sec or '—'),
            'a':       a_size,
            'b':       b_size,
            'delta':   delta,
            'state':   'added' if a_size == 0
                       else 'removed' if b_size == 0
                       else 'changed',
        })
    rows.sort(key=lambda r: -abs(r['delta']))
    return rows[:n]


@require_POST
def rebuild(request):
    """Run `make -j all dbg` in OFFICE_DIR and render the log.

    Synchronous; 120 s ceiling. The cc invocations are -Os and the
    suite is ~38 KB of source — typical run is well under 5 s. We
    don't bother with background tasks; if it ever gets that slow,
    revisit. The analyser keys its cache off the .dbg mtime, so the
    next page load picks up the fresh binaries automatically."""
    cmd = ['make', '-j', 'all', 'dbg']
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(OFFICE_DIR),
            capture_output=True, text=True, timeout=120,
        )
        rc       = proc.returncode
        stdout   = proc.stdout
        stderr   = proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        rc       = -1
        stdout   = e.stdout or ''
        stderr   = (e.stderr or '') + '\n[timed out after 120 s]'
        timed_out = True
    elapsed = time.monotonic() - started

    return render(request, 'officelab/rebuild.html', {
        'cmd':        ' '.join(cmd),
        'cwd':        str(OFFICE_DIR),
        'rc':         rc,
        'ok':         rc == 0,
        'stdout':     stdout,
        'stderr':     stderr,
        'timed_out':  timed_out,
        'elapsed':    elapsed,
        'all_versions': analyzer.VERSIONS + [analyzer.BASELINE],
    })


def planner(request):
    """Headroom planner: 'what fits in the remaining budget?'.

    Sandbox for sketching office8+. The user enters candidate features
    as `name = bytes` lines (one per line); we sum them on top of the
    latest fork's binary size and show whether each addition still
    fits under the 64 KB cap, plus a running total. The 'reference'
    table seeds estimates from existing features so the user has a
    sense of typical costs."""
    family = _family(request)
    versions, baseline = analyse_family(family)
    if not versions:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})

    latest = versions[-1]
    overhead = baseline.binary_size if baseline else 0

    plan_text = request.GET.get('plan', '')
    candidates, plan_errors = _parse_plan(plan_text)

    running = latest.binary_size
    plan_rows = []
    for c in candidates:
        running += c['bytes']
        plan_rows.append({
            **c,
            'running':    running,
            'budget_pct': min(100.0, 100.0 * running / BUDGET_BYTES),
            'over':       running > BUDGET_BYTES,
            'left':       BUDGET_BYTES - running,
        })

    # Reference: every existing feature's current code+data cost in
    # the latest fork, sorted desc — gives the user a calibrated
    # sense of "what does adding a feature like X usually cost."
    ref_rows = []
    for name, text, data, bss, code in _features_sorted_by_size(latest):
        ref_rows.append({'name': name, 'code': code, 'bss': bss})

    # First-time costs: when did each feature show up, and what was
    # the binary delta on that fork? Adds another data point on top
    # of "current cost". Per-fork delta is noisy (compiler whim,
    # other shared-infra refactors land alongside), so we label it
    # honestly: 'fork delta when introduced.'
    first_seen = []
    seen = set()
    prev_size = None
    for v in versions:
        for f in v.new_features:
            if f in seen:
                continue
            seen.add(f)
            first_seen.append({
                'name':       f,
                'introduced': v.name,
                'fork_delta': (v.binary_size - prev_size) if prev_size else None,
            })
        prev_size = v.binary_size

    return render(request, 'officelab/planner.html', {
        'latest':       latest,
        'baseline':     baseline,
        'overhead':     overhead,
        'budget':       BUDGET_BYTES,
        'budget_left':  max(0, BUDGET_BYTES - latest.binary_size),
        'budget_pct':   min(100.0, 100.0 * latest.binary_size / BUDGET_BYTES),
        'plan_text':    plan_text,
        'plan_rows':    plan_rows,
        'plan_errors':  plan_errors,
        'plan_total':   running - latest.binary_size,
        'plan_final':   running,
        'plan_over':    running > BUDGET_BYTES,
        'ref_rows':     ref_rows,
        'first_seen':   first_seen,
        'all_versions': [v.name for v in versions],
        **_family_context(family),
    })


def _parse_plan(plan_text: str):
    """`name = N` (or `name: N`, or `N name`) one per line. Bytes accepts
    `2k`, `1.5K`, `512`. Blank lines and `#` comments skipped."""
    rows = []
    errors = []
    for lineno, raw in enumerate((plan_text or '').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        # split on = or : first; fall back to whitespace
        if '=' in line:
            name, _, val = line.partition('=')
        elif ':' in line:
            name, _, val = line.partition(':')
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                errors.append(f'line {lineno}: expected `name = bytes` — got `{line}`')
                continue
            # accept either order
            if parts[0].rstrip('kKbB').replace('.', '').isdigit():
                val, name = parts
            else:
                name, val = parts
        name = name.strip()
        val = val.strip()
        if not name:
            errors.append(f'line {lineno}: empty name')
            continue
        try:
            b = _parse_bytes(val)
        except ValueError as e:
            errors.append(f'line {lineno}: {e}')
            continue
        rows.append({'name': name, 'bytes': b})
    return rows, errors


def _parse_bytes(s: str) -> int:
    s = s.strip().lower().rstrip('b')
    mult = 1
    if s.endswith('k'):
        mult, s = 1024, s[:-1]
    elif s.endswith('m'):
        mult, s = 1024 * 1024, s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        raise ValueError(f"can't parse `{s}` as bytes")


# Category map — mirrors OfficeForge's grouping so the same colour
# convention reads consistently across both apps.  "infra" is the
# always-on bedrock (boot, syscalls, terminal, framebuffer, etc.) that
# can't be toggled off; the four colour bands let you eyeball the
# binary's composition at a glance.
TREEMAP_CATEGORIES = {
    # core
    "notepad": "core", "sheet": "core", "hex": "core",
    "files": "core", "calc": "core", "shell": "core",

    # extras (selectable but optional)
    "ask": "extras", "garden": "extras", "hxhnt": "extras",
    "rpg": "extras", "lsys": "extras", "screensaver": "extras",
    "sheet_macros": "extras", "bytebeat": "extras", "bfc": "extras",
    "mines": "extras", "word": "extras", "paint": "extras",
    "find": "extras", "mail": "extras", "export": "extras",
    # soul — embedded int8 transformer (officeagent + officesoul)
    "soul": "extras",

    # network stack — tier-1..tier-5 of office60..office64
    "net_panel": "network", "http": "network",
    "echo": "network", "finger": "network", "gopher": "network",
    "tcp_runner": "network", "probe": "network",
    "dns": "network", "ftp": "network", "sshtel": "network",

    # always-on infrastructure
    "baseline": "infra", "menu": "infra", "chrome": "infra",
    "framebuffer": "infra", "term": "infra", "syscalls": "infra",
    "libc_replacements": "infra", "shared_buf": "infra",
    "clipboard": "infra",

    # uncategorized symbols and the synthetic headroom tile
    "uncategorized": "other",
    "_headroom":     "headroom",
    "_overage":      "overage",
}


def treemap(request):
    """Treemap showing how the latest fork's bytes fill the 64 KB
    target.  Each feature is one tile sized by its (text + data + bss);
    a synthetic "headroom" tile fills the remaining budget when under,
    or is replaced by an "overage" tile when over."""
    family = _family(request)
    versions, baseline = analyse_family(family)
    if not versions:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})

    requested = request.GET.get('v', '').strip()
    target = None
    if requested:
        for v in versions:
            if v.name == requested:
                target = v
                break
    if target is None:
        target = versions[-1]

    # Size each tile by what actually lands on disk: text + data only.
    # bss is a runtime allocation (zeros reserved at process start),
    # not stored in the ELF.  Including it would make rpg dwarf the
    # treemap by its 1.8 MB world-buffer that doesn't cost any disk.
    items = []
    sym_total = 0
    for name, b in target.features.items():
        sz = b.text + b.data
        if sz <= 0:
            continue
        items.append({
            "name":     name,
            "size":     sz,
            "text":     b.text,
            "data":     b.data,
            "bss":      b.bss,
            "syms":     len(b.syms),
            "category": TREEMAP_CATEGORIES.get(name, "other"),
        })
        sym_total += sz
    # uncategorized lump (text + data only, same rule)
    uncat_text_data = sum(
        s.size for s in target.uncategorized
        if s.section in ("t", "T", "d", "D", "r", "R")
    )
    uncat_bss = sum(
        s.size for s in target.uncategorized
        if s.section in ("b", "B")
    )
    if uncat_text_data > 0:
        items.append({
            "name":     "uncategorized",
            "size":     uncat_text_data,
            "text":     uncat_text_data, "data": 0, "bss": uncat_bss,
            "syms":     len(target.uncategorized),
            "category": "other",
        })
        sym_total += uncat_text_data

    # ELF overhead: everything in the binary that nm doesn't enumerate
    # — program/section headers, the gap-padding ld inserts to align
    # sections to the 512-byte page-size we set, dropped-symbol stubs
    # if any.  Without surfacing this as a tile, the treemap claimed
    # headroom that didn't exist (e.g. office53 reported 8987 B of
    # phantom headroom but was actually 1376 B *over* the 64 KB cap).
    overhead = max(0, target.binary_size - sym_total)
    if overhead > 0:
        items.append({
            "name":     "_elf_overhead",
            "size":     overhead,
            "text":     0, "data": 0, "bss": 0, "syms": 0,
            "category": "overhead",
        })

    # Now headroom is computed from the *actual binary size*, not the
    # symbol sum.  This matches the budget page's number.
    over_budget = target.binary_size > BUDGET_BYTES
    overage     = max(0, target.binary_size - BUDGET_BYTES)
    headroom    = max(0, BUDGET_BYTES - target.binary_size)
    if not over_budget and headroom > 0:
        items.append({
            "name":     "_headroom",
            "size":     headroom,
            "text":     0, "data": 0, "bss": 0, "syms": 0,
            "category": "headroom",
        })

    items.sort(key=lambda x: -x["size"])

    return render(request, "officelab/treemap.html", {
        "target":         target,
        "items":          items,
        "all_versions":  [v.name for v in versions],
        "budget":         BUDGET_BYTES,
        "binary_size":    target.binary_size,
        "sym_total":      sym_total,
        "overhead":       overhead,
        "over_budget":    over_budget,
        "overage":        overage,
        "headroom":       headroom,
        **_family_context(family),
    })


def budget(request):
    family = _family(request)
    versions, baseline = analyse_family(family)
    if not versions:
        return render(request, 'officelab/needs_build.html',
                      {**_missing_dbg_context(), **_family_context(family)})

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
        **_family_context(family),
    })

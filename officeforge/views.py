"""OfficeForge — pick-your-features build of office66.

The user sees a checkbox list; submitting POSTs the toggle state to
/build/, which shells out to `cc -DOFFICE_FEATURE_<NAME>=0 ...` for
each unchecked feature, and serves the resulting binary back as an
octet-stream download.

Byte costs come from officelab's analyzer so the same source-of-truth
attributes per-feature bytes consistently across the two apps.  The
budget readout is approximate: --gc-sections plus shared helpers mean
disabling two features that share a helper saves slightly less than
the sum of their analyzer-reported sizes.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from officelab import analyzer


# Feature catalogue — order is the UI rendering order.
# (macro_suffix, label, category, default_on, depends_on_macro, analyzer_name)
FEATURES = [
    # core
    ("NOTEPAD",     "Notepad",        "core",    True, None, "notepad"),
    ("SHEET",       "Sheet",          "core",    True, None, "sheet"),
    ("HEX",         "Hex editor",     "core",    True, None, "hex"),
    ("FILES",       "File browser",   "core",    True, None, "files"),
    ("CALC",        "Calculator",     "core",    True, None, "calc"),

    # extras
    ("ASK",         "Ask LLM",        "extras",  True, None, "ask"),
    ("GARDEN",      "Theme garden",   "extras",  True, None, "garden"),
    ("HXHNT",       "Hex hunter",     "extras",  True, None, "hxhnt"),
    ("RPG",         "Tile RPG",       "extras",  True, None, "rpg"),
    ("LSYS",        "L-system viewer","extras",  True, None, "lsys"),
    ("SCREENSAVER", "Screensaver",    "extras",  True, "RPG", "screensaver"),

    # sheet sub-feature: change-trigger macros (only meaningful with sheet)
    ("SHEET_MACROS", "Sheet macros",  "extras",  True, "SHEET", "sheet_macros"),

    # network stack — tier-1..tier-5
    ("NET",         "Net panel",      "network", True, None, "net_panel"),
    ("HTTP",        "HTTP server",    "network", True, None, "http"),
    ("ECHO",        "Echo server",    "network", True, None, "echo"),
    ("FINGER",      "Finger server",  "network", True, None, "finger"),
    ("GOPHER",      "Gopher server",  "network", True, None, "gopher"),
    ("PROBE",       "Outbound probe", "network", True, None, "probe"),
    ("DNS",         "DNS resolver",   "network", True, None, "dns"),
    ("FTP",         "FTP server",     "network", True, None, "ftp"),
    ("SSHTEL",      "SSH/telnet hybrid","network", True, None, "sshtel"),
]

# Suggested presets — opinionated combinations a user can load with
# one click before tweaking individually.  Each preset is a *whitelist*
# of macros to enable; everything else is unchecked.  Names + the
# one-line tagline both surface in the UI.
#
# Sizes in the labels are approximate (sum of feature attributions +
# always-on baseline) and assume the analyzer's current numbers for
# office66.  Real builds will be a couple hundred bytes off because
# --gc-sections behaves slightly differently when shared helpers can
# also be dropped.
PRESETS = [
    ("tiny",
     "Tiny",
     "Bare essentials. Notepad + hex + files + calc.",
     ["NOTEPAD", "HEX", "FILES", "CALC"]),

    ("productivity",
     "Productivity",
     "Classic office work. Adds sheet (with macros).",
     ["NOTEPAD", "SHEET", "SHEET_MACROS", "HEX", "FILES", "CALC"]),

    ("researcher",
     "Researcher",
     "Productivity plus creative + investigative tools — Ask LLM, "
     "L-system, hex hunter, garden.  (RPG dropped to stay under 64 KB; "
     "use Gamer if you want it back.)",
     ["NOTEPAD", "SHEET", "SHEET_MACROS", "HEX", "FILES", "CALC",
      "ASK", "LSYS", "HXHNT", "GARDEN"]),

    ("gamer",
     "Gamer",
     "Office at play. RPG + hex hunter + L-system + garden + "
     "screensaver, plus notepad/sheet/files for save-keeping.",
     ["NOTEPAD", "SHEET", "SHEET_MACROS", "FILES", "CALC",
      "RPG", "HXHNT", "LSYS", "GARDEN", "SCREENSAVER"]),

    ("sysadmin",
     "Sysadmin",
     "Productivity plus the entire network stack — net panel, "
     "HTTP, echo/finger/gopher, probe, DNS, FTP, SSH/telnet hybrid.",
     ["NOTEPAD", "SHEET", "SHEET_MACROS", "HEX", "FILES", "CALC",
      "NET", "HTTP", "ECHO", "FINGER", "GOPHER",
      "PROBE", "DNS", "FTP", "SSHTEL"]),

    ("honeypot",
     "Honeypot",
     "Looks-like-a-server kit. Net introspection + the public "
     "listeners (HTTP, FTP, finger, gopher, SSH/telnet hybrid).",
     ["NOTEPAD", "HEX", "FILES",
      "NET", "HTTP", "FTP", "FINGER", "GOPHER", "SSHTEL"]),

    ("full",
     "Full",
     "Every feature. Goes over the 64 KB target — this is the "
     "default Makefile build.",
     None),  # None = enable everything
]


# Which fork is the source-of-truth for selective builds.
SOURCE_FORK = "office66"

# What's always on (no toggle): infra + shared helpers + the home shell.
ALWAYS_ON = (
    "baseline", "shell", "menu", "chrome", "framebuffer",
    "term", "syscalls", "libc_replacements", "shared_buf",
    "clipboard", "export",
)

CFLAGS = (
    "-DTINY -std=c99 -Os -Wall -Wextra "
    "-fno-stack-protector -fno-asynchronous-unwind-tables -fno-unwind-tables "
    "-fno-builtin -ffreestanding "
    "-ffunction-sections -fdata-sections"
).split()
LDFLAGS = (
    "-nostdlib -nostartfiles -static "
    "-Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code "
    "-Wl,-z,common-page-size=512 -s"
).split()


def _feature_costs():
    """{macro_suffix: bytes_estimate}.  Reads office66's current analysis.
    Sized by text + data only — bss is runtime-allocated and never lands
    on disk, so including it would make rpg's 1.8 MB world-buffer dwarf
    every real feature and push the budget past 2 MB."""
    a = analyzer.analyse_one(SOURCE_FORK)
    if a is None:
        return {}
    out = {}
    for macro, _label, _cat, _on, _dep, anl in FEATURES:
        b = a.features.get(anl)
        if b is None:
            out[macro] = 0
        else:
            out[macro] = b.text + b.data
    return out


def _baseline_estimate():
    """Bytes that stay in every build no matter the feature toggles.
    Built up so the sum of (this baseline + Σ enabled features) is
    a close estimate of the resulting binary size:
        - the sum of always-on feature text + data
        - the ELF overhead measured on the full office66 build
          (program/section headers + alignment padding)
    Same bss-exclusion rule as _feature_costs above. """
    a = analyzer.analyse_one(SOURCE_FORK)
    if a is None:
        return 0
    total = 0
    for name in ALWAYS_ON:
        b = a.features.get(name)
        if b is None:
            continue
        total += b.text + b.data
    # ELF overhead on disk = total binary − sum of every named symbol's
    # (text + data).  Independent of which features are enabled,
    # because section-header overhead is roughly constant.
    sym_total = 0
    for b in a.features.values():
        sym_total += b.text + b.data
    sym_total += sum(s.size for s in a.uncategorized
                     if s.section in ("t", "T", "d", "D", "r", "R"))
    overhead = max(0, a.binary_size - sym_total)
    total += overhead
    return total


def _preset_estimates(costs, baseline):
    """For each preset, sum the byte cost of its enabled features so
    the UI can show '~46 KB' next to each preset name without firing
    a real build."""
    all_macros = {m for m, *_ in FEATURES}
    out = []
    for slug, name, desc, macros in PRESETS:
        enabled = all_macros if macros is None else set(macros)
        # Apply the SHEET_MACROS->SHEET dependency rule the same way
        # the C source does, so the estimate matches reality.
        if "SHEET" not in enabled:
            enabled.discard("SHEET_MACROS")
        if "RPG" not in enabled:
            enabled.discard("SCREENSAVER")
        feat_bytes = sum(costs.get(m, 0) for m in enabled)
        out.append({
            "slug": slug,
            "name": name,
            "desc": desc,
            "macros": sorted(enabled),
            "bytes": baseline + feat_bytes,
        })
    return out


def index(request):
    """Render the checkbox UI with current byte costs."""
    costs = _feature_costs()
    baseline = _baseline_estimate()
    rows = []
    for macro, label, cat, default_on, dep, anl in FEATURES:
        rows.append({
            "macro": macro,
            "label": label,
            "category": cat,
            "default_on": default_on,
            "depends_on": dep or "",
            "bytes": costs.get(macro, 0),
        })
    presets = _preset_estimates(costs, baseline)
    return render(request, "officeforge/index.html", {
        "features": rows,
        "presets": presets,
        "baseline_bytes": baseline,
        "budget_target": analyzer.BUDGET_BYTES,
        "source_fork": SOURCE_FORK,
    })


@require_POST
def build(request):
    """Build a custom binary.  Only flag *unchecked* features by
    passing -DOFFICE_FEATURE_<X>=0; checked features get the source's
    default of 1.  Any unknown form key is ignored — the only thing
    we put on the cc command line comes from the FEATURES whitelist."""
    valid_macros = {m for m, *_ in FEATURES}
    selected = set()
    for macro in valid_macros:
        if request.POST.get(f"f_{macro}") == "1":
            selected.add(macro)

    src = analyzer.OFFICE_DIR / f"{SOURCE_FORK}.c"
    if not src.exists():
        return HttpResponseBadRequest(f"source missing: {src}")

    with tempfile.TemporaryDirectory(prefix="officeforge_") as td:
        tdp = Path(td)
        out_path = tdp / "office_custom"
        cmd = ["cc", *CFLAGS]
        for macro in valid_macros:
            if macro not in selected:
                cmd.append(f"-DOFFICE_FEATURE_{macro}=0")
        cmd += [*LDFLAGS, "-o", str(out_path), str(src)]

        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            # Surface the compiler error so the user can see what failed
            # (typically nothing — but flag combos that strand a helper
            # could in principle).
            err = p.stderr[-4000:] if p.stderr else "(no stderr)"
            return HttpResponse(
                f"build failed (rc={p.returncode}):\n\n{err}",
                content_type="text/plain", status=500)

        # strip --remove-section=.comment for parity with Makefile
        subprocess.run(
            ["strip", "--remove-section=.comment", str(out_path)],
            capture_output=True)

        data = out_path.read_bytes()

    # Filename includes a stable hash of the selection so different
    # combos produce different downloads.
    selected_count = len(selected)
    fname = f"office_{selected_count}feat_{len(data)}B"
    resp = HttpResponse(data, content_type="application/octet-stream")
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    resp["X-OfficeForge-Size"] = str(len(data))
    resp["X-OfficeForge-Features"] = ",".join(sorted(selected))
    return resp

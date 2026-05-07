"""Per-feature byte attribution for the office..officeN ELFs.

The analyser shells out to `nm --print-size` and `size` on the
unstripped *.dbg binaries built by isolation/artifacts/office/Makefile.
Each symbol is matched against an ordered pattern table to assign it
to a feature; per-feature byte sums and a 64 KB budget readout fall
out from there.

Lazy + cached for the Django process lifetime: the .dbg files don't
change between analyser runs unless `make dbg` is re-run, so we cache
on (path, mtime, size).
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings


# Where the office artefacts live.  Resolved relative to BASE_DIR so
# this works in any checkout layout.
OFFICE_DIR = Path(settings.BASE_DIR) / "isolation" / "artifacts" / "office"

# All known versions, in order.  `minimal` is the baseline.
VERSIONS = ["office", "office2", "office3", "office4",
            "office5", "office6", "office7", "office8", "office9",
            "office10", "office11", "office12", "office13", "office14",
            "office15", "office16", "office17", "office18", "office19",
            "office20", "office21", "office22", "office23", "office24",
            "office25", "office26", "office27", "office28",
            "office29", "office30", "office31", "office32",
            "office33", "office34", "office35", "office36", "office37",
            "office38", "office39", "office40", "office41", "office42",
            "office43", "office44", "office45", "office46", "office47",
            "office48", "office49"]
BASELINE = "minimal"

# 64 KB binary cap that the user is shooting for.
BUDGET_BYTES = 64 * 1024


# ── feature pattern table ────────────────────────────────────────────
#
# Ordered list of (feature, regex).  First match wins.  Each regex
# matches against the *symbol name only* (no leading underscore).  Be
# careful with order: more-specific patterns must come before more
# general ones.

# Helper: bracket the alternation so we don't repeat the prefix glue.
def _re(*alts: str) -> str:
    return r"^(" + "|".join(alts) + r")$"


#
# Patterns match against the *normalised* symbol name (gcc's
# `.isra.0`, `.constprop.0`, `.cold`, and trailing `.<digit>`
# disambiguators all stripped).  So `req.5` → `req`,
# `run_shell.isra.0` → `run_shell`,
# `files_scan.constprop.0.isra.0` → `files_scan`.
#
# Each entry is `(feature_name, prefixes, exacts)`:
#   - prefixes: matched as `name.startswith(p)`
#   - exacts:   matched as `name == e`
# First (feature, prefix-or-exact) match wins.

FEATURE_PATTERNS: list[tuple[str, list[str], list[str]]] = [
    # ── per-app code ──
    ("ask",
     ["run_ask", "ask_", "mF_ask", "ms_ask"],
     # function-local statics inside ask_*: gcc-disambiguated as
     # req.5, resp.11, auth.4, content.10, etc.  `tmp` is only used
     # as a static array in ask_load_conf / ask_save_conf, so it's
     # safe to attribute to ask across the suite.
     ["req", "resp", "auth", "content", "emsg", "errmsg", "input",
      "labels", "needle", "tmp"]),

    ("garden",
     ["run_garden", "garden_", "mF_garden", "mE_garden", "ms_garden"],
     ["g_pop", "g_marked", "g_generation", "g_rng_state", "g_genome",
      "border_chars", "last_msg", "hex_mode"]),

    # hxhnt — class-4 hex-CA hunter, ported from
    # isolation/artifacts/oneclick_class4/hunter.c into office15+.
    # `u2` is the 2-digit zero-padder added alongside clock_render in
    # office11; `atoi_` is hxhnt's own arg parser.
    ("hxhnt",
     ["run_hxhnt", "hx_", "HX_", "mF_hxhnt", "mE_hxhnt", "ms_hxhnt"],
     ["mdays", "u2", "atoi_"]),

    # rpg — tile explorer driven by the .hxseed ruleset (office20+);
    # office22+ adds entity layer (plants/buildings/animals/items),
    # player stats (HP/MP/inventory), spells, and z-sorted occluding
    # sprites that overdraw cells north of tall objects.  office37+
    # adds the meta-overworld stack; office40 adds wander paths;
    # office41 the seamless 3×3 mosaic.
    ("rpg",
     ["run_rpg", "rpg_", "RPG_"],
     []),

    # bytebeat — tiny PCM synth with curl→aplay/paplay/ffplay
    # playback (office39+).  bb_eval / bb_render_and_play and the
    # preset name/formula tables.
    ("bytebeat",
     ["run_bytebeat", "bb_", "BB_"],
     []),

    # screensaver — auto-plays the rpg world in fullscreen until
    # any keypress (office43+).  Owns g_rpg_fullscreen because it's
    # the only caller; rpg sets it to 0 on entry/exit.
    ("screensaver",
     ["run_screensaver"],
     ["g_rpg_fullscreen"]),

    # lsys — character-mode L-system viewer (office21+).  4 category
    # interpretations of the same axiom+rule grammar.
    ("lsys",
     ["run_lsys", "lsys_", "LSYS_"],
     ["g_lsys_min_x", "g_lsys_min_y", "g_lsys_max_x", "g_lsys_max_y",
      "g_lsys_ox", "g_lsys_oy", "g_lsys_glyph", "g_lsys_col"]),

    # office19+ — generic splice export shared by hxhnt and garden.
    ("export",
     ["office_splice", "gd_splice_export", "gd_embedded", "gd_payload",
      "gd_export_seq"],
     []),

    ("notepad",
     ["run_notepad", "notepad_", "npad_"],
     ["line_start_at", "line_end_at", "line_index_of", "line_count",
      "line_start_after", "ms_notepad"]),

    ("word",
     ["run_word", "ms_word", "word_", "mV_word", "reflow_"],
     []),

    ("mail",
     ["run_mail", "mail_", "ms_mail", "mE_paste"],
     []),

    ("sheet",
     ["run_sheet", "sheet_", "feval_", "ms_sheet", "parse_ref",
      "skip_ws", "fskip_ws", "try_cellref", "match_func",
      "range_reduce", "cell", "cellrow", "cellcol"],
     ["fp", "rscratch", "cval"]),

    ("paint",
     ["run_paint", "canvas", "canvas_fg", "paint_", "ms_paint"],
     ["brush", "cur_sx", "cur_sy", "px", "py"]),

    ("hex",
     ["run_hex", "hex_", "ms_hex", "mV_hex"],
     []),

    ("bfc",
     ["run_bfc", "bf_", "brainfuck"],
     ["tape"]),

    ("files",
     ["run_files", "files_", "ms_files"],
     []),

    ("find",
     ["run_find", "find_", "ms_find"],
     []),

    ("calc",
     ["run_calc", "calc_", "ms_calc"],
     []),

    ("mines",
     ["run_mines", "mines_", "m_", "mF_mines", "ms_mines"],
     ["q"]),                             # `q` = flood-fill queue

    ("shell",
     ["run_shell", "shell_", "ms_shell"],
     []),

    # ── shared infrastructure ──
    ("clipboard",
     ["cb_"],
     ["cb"]),

    ("shared_buf",
     ["buf_"],
     ["buf", "blen", "bcur", "btop", "fname",
      "load_file", "save_file"]),

    # menu engine + the function-local `names` / `titles` arrays.
    ("menu",
     ["menu_", "show_about", "current_ms", "ms_count", "ms_about",
      "mF_full", "mF_save", "mF_quit", "mE_full", "mH_about", "MA_"],
     ["names", "titles"]),

    # chrome + the static `sp` space-filler buffer used by blanks() +
    # the office8 screen_w/screen_h runtime dimensions queried by term_init.
    # office11 added g_tz_offset_sec for the home-screen clock's TZ.
    ("chrome",
     ["chrome", "paint_desktop", "body_clear", "body_at",
      "status", "blanks", "term_init"],
     ["sp", "screen_w", "screen_h", "g_tz_offset_sec"]),

    ("term",
     ["term_raw", "term_cooked"],
     ["read_key", "term_orig"]),

    ("framebuffer",
     ["fb", "cls", "cup", "sgr"],
     []),

    ("libc_replacements",
     [],
     ["slen", "scmp", "mcpy", "mset", "utoa", "itoa_", "sapp",
      "basename_"]),

    ("syscalls",
     [],
     ["sys3", "sys4", "forkk", "wait4_", "execvee"]),

    # ── boot ──
    ("baseline",
     [],
     ["_start", "main_c", "g_envp"]),
]


@dataclass
class SymbolRow:
    name: str
    addr: int
    size: int
    section: str       # 't' = text, 'b' = bss, 'd'/'r' = data/rodata, etc.
    feature: str

    @property
    def is_code(self) -> bool:
        return self.section in ("t", "T")

    @property
    def is_bss(self) -> bool:
        return self.section in ("b", "B")

    @property
    def is_data(self) -> bool:
        return self.section in ("d", "D", "r", "R")


@dataclass
class FeatureBucket:
    name: str
    text: int = 0
    data: int = 0
    bss:  int = 0
    syms: list[SymbolRow] = field(default_factory=list)

    @property
    def code_total(self) -> int:
        return self.text + self.data


@dataclass
class VersionAnalysis:
    name: str                       # e.g. "office7"
    binary_size: int                # stripped on-disk bytes
    dbg_size: int                   # unstripped on-disk bytes
    text: int
    data: int
    bss: int
    source_lines: int
    features: dict[str, FeatureBucket]
    uncategorized: list[SymbolRow]
    delta_vs_prev: int | None = None     # binary-size delta vs. previous fork
    new_features: list[str] = field(default_factory=list)

    baseline_overhead: int = 0      # filled in by analyse_all from minimal.dbg


def _classify(symbol: str) -> str:
    for feat, prefixes, exacts in FEATURE_PATTERNS:
        if symbol in exacts:
            return feat
        for p in prefixes:
            if symbol.startswith(p):
                return feat
    return "uncategorized"


# Symbols whose names get mangled by gcc — strip suffixes so the
# pattern table can match against the original C identifier:
#   run_shell.isra.0    → run_shell      (interprocedural opt)
#   ask_call_curl.cold  → ask_call_curl  (cold path split)
#   tmp.6 / req.5       → tmp / req      (function-local statics
#                                          disambiguated by gcc)
_GCC_SUFFIX = re.compile(
    r"\.(isra|constprop|part|cold|lto_priv)(\.\d+)?$"
)
def _normalise(symbol: str) -> str:
    prev = None
    while symbol != prev:
        prev = symbol
        symbol = _GCC_SUFFIX.sub("", symbol)
        symbol = re.sub(r"\.\d+$", "", symbol)
    return symbol


def _run_nm(dbg_path: Path) -> list[SymbolRow]:
    """Returns only symbols with a known size > 0."""
    out = subprocess.run(
        ["nm", "--print-size", "--size-sort", "-t", "d", str(dbg_path)],
        capture_output=True, text=True, check=False,
    )
    rows: list[SymbolRow] = []
    for line in out.stdout.splitlines():
        # Format:  ADDR  SIZE  TYPE  NAME
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        addr_s, size_s, type_s, name = parts
        try:
            addr = int(addr_s)
            size = int(size_s)
        except ValueError:
            continue
        if size <= 0:
            continue
        feat = _classify(_normalise(name))
        rows.append(SymbolRow(
            name=name, addr=addr, size=size, section=type_s, feature=feat,
        ))
    return rows


def _run_size(path: Path) -> tuple[int, int, int]:
    out = subprocess.run(
        ["size", str(path)], capture_output=True, text=True, check=False,
    )
    lines = out.stdout.strip().splitlines()
    if len(lines) < 2:
        return (0, 0, 0)
    nums = lines[-1].split()[:3]
    try:
        return (int(nums[0]), int(nums[1]), int(nums[2]))
    except (ValueError, IndexError):
        return (0, 0, 0)


def _wc_lines(c_path: Path) -> int:
    try:
        with c_path.open() as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ── public api ────────────────────────────────────────────────────────


def analyse_one(version: str) -> VersionAnalysis | None:
    """Build a VersionAnalysis for `office`/`office7`/etc.  Returns
    None if the .dbg or source is missing — caller should hint the
    user to run `make dbg`."""
    c_path   = OFFICE_DIR / f"{version}.c"
    dbg_path = OFFICE_DIR / f"{version}.dbg"
    bin_path = OFFICE_DIR / version
    if not c_path.exists() or not dbg_path.exists():
        return None

    text, data, bss = _run_size(dbg_path)
    syms = _run_nm(dbg_path)

    feats: dict[str, FeatureBucket] = {}
    uncat: list[SymbolRow] = []
    for s in syms:
        if s.feature == "uncategorized":
            uncat.append(s)
        b = feats.setdefault(s.feature, FeatureBucket(s.feature))
        if s.is_code:
            b.text += s.size
        elif s.is_bss:
            b.bss += s.size
        elif s.is_data:
            b.data += s.size
        b.syms.append(s)

    # Most versions ship as both `office7` (stripped) and `office7.dbg`
    # (with symbols).  `minimal` only exists as `minimal.dbg` — there's
    # no shipping binary because it's analysis-only.  Fall back to the
    # dbg size minus a 1024 B "symbol overhead" estimate so the budget
    # readouts make sense.
    if bin_path.exists():
        binary_size = bin_path.stat().st_size
    else:
        binary_size = max(0, dbg_path.stat().st_size - 1024)
    dbg_size = dbg_path.stat().st_size

    return VersionAnalysis(
        name=version,
        binary_size=binary_size,
        dbg_size=dbg_size,
        text=text,
        data=data,
        bss=bss,
        source_lines=_wc_lines(c_path),
        features=feats,
        uncategorized=uncat,
    )


def analyse_baseline() -> VersionAnalysis | None:
    """The 'Linux ELF + _start + syscall stub' baseline."""
    return analyse_one(BASELINE)


def analyse_all() -> tuple[list[VersionAnalysis], VersionAnalysis | None]:
    """Returns (per-version analyses in order, baseline)."""
    versions: list[VersionAnalysis] = []
    prev_size = None
    prev_features: set[str] = set()
    for v in VERSIONS:
        a = analyse_one(v)
        if a is None:
            continue
        if prev_size is not None:
            a.delta_vs_prev = a.binary_size - prev_size
        cur_features = {f for f, b in a.features.items()
                        if (b.text + b.data) > 0}
        a.new_features = sorted(cur_features - prev_features)
        prev_features = cur_features
        prev_size = a.binary_size
        versions.append(a)
    base = analyse_baseline()
    if base is not None:
        for v in versions:
            v.baseline_overhead = base.binary_size
    return versions, base


def feature_order() -> list[str]:
    """Stable ordering for table columns / chart segments."""
    return [f for f, _, _ in FEATURE_PATTERNS] + ["uncategorized"]

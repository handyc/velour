"""ANSI escape sequence decoder — turn a captured terminal stream
into a 2D grid of `(char, fg, bg)` cells, then render that grid as
a luminance-shaded text image so a non-terminal reader (a person
in a code review, a Claude session, a static HTML page) can read
what was on the screen without paying for a real terminal.

The general feature: given any byte stream that some program would
have spat at a terminal, recover the visual end-state.  The
officerpg shot-export hotkey is the seed use case (write fb to
disk, decode here), but the same module reads any vt100/xterm-256
stream — `script` output, asciicast frames, captured CI logs, etc.

Implementation notes:

  - We emulate a fixed-size grid (default 80×24, configurable).
    The cursor's home position is (0, 0).  Out-of-range cursor
    positions clamp; out-of-range writes are dropped (no scroll).
  - Only the SGR / cursor / clear-screen subset of CSI is
    interpreted; everything else (DECSET 2026 sync output, EL,
    REP, save/restore cursor, etc.) is silently consumed.  That's
    enough for ANSI screenshots from anything not running a TUI
    that uses scroll regions.
  - Colours are tracked as xterm-256 indices (0..255).  fg/bg=
    -1 means "default" (the rendering picks black/white).  16-
    colour SGR codes (30-37 / 40-47 / 90-97 / 100-107) are mapped
    onto the same 256-table indices so downstream rendering is
    uniform.
"""
from __future__ import annotations

from typing import List, Tuple


Cell = Tuple[str, int, int]   # (char, fg_index, bg_index)


# ---------------------------------------------------------------
# xterm-256 palette → RGB.
# ---------------------------------------------------------------

# System 16 colours — the values most modern terminals use.
_SYS16 = [
    (  0,   0,   0), (170,   0,   0), (  0, 170,   0), (170,  85,   0),
    (  0,   0, 170), (170,   0, 170), (  0, 170, 170), (170, 170, 170),
    ( 85,  85,  85), (255,  85,  85), ( 85, 255,  85), (255, 255,  85),
    ( 85,  85, 255), (255,  85, 255), ( 85, 255, 255), (255, 255, 255),
]


def xterm256_rgb(idx: int) -> Tuple[int, int, int]:
    """Map an xterm-256 colour index to (r, g, b)."""
    if idx < 0:
        return (0, 0, 0)
    if idx < 16:
        return _SYS16[idx]
    if idx < 232:
        # 6×6×6 colour cube starting at index 16.  Cube level n is
        # 0 if n=0 else 55 + 40·n; that's the standard formula
        # most terminals (xterm, kitty, alacritty, etc.) honour.
        i = idx - 16
        r = (i // 36) % 6
        g = (i //  6) % 6
        b =  i        % 6
        scale = lambda c: 0 if c == 0 else 55 + 40 * c
        return (scale(r), scale(g), scale(b))
    # 24-step grayscale ramp at indices 232..255.
    g = 8 + (idx - 232) * 10
    return (g, g, g)


# ---------------------------------------------------------------
# Grid emulator.
# ---------------------------------------------------------------

class TerminalGrid:
    def __init__(self, cols: int = 80, rows: int = 24):
        self.cols = cols
        self.rows = rows
        self.reset()

    def reset(self):
        self.cells: List[List[Cell]] = [
            [(' ', -1, -1) for _ in range(self.cols)]
            for _ in range(self.rows)
        ]
        self.cur_r = 0
        self.cur_c = 0
        self.fg = -1
        self.bg = -1

    def _put(self, ch: str):
        if 0 <= self.cur_r < self.rows and 0 <= self.cur_c < self.cols:
            self.cells[self.cur_r][self.cur_c] = (ch, self.fg, self.bg)
        self.cur_c += 1
        if self.cur_c >= self.cols:
            self.cur_c = self.cols - 1   # clamp; no auto-wrap

    def _newline(self):
        self.cur_r = min(self.cur_r + 1, self.rows - 1)

    def _carriage_return(self):
        self.cur_c = 0

    def _clear_screen(self):
        self.cells = [
            [(' ', self.fg, self.bg) for _ in range(self.cols)]
            for _ in range(self.rows)
        ]


# ---------------------------------------------------------------
# Stream parser.
# ---------------------------------------------------------------

def _parse_csi_params(s: str):
    """Parse the parameter substring of a CSI sequence (everything
    between '[' and the final byte) into a list of ints, treating
    empty values as 0.  Returns the list + an `intro` byte that
    tells the SGR handler whether the sequence began with '?' or
    similar non-digit private prefix (so we can ignore those).
    """
    intro = ''
    if s and s[0] in '?>':
        intro = s[0]
        s = s[1:]
    if not s:
        return [], intro
    parts = []
    for p in s.split(';'):
        try:
            parts.append(int(p) if p else 0)
        except ValueError:
            parts.append(0)
    return parts, intro


def _apply_sgr(grid: TerminalGrid, params: list[int]):
    """Apply an SGR sequence to the grid's pen state.  Handles
    reset, 8/16 colour, xterm-256 (38;5;n / 48;5;n).  Bold +
    italic + underline are accepted but not tracked (we only
    care about colour for visual analysis)."""
    if not params:
        params = [0]
    i = 0
    while i < len(params):
        n = params[i]
        if n == 0:
            grid.fg = -1; grid.bg = -1
            i += 1
        elif 30 <= n <= 37:
            grid.fg = n - 30; i += 1
        elif n == 39:
            grid.fg = -1; i += 1
        elif 40 <= n <= 47:
            grid.bg = n - 40; i += 1
        elif n == 49:
            grid.bg = -1; i += 1
        elif 90 <= n <= 97:
            grid.fg = n - 90 + 8; i += 1
        elif 100 <= n <= 107:
            grid.bg = n - 100 + 8; i += 1
        elif n == 38 and i + 2 < len(params) and params[i + 1] == 5:
            grid.fg = params[i + 2] & 0xff; i += 3
        elif n == 48 and i + 2 < len(params) and params[i + 1] == 5:
            grid.bg = params[i + 2] & 0xff; i += 3
        elif n == 38 and i + 4 < len(params) and params[i + 1] == 2:
            # 24-bit fg — collapse to nearest cube index.
            r, g, b = params[i+2], params[i+3], params[i+4]
            grid.fg = _rgb_to_cube(r, g, b); i += 5
        elif n == 48 and i + 4 < len(params) and params[i + 1] == 2:
            r, g, b = params[i+2], params[i+3], params[i+4]
            grid.bg = _rgb_to_cube(r, g, b); i += 5
        else:
            i += 1


def _rgb_to_cube(r: int, g: int, b: int) -> int:
    """Approximate a 24-bit RGB triple by the nearest 6×6×6 cube
    cell.  Good enough for analysis output."""
    def to_cube(c: int) -> int:
        if c < 48: return 0
        if c < 115: return 1
        return min(5, (c - 35) // 40)
    return 16 + to_cube(r) * 36 + to_cube(g) * 6 + to_cube(b)


def split_frames(data) -> list[bytes]:
    """Split a stream that uses DECSET 2026 (synchronized output)
    into one bytes-payload per frame.  Each emitted slice is one
    self-contained `\\033[?2026h … \\033[?2026l` block, ready to
    feed into `parse()` independently.

    officerpg's fbflush wraps every frame this way, so a captured
    session lays down one well-formed slice per render iteration.
    Streams without sync markers get a single-frame fallback (the
    whole input is the one frame).
    """
    if isinstance(data, (bytes, bytearray)):
        s = bytes(data)
    else:
        s = data.encode('utf-8', errors='replace')
    BEGIN = b'\x1b[?2026h'
    frames: list[bytes] = []
    i = 0
    n = len(s)
    while i < n:
        j = s.find(BEGIN, i + 1)
        if j == -1:
            frames.append(s[i:])
            break
        frames.append(s[i:j])
        i = j
    if not frames:
        frames = [s]
    # Drop empty leading frames (a stream that opens with a
    # BEGIN marker would otherwise yield a zero-byte first slice).
    return [f for f in frames if f]


def parse(data, cols: int = 80, rows: int = 24) -> TerminalGrid:
    """Parse a byte stream of vt100/xterm-256 escape sequences into
    a fresh TerminalGrid.  Convenience wrapper around parse_into."""
    g = TerminalGrid(cols=cols, rows=rows)
    parse_into(g, data)
    return g


def parse_frames(data, cols: int = 80, rows: int = 24) -> list[TerminalGrid]:
    """Replay a sync-output-bracketed stream and snapshot the grid
    after each frame.  Cells / cursor / pen state carry across
    frames so an incremental repaint reads as the running cumulative
    image, not as 24 rows of "default cell" plus the new patch.

    Returns a list of independent TerminalGrid instances — caller
    can render any of them, scrub through them, or pull just the
    last one for the equivalent of a single-frame parse().
    """
    import copy
    slices = split_frames(data)
    snapshots: list[TerminalGrid] = []
    g = TerminalGrid(cols=cols, rows=rows)
    for sl in slices:
        parse_into(g, sl)
        snapshots.append(copy.deepcopy(g))
    return snapshots


def parse_into(g: TerminalGrid, data) -> TerminalGrid:
    """Apply an ANSI byte stream onto an existing TerminalGrid.
    Lets a caller replay a multi-frame stream while carrying
    cell + cursor + pen state across frame boundaries — important
    for analysis of incremental redraws (status-bar-only updates,
    partial repaints, etc.)."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode('utf-8', errors='replace')
    i = 0
    n = len(data)
    while i < n:
        ch = data[i]
        if ch == '\x1b' and i + 1 < n:
            nxt = data[i + 1]
            if nxt == '[':
                # CSI: collect parameters until a final byte 0x40-0x7e.
                j = i + 2
                while j < n and not (0x40 <= ord(data[j]) <= 0x7e):
                    j += 1
                if j >= n:
                    break
                final = data[j]
                params_str = data[i + 2:j]
                i = j + 1
                params, intro = _parse_csi_params(params_str)
                if intro == '?':
                    # Private mode (DECSET 2026, etc.) — ignore.
                    continue
                if final in 'Hf':
                    r = (params[0] - 1) if params and params[0] > 0 else 0
                    c = (params[1] - 1) if len(params) > 1 and params[1] > 0 else 0
                    g.cur_r = max(0, min(r, g.rows - 1))
                    g.cur_c = max(0, min(c, g.cols - 1))
                elif final == 'A':
                    d = params[0] if params else 1
                    g.cur_r = max(0, g.cur_r - d)
                elif final == 'B':
                    d = params[0] if params else 1
                    g.cur_r = min(g.rows - 1, g.cur_r + d)
                elif final == 'C':
                    d = params[0] if params else 1
                    g.cur_c = min(g.cols - 1, g.cur_c + d)
                elif final == 'D':
                    d = params[0] if params else 1
                    g.cur_c = max(0, g.cur_c - d)
                elif final == 'J':
                    mode = params[0] if params else 0
                    if mode == 2:
                        g._clear_screen()
                    # 0/1 are partial clears — ignore for analysis
                    # (we already initialised to spaces).
                elif final == 'K':
                    # Erase in line — clear from cursor to end of
                    # row at the current bg.
                    mode = params[0] if params else 0
                    if mode == 0:
                        for c in range(g.cur_c, g.cols):
                            g.cells[g.cur_r][c] = (' ', g.fg, g.bg)
                    elif mode == 1:
                        for c in range(0, g.cur_c + 1):
                            g.cells[g.cur_r][c] = (' ', g.fg, g.bg)
                    elif mode == 2:
                        for c in range(g.cols):
                            g.cells[g.cur_r][c] = (' ', g.fg, g.bg)
                elif final == 'm':
                    _apply_sgr(g, params)
                # Other CSI finals (s, u, r, etc.) — ignored.
                continue
            elif nxt == ']':
                # OSC: skip until BEL (0x07) or ESC \.
                j = i + 2
                while j < n:
                    if data[j] == '\x07':
                        j += 1; break
                    if data[j] == '\x1b' and j + 1 < n and data[j+1] == '\\':
                        j += 2; break
                    j += 1
                i = j
                continue
            else:
                # Two-byte ESC sequence (ESC =, ESC >, ESC c, etc.).
                if nxt == 'c':
                    g.reset()
                i += 2
                continue
        if ch == '\r':
            g._carriage_return(); i += 1
        elif ch == '\n':
            g._newline(); i += 1
        elif ch == '\b':
            g.cur_c = max(0, g.cur_c - 1); i += 1
        elif ch == '\t':
            g.cur_c = min(g.cols - 1, (g.cur_c + 8) & ~7); i += 1
        elif ch < ' ':
            i += 1   # other control chars — ignore
        else:
            g._put(ch); i += 1
    return g


# ---------------------------------------------------------------
# Rendering — turn a grid into something a non-terminal reader
# can absorb.
# ---------------------------------------------------------------

# Shading characters from lightest to darkest, indexed by the
# bg luminance of an empty (' ') cell.
_SHADES = ' .,:;-=+*#%@'


def _luminance(rgb):
    """Rec. 601 luminance, scaled to [0, 1]."""
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def render_shaded(grid: TerminalGrid) -> str:
    """ASCII-art rendering: glyph cells keep their character;
    space cells map to a shading char chosen by their bg colour's
    luminance.  Trailing whitespace per line is stripped.  Result
    reads as a faithful black-and-white view of what the screen
    looked like."""
    lines = []
    for row in grid.cells:
        chars = []
        for (ch, fg, bg) in row:
            if ch != ' ':
                chars.append(ch)
            else:
                rgb = xterm256_rgb(bg) if bg >= 0 else (0, 0, 0)
                lum = _luminance(rgb)
                idx = int(lum * (len(_SHADES) - 1))
                chars.append(_SHADES[idx])
        lines.append(''.join(chars).rstrip())
    return '\n'.join(lines)


def render_html(grid: TerminalGrid) -> str:
    """A `<pre>` block where every cell carries its inline bg/fg
    style.  Suitable for embedding in a Velour template — gives
    the reader the actual colours, preserved pixel-for-pixel."""
    out = ['<pre style="line-height:1; font-family:'
           'ui-monospace,Menlo,monospace; margin:0;">']
    for row in grid.cells:
        run = []
        cur_style = None
        for (ch, fg, bg) in row:
            fg_rgb = xterm256_rgb(fg) if fg >= 0 else (200, 200, 200)
            bg_rgb = xterm256_rgb(bg) if bg >= 0 else (0, 0, 0)
            style = (
                f'color:rgb({fg_rgb[0]},{fg_rgb[1]},{fg_rgb[2]});'
                f'background:rgb({bg_rgb[0]},{bg_rgb[1]},{bg_rgb[2]});'
            )
            if style != cur_style:
                if run:
                    out.append(f'<span style="{cur_style}">'
                               f'{"".join(run)}</span>')
                run = []
                cur_style = style
            # HTML-escape the printable char.
            if ch == '<':   ch = '&lt;'
            elif ch == '>': ch = '&gt;'
            elif ch == '&': ch = '&amp;'
            run.append(ch)
        if run:
            out.append(f'<span style="{cur_style}">'
                       f'{"".join(run)}</span>')
        out.append('\n')
    out.append('</pre>')
    return ''.join(out)


def color_summary(grid: TerminalGrid) -> str:
    """Tally distinct (fg, bg) pairs in the grid + their
    occurrence counts.  Useful to confirm a render hit the
    expected palette without paging through 24×80 cells."""
    from collections import Counter
    counts = Counter()
    for row in grid.cells:
        for (ch, fg, bg) in row:
            counts[(fg, bg)] += 1
    lines = []
    for (fg, bg), n in counts.most_common():
        fg_rgb = xterm256_rgb(fg) if fg >= 0 else None
        bg_rgb = xterm256_rgb(bg) if bg >= 0 else None
        fg_s = f'#{fg:3d}={fg_rgb}' if fg >= 0 else '(default)'
        bg_s = f'#{bg:3d}={bg_rgb}' if bg >= 0 else '(default)'
        lines.append(f'  fg={fg_s:30s}  bg={bg_s:30s}  ×{n}')
    return '\n'.join(lines)

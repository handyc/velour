"""Tufte sparklines — word-sized inline data graphics.

Draws directly into an fpdf2 FPDF object using vector primitives.
No images, no rasterization, no extra dependencies.

A sparkline is, in Tufte's words, a "small intense, simple,
word-sized graphic with typographic resolution... data-intense,
design-simple, word-sized graphics" with a data-ink ratio of 1.0:
no frames, no axes, no labels, no gridlines, only the data.

Sparklines are the DEFAULT way to express quantitative data in
Codex documentation. When you can fit it inline, use a sparkline.

Defaults:
  - Width:  22mm   (roughly 14 letterspaces of 11pt body text)
  - Height: 2.8mm  (roughly the cap-height of 11pt ET Book)
  - Line:   muted dark gray, 0.18mm thickness
  - Band:   light gray fill, optional
  - Markers: small filled circles, optional

Variants (set via options):
  (default)     — connected line segments
  bar           — discrete vertical bars
  area          — filled area under the line
  dot           — dot plot (disconnected points)
  winloss       — binary bar: above zero = up, below = down
  band(lo,hi)   — light gray rectangle showing a "normal" range

Options the renderer can request via the parsed spark spec:
  end           — endpoint dot at the rightmost data point
  min, max      — markers at the global minimum / maximum value
  bar           — render as bar variant instead of line
  area          — filled area under the line curve
  dot           — disconnected dots (no connecting lines)
  winloss       — binary up/down bars (positive=up, negative=down)
  band(lo,hi)   — light gray rectangle showing a "normal" range
"""

DEFAULT_W = 22.0          # mm
DEFAULT_H = 2.8           # mm
LINE_WIDTH = 0.18         # mm
LINE_COLOR = (60, 60, 60)
BAND_COLOR = (220, 220, 220)
ENDPOINT_COLOR = (50, 50, 50)
MIN_COLOR = (30, 110, 200)     # blue
MAX_COLOR = (200, 50, 50)      # red
DOT_DIAMETER = 0.9       # mm — markers are small filled circles


def _scale(val, lo, hi, out_lo, out_hi):
    if hi == lo:
        return (out_lo + out_hi) / 2
    return out_lo + (val - lo) * (out_hi - out_lo) / (hi - lo)


def draw_sparkline(pdf, spec, x, y, width=DEFAULT_W, height=DEFAULT_H):
    """Render a sparkline into `pdf` at top-left corner (x, y).

    `spec` is a dict with:
      data:   list[float]
      options: set[str]   — 'end', 'min', 'max', 'bar'
      band:   tuple[float, float] | None

    Returns the actual width consumed (in mm). For empty data,
    returns 0 and draws nothing.
    """
    data = spec.get('data') or []
    if len(data) < 2:
        return 0.0

    options = spec.get('options') or set()
    band = spec.get('band')

    # Save fpdf2 drawing state so we don't pollute the surrounding text.
    saved_draw_color = (pdf.draw_color, pdf.fill_color)
    saved_line_width = pdf.line_width

    data_min = min(data)
    data_max = max(data)

    # If a band is specified, expand the data range so the band sits
    # within the visible plot area even if all data points are inside it.
    plot_min = data_min
    plot_max = data_max
    if band:
        plot_min = min(plot_min, band[0])
        plot_max = max(plot_max, band[1])

    pad = 0.15  # mm — leave a tiny margin so endpoints don't kiss the edge
    plot_top = y + pad
    plot_bot = y + height - pad
    plot_left = x
    plot_right = x + width

    # --- band first (behind the line) ---
    if band:
        b_lo, b_hi = band
        band_top = _scale(b_hi, plot_min, plot_max, plot_bot, plot_top)
        band_bot = _scale(b_lo, plot_min, plot_max, plot_bot, plot_top)
        pdf.set_fill_color(*BAND_COLOR)
        pdf.rect(plot_left, band_top, plot_right - plot_left,
                 band_bot - band_top, style='F')

    n = len(data)
    x_step = (plot_right - plot_left) / (n - 1) if n > 1 else 0

    if 'winloss' in options:
        # Win/loss variant — binary bars: above zero = up, below = down.
        bar_w = (width - 0.18 * width / max(n, 1) * (n - 1)) / n
        gap = 0.18 * (width / max(n, 1))
        mid_y = (plot_top + plot_bot) / 2
        bar_half = (plot_bot - plot_top) * 0.4
        for i, v in enumerate(data):
            bx = plot_left + i * (bar_w + gap)
            if v > 0:
                pdf.set_fill_color(46, 160, 67)   # green
                pdf.rect(bx, mid_y - bar_half, bar_w, bar_half, style='F')
            elif v < 0:
                pdf.set_fill_color(200, 50, 50)    # red
                pdf.rect(bx, mid_y, bar_w, bar_half, style='F')
            else:
                pdf.set_fill_color(*LINE_COLOR)
                pdf.rect(bx, mid_y - 0.1, bar_w, 0.2, style='F')

    elif 'bar' in options:
        # Bar variant — discrete values, no connecting line.
        gap = 0.18 * (width / max(n, 1))
        bar_w = (width - gap * (n - 1)) / n
        baseline = plot_bot
        zero_y = _scale(0, plot_min, plot_max, plot_bot, plot_top)
        if not (plot_min <= 0 <= plot_max):
            zero_y = baseline
        pdf.set_fill_color(*LINE_COLOR)
        for i, v in enumerate(data):
            bx = plot_left + i * (bar_w + gap)
            top = _scale(v, plot_min, plot_max, plot_bot, plot_top)
            if v >= 0:
                pdf.rect(bx, top, bar_w, zero_y - top, style='F')
            else:
                pdf.rect(bx, zero_y, bar_w, top - zero_y, style='F')

    elif 'dot' in options:
        # Dot variant — disconnected points, no lines.
        pdf.set_fill_color(*LINE_COLOR)
        for i, v in enumerate(data):
            px = plot_left + i * x_step
            py = _scale(v, plot_min, plot_max, plot_bot, plot_top)
            pdf.ellipse(px - DOT_DIAMETER / 2, py - DOT_DIAMETER / 2,
                        DOT_DIAMETER, DOT_DIAMETER, style='F')

    elif 'area' in options:
        # Area variant — filled region under the line curve.
        # Draw filled polygon: data points + baseline corners.
        # fpdf2 doesn't have a polygon fill, so we approximate with
        # thin vertical slices (fast, clean at PDF resolution).
        pdf.set_fill_color(*LINE_COLOR)
        baseline_y = plot_bot
        slice_w = (plot_right - plot_left) / max(n - 1, 1)
        for i, v in enumerate(data):
            px = plot_left + i * x_step
            py = _scale(v, plot_min, plot_max, plot_bot, plot_top)
            sw = slice_w if i < n - 1 else slice_w * 0.5
            h = baseline_y - py
            if h > 0.05:
                # Use a light fill for the area
                pdf.set_fill_color(180, 180, 180)
                pdf.rect(px - sw * 0.5, py, sw, h, style='F')
        # Draw the line on top of the area
        pdf.set_draw_color(*LINE_COLOR)
        pdf.set_line_width(LINE_WIDTH)
        prev_x = None
        prev_y = None
        for i, v in enumerate(data):
            px = plot_left + i * x_step
            py = _scale(v, plot_min, plot_max, plot_bot, plot_top)
            if prev_x is not None:
                pdf.line(prev_x, prev_y, px, py)
            prev_x, prev_y = px, py

    else:
        # Line variant (default) — connect consecutive points.
        pdf.set_draw_color(*LINE_COLOR)
        pdf.set_line_width(LINE_WIDTH)
        prev_x = None
        prev_y = None
        for i, v in enumerate(data):
            px = plot_left + i * x_step
            py = _scale(v, plot_min, plot_max, plot_bot, plot_top)
            if prev_x is not None:
                pdf.line(prev_x, prev_y, px, py)
            prev_x, prev_y = px, py

    # --- markers ---
    def _dot(cx, cy, color):
        pdf.set_fill_color(*color)
        pdf.ellipse(cx - DOT_DIAMETER / 2, cy - DOT_DIAMETER / 2,
                    DOT_DIAMETER, DOT_DIAMETER, style='F')

    if 'min' in options:
        idx = data.index(data_min)
        cx = plot_left + idx * (
            (plot_right - plot_left) / (len(data) - 1) if len(data) > 1 else 0
        )
        cy = _scale(data_min, plot_min, plot_max, plot_bot, plot_top)
        _dot(cx, cy, MIN_COLOR)
    if 'max' in options:
        idx = data.index(data_max)
        cx = plot_left + idx * (
            (plot_right - plot_left) / (len(data) - 1) if len(data) > 1 else 0
        )
        cy = _scale(data_max, plot_min, plot_max, plot_bot, plot_top)
        _dot(cx, cy, MAX_COLOR)
    if 'end' in options:
        cx = plot_right
        cy = _scale(data[-1], plot_min, plot_max, plot_bot, plot_top)
        _dot(cx, cy, ENDPOINT_COLOR)

    # Restore drawing state.
    pdf.draw_color, pdf.fill_color = saved_draw_color
    pdf.set_line_width(saved_line_width)

    return width

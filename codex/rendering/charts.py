"""Quantitative graphics for Codex — Tufte + Cleveland + Few + Ware + Munzner.

All charts are drawn directly into an fpdf2 FPDF object using vector
primitives. No matplotlib, no images, no rasterization.

Design principles:
  1. Sparklines are the default. If you can say it in a sparkline, do.
  2. Cleveland-McGill hierarchy drives chart-type selection: position
     along a common scale (bar, line) > length > angle > area.
  3. Colorblind-safe palettes only (ColorBrewer-derived).
  4. High data-ink ratio. No chartjunk, no 3D, no gradients.
  5. Pre-attentive features for emphasis (intensity, not labels).

Chart types:
  - bar         Horizontal bars (Few's default for comparison)
  - column      Vertical bars (for time series with few points)
  - line        Connected points (change over time, ≥7 points)
  - bullet      Few's bullet graph (actual vs target + qualitative ranges)
  - scatter     Position × position (two quantitative variables)
  - histogram   Frequency distribution (single variable)
  - sparkstrip  Multiple sparklines stacked vertically with labels
                (small-multiples for sparklines — the killer feature)

Markdown syntax parsed by the codex markdown module:

    :::chart bar
    title: Server response times (ms)
    data: API=120, Web=95, WS=340, DB=42
    :::

    :::chart bullet
    title: CPU load
    actual: 72
    target: 80
    ranges: 50,80,100
    :::

    :::chart sparkstrip
    title: Weekly trends
    Disk: 40,42,45,43,48,52,55
    CPU:  12,15,14,18,22,19,16
    Mem:  60,62,58,65,70,68,72
    :::

    :::chart line
    title: Requests per hour
    data: 120,135,142,138,156,170,165,180,192,188
    :::
"""

# ---------------------------------------------------------------------------
# Colorblind-safe palette (ColorBrewer "Dark2" — 8 qualitative colors)
# Safe for deuteranopia and protanopia; verified against Viridis principles.
# ---------------------------------------------------------------------------

PALETTE = [
    (27, 158, 119),    # teal
    (217, 95, 2),      # orange
    (117, 112, 179),   # purple
    (231, 41, 138),    # pink
    (102, 166, 30),    # green
    (230, 171, 2),     # gold
    (166, 118, 29),    # brown
    (102, 102, 102),   # gray
]

# Qualitative ranges for bullet graphs (Few's convention)
BULLET_POOR = (220, 220, 220)      # lightest
BULLET_OK = (200, 200, 200)
BULLET_GOOD = (180, 180, 180)      # darkest of the three

# Text/line colors
CHART_BLACK = (30, 30, 30)
CHART_GRAY = (120, 120, 120)
CHART_LIGHT = (200, 200, 200)
CHART_AXIS = (80, 80, 80)

# Default dimensions (mm)
CHART_W = 130.0       # full body column width
CHART_H = 60.0        # default chart height
BAR_H = 5.0           # height of each horizontal bar
BAR_GAP = 2.0         # gap between bars
BULLET_H = 8.0        # bullet graph bar height
SPARKSTRIP_H = 3.2    # height of each sparkline row in a strip
SPARKSTRIP_GAP = 1.8  # gap between strip rows


def _scale(val, lo, hi, out_lo, out_hi):
    """Linear interpolation."""
    if hi == lo:
        return (out_lo + out_hi) / 2
    return out_lo + (val - lo) * (out_hi - out_lo) / (hi - lo)


def _nice_ticks(lo, hi, max_ticks=5):
    """Generate human-friendly tick values for an axis."""
    if hi == lo:
        return [lo]
    span = hi - lo
    # Find a nice step size
    raw_step = span / max_ticks
    magnitude = 1
    while magnitude * 10 <= raw_step:
        magnitude *= 10
    if raw_step / magnitude < 1.5:
        step = magnitude
    elif raw_step / magnitude < 3.5:
        step = magnitude * 2
    elif raw_step / magnitude < 7.5:
        step = magnitude * 5
    else:
        step = magnitude * 10
    # Generate ticks from the floor
    start = int(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.01:
        if v >= lo - step * 0.01:
            ticks.append(v)
        v += step
    return ticks or [lo, hi]


def _fmt(v):
    """Format a number concisely."""
    if v == int(v):
        return str(int(v))
    if abs(v) >= 100:
        return f'{v:.0f}'
    if abs(v) >= 10:
        return f'{v:.1f}'
    return f'{v:.2g}'


# ---------------------------------------------------------------------------
# Horizontal bar chart (Few's default for categorical comparison)
# Cleveland-McGill rank 1: position along a common scale
# ---------------------------------------------------------------------------

def draw_bar_chart(pdf, spec, x, y, width=CHART_W):
    """Horizontal bar chart.

    spec keys:
      title:  str (optional)
      data:   list of (label, value) tuples
      highlight: int index or None (pre-attentive emphasis)
    """
    data = spec.get('data', [])
    if not data:
        return 0
    title = spec.get('title', '')
    highlight = spec.get('highlight')

    n = len(data)
    total_h = n * (BAR_H + BAR_GAP) + 12  # +12 for title + axis
    label_w = 30.0  # mm reserved for labels
    plot_left = x + label_w + 2
    plot_right = x + width
    plot_w = plot_right - plot_left

    values = [v for _, v in data]
    v_min = min(0, min(values))
    v_max = max(values)
    if v_max == v_min:
        v_max = v_min + 1

    cur_y = y

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, cur_y)
        pdf.cell(width, 4, title, align='L')
        cur_y += 5

    # Axis line at zero
    zero_x = _scale(0, v_min, v_max, plot_left, plot_right)
    pdf.set_draw_color(*CHART_AXIS)
    pdf.set_line_width(0.15)
    pdf.line(zero_x, cur_y, zero_x, cur_y + n * (BAR_H + BAR_GAP))

    # Tick marks along the top
    ticks = _nice_ticks(v_min, v_max)
    pdf.set_font('ETBook', '', 7)
    pdf.set_text_color(*CHART_GRAY)
    for tv in ticks:
        tx = _scale(tv, v_min, v_max, plot_left, plot_right)
        pdf.line(tx, cur_y - 0.5, tx, cur_y + 0.5)
        pdf.set_xy(tx - 8, cur_y - 4)
        pdf.cell(16, 3, _fmt(tv), align='C')

    # Bars
    for i, (label, value) in enumerate(data):
        bar_y = cur_y + i * (BAR_H + BAR_GAP)

        # Label
        pdf.set_font('ETBook', '', 8)
        pdf.set_text_color(*CHART_BLACK)
        pdf.set_xy(x, bar_y + 0.5)
        pdf.cell(label_w, BAR_H, label, align='R')

        # Bar
        if highlight is not None and i == highlight:
            color = PALETTE[0]
        else:
            color = PALETTE[0] if n <= 1 else PALETTE[i % len(PALETTE)]
        # Single-color when not highlighting
        if highlight is None and n > 1:
            color = PALETTE[0]

        pdf.set_fill_color(*color)
        if value >= 0:
            bx = zero_x
            bw = _scale(value, v_min, v_max, plot_left, plot_right) - zero_x
        else:
            bx = _scale(value, v_min, v_max, plot_left, plot_right)
            bw = zero_x - bx
        if abs(bw) > 0.1:
            pdf.rect(bx, bar_y, bw, BAR_H, style='F')

        # Value label at end of bar
        pdf.set_font('ETBook', '', 7)
        pdf.set_text_color(*CHART_GRAY)
        end_x = bx + bw if value >= 0 else bx
        pdf.set_xy(end_x + 1, bar_y + 0.5)
        pdf.cell(12, BAR_H - 1, _fmt(value), align='L')

    total_h = cur_y + n * (BAR_H + BAR_GAP) + 2 - y
    pdf.set_text_color(0, 0, 0)
    return total_h


# ---------------------------------------------------------------------------
# Line chart (change over time, ≥7 data points)
# Cleveland-McGill rank 1: position along a common scale
# ---------------------------------------------------------------------------

def draw_line_chart(pdf, spec, x, y, width=CHART_W):
    """Line chart for temporal/sequential data.

    spec keys:
      title:    str (optional)
      data:     list of float values (y-axis, sequential x)
      labels:   list of str x-axis labels (optional, same length as data)
      series:   list of (name, [values]) for multi-line (optional)
    """
    series_list = spec.get('series', [])
    if not series_list:
        data = spec.get('data', [])
        if not data:
            return 0
        series_list = [('', data)]

    title = spec.get('title', '')
    labels = spec.get('labels', [])

    plot_left = x + 12
    plot_right = x + width - 4
    plot_w = plot_right - plot_left
    plot_top = y + (7 if title else 2)
    plot_bot = y + CHART_H - 8
    plot_h = plot_bot - plot_top

    all_values = [v for _, vals in series_list for v in vals]
    v_min = min(all_values)
    v_max = max(all_values)
    if v_max == v_min:
        v_max = v_min + 1

    cur_y = y

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, cur_y)
        pdf.cell(width, 4, title, align='L')

    # Y-axis ticks
    ticks = _nice_ticks(v_min, v_max)
    pdf.set_font('ETBook', '', 7)
    pdf.set_text_color(*CHART_GRAY)
    pdf.set_draw_color(*CHART_LIGHT)
    pdf.set_line_width(0.08)
    for tv in ticks:
        ty = _scale(tv, v_min, v_max, plot_bot, plot_top)
        # Light reference line
        pdf.line(plot_left, ty, plot_right, ty)
        # Tick label
        pdf.set_xy(x, ty - 1.5)
        pdf.cell(11, 3, _fmt(tv), align='R')

    # Data lines
    for si, (name, vals) in enumerate(series_list):
        n = len(vals)
        if n < 2:
            continue
        color = PALETTE[si % len(PALETTE)]
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.35)
        x_step = plot_w / (n - 1) if n > 1 else 0
        prev_px, prev_py = None, None
        for i, v in enumerate(vals):
            px = plot_left + i * x_step
            py = _scale(v, v_min, v_max, plot_bot, plot_top)
            if prev_px is not None:
                pdf.line(prev_px, prev_py, px, py)
            prev_px, prev_py = px, py

        # Series label at end
        if name:
            pdf.set_font('ETBook', '', 7)
            pdf.set_text_color(*color)
            pdf.set_xy(prev_px + 1, prev_py - 1.5)
            pdf.cell(20, 3, name, align='L')

    # X-axis labels
    if labels:
        max_n = len(labels)
        x_step = plot_w / (max_n - 1) if max_n > 1 else 0
        pdf.set_font('ETBook', '', 6.5)
        pdf.set_text_color(*CHART_GRAY)
        # Show at most 10 labels to avoid overlap
        step = max(1, max_n // 10)
        for i in range(0, max_n, step):
            lx = plot_left + i * x_step
            pdf.set_xy(lx - 6, plot_bot + 1)
            pdf.cell(12, 3, str(labels[i]), align='C')

    # Bottom axis
    pdf.set_draw_color(*CHART_AXIS)
    pdf.set_line_width(0.15)
    pdf.line(plot_left, plot_bot, plot_right, plot_bot)

    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    return CHART_H


# ---------------------------------------------------------------------------
# Bullet graph (Few's compact alternative to gauges/dials)
# ---------------------------------------------------------------------------

def draw_bullet_graph(pdf, spec, x, y, width=CHART_W):
    """Few's bullet graph: actual value bar + target marker + ranges.

    spec keys:
      title:   str (optional)
      actual:  float
      target:  float (optional — shown as a thin marker line)
      ranges:  list of 2-3 floats (qualitative range boundaries)
      label:   str (optional, left label)
    """
    actual = spec.get('actual', 0)
    target = spec.get('target')
    ranges = spec.get('ranges', [])
    title = spec.get('title', '')
    label = spec.get('label', '')

    label_w = 30.0
    plot_left = x + label_w + 2
    plot_right = x + width - 4
    plot_w = plot_right - plot_left

    v_max = max([actual] + ([target] if target else []) + ranges) * 1.05
    v_min = 0

    cur_y = y

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, cur_y)
        pdf.cell(width, 4, title, align='L')
        cur_y += 5

    # Label
    if label:
        pdf.set_font('ETBook', '', 8)
        pdf.set_text_color(*CHART_BLACK)
        pdf.set_xy(x, cur_y + 1)
        pdf.cell(label_w, BULLET_H, label, align='R')

    # Qualitative ranges (background bands, lightest to darkest)
    range_colors = [BULLET_POOR, BULLET_OK, BULLET_GOOD]
    sorted_ranges = sorted(ranges)
    prev_x = plot_left
    for i, boundary in enumerate(sorted_ranges):
        bx = _scale(boundary, v_min, v_max, plot_left, plot_right)
        c = range_colors[i % len(range_colors)]
        pdf.set_fill_color(*c)
        pdf.rect(prev_x, cur_y, bx - prev_x, BULLET_H, style='F')
        prev_x = bx
    # Fill remainder
    if prev_x < plot_right:
        pdf.set_fill_color(*BULLET_POOR)
        pdf.rect(prev_x, cur_y, plot_right - prev_x, BULLET_H, style='F')

    # Actual value bar (thin, dark, centered vertically)
    bar_h = BULLET_H * 0.4
    bar_y = cur_y + (BULLET_H - bar_h) / 2
    actual_x = _scale(actual, v_min, v_max, plot_left, plot_right)
    pdf.set_fill_color(*CHART_BLACK)
    pdf.rect(plot_left, bar_y, actual_x - plot_left, bar_h, style='F')

    # Target marker (thin vertical line)
    if target is not None:
        target_x = _scale(target, v_min, v_max, plot_left, plot_right)
        marker_h = BULLET_H * 0.7
        marker_y = cur_y + (BULLET_H - marker_h) / 2
        pdf.set_draw_color(*CHART_BLACK)
        pdf.set_line_width(0.5)
        pdf.line(target_x, marker_y, target_x, marker_y + marker_h)
        pdf.set_line_width(0.2)

    # Value annotation
    pdf.set_font('ETBook', '', 7)
    pdf.set_text_color(*CHART_GRAY)
    pdf.set_xy(actual_x + 1, cur_y + 1.5)
    pdf.cell(12, 4, _fmt(actual), align='L')

    total_h = cur_y + BULLET_H + 3 - y
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    return total_h


# ---------------------------------------------------------------------------
# Scatter plot (two quantitative variables)
# Cleveland-McGill rank 1: position × position
# ---------------------------------------------------------------------------

def draw_scatter(pdf, spec, x, y, width=CHART_W):
    """Scatter plot.

    spec keys:
      title:  str (optional)
      data:   list of (x_val, y_val) tuples
      xlabel: str (optional)
      ylabel: str (optional)
    """
    data = spec.get('data', [])
    if not data:
        return 0
    title = spec.get('title', '')

    plot_left = x + 14
    plot_right = x + width - 4
    plot_top = y + (7 if title else 2)
    plot_bot = y + CHART_H - 8
    plot_w = plot_right - plot_left
    plot_h = plot_bot - plot_top

    xs = [p[0] for p in data]
    ys = [p[1] for p in data]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1
    if y_max == y_min:
        y_max = y_min + 1

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, y)
        pdf.cell(width, 4, title, align='L')

    # Axes
    pdf.set_draw_color(*CHART_AXIS)
    pdf.set_line_width(0.15)
    pdf.line(plot_left, plot_bot, plot_right, plot_bot)
    pdf.line(plot_left, plot_top, plot_left, plot_bot)

    # Y ticks
    for tv in _nice_ticks(y_min, y_max):
        ty = _scale(tv, y_min, y_max, plot_bot, plot_top)
        pdf.set_draw_color(*CHART_LIGHT)
        pdf.set_line_width(0.08)
        pdf.line(plot_left, ty, plot_right, ty)
        pdf.set_font('ETBook', '', 7)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, ty - 1.5)
        pdf.cell(13, 3, _fmt(tv), align='R')

    # X ticks
    for tv in _nice_ticks(x_min, x_max):
        tx = _scale(tv, x_min, x_max, plot_left, plot_right)
        pdf.set_font('ETBook', '', 7)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(tx - 6, plot_bot + 1)
        pdf.cell(12, 3, _fmt(tv), align='C')

    # Points
    dot_r = 0.8
    pdf.set_fill_color(*PALETTE[0])
    for xv, yv in data:
        px = _scale(xv, x_min, x_max, plot_left, plot_right)
        py = _scale(yv, y_min, y_max, plot_bot, plot_top)
        pdf.ellipse(px - dot_r, py - dot_r, dot_r * 2, dot_r * 2, style='F')

    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    return CHART_H


# ---------------------------------------------------------------------------
# Histogram (frequency distribution)
# ---------------------------------------------------------------------------

def draw_histogram(pdf, spec, x, y, width=CHART_W):
    """Histogram.

    spec keys:
      title:  str (optional)
      data:   list of float values (raw data, will be binned)
      bins:   int (optional, default 10)
    """
    data = spec.get('data', [])
    if not data:
        return 0
    title = spec.get('title', '')
    n_bins = spec.get('bins', 10)

    d_min, d_max = min(data), max(data)
    if d_max == d_min:
        d_max = d_min + 1

    bin_width = (d_max - d_min) / n_bins
    counts = [0] * n_bins
    for v in data:
        idx = min(int((v - d_min) / bin_width), n_bins - 1)
        counts[idx] += 1
    max_count = max(counts) if counts else 1

    plot_left = x + 12
    plot_right = x + width - 4
    plot_w = plot_right - plot_left
    plot_top = y + (7 if title else 2)
    plot_bot = y + CHART_H - 8

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, y)
        pdf.cell(width, 4, title, align='L')

    # Bars
    bar_w = plot_w / n_bins
    pdf.set_fill_color(*PALETTE[0])
    for i, count in enumerate(counts):
        if count == 0:
            continue
        bx = plot_left + i * bar_w
        bh = _scale(count, 0, max_count, 0, plot_bot - plot_top)
        by = plot_bot - bh
        pdf.rect(bx + 0.2, by, bar_w - 0.4, bh, style='F')

    # Axes
    pdf.set_draw_color(*CHART_AXIS)
    pdf.set_line_width(0.15)
    pdf.line(plot_left, plot_bot, plot_right, plot_bot)
    pdf.line(plot_left, plot_top, plot_left, plot_bot)

    # Y ticks
    for tv in _nice_ticks(0, max_count, max_ticks=4):
        ty = plot_bot - _scale(tv, 0, max_count, 0, plot_bot - plot_top)
        pdf.set_font('ETBook', '', 7)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, ty - 1.5)
        pdf.cell(11, 3, _fmt(tv), align='R')

    # X ticks
    for i in range(0, n_bins + 1, max(1, n_bins // 5)):
        v = d_min + i * bin_width
        tx = plot_left + i * bar_w
        pdf.set_font('ETBook', '', 6.5)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(tx - 5, plot_bot + 1)
        pdf.cell(10, 3, _fmt(v), align='C')

    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    return CHART_H


# ---------------------------------------------------------------------------
# Sparkstrip — small-multiples of sparklines with labels
# The signature Codex chart: dense, scannable, Tufte-pure
# ---------------------------------------------------------------------------

def draw_sparkstrip(pdf, spec, x, y, width=CHART_W):
    """Vertically stacked labeled sparklines.

    spec keys:
      title:    str (optional)
      series:   list of (label, [values]) tuples
    """
    from .sparklines import draw_sparkline, DEFAULT_W

    series = spec.get('series', [])
    if not series:
        return 0
    title = spec.get('title', '')

    label_w = 24.0
    spark_x = x + label_w + 2
    spark_w = min(DEFAULT_W * 1.5, width - label_w - 14)

    cur_y = y

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, cur_y)
        pdf.cell(width, 4, title, align='L')
        cur_y += 5

    for label, values in series:
        if len(values) < 2:
            continue

        # Label
        pdf.set_font('ETBook', '', 8)
        pdf.set_text_color(*CHART_BLACK)
        pdf.set_xy(x, cur_y + 0.2)
        pdf.cell(label_w, SPARKSTRIP_H, label, align='R')

        # Sparkline
        spark_spec = {
            'data': values,
            'options': {'end', 'min', 'max'},
            'band': None,
        }
        draw_sparkline(pdf, spark_spec, spark_x, cur_y,
                       width=spark_w, height=SPARKSTRIP_H)

        # Current value (rightmost) as a number
        pdf.set_font('ETBook', '', 7)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(spark_x + spark_w + 1, cur_y + 0.2)
        pdf.cell(10, SPARKSTRIP_H, _fmt(values[-1]), align='L')

        cur_y += SPARKSTRIP_H + SPARKSTRIP_GAP

    total_h = cur_y - y + 1
    pdf.set_text_color(0, 0, 0)
    return total_h


# ---------------------------------------------------------------------------
# Column chart (vertical bars — for time series with few categories)
# ---------------------------------------------------------------------------

def draw_column_chart(pdf, spec, x, y, width=CHART_W):
    """Vertical bar chart.

    spec keys:
      title:  str (optional)
      data:   list of (label, value) tuples
    """
    data = spec.get('data', [])
    if not data:
        return 0
    title = spec.get('title', '')

    n = len(data)
    plot_left = x + 12
    plot_right = x + width - 4
    plot_w = plot_right - plot_left
    plot_top = y + (7 if title else 2)
    plot_bot = y + CHART_H - 10

    values = [v for _, v in data]
    v_min = min(0, min(values))
    v_max = max(values)
    if v_max == v_min:
        v_max = v_min + 1

    # Title
    if title:
        pdf.set_font('ETBook', 'I', 9)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, y)
        pdf.cell(width, 4, title, align='L')

    # Y axis
    pdf.set_draw_color(*CHART_AXIS)
    pdf.set_line_width(0.15)
    pdf.line(plot_left, plot_top, plot_left, plot_bot)
    pdf.line(plot_left, plot_bot, plot_right, plot_bot)

    # Y ticks + reference lines
    for tv in _nice_ticks(v_min, v_max):
        ty = _scale(tv, v_min, v_max, plot_bot, plot_top)
        pdf.set_draw_color(*CHART_LIGHT)
        pdf.set_line_width(0.08)
        pdf.line(plot_left, ty, plot_right, ty)
        pdf.set_font('ETBook', '', 7)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(x, ty - 1.5)
        pdf.cell(11, 3, _fmt(tv), align='R')

    # Bars
    col_w = plot_w / n
    gap = col_w * 0.2
    bar_w = col_w - gap
    zero_y = _scale(0, v_min, v_max, plot_bot, plot_top)
    pdf.set_fill_color(*PALETTE[0])

    for i, (label, value) in enumerate(data):
        cx = plot_left + i * col_w + gap / 2
        top_y = _scale(value, v_min, v_max, plot_bot, plot_top)
        if value >= 0:
            pdf.rect(cx, top_y, bar_w, zero_y - top_y, style='F')
        else:
            pdf.rect(cx, zero_y, bar_w, top_y - zero_y, style='F')

        # X label
        pdf.set_font('ETBook', '', 6.5)
        pdf.set_text_color(*CHART_GRAY)
        pdf.set_xy(cx - 1, plot_bot + 1)
        pdf.cell(bar_w + 2, 3, str(label), align='C')

    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    return CHART_H


# ---------------------------------------------------------------------------
# Dispatch: chart type → draw function
# ---------------------------------------------------------------------------

CHART_TYPES = {
    'bar': draw_bar_chart,
    'line': draw_line_chart,
    'bullet': draw_bullet_graph,
    'scatter': draw_scatter,
    'histogram': draw_histogram,
    'sparkstrip': draw_sparkstrip,
    'column': draw_column_chart,
}


def draw_chart(pdf, chart_type, spec, x, y, width=CHART_W):
    """Dispatch to the appropriate chart renderer.

    Returns the height consumed (mm).
    """
    fn = CHART_TYPES.get(chart_type)
    if fn is None:
        return 0
    return fn(pdf, spec, x, y, width=width)

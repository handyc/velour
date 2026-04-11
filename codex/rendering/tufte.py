"""Tufte-style PDF renderer for Codex manuals.

Page geometry (A4, 210 x 297 mm):

    +------------------------------------------+
    |   top margin = 22mm                      |
    +-----+----------------------+-------------+
    |     |                      |             |
    | L=  |   body column        |  sidenote   |
    | 22  |     130 mm wide      |  margin     |
    |     |                      |  ~50 mm     |
    |     |                      |             |
    +-----+----------------------+-------------+
    |   bottom margin = 22mm                   |
    +------------------------------------------+

Body text is ET Book (Edward Tufte's MIT-licensed serif), bundled
under static/fonts/et-book/. Sizes: body 11pt, h1 22pt, h2 15pt,
h3 12pt italic. Leading is 1.27x by default; per-manual
double_spaced flag bumps it to 2.0x.

Sidenotes come from two sources:
  1. Inline anchors: ^[note text] in section bodies. The renderer
     places a small raised number in the body and hangs the note
     in the right margin at the anchor's vertical position.
  2. Section-level: lines in Section.sidenotes. Stacked at the
     start of the section, also in the right margin.

Page numbers go in the lower-right corner of the body column,
italic and gray, with the title page suppressed.
"""

from io import BytesIO
from pathlib import Path

from django.conf import settings
from fpdf import FPDF

from .markdown import parse
from .sparklines import DEFAULT_H as SPARK_H
from .sparklines import DEFAULT_W as SPARK_W
from .sparklines import draw_sparkline


# --- page geometry constants (mm) -----------------------------------------

A4_W, A4_H = 210, 297
LEFT_MARGIN = 22
TOP_MARGIN = 22
BOTTOM_MARGIN = 22
BODY_W = 130
SIDENOTE_GAP = 8
SIDENOTE_W = A4_W - LEFT_MARGIN - BODY_W - SIDENOTE_GAP - 4
RIGHT_MARGIN = A4_W - LEFT_MARGIN - BODY_W

BODY_FONT_SIZE = 11
H1_SIZE = 22
H2_SIZE = 15
H3_SIZE = 12
SIDENOTE_FONT_SIZE = 8
SIDENOTE_LEADING = 3.6

GRAY = (130, 130, 130)
DARK_GRAY = (80, 80, 80)
BLACK = (0, 0, 0)

# Logical font name we register with fpdf2.
FONT = 'ETBook'

FONT_DIR = Path(settings.BASE_DIR) / 'static' / 'fonts' / 'et-book'


class TufteManualPDF(FPDF):
    def __init__(self, manual):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.manual = manual
        self.set_margins(LEFT_MARGIN, TOP_MARGIN, RIGHT_MARGIN)
        self.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN)
        self.set_title(manual.title)
        self.set_author(manual.author)

        # Register ET Book faces. Roman, bold, italic. ET Book has no
        # bold-italic face, so we alias bold-italic to italic — fpdf2
        # will fall back gracefully when set_font('ETBook', 'BI', ...)
        # is requested.
        self.add_font(FONT, '',  str(FONT_DIR / 'et-book-roman.ttf'))
        self.add_font(FONT, 'B', str(FONT_DIR / 'et-book-bold.ttf'))
        self.add_font(FONT, 'I', str(FONT_DIR / 'et-book-italic.ttf'))
        self.add_font(FONT, 'BI', str(FONT_DIR / 'et-book-italic.ttf'))

        if manual.double_spaced:
            self.body_leading = BODY_FONT_SIZE * 0.36 * 2.0
        else:
            self.body_leading = BODY_FONT_SIZE * 0.36 * 1.27

        self._is_title_page = False

        # Per-section sidenote queue: list of (anchor_y, text). Cleared
        # at the start of each section. Inline anchors push (y, text);
        # render_pending_sidenotes draws them all in the margin.
        self._inline_notes = []
        # Per-section counter so the body shows 1, 2, 3...
        self._note_counter = 0
        # The first y at which a margin note has been written. Used so
        # the next note can be placed below it instead of overlapping.
        self._next_sidenote_y = None

    # --- footer override --------------------------------------------------

    def footer(self):
        if self._is_title_page:
            return
        self.set_y(-15)
        self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE)
        self.set_text_color(*GRAY)
        self.set_x(LEFT_MARGIN)
        self.cell(BODY_W, 6, str(self.page_no() - 1), align='R')
        self.set_text_color(*BLACK)

    # --- title page -------------------------------------------------------

    def render_title_page(self):
        self._is_title_page = True
        self.add_page()
        self.set_y(80)

        self.set_font(FONT, '', 30)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, 14, self.manual.title, align='L')

        if self.manual.subtitle:
            self.ln(2)
            self.set_font(FONT, 'I', 16)
            self.set_text_color(*GRAY)
            self.multi_cell(BODY_W, 8, self.manual.subtitle, align='L')

        self.ln(18)
        self.set_text_color(*BLACK)
        self.set_font(FONT, '', 11)
        if self.manual.author:
            self.cell(BODY_W, 6, self.manual.author, align='L',
                      new_x='LMARGIN', new_y='NEXT')
        if self.manual.version:
            self.set_font(FONT, 'I', 10)
            self.set_text_color(*GRAY)
            self.cell(BODY_W, 6, f'version {self.manual.version}', align='L',
                      new_x='LMARGIN', new_y='NEXT')

        if self.manual.abstract:
            self.ln(18)
            self.set_font(FONT, '', 11)
            self.set_text_color(*BLACK)
            self.multi_cell(BODY_W * 0.85, self.body_leading,
                            self.manual.abstract.strip())

        self._is_title_page = False

    # --- block emitters ---------------------------------------------------

    def emit_h1(self, text):
        self.ln(8)
        self.set_font(FONT, '', H1_SIZE)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, H1_SIZE * 0.45, text, align='L')
        self.ln(3)

    def emit_h2(self, text):
        self.ln(5)
        self.set_font(FONT, '', H2_SIZE)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, H2_SIZE * 0.45, text, align='L')
        self.ln(2)

    def emit_h3(self, text):
        self.ln(3)
        self.set_font(FONT, 'I', H3_SIZE)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, H3_SIZE * 0.45, text, align='L')
        self.ln(1)

    def _write_text_run(self, style, text, leading):
        self.set_font(FONT, style, BODY_FONT_SIZE)
        self.write(leading, text)

    def _write_anchor(self, leading):
        """Write a small raised number where the anchor is, and queue
        the note for margin rendering."""
        self._note_counter += 1
        n = self._note_counter
        # Capture the y position of the anchor's baseline before we
        # raise the cursor. This is where the margin note will go.
        anchor_y = self.get_y()
        # Render a small raised superscript-ish number.
        # fpdf2 doesn't have true superscript; we approximate by
        # switching to a smaller size and writing the number inline.
        prev_size = BODY_FONT_SIZE
        self.set_font(FONT, 'B', prev_size * 0.7)
        # Slight raise via set_y is fragile; just inline the number.
        self.write(leading, str(n))
        self.set_font(FONT, '', prev_size)
        return anchor_y

    def _write_sparkline(self, spec, leading):
        """Draw an inline sparkline at the current cursor position and
        advance the cursor x by the sparkline's width.

        The sparkline is positioned to sit centered around the
        x-height of the surrounding text — drawn slightly below the
        cursor y, since fpdf2's cursor y is the *top* of the line and
        the visual baseline is roughly y + leading * 0.78.
        """
        cur_x = self.get_x()
        cur_y = self.get_y()

        # If the remaining horizontal space on this line is too small
        # to fit the sparkline, push it onto the next line first by
        # writing a soft break.
        body_right = LEFT_MARGIN + BODY_W
        if cur_x + SPARK_W > body_right + 0.5:
            self.ln(leading)
            cur_x = self.get_x()
            cur_y = self.get_y()

        # Vertically center the sparkline within the line: top edge
        # sits at y + (leading - SPARK_H) / 2.
        top_y = cur_y + max(0, (leading - SPARK_H) / 2)

        # Add a hair of horizontal padding before/after so it doesn't
        # collide with neighbouring letterforms.
        cur_x += 0.6
        consumed = draw_sparkline(self, spec, cur_x, top_y)
        new_x = cur_x + consumed + 0.6

        # Restore the cursor to the same baseline y, but at the new x
        # so subsequent text continues on the same line.
        self.set_xy(new_x, cur_y)

    def emit_runs_with_notes(self, runs, leading):
        """Walk a paragraph's runs, writing text inline and queuing any
        inline sidenote anchors. Returns the list of (anchor_y, text)
        tuples encountered."""
        self.set_text_color(*BLACK)
        notes_in_para = []
        for run in runs:
            tag = run[0]
            if tag == 'text':
                _, style, text = run
                self._write_text_run(style, text, leading)
            elif tag == 'note':
                _, note_text = run
                anchor_y = self._write_anchor(leading)
                notes_in_para.append((anchor_y, self._note_counter, note_text))
            elif tag == 'spark':
                _, spec = run
                self._write_sparkline(spec, leading)
            elif tag == 'link':
                _, text, url = run
                # Render the link text inline (italic so the reader sees
                # it's special) and queue the URL itself as a sidenote so
                # the printed page is self-contained — no opaque [1]
                # markers, no half-shown URLs in the body.
                self.set_font(FONT, 'I', BODY_FONT_SIZE)
                self.write(leading, text)
                self.set_font(FONT, '', BODY_FONT_SIZE)
                anchor_y = self._write_anchor(leading)
                notes_in_para.append((anchor_y, self._note_counter, url))
        self.ln(leading)
        return notes_in_para

    def emit_paragraph(self, runs):
        notes = self.emit_runs_with_notes(runs, self.body_leading)
        for anchor_y, n, text in notes:
            self.render_inline_sidenote(anchor_y, n, text)
        self.ln(self.body_leading * 0.4)

    def emit_bullet_list(self, items):
        self.set_font(FONT, '', BODY_FONT_SIZE)
        for runs in items:
            self.set_x(LEFT_MARGIN)
            self.set_font(FONT, '', BODY_FONT_SIZE)
            self.write(self.body_leading, '\u00b7 ')
            notes = self.emit_runs_with_notes(runs, self.body_leading)
            for anchor_y, n, text in notes:
                self.render_inline_sidenote(anchor_y, n, text)
        self.ln(self.body_leading * 0.4)

    def emit_quote(self, runs):
        self.ln(1)
        prev_left = self.l_margin
        self.set_left_margin(LEFT_MARGIN + 6)
        self.set_x(LEFT_MARGIN + 6)
        self.set_text_color(*DARK_GRAY)
        for run in runs:
            tag = run[0]
            if tag == 'text':
                _, style, text = run
                actual_style = 'BI' if style == 'B' else 'I'
                self.set_font(FONT, actual_style, BODY_FONT_SIZE)
                self.write(self.body_leading, text)
            elif tag == 'note':
                _, note_text = run
                anchor_y = self._write_anchor(self.body_leading)
                self.render_inline_sidenote(
                    anchor_y, self._note_counter, note_text,
                )
            elif tag == 'spark':
                _, spec = run
                self._write_sparkline(spec, self.body_leading)
            elif tag == 'link':
                _, text, url = run
                self.set_font(FONT, 'I', BODY_FONT_SIZE)
                self.write(self.body_leading, text)
                anchor_y = self._write_anchor(self.body_leading)
                self.render_inline_sidenote(
                    anchor_y, self._note_counter, url,
                )
                self.set_text_color(*DARK_GRAY)
        self.ln(self.body_leading)
        self.set_left_margin(prev_left)
        self.set_text_color(*BLACK)
        self.ln(self.body_leading * 0.5)

    # --- callout / admonition ---------------------------------------------

    def emit_callout(self, kind, blocks):
        """A bordered note/tip/warn/danger box.

        The Tufte-flavored choice: no big colored backgrounds, no icons,
        no chunky borders. Just a thin colored bar on the left edge, the
        kind label as small italic gray at the top, and the body text
        slightly indented. Quiet, scannable, no chartjunk.
        """
        # Map kinds to bar colors (muted, not screaming).
        bar_colors = {
            'note':    (88, 166, 255),    # blue
            'info':    (88, 166, 255),
            'tip':     (46, 160, 67),     # green
            'warn':    (210, 153, 34),    # amber
            'warning': (210, 153, 34),
            'danger':  (200, 50, 50),     # red
        }
        bar = bar_colors.get(kind, (130, 130, 130))

        self.ln(1.5)
        bar_top = self.get_y()
        bar_x = LEFT_MARGIN

        # Indent the body slightly so it's visually separated from the bar.
        prev_left = self.l_margin
        self.set_left_margin(LEFT_MARGIN + 5)
        self.set_x(LEFT_MARGIN + 5)

        # Label.
        self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE)
        self.set_text_color(*GRAY)
        self.write(SIDENOTE_LEADING, kind.upper())
        self.ln(SIDENOTE_LEADING + 0.5)
        self.set_text_color(*BLACK)

        # Body — recursively render each inner block. We keep nesting
        # simple: paragraphs and lists work; nested callouts would also
        # work via recursion but probably never happen in practice.
        for inner_kind, inner_payload in blocks:
            self._dispatch_block(inner_kind, inner_payload, figure_map={})

        bar_bot = self.get_y()
        # Draw the colored bar AFTER the body so we know how tall to make it.
        self.set_draw_color(*bar)
        self.set_line_width(0.6)
        self.line(bar_x, bar_top, bar_x, bar_bot)
        self.set_line_width(0.2)
        self.set_draw_color(0, 0, 0)

        self.set_left_margin(prev_left)
        self.set_x(prev_left)
        self.ln(2)

    # --- code blocks ------------------------------------------------------

    def emit_code(self, source):
        """Monospace code block with a quiet light-gray background."""
        if not source:
            return
        self.ln(1)
        # We don't have a real monospace TTF in the bundle yet — fpdf2's
        # built-in Courier is latin-1 only, but for code that's usually
        # fine. Use it.
        prev_font = (self.font_family, self.font_style, self.font_size)
        self.set_font('Courier', '', 9)
        leading = 4.0
        lines = source.split('\n')

        # Background block: rect spanning full body width.
        block_top = self.get_y()
        block_h = leading * len(lines) + 2
        self.set_fill_color(245, 245, 245)
        self.rect(LEFT_MARGIN - 1, block_top - 0.5,
                  BODY_W + 2, block_h, style='F')

        self.set_text_color(40, 40, 40)
        self.set_xy(LEFT_MARGIN + 1, block_top + 1)
        for line in lines:
            self.set_x(LEFT_MARGIN + 1)
            # Manual width clipping — Courier is fixed-pitch, ~1.7mm/char
            # at 9pt, so 130mm fits ~76 characters comfortably.
            self.write(leading, line)
            self.ln(leading)
        self.set_text_color(*BLACK)
        self.ln(1.5)
        self.set_font(*prev_font[:2], prev_font[2])

    # --- tables -----------------------------------------------------------

    def emit_table(self, header, rows, bordered=False):
        """Render a table.

        Two styles:
          - Tufte minimal-rule (default): no vertical lines, horizontal
            rules only above/below the header and below the last row.
          - Bordered (for linguistic/spreadsheet data): every cell has
            full borders. Headers are bold and slightly tinted.

        If `header` is None the table is rendered without a header
        row (all rows are data) — useful for noheader tables.
        """
        widths_source = []
        if header:
            widths_source.append(header)
        widths_source.extend(rows)
        ncols = max((len(r) for r in widths_source), default=0)
        if ncols == 0:
            return

        col_w = BODY_W / ncols
        cell_h = self.body_leading * 1.05
        cell_pad = 1.4
        full_cell_h = cell_h + cell_pad * 2

        self.ln(1.5)
        top_y = self.get_y()

        def _draw_rule(y, weight=0.25, color=(80, 80, 80)):
            self.set_draw_color(*color)
            self.set_line_width(weight)
            self.line(LEFT_MARGIN, y, LEFT_MARGIN + BODY_W, y)
            self.set_draw_color(0, 0, 0)
            self.set_line_width(0.2)

        cur_y = top_y

        if bordered:
            # Header tinted background.
            if header:
                self.set_fill_color(240, 240, 240)
                self.rect(LEFT_MARGIN, cur_y, BODY_W, full_cell_h, style='F')
                for i in range(ncols):
                    cell_runs = header[i] if i < len(header) else []
                    cx = LEFT_MARGIN + i * col_w
                    self.set_xy(cx + cell_pad, cur_y + cell_pad)
                    self._write_cell_runs(cell_runs, col_w - cell_pad * 2,
                                          cell_h, bold=True)
                cur_y += full_cell_h
            for row in rows:
                for i in range(ncols):
                    cell_runs = row[i] if i < len(row) else []
                    cx = LEFT_MARGIN + i * col_w
                    self.set_xy(cx + cell_pad, cur_y + cell_pad)
                    self._write_cell_runs(cell_runs, col_w - cell_pad * 2,
                                          cell_h, bold=False)
                cur_y += full_cell_h
            # Draw the grid AFTER content so cell text isn't hidden.
            self.set_draw_color(120, 120, 120)
            self.set_line_width(0.18)
            n_rows_drawn = (1 if header else 0) + len(rows)
            total_h = n_rows_drawn * full_cell_h
            # Outer rectangle
            self.rect(LEFT_MARGIN, top_y, BODY_W, total_h)
            # Horizontal interior rules
            for r in range(1, n_rows_drawn):
                y = top_y + r * full_cell_h
                self.line(LEFT_MARGIN, y, LEFT_MARGIN + BODY_W, y)
            # Vertical interior rules
            for c in range(1, ncols):
                x = LEFT_MARGIN + c * col_w
                self.line(x, top_y, x, top_y + total_h)
            self.set_draw_color(0, 0, 0)
            self.set_line_width(0.2)
        else:
            # Tufte minimal-rule.
            _draw_rule(top_y, weight=0.4)
            if header:
                self.set_xy(LEFT_MARGIN, top_y + cell_pad)
                for i in range(ncols):
                    cell_runs = header[i] if i < len(header) else []
                    cx = LEFT_MARGIN + i * col_w
                    self.set_xy(cx + cell_pad, top_y + cell_pad)
                    self._write_cell_runs(cell_runs, col_w - cell_pad * 2,
                                          cell_h, bold=True)
                cur_y = top_y + full_cell_h
                _draw_rule(cur_y, weight=0.25)
            for row in rows:
                for i in range(ncols):
                    cell_runs = row[i] if i < len(row) else []
                    cx = LEFT_MARGIN + i * col_w
                    self.set_xy(cx + cell_pad, cur_y + cell_pad)
                    self._write_cell_runs(cell_runs, col_w - cell_pad * 2,
                                          cell_h, bold=False)
                cur_y += full_cell_h
            _draw_rule(cur_y, weight=0.4)

        self.set_xy(LEFT_MARGIN, cur_y + 2)
        self.ln(0)

    # --- definition list --------------------------------------------------

    def emit_def_list(self, pairs):
        """A list of bold-label / plain-value pairs.

        Used for linguistic gloss data, glossaries, key-value lists.
        Layout: bold label on the left, value flowing to the right of
        the label on the same line. If the value wraps, the wrapped
        lines are hung-indented under the value start (not the label).
        """
        if not pairs:
            return
        self.ln(1)

        # Compute label column width based on the longest label, capped.
        self.set_font(FONT, 'B', BODY_FONT_SIZE)
        max_label_w = max(self.get_string_width(label) for label, _ in pairs)
        label_w = min(max_label_w + 3, BODY_W * 0.35)
        value_x = LEFT_MARGIN + label_w + 1

        for label, value_runs in pairs:
            row_top = self.get_y()
            # Label
            self.set_xy(LEFT_MARGIN, row_top)
            self.set_font(FONT, 'B', BODY_FONT_SIZE)
            self.set_text_color(*BLACK)
            self.cell(label_w, self.body_leading, label, align='L')

            # Value — wrap to remaining width.
            self.set_xy(value_x, row_top)
            self.set_font(FONT, '', BODY_FONT_SIZE)
            # Save the right margin and set a temporary one so wraps
            # respect the value column.
            prev_l = self.l_margin
            self.set_left_margin(value_x)
            for run in value_runs or [('text', '', '')]:
                if run[0] == 'text':
                    _, style, text = run
                    self.set_font(FONT, style, BODY_FONT_SIZE)
                    self.write(self.body_leading, text)
            self.ln(self.body_leading)
            self.set_left_margin(prev_l)

        self.ln(self.body_leading * 0.4)

    def _write_cell_runs(self, runs, max_w, line_h, bold=False):
        """Render a sequence of inline runs into a single-line table cell.
        Truncates if the rendered string overflows the column."""
        # Concatenate plain text from runs (we ignore inline sidenotes /
        # sparklines / links inside table cells in Phase 3 — keep cells
        # simple).
        flat = ''
        bold_segments = []
        italic_segments = []
        for run in runs:
            if run[0] == 'text':
                _, style, text = run
                start = len(flat)
                flat += text
                end = len(flat)
                if 'B' in style:
                    bold_segments.append((start, end))
                if 'I' in style:
                    italic_segments.append((start, end))

        if not flat:
            return

        # Single-font rendering for simplicity: use bold if any of the
        # cell content is bold, italic if any is italic. Cells are
        # short enough that mixed styles within a single cell are rare.
        style = ''
        if bold or bold_segments:
            style += 'B'
        if italic_segments:
            style += 'I'
        self.set_font(FONT, style, BODY_FONT_SIZE - 1)
        self.set_text_color(*BLACK)
        # Trim to fit width (rough — Courier-style estimate isn't right
        # for proportional fonts but the truncation is a safety net).
        text = flat
        while text and self.get_string_width(text) > max_w:
            text = text[:-2] + '…' if len(text) > 2 else ''
        self.write(line_h, text)

    # --- slope graphs -----------------------------------------------------

    def emit_slope(self, left_label, right_label, series):
        """Tufte slope graph: two columns of points connected by lines.

        Series is a list of (name, left_value, right_value).
        """
        if not series:
            return
        self.ln(2)
        # Block geometry within the body column.
        block_top = self.get_y()
        block_h = 50.0  # mm
        gutter_left = 30  # mm reserved for left labels + values
        gutter_right = 35  # mm reserved for right labels + values
        plot_left = LEFT_MARGIN + gutter_left
        plot_right = LEFT_MARGIN + BODY_W - gutter_right
        plot_top = block_top + 8
        plot_bot = block_top + block_h - 6

        # Header labels for the two columns.
        self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE)
        self.set_text_color(*GRAY)
        if left_label:
            self.set_xy(plot_left - 22, plot_top - 6)
            self.cell(20, 4, left_label, align='R')
        if right_label:
            self.set_xy(plot_right + 2, plot_top - 6)
            self.cell(28, 4, right_label, align='L')
        self.set_text_color(*BLACK)

        all_values = [v for _, l, r in series for v in (l, r)]
        v_min = min(all_values)
        v_max = max(all_values)

        def _y(v):
            if v_max == v_min:
                return (plot_top + plot_bot) / 2
            return plot_bot - (v - v_min) / (v_max - v_min) * (plot_bot - plot_top)

        # Draw all the lines first (so labels overlay).
        self.set_draw_color(80, 80, 80)
        self.set_line_width(0.25)
        for name, left_v, right_v in series:
            self.line(plot_left, _y(left_v), plot_right, _y(right_v))
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.2)

        # Endpoint labels: name + value on each side.
        self.set_font(FONT, '', BODY_FONT_SIZE - 2)
        self.set_text_color(*BLACK)

        # To avoid overlapping labels, sort by y and bump down if too close.
        def _layout(side):
            placed = []
            for name, left_v, right_v in series:
                v = left_v if side == 'left' else right_v
                placed.append([name, v, _y(v)])
            placed.sort(key=lambda p: p[2])
            min_gap = 3.2  # mm
            for i in range(1, len(placed)):
                if placed[i][2] - placed[i - 1][2] < min_gap:
                    placed[i][2] = placed[i - 1][2] + min_gap
            return placed

        for name, v, y in _layout('left'):
            txt = f'{name}  {self._fmt_num(v)}'
            self.set_xy(LEFT_MARGIN, y - 1.4)
            self.cell(gutter_left - 1.5, 3, txt, align='R')
        for name, v, y in _layout('right'):
            txt = f'{self._fmt_num(v)}  {name}'
            self.set_xy(plot_right + 1.5, y - 1.4)
            self.cell(gutter_right - 1.5, 3, txt, align='L')

        self.set_xy(LEFT_MARGIN, block_top + block_h + 1)
        self.ln(0)

    @staticmethod
    def _fmt_num(v):
        if v == int(v):
            return str(int(v))
        return f'{v:g}'

    # --- small multiples (figs grid) --------------------------------------

    def emit_figs(self, cols, slugs, figure_map):
        """Arrange N figures in a grid of `cols` columns."""
        figures = [figure_map.get(s) for s in slugs]
        figures = [f for f in figures if f and f.image]
        if not figures:
            return

        cell_w = BODY_W / cols
        cell_pad = 2.0
        img_max_w = cell_w - cell_pad * 2

        self.ln(1.5)
        row_top = self.get_y()
        row_max_h = 0
        col_idx = 0

        for f in figures:
            try:
                path = Path(f.image.path)
                if not path.is_file():
                    continue
            except Exception:
                continue

            cx = LEFT_MARGIN + col_idx * cell_w + cell_pad
            self.set_xy(cx, row_top)
            try:
                self.image(str(path), x=cx, y=row_top, w=img_max_w)
            except Exception:
                continue
            after_y = self.get_y()
            img_h = after_y - row_top
            if f.caption:
                self.set_xy(cx, after_y + 0.5)
                self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE - 0.5)
                self.set_text_color(*GRAY)
                self.multi_cell(img_max_w, SIDENOTE_LEADING - 0.5,
                                f.caption)
                self.set_text_color(*BLACK)
                cap_h = self.get_y() - (after_y + 0.5)
                img_h += 0.5 + cap_h
            row_max_h = max(row_max_h, img_h)
            col_idx += 1
            if col_idx >= cols:
                col_idx = 0
                row_top = row_top + row_max_h + 2.5
                row_max_h = 0
                self.set_xy(LEFT_MARGIN, row_top)

        # Move cursor below the last row.
        self.set_xy(LEFT_MARGIN, row_top + row_max_h + 2)
        self.ln(0)

    # --- figures ----------------------------------------------------------

    def emit_figure(self, figure):
        """Embed an image inline in the body column.

        Caption position depends on the figure's caption_position field:
          - 'margin' (default): hangs in the right margin alongside the
            figure's vertical extent. Tufte's preferred form.
          - 'below': appears underneath the image, italic and centered
            below the figure block. Academic-paper style.
        """
        if not figure.image:
            return

        path = Path(figure.image.path)
        if not path.is_file():
            return

        self.ln(2)
        anchor_y = self.get_y()

        max_w = BODY_W
        try:
            self.image(str(path), x=LEFT_MARGIN, w=max_w)
        except Exception:
            return

        end_y = self.get_y()
        position = getattr(figure, 'caption_position', 'margin')

        if figure.caption and position == 'below':
            self.ln(0.5)
            self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE + 0.5)
            self.set_text_color(*DARK_GRAY)
            self.multi_cell(BODY_W, SIDENOTE_LEADING + 0.5,
                            figure.caption, align='C')
            self.set_text_color(*BLACK)
        elif figure.caption:
            saved_x = self.get_x()
            saved_y = self.get_y()
            sx = LEFT_MARGIN + BODY_W + SIDENOTE_GAP
            self.set_xy(sx, anchor_y)
            self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE)
            self.set_text_color(*GRAY)
            self.multi_cell(SIDENOTE_W, SIDENOTE_LEADING, figure.caption)
            self.set_text_color(*BLACK)
            self.set_xy(saved_x, max(end_y, saved_y))

        self.ln(2)

    # --- sidenote rendering -----------------------------------------------

    def render_section_sidenotes(self, notes, anchor_y):
        """Stack the section-level (line-by-line) sidenotes in the
        margin starting at `anchor_y`. Updates _next_sidenote_y so any
        inline notes that follow are placed below them."""
        if not notes:
            return
        saved_x = self.get_x()
        saved_y = self.get_y()

        sx = LEFT_MARGIN + BODY_W + SIDENOTE_GAP
        cur_y = anchor_y
        self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE)
        self.set_text_color(*GRAY)
        for i, note in enumerate(notes, start=1):
            self.set_xy(sx, cur_y)
            self.multi_cell(SIDENOTE_W, SIDENOTE_LEADING, f'{i}. {note}')
            cur_y = self.get_y() + 0.8
        self._next_sidenote_y = cur_y
        self.set_text_color(*BLACK)
        self.set_xy(saved_x, saved_y)

    def render_inline_sidenote(self, anchor_y, number, text):
        """Place an inline sidenote in the margin. Tries to anchor at
        `anchor_y` but slides down if a previous note already
        occupies that vertical space."""
        saved_x = self.get_x()
        saved_y = self.get_y()

        target_y = anchor_y
        if self._next_sidenote_y is not None and target_y < self._next_sidenote_y:
            target_y = self._next_sidenote_y

        sx = LEFT_MARGIN + BODY_W + SIDENOTE_GAP
        self.set_xy(sx, target_y)
        self.set_font(FONT, 'I', SIDENOTE_FONT_SIZE)
        self.set_text_color(*GRAY)
        self.multi_cell(SIDENOTE_W, SIDENOTE_LEADING, f'{number}. {text}')
        self._next_sidenote_y = self.get_y() + 0.8

        self.set_text_color(*BLACK)
        self.set_xy(saved_x, saved_y)

    # --- section walker ---------------------------------------------------

    def _dispatch_block(self, kind, payload, figure_map):
        if kind == 'h1':
            self.emit_h2(payload)
        elif kind == 'h2':
            self.emit_h2(payload)
        elif kind == 'h3':
            self.emit_h3(payload)
        elif kind == 'p':
            self.emit_paragraph(payload)
        elif kind == 'ul':
            self.emit_bullet_list(payload)
        elif kind == 'quote':
            self.emit_quote(payload)
        elif kind == 'fig':
            fig = figure_map.get(payload)
            if fig:
                self.emit_figure(fig)
        elif kind == 'figs':
            self.emit_figs(payload['cols'], payload['slugs'], figure_map)
        elif kind == 'callout':
            self.emit_callout(payload['kind'], payload['blocks'])
        elif kind == 'code':
            self.emit_code(payload)
        elif kind == 'table':
            self.emit_table(
                payload['header'], payload['rows'],
                bordered=payload.get('bordered', False),
            )
        elif kind == 'def':
            self.emit_def_list(payload['pairs'])
        elif kind == 'slope':
            self.emit_slope(
                payload['left_label'], payload['right_label'],
                payload['series'],
            )
        elif kind == 'blank':
            self.ln(self.body_leading * 0.3)

    def render_section(self, section):
        # Reset per-section sidenote state.
        self._note_counter = 0
        self._next_sidenote_y = None

        # Build a slug-keyed map of figures so !fig:slug references can
        # find them.
        try:
            figure_map = {f.slug: f for f in section.figures.all()}
        except Exception:
            figure_map = {}

        self.emit_h1(section.title)
        anchor_y = self.get_y()
        self.render_section_sidenotes(section.sidenote_list, anchor_y)

        blocks = parse(section.body)
        for kind, payload in blocks:
            self._dispatch_block(kind, payload, figure_map)


def render_manual_to_pdf(manual):
    """Build the PDF for a Manual and return its bytes."""
    pdf = TufteManualPDF(manual)
    pdf.render_title_page()
    pdf.add_page()
    sections = manual.sections.all().order_by('sort_order', 'pk')
    for section in sections:
        pdf.render_section(section)
    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()

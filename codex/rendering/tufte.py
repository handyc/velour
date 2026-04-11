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
        self.ln(self.body_leading)
        self.set_left_margin(prev_left)
        self.set_text_color(*BLACK)
        self.ln(self.body_leading * 0.5)

    # --- figures ----------------------------------------------------------

    def emit_figure(self, figure):
        """Embed an image inline in the body column. Caption hangs in
        the right margin alongside the figure's vertical extent."""
        if not figure.image:
            return

        path = Path(figure.image.path)
        if not path.is_file():
            return

        self.ln(2)
        anchor_y = self.get_y()

        # Cap image width to body column.
        max_w = BODY_W
        try:
            self.image(str(path), x=LEFT_MARGIN, w=max_w)
        except Exception:
            # Bad image — skip silently rather than crashing the whole render.
            return

        end_y = self.get_y()

        # Caption in the margin, top-aligned with the figure.
        if figure.caption:
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
            elif kind == 'blank':
                self.ln(self.body_leading * 0.3)


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

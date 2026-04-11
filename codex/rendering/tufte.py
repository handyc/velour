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

Body text is Times 11pt with leading derived from the manual's
double_spaced flag (1.27x by default, 2.0x if double-spaced).
Sidenotes are Times 8pt italic gray, hung at the start of each
section's body in the right margin.

Page numbers go in the lower-right corner of the body column,
italic and gray, with the title page suppressed.
"""

from io import BytesIO

from fpdf import FPDF

from .markdown import parse


# --- page geometry constants (mm) -----------------------------------------

A4_W, A4_H = 210, 297
LEFT_MARGIN = 22
TOP_MARGIN = 22
BOTTOM_MARGIN = 22
BODY_W = 130
SIDENOTE_GAP = 8           # space between body column and sidenote area
SIDENOTE_W = A4_W - LEFT_MARGIN - BODY_W - SIDENOTE_GAP - 4  # right edge pad
RIGHT_MARGIN = A4_W - LEFT_MARGIN - BODY_W   # what fpdf2 sees as the right margin

BODY_FONT_SIZE = 11
H1_SIZE = 22
H2_SIZE = 15
H3_SIZE = 12

GRAY = (130, 130, 130)
BLACK = (0, 0, 0)


# fpdf2's built-in Times is encoded latin-1 only. Substitute the common
# Unicode glyphs that show up in everyday English prose so we don't have
# to ship a font in Phase 1. Phase 2 will bundle ET Book (the Tufte font,
# MIT-licensed) for proper Unicode coverage and nicer typography.
_LATIN1_SUBS = {
    '\u2014': '--',     # em dash
    '\u2013': '-',      # en dash
    '\u2018': "'",      # left single curly quote
    '\u2019': "'",      # right single curly quote / apostrophe
    '\u201c': '"',      # left double curly quote
    '\u201d': '"',      # right double curly quote
    '\u2026': '...',    # ellipsis
    '\u2022': '\xb7',   # bullet → middle dot (latin-1 0xB7)
    '\u00a0': ' ',      # non-breaking space
    '\u202f': ' ',      # narrow no-break space
    '\u2009': ' ',      # thin space
}


def _to_latin1(s):
    if not s:
        return s
    for k, v in _LATIN1_SUBS.items():
        if k in s:
            s = s.replace(k, v)
    return s


class TufteManualPDF(FPDF):
    def __init__(self, manual):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.manual = manual
        self.set_margins(LEFT_MARGIN, TOP_MARGIN, RIGHT_MARGIN)
        self.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN)
        self.set_title(manual.title)
        self.set_author(manual.author)
        if manual.double_spaced:
            self.body_leading = BODY_FONT_SIZE * 0.36 * 2.0  # ~7.92mm
        else:
            self.body_leading = BODY_FONT_SIZE * 0.36 * 1.27  # ~5.03mm
        self._is_title_page = False

    def normalize_text(self, text):
        return super().normalize_text(_to_latin1(text))

    # --- footer override (page numbers) -----------------------------------

    def footer(self):
        if self._is_title_page:
            return
        self.set_y(-15)
        self.set_font('Times', 'I', 8)
        self.set_text_color(*GRAY)
        # Right-align inside the body column.
        self.set_x(LEFT_MARGIN)
        self.cell(BODY_W, 6, str(self.page_no() - 1), align='R')
        self.set_text_color(*BLACK)

    # --- title page -------------------------------------------------------

    def render_title_page(self):
        self._is_title_page = True
        self.add_page()
        self.set_y(80)

        self.set_font('Times', '', 30)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, 14, self.manual.title, align='L')

        if self.manual.subtitle:
            self.ln(2)
            self.set_font('Times', 'I', 16)
            self.set_text_color(*GRAY)
            self.multi_cell(BODY_W, 8, self.manual.subtitle, align='L')

        self.ln(18)
        self.set_text_color(*BLACK)
        self.set_font('Times', '', 11)
        if self.manual.author:
            self.cell(BODY_W, 6, self.manual.author, align='L', new_x='LMARGIN', new_y='NEXT')
        if self.manual.version:
            self.set_font('Times', 'I', 10)
            self.set_text_color(*GRAY)
            self.cell(BODY_W, 6, f'version {self.manual.version}', align='L', new_x='LMARGIN', new_y='NEXT')

        if self.manual.abstract:
            self.ln(18)
            self.set_font('Times', '', 11)
            self.set_text_color(*BLACK)
            self.multi_cell(BODY_W * 0.85, self.body_leading, self.manual.abstract.strip())

        self._is_title_page = False

    # --- block emitters ---------------------------------------------------

    def emit_h1(self, text):
        self.ln(8)
        self.set_font('Times', '', H1_SIZE)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, H1_SIZE * 0.45, text, align='L')
        self.ln(3)

    def emit_h2(self, text):
        self.ln(5)
        self.set_font('Times', '', H2_SIZE)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, H2_SIZE * 0.45, text, align='L')
        self.ln(2)

    def emit_h3(self, text):
        self.ln(3)
        self.set_font('Times', 'I', H3_SIZE)
        self.set_text_color(*BLACK)
        self.multi_cell(BODY_W, H3_SIZE * 0.45, text, align='L')
        self.ln(1)

    def emit_runs(self, runs, leading):
        """Write a sequence of (style, text) runs as a single flowing
        paragraph. Uses fpdf2's write() so each run inherits the current
        font but the text wraps continuously across font changes."""
        self.set_text_color(*BLACK)
        for style, text in runs:
            self.set_font('Times', style, BODY_FONT_SIZE)
            self.write(leading, text)
        self.ln(leading)

    def emit_paragraph(self, runs):
        self.emit_runs(runs, self.body_leading)
        self.ln(self.body_leading * 0.4)

    def emit_bullet_list(self, items):
        self.set_font('Times', '', BODY_FONT_SIZE)
        for runs in items:
            # Bullet glyph in body, then runs
            self.set_x(LEFT_MARGIN)
            self.set_font('Times', '', BODY_FONT_SIZE)
            self.write(self.body_leading, '\xb7 ')
            for style, text in runs:
                self.set_font('Times', style, BODY_FONT_SIZE)
                self.write(self.body_leading, text)
            self.ln(self.body_leading)
        self.ln(self.body_leading * 0.4)

    def emit_quote(self, runs):
        self.ln(1)
        prev_left = self.l_margin
        self.set_left_margin(LEFT_MARGIN + 6)
        self.set_x(LEFT_MARGIN + 6)
        for style, text in runs:
            # Quotes always italic
            actual_style = 'BI' if style == 'B' else 'I'
            self.set_font('Times', actual_style, BODY_FONT_SIZE)
            self.set_text_color(80, 80, 80)
            self.write(self.body_leading, text)
        self.ln(self.body_leading)
        self.set_left_margin(prev_left)
        self.set_text_color(*BLACK)
        self.ln(self.body_leading * 0.5)

    # --- sidenotes --------------------------------------------------------

    def render_sidenotes(self, notes, anchor_y):
        """Render a stack of sidenote strings in the right margin
        starting at vertical position `anchor_y`. Each note is
        prefixed with its index in superscript-ish brackets."""
        if not notes:
            return
        saved_x = self.get_x()
        saved_y = self.get_y()

        sx = LEFT_MARGIN + BODY_W + SIDENOTE_GAP
        self.set_xy(sx, anchor_y)
        self.set_font('Times', 'I', 8)
        self.set_text_color(*GRAY)
        for i, note in enumerate(notes, start=1):
            self.set_x(sx)
            self.multi_cell(SIDENOTE_W, 3.5, f'{i}. {note}', align='L')
            self.ln(0.8)
        self.set_text_color(*BLACK)
        self.set_xy(saved_x, saved_y)

    # --- section walker ---------------------------------------------------

    def render_section(self, section):
        # Section heading first.
        self.emit_h1(section.title)
        # Sidenotes anchored to where the body begins.
        anchor_y = self.get_y()
        self.render_sidenotes(section.sidenote_list, anchor_y)

        blocks = parse(section.body)
        for kind, payload in blocks:
            if kind == 'h1':
                # Body-level "# Heading" inside a section is treated as h2.
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

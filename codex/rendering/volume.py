"""Stitch multiple Manual PDFs into one bound Volume.

The output has three parts:
  1. A cover page with the Volume's title/subtitle/author.
  2. A table of contents listing each Manual and its first page in the
     combined PDF.
  3. Each Manual rendered in order via the Tufte renderer.

pypdf stitches the byte streams together. Page numbers reset per
Manual — the Tufte renderer numbers pages within a Manual, and the
Volume TOC provides the "absolute" page where each Manual starts.
"""

from io import BytesIO

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

from .tufte import FONT, FONT_DIR, GRAY, BLACK, A4_W, A4_H, LEFT_MARGIN, BODY_W
from .tufte import render_manual_to_pdf


def _register_etbook(pdf):
    pdf.add_font(FONT, '',  str(FONT_DIR / 'et-book-roman.ttf'))
    pdf.add_font(FONT, 'B', str(FONT_DIR / 'et-book-bold.ttf'))
    pdf.add_font(FONT, 'I', str(FONT_DIR / 'et-book-italic.ttf'))
    pdf.add_font(FONT, 'BI', str(FONT_DIR / 'et-book-italic.ttf'))


def _front_matter_pdf(volume, manuals_with_startpages):
    """Cover + TOC, as its own PDF byte stream."""
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(LEFT_MARGIN, 22, A4_W - LEFT_MARGIN - BODY_W)
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_title(volume.title)
    pdf.set_author(volume.author)
    _register_etbook(pdf)

    # Cover.
    pdf.add_page()
    pdf.set_y(80)
    pdf.set_font(FONT, '', 30)
    pdf.set_text_color(*BLACK)
    pdf.multi_cell(BODY_W, 14, volume.title, align='L',
                   new_x='LMARGIN', new_y='NEXT')
    if volume.subtitle:
        pdf.ln(2)
        pdf.set_font(FONT, 'I', 16)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(BODY_W, 8, volume.subtitle, align='L',
                       new_x='LMARGIN', new_y='NEXT')
    pdf.ln(18)
    pdf.set_text_color(*BLACK)
    pdf.set_font(FONT, '', 11)
    if volume.author:
        pdf.cell(BODY_W, 6, volume.author, new_x='LMARGIN', new_y='NEXT')
    if volume.version:
        pdf.set_font(FONT, 'I', 10)
        pdf.set_text_color(*GRAY)
        pdf.cell(BODY_W, 6, f'version {volume.version}',
                 new_x='LMARGIN', new_y='NEXT')
    if volume.abstract:
        pdf.ln(18)
        pdf.set_font(FONT, '', 11)
        pdf.set_text_color(*BLACK)
        pdf.multi_cell(BODY_W * 0.85, 5.5, volume.abstract.strip(),
                       new_x='LMARGIN', new_y='NEXT')

    # Contents.
    pdf.add_page()
    pdf.set_font(FONT, '', 22)
    pdf.set_text_color(*BLACK)
    pdf.cell(BODY_W, 10, 'Contents', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)
    pdf.set_font(FONT, '', 11)
    for m, start_page in manuals_with_startpages:
        # Title on left, page number on right, dot-leader ellipsis between.
        title = m.title
        pdf.cell(BODY_W - 15, 8, title, align='L')
        pdf.cell(15, 8, str(start_page), align='R',
                 new_x='LMARGIN', new_y='NEXT')

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue(), pdf.page_no()


def render_volume_to_pdf(volume):
    """Build and return the combined Volume PDF bytes."""
    entries = list(volume.entries.select_related('manual').order_by('sort_order', 'pk'))
    manuals = [e.manual for e in entries]

    # Two-pass: first render each Manual to know its page count, then
    # build front matter with correct page numbers.
    manual_pdfs = []
    page_counts = []
    for m in manuals:
        data = render_manual_to_pdf(m)
        reader = PdfReader(BytesIO(data))
        manual_pdfs.append(data)
        page_counts.append(len(reader.pages))

    # Compute per-manual start page. Front matter takes some pages too
    # — we pass a placeholder initially, read its actual length, then
    # rebuild with correct offsets if needed. In practice front matter
    # is 2 pages (cover + TOC), so we build twice at most.
    front_bytes, front_pages = _front_matter_pdf(volume, [])
    start_pages = []
    cursor = front_pages + 1
    for m, count in zip(manuals, page_counts):
        start_pages.append((m, cursor))
        cursor += count
    front_bytes, front_pages2 = _front_matter_pdf(volume, start_pages)
    if front_pages2 != front_pages:
        # Recompute with new front-matter size (rare: only if TOC grew
        # past a single page).
        start_pages = []
        cursor = front_pages2 + 1
        for m, count in zip(manuals, page_counts):
            start_pages.append((m, cursor))
            cursor += count
        front_bytes, _ = _front_matter_pdf(volume, start_pages)

    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(front_bytes)))
    for data in manual_pdfs:
        writer.append(PdfReader(BytesIO(data)))
    out = BytesIO()
    writer.write(out)
    return out.getvalue()

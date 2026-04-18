"""Print-ready wrapping — bleed + crop marks around an existing PDF.

Print shops expect an oversized page with the content shifted inward
so ink can run off the trim edge, plus short lines marking where to
cut. This module takes a finished PDF (A4 trim) and emits a new PDF
with:

  * A larger media box — trim + `bleed` on every side (default 3 mm).
  * The original page content translated inward so it sits inside the
    trim rectangle.
  * Four L-shaped crop marks at the corners of the trim box.
  * /TrimBox and /BleedBox entries so print RIPs know the geometry.

Colour stays RGB — full CMYK separation wants a post-processing step
with Ghostscript (`gs -sDEVICE=pdfwrite -sProcessColorModel=DeviceCMYK`
or the print shop's RIP) and is intentionally left outside this module.
"""

from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, NameObject, RectangleObject,
)


MM_TO_PT = 72 / 25.4


def _crop_marks_stream(page_w_pt, page_h_pt, bleed_pt,
                       mark_len_pt=5 * MM_TO_PT,
                       mark_offset_pt=1 * MM_TO_PT,
                       line_width_pt=0.25):
    """Return a DecodedStreamObject that draws four corner crop marks.

    The trim box sits at (bleed, bleed) → (page_w - bleed, page_h - bleed).
    Each corner gets two short strokes pointing outward, with a small
    gap between the corner and the mark so it doesn't print over the
    trim edge itself.
    """
    x0 = bleed_pt
    y0 = bleed_pt
    x1 = page_w_pt - bleed_pt
    y1 = page_h_pt - bleed_pt
    ops = ['q', f'{line_width_pt} w', '0 0 0 RG']
    for cx, cy, xdir, ydir in [
        (x0, y0, -1, -1),
        (x1, y0,  1, -1),
        (x0, y1, -1,  1),
        (x1, y1,  1,  1),
    ]:
        hx0 = cx + xdir * mark_offset_pt
        hx1 = cx + xdir * (mark_offset_pt + mark_len_pt)
        vy0 = cy + ydir * mark_offset_pt
        vy1 = cy + ydir * (mark_offset_pt + mark_len_pt)
        ops.append(f'{hx0:.3f} {cy:.3f} m {hx1:.3f} {cy:.3f} l S')
        ops.append(f'{cx:.3f} {vy0:.3f} m {cx:.3f} {vy1:.3f} l S')
    ops.append('Q')
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(ops).encode('latin-1'))
    return stream


def wrap_print_ready(pdf_bytes, bleed_mm=3.0):
    """Return a print-ready PDF: trim-size input with bleed + crop marks."""
    bleed_pt = bleed_mm * MM_TO_PT
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        trim_w = float(page.mediabox.width)
        trim_h = float(page.mediabox.height)
        new_w = trim_w + 2 * bleed_pt
        new_h = trim_h + 2 * bleed_pt

        # Translate content inward by the bleed so it occupies the trim
        # rectangle on the larger page.
        page.add_transformation([1, 0, 0, 1, bleed_pt, bleed_pt])
        page.mediabox = RectangleObject([0, 0, new_w, new_h])
        page[NameObject('/TrimBox')] = RectangleObject(
            [bleed_pt, bleed_pt, bleed_pt + trim_w, bleed_pt + trim_h],
        )
        page[NameObject('/BleedBox')] = page.mediabox

        out_page = writer.add_page(page)
        marks = _crop_marks_stream(new_w, new_h, bleed_pt)
        marks_ref = writer._add_object(marks)
        contents = out_page.get('/Contents')
        if isinstance(contents, ArrayObject):
            contents.append(marks_ref)
            out_page[NameObject('/Contents')] = contents
        elif contents is not None:
            arr = ArrayObject([contents.indirect_reference, marks_ref])
            out_page[NameObject('/Contents')] = arr
        else:
            out_page[NameObject('/Contents')] = marks_ref

    out = BytesIO()
    writer.write(out)
    return out.getvalue()

"""
Detailed 64-world booklet: one world per page, large studded-brick view.

Differences from worlds_gallery.py:
  * one world per page instead of four
  * full-detail rendering (studs on, edge strokes on) so every brick is
    individually readable
  * half the complexity: primary object counts drawn from 0-8 (not 0-16),
    decor counts from 0-2 hills / 0-3 lamps / 0-3 rocks
"""
from __future__ import annotations

import argparse
import datetime
import io
import os
import random
import sys

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Image as RLImage, Table, TableStyle,
)

from .brick_render import new_scene, draw_group
from . import worlds as W


BIOME_NAMES = list(W.BIOMES.keys())


def _half_complexity_world(seed: int) -> W.World:
    """Random world with counts halved from the gallery generator.

    Primary kinds: 0-8 (was 0-16).  Decor: 0-2 hills, 0-3 lamps, 0-3 rocks
    (was 0-4, 0-6, 0-6).
    """
    rng = random.Random(seed)
    biome = rng.choice(BIOME_NAMES)
    nb = rng.randint(0, 8)
    nt = rng.randint(0, 8)
    nf = rng.randint(0, 8)
    np_ = rng.randint(0, 8)
    nh = rng.randint(0, 2)
    nl = rng.randint(0, 3)
    nr = rng.randint(0, 3)
    name = f"hc{seed:04d}"
    return W.build_world(name=name, biome=biome, seed=seed,
                         n_buildings=nb, n_trees=nt, n_flowers=nf,
                         n_people=np_, n_hills=nh, n_lamps=nl, n_rocks=nr)


def _detailed_image(world: W.World, width_in: float, height_in: float,
                    dpi: int = 170) -> RLImage:
    """Full-detail render: studs visible, edges drawn on every brick."""
    from PIL import Image
    fig, ax = new_scene(width_in, height_in, dpi=dpi)
    draw_group(ax, W.world_to_bricks(world))
    ax.relim(); ax.autoscale_view()
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    cw, ch = (x1 - x0) * 1.04, (y1 - y0) * 1.04
    aspect = width_in / height_in
    if cw / ch > aspect:
        ch = cw / aspect
    else:
        cw = ch * aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ax.set_xlim(cx - cw / 2, cx + cw / 2)
    ax.set_ylim(cy - ch / 2, cy + ch / 2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=False, dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf)
    w_px, h_px = img.size
    ra = w_px / h_px
    if ra > aspect:
        ow, oh = width_in, width_in / ra
    else:
        oh, ow = height_in, height_in * ra
    buf.seek(0)
    return RLImage(buf, width=ow * 72, height=oh * 72)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("T", parent=base, fontName="Times-Bold",
                                fontSize=20, leading=24, spaceAfter=3),
        "sub": ParagraphStyle("S", parent=base, fontName="Times-Italic",
                              fontSize=11, leading=14,
                              textColor=colors.HexColor("#555"),
                              spaceAfter=8),
        "body": ParagraphStyle("B", parent=base, fontName="Times-Roman",
                               fontSize=10.5, leading=13.5, spaceAfter=6),
        "cap": ParagraphStyle("C", parent=base, fontName="Courier",
                              fontSize=8.5, leading=10.5,
                              alignment=TA_CENTER,
                              textColor=colors.HexColor("#333")),
    }


def _metadata_row(world: W.World, body: ParagraphStyle) -> Table:
    cells = [[
        Paragraph(f"<b>{world.n_buildings}</b>&nbsp;buildings", body),
        Paragraph(f"<b>{world.n_trees}</b>&nbsp;trees", body),
        Paragraph(f"<b>{world.n_flowers}</b>&nbsp;flowers", body),
        Paragraph(f"<b>{world.n_people}</b>&nbsp;people", body),
        Paragraph(f"<b>{world.n_hills}</b>&nbsp;hills", body),
        Paragraph(f"<b>{world.n_lamps}</b>&nbsp;lamps", body),
        Paragraph(f"<b>{world.n_rocks}</b>&nbsp;rocks", body),
    ]]
    t = Table(cells, colWidths=[1.05 * inch] * 7)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
    ]))
    return t


def build(count: int = 64, seed_start: int = 30001,
          out_dir: str = "worlds",
          out_pdf: str | None = None,
          dpi: int = 170) -> tuple[str, list[str]]:
    ss = _styles()
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if out_pdf is None:
        out_pdf = f"Lego_Worlds_Detailed_{count}_{ts}.pdf"
    os.makedirs(out_dir, exist_ok=True)

    doc = BaseDocTemplate(
        out_pdf, pagesize=LETTER,
        leftMargin=0.55 * inch, rightMargin=0.55 * inch,
        topMargin=0.55 * inch, bottomMargin=0.55 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  LETTER[0] - 1.1 * inch, LETTER[1] - 1.1 * inch,
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)

    def chrome(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Times-Italic", 8.5)
        canvas.setFillColor(colors.HexColor("#777"))
        canvas.drawString(0.55 * inch, 0.3 * inch,
                          f"Lego Worlds — detailed booklet ({count} worlds, "
                          f"half complexity)")
        canvas.drawRightString(LETTER[0] - 0.55 * inch, 0.3 * inch,
                               f"page {_doc.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="d", frames=[frame], onPage=chrome)])

    story: list = []

    # ---- cover ----
    story.append(Paragraph("Lego Worlds — Detailed Booklet", ss["title"]))
    story.append(Paragraph(
        f"{count} random worlds, one per page, rendered with every stud and "
        f"brick edge visible so individual blocks are clearly distinct. "
        f"Seeds {seed_start}&ndash;{seed_start + count - 1}.",
        ss["sub"]))
    story.append(Paragraph(
        "<b>Complexity.</b> Counts are drawn from halved ranges compared to "
        "the 500-world gallery: 0&ndash;8 each for buildings, trees, flowers, "
        "and people; 0&ndash;2 hills, 0&ndash;3 lamps, 0&ndash;3 rocks. "
        "The same L-System rules apply — tree variants (bushy / conifer / "
        "blossom), flower variants (cross / ring / spire), and buildings "
        "with optional chimney or antenna.",
        ss["body"]))
    story.append(Paragraph(
        "<b>Reading a page.</b> The title is the world's slug; the italic "
        "line lists biome and seed; the table summarises counts; the "
        "caption beneath the render is the on-disk filename (always "
        "searchable via glob).",
        ss["body"]))
    story.append(PageBreak())

    saved: list[str] = []
    for i in range(count):
        seed = seed_start + i
        world = _half_complexity_world(seed)
        path = world.save(out_dir)
        saved.append(path)
        story.append(Paragraph(world.name, ss["title"]))
        story.append(Paragraph(
            f"biome: <b>{world.biome}</b> &middot; seed: <b>{world.seed}</b> "
            f"&middot; baseplate: "
            f"<font color='{world.baseplate_color}'>&#x25a0;</font> "
            f"<tt>{world.baseplate_color}</tt>",
            ss["sub"]))
        story.append(_metadata_row(world, ss["body"]))
        story.append(Spacer(1, 8))
        story.append(_detailed_image(world, width_in=7.2, height_in=6.4,
                                     dpi=dpi))
        story.append(Paragraph(world.filename(), ss["cap"]))
        story.append(PageBreak())
        if (i + 1) % 8 == 0:
            print(f"  built {i + 1}/{count}", file=sys.stderr)

    doc.build(story)
    return out_pdf, saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=64)
    ap.add_argument("--seed-start", type=int, default=30001)
    ap.add_argument("--dpi", type=int, default=170)
    ap.add_argument("--out-dir", default="worlds")
    args = ap.parse_args()
    pdf, files = build(count=args.count, seed_start=args.seed_start,
                       out_dir=args.out_dir, dpi=args.dpi)
    print(f"wrote {pdf}")
    print(f"saved {len(files)} worlds to {args.out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

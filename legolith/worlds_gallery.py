"""
Generate a gallery of 500 randomly-seeded Lego worlds and render them as a
4-up PDF.

Each world is saved as JSON (searchable filename; see worlds.py) and rendered
as a thumbnail. The PDF is a browsable atlas: one page per 4 worlds, each
with its filename-style caption.

Usage:
    python worlds_gallery.py [--count N] [--seed-start S]
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
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Image as RLImage, Table, TableStyle, KeepTogether,
)

from matplotlib.collections import PolyCollection
from .brick_render import new_scene, draw_group, Brick, iso, shade, EDGE, PLATE_H
from . import worlds as W


def _fast_draw_group(ax, placements):
    """Batched polygon renderer for gallery thumbnails.

    draw_group() calls ax.add_patch() once per face (and twice more per stud).
    A 32x32 baseplate plus 50+ objects explodes that to 5k-15k individual
    patches, and matplotlib's bookkeeping dominates the runtime. We instead
    build all top/left/right face polygons into three arrays and add them in
    three PolyCollection calls — typically 8-10x faster for large scenes.

    Studs are omitted entirely (imperceptible at thumbnail size).
    """
    items = sorted(placements, key=lambda bp: bp[1][0] + bp[1][1] + bp[1][2])
    tops, lefts, rights = [], [], []
    top_colors, left_colors, right_colors = [], [], []
    for brick, (x0, y0, z0) in items:
        w, d = brick.w, brick.d
        h = brick.plates * PLATE_H
        c_top = brick.color
        c_r = shade(c_top, 0.82)
        c_l = shade(c_top, 0.65)
        lefts.append([iso(x0, y0, z0), iso(x0, y0 + d, z0),
                      iso(x0, y0 + d, z0 + h), iso(x0, y0, z0 + h)])
        left_colors.append(c_l)
        rights.append([iso(x0, y0, z0), iso(x0 + w, y0, z0),
                       iso(x0 + w, y0, z0 + h), iso(x0, y0, z0 + h)])
        right_colors.append(c_r)
        tops.append([iso(x0, y0, z0 + h), iso(x0 + w, y0, z0 + h),
                     iso(x0 + w, y0 + d, z0 + h), iso(x0, y0 + d, z0 + h)])
        top_colors.append(c_top)
    for polys, fcs in [(lefts, left_colors),
                       (rights, right_colors),
                       (tops, top_colors)]:
        coll = PolyCollection(polys, facecolors=fcs, edgecolors=EDGE,
                              linewidths=0.25)
        ax.add_collection(coll)
    ax.autoscale_view()


BIOME_NAMES = list(W.BIOMES.keys())


def _random_world(seed: int) -> W.World:
    """Roll a random world with rich object counts.

    Counts per kind are drawn from independent distributions so roughly a
    third of worlds of each kind are sparse and another third are crowded.
    """
    rng = random.Random(seed)
    biome = rng.choice(BIOME_NAMES)
    # Primary kinds: 0-16 range, skewed toward mid densities
    nb = rng.randint(0, 16)
    nt = rng.randint(0, 16)
    nf = rng.randint(0, 16)
    np_ = rng.randint(0, 16)
    nh = rng.randint(0, 4)
    nl = rng.randint(0, 6)
    nr = rng.randint(0, 6)
    # A short slug so filenames sort readably: "rnd123"
    name = f"rnd{seed:03d}"
    return W.build_world(name=name, biome=biome, seed=seed,
                         n_buildings=nb, n_trees=nt, n_flowers=nf,
                         n_people=np_, n_hills=nh, n_lamps=nl, n_rocks=nr)


def _thumbnail(world: W.World, width_in: float, height_in: float,
               dpi: int = 110) -> RLImage:
    """Render a world to an aspect-preserving RLImage sized for a cell."""
    from PIL import Image
    fig, ax = new_scene(width_in, height_in, dpi=dpi)
    _fast_draw_group(ax, W.world_to_bricks(world))
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
                                fontSize=20, leading=24, spaceAfter=4),
        "sub": ParagraphStyle("S", parent=base, fontName="Times-Italic",
                              fontSize=11, leading=14,
                              textColor=colors.HexColor("#555"),
                              spaceAfter=8),
        "body": ParagraphStyle("B", parent=base, fontName="Times-Roman",
                               fontSize=10.5, leading=13.5, spaceAfter=5),
        "cap": ParagraphStyle("C", parent=base, fontName="Courier",
                              fontSize=7.2, leading=8.5,
                              alignment=TA_CENTER,
                              textColor=colors.HexColor("#333")),
        "cap2": ParagraphStyle("C2", parent=base, fontName="Times-Roman",
                               fontSize=8.5, leading=10.5,
                               alignment=TA_CENTER,
                               textColor=colors.HexColor("#666")),
    }


def build_gallery(count: int, seed_start: int = 1,
                  out_dir: str = "worlds",
                  out_pdf: str | None = None,
                  dpi: int = 110) -> tuple[str, list[str]]:
    ss = _styles()
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if out_pdf is None:
        out_pdf = f"Lego_Worlds_Gallery_{count}_{ts}.pdf"
    os.makedirs(out_dir, exist_ok=True)

    doc = BaseDocTemplate(
        out_pdf, pagesize=LETTER,
        leftMargin=0.45 * inch, rightMargin=0.45 * inch,
        topMargin=0.45 * inch, bottomMargin=0.45 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  LETTER[0] - 0.9 * inch, LETTER[1] - 0.9 * inch,
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)

    def chrome(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Times-Italic", 8.5)
        canvas.setFillColor(colors.HexColor("#777"))
        canvas.drawString(0.45 * inch, 0.25 * inch,
                          f"Lego Worlds Gallery — {count} L-System worlds")
        canvas.drawRightString(LETTER[0] - 0.45 * inch, 0.25 * inch,
                               f"page {_doc.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="g", frames=[frame], onPage=chrome)])

    story: list = []

    # ---- cover ----
    story.append(Paragraph(f"Lego Worlds Gallery", ss["title"]))
    story.append(Paragraph(
        f"{count} random 32&times;32-stud baseplates, each grown from an "
        f"L-System rule set. Seeds {seed_start}&ndash;{seed_start + count - 1}.",
        ss["sub"]))
    story.append(Paragraph(
        "<b>Object kinds.</b> Every world draws counts independently from "
        "0&ndash;16 for buildings, trees, flowers, and people; plus "
        "0&ndash;4 hills, 0&ndash;6 lamp-posts, and 0&ndash;6 rocks. Tree "
        "rules have three variants (bushy, conifer, blossom); flowers have "
        "three (cross, ring, spire); buildings pick wall/roof colors and "
        "occasionally sprout a chimney or antenna. A biome is drawn at "
        "random and determines the baseplate color.",
        ss["body"]))
    story.append(Paragraph(
        "<b>Storage.</b> Each world is saved at "
        "<font face='Courier' size='9'>worlds/world_&lt;name&gt;_b&lt;n&gt;_"
        "t&lt;n&gt;_f&lt;n&gt;_p&lt;n&gt;_d&lt;n&gt;_&lt;biome&gt;_"
        "s&lt;seed&gt;.json</font>, so glob queries — "
        "<font face='Courier' size='9'>worlds/world_*_b0_*</font> "
        "(no buildings), "
        "<font face='Courier' size='9'>worlds/world_*_forest_*</font> "
        "(forest biome), "
        "<font face='Courier' size='9'>worlds/world_*_*_*_*_*_d0_*</font> "
        "(no decor) — are trivial to run.",
        ss["body"]))
    story.append(Paragraph(
        "<b>Layout.</b> Four worlds per page, in reading order. The caption "
        "under each thumbnail is the filename.",
        ss["body"]))
    story.append(PageBreak())

    # ---- body: build & render worlds in groups of 4 ----
    # Grid cell dims: page content 7.6 x 10.1, minus ~0.4 for the page banner
    # at bottom. 2x2 grid with small gutter gives roughly 3.7 x 4.85 per cell.
    # Each cell holds an image (3.6 x 3.6 in) and a small caption below.
    cell_img_w = 3.6
    cell_img_h = 3.4
    saved: list[str] = []

    pending: list[tuple[RLImage, str, str]] = []  # (img, top_caption, filename)

    def flush_page():
        if not pending:
            return
        # Build 2x2 table; pad with empty cells if fewer than 4 pending.
        cells: list[list] = []
        row: list = []
        for img, top_cap, fname in pending:
            cell_stack = [
                img,
                Spacer(1, 2),
                Paragraph(top_cap, ss["cap2"]),
                Paragraph(fname, ss["cap"]),
            ]
            row.append(cell_stack)
            if len(row) == 2:
                cells.append(row)
                row = []
        if row:
            while len(row) < 2:
                row.append("")
            cells.append(row)
        if len(cells) < 2:
            cells.append(["", ""])
        t = Table(cells, colWidths=[3.8 * inch, 3.8 * inch],
                  rowHeights=[4.9 * inch, 4.9 * inch])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(PageBreak())
        pending.clear()

    for i in range(count):
        seed = seed_start + i
        world = _random_world(seed)
        path = world.save(out_dir)
        saved.append(path)
        img = _thumbnail(world, cell_img_w, cell_img_h, dpi=dpi)
        top_cap = (f"<b>{world.name}</b> &middot; {world.biome} &middot; "
                   f"b{world.n_buildings} t{world.n_trees} f{world.n_flowers} "
                   f"p{world.n_people} d{world.n_decor}")
        pending.append((img, top_cap, world.filename()))
        if len(pending) == 4:
            flush_page()
        if (i + 1) % 25 == 0:
            print(f"  built {i + 1}/{count}", file=sys.stderr)
    flush_page()

    doc.build(story)
    return out_pdf, saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--seed-start", type=int, default=10001)
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--out-dir", default="worlds")
    args = ap.parse_args()
    pdf, files = build_gallery(count=args.count, seed_start=args.seed_start,
                               out_dir=args.out_dir, dpi=args.dpi)
    print(f"wrote {pdf}")
    print(f"saved {len(files)} worlds to {args.out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

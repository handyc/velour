"""
Generate 10 example Lego worlds and render them as a PDF booklet.

Each page shows one world:
  - title + biome + seed
  - metadata badges (buildings/trees/flowers/people counts)
  - isometric render of the 32x32 baseplate populated with all objects

Worlds are saved as JSON in ./worlds/ using a searchable filename convention
(see worlds.py for details) so the booklet can be rebuilt without re-rolling
the RNG, and individual worlds can be looked up with simple glob patterns.
"""
from __future__ import annotations

import datetime
import io
import os

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Image as RLImage, Table, TableStyle,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from .brick_render import new_scene, draw_group
from . import worlds as W


# Exactly 10 worlds. Each entry is
#   (name, biome, seed, n_buildings, n_trees, n_flowers, n_people)
# Counts are tuned to showcase different densities, always in the 0-8 range.
EXAMPLE_WORLDS: list[tuple[str, str, int, int, int, int, int]] = [
    ("meadow",    "plains",  101, 0, 2, 8, 2),
    ("village",   "town",    202, 3, 3, 2, 4),
    ("forest",    "forest",  303, 0, 8, 2, 1),
    ("garden",    "meadow",  404, 1, 2, 8, 3),
    ("square",    "town",    505, 4, 2, 4, 8),
    ("outpost",   "desert",  606, 2, 0, 1, 2),
    ("harbor",    "harbor",  707, 1, 0, 0, 3),
    ("park",      "autumn",  808, 0, 5, 5, 2),
    ("hamlet",    "snow",    909, 2, 4, 1, 3),
    ("capital",   "town",   1010, 8, 8, 8, 8),
]


def _world_image(world: W.World, width_in: float, height_in: float) -> RLImage:
    """Render a world to an RLImage sized to fit (width_in, height_in)."""
    from PIL import Image
    fig, ax = new_scene(width_in, height_in, dpi=170)
    draw_group(ax, W.world_to_bricks(world))
    ax.relim(); ax.autoscale_view()
    # Equal padding so the baseplate is centered with a little breathing room.
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    pad = 0.04
    cw = (x1 - x0) * (1 + pad); ch = (y1 - y0) * (1 + pad)
    aspect = width_in / height_in
    if cw / ch > aspect:
        ch = cw / aspect
    else:
        cw = ch * aspect
    cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
    ax.set_xlim(cx - cw / 2, cx + cw / 2)
    ax.set_ylim(cy - ch / 2, cy + ch / 2)
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=False, dpi=170)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf)
    w_px, h_px = img.size
    ra = w_px / h_px
    if ra > aspect:
        ow = width_in; oh = width_in / ra
    else:
        oh = height_in; ow = height_in * ra
    buf.seek(0)
    return RLImage(buf, width=ow * 72, height=oh * 72)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    title = ParagraphStyle("Title", parent=base, fontName="Times-Bold",
                           fontSize=22, leading=26, spaceAfter=4)
    sub = ParagraphStyle("Sub", parent=base, fontName="Times-Italic",
                         fontSize=12, leading=15, textColor=colors.HexColor("#555"),
                         spaceAfter=10)
    body = ParagraphStyle("Body", parent=base, fontName="Times-Roman",
                          fontSize=11, leading=14, spaceAfter=6)
    caption = ParagraphStyle("Caption", parent=base, fontName="Times-Italic",
                             fontSize=9.5, leading=12, alignment=TA_CENTER,
                             textColor=colors.HexColor("#555"))
    return {"title": title, "sub": sub, "body": body, "caption": caption}


def _metadata_table(world: W.World) -> Table:
    data = [[
        Paragraph(f"<b>{world.n_buildings}</b>&nbsp;buildings", _styles()["body"]),
        Paragraph(f"<b>{world.n_trees}</b>&nbsp;trees", _styles()["body"]),
        Paragraph(f"<b>{world.n_flowers}</b>&nbsp;flowers", _styles()["body"]),
        Paragraph(f"<b>{world.n_people}</b>&nbsp;people", _styles()["body"]),
    ]]
    t = Table(data, colWidths=[1.5 * inch] * 4)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
    ]))
    return t


def build_booklet(out_dir: str = "worlds",
                  out_pdf: str | None = None) -> tuple[str, list[str]]:
    """Generate 10 worlds, save them as JSON, and render the booklet PDF.

    Returns (pdf_path, [world_json_paths]).
    """
    os.makedirs(out_dir, exist_ok=True)

    ss = _styles()
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if out_pdf is None:
        out_pdf = f"Lego_Worlds_Booklet_{ts}.pdf"

    # ---- build & save worlds ----
    saved: list[str] = []
    world_objs: list[W.World] = []
    for (name, biome, seed, nb, nt, nf, np_) in EXAMPLE_WORLDS:
        world = W.build_world(name=name, biome=biome, seed=seed,
                              n_buildings=nb, n_trees=nt,
                              n_flowers=nf, n_people=np_)
        path = world.save(out_dir)
        saved.append(path)
        world_objs.append(world)

    # ---- render PDF ----
    doc = BaseDocTemplate(
        out_pdf, pagesize=LETTER,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  LETTER[0] - 1.4 * inch, LETTER[1] - 1.2 * inch,
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)

    def chrome(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Times-Italic", 9)
        canvas.setFillColor(colors.HexColor("#777"))
        canvas.drawString(0.7 * inch, 0.4 * inch,
                          "Lego Worlds — L-System sample booklet")
        canvas.drawRightString(LETTER[0] - 0.7 * inch, 0.4 * inch,
                               datetime.datetime.now().strftime("%Y-%m-%d"))
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="book", frames=[frame], onPage=chrome)])

    story: list = []

    # ---- cover page ----
    story.append(Paragraph("Lego Worlds", ss["title"]))
    story.append(Paragraph(
        "Ten 32 &times; 32 stud baseplates grown from an L-System rule set. "
        "Each world contains between 0 and 8 of each object kind "
        "(buildings, trees, flowers, people). "
        "Every object is produced by a production-rule expansion interpreted "
        "by a 3D grid-turtle that places studded bricks.",
        ss["sub"]))
    story.append(Paragraph(
        "<b>The L-System alphabet.</b> <tt>F</tt> places a brick and steps "
        "one brick up; <tt>P</tt> places a plate and steps one plate up; "
        "<tt>L</tt> places a brick without advancing (used for leaves and "
        "petals); <tt>W</tt> builds a 2&times;2 wall block; <tt>R</tt> lays a "
        "flat roof plate. The movement commands <tt>&gt; &lt; ^ &amp;</tt> "
        "step one stud in each horizontal direction, and <tt>[ ]</tt> save "
        "and restore the turtle state so branches can diverge and rejoin. "
        "<tt>{C:rrggbb}</tt> sets color and <tt>{S:w,d,h}</tt> sets the "
        "current brick shape.",
        ss["body"]))
    story.append(Paragraph(
        "<b>Example rule — tree.</b> "
        "<tt>T &rarr; {C:trunk}FFFF{C:leaf}C</tt><br/>"
        "<tt>C &rarr; L[&gt;L][&lt;L][^L][&amp;L][&gt;^L][&lt;^L][&gt;&amp;L]"
        "[&lt;&amp;L]FL</tt><br/>"
        "Three trunk bricks, then a crown of eight leaf placements around "
        "the trunk top, then one more trunk, then a top leaf.",
        ss["body"]))
    story.append(Paragraph(
        "<b>Storage.</b> Each world is serialized as "
        "<tt>world_&lt;name&gt;_b&lt;n&gt;_t&lt;n&gt;_f&lt;n&gt;_p&lt;n&gt;_"
        "&lt;biome&gt;_s&lt;seed&gt;.json</tt> in the <tt>worlds/</tt> "
        "directory, so glob queries like <tt>worlds/world_*_b0_*.json</tt> "
        "(no-building worlds) or <tt>worlds/world_*_forest_*.json</tt> "
        "(forest biome) are trivial to run.",
        ss["body"]))
    story.append(PageBreak())

    # ---- one page per world ----
    for world in world_objs:
        story.append(Paragraph(
            f"{world.name.capitalize()}", ss["title"]))
        story.append(Paragraph(
            f"biome: <b>{world.biome}</b> &middot; seed: <b>{world.seed}</b> "
            f"&middot; baseplate: <font color='{world.baseplate_color}'>"
            f"&#x25a0;</font> <tt>{world.baseplate_color}</tt>",
            ss["sub"]))
        story.append(_metadata_table(world))
        story.append(Spacer(1, 10))
        story.append(_world_image(world, width_in=6.5, height_in=5.5))
        story.append(Paragraph(
            f"<i>{world.filename()}</i>", ss["caption"]))
        story.append(PageBreak())

    doc.build(story)
    return out_pdf, saved


if __name__ == "__main__":
    pdf, world_files = build_booklet()
    print(f"wrote {pdf}")
    print(f"saved {len(world_files)} worlds to ./worlds/")
    for w in world_files:
        print(f"  {w}")

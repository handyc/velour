"""
Ten math worksheets — one page each — illustrated with generic studded bricks.

Grades K-ish through 7:
  1. 1st grade addition
  2. 1st grade subtraction
  3. 2nd grade multiplication
  4. 2nd grade division
  5. 3rd grade fractions
  6. 3rd grade decimals
  7. 4th grade exponents
  8. 5th grade variables
  9. 6th grade functions
 10. 7th grade multivariable functions

No LEGO trademarks or trade dress. Generic rectangular studded bricks only.
"""
from __future__ import annotations

import io
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, StyleSheet1
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Table, TableStyle, Image as RLImage, KeepTogether, Flowable,
)

from . import brick_render as B
from .brick_render import (
    Brick, draw_brick, draw_figure, draw_group, new_scene,
    scene_to_rlimage, render_groups,
    BRICK_RED, BRICK_BLUE, BRICK_YELLOW, BRICK_GREEN, BRICK_ORANGE,
    BRICK_WHITE, BRICK_BLACK, BRICK_GREY, BRICK_TAN, BRICK_PURPLE,
    PLATE_H, BRICK_H,
)

OUT = "Math_Worksheets_Bricks.pdf"

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b6b6b")
RULE = colors.HexColor("#c9c9c9")
ACCENT = colors.HexColor("#1565c0")


def build_ss() -> StyleSheet1:
    ss = StyleSheet1()
    ss.add(ParagraphStyle("Title",     fontName="Helvetica-Bold",
                          fontSize=22, leading=26, textColor=INK,
                          spaceAfter=2))
    ss.add(ParagraphStyle("Subtitle",  fontName="Helvetica",
                          fontSize=13, leading=16, textColor=MUTED,
                          spaceAfter=10))
    ss.add(ParagraphStyle("NameLine",  fontName="Helvetica",
                          fontSize=10, leading=12, textColor=MUTED,
                          spaceAfter=14))
    ss.add(ParagraphStyle("Instr",     fontName="Helvetica-Oblique",
                          fontSize=11, leading=14, textColor=INK,
                          spaceAfter=8))
    ss.add(ParagraphStyle("Problem",   fontName="Helvetica",
                          fontSize=13, leading=17, textColor=INK,
                          spaceAfter=4))
    ss.add(ParagraphStyle("ProblemBig", fontName="Helvetica",
                          fontSize=16, leading=20, textColor=INK,
                          spaceAfter=4))
    ss.add(ParagraphStyle("Answer",    fontName="Helvetica",
                          fontSize=13, leading=17, textColor=INK,
                          spaceAfter=10))
    ss.add(ParagraphStyle("Footnote",  fontName="Helvetica-Oblique",
                          fontSize=8, leading=10, textColor=MUTED))
    ss.add(ParagraphStyle("Math",      fontName="Helvetica",
                          fontSize=14, leading=18, textColor=INK,
                          spaceAfter=6))
    return ss


# ---------------------------------------------------------------------------
# Page chrome — name / grade / footer
# ---------------------------------------------------------------------------
def chrome(canvas, doc):
    canvas.saveState()
    # Footer: worksheet name + page
    canvas.setFont("Helvetica-Oblique", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.45 * inch,
                      "Brick Math  —  printable worksheet")
    canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.45 * inch,
                           "generic studded bricks; no affiliation")
    # Top rule
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.3)
    canvas.line(0.75 * inch, LETTER[1] - 0.55 * inch,
                LETTER[0] - 0.75 * inch, LETTER[1] - 0.55 * inch)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def name_row():
    """Returns a small flowable row: 'Name: ____   Date: ____'."""
    ss = build_ss()
    t = Table([[
        Paragraph("<b>Name:</b> ______________________________________",
                  ss["NameLine"]),
        Paragraph("<b>Date:</b> _______________",
                  ss["NameLine"]),
    ]], colWidths=[4.5 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def page_header(ss, title, subtitle):
    return [
        Paragraph(title, ss["Title"]),
        Paragraph(subtitle, ss["Subtitle"]),
        name_row(),
    ]


def hrule(width_in=7.0, thick=0.3, space_above=6, space_below=8):
    class _HR(Flowable):
        def wrap(self, aw, ah):
            return width_in * 72, thick + space_above + space_below
        def draw(self):
            self.canv.setStrokeColor(RULE)
            self.canv.setLineWidth(thick)
            self.canv.line(0, space_below, width_in * 72, space_below)
    return _HR()


def answer_line(ss, text: str, blank_chars: int = 10):
    """A problem text followed by '= ____'. blank_chars controls line length."""
    underline = "_" * blank_chars
    return Paragraph(f"{text}  <b>=</b>  {underline}", ss["Math"])


# ---------------------------------------------------------------------------
# Specialized illustrations
# ---------------------------------------------------------------------------
def illus_row_of_bricks(bricks: list[Brick], width_in: float,
                        height_in: float) -> RLImage:
    """Render bricks arranged along a diagonal (isometric 'row going back')."""
    fig, ax = new_scene(width_in, height_in)
    x = 0.0
    for b in bricks:
        draw_brick(ax, b, x, 0, 0)
        x += b.w + 0.6
    return scene_to_rlimage(fig, ax, width_in, height_in)


def illus_group_count(n: int, color: str, width_in: float,
                      height_in: float,
                      per_row: int = 5,
                      greyed_indices: list[int] | None = None) -> RLImage:
    """Render n distinct 1x1 bricks in a single horizontal row.

    greyed_indices marks bricks that should appear 'taken away' (greyed).
    per_row is kept for API compatibility but ignored — every brick is its
    own panel so they never overlap.
    """
    greyed_indices = greyed_indices or []
    bricks = []
    for i in range(n):
        c = "#d8d8d8" if i in greyed_indices else color
        bricks.append(Brick(1, 1, 3, c))
    return render_groups([bricks], width_in, height_in)


def illus_single_brick(brick: Brick, width_in: float,
                       height_in: float) -> RLImage:
    fig, ax = new_scene(width_in, height_in)
    draw_brick(ax, brick, 0, 0, 0)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def illus_stack(brick: Brick, count: int, width_in: float,
                height_in: float) -> RLImage:
    """A vertical stack of 'count' identical bricks."""
    fig, ax = new_scene(width_in, height_in)
    for k in range(count):
        draw_brick(ax, brick, 0, 0, k * brick.h)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def illus_cube_of_bricks(side: int, color: str,
                         width_in: float, height_in: float) -> RLImage:
    """A cube built of side x side x side 1x1 bricks, each 3-plates tall.

    Total footprint: side x side studs.
    Total height: side bricks = side * 1.2 units.
    """
    fig, ax = new_scene(width_in, height_in)
    # Draw in painter order — back to front, bottom to top
    positions = []
    for i in range(side):
        for j in range(side):
            for k in range(side):
                positions.append((i, j, k))
    positions.sort(key=lambda p: (-(p[0] + p[1]), p[2]))
    for i, j, k in positions:
        draw_brick(ax, Brick(1, 1, 3, color),
                   i, j, k * BRICK_H)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def illus_fraction_brick(total_w: int, total_d: int, highlighted: int,
                         main_color: str, hl_color: str,
                         width_in: float, height_in: float) -> RLImage:
    """Render a total_w x total_d brick where `highlighted` studs are shown
    as a different-colored 1x1 plate sitting atop the base brick."""
    fig, ax = new_scene(width_in, height_in)
    base = Brick(total_w, total_d, 3, main_color)
    draw_brick(ax, base, 0, 0, 0)
    # Mark highlighted studs by placing 1x1 plates in the first `highlighted`
    # positions (row-major).
    placed = 0
    plates = []
    for j in range(total_d):
        for i in range(total_w):
            if placed >= highlighted:
                break
            plates.append((Brick(1, 1, 1, hl_color),
                           (i, j, base.h)))
            placed += 1
    # Paint plates in back-to-front order.
    plates.sort(key=lambda bp: -(bp[1][0] + bp[1][1]))
    for br, (x, y, z) in plates:
        draw_brick(ax, br, x, y, z)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def illus_figure(shirt=BRICK_BLUE, pants=BRICK_RED, hat=None,
                 width_in=1.2, height_in=1.6) -> RLImage:
    fig, ax = new_scene(width_in, height_in)
    draw_figure(ax, 0, 0, 0, shirt=shirt, pants=pants, hat=hat)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def illus_two_groups(n_left: int, n_right: int,
                     c_left: str, c_right: str,
                     width_in: float, height_in: float) -> RLImage:
    """Two groups of distinct 1x1 bricks side-by-side, separated by a wider
    gap so the groups read as two collections to count."""
    left = [Brick(1, 1, 3, c_left) for _ in range(n_left)]
    right = [Brick(1, 1, 3, c_right) for _ in range(n_right)]
    return render_groups([left, right], width_in, height_in)


def illus_division_groups(groups: list[int], colors: list[str],
                          width_in: float, height_in: float) -> RLImage:
    """Several groups of distinct 1x1 bricks, one colored group per entry."""
    brick_groups = [
        [Brick(1, 1, 3, c) for _ in range(n)]
        for n, c in zip(groups, colors)
    ]
    return render_groups(brick_groups, width_in, height_in)


def illus_xy_plane_fn(points: list[tuple[float, float]],
                      width_in: float, height_in: float) -> RLImage:
    """A small Cartesian plot for the functions pages."""
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=220)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ax.plot(xs, ys, "o-", color="#1565c0", linewidth=1.2, markersize=5)
    ax.grid(True, color="#e0e0e0", linewidth=0.5)
    ax.axhline(0, color="#777", linewidth=0.5)
    ax.axvline(0, color="#777", linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_color("#888")
        spine.set_linewidth(0.5)
    ax.set_xlabel("n", fontsize=9, family="sans-serif")
    ax.set_ylabel("f(n)", fontsize=9, family="sans-serif")
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.04,
                transparent=True)
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=width_in * 72, height=height_in * 72)


def sierpinski_carpet_cells(stage: int) -> list[tuple[int, int]]:
    """Return the grid cells of a Sierpinski-carpet at the given stage."""
    n = 3 ** stage
    cells = []
    for i in range(n):
        for j in range(n):
            x, y, s = i, j, stage
            keep = True
            while s > 0:
                if x % 3 == 1 and y % 3 == 1:
                    keep = False
                    break
                x //= 3
                y //= 3
                s -= 1
            if keep:
                cells.append((i, j))
    return cells


def illus_fractal_grid(cells, color: str, width_in: float,
                       height_in: float) -> RLImage:
    """Render 1x1 bricks at the given (i, j) grid positions."""
    fig, ax = new_scene(width_in, height_in)
    group = [(Brick(1, 1, 3, color), (i, j, 0)) for i, j in cells]
    draw_group(ax, group)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def sierpinski_triangle_cells(stage: int) -> list[tuple[int, int]]:
    """Pascal-mod-2 Sierpinski triangle on a 2^stage grid."""
    n = 2 ** stage
    return [(i, j) for i in range(n) for j in range(n) if (i & j) == 0]


def vicsek_cells(stage: int) -> list[tuple[int, int]]:
    """Vicsek (plus-cross) fractal on a 3^stage grid."""
    plus = {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)}
    n = 3 ** stage
    cells = []
    for i in range(n):
        for j in range(n):
            x, y, s = i, j, stage
            keep = True
            while s > 0:
                if (x % 3, y % 3) not in plus:
                    keep = False
                    break
                x //= 3
                y //= 3
                s -= 1
            if keep:
                cells.append((i, j))
    return cells


# ---------------------------------------------------------------------------
# Worksheet pages
# ---------------------------------------------------------------------------
def page_addition(story, ss):
    story.extend(page_header(
        ss,
        "Brick Addition",
        "1st grade &middot; count the bricks in each group, then add"))
    story.append(Paragraph(
        "Look at the two groups of bricks. Count each group, then "
        "write the total.", ss["Instr"]))

    problems = [
        (3, 2, BRICK_RED, BRICK_BLUE),
        (4, 1, BRICK_YELLOW, BRICK_GREEN),
        (2, 4, BRICK_ORANGE, BRICK_PURPLE),
        (5, 3, BRICK_BLUE, BRICK_RED),
    ]
    for idx, (a, b, ca, cb) in enumerate(problems, 1):
        story.append(Paragraph(f"<b>Problem {idx}.</b>", ss["Problem"]))
        story.append(illus_two_groups(a, b, ca, cb, width_in=5.0, height_in=1.1))
        story.append(Paragraph(
            f"{a} &nbsp; + &nbsp; {b} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
            ss["Math"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())


def page_subtraction(story, ss):
    story.extend(page_header(
        ss,
        "Brick Subtraction",
        "1st grade &middot; start with some bricks, take some away"))
    story.append(Paragraph(
        "The grey bricks have been taken away. How many bricks are left?",
        ss["Instr"]))

    problems = [
        (5, 2, BRICK_RED),
        (6, 3, BRICK_BLUE),
        (8, 4, BRICK_GREEN),
        (7, 2, BRICK_ORANGE),
    ]
    for idx, (total, taken, color) in enumerate(problems, 1):
        # Grey out the LAST `taken` bricks
        greyed = list(range(total - taken, total))
        story.append(Paragraph(f"<b>Problem {idx}.</b>", ss["Problem"]))
        story.append(illus_group_count(total, color, width_in=5.0,
                                        height_in=1.0, per_row=total,
                                        greyed_indices=greyed))
        story.append(Paragraph(
            f"{total} &nbsp; &minus; &nbsp; {taken} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
            ss["Math"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())


def page_multiplication(story, ss):
    story.extend(page_header(
        ss,
        "Brick Multiplication",
        "2nd grade &middot; the studs on a brick show you rows &times; columns"))
    story.append(Paragraph(
        "Every brick's studs are arranged in rows and columns. "
        "A <b>2 &times; 3</b> brick has 2 rows of 3 studs. How many studs "
        "in total? Count by multiplying.",
        ss["Instr"]))

    problems = [
        (2, 3, BRICK_RED),
        (3, 4, BRICK_BLUE),
        (2, 6, BRICK_YELLOW),
        (4, 4, BRICK_GREEN),
    ]
    # Use a two-column table: illustration | equation
    rows = []
    for idx, (w, d, c) in enumerate(problems, 1):
        img = illus_single_brick(Brick(w, d, 3, c), width_in=2.2,
                                 height_in=1.3)
        eq = Paragraph(
            f"<b>Problem {idx}.</b><br/>"
            f"This brick is {w} &times; {d}.<br/>"
            f"{w} &times; {d} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> studs",
            ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[2.4 * inch, 4.5 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_division(story, ss):
    story.extend(page_header(
        ss,
        "Brick Division",
        "2nd grade &middot; share the studs equally"))
    story.append(Paragraph(
        "A big brick has many studs. If a group of friends share the studs "
        "equally, how many does each friend get? Look at the brick and "
        "divide.",
        ss["Instr"]))

    # Design: show a big brick and N friends below; answer = total_studs / N.
    problems = [
        (Brick(2, 4, 3, BRICK_BLUE), 2),    # 8 / 2 = 4
        (Brick(2, 6, 3, BRICK_RED), 3),     # 12 / 3 = 4
        (Brick(3, 4, 3, BRICK_GREEN), 4),   # 12 / 4 = 3
        (Brick(2, 5, 3, BRICK_ORANGE), 5),  # 10 / 5 = 2
    ]
    rows = []
    for idx, (brick, friends) in enumerate(problems, 1):
        total = brick.w * brick.d
        img = illus_single_brick(brick, width_in=2.2, height_in=1.3)
        # Draw `friends` little figures stacked
        fig, ax = new_scene(2.0, 1.3)
        for k in range(friends):
            draw_figure(ax, k * 2.6, 0, 0,
                        shirt=[BRICK_RED, BRICK_BLUE, BRICK_GREEN,
                               BRICK_YELLOW, BRICK_ORANGE][k % 5],
                        pants=BRICK_BLACK)
        people_img = scene_to_rlimage(fig, ax, 2.0, 1.3)
        eq = Paragraph(
            f"<b>Problem {idx}.</b> The brick has {total} studs.<br/>"
            f"Shared with {friends} friends:<br/>"
            f"{total} &divide; {friends} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;</u> studs each",
            ss["Math"])
        rows.append([img, people_img, eq])
    tbl = Table(rows, colWidths=[2.2 * inch, 2.1 * inch, 2.6 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_fractions(story, ss):
    story.extend(page_header(
        ss,
        "Brick Fractions",
        "3rd grade &middot; what part of the brick is highlighted?"))
    story.append(Paragraph(
        "The studs on a brick can be split into equal parts. "
        "Each coloured plate covers one stud. How many studs are "
        "covered, and what fraction of the whole brick is covered?",
        ss["Instr"]))

    problems = [
        (Brick(2, 4, 3, BRICK_WHITE), 2, BRICK_RED),     # 2/8 = 1/4
        (Brick(2, 3, 3, BRICK_WHITE), 3, BRICK_BLUE),    # 3/6 = 1/2
        (Brick(3, 3, 3, BRICK_WHITE), 3, BRICK_GREEN),   # 3/9 = 1/3
        (Brick(2, 4, 3, BRICK_WHITE), 6, BRICK_ORANGE),  # 6/8 = 3/4
    ]
    rows = []
    for idx, (base, hl, color) in enumerate(problems, 1):
        img = illus_fraction_brick(base.w, base.d, hl, base.color,
                                    color, width_in=2.4, height_in=1.4)
        total = base.w * base.d
        eq = Paragraph(
            f"<b>Problem {idx}.</b> The brick has {total} studs.<br/>"
            f"{hl} are coloured.<br/>"
            f"Fraction coloured = "
            f"<u>&nbsp;&nbsp;&nbsp;</u> / <u>&nbsp;&nbsp;&nbsp;</u>"
            f"<br/>"
            f"<i>(then simplify if you can)</i>",
            ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[2.5 * inch, 4.4 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_decimals(story, ss):
    story.extend(page_header(
        ss,
        "Brick Decimals",
        "3rd grade &middot; heights and thicknesses in centimetres"))
    story.append(Paragraph(
        "For these problems, pretend one brick is <b>1.2 cm</b> tall "
        "and one plate (a thin brick) is <b>0.4 cm</b> tall. "
        "Use these numbers to work out each tower's height.",
        ss["Instr"]))

    # Problem types: tower of n bricks; brick + m plates; etc.
    problems = [
        ("A tower of 3 bricks",
         [Brick(2, 2, 3, BRICK_RED)] * 3,
         "3 &times; 1.2"),
        ("2 bricks, then 3 plates on top",
         [Brick(2, 2, 3, BRICK_BLUE)] * 2 +
         [Brick(2, 2, 1, BRICK_YELLOW)] * 3,
         "2 &times; 1.2 &nbsp; + &nbsp; 3 &times; 0.4"),
        ("4 plates stacked",
         [Brick(2, 2, 1, BRICK_GREEN)] * 4,
         "4 &times; 0.4"),
        ("1 brick + 5 plates",
         [Brick(2, 2, 3, BRICK_ORANGE)] +
         [Brick(2, 2, 1, BRICK_WHITE)] * 5,
         "1.2 &nbsp; + &nbsp; 5 &times; 0.4"),
    ]
    rows = []
    for idx, (desc, stack, expr) in enumerate(problems, 1):
        fig, ax = new_scene(1.6, 1.6)
        z = 0
        for b in stack:
            draw_brick(ax, b, 0, 0, z)
            z += b.h
        img = scene_to_rlimage(fig, ax, 1.6, 1.6)
        eq = Paragraph(
            f"<b>Problem {idx}.</b> {desc}.<br/>"
            f"Total height = {expr} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> cm",
            ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[1.8 * inch, 5.1 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_exponents(story, ss):
    story.extend(page_header(
        ss,
        "Brick Exponents",
        "4th grade &middot; cubes of bricks"))
    story.append(Paragraph(
        "A cube that is <b>n</b> bricks wide, <b>n</b> bricks deep, "
        "and <b>n</b> bricks tall contains <b>n &times; n &times; n = "
        "n<sup>3</sup></b> bricks. Look at each cube and count how many "
        "bricks it is made of.",
        ss["Instr"]))

    problems = [2, 3, 4]
    rows = []
    colors_ = [BRICK_RED, BRICK_BLUE, BRICK_GREEN]
    for idx, (n, c) in enumerate(zip(problems, colors_), 1):
        img = illus_cube_of_bricks(n, c, width_in=1.7, height_in=1.7)
        eq = Paragraph(
            f"<b>Problem {idx}.</b> This cube is "
            f"{n} &times; {n} &times; {n}.<br/>"
            f"{n}<sup>3</sup> &nbsp; = &nbsp; {n} &times; {n} &times; {n} "
            f"&nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks",
            ss["Math"])
        rows.append([img, eq])
    # One more problem that's algebraic without a picture
    rows.append([
        Paragraph("", ss["Math"]),
        Paragraph(
            "<b>Problem 4.</b> A cube is 5 &times; 5 &times; 5.<br/>"
            "How many bricks does it use?<br/>"
            "5<sup>3</sup> &nbsp; = &nbsp; "
            "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks",
            ss["Math"])])
    tbl = Table(rows, colWidths=[1.9 * inch, 5.0 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_variables(story, ss):
    story.extend(page_header(
        ss,
        "Brick Variables",
        "5th grade &middot; letters stand in for numbers"))
    story.append(Paragraph(
        "We'll use the letter <b>x</b> to mean <i>&ldquo;the number of studs "
        "on one brick.&rdquo;</i> The value of <b>x</b> depends on which "
        "brick we are looking at. Work out each expression.",
        ss["Instr"]))

    problems = [
        (Brick(2, 2, 3, BRICK_RED), "3x",
         "If x is the number of studs on this brick, what is 3x?"),
        (Brick(2, 3, 3, BRICK_BLUE), "x + 4",
         "If x is the number of studs on this brick, what is x + 4?"),
        (Brick(2, 4, 3, BRICK_GREEN), "2x - 1",
         "If x is the number of studs on this brick, what is 2x &minus; 1?"),
        (Brick(1, 4, 3, BRICK_ORANGE), "x\u00b2",
         "If x is the number of studs on this brick, what is x &times; x?"),
    ]
    rows = []
    for idx, (brick, expr, prompt) in enumerate(problems, 1):
        img = illus_single_brick(brick, width_in=2.1, height_in=1.2)
        studs = brick.w * brick.d
        eq = Paragraph(
            f"<b>Problem {idx}.</b> {prompt}<br/>"
            f"x = {studs}, so <b>{expr}</b> = "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
            ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[2.3 * inch, 4.6 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_functions(story, ss):
    story.extend(page_header(
        ss,
        "Brick Functions",
        "6th grade &middot; a rule that turns one number into another"))
    story.append(Paragraph(
        "A <b>function</b> is a rule. Put a number in, get a number out. "
        "Let <b>f(n)</b> = <i>the number of studs on a 2 &times; n brick.</i>  "
        "So f(1) = 2, f(2) = 4, f(3) = 6, and so on.",
        ss["Instr"]))

    # Row of distinct 2xn bricks for n = 1..4
    story.append(Paragraph("<b>The bricks this function describes "
                           "(n = 1, 2, 3, 4):</b>", ss["Problem"]))
    story.append(render_groups(
        [[Brick(2, n, 3, BRICK_BLUE)] for n in (1, 2, 3, 4)],
        width_in=5.5, height_in=1.5, group_gap=0.35))

    story.append(Paragraph(
        "<b>Problem 1.</b> Finish the table:", ss["Problem"]))
    table_data = [
        ["n", "1", "2", "3", "4", "5", "10"],
        ["f(n)", "2", "4", "6", "___", "___", "___"],
    ]
    t = Table(table_data,
              colWidths=[0.6 * inch] + [0.65 * inch] * 6)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        "<b>Problem 2.</b> Write a rule for f(n) using only the letter n:",
        ss["Problem"]))
    story.append(Paragraph("f(n) = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                            "&nbsp;&nbsp;&nbsp;&nbsp;</u>",
                            ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 3.</b> Plot the points (1,2), (2,4), (3,6), (4,8) "
        "on the grid below. What shape do they make?", ss["Problem"]))
    story.append(illus_xy_plane_fn(
        [(0, 0), (1, 2), (2, 4), (3, 6), (4, 8)],
        width_in=3.5, height_in=2.2))
    story.append(PageBreak())


def page_multivariable(story, ss):
    story.extend(page_header(
        ss,
        "Brick Multivariable Functions",
        "7th grade &middot; a rule that takes two numbers in"))
    story.append(Paragraph(
        "A <b>multivariable function</b> takes more than one number as input. "
        "Let <b>S(w, d)</b> = <i>the number of studs on a w &times; d brick.</i>  "
        "Then S(w, d) = w &times; d. A separate function <b>V(w, d, h)</b> "
        "= <i>the volume of a w &times; d &times; h tower</i> uses three "
        "inputs: V(w, d, h) = w &times; d &times; h.",
        ss["Instr"]))

    # Problem 1: S(w, d)
    story.append(Paragraph("<b>Problem 1.</b> Use S(w, d) = w &times; d.",
                            ss["Problem"]))
    story.append(Paragraph(
        "&nbsp;&nbsp;(a)&nbsp; S(2, 3) &nbsp; = &nbsp; "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    story.append(Paragraph(
        "&nbsp;&nbsp;(b)&nbsp; S(4, 5) &nbsp; = &nbsp; "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    # Illustration: three distinct bricks of different w, d, each in its
    # own panel so they don't visually merge.
    story.append(render_groups(
        [[Brick(2, 3, 3, BRICK_RED)],
         [Brick(3, 4, 3, BRICK_BLUE)],
         [Brick(2, 6, 3, BRICK_GREEN)]],
        width_in=5.5, height_in=1.6, group_gap=0.4))

    # Problem 2: V(w, d, h)
    story.append(Paragraph(
        "<b>Problem 2.</b> Use V(w, d, h) = w &times; d &times; h.",
        ss["Problem"]))
    story.append(Paragraph(
        "&nbsp;&nbsp;(a)&nbsp; V(2, 2, 2) &nbsp; = &nbsp; "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    story.append(Paragraph(
        "&nbsp;&nbsp;(b)&nbsp; V(3, 2, 4) &nbsp; = &nbsp; "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    # Problem 3: surface area as a warm-up to algebraic multivariable fns
    story.append(Paragraph(
        "<b>Problem 3.</b> The surface area of a w &times; d &times; h "
        "brick is A(w, d, h) = 2(wd + wh + dh). Compute A(2, 3, 4):",
        ss["Problem"]))
    story.append(Paragraph(
        "&nbsp;&nbsp;A(2, 3, 4) = 2(2&middot;3 + 2&middot;4 + 3&middot;4) "
        "= 2(6 + 8 + 12) = 2 &middot; 26 = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    # Problem 4: challenge — fill a table
    story.append(Paragraph(
        "<b>Problem 4.</b> Finish this table of S(w, d) values:",
        ss["Problem"]))
    table_data = [
        ["w \\ d", "1", "2", "3", "4"],
        ["1", "1", "2", "3", "___"],
        ["2", "2", "4", "___", "___"],
        ["3", "3", "___", "___", "___"],
        ["4", "___", "___", "___", "___"],
    ]
    t = Table(table_data,
              colWidths=[0.7 * inch] + [0.6 * inch] * 4,
              rowHeights=[0.3 * inch] * 5)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eee")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eee")),
    ]))
    story.append(t)
    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Build the whole PDF
# ---------------------------------------------------------------------------
def page_fractals(story, ss):
    story.extend(page_header(
        ss,
        "Brick Fractals",
        "6th grade &middot; shapes that repeat inside themselves"))
    story.append(Paragraph(
        "A <b>fractal</b> is a pattern that looks the same when you zoom in. "
        "The <i>Sierpinski carpet</i> starts with a 3 &times; 3 square of "
        "bricks and removes the middle. Then each of the 8 remaining squares "
        "has its own middle removed, and so on.",
        ss["Instr"]))

    story.append(Paragraph(
        "<b>Problem 1.</b> This is <b>stage 1</b>: a 3 &times; 3 block with "
        "the middle brick removed. Count the bricks.", ss["Problem"]))
    story.append(illus_fractal_grid(sierpinski_carpet_cells(1), BRICK_RED,
                                    width_in=1.8, height_in=1.4))
    story.append(Paragraph(
        "Stage 1 bricks = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 2.</b> For <b>stage 2</b>, each brick from stage 1 is "
        "replaced by another stage-1 pattern. Count, or compute 8 &times; 8:",
        ss["Problem"]))
    story.append(illus_fractal_grid(sierpinski_carpet_cells(2), BRICK_BLUE,
                                    width_in=3.0, height_in=2.0))
    story.append(Paragraph(
        "Stage 2 bricks = 8 &times; 8 = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 3.</b> Each stage multiplies the bricks by 8. "
        "How many bricks in <b>stage 3</b>?", ss["Problem"]))
    story.append(Paragraph(
        "Stage 3 = 8 &times; 8 &times; 8 = 8<sup>3</sup> = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 4.</b> Stage 1 is <b>3</b> bricks across. "
        "Stage 2 is <b>9</b> bricks across. How wide is stage 3?",
        ss["Problem"]))
    story.append(Paragraph(
        "Stage 3 width = 3 &times; 3 &times; 3 = 3<sup>3</sup> = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks",
        ss["Math"]))
    story.append(PageBreak())


def page_logic(story, ss):
    story.extend(page_header(
        ss,
        "Brick Logic",
        "5th grade &middot; AND, OR, NOT"))
    story.append(Paragraph(
        "In logic, <b>AND</b> means both things are true. <b>OR</b> means "
        "at least one is true. <b>NOT</b> flips true and false.",
        ss["Instr"]))

    story.append(Paragraph(
        "<b>Problem 1 (AND).</b> Look at bricks A, B, C, D. Which one is "
        "<i>red</i> AND has exactly <i>4 studs</i>?", ss["Problem"]))
    story.append(render_groups(
        [[Brick(2, 2, 3, BRICK_RED)],
         [Brick(2, 3, 3, BRICK_RED)],
         [Brick(2, 2, 3, BRICK_BLUE)],
         [Brick(3, 2, 3, BRICK_RED)]],
        width_in=5.5, height_in=1.1, group_gap=0.45))
    story.append(Paragraph(
        "Answer: <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> (A / B / C / D)",
        ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 2 (OR).</b> Which bricks are <i>green</i> OR have "
        "<i>more than 5 studs</i>? (List all that apply.)",
        ss["Problem"]))
    story.append(render_groups(
        [[Brick(2, 3, 3, BRICK_YELLOW)],
         [Brick(2, 2, 3, BRICK_GREEN)],
         [Brick(1, 4, 3, BRICK_RED)],
         [Brick(3, 3, 3, BRICK_GREEN)]],
        width_in=5.5, height_in=1.1, group_gap=0.45))
    story.append(Paragraph(
        "Answer: <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 3 (NOT).</b> Which brick is <i>NOT</i> blue?",
        ss["Problem"]))
    story.append(render_groups(
        [[Brick(2, 2, 3, BRICK_BLUE)],
         [Brick(2, 4, 3, BRICK_BLUE)],
         [Brick(2, 2, 3, BRICK_ORANGE)],
         [Brick(3, 2, 3, BRICK_BLUE)]],
        width_in=5.5, height_in=1.1, group_gap=0.45))
    story.append(Paragraph(
        "Answer: <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 4.</b> Fill in the truth table for <b>A AND B</b>. "
        "(T = true, F = false.)", ss["Problem"]))
    data = [
        ["A", "B", "A AND B"],
        ["T", "T", "___"],
        ["T", "F", "___"],
        ["F", "T", "___"],
        ["F", "F", "___"],
    ]
    t = Table(data, colWidths=[0.6 * inch, 0.6 * inch, 1.0 * inch])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(PageBreak())


def page_programming(story, ss):
    story.extend(page_header(
        ss,
        "Brick Computer Programming",
        "6th grade &middot; loops, conditions, and binary numbers"))
    story.append(Paragraph(
        "Computers use <b>binary</b>: only 0 and 1. In our bricks, "
        "<b>colored = 1</b> and <b>grey = 0</b>. "
        "They also follow <b>loops</b> (do it N times) and "
        "<b>conditions</b> (if something is true, do this).",
        ss["Instr"]))

    story.append(Paragraph(
        "<b>Problem 1 (binary).</b> Place values are "
        "<b>8, 4, 2, 1</b> from left to right. What number is this pattern?",
        ss["Problem"]))
    story.append(render_groups(
        [[Brick(1, 1, 3, BRICK_RED)],
         [Brick(1, 1, 3, BRICK_GREY)],
         [Brick(1, 1, 3, BRICK_RED)],
         [Brick(1, 1, 3, BRICK_RED)]],
        width_in=3.0, height_in=0.9, group_gap=0.3))
    story.append(Paragraph(
        "1 0 1 1 = 8 + 0 + 2 + 1 = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 2 (loop).</b> This pseudocode runs a loop 5 times, "
        "placing one brick each time:", ss["Problem"]))
    story.append(Paragraph(
        "<font face='Courier'>for i in range(5):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;place_one_brick()</font>",
        ss["Math"]))
    story.append(illus_stack(Brick(2, 2, 3, BRICK_BLUE), count=5,
                             width_in=1.2, height_in=1.8))
    story.append(Paragraph(
        "Total bricks = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 3 (if).</b> This pseudocode counts red bricks:",
        ss["Problem"]))
    story.append(Paragraph(
        "<font face='Courier'>count = 0<br/>"
        "for brick in bricks:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;if brick.color == 'red':<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;count = count + 1"
        "</font>", ss["Math"]))
    story.append(render_groups(
        [[Brick(2, 2, 3, BRICK_RED)],
         [Brick(2, 3, 3, BRICK_BLUE)],
         [Brick(2, 4, 3, BRICK_RED)],
         [Brick(1, 4, 3, BRICK_GREEN)],
         [Brick(2, 2, 3, BRICK_RED)]],
        width_in=5.5, height_in=1.0, group_gap=0.35))
    story.append(Paragraph(
        "Final count = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))
    story.append(PageBreak())


def page_advanced_fractals(story, ss):
    story.extend(page_header(
        ss,
        "Advanced Brick Fractals",
        "7th&#8211;8th grade &middot; Sierpinski triangle, Vicsek fractal, "
        "self-similarity"))
    story.append(Paragraph(
        "Some fractals replicate themselves <i>N</i> times at each step. "
        "If one stage fits inside a 3 &times; 3 parent, the Sierpinski "
        "<i>carpet</i> keeps 8 of 9 cells; the Vicsek fractal keeps only "
        "the center-plus 5 of 9. The Sierpinski <i>triangle</i> keeps 3 of "
        "4 cells in a 2 &times; 2 parent.",
        ss["Instr"]))

    story.append(Paragraph(
        "<b>Problem 1.</b> Here is a stage-2 <b>Sierpinski triangle</b> "
        "(4 &times; 4 grid, Pascal-mod-2 rule). Count the bricks.",
        ss["Problem"]))
    story.append(illus_fractal_grid(sierpinski_triangle_cells(2), BRICK_ORANGE,
                                    width_in=1.2, height_in=1.2))
    story.append(Paragraph(
        "Stage 2 bricks = 3 &times; 3 = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 2.</b> This is <b>stage 3</b> of the Sierpinski "
        "triangle. Use 3<sup>n</sup> to predict the count, then check.",
        ss["Problem"]))
    story.append(illus_fractal_grid(sierpinski_triangle_cells(3), BRICK_GREEN,
                                    width_in=1.6, height_in=1.6))
    story.append(Paragraph(
        "Stage 3 bricks = 3<sup>3</sup> = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 3 (Vicsek).</b> The plus-cross fractal keeps 5 of every "
        "9 cells. Below is <b>stage 2</b> (9 &times; 9 grid). Predict the "
        "brick count.", ss["Problem"]))
    story.append(illus_fractal_grid(vicsek_cells(2), BRICK_PURPLE,
                                    width_in=1.6, height_in=1.6))
    story.append(Paragraph(
        "Stage 2 bricks = 5<sup>2</sup> = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    story.append(Paragraph(
        "<b>Problem 4.</b> The Sierpinski carpet multiplies bricks by 8 at "
        "each stage. How many bricks in <b>stage 4</b>?", ss["Problem"]))
    story.append(Paragraph(
        "Stage 4 = 8<sup>4</sup> = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))
    story.append(PageBreak())


def build():
    ss = build_ss()
    doc = BaseDocTemplate(
        OUT, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.7 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  LETTER[0] - 1.5 * inch, LETTER[1] - 1.45 * inch,
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="ws", frames=[frame], onPage=chrome)])

    story = []
    page_addition(story, ss)
    page_subtraction(story, ss)
    page_multiplication(story, ss)
    page_division(story, ss)
    page_fractions(story, ss)
    page_decimals(story, ss)
    page_exponents(story, ss)
    page_variables(story, ss)
    page_functions(story, ss)
    page_multivariable(story, ss)
    page_fractals(story, ss)
    page_logic(story, ss)
    page_programming(story, ss)
    page_advanced_fractals(story, ss)

    doc.build(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()

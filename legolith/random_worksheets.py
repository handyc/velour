"""
Random 50-page math worksheet set. Each page is one of the 10 topics from
worksheets.py, but with freshly generated problems. Uses the same canonical
LDraw-ratio brick renderer.

Run:  .venv/bin/python random_worksheets.py [--seed N] [--pages N]
"""
from __future__ import annotations

import argparse
import datetime
import random

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Table, TableStyle,
)

from .brick_render import (
    Brick, render_groups,
    BRICK_RED, BRICK_BLUE, BRICK_YELLOW, BRICK_GREEN, BRICK_ORANGE,
    BRICK_WHITE, BRICK_BLACK, BRICK_GREY, BRICK_TAN, BRICK_PURPLE,
)

from . import worksheets as W
from .worksheets import (
    build_ss, chrome, page_header,
    illus_single_brick, illus_stack, illus_cube_of_bricks,
    illus_fraction_brick, illus_figure, illus_xy_plane_fn,
    illus_two_groups, illus_group_count, illus_division_groups,
    illus_fractal_grid, sierpinski_carpet_cells,
    sierpinski_triangle_cells, vicsek_cells,
    answer_line, INK, RULE,
)
from reportlab.platypus import Table as _Table, TableStyle as _TableStyle


COLORS = [BRICK_RED, BRICK_BLUE, BRICK_YELLOW, BRICK_GREEN,
          BRICK_ORANGE, BRICK_PURPLE]


def pick_color(rng, exclude: list[str] | None = None) -> str:
    exclude = exclude or []
    choices = [c for c in COLORS if c not in exclude]
    return rng.choice(choices)


# ---------------------------------------------------------------------------
# Random problem generators (each returns a list of problem tuples)
# ---------------------------------------------------------------------------
def gen_addition(rng) -> list:
    out = []
    for _ in range(4):
        a = rng.randint(1, 5)
        b = rng.randint(1, 5)
        ca = pick_color(rng)
        cb = pick_color(rng, exclude=[ca])
        out.append((a, b, ca, cb))
    return out


def gen_subtraction(rng) -> list:
    out = []
    for _ in range(4):
        total = rng.randint(4, 8)
        taken = rng.randint(1, total - 1)
        color = pick_color(rng)
        out.append((total, taken, color))
    return out


def gen_multiplication(rng) -> list:
    out = []
    for _ in range(4):
        w = rng.randint(2, 4)
        d = rng.randint(2, 6)
        out.append((w, d, pick_color(rng)))
    return out


def gen_division(rng) -> list:
    out = []
    for _ in range(4):
        # Choose (w, d, friends) such that w*d is divisible by friends.
        while True:
            w = rng.randint(2, 4)
            d = rng.randint(2, 6)
            total = w * d
            divisors = [k for k in (2, 3, 4, 5, 6) if total % k == 0 and k < total]
            if divisors:
                friends = rng.choice(divisors)
                break
        out.append((Brick(w, d, 3, pick_color(rng)), friends))
    return out


def gen_fractions(rng) -> list:
    out = []
    for _ in range(4):
        w = rng.randint(2, 3)
        d = rng.randint(2, 4)
        total = w * d
        hl = rng.randint(1, total - 1)
        out.append((w, d, hl, pick_color(rng)))
    return out


def gen_decimals(rng) -> list:
    out = []
    for _ in range(4):
        n_bricks = rng.randint(0, 3)
        n_plates = rng.randint(0, 5)
        if n_bricks + n_plates == 0:
            n_bricks = 1
        cb = pick_color(rng)
        cp = pick_color(rng, exclude=[cb])
        parts = []
        pieces_desc = []
        expr_parts = []
        if n_bricks:
            parts += [Brick(2, 2, 3, cb)] * n_bricks
            pieces_desc.append(f"{n_bricks} brick{'s' if n_bricks != 1 else ''}")
            expr_parts.append(f"{n_bricks} &times; 1.2")
        if n_plates:
            parts += [Brick(2, 2, 1, cp)] * n_plates
            pieces_desc.append(f"{n_plates} plate{'s' if n_plates != 1 else ''}")
            expr_parts.append(f"{n_plates} &times; 0.4")
        desc = " and ".join(pieces_desc) + " stacked"
        expr = " &nbsp; + &nbsp; ".join(expr_parts)
        out.append((desc, parts, expr))
    return out


def gen_exponents(rng) -> list:
    # Pick 3 distinct side lengths in [2, 4] to avoid huge cubes; 5³ is huge.
    sides = rng.sample([2, 3, 4], 3)
    return [(s, pick_color(rng)) for s in sides]


def gen_variables(rng) -> list:
    # Each problem: brick of (w, d); x = studs; an expression in x.
    templates = [
        ("3x", "what is 3x?", lambda x: 3 * x),
        ("x + 4", "what is x + 4?", lambda x: x + 4),
        ("2x &minus; 1", "what is 2x &minus; 1?", lambda x: 2 * x - 1),
        ("x\u00b2", "what is x &times; x?", lambda x: x * x),
        ("x + 10", "what is x + 10?", lambda x: x + 10),
        ("5x", "what is 5x?", lambda x: 5 * x),
    ]
    chosen = rng.sample(templates, 4)
    out = []
    for expr, prompt, _fn in chosen:
        w = rng.randint(1, 3)
        d = rng.randint(2, 4)
        out.append((Brick(w, d, 3, pick_color(rng)), expr, prompt))
    return out


def gen_functions(rng) -> tuple:
    # Pick f(n) = k*n (k in 2..3) or f(n) = n + c (c in 1..4)
    kind = rng.choice(["linear", "shift"])
    if kind == "linear":
        k = rng.randint(2, 3)
        rule = f"{k} &times; n"
        rule_no_markup = f"f(n) = {k}n"
        fn = lambda n: k * n
        bricks_for = lambda n: Brick(k, n, 3, BRICK_BLUE)
        desc = (f"Let <b>f(n)</b> = <i>the number of studs on a {k} &times; n "
                f"brick.</i> So f(1) = {k}, f(2) = {2 * k}, and so on.")
    else:
        c = rng.randint(1, 4)
        rule = f"n + {c}"
        rule_no_markup = f"f(n) = n + {c}"
        fn = lambda n: n + c
        bricks_for = lambda n: Brick(1, n, 3, BRICK_BLUE)
        desc = (f"Let <b>f(n)</b> = <i>the number of studs on a 1 &times; n "
                f"brick, plus {c}.</i> So f(1) = {1 + c}, f(2) = {2 + c}, "
                f"and so on.")
    ns_shown = [1, 2, 3, 4]
    table_ns = [1, 2, 3, 4, 5, 10]
    table_fs = [fn(n) if n <= 3 else "___" for n in table_ns]
    return {
        "rule": rule, "rule_no_markup": rule_no_markup,
        "desc": desc, "fn": fn, "bricks_for": bricks_for,
        "ns_shown": ns_shown, "table_ns": table_ns, "table_fs": table_fs,
    }


def gen_multivariable(rng) -> dict:
    bricks = []
    for _ in range(3):
        w = rng.randint(2, 3)
        d = rng.randint(2, 5)
        bricks.append(Brick(w, d, 3, pick_color(rng)))
    probs_S = [(rng.randint(2, 4), rng.randint(2, 5)) for _ in range(2)]
    probs_V = [(rng.randint(2, 3), rng.randint(2, 3), rng.randint(2, 4))
               for _ in range(2)]
    return {"bricks": bricks, "probs_S": probs_S, "probs_V": probs_V}


# ---------------------------------------------------------------------------
# Parametric page builders
# ---------------------------------------------------------------------------
def page_addition(story, ss, rng):
    problems = gen_addition(rng)
    story.extend(page_header(
        ss, "Brick Addition",
        "1st grade &middot; count the bricks in each group, then add"))
    story.append(Paragraph(
        "Look at the two groups of bricks. Count each group, then "
        "write the total.", ss["Instr"]))
    for idx, (a, b, ca, cb) in enumerate(problems, 1):
        story.append(Paragraph(f"<b>Problem {idx}.</b>", ss["Problem"]))
        story.append(illus_two_groups(a, b, ca, cb, width_in=5.0, height_in=1.1))
        story.append(Paragraph(
            f"{a} &nbsp; + &nbsp; {b} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())


def page_subtraction(story, ss, rng):
    problems = gen_subtraction(rng)
    story.extend(page_header(
        ss, "Brick Subtraction",
        "1st grade &middot; start with some bricks, take some away"))
    story.append(Paragraph(
        "The grey bricks have been taken away. How many bricks are left?",
        ss["Instr"]))
    for idx, (total, taken, color) in enumerate(problems, 1):
        greyed = list(range(total - taken, total))
        story.append(Paragraph(f"<b>Problem {idx}.</b>", ss["Problem"]))
        story.append(illus_group_count(total, color, width_in=5.0,
                                       height_in=1.0, per_row=total,
                                       greyed_indices=greyed))
        story.append(Paragraph(
            f"{total} &nbsp; &minus; &nbsp; {taken} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())


def page_multiplication(story, ss, rng):
    problems = gen_multiplication(rng)
    story.extend(page_header(
        ss, "Brick Multiplication",
        "2nd grade &middot; the studs on a brick show you rows &times; columns"))
    story.append(Paragraph(
        "Every brick's studs are arranged in rows and columns. "
        "Count how many studs by multiplying.", ss["Instr"]))
    rows = []
    for idx, (w, d, c) in enumerate(problems, 1):
        img = illus_single_brick(Brick(w, d, 3, c), width_in=2.2, height_in=1.3)
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


def page_division(story, ss, rng):
    problems = gen_division(rng)
    story.extend(page_header(
        ss, "Brick Division",
        "2nd grade &middot; share the studs equally"))
    story.append(Paragraph(
        "A big brick has many studs. If a group of friends share the studs "
        "equally, how many does each friend get? Look at the brick and divide.",
        ss["Instr"]))
    rows = []
    shirts = [BRICK_RED, BRICK_BLUE, BRICK_GREEN, BRICK_YELLOW, BRICK_ORANGE]
    from .brick_render import new_scene, draw_figure
    for idx, (brick, friends) in enumerate(problems, 1):
        total = brick.w * brick.d
        img = illus_single_brick(brick, width_in=2.2, height_in=1.3)
        fig, ax = new_scene(2.0, 1.3)
        for k in range(friends):
            draw_figure(ax, k * 2.6, 0, 0,
                        shirt=shirts[k % len(shirts)], pants=BRICK_BLACK)
        from .worksheets import scene_to_rlimage as _s2r
        people_img = _s2r(fig, ax, 2.0, 1.3)
        eq = Paragraph(
            f"<b>Problem {idx}.</b> The brick has {total} studs.<br/>"
            f"Shared with {friends} friends:<br/>"
            f"{total} &divide; {friends} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;</u> studs each", ss["Math"])
        rows.append([img, people_img, eq])
    tbl = Table(rows, colWidths=[2.2 * inch, 2.1 * inch, 2.6 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_fractions(story, ss, rng):
    problems = gen_fractions(rng)
    story.extend(page_header(
        ss, "Brick Fractions",
        "3rd grade &middot; what part of the brick is highlighted?"))
    story.append(Paragraph(
        "The studs on a brick can be split into equal parts. "
        "Each coloured plate covers one stud. How many studs are "
        "covered, and what fraction of the whole brick is covered?",
        ss["Instr"]))
    rows = []
    for idx, (w, d, hl, color) in enumerate(problems, 1):
        img = illus_fraction_brick(w, d, hl, BRICK_WHITE, color,
                                   width_in=2.4, height_in=1.4)
        total = w * d
        eq = Paragraph(
            f"<b>Problem {idx}.</b> The brick has {total} studs.<br/>"
            f"{hl} are coloured.<br/>"
            f"Fraction coloured = __ / __<br/>"
            f"<i>(then simplify if you can)</i>", ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[2.6 * inch, 4.3 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_decimals(story, ss, rng):
    problems = gen_decimals(rng)
    story.extend(page_header(
        ss, "Brick Decimals",
        "3rd grade &middot; heights and thicknesses in centimetres"))
    story.append(Paragraph(
        "For these problems, pretend one brick is <b>1.2 cm</b> tall "
        "and one plate (a thin brick) is <b>0.4 cm</b> tall. "
        "Use these numbers to work out each tower's height.", ss["Instr"]))
    rows = []
    from .brick_render import new_scene, draw_brick
    from .worksheets import scene_to_rlimage as _s2r
    for idx, (desc, stack, expr) in enumerate(problems, 1):
        fig, ax = new_scene(1.6, 1.8)
        z = 0
        for b in stack:
            draw_brick(ax, b, 0, 0, z)
            z += b.h
        img = _s2r(fig, ax, 1.6, 1.8)
        eq = Paragraph(
            f"<b>Problem {idx}.</b> {desc}.<br/>"
            f"Total height = {expr} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> cm", ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[1.8 * inch, 5.1 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_exponents(story, ss, rng):
    problems = gen_exponents(rng)
    story.extend(page_header(
        ss, "Brick Exponents",
        "4th grade &middot; cubes of bricks"))
    story.append(Paragraph(
        "A cube that is <b>n</b> bricks wide, <b>n</b> bricks deep, "
        "and <b>n</b> bricks tall contains <b>n &times; n &times; n = "
        "n<sup>3</sup></b> bricks. Look at each cube and count how many "
        "bricks it is made of.", ss["Instr"]))
    rows = []
    for idx, (side, color) in enumerate(problems, 1):
        img = illus_cube_of_bricks(side, color, width_in=1.7, height_in=1.7)
        eq = Paragraph(
            f"<b>Problem {idx}.</b> This cube is {side} &times; {side} "
            f"&times; {side}.<br/>"
            f"{side}<sup>3</sup> &nbsp; = &nbsp; {side} &times; {side} "
            f"&times; {side} &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks", ss["Math"])
        rows.append([img, eq])
    # Trailing pure-math problem: 5^n
    n5 = rng.randint(2, 3)
    rows.append([
        Paragraph("", ss["Math"]),
        Paragraph(
            f"<b>Problem {len(problems) + 1}.</b> A cube is {n5} &times; "
            f"{n5} &times; {n5}.<br/>How many bricks does it use?<br/>"
            f"{n5}<sup>3</sup> &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks",
            ss["Math"]),
    ])
    tbl = Table(rows, colWidths=[1.9 * inch, 5.0 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_variables(story, ss, rng):
    problems = gen_variables(rng)
    story.extend(page_header(
        ss, "Brick Variables",
        "5th grade &middot; letters stand in for numbers"))
    story.append(Paragraph(
        "We'll use the letter <b>x</b> to mean <i>&ldquo;the number of studs "
        "on one brick.&rdquo;</i> The value of <b>x</b> depends on which "
        "brick we are looking at. Work out each expression.", ss["Instr"]))
    rows = []
    for idx, (brick, expr, prompt) in enumerate(problems, 1):
        img = illus_single_brick(brick, width_in=2.1, height_in=1.2)
        studs = brick.w * brick.d
        eq = Paragraph(
            f"<b>Problem {idx}.</b> If x is the number of studs on this brick, "
            f"{prompt}<br/>"
            f"x = {studs}, so <b>{expr}</b> = "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"])
        rows.append([img, eq])
    tbl = Table(rows, colWidths=[2.3 * inch, 4.6 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tbl)
    story.append(PageBreak())


def page_functions(story, ss, rng):
    f = gen_functions(rng)
    story.extend(page_header(
        ss, "Brick Functions",
        "6th grade &middot; a rule that turns one number into another"))
    story.append(Paragraph(
        "A <b>function</b> is a rule. Put a number in, get a number out. "
        + f["desc"], ss["Instr"]))
    story.append(Paragraph(
        "<b>The bricks this function describes (n = 1, 2, 3, 4):</b>",
        ss["Problem"]))
    story.append(render_groups(
        [[f["bricks_for"](n)] for n in f["ns_shown"]],
        width_in=5.5, height_in=1.5, group_gap=0.35))
    story.append(Paragraph("<b>Problem 1.</b> Finish the table:",
                           ss["Problem"]))
    header_row = ["n"] + [str(n) for n in f["table_ns"]]
    value_row = ["f(n)"] + [str(v) for v in f["table_fs"]]
    t = Table([header_row, value_row],
              colWidths=[0.6 * inch] + [0.65 * inch] * len(f["table_ns"]))
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
                           "&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    pts = [(n, f["fn"](n)) for n in f["ns_shown"]]
    story.append(Paragraph(
        f"<b>Problem 3.</b> Plot the points {', '.join(str(p) for p in pts)} "
        f"on the grid below. What shape do they make?", ss["Problem"]))
    story.append(illus_xy_plane_fn([(0, 0)] + pts,
                                   width_in=3.5, height_in=2.2))
    story.append(PageBreak())


def page_multivariable(story, ss, rng):
    m = gen_multivariable(rng)
    story.extend(page_header(
        ss, "Brick Multivariable Functions",
        "7th grade &middot; a rule that takes two numbers in"))
    story.append(Paragraph(
        "A <b>multivariable function</b> takes more than one number as input. "
        "Let <b>S(w, d)</b> = <i>the number of studs on a w &times; d brick.</i>  "
        "Then S(w, d) = w &times; d. A separate function <b>V(w, d, h)</b> "
        "= <i>the volume of a w &times; d &times; h tower</i> uses three "
        "inputs: V(w, d, h) = w &times; d &times; h.", ss["Instr"]))
    story.append(Paragraph("<b>Problem 1.</b> Use S(w, d) = w &times; d.",
                           ss["Problem"]))
    for (w, d) in m["probs_S"]:
        story.append(Paragraph(
            f"&nbsp;&nbsp;S({w}, {d}) &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    story.append(render_groups([[b] for b in m["bricks"]],
                               width_in=5.5, height_in=1.6, group_gap=0.4))
    story.append(Paragraph(
        "<b>Problem 2.</b> Use V(w, d, h) = w &times; d &times; h.",
        ss["Problem"]))
    for (w, d, h) in m["probs_V"]:
        story.append(Paragraph(
            f"&nbsp;&nbsp;V({w}, {d}, {h}) &nbsp; = &nbsp; "
            f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    w, d, h = (rng.randint(2, 3), rng.randint(2, 4), rng.randint(2, 4))
    A = 2 * (w * d + w * h + d * h)
    story.append(Paragraph(
        f"<b>Problem 3.</b> The surface area of a w &times; d &times; h "
        f"brick is A(w, d, h) = 2(wd + wh + dh). Compute A({w}, {d}, {h}):",
        ss["Problem"]))
    story.append(Paragraph(
        f"&nbsp;&nbsp;A({w}, {d}, {h}) = 2({w}&middot;{d} + {w}&middot;{h} "
        f"+ {d}&middot;{h}) = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Fractals (stages vary, color randomised)
# ---------------------------------------------------------------------------
def page_fractals(story, ss, rng):
    color1 = pick_color(rng)
    color2 = pick_color(rng, exclude=[color1])
    story.extend(page_header(
        ss, "Brick Fractals",
        "6th grade &middot; shapes that repeat inside themselves"))
    story.append(Paragraph(
        "A <b>fractal</b> is a pattern that looks the same when you zoom in. "
        "The <i>Sierpinski carpet</i> starts with a 3 &times; 3 square of "
        "bricks and removes the middle. Then each of the 8 remaining squares "
        "has its own middle removed, and so on.", ss["Instr"]))
    story.append(Paragraph(
        "<b>Problem 1.</b> This is <b>stage 1</b>: a 3 &times; 3 block with "
        "the middle brick removed. Count the bricks.", ss["Problem"]))
    story.append(illus_fractal_grid(sierpinski_carpet_cells(1), color1,
                                    width_in=1.8, height_in=1.4))
    story.append(Paragraph(
        "Stage 1 bricks = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))
    story.append(Paragraph(
        "<b>Problem 2.</b> For <b>stage 2</b>, each brick from stage 1 is "
        "replaced by another stage-1 pattern. Count, or compute 8 &times; 8:",
        ss["Problem"]))
    story.append(illus_fractal_grid(sierpinski_carpet_cells(2), color2,
                                    width_in=3.0, height_in=2.0))
    story.append(Paragraph(
        "Stage 2 bricks = 8 &times; 8 = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    stage3 = rng.choice([3, 4])
    story.append(Paragraph(
        f"<b>Problem 3.</b> Each stage multiplies the bricks by 8. "
        f"How many bricks in <b>stage {stage3}</b>?", ss["Problem"]))
    story.append(Paragraph(
        f"Stage {stage3} = 8<sup>{stage3}</sup> = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))
    story.append(Paragraph(
        "<b>Problem 4.</b> Stage 1 is 3 bricks across, stage 2 is 9 across. "
        f"How wide is stage {stage3}?", ss["Problem"]))
    story.append(Paragraph(
        f"Stage {stage3} width = 3<sup>{stage3}</sup> = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks", ss["Math"]))
    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Logic (random attribute picks)
# ---------------------------------------------------------------------------
def _random_attribute_bricks(rng, n, target_color, target_studs):
    """Generate a list of n bricks with at least one matching target and
    some mix of non-matching to make the AND question meaningful."""
    from .brick_render import Brick as _B
    sizes = [(2, 2), (2, 3), (2, 4), (1, 4), (3, 2), (3, 3)]
    bricks = []
    # ensure one perfect match
    bricks.append(_B(target_studs[0], target_studs[1], 3, target_color))
    other_colors = [c for c in COLORS if c != target_color]
    for _ in range(n - 1):
        w, d = rng.choice(sizes)
        c = rng.choice(other_colors + [target_color])
        bricks.append(_B(w, d, 3, c))
    rng.shuffle(bricks)
    return bricks


def page_logic(story, ss, rng):
    story.extend(page_header(
        ss, "Brick Logic",
        "5th grade &middot; AND, OR, NOT"))
    story.append(Paragraph(
        "In logic, <b>AND</b> means both things are true. <b>OR</b> means "
        "at least one is true. <b>NOT</b> flips true and false.",
        ss["Instr"]))
    and_color = rng.choice([BRICK_RED, BRICK_BLUE, BRICK_GREEN])
    and_color_name = {BRICK_RED: "red", BRICK_BLUE: "blue",
                      BRICK_GREEN: "green"}[and_color]
    and_size = rng.choice([(2, 2), (2, 3), (3, 2)])
    and_studs = and_size[0] * and_size[1]
    bricks_1 = _random_attribute_bricks(rng, 4, and_color, and_size)
    story.append(Paragraph(
        f"<b>Problem 1 (AND).</b> Look at bricks A, B, C, D. Which is "
        f"<i>{and_color_name}</i> AND has exactly <i>{and_studs} studs</i>?",
        ss["Problem"]))
    story.append(render_groups([[b] for b in bricks_1],
                               width_in=5.5, height_in=1.1, group_gap=0.45))
    story.append(Paragraph(
        "Answer: <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> (A / B / C / D)",
        ss["Math"]))

    or_color = rng.choice([BRICK_YELLOW, BRICK_GREEN, BRICK_ORANGE])
    or_color_name = {BRICK_YELLOW: "yellow", BRICK_GREEN: "green",
                     BRICK_ORANGE: "orange"}[or_color]
    or_threshold = rng.randint(4, 6)
    bricks_2 = [Brick(2, 3, 3, or_color),
                Brick(2, 2, 3, pick_color(rng, exclude=[or_color])),
                Brick(1, 4, 3, pick_color(rng, exclude=[or_color])),
                Brick(3, 3, 3, or_color)]
    rng.shuffle(bricks_2)
    story.append(Paragraph(
        f"<b>Problem 2 (OR).</b> Which bricks are <i>{or_color_name}</i> "
        f"OR have <i>more than {or_threshold} studs</i>?", ss["Problem"]))
    story.append(render_groups([[b] for b in bricks_2],
                               width_in=5.5, height_in=1.1, group_gap=0.45))
    story.append(Paragraph(
        "Answer: <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    not_color = rng.choice([BRICK_BLUE, BRICK_RED, BRICK_ORANGE])
    not_color_name = {BRICK_BLUE: "blue", BRICK_RED: "red",
                      BRICK_ORANGE: "orange"}[not_color]
    bricks_3 = [Brick(2, 2, 3, not_color),
                Brick(2, 4, 3, not_color),
                Brick(2, 2, 3, pick_color(rng, exclude=[not_color])),
                Brick(3, 2, 3, not_color)]
    rng.shuffle(bricks_3)
    story.append(Paragraph(
        f"<b>Problem 3 (NOT).</b> Which brick is <i>NOT</i> {not_color_name}?",
        ss["Problem"]))
    story.append(render_groups([[b] for b in bricks_3],
                               width_in=5.5, height_in=1.1, group_gap=0.45))
    story.append(Paragraph("Answer: <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
                           ss["Math"]))

    op = rng.choice(["AND", "OR"])
    story.append(Paragraph(
        f"<b>Problem 4.</b> Fill in the truth table for <b>A {op} B</b>. "
        "(T = true, F = false.)", ss["Problem"]))
    data = [["A", "B", f"A {op} B"],
            ["T", "T", "___"],
            ["T", "F", "___"],
            ["F", "T", "___"],
            ["F", "F", "___"]]
    t = _Table(data, colWidths=[0.6 * inch, 0.6 * inch, 1.0 * inch])
    t.setStyle(_TableStyle([
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


# ---------------------------------------------------------------------------
# Computer Programming (random bits, loop count, and red-count list)
# ---------------------------------------------------------------------------
def page_programming(story, ss, rng):
    story.extend(page_header(
        ss, "Brick Computer Programming",
        "6th grade &middot; loops, conditions, and binary numbers"))
    story.append(Paragraph(
        "Computers use <b>binary</b>: only 0 and 1. In our bricks, "
        "<b>colored = 1</b> and <b>grey = 0</b>. "
        "They also follow <b>loops</b> (do it N times) and "
        "<b>conditions</b> (if something is true, do this).",
        ss["Instr"]))

    bits = [rng.randint(0, 1) for _ in range(4)]
    if all(b == 0 for b in bits):
        bits[rng.randint(0, 3)] = 1
    values = [8, 4, 2, 1]
    bit_color = pick_color(rng, exclude=[BRICK_GREY])
    bricks_bits = [Brick(1, 1, 3, bit_color if b else BRICK_GREY)
                   for b in bits]
    story.append(Paragraph(
        "<b>Problem 1 (binary).</b> Place values are "
        "<b>8, 4, 2, 1</b> from left to right. What number is this pattern?",
        ss["Problem"]))
    story.append(render_groups([[b] for b in bricks_bits],
                               width_in=3.0, height_in=0.9, group_gap=0.3))
    sum_expr = " + ".join(str(v * b) for v, b in zip(values, bits))
    pattern_str = " ".join(str(b) for b in bits)
    story.append(Paragraph(
        f"{pattern_str} = {sum_expr} = "
        "<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    loop_n = rng.randint(3, 6)
    loop_color = pick_color(rng)
    story.append(Paragraph(
        f"<b>Problem 2 (loop).</b> This pseudocode runs a loop "
        f"{loop_n} times, placing one brick each time:", ss["Problem"]))
    story.append(Paragraph(
        f"<font face='Courier'>for i in range({loop_n}):<br/>"
        f"&nbsp;&nbsp;&nbsp;&nbsp;place_one_brick()</font>", ss["Math"]))
    story.append(illus_stack(Brick(2, 2, 3, loop_color), count=loop_n,
                             width_in=1.2, height_in=1.8))
    story.append(Paragraph(
        "Total bricks = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    target_color = rng.choice([BRICK_RED, BRICK_BLUE, BRICK_GREEN])
    target_name = {BRICK_RED: "red", BRICK_BLUE: "blue",
                   BRICK_GREEN: "green"}[target_color]
    n_row = 5
    other_colors = [c for c in COLORS if c != target_color]
    row_colors = []
    n_target = rng.randint(2, 3)
    for i in range(n_row):
        if i < n_target:
            row_colors.append(target_color)
        else:
            row_colors.append(rng.choice(other_colors))
    rng.shuffle(row_colors)
    row_sizes = [rng.choice([(2, 2), (2, 3), (2, 4), (1, 4)])
                 for _ in range(n_row)]
    bricks_c = [Brick(w, d, 3, c) for (w, d), c in zip(row_sizes, row_colors)]
    story.append(Paragraph(
        f"<b>Problem 3 (if).</b> This pseudocode counts {target_name} bricks:",
        ss["Problem"]))
    story.append(Paragraph(
        f"<font face='Courier'>count = 0<br/>"
        f"for brick in bricks:<br/>"
        f"&nbsp;&nbsp;&nbsp;&nbsp;if brick.color == '{target_name}':<br/>"
        f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;count = count + 1"
        f"</font>", ss["Math"]))
    story.append(render_groups([[b] for b in bricks_c],
                               width_in=5.5, height_in=1.0, group_gap=0.35))
    story.append(Paragraph(
        "Final count = <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))
    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Advanced Fractals (Sierpinski triangle, Vicsek, higher-stage counts)
# ---------------------------------------------------------------------------
def page_advanced_fractals(story, ss, rng):
    c1 = pick_color(rng)
    c2 = pick_color(rng, exclude=[c1])
    c3 = pick_color(rng, exclude=[c1, c2])
    story.extend(page_header(
        ss, "Advanced Brick Fractals",
        "7th&#8211;8th grade &middot; Sierpinski triangle, Vicsek fractal, "
        "self-similarity"))
    story.append(Paragraph(
        "Some fractals replicate themselves <i>N</i> times at each step. "
        "If one stage fits inside a 3 &times; 3 parent, the Sierpinski "
        "<i>carpet</i> keeps 8 of 9 cells; the Vicsek fractal keeps only "
        "the center-plus 5 of 9. The Sierpinski <i>triangle</i> keeps 3 of "
        "4 cells in a 2 &times; 2 parent.", ss["Instr"]))

    tri_stage = rng.choice([2, 3])
    story.append(Paragraph(
        f"<b>Problem 1.</b> Here is a stage-{tri_stage} "
        f"<b>Sierpinski triangle</b> on a {2**tri_stage} &times; "
        f"{2**tri_stage} grid. Use 3<sup>n</sup> to predict the brick count.",
        ss["Problem"]))
    tri_w = 1.2 if tri_stage == 2 else 1.6
    story.append(illus_fractal_grid(
        sierpinski_triangle_cells(tri_stage), c1,
        width_in=tri_w, height_in=tri_w))
    story.append(Paragraph(
        f"Stage {tri_stage} bricks = 3<sup>{tri_stage}</sup> = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    vstage = rng.choice([1, 2])
    vn = 3 ** vstage
    story.append(Paragraph(
        f"<b>Problem 2 (Vicsek).</b> The plus-cross fractal keeps 5 of every "
        f"9 cells. Below is <b>stage {vstage}</b> on a {vn} &times; {vn} grid. "
        f"Predict the brick count.", ss["Problem"]))
    vw = 1.2 if vstage == 1 else 1.6
    story.append(illus_fractal_grid(
        vicsek_cells(vstage), c2, width_in=vw, height_in=vw))
    story.append(Paragraph(
        f"Stage {vstage} bricks = 5<sup>{vstage}</sup> = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>", ss["Math"]))

    carpet_stage = rng.choice([4, 5])
    story.append(Paragraph(
        f"<b>Problem 3.</b> The Sierpinski carpet multiplies bricks by 8 at "
        f"each stage. How many bricks in <b>stage {carpet_stage}</b>?",
        ss["Problem"]))
    story.append(Paragraph(
        f"Stage {carpet_stage} = 8<sup>{carpet_stage}</sup> = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>",
        ss["Math"]))

    width_stage = rng.choice([4, 5])
    base_n, base_kind = rng.choice([(2, "triangle"), (3, "carpet")])
    story.append(Paragraph(
        f"<b>Problem 4.</b> For the Sierpinski <b>{base_kind}</b>, each "
        f"stage is {base_n} &times; wider than the last. How wide is "
        f"<b>stage {width_stage}</b>?", ss["Problem"]))
    story.append(Paragraph(
        f"Stage {width_stage} width = {base_n}<sup>{width_stage}</sup> = "
        f"<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u> bricks",
        ss["Math"]))
    # c3 is reserved for visual parity — reference it so linter is happy
    _ = c3
    story.append(PageBreak())


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
CATEGORIES = [
    ("addition",       page_addition),
    ("subtraction",    page_subtraction),
    ("multiplication", page_multiplication),
    ("division",       page_division),
    ("fractions",      page_fractions),
    ("decimals",       page_decimals),
    ("exponents",      page_exponents),
    ("variables",      page_variables),
    ("functions",      page_functions),
    ("multivariable",  page_multivariable),
    ("fractals",       page_fractals),
    ("logic",          page_logic),
    ("programming",    page_programming),
    ("advanced_fractals", page_advanced_fractals),
]


def build(n_pages: int, seed: int) -> str:
    rng = random.Random(seed)
    ss = build_ss()
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = f"Math_Worksheets_Random_{n_pages}_{ts}.pdf"
    doc = BaseDocTemplate(
        out, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.7 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  LETTER[0] - 1.5 * inch, LETTER[1] - 1.45 * inch,
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="ws", frames=[frame], onPage=chrome)])

    # Equal distribution: every category appears (n_pages // k) times, with
    # the first (n_pages % k) categories getting one extra. Then shuffle so
    # topics are interleaved, and rotate if two in a row collide.
    k = len(CATEGORIES)
    base = n_pages // k
    extra = n_pages % k
    schedule = []
    for idx, cat in enumerate(CATEGORIES):
        schedule.extend([cat] * (base + (1 if idx < extra else 0)))
    rng.shuffle(schedule)
    # De-duplicate consecutive entries by swapping with a later non-matching
    # slot when needed.
    for i in range(1, len(schedule)):
        if schedule[i][0] == schedule[i - 1][0]:
            for j in range(i + 1, len(schedule)):
                if (schedule[j][0] != schedule[i - 1][0] and
                    (i + 1 >= len(schedule)
                     or schedule[j][0] != schedule[i + 1][0])):
                    schedule[i], schedule[j] = schedule[j], schedule[i]
                    break

    story = []
    counts = {}
    for name, fn in schedule:
        fn(story, ss, rng)
        counts[name] = counts.get(name, 0) + 1
    doc.build(story)
    print(f"wrote {out}")
    print(f"category counts: {counts}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    build(args.pages, args.seed)

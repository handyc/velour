"""
L-System grammar + 3D grid-turtle that emits studded Lego bricks.

An L-System is a rewriting system: start from an *axiom* string, apply
*production rules* to every character for a number of iterations, then hand
the resulting string to a *turtle* that interprets each character as a
drawing command.

Grammar (the turtle alphabet)
-----------------------------
    F   place a brick at current position; advance +z by one brick
    P   place a 1-plate-tall brick at current position; advance +z by one plate
    L   place a brick at current position WITHOUT advancing (leaf / petal / stud)
    W   place a 2x2 wall brick at current position; advance +z by one brick
    R   place a 1-plate roof slab at current position (no advance)
    >   step +x by one stud (no placement)
    <   step -x by one stud
    ^   step +y by one stud
    &   step -y by one stud
    [   push turtle state (position, color, shape)
    ]   pop turtle state
    {C:rrggbb}   set current color to hex rrggbb
    {S:w,d,h}    set current brick shape (width and depth in studs, height in plates)

Each L-System rule is (symbol -> replacement string). Non-production symbols
(the turtle alphabet) act as the terminal alphabet and pass through unchanged.

High-level preset generators (make_tree, make_flower, make_building,
make_person, make_hill) build a deterministic L-System + seed-based
randomisation, then run the turtle and return a list of
(Brick, (x, y, z)) placements suitable for brick_render.draw_group().

Everything is grid-aligned: x and y are integer stud positions, z is a
multiple of PLATE_H = 0.4 so placements snap to real brick heights.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from lsystem.core import Grammar

from .brick_render import (
    Brick, BRICK_H, PLATE_H,
    BRICK_RED, BRICK_BLUE, BRICK_YELLOW, BRICK_GREEN, BRICK_ORANGE,
    BRICK_WHITE, BRICK_BLACK, BRICK_GREY, BRICK_TAN, BRICK_PURPLE,
)


# ---------------------------------------------------------------------------
# Extra palette for terrain / nature (generic studded-brick colors)
# ---------------------------------------------------------------------------
BROWN       = "#6b4a2e"   # tree trunk
DARK_GREEN  = "#2d6b2a"
LIGHT_GREEN = "#76c376"
MEADOW      = "#5ea04b"   # grassy baseplate
SAND        = "#efdca2"   # desert baseplate
SEA         = "#3b7fa8"   # water baseplate
SNOW        = "#f4f7fb"   # snow baseplate
STONE_GREY  = "#b4b2ad"
DIRT        = "#8c6a45"
PINK        = "#d98bb4"
CREAM       = "#efe4c6"


Placement = tuple[Brick, tuple[float, float, float]]


# ---------------------------------------------------------------------------
# L-System core: string expansion
# ---------------------------------------------------------------------------
# The legacy Legolith `LSystem` class is now a thin facade over the shared
# `lsystem.core.Grammar` so every Velour app expands grammars identically.
# Legolith's brick alphabet still rides through untouched because Grammar
# copies unknown symbols verbatim and preserves `{…}` pragmas as literal
# terminals.
class LSystem:
    """Deterministic L-System (Legolith facade over lsystem.core.Grammar)."""

    def __init__(self, axiom: str, rules: dict[str, str], iterations: int = 3):
        self.axiom = axiom
        self.rules = rules
        self.iterations = iterations
        self._grammar = Grammar(axiom, rules, iterations=iterations)

    def expand(self) -> str:
        return self._grammar.expand()


# ---------------------------------------------------------------------------
# Turtle interpreter
# ---------------------------------------------------------------------------
@dataclass
class TurtleState:
    x: int
    y: int
    z: float
    color: str
    shape: tuple[int, int, int]   # (w, d, plates)


def _parse_braced(s: str, i: int) -> tuple[str, int]:
    j = s.index("}", i)
    return s[i + 1:j], j + 1


def run_turtle(program: str, origin=(0, 0, 0.0),
               color: str = DARK_GREEN,
               shape: tuple[int, int, int] = (1, 1, 3)) -> list[Placement]:
    """Interpret an L-System expansion as brick placements.

    Returns a list of (Brick, (x, y, z)) tuples.
    """
    st = TurtleState(origin[0], origin[1], origin[2], color, shape)
    stack: list[TurtleState] = []
    out: list[Placement] = []
    i = 0
    n = len(program)
    while i < n:
        c = program[i]
        if c == "{":
            body, i = _parse_braced(program, i)
            if body.startswith("C:"):
                st.color = "#" + body[2:]
            elif body.startswith("S:"):
                w, d, h = (int(v) for v in body[2:].split(","))
                st.shape = (w, d, h)
            continue
        w, d, h = st.shape
        if c == "F":
            out.append((Brick(w, d, h, st.color), (st.x, st.y, st.z)))
            st.z += h * PLATE_H
        elif c == "P":
            out.append((Brick(w, d, 1, st.color), (st.x, st.y, st.z)))
            st.z += PLATE_H
        elif c == "L":
            out.append((Brick(w, d, h, st.color), (st.x, st.y, st.z)))
        elif c == "W":
            out.append((Brick(2, 2, h, st.color), (st.x, st.y, st.z)))
            st.z += h * PLATE_H
        elif c == "R":
            out.append((Brick(w, d, 1, st.color), (st.x, st.y, st.z)))
        elif c == ">":
            st.x += 1
        elif c == "<":
            st.x -= 1
        elif c == "^":
            st.y += 1
        elif c == "&":
            st.y -= 1
        elif c == "[":
            stack.append(TurtleState(st.x, st.y, st.z, st.color, st.shape))
        elif c == "]":
            st = stack.pop()
        # all other characters are ignored (they were production symbols
        # that should have been expanded before reaching the turtle)
        i += 1
    return out


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def _hx(c: str) -> str:
    """Strip the leading # so a color can be embedded in {C:...}."""
    return c.lstrip("#")


# ---------------------------------------------------------------------------
# Preset generators
# ---------------------------------------------------------------------------
# Each returns a list of Placement tuples anchored at (ox, oy, oz). oz=0 means
# 'sits on top of the baseplate'. Each generator also advertises a *footprint*
# (half-extents in x and y) so the world builder can lay objects out without
# overlap.

def footprint_tree() -> tuple[int, int]:
    return 2, 2


def make_tree(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """Branching tree with three variants: bushy / conifer / blossom.

    bushy (the classic): wide ring of leaf placements around the trunk top.
        T -> {C:trunk}F...F{C:leaf}C
        C -> L[>L][<L][^L][&L][>^L][<^L][>&L][<&L]FL

    conifer: tall narrow trunk, then a shrinking cone of leaf rings.
        T -> {C:trunk}F...F{C:leaf}K
        K -> L[>L][<L][^L][&L]FL[>L][<L][^L][&L]FLL

    blossom: trunk + dense canopy plus petal-colored accents on top.
        T -> {C:trunk}F...F{C:leaf}C{C:blossom}[>L][<L][^L][&L]
    """
    variant = rng.choices(["bushy", "conifer", "blossom"], weights=[5, 3, 2])[0]
    height = rng.randint(3, 5) if variant != "conifer" else rng.randint(4, 6)
    trunk_color = BROWN
    leaf_color = rng.choice([BRICK_GREEN, DARK_GREEN, LIGHT_GREEN])
    blossom_color = rng.choice([PINK, BRICK_WHITE, BRICK_YELLOW])
    trunk_str = "{C:" + _hx(trunk_color) + "}" + "F" * height
    if variant == "bushy":
        rules = {
            "T": trunk_str + "{C:" + _hx(leaf_color) + "}C",
            "C": "L[>L][<L][^L][&L][>^L][<^L][>&L][<&L]FL",
        }
    elif variant == "conifer":
        rules = {
            "T": trunk_str + "{C:" + _hx(leaf_color) + "}K",
            "K": "L[>L][<L][^L][&L]FL[>L][<L][^L][&L]FLL",
        }
    else:  # blossom
        rules = {
            "T": (trunk_str + "{C:" + _hx(leaf_color) + "}C"
                  + "{C:" + _hx(blossom_color) + "}[>L][<L][^L][&L]"),
            "C": "L[>L][<L][^L][&L][>^L][<^L][>&L][<&L]F",
        }
    prog = LSystem("T", rules, iterations=2).expand()
    return run_turtle(prog, origin=origin)


def footprint_giant_tree() -> tuple[int, int]:
    return 4, 4


def make_giant_tree(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """Super-tall L-system tree (~10-14 brick-heights). Four variants:

        pine     — narrow 1x1 trunk + downsweeping conifer rings
        sequoia  — thick 2x2 trunk + dense layered crown
        baobab   — bulbous 2x2 trunk narrowing to twin spires
        fantasy  — twin candy-stripe trunk with arching blossom branches

    Trunks here use the LSystem-grammar/turtle pipeline so the tree-shape
    grammar stays readable; canopies use direct brick placements because
    the turtle alphabet does not (yet) speak in concentric rings.
    """
    variant = rng.choices(['pine', 'sequoia', 'baobab', 'fantasy'],
                          weights=[3, 3, 2, 2])[0]
    trunk_h = rng.randint(10, 14)
    bark = rng.choice([BROWN, '#5a3a20', '#6b4a2e', '#7a553a', '#3e2917'])
    leaf = rng.choice([BRICK_GREEN, DARK_GREEN, LIGHT_GREEN, '#1a4f1a'])
    blossom = rng.choice([PINK, BRICK_WHITE, BRICK_YELLOW, BRICK_PURPLE])

    ox, oy, oz = origin
    out: list[Placement] = []

    if variant == 'pine':
        cx, cy = ox + 1, oy + 1
        # Trunk by L-system: axiom T -> {bark}{S:1,1,3}F^h
        rules = {'T': '{C:' + _hx(bark) + '}{S:1,1,3}' + 'F' * trunk_h}
        prog = LSystem('T', rules, iterations=1).expand()
        out.extend(run_turtle(prog, origin=(cx, cy, oz)))
        # 5 conifer rings, shrinking from r=2 to r=0 + apex blossom
        rings = [(2, [(-2, 0), (2, 0), (0, -2), (0, 2),
                      (-1, -1), (1, -1), (-1, 1), (1, 1)]),
                 (1, [(-1, 0), (1, 0), (0, -1), (0, 1)]),
                 (1, [(-1, 0), (1, 0), (0, -1), (0, 1)]),
                 (0, []),
                 (0, [])]
        ring_z0 = oz + (trunk_h - 4) * BRICK_H
        for ri, (_, offsets) in enumerate(rings):
            z = ring_z0 + ri * BRICK_H
            out.append((Brick(1, 1, 3, leaf), (cx, cy, z)))
            for dx, dy in offsets:
                out.append((Brick(1, 1, 3, leaf), (cx + dx, cy + dy, z)))
        out.append((Brick(1, 1, 1, blossom),
                    (cx, cy, oz + (trunk_h + 5) * BRICK_H)))

    elif variant == 'sequoia':
        # 2x2 thick trunk
        rules = {'T': '{C:' + _hx(bark) + '}{S:2,2,3}' + 'F' * trunk_h}
        prog = LSystem('T', rules, iterations=1).expand()
        out.extend(run_turtle(prog, origin=(ox + 1, oy + 1, oz)))
        cz = oz + trunk_h * BRICK_H
        out.append((Brick(4, 4, 3, leaf), (ox, oy, cz)))
        out.append((Brick(4, 4, 3, leaf), (ox, oy, cz + BRICK_H)))
        out.append((Brick(3, 3, 3, leaf), (ox, oy, cz + 2 * BRICK_H)))
        out.append((Brick(2, 2, 3, leaf),
                    (ox + 1, oy + 1, cz + 3 * BRICK_H)))
        for dx, dy in [(0, 0), (3, 0), (0, 3), (3, 3), (1, 1), (2, 2)]:
            out.append((Brick(1, 1, 1, blossom),
                        (ox + dx, oy + dy, cz + 4 * BRICK_H)))

    elif variant == 'baobab':
        # Lower trunk: bulbous 2x2; upper trunk: twin 1x1 spires
        lower = max(3, trunk_h - 5)
        rules_lo = {'L': '{C:' + _hx(bark) + '}{S:2,2,3}' + 'F' * lower}
        out.extend(run_turtle(
            LSystem('L', rules_lo, iterations=1).expand(),
            origin=(ox + 1, oy + 1, oz),
        ))
        # Twin spires
        spire_h = trunk_h - lower
        rules_sp = {'S': '{C:' + _hx(bark) + '}{S:1,1,3}' + 'F' * spire_h}
        spire_z = oz + lower * BRICK_H
        prog = LSystem('S', rules_sp, iterations=1).expand()
        out.extend(run_turtle(prog, origin=(ox + 1, oy + 1, spire_z)))
        out.extend(run_turtle(prog, origin=(ox + 2, oy + 2, spire_z)))
        # Wide flat crown
        cz = oz + trunk_h * BRICK_H
        for dx, dy in [(0, 1), (3, 1), (1, 0), (1, 3), (0, 2), (3, 2),
                       (2, 0), (2, 3)]:
            for k in range(2):
                out.append((Brick(1, 1, 3, leaf),
                            (ox + dx, oy + dy, cz + k * BRICK_H)))
        out.append((Brick(2, 2, 3, leaf),
                    (ox + 1, oy + 1, cz + BRICK_H)))
        for dx, dy in [(0, 1), (3, 2), (2, 0), (1, 3)]:
            out.append((Brick(1, 1, 1, blossom),
                        (ox + dx, oy + dy, cz + 2 * BRICK_H)))

    else:  # fantasy
        c1, c2 = bark, '#a04030'
        # Twin candy-stripe trunk via two passes with alternating colors
        for k in range(trunk_h):
            color = c1 if (k % 2 == 0) else c2
            rules = {'T': '{C:' + _hx(color) + '}{S:1,1,3}F'}
            prog = LSystem('T', rules, iterations=1).expand()
            out.extend(run_turtle(prog,
                                  origin=(ox + 1, oy + 1, oz + k * BRICK_H)))
            out.extend(run_turtle(prog,
                                  origin=(ox + 2, oy + 2, oz + k * BRICK_H)))
        cz = oz + trunk_h * BRICK_H
        # Arching corner branches
        for px, py in [(0, 0), (3, 0), (0, 3), (3, 3)]:
            for k in range(2):
                out.append((Brick(1, 1, 3, leaf),
                            (ox + px, oy + py, cz + k * BRICK_H)))
            out.append((Brick(1, 1, 1, blossom),
                        (ox + px, oy + py, cz + 2 * BRICK_H)))
        out.append((Brick(2, 2, 3, leaf),
                    (ox + 1, oy + 1, cz + BRICK_H)))
        out.append((Brick(2, 2, 1, blossom),
                    (ox + 1, oy + 1, cz + 2 * BRICK_H)))

    return out


def footprint_flower() -> tuple[int, int]:
    return 1, 1


def make_flower(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """Three flower variants: cross / ring / spire.

    cross:  stem + 4 petals in a plus + center
    ring:   stem + 8 petals at cardinals and diagonals
    spire:  tall stem + stacked 3-petal layers (foxglove / hollyhock-ish)
    """
    variant = rng.choices(["cross", "ring", "spire"], weights=[5, 3, 2])[0]
    stem_h = rng.randint(2, 4)
    petal_color = rng.choice([PINK, BRICK_RED, BRICK_YELLOW, BRICK_ORANGE,
                              BRICK_PURPLE, BRICK_WHITE, BRICK_BLUE])
    center_color = rng.choice([BRICK_YELLOW, BRICK_ORANGE, BRICK_WHITE])
    stem_color = rng.choice([DARK_GREEN, BRICK_GREEN])
    stem_str = ("{S:1,1,1}{C:" + _hx(stem_color) + "}" + "P" * stem_h
                + "{C:" + _hx(petal_color) + "}")
    if variant == "cross":
        body = "L[>L][<L][^L][&L]{C:" + _hx(center_color) + "}F"
    elif variant == "ring":
        body = ("L[>L][<L][^L][&L][>^L][<^L][>&L][<&L]"
                "{C:" + _hx(center_color) + "}F")
    else:  # spire
        petal2 = rng.choice([PINK, BRICK_WHITE, BRICK_PURPLE])
        body = ("L[>L][<L][^L][&L]F"
                "{C:" + _hx(petal2) + "}L[>L][<L][^L][&L]F"
                "{C:" + _hx(center_color) + "}F")
    rules = {"X": stem_str + body}
    return run_turtle(LSystem("X", rules, iterations=1).expand(),
                      origin=origin)


def footprint_building(rng: random.Random) -> tuple[int, int, int, int]:
    """Return (w, d, floors, _reserved). Called before placement so the world
    generator can pre-reserve baseplate cells. Uses rng but in the same order
    that make_building will, so geometry stays consistent if re-seeded."""
    w = rng.randint(3, 7)
    d = rng.randint(3, 7)
    floors = rng.randint(2, 6)
    return w, d, floors, 0


def make_building(rng: random.Random, origin=(0, 0, 0.0),
                  dims: tuple[int, int, int] | None = None) -> list[Placement]:
    """Rectangular studded building.

    L-System at the *floor* level:
        axiom  B
        B -> W{n}R                       (n floors of walls, then a roof)

    Each W is expanded by the turtle into a perimeter of 1x1 bricks at the
    current z, then z advances by one brick height. R places a flat roof
    plate covering the footprint.
    """
    if dims is None:
        w, d, floors, _ = footprint_building(rng)
    else:
        w, d, floors = dims
    wall_color = rng.choice([BRICK_TAN, BRICK_WHITE, STONE_GREY, CREAM, SAND])
    roof_color = rng.choice([BRICK_RED, BRICK_BLUE, BRICK_BLACK, BRICK_GREEN,
                             BRICK_ORANGE])
    door_color = BRICK_BLACK
    window_color = rng.choice([BRICK_BLUE, BRICK_WHITE, BRICK_YELLOW])

    rules = {"B": "W" * floors + "R"}
    prog = LSystem("B", rules, iterations=1).expand()

    # We drive the perimeter construction procedurally rather than encoding
    # every perimeter stud as a turtle symbol — that would produce unwieldy
    # strings for 4x5 buildings.
    ox, oy, oz = origin
    out: list[Placement] = []
    door_x = ox + w // 2
    door_y = oy
    window_positions = set()
    if floors >= 2:
        for fl in range(1, floors):
            wx = ox + max(1, w // 2 - 1)
            wy = oy
            window_positions.add((wx, wy, fl))

    for idx, sym in enumerate(prog):
        if sym == "W":
            fz = oz + idx * BRICK_H
            for i in range(w):
                for j in range(d):
                    if not (i == 0 or i == w - 1 or j == 0 or j == d - 1):
                        continue
                    c = wall_color
                    if (ox + i, oy + j) == (door_x, door_y) and idx == 0:
                        c = door_color
                    elif (ox + i, oy + j, idx) in window_positions:
                        c = window_color
                    out.append((Brick(1, 1, 3, c), (ox + i, oy + j, fz)))
        elif sym == "R":
            fz = oz + idx * BRICK_H
            out.append((Brick(w, d, 1, roof_color), (ox, oy, fz)))
    # Optional chimney or antenna on the roof (rule-extension): 30% chimney,
    # 20% antenna, 50% bare.
    roof_z = oz + floors * BRICK_H + PLATE_H
    deco = rng.random()
    if deco < 0.30:
        cx = ox + w - 2
        cy = oy + 1
        out.append((Brick(1, 1, 3, BRICK_BLACK), (cx, cy, roof_z)))
        out.append((Brick(1, 1, 3, BRICK_BLACK),
                    (cx, cy, roof_z + BRICK_H)))
    elif deco < 0.50:
        cx = ox + w // 2
        cy = oy + d // 2
        out.append((Brick(1, 1, 1, BRICK_GREY),
                    (cx, cy, roof_z)))
        out.append((Brick(1, 1, 1, BRICK_GREY),
                    (cx, cy, roof_z + PLATE_H)))
        out.append((Brick(1, 1, 1, BRICK_RED),
                    (cx, cy, roof_z + 2 * PLATE_H)))
    return out


def footprint_person() -> tuple[int, int]:
    return 2, 1


def make_person(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """Blocky brick-person: legs, torso, head, optional hat.

    Axiom:
        P -> {pants}{S:1,1,3}F{S:1,1,3}F{torso}{S:2,1,3}F{skin}{S:1,1,3}F

    The two legs are placed by stepping once before the second F:
        P -> {pants}F>F<{shirt}F{skin}F[hat? : {C:...}P]
    """
    shirt = rng.choice([BRICK_RED, BRICK_BLUE, BRICK_GREEN, BRICK_YELLOW,
                        BRICK_ORANGE, BRICK_PURPLE])
    pants = rng.choice([BRICK_BLUE, BRICK_BLACK, BRICK_TAN, BRICK_RED])
    skin = BRICK_TAN
    has_hat = rng.random() < 0.5
    hat = rng.choice([BRICK_RED, BRICK_BLUE, BRICK_GREEN, BRICK_YELLOW,
                      BRICK_BLACK, BRICK_WHITE])

    # Two legs (1x1x3), torso (2x1x3), head (1x1x3, studless hidden — we'll
    # render it as a normal 1x1 brick tinted skin color; the higher-fidelity
    # draw_figure() is used in brick_render tests, but for worlds we keep
    # people compact and grid-aligned).
    parts: list[Placement] = []
    ox, oy, oz = origin
    parts.append((Brick(1, 1, 3, pants), (ox, oy, oz)))
    parts.append((Brick(1, 1, 3, pants), (ox + 1, oy, oz)))
    parts.append((Brick(2, 1, 3, shirt), (ox, oy, oz + BRICK_H)))
    parts.append((Brick(1, 1, 3, skin), (ox, oy, oz + 2 * BRICK_H)))
    if has_hat:
        parts.append((Brick(1, 1, 1, hat), (ox, oy, oz + 3 * BRICK_H)))
    return parts


def footprint_hill() -> tuple[int, int]:
    return 4, 4


def make_hill(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """Stepped hill / terrain feature: stacked concentric squares.

    Axiom H -> H1 H2 H3 where each Hn is a shrinking square plate.
    """
    base = rng.choice([4, 5])
    color = rng.choice([STONE_GREY, BRICK_GREEN, DARK_GREEN, SAND, DIRT])
    out: list[Placement] = []
    ox, oy, oz = origin
    size = base
    for k in range(base // 2 + 1):
        if size < 1:
            break
        out.append((Brick(size, size, 1, color),
                    (ox + k, oy + k, oz + k * PLATE_H)))
        size -= 2
    return out


def footprint_lamp() -> tuple[int, int]:
    return 1, 1


def make_lamp(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """Tall post lamp: 1x1 grey post + glowing yellow/white cap.

    Axiom:  P -> {post}F F F F {bulb} L [>L][<L][^L][&L]
    """
    post_color = rng.choice([BRICK_BLACK, BRICK_GREY, STONE_GREY])
    bulb_color = rng.choice([BRICK_YELLOW, BRICK_WHITE, BRICK_ORANGE])
    post_h = rng.randint(3, 5)
    rules = {
        "P": ("{S:1,1,3}{C:" + _hx(post_color) + "}" + "F" * post_h
              + "{S:1,1,1}{C:" + _hx(bulb_color) + "}F[>L][<L][^L][&L]"),
    }
    return run_turtle(LSystem("P", rules, iterations=1).expand(),
                      origin=origin)


def footprint_rock() -> tuple[int, int]:
    return 2, 2


def make_rock(rng: random.Random, origin=(0, 0, 0.0)) -> list[Placement]:
    """A small mossy rock cluster: 2x2 base, 1x1 cap."""
    base_color = rng.choice([STONE_GREY, BRICK_GREY, DIRT])
    cap_color = rng.choice([STONE_GREY, BRICK_GREY])
    moss = rng.random() < 0.3
    out: list[Placement] = []
    ox, oy, oz = origin
    out.append((Brick(2, 2, 1, base_color), (ox, oy, oz)))
    out.append((Brick(1, 1, 3, cap_color), (ox, oy, oz + PLATE_H)))
    if moss:
        out.append((Brick(1, 1, 1, DARK_GREEN),
                    (ox + 1, oy + 1, oz + PLATE_H)))
    return out


# ---------------------------------------------------------------------------
# Registry for world builders
# ---------------------------------------------------------------------------
Generator = Callable[[random.Random, tuple[int, int, float]], list[Placement]]

GENERATORS: dict[str, Generator] = {
    "tree":        make_tree,
    "giant_tree":  make_giant_tree,
    "flower":      make_flower,
    "building":    make_building,
    "person":      make_person,
    "hill":        make_hill,
    "lamp":        make_lamp,
    "rock":        make_rock,
}


# ---------------------------------------------------------------------------
# Library spec -> placements
# ---------------------------------------------------------------------------
def make_from_spec(spec: dict, origin=(0, 0, 0.0)) -> list[Placement]:
    """Render a LegoModel spec dict to brick placements.

    ``spec`` keys:
        axiom        : str
        rules        : dict[str, str]
        iterations   : int
        init_color   : '#rrggbb'
        init_shape   : (w, d, plates)
    """
    prog = LSystem(
        spec["axiom"], spec.get("rules", {}),
        iterations=int(spec.get("iterations", 2)),
    ).expand()
    return run_turtle(
        prog, origin=origin,
        color=spec.get("init_color", "#888888"),
        shape=tuple(spec.get("init_shape", (1, 1, 3))),
    )

FOOTPRINTS: dict[str, Callable] = {
    "tree":        footprint_tree,
    "giant_tree":  footprint_giant_tree,
    "flower":      footprint_flower,
    "person":      footprint_person,
    "hill":        footprint_hill,
    "lamp":        footprint_lamp,
    "rock":        footprint_rock,
    # building footprint is rng-dependent; handled specially in worlds.py
}

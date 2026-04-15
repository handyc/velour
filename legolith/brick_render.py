"""
Generic studded-brick isometric renderer.

- Uses only matplotlib + numpy (no 3D engine).
- The patent on the basic stud-and-tube brick (US 3,005,282) expired in 1988;
  generic rectangular studded bricks are not protected. This module
  deliberately does NOT mimic LEGO-specific trade dress (no LEGO logos on
  studs, no LEGO minifigure shape, no LEGO character face prints).
- The "figure" here is a blocky stacked-brick person with a generic round
  head and a generic smile; distinct from a LEGO minifigure.

Coordinate system:
  x = width  (studs,   +x toward back-right on page)
  y = depth  (studs,   +y toward back-left  on page)
  z = height (plates,  +z up)

Units:
  1 stud   = 1.0 in x/y
  1 plate  = 0.4 in z   (a "brick" is 3 plates tall = 1.2)
  stud top-diameter = 0.6, stud height = 0.2 plate units
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection

from reportlab.platypus import Image as RLImage


# ---------------------------------------------------------------------------
# Isometric projection
# ---------------------------------------------------------------------------
_COS30 = math.cos(math.radians(30))
_SIN30 = math.sin(math.radians(30))


def iso(x: float, y: float, z: float) -> tuple[float, float]:
    """Project a 3D point to 2D using classic 30-degree isometric.

    +x projects up-and-right; +y projects up-and-left; +z straight up.
    The near ('front') vertex of a unit cube at the origin is (0,0,0).
    """
    u = (x - y) * _COS30
    v = (x + y) * _SIN30 + z
    return (u, v)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        *[max(0, min(255, int(c * 255))) for c in rgb])


def shade(color: str, factor: float) -> str:
    """Multiply each RGB channel by factor (clamped)."""
    r, g, b = _hex_to_rgb(color)
    return _rgb_to_hex((r * factor, g * factor, b * factor))


# Palette tuned toward the classic studded-brick reference colors
# (approximate Bricklink 'Bright' family; generic, not LEGO-specific).
BRICK_RED    = "#d01712"   # bright red
BRICK_BLUE   = "#0a6fc2"   # bright blue
BRICK_YELLOW = "#f5cd30"   # bright yellow
BRICK_GREEN  = "#4b9b3f"   # bright green
BRICK_ORANGE = "#fb8a18"   # bright orange
BRICK_WHITE  = "#ffffff"   # pure white
BRICK_BLACK  = "#1b1d1f"
BRICK_GREY   = "#9ba09d"   # medium stone grey
BRICK_TAN    = "#e4cd9e"   # tan — head of the blocky figure
BRICK_PURPLE = "#923978"


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
# Canonical LDraw ratios (1 LDU = 0.4 mm; stud pitch = 20 LDU = 8.0 mm):
#   brick height  24 LDU / 20 = 1.2
#   plate height   8 LDU / 20 = 0.4
#   stud diameter 12 LDU / 20 = 0.6   (radius 0.3)
#   stud height    4 LDU / 20 = 0.2
PLATE_H = 0.4
BRICK_H = 1.2
STUD_R = 0.30
STUD_H = 0.20
EDGE = "#2a2a2a"
EDGE_LW = 0.4


# ---------------------------------------------------------------------------
# Primitive drawing
# ---------------------------------------------------------------------------
def _face(ax, pts3d, color, edge=EDGE, lw=EDGE_LW):
    pts = [iso(*p) for p in pts3d]
    ax.add_patch(Polygon(pts, closed=True, facecolor=color,
                         edgecolor=edge, linewidth=lw, joinstyle="miter"))


def _ring(cx, cy, cz, r, n=28):
    angs = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return [(cx + r * math.cos(a), cy + r * math.sin(a), cz) for a in angs]


def _draw_stud(ax, cx, cy, z_base, top_color, side_color):
    """Stud sitting on a brick top at (cx, cy, z_base)."""
    # Visible side half: normals (cos a, sin a) facing -x and -y
    # (front half of cylinder). Derive: viewer direction is roughly (-1,-1,+) in
    # xy plane; a face is visible if its normal . viewer_dir > 0.
    # Normal = (cos a, sin a, 0). Viewer = (-1, -1, 0) / sqrt(2).
    # Dot > 0 when -cos a - sin a > 0, i.e. cos a + sin a < 0,
    # i.e. a in (3*pi/4, 7*pi/4).
    vis_angs = np.linspace(3 * np.pi / 4, 7 * np.pi / 4, 18)
    bottom = [(cx + STUD_R * math.cos(a), cy + STUD_R * math.sin(a), z_base)
              for a in vis_angs]
    top = [(cx + STUD_R * math.cos(a), cy + STUD_R * math.sin(a),
            z_base + STUD_H) for a in vis_angs]
    # Wall polygon: bottom forward + top reversed
    wall = [iso(*p) for p in bottom] + [iso(*p) for p in reversed(top)]
    ax.add_patch(Polygon(wall, closed=True, facecolor=side_color,
                         edgecolor=EDGE, linewidth=0.25))
    # Top ellipse (full ring)
    top_full = _ring(cx, cy, z_base + STUD_H, STUD_R)
    pts = [iso(*p) for p in top_full]
    ax.add_patch(Polygon(pts, closed=True, facecolor=top_color,
                         edgecolor=EDGE, linewidth=0.25))


# ---------------------------------------------------------------------------
# Bricks
# ---------------------------------------------------------------------------
@dataclass
class Brick:
    w: int          # studs in x
    d: int          # studs in y
    plates: int = 3 # height in plate-units; 3 = brick, 1 = plate
    color: str = BRICK_RED
    studs: bool = True

    @property
    def h(self) -> float:
        return self.plates * PLATE_H


def draw_brick(ax, brick: Brick, x0=0.0, y0=0.0, z0=0.0):
    """Draw a brick with its near-bottom corner at (x0, y0, z0)."""
    w, d, h = brick.w, brick.d, brick.h
    c_top = brick.color
    c_r = shade(brick.color, 0.82)   # face at y = y0 (front-right on page)
    c_l = shade(brick.color, 0.65)   # face at x = x0 (front-left on page)

    # Draw back faces first (painter order). For a single brick the three
    # visible faces don't overlap in their interiors, but we render in the
    # order left, right, top so that edges meet cleanly on the silhouette.
    front_left = [
        (x0, y0, z0), (x0, y0 + d, z0),
        (x0, y0 + d, z0 + h), (x0, y0, z0 + h),
    ]
    front_right = [
        (x0, y0, z0), (x0 + w, y0, z0),
        (x0 + w, y0, z0 + h), (x0, y0, z0 + h),
    ]
    top = [
        (x0, y0, z0 + h), (x0 + w, y0, z0 + h),
        (x0 + w, y0 + d, z0 + h), (x0, y0 + d, z0 + h),
    ]
    _face(ax, front_left, c_l)
    _face(ax, front_right, c_r)
    _face(ax, top, c_top)

    if brick.studs:
        # Draw studs in back-to-front order so front studs paint over back ones
        # (near-corner is small x+y; far is large). Iterate from large to small.
        order = []
        for i in range(brick.w):
            for j in range(brick.d):
                order.append((i, j))
        order.sort(key=lambda ij: -(ij[0] + ij[1]))
        for i, j in order:
            cx = x0 + i + 0.5
            cy = y0 + j + 0.5
            _draw_stud(ax, cx, cy, z0 + h, c_top, c_r)


def draw_group(ax, bricks_with_pos):
    """Draw a group of (brick, (x,y,z)) tuples in correct painter order.

    Back-to-front ordering by (x+y+z) so that near bricks paint over far ones.
    """
    items = list(bricks_with_pos)
    items.sort(key=lambda bp: (bp[1][0] + bp[1][1] + bp[1][2]))
    for brick, (x, y, z) in items:
        draw_brick(ax, brick, x, y, z)


# ---------------------------------------------------------------------------
# Blocky figure (NOT a LEGO minifigure — generic brick-person)
# ---------------------------------------------------------------------------
def draw_figure(ax, x0=0.0, y0=0.0, z0=0.0,
                shirt=BRICK_BLUE, pants=BRICK_RED,
                skin=BRICK_TAN, hat=None):
    """
    A generic blocky brick-person:
      - Two 1x1 leg bricks (side by side)
      - A 2x1 body brick on top
      - A 1x1 cube head (no stud on head)
      - Optional 1x1 plate 'hat'
      - A simple smile face on the front of the head (no LEGO-style print)

    Footprint: 2 x 1 studs, approx 3.5 units tall.
    """
    # Legs: two 1x1 bricks at (x0, y0) and (x0+1, y0)
    draw_brick(ax, Brick(w=1, d=1, plates=3, color=pants), x0, y0, z0)
    draw_brick(ax, Brick(w=1, d=1, plates=3, color=pants), x0 + 1, y0, z0)
    # Body: 2x1 brick sitting on top of legs
    z1 = z0 + 3 * PLATE_H
    draw_brick(ax, Brick(w=2, d=1, plates=3, color=shirt), x0, y0, z1)
    # Head: a studless 1x1 cube centered on body. We render it as a 1x1 brick
    # with studs=False and height = 1 (≈ cube).
    z2 = z1 + 3 * PLATE_H
    head_color = skin
    # Head is centered over the body: body is 2 studs wide, head is 1, so
    # offset x by 0.5. Head size: 1 x 1 x 1.
    head_brick = Brick(w=1, d=1, plates=3, color=head_color, studs=False)
    # Custom draw for exact cube height (3 plates ≈ 1.2); close enough to a
    # 1-unit head.
    draw_brick(ax, head_brick, x0 + 0.5, y0, z2)
    # Face on the front-right face (at y = y0, head spans x in [0.5, 1.5]).
    # Front-right face in 2D: the quad with corners at
    #   iso(x0+0.5, y0, z2), iso(x0+1.5, y0, z2),
    #   iso(x0+1.5, y0, z2+1.2), iso(x0+0.5, y0, z2+1.2).
    _draw_face(ax, x0 + 0.5, y0, z2, width=1.0, height=1.2)

    # Optional hat: a 1x1 plate on top of the head.
    if hat is not None:
        draw_brick(ax, Brick(w=1, d=1, plates=1, color=hat),
                   x0 + 0.5, y0, z2 + 1.2)


def _draw_face(ax, x0, y0, z0, width, height):
    """Draw two eye dots and a smile on the front-right face of the head.

    Face coordinates are in the y = y0 plane, spanning x in [x0, x0+width]
    and z in [z0, z0+height].
    """
    # Eye dots
    eye_z = z0 + 0.75 * height
    for ex in (x0 + 0.32 * width, x0 + 0.68 * width):
        cx2d, cy2d = iso(ex, y0, eye_z)
        ax.add_patch(plt.Circle((cx2d, cy2d), 0.06,
                                color=EDGE, linewidth=0))
    # Smile: a small arc. Parameterize in face coords, project point-by-point.
    smile_z = z0 + 0.35 * height
    xs = np.linspace(x0 + 0.30 * width, x0 + 0.70 * width, 9)
    ys_curve = [-0.09 * math.sin(math.pi * ((x - xs[0]) / (xs[-1] - xs[0])))
                for x in xs]
    pts = [iso(x, y0, smile_z + dy) for x, dy in zip(xs, ys_curve)]
    # Draw as a thin line
    for i in range(len(pts) - 1):
        ax.plot([pts[i][0], pts[i + 1][0]], [pts[i][1], pts[i + 1][1]],
                color=EDGE, linewidth=1.2, solid_capstyle="round")


# ---------------------------------------------------------------------------
# High-level: render a scene to a PNG buffer / RLImage flowable
# ---------------------------------------------------------------------------
def new_scene(width_in: float, height_in: float, dpi: int = 220):
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=dpi)
    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig, ax


def scene_to_rlimage(fig, ax, width_in: float, height_in: float,
                     pad: float = 0.1) -> RLImage:
    # Autoscale to content, add a margin, then pad the axes to the figsize
    # aspect ratio so the saved raster is never non-uniformly scaled when
    # placed into the PDF at (width_in, height_in).
    from PIL import Image
    ax.relim()
    ax.autoscale_view()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    content_w = (x1 - x0) * (1 + pad)
    content_h = (y1 - y0) * (1 + pad)
    target_aspect = width_in / height_in
    content_aspect = content_w / max(content_h, 1e-6)
    if content_aspect > target_aspect:
        # content wider than box: pad height to match
        content_h = content_w / target_aspect
    else:
        content_w = content_h * target_aspect
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    ax.set_xlim(cx - content_w / 2, cx + content_w / 2)
    ax.set_ylim(cy - content_h / 2, cy + content_h / 2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=220)
    plt.close(fig)
    buf.seek(0)
    # Verify aspect and wrap; the raster now matches figsize aspect exactly.
    img = Image.open(buf)
    w_px, h_px = img.size
    raster_aspect = w_px / h_px
    # Fit into the box while preserving aspect (shrink, never stretch).
    if raster_aspect > target_aspect:
        out_w = width_in
        out_h = width_in / raster_aspect
    else:
        out_h = height_in
        out_w = height_in * raster_aspect
    buf.seek(0)
    return RLImage(buf, width=out_w * 72, height=out_h * 72)


def render_bricks(bricks_with_pos, width_in: float, height_in: float,
                  dpi: int = 220) -> RLImage:
    """Convenience: render a list of (Brick, (x,y,z)) as a flowable image."""
    fig, ax = new_scene(width_in, height_in, dpi=dpi)
    draw_group(ax, bricks_with_pos)
    return scene_to_rlimage(fig, ax, width_in, height_in)


def render_row(bricks: list[Brick], width_in: float, height_in: float,
               gap: float = 0.3) -> RLImage:
    """Render a horizontal row of bricks (left-to-right along -y).

    Each brick placed with increasing y-offset so that it appears to the
    right of the previous one on the page (since +y goes up-and-LEFT, we
    want -y for 'right', i.e. decreasing y). We simulate that by offsetting
    in x instead: +x goes up-and-RIGHT on page, so bricks placed with
    increasing x end up in a diagonal-up-right row. That reads as a row
    going 'into the page' from the viewer's perspective.

    To make a horizontal row that reads naturally on a flat page, we just
    render each brick in its own subplot-column... or, easier: place them
    all at the same y=z=0 and step x forward. The iso projection then gives
    a staircase-looking row. For a true horizontal row on the page we need
    to post-arrange individual renders side by side.
    """
    # Render each brick separately, then compose side-by-side.
    imgs = []
    per_w = (width_in - gap * (len(bricks) - 1)) / max(len(bricks), 1)
    for b in bricks:
        fig, ax = new_scene(per_w, height_in)
        draw_brick(ax, b, 0, 0, 0)
        imgs.append(_fig_to_rgba(fig, ax, per_w, height_in))
    # Composite
    total_w_px = int(width_in * 220)
    total_h_px = int(height_in * 220)
    canvas = np.ones((total_h_px, total_w_px, 4), dtype=np.uint8)
    canvas[..., 3] = 0
    x_cursor = 0
    gap_px = int(gap * 220)
    for im in imgs:
        h, w = im.shape[:2]
        # Vertically center
        y_off = (total_h_px - h) // 2
        x_off = x_cursor
        # Paste
        h2 = min(h, total_h_px - y_off)
        w2 = min(w, total_w_px - x_off)
        canvas[y_off:y_off + h2, x_off:x_off + w2] = im[:h2, :w2]
        x_cursor += w + gap_px
    # Encode
    from PIL import Image
    img = Image.fromarray(canvas, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return RLImage(buf, width=width_in * 72, height=height_in * 72)


def render_groups(groups: list[list["Brick"]], width_in: float,
                  height_in: float, inner_gap: float = 0.15,
                  group_gap: float = 0.55) -> RLImage:
    """Render several groups of bricks. Each brick gets its own panel so there
    is no iso-projection overlap. Gaps inside a group are small; gaps between
    groups are larger so the groups read as distinct collections."""
    from PIL import Image
    flat: list[tuple["Brick", bool]] = []  # (brick, is_group_start)
    for g_idx, g in enumerate(groups):
        for b_idx, b in enumerate(g):
            flat.append((b, b_idx == 0 and g_idx > 0))
    if not flat:
        fig, ax = new_scene(width_in, height_in)
        return scene_to_rlimage(fig, ax, width_in, height_in)
    n = len(flat)
    n_inner_gaps = n - 1 - sum(1 for _, s in flat if s)
    n_group_gaps = sum(1 for _, s in flat if s)
    total_gap = n_inner_gaps * inner_gap + n_group_gaps * group_gap
    per_w = (width_in - total_gap) / n
    per_w = max(per_w, 0.3)
    imgs = []
    for b, _ in flat:
        fig, ax = new_scene(per_w, height_in)
        draw_brick(ax, b, 0, 0, 0)
        imgs.append(_fig_to_rgba(fig, ax, per_w, height_in))
    total_w_px = int(width_in * 220)
    total_h_px = int(height_in * 220)
    canvas = np.zeros((total_h_px, total_w_px, 4), dtype=np.uint8)
    x_cursor = 0
    for (b, is_group_start), im in zip(flat, imgs):
        if x_cursor > 0:
            gap_px = int((group_gap if is_group_start else inner_gap) * 220)
            x_cursor += gap_px
        h, w = im.shape[:2]
        y_off = max(0, (total_h_px - h) // 2)
        x_off = x_cursor
        h2 = min(h, total_h_px - y_off)
        w2 = min(w, total_w_px - x_off)
        if w2 > 0 and h2 > 0:
            canvas[y_off:y_off + h2, x_off:x_off + w2] = im[:h2, :w2]
        x_cursor += w
    img = Image.fromarray(canvas, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return RLImage(buf, width=width_in * 72, height=height_in * 72)


def _fig_to_rgba(fig, ax, width_in, height_in):
    # Fit content to the exact figsize, centered, so the returned raster is
    # exactly (width_in * dpi, height_in * dpi) pixels. This is required for
    # render_groups's composite math to tile panels predictably.
    ax.relim()
    ax.autoscale_view()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    content_w = x1 - x0
    content_h = y1 - y0
    aspect = width_in / height_in
    content_aspect = content_w / max(content_h, 1e-6)
    pad_frac = 0.08
    if content_aspect > aspect:
        target_w = content_w * (1 + pad_frac)
        target_h = target_w / aspect
    else:
        target_h = content_h * (1 + pad_frac)
        target_w = target_h * aspect
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    ax.set_xlim(cx - target_w / 2, cx + target_w / 2)
    ax.set_ylim(cy - target_h / 2, cy + target_h / 2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=220)
    plt.close(fig)
    buf.seek(0)
    from PIL import Image
    img = np.array(Image.open(buf).convert("RGBA"))
    return img


# ---------------------------------------------------------------------------
# A quick self-test when run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fig, ax = new_scene(5, 3, dpi=180)
    # A staircase of bricks demonstrating sizes
    draw_brick(ax, Brick(1, 1, 3, BRICK_RED), 0, 0, 0)
    draw_brick(ax, Brick(1, 2, 3, BRICK_BLUE), 2, 0, 0)
    draw_brick(ax, Brick(2, 2, 3, BRICK_YELLOW), 5, 0, 0)
    draw_brick(ax, Brick(2, 3, 3, BRICK_GREEN), 8, 0, 0)
    draw_brick(ax, Brick(2, 4, 1, BRICK_ORANGE), 11, 0, 0)  # a plate
    draw_figure(ax, 16, 0, 0, shirt=BRICK_GREEN, pants=BRICK_BLUE,
                hat=BRICK_RED)
    ax.relim(); ax.autoscale_view()
    fig.savefig("_preview/brick_selftest.png", dpi=220, bbox_inches="tight")
    print("wrote _preview/brick_selftest.png")

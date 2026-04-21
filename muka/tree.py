"""Labelled-bracket syntactic tree — parser + tidy SVG renderer.

Input syntax is the Chomsky-style notation widely used in
introductory syntax classes:

    [S [NP nama] [VP [NP tika] [V gupe]]]

Every node is `[LABEL child child ...]`. A child is either another
bracketed node or a bare token (= terminal / leaf). Tokens may
contain apostrophes (for Konso glottal stop) and hyphens (for
morpheme segmentation). Whitespace between tokens is irrelevant.

A terminal token may carry an optional romanization / transliteration
after a `|` separator — e.g. `你|nǐ`, `食べる|taberu`, `한국|hanguk`.
The renderer draws the romanization as a smaller second line beneath
the main surface form; this keeps ideographic trees readable for
non-readers without forcing a separate data field.

Layout is a textbook tidy-tree: post-order pass assigns each node an
x-position equal to the midpoint of its children's x-range; leaves
are placed at integer x-slots in reading order. Depth is the y-axis.
The result is clean for the small trees a Konso sentence produces
(depth rarely above 5, leaves rarely above 10).

Rendering produces inline SVG — no external assets, no JS. Non-
terminal labels are drawn in a blue-grey; terminals (Konso surface
forms) are drawn in white and slightly larger so the actual sentence
is easy to read off the bottom row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from typing import List, Optional


class ParseError(ValueError):
    pass


@dataclass
class Node:
    label: str
    children: List['Node'] = field(default_factory=list)
    x: float = 0.0
    depth: int = 0
    romanization: str = ''

    @property
    def is_leaf(self) -> bool:
        return not self.children


def _split_leaf_token(tok: str) -> tuple:
    """Split a leaf token on the first `|` into (surface, romanization)."""
    if '|' in tok:
        surface, _, rom = tok.partition('|')
        return surface, rom
    return tok, ''


_TOKEN = re.compile(r"\[|\]|[^\s\[\]]+")


def parse_bracket(s: str) -> Node:
    s = (s or '').strip()
    if not s:
        raise ParseError('Empty tree.')
    tokens = _TOKEN.findall(s)
    if not tokens:
        raise ParseError('No tokens found.')
    pos = [0]

    def parse_node() -> Node:
        if pos[0] >= len(tokens) or tokens[pos[0]] != '[':
            raise ParseError(
                f"Expected '[' at token {pos[0]}: "
                f"{tokens[pos[0]] if pos[0] < len(tokens) else 'EOF'}.")
        pos[0] += 1
        if pos[0] >= len(tokens):
            raise ParseError('Unterminated bracket after [.')
        label = tokens[pos[0]]
        if label in ('[', ']'):
            raise ParseError(
                f"Expected label after '[', got {label!r}.")
        pos[0] += 1
        children: List[Node] = []
        while pos[0] < len(tokens) and tokens[pos[0]] != ']':
            tok = tokens[pos[0]]
            if tok == '[':
                children.append(parse_node())
            else:
                surface, rom = _split_leaf_token(tok)
                children.append(Node(label=surface, romanization=rom))
                pos[0] += 1
        if pos[0] >= len(tokens):
            raise ParseError(f"Unterminated bracket at {label!r}.")
        pos[0] += 1
        return Node(label=label, children=children)

    root = parse_node()
    if pos[0] != len(tokens):
        raise ParseError(
            f'Extra tokens after root close: '
            f'{" ".join(tokens[pos[0]:])}')
    return root


def _assign_leaf_positions(node: Node, depth: int,
                           counter: List[int]) -> None:
    node.depth = depth
    if node.is_leaf:
        node.x = float(counter[0])
        counter[0] += 1
        return
    for c in node.children:
        _assign_leaf_positions(c, depth + 1, counter)
    node.x = (node.children[0].x + node.children[-1].x) / 2.0


def _walk(node: Node, out: List[Node]) -> None:
    out.append(node)
    for c in node.children:
        _walk(c, out)


def render_svg(root: Node,
               *,
               col_w: int = 64,
               row_h: int = 52,
               pad: int = 18) -> str:
    """Return an inline SVG <svg> fragment for the tree."""
    leaves: List[int] = [0]
    _assign_leaf_positions(root, 0, leaves)
    n_leaves = leaves[0]
    nodes: List[Node] = []
    _walk(root, nodes)
    max_depth = max(n.depth for n in nodes)
    has_rom = any(n.is_leaf and n.romanization for n in nodes)

    width = max(n_leaves, 1) * col_w + 2 * pad
    # Add an extra half-row under the leaves when any leaf carries a
    # romanization, so the reading fits without colliding with the
    # SVG floor.
    rom_pad = 18 if has_rom else 0
    height = (max_depth + 1) * row_h + 2 * pad + rom_pad

    def px(node: Node) -> float:
        return pad + (node.x + 0.5) * col_w

    def py(node: Node) -> float:
        return pad + node.depth * row_h + 20

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" '
        f'role="img" aria-label="Konso syntax tree" '
        f'style="background:#0d1117;border:1px solid #21262d;'
        f'border-radius:4px;font-family:ui-monospace,SFMono-Regular,'
        f'Menlo,monospace">')
    # Edges first so text draws on top.
    for n in nodes:
        for c in n.children:
            parts.append(
                f'<line x1="{px(n):.1f}" y1="{py(n) + 4:.1f}" '
                f'x2="{px(c):.1f}" y2="{py(c) - 14:.1f}" '
                f'stroke="#30363d" stroke-width="1"/>')
    for n in nodes:
        label = escape(n.label)
        if n.is_leaf:
            parts.append(
                f'<text x="{px(n):.1f}" y="{py(n):.1f}" '
                f'text-anchor="middle" fill="#c9d1d9" '
                f'font-size="15" font-weight="500">{label}</text>')
            if n.romanization:
                parts.append(
                    f'<text x="{px(n):.1f}" y="{py(n) + 16:.1f}" '
                    f'text-anchor="middle" fill="#8b949e" '
                    f'font-size="10" font-style="italic">'
                    f'{escape(n.romanization)}</text>')
        else:
            parts.append(
                f'<text x="{px(n):.1f}" y="{py(n):.1f}" '
                f'text-anchor="middle" fill="#58a6ff" '
                f'font-size="13" font-style="italic">{label}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def render_bracket(node: Node) -> str:
    """Re-serialize a Node back to `[S [NP ...]]` form — useful for
    echoing a normalized version of user input."""
    if node.is_leaf:
        if node.romanization:
            return f'{node.label}|{node.romanization}'
        return node.label
    inner = ' '.join(render_bracket(c) for c in node.children)
    return f'[{node.label} {inner}]'

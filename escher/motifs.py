"""Stock asymmetric motifs used as the default fundamental-domain
content for escher renderings.

Each motif is given as an SVG ``<path d="…">`` definition whose
nominal coordinates live in [0, 1]×[0, 1].  Because they are
intentionally asymmetric, the wallpaper-group structure reads at a
glance — you can see exactly which symmetry was applied to which
copy.

When the user wires up an external content source (CA frame,
TileSpec, bitmap), the renderer accepts any SVG snippet whose own
coordinates fit in the [0, 1] box; the stock motifs below are just
the default population.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class StockMotif:
    slug: str
    name: str
    note: str
    # Body of one or more <path>/<polygon>/etc. SVG elements that fit
    # inside [0, 1]×[0, 1].  The renderer wraps these in a <g> with
    # the appropriate transform applied.
    svg_body: str
    # A short colour list used as the default palette when the
    # rendering uses ``fill="currentColor"`` references.
    palette: tuple = ('#222', '#cfa', '#7af', '#fa7')


# Stock motifs.  Each is asymmetric in all axes so reflections,
# rotations, and glides are visually distinct.

STOCK: Dict[str, StockMotif] = {
    'comma': StockMotif(
        slug='comma', name='Comma',
        note='Classical asymmetric tile teaching motif.',
        svg_body=(
            # A teardrop / comma curve hooked downward-right.  Hand-tuned
            # bezier so the symmetry of its mirror image is unmistakable.
            '<path d="M 0.2 0.15 '
              'C 0.6 0.05, 0.95 0.4, 0.75 0.7 '
              'C 0.65 0.85, 0.45 0.9,  0.35 0.78 '
              'C 0.28 0.7,  0.45 0.6,  0.5 0.55 '
              'C 0.6 0.45,  0.55 0.32, 0.4 0.32 '
              'C 0.28 0.32, 0.2 0.2, 0.2 0.15 Z" '
              'fill="#3a7eec" stroke="#1a3e7a" stroke-width="0.02" />'
        ),
    ),
    'p-letter': StockMotif(
        slug='p-letter', name='Letter “P”',
        note='The classic "letter p" example — asymmetric in every axis.',
        svg_body=(
            '<g stroke="#222" stroke-width="0.04" fill="none" stroke-linecap="round">'
            '<line x1="0.3" y1="0.1" x2="0.3" y2="0.9" />'
            '<path d="M 0.3 0.15 '
              'C 0.7 0.15, 0.85 0.35, 0.7 0.5 '
              'C 0.6  0.55, 0.4 0.5, 0.3 0.5" '
              'fill="none" />'
            '<circle cx="0.45" cy="0.32" r="0.04" fill="#ec5b3a" stroke="none" />'
            '</g>'
        ),
    ),
    'spiral': StockMotif(
        slug='spiral', name='Hooked spiral',
        note='Spiral inward + a hook tail; chirality reads clearly.',
        svg_body=(
            '<path d="M 0.5 0.5 '
              'C 0.65 0.4, 0.7 0.55, 0.55 0.65 '
              'C 0.4 0.7,  0.3 0.55, 0.4 0.4 '
              'C 0.5 0.25, 0.75 0.3, 0.85 0.5 '
              'C 0.85 0.85, 0.55 0.95, 0.3 0.85" '
              'fill="none" stroke="#3aec74" stroke-width="0.05" '
              'stroke-linecap="round" />'
        ),
    ),
    'triangle-arrow': StockMotif(
        slug='triangle-arrow', name='Arrow + dot',
        note='Right-pointing arrow with a colour-coded tail dot.',
        svg_body=(
            '<polygon points="0.1,0.4 0.7,0.4 0.7,0.25 0.95,0.5 0.7,0.75 0.7,0.6 0.1,0.6" '
              'fill="#ec5b3a" stroke="#7a2a1a" stroke-width="0.02" />'
            '<circle cx="0.2" cy="0.5" r="0.06" fill="#3a7eec" stroke="#1a3e7a" stroke-width="0.02" />'
        ),
    ),
    'crescent': StockMotif(
        slug='crescent', name='Crescent + star',
        note='Asymmetric crescent with a small accent.',
        svg_body=(
            '<path d="M 0.65 0.2 '
              'A 0.32 0.32 0 1 0 0.65 0.8 '
              'A 0.25 0.25 0 1 1 0.65 0.2 Z" '
              'fill="#fbbf3a" stroke="#7a5a1a" stroke-width="0.02" />'
            '<polygon points="0.25,0.5 0.3,0.42 0.36,0.5 0.3,0.58" '
              'fill="#ec5b3a" stroke="none" />'
        ),
    ),
    'asymmetric-blob': StockMotif(
        slug='asymmetric-blob', name='Wavy blob',
        note='Soft asymmetric quadrilateral — good for textures.',
        svg_body=(
            '<path d="M 0.15 0.25 '
              'C 0.5 0.05,  0.85 0.3,  0.8 0.55 '
              'C 0.75 0.85, 0.45 0.95, 0.25 0.78 '
              'C 0.1 0.6,  0.05 0.45, 0.15 0.25 Z" '
              'fill="#d2a8ff" stroke="#5a3e7a" stroke-width="0.025" />'
            '<circle cx="0.55" cy="0.45" r="0.06" fill="#222" />'
        ),
    ),
}


def get(slug: str) -> StockMotif:
    return STOCK[slug]


DEFAULT_MOTIF = 'comma'

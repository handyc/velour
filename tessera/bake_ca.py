"""Image → hex-flower CA rule baker.

For each pixel of an input RGBA image, sample the pixel and its 6
hex-neighbours (offset-r topology, so the image is interpreted as a
hex grid — no averaging needed because offset-r maps 1-to-1 onto a
square pixel grid with odd rows shifted).  Quantise the 7 samples
into 4 colours where palette[0] = the centre pixel exactly and
palette[1..3] = 3 neighbours that are most distant from the centre
(under squared-Euclidean RGBA distance).

Each pixel yields a (rule_key, palette) pair where rule_key is the
6-tuple of palette-indices assigned to the neighbours.  Across the
image we count rule-key occurrences and average the palettes per
rule_key.  Collisions (same 6-tuple, different palettes) collapse
into one entry whose palette is the channel-wise mean.

The output is a ranked catalogue of hex-flower configurations
occurring in the image — i.e. an identity (no-change) CA rule whose
table only contains the patterns the image actually exhibits.
"""

from __future__ import annotations
import math

import numpy as np


def _hex_neighbour_indices(y: int, x: int, W: int):
    """Return six (ny, nx) tuples for the 6 hex-flower neighbours of
    (y, x) under offset-r layout (odd rows shifted right).  The
    neighbour order matches Tessera edge numbering 0..5 — clockwise
    from top-right: TR, R, BR, BL, L, TL.  Returns None if any
    neighbour falls outside the grid (caller must skip that pixel)."""
    shift = y % 2
    tl_x = x - 1 + shift
    br_x = x + shift
    if tl_x < 0 or br_x >= W or x - 1 < 0 or x + 1 >= W:
        return None
    return [
        (y - 1, br_x),   # 0 TR
        (y,     x + 1),  # 1 R
        (y + 1, br_x),   # 2 BR
        (y + 1, tl_x),   # 3 BL
        (y,     x - 1),  # 4 L
        (y - 1, tl_x),   # 5 TL
    ]


def _build_palette(self_c: np.ndarray, neighbours: np.ndarray,
                   min_dist_sq: int = 200) -> np.ndarray:
    """`self_c`: (4,) int64.  `neighbours`: (6, 4) int64.

    Returns a (4, 4) int64 palette where row 0 = self exactly and
    rows 1..3 = up to three neighbour values, chosen greedily as the
    farthest-from-self that are also far enough from each other
    (squared-Euclidean RGBA distance > `min_dist_sq`).  Pads with
    self when the neighbourhood is too uniform to fill all four
    slots."""
    palette = [self_c.copy()]
    dists_self = np.sum((neighbours - self_c) ** 2, axis=1)
    order = np.argsort(-dists_self)  # descending
    for i in order:
        if len(palette) >= 4:
            break
        n = neighbours[i]
        too_close = False
        for p in palette:
            if int(np.sum((n - p) ** 2)) <= min_dist_sq:
                too_close = True
                break
        if not too_close:
            palette.append(n.copy())
    while len(palette) < 4:
        palette.append(palette[0].copy())
    return np.array(palette, dtype=np.int64)


def _label_neighbours(neighbours: np.ndarray,
                      palette: np.ndarray) -> tuple:
    """Return a 6-tuple of palette indices, one per neighbour."""
    # neighbours: (6, 4); palette: (4, 4); broadcast → (6, 4, 4)
    diffs = neighbours[:, None, :] - palette[None, :, :]
    d2 = np.sum(diffs ** 2, axis=2)        # (6, 4)
    return tuple(int(i) for i in np.argmin(d2, axis=1))


def bake_rules(arr_rgba: np.ndarray, sample_step: int = 1) -> dict:
    """Scan every pixel of `arr_rgba` (after a 1-pixel border skip),
    accumulate (rule_key → count + palette-sum), return the merged
    dict.  `sample_step` > 1 speeds the scan at the cost of coverage.

    `arr_rgba`: (H, W, 4) uint8.  Returns: dict mapping 6-tuple →
    {'count': int, 'palette': (4, 4) uint8}.  The palette is the
    channel-wise mean across all pixels that hit that rule key.
    """
    H, W = arr_rgba.shape[:2]
    arr = arr_rgba.astype(np.int64)
    acc: dict[tuple, dict] = {}
    for y in range(1, H - 1, sample_step):
        for x in range(1, W - 1, sample_step):
            idxs = _hex_neighbour_indices(y, x, W)
            if idxs is None:
                continue
            self_c = arr[y, x]
            neighbours = np.array([arr[ny, nx] for ny, nx in idxs])
            palette = _build_palette(self_c, neighbours)
            labels = _label_neighbours(neighbours, palette)
            slot = acc.get(labels)
            if slot is None:
                slot = {'count': 0,
                        'pal_sum': np.zeros((4, 4), dtype=np.float64)}
                acc[labels] = slot
            slot['count'] += 1
            slot['pal_sum'] += palette
    out: dict[tuple, dict] = {}
    for k, v in acc.items():
        avg = v['pal_sum'] / v['count']
        out[k] = {
            'count': v['count'],
            'palette': np.clip(avg, 0, 255).astype(np.uint8),
        }
    return out


def build_global_palette_and_table(rules: dict,
                                   k: int = 4) -> tuple:
    """Collapse the per-rule palettes into ONE global k-colour palette
    (k-means on the central pixels weighted by rule frequency) and
    build a complete 4096-entry rule table mapping 6-tuple → output
    label in {0..k-1}.

    Missing 6-tuples (configurations the image never produced) are
    filled by Hamming-nearest baked rule, breaking ties by frequency.

    The semantics: each Wang-tessellation cell carries a label
    ∈ {0..k-1}; a CA tick reads 6 neighbour labels, packs them into
    a 12-bit key, and the table gives the new self-label.  The
    global palette then maps that label to an RGB the user sees.

    Returns: (global_palette (k, 4) uint8, table (4096,) int8).
    """
    if not rules:
        gp = np.array([[60, 60, 60, 255], [150, 150, 150, 255],
                       [210, 210, 210, 255], [255, 255, 255, 255]],
                      dtype=np.uint8)
        return gp, np.zeros(4096, dtype=np.int8)

    centres = np.array([info['palette'][0] for info in rules.values()],
                       dtype=np.float64)             # (N, 4)
    weights = np.array([info['count'] for info in rules.values()],
                       dtype=np.float64)             # (N,)

    # k-means seeded from the k most-frequent rules' central pixels
    # so the initial centroids actually fall on real image content.
    top_k_idx = np.argsort(-weights)[:k]
    palette = centres[top_k_idx].copy()
    for _ in range(8):
        d = np.sum((centres[:, None, :] - palette[None, :, :]) ** 2, axis=2)
        assign = np.argmin(d, axis=1)
        for j in range(k):
            mask = (assign == j)
            if np.any(mask):
                palette[j] = np.average(centres[mask], axis=0,
                                        weights=weights[mask])
    palette = np.clip(palette, 0, 255).astype(np.uint8)

    # Each baked rule's output label = global-palette index closest
    # to its central pixel.
    def encode_key(k_tuple):
        return (k_tuple[0] << 10) | (k_tuple[1] << 8) | (k_tuple[2] << 6) \
             | (k_tuple[3] << 4) | (k_tuple[4] << 2) | k_tuple[5]

    table = np.full(4096, -1, dtype=np.int8)
    rule_keys = np.array(list(rules.keys()), dtype=np.int64)  # (N, 6)
    rule_counts = weights.copy()
    rule_outputs = np.zeros(len(rules), dtype=np.int8)
    for i, key in enumerate(rules.keys()):
        info = rules[key]
        idx = encode_key(key)
        d = np.sum((info['palette'][0].astype(np.int64)
                    - palette.astype(np.int64)) ** 2, axis=1)
        out = int(np.argmin(d))
        table[idx] = out
        rule_outputs[i] = out

    # Fill missing 6-tuples by Hamming-nearest baked rule, ties → freq.
    missing = np.where(table == -1)[0]
    if missing.size and rule_keys.size:
        # Decode missing indices to (M, 6) tuples (column-major).
        m = missing.shape[0]
        mtuples = np.zeros((m, 6), dtype=np.int64)
        mtuples[:, 0] = (missing >> 10) & 3
        mtuples[:, 1] = (missing >> 8)  & 3
        mtuples[:, 2] = (missing >> 6)  & 3
        mtuples[:, 3] = (missing >> 4)  & 3
        mtuples[:, 4] = (missing >> 2)  & 3
        mtuples[:, 5] = missing & 3
        # Compute Hamming distance (M, N).  Tiebreaker: maximise count.
        for batch_start in range(0, m, 256):
            batch = mtuples[batch_start:batch_start + 256]
            # Broadcast: (B, 1, 6) vs (1, N, 6) → (B, N, 6) → sum diff
            hd = np.sum(batch[:, None, :] != rule_keys[None, :, :], axis=2)
            min_h = hd.min(axis=1, keepdims=True)
            # Mask of best candidates per row.
            mask = (hd == min_h)
            # Pick the highest-count one among ties.
            counts = np.where(mask, rule_counts[None, :], -1.0)
            best = np.argmax(counts, axis=1)
            for j, bi in enumerate(best):
                table[missing[batch_start + j]] = rule_outputs[bi]
    table = table.astype(np.int8)
    table[table < 0] = 0
    return palette, table


def hex_flower_svg(self_rgba, neighbour_rgbas, labels=None,
                   R: float = 15.0) -> str:
    """Render a 7-hex flower as an inline SVG string.  Central hex =
    self, 6 outer hexes = neighbours (indexed CW from top-right to
    match the edge numbering used everywhere else in tessera).
    Optional `labels` writes the 0..3 palette index on each outer
    hex so the catalogue layout is legible at a glance.
    """
    s = math.sqrt(3) / 2
    width = 6 * R * s + 4
    height = 5 * R + 4
    cx = width / 2
    cy = height / 2

    def verts(x, y):
        return [(x,         y - R),
                (x + R * s, y - R / 2),
                (x + R * s, y + R / 2),
                (x,         y + R),
                (x - R * s, y + R / 2),
                (x - R * s, y - R / 2)]

    def rgb_hex(rgba):
        r, g, b = int(rgba[0]), int(rgba[1]), int(rgba[2])
        return f'#{r:02x}{g:02x}{b:02x}'

    def polygon(x, y, fill):
        pts = ' '.join(f'{px:.1f},{py:.1f}' for px, py in verts(x, y))
        return (f'<polygon points="{pts}" fill="{fill}" '
                f'stroke="#222" stroke-width="0.5"/>')

    outer_off = [
        ( R * s, -3 * R / 2),  # 0 TR
        ( 2 * R * s,     0  ),  # 1 R
        ( R * s,  3 * R / 2),  # 2 BR
        (-R * s,  3 * R / 2),  # 3 BL
        (-2 * R * s,     0  ),  # 4 L
        (-R * s, -3 * R / 2),  # 5 TL
    ]
    parts = [f'<svg width="{width:.0f}" height="{height:.0f}" '
             f'xmlns="http://www.w3.org/2000/svg">']
    for i, (dx, dy) in enumerate(outer_off):
        parts.append(polygon(cx + dx, cy + dy, rgb_hex(neighbour_rgbas[i])))
        if labels is not None:
            tx, ty = cx + dx, cy + dy + 4
            parts.append(
                f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" '
                f'font-size="10" fill="#fff" stroke="#000" '
                f'stroke-width="0.6" paint-order="stroke fill">'
                f'{labels[i]}</text>')
    parts.append(polygon(cx, cy, rgb_hex(self_rgba)))
    parts.append('</svg>')
    return ''.join(parts)

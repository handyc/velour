"""caframe/render — generate frames from a Sequence recipe.

Pure functions; no Django ORM here so they're easy to call from the
GA, the views, and from a Jupyter REPL.  Reuses caformer's hex CA
primitives for the hex shape so the same K=4 substrate underlies both
language and video work.
"""
from __future__ import annotations
import io
import struct
import zlib
from typing import Iterator, List, Tuple

import numpy as np


# Default 4-color palette — gentle greens (matches the Velour aesthetic).
DEFAULT_PALETTE_RGB = (
    (0x00, 0x00, 0x00),
    (0x66, 0xcc, 0x66),
    (0xcc, 0x66, 0x66),
    (0xee, 0xee, 0xcc),
)


def _lcg_bytes(seed: int, n: int) -> np.ndarray:
    """Same generator caformer uses, kept local so we don't drag the
    full caformer import chain into a Django app that should stand on
    its own."""
    state = np.uint32(seed)
    out = np.empty(n, dtype=np.uint8)
    for i in range(n):
        state = np.uint32(state * 1664525 + 1013904223)
        out[i] = (state >> np.uint32(16)) & np.uint8(0xFF)
    return out


def _seed_grid(seed: int, w: int, h: int, n_colors: int) -> np.ndarray:
    arr = _lcg_bytes(seed, w * h)
    return (arr % np.uint8(n_colors)).reshape(h, w)


def iter_frames(*, rule_genome: bytes, seed: int, w: int, h: int,
                 n_frames: int, shape: str = 'hex',
                 n_colors: int = 4) -> Iterator[np.ndarray]:
    """Yield ``n_frames`` (h, w) uint8 grids by stepping the CA from
    ``seed`` once per frame. Frame 0 is the seed grid itself."""
    grid = _seed_grid(seed, w, h, n_colors)
    yield grid.copy()
    if shape == 'hex':
        from caformer.primitives import hex_ca_step
        rule_arr = np.frombuffer(rule_genome, dtype=np.uint8)
        # caformer's hex CA wants exactly 16,384 entries (4^7 neighborhood)
        if rule_arr.size != 16384:
            raise ValueError(
                f'hex rule_genome must be 16384 bytes (got {rule_arr.size})')
        for _ in range(n_frames - 1):
            grid = hex_ca_step(grid, rule_arr)
            yield grid.copy()
    elif shape == 'square':
        # Wolfram-style 9-cell Moore neighborhood, K=n_colors.
        # rule_genome is K^9 bytes for K=4 → 262144; too big to ship.
        # Use a compact "totalistic" variant: rule indexed by the sum
        # of the 9 cells (max 9*(K-1) = 27 for K=4 → 28 entries).
        rule_arr = np.frombuffer(rule_genome, dtype=np.uint8)
        max_sum = 9 * (n_colors - 1)
        if rule_arr.size < max_sum + 1:
            raise ValueError(
                f'square totalistic rule needs {max_sum + 1} bytes '
                f'(got {rule_arr.size})')
        for _ in range(n_frames - 1):
            # Sum all 9 cells (self + 8 neighbours) using rolls — wraps
            # at the edges, which keeps frames bounded.
            s = np.zeros_like(grid, dtype=np.int16)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    s += np.roll(np.roll(grid, dy, axis=0), dx, axis=1)
            grid = rule_arr[s] % np.uint8(n_colors)
            yield grid.copy()
    else:
        raise ValueError(f'unknown shape {shape!r}; use hex or square')


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    chunk = tag + data
    return (struct.pack('>I', len(data)) + chunk
            + struct.pack('>I', zlib.crc32(chunk)))


def grid_to_png(grid: np.ndarray, palette: List[Tuple[int, int, int]] = None,
                  cell_px: int = 6) -> bytes:
    """Encode a (h, w) uint8 grid as a stand-alone PNG (no dependencies
    beyond numpy + zlib). cell_px upscales each cell to cell_px×cell_px
    so a 64×64 grid at cell_px=6 becomes a 384×384 PNG."""
    pal = palette or DEFAULT_PALETTE_RGB
    h, w = grid.shape
    out_h = h * cell_px
    out_w = w * cell_px
    # Build the upscaled RGB buffer.
    pal_arr = np.array(pal, dtype=np.uint8)         # (K, 3)
    rgb_small = pal_arr[grid]                          # (h, w, 3)
    rgb = np.repeat(np.repeat(rgb_small, cell_px, axis=0),
                     cell_px, axis=1)                  # (out_h, out_w, 3)
    # PNG scanline format: each row is preceded by a filter byte (0).
    row_bytes = bytearray()
    for y in range(out_h):
        row_bytes.append(0)
        row_bytes.extend(rgb[y].tobytes())
    compressed = zlib.compress(bytes(row_bytes), 9)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', out_w, out_h, 8, 2, 0, 0, 0)
    return (sig
            + _png_chunk(b'IHDR', ihdr)
            + _png_chunk(b'IDAT', compressed)
            + _png_chunk(b'IEND', b''))


def grids_to_apng(frames: List[np.ndarray],
                    palette: List[Tuple[int, int, int]] = None,
                    cell_px: int = 6, fps: int = 8) -> bytes:
    """Encode a list of frames as APNG (animated PNG).  Same palette
    + cell_px as ``grid_to_png``; ``fps`` controls playback speed.

    APNG is supported by every modern browser; no FFmpeg dependency,
    no extra Python packages — just zlib + struct."""
    if not frames:
        raise ValueError('need at least one frame')
    pal = palette or DEFAULT_PALETTE_RGB
    pal_arr = np.array(pal, dtype=np.uint8)
    h, w = frames[0].shape
    out_h = h * cell_px
    out_w = w * cell_px
    delay_num = 1
    delay_den = max(1, int(fps))

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', out_w, out_h, 8, 2, 0, 0, 0)
    actl = struct.pack('>II', len(frames), 0)        # num_frames, plays=0=∞
    chunks = [sig, _png_chunk(b'IHDR', ihdr), _png_chunk(b'acTL', actl)]
    seq = 0
    for i, grid in enumerate(frames):
        rgb_small = pal_arr[grid]
        rgb = np.repeat(np.repeat(rgb_small, cell_px, axis=0),
                          cell_px, axis=1)
        row_bytes = bytearray()
        for y in range(out_h):
            row_bytes.append(0)
            row_bytes.extend(rgb[y].tobytes())
        compressed = zlib.compress(bytes(row_bytes), 9)
        # fcTL precedes every frame.
        fctl = struct.pack('>IIIIIHHBB', seq, out_w, out_h, 0, 0,
                            delay_num, delay_den, 0, 0)
        chunks.append(_png_chunk(b'fcTL', fctl))
        seq += 1
        if i == 0:
            chunks.append(_png_chunk(b'IDAT', compressed))
        else:
            # fdAT = sequence number + frame data.
            chunks.append(_png_chunk(b'fdAT',
                                       struct.pack('>I', seq) + compressed))
            seq += 1
    chunks.append(_png_chunk(b'IEND', b''))
    return b''.join(chunks)


def consistency_score(frames: List[np.ndarray]) -> float:
    """Frame-to-frame consistency = mean fraction of cells unchanged
    between consecutive frames. Range [0, 1]; 1 = static, 0 = every
    cell changes every frame.  This is the headline fitness for
    "sensible video" GA — too high = boring, too low = noise; a
    reasonable target is ~0.85."""
    if len(frames) < 2:
        return 1.0
    h, w = frames[0].shape
    total = 0.0
    for a, b in zip(frames[:-1], frames[1:]):
        total += float((a == b).sum()) / (h * w)
    return total / (len(frames) - 1)


def edge_activity(frames: List[np.ndarray]) -> float:
    """Sum of pairwise cell changes — useful as an "interestingness"
    metric to *minimise* against in conjunction with consistency
    (you want stable but-not-static)."""
    if len(frames) < 2:
        return 0.0
    h, w = frames[0].shape
    diffs = sum(int((a != b).sum()) for a, b in zip(frames[:-1], frames[1:]))
    return diffs / (h * w * (len(frames) - 1))

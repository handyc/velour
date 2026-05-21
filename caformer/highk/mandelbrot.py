"""Render a 1024x1024 Mandelbrot at 32-bit color depth.

The output is a uint32 array.  Each pixel's value is treated as a
K=2^32 cell value / token ID.  ~1M unique colors at most.
"""
from __future__ import annotations

import numpy as np


def render(side: int = 1024,
              cx: float = -0.5, cy: float = 0.0, span: float = 3.0,
              max_iter: int = 4096) -> np.ndarray:
    """Render a Mandelbrot set as a `side x side` uint32 image.

    The K=2^32 value at each pixel encodes the escape time + smooth
    coloring:

      bits 0..23  smooth-iteration count scaled to 24-bit
      bits 24..31 a low-byte "depth slice" so deeply-escaped pixels
                  don't all collide on the same hue

    Pixels INSIDE the Mandelbrot set (didn't escape) get 0 — a
    natural sentinel that's also the most likely "default token".
    """
    side = int(side)
    cx, cy, span = float(cx), float(cy), float(span)
    extent = span / 2.0
    xs = np.linspace(cx - extent, cx + extent, side, dtype=np.float64)
    ys = np.linspace(cy - extent, cy + extent, side, dtype=np.float64)

    out = np.zeros((side, side), dtype=np.uint32)
    log2 = np.log(2.0)
    for j, y0 in enumerate(ys):
        # Vectorise across the full row.
        c = (xs + 1j * y0).astype(np.complex128)
        z = np.zeros_like(c)
        active = np.ones(side, dtype=bool)
        # iter_at[i] = the iteration at which pixel i first escaped
        iter_at = np.zeros(side, dtype=np.int32)
        # mag_at[i] = |z|^2 at first escape (for smoothing)
        mag_at = np.zeros(side, dtype=np.float64)
        for n in range(max_iter):
            # z[active] = z[active] ** 2 + c[active]
            z[active] = z[active] * z[active] + c[active]
            mag2 = (z.real * z.real + z.imag * z.imag)
            escaped = active & (mag2 > 4.0)
            iter_at[escaped] = n + 1
            mag_at[escaped]  = mag2[escaped]
            active = active & ~escaped
            if not active.any():
                break
        # Smooth iteration count: nu = n + 1 - log(log(|z|))/log(2)
        smooth = iter_at.astype(np.float64)
        mask = iter_at > 0
        # Guard log domain.
        m = np.clip(mag_at[mask], 1.0001, None)
        smooth[mask] = iter_at[mask] + 1.0 - np.log(np.log(m) / 2.0) / log2
        # Quantise smooth to 24 bits; depth slice in top byte.
        lo24 = (smooth * 4096.0).astype(np.int64) & 0xFFFFFF
        hi8  = ((iter_at >> 4) & 0xFF).astype(np.int64) << 24
        row  = (hi8 | lo24).astype(np.uint32)
        # Inside-set pixels stay 0 (didn't escape).
        row[iter_at == 0] = 0
        out[j] = row
    return out


def render_to_png_bytes(arr: np.ndarray) -> bytes:
    """Quick view: take the LOW 24 bits as RGB and write a PNG.
    Returns PNG bytes (no caller-side file IO required)."""
    import io, struct, zlib
    h, w = arr.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[:, :, 0] = (arr        & 0xFF).astype(np.uint8)
    rgb[:, :, 1] = ((arr >> 8) & 0xFF).astype(np.uint8)
    rgb[:, :, 2] = ((arr >> 16) & 0xFF).astype(np.uint8)
    raw = b''.join(b'\x00' + rgb[j].tobytes() for j in range(h))
    def chunk(tag, data):
        crc = zlib.crc32(tag + data)
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', crc & 0xFFFFFFFF))
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw, 6)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

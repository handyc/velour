"""Class-4 LUT pool — references mandelhunt-pool .lut files on disk.

A "pool member" is identified by an integer index into a sorted list
of pool files.  We never copy LUT bytes around; the engine loads
them on demand and caches.  This lets the gene refer to a pool of
65,536+ rules cheaply (the gene just stores 16-bit indices)."""
from __future__ import annotations

import functools
from pathlib import Path
from typing import List

import numpy as np


DEFAULT_POOL_DIRS = (
    '.artifacts/loupe_rules',
    '.artifacts/mandelhunt_pool',
    '.artifacts/true_l0_quines',
    '.artifacts/strict_class4_quines',
)


@functools.lru_cache(maxsize=1)
def list_pool_files(pool_dirs: tuple = DEFAULT_POOL_DIRS) -> tuple:
    """Sorted tuple of .lut files across all configured pool dirs.
    Caching is intentional — the pool changes rarely; restart the
    process if you add new LUTs."""
    from django.conf import settings
    base = Path(settings.BASE_DIR)
    paths = []
    for d in pool_dirs:
        dp = (base / d) if not Path(d).is_absolute() else Path(d)
        if dp.is_dir():
            paths.extend(sorted(dp.glob('*.lut')))
    return tuple(paths)


def pool_size(pool_dirs: tuple = DEFAULT_POOL_DIRS) -> int:
    return len(list_pool_files(pool_dirs))


@functools.lru_cache(maxsize=4096)
def load_pool_lut(idx: int, pool_dirs: tuple = DEFAULT_POOL_DIRS) -> np.ndarray:
    """Load LUT #idx from the pool as a 16,384-byte uint8 array.
    LRU-cached so the GA's inner loop doesn't re-read from disk
    every fitness eval."""
    files = list_pool_files(pool_dirs)
    if not files:
        raise FileNotFoundError(
            f'no .lut files found in {pool_dirs}; populate via mandelhunt '
            f'or caformer_generator_compare first')
    p = files[idx % len(files)]
    blob = p.read_bytes()
    if len(blob) != 16_384:
        raise ValueError(
            f'{p.name} is {len(blob)} B (need 16,384 for K=4 7→1 LUT)')
    return np.frombuffer(blob, dtype=np.uint8).copy() & 3

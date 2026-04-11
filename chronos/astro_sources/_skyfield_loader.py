"""Lazy skyfield loader.

Loading the ephemeris is expensive (16MB file → 1-2 seconds), so
we cache the loaded `eph` object across calls. The first call
also downloads de421.bsp to chronos/data/ if it isn't there.
"""

from pathlib import Path

from django.conf import settings


_cache = {'eph': None, 'ts': None}


def get():
    if _cache['eph'] is not None:
        return _cache['ts'], _cache['eph']
    try:
        from skyfield.api import Loader
    except ImportError:
        return None, None
    data_dir = Path(settings.BASE_DIR) / 'chronos' / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(data_dir), verbose=False)
    eph = loader('de421.bsp')
    ts = loader.timescale()
    _cache['eph'] = eph
    _cache['ts'] = ts
    return ts, eph

"""In-process daemon thread for the DMN dream generator.

Toggleable from the /caformer/dreams/ page via the
caformer_dreams_toggle view.  Same dream-generation logic as
caformer_dmn_dream management command, hoisted into a thread so
Django can control it.

State is process-global — restarting Django stops the daemon.
That's intentional: this is a dev convenience, not a production
service.  For long-lived production use, run caformer_dmn_dream
as a separate nohup process.
"""
from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np


_lock = threading.Lock()
_thread = None         # threading.Thread or None
_stop_flag = False     # set by toggle_off, polled by the loop
_state = {
    'running':        False,
    'started_at':     None,
    'stopped_at':     None,
    'attempts':       0,
    'kept':           0,
    'rejected_c1c3':  0,
    'last_dream':     None,    # str filename
    'last_dream_at':  None,    # float epoch
    'interval_sec':   3.0,
    'max_pool':       200,
    'pool_dir':       '.artifacts/dmn_dreams',
}


def get_state():
    """Snapshot the current daemon state.  Safe to call from a view."""
    with _lock:
        return dict(_state)


def start(*, interval_sec: float = 3.0, max_pool: int = 200,
              pool_dir: str = '.artifacts/dmn_dreams') -> dict:
    """Start the dream daemon if not already running.  Returns the
    current state dict."""
    global _thread, _stop_flag
    with _lock:
        if _thread is not None and _thread.is_alive():
            return dict(_state)
        _stop_flag = False
        _state.update({
            'running':       True,
            'started_at':    time.time(),
            'stopped_at':    None,
            'attempts':      0,
            'kept':          0,
            'rejected_c1c3': 0,
            'last_dream':    None,
            'last_dream_at': None,
            'interval_sec':  float(interval_sec),
            'max_pool':      int(max_pool),
            'pool_dir':      pool_dir,
        })
        _thread = threading.Thread(target=_loop, daemon=True,
                                          name='dmn-dream-daemon')
        _thread.start()
        return dict(_state)


def stop() -> dict:
    """Signal the loop to exit and wait briefly."""
    global _thread, _stop_flag
    with _lock:
        _stop_flag = True
        _state['running'] = False
        _state['stopped_at'] = time.time()
        t = _thread
    if t is not None:
        t.join(timeout=5.0)
    with _lock:
        _thread = None
        return dict(_state)


def _loop():
    """Daemon body — same logic as caformer_dmn_dream's main loop.
    Imports are deferred so Django app loading isn't perturbed."""
    from caformer.lut_generators import (gen_mandelbrot, gen_julia,
                                                   gen_burning_ship,
                                                   gen_tricorn,
                                                   gen_multibrot,
                                                   gen_newton, gen_phoenix)
    from caformer.management.commands.caformer_dmn_dream import (
        is_class4, render_lut_png)
    from django.conf import settings

    gens = [('mandel',  gen_mandelbrot),
            ('julia',   gen_julia),
            ('bship',   gen_burning_ship),
            ('tricorn', gen_tricorn),
            ('multi',   gen_multibrot),
            ('newton',  gen_newton),
            ('phoenix', gen_phoenix)]

    base = Path(settings.BASE_DIR)
    cfg = get_state()
    pool = (base / cfg['pool_dir']) if not Path(cfg['pool_dir']).is_absolute() \
                                              else Path(cfg['pool_dir'])
    pool.mkdir(parents=True, exist_ok=True)

    while True:
        if _stop_flag:
            return
        iter_t0 = time.time()
        gen_name, gen_fn = secrets.choice(gens)
        rng = np.random.RandomState(secrets.randbits(32))
        try:
            lut = gen_fn(rng)
        except Exception:
            lut = None

        kept = False
        with _lock:
            _state['attempts'] += 1
        if lut is not None:
            arr = np.asarray(lut, dtype=np.uint8).ravel() & 3
            if arr.size == 16384:
                is_c4, act = is_class4(arr)
                if is_c4:
                    ts  = datetime.now().strftime('%Y%m%d_%H%M%S')
                    sid = secrets.token_hex(2)
                    name = f'{ts}_{gen_name}_act{act:.2f}_{sid}'
                    try:
                        (pool / f'{name}.lut').write_bytes(bytes(arr))
                        render_lut_png(arr, pool / f'{name}.png')
                        kept = True
                        with _lock:
                            _state['kept'] += 1
                            _state['last_dream'] = name
                            _state['last_dream_at'] = time.time()
                    except Exception:
                        pass
                else:
                    with _lock:
                        _state['rejected_c1c3'] += 1

        # Cull oldest if over cap.
        if kept:
            existing = sorted(pool.glob('*.lut'),
                                  key=lambda p: p.stat().st_mtime)
            cap = _state['max_pool']
            while len(existing) > cap:
                old = existing.pop(0)
                try:
                    old.unlink()
                    old.with_suffix('.png').unlink(missing_ok=True)
                except OSError:
                    pass

        # Sleep to next tick (or until stopped).
        elapsed = time.time() - iter_t0
        wait = max(0.0, _state['interval_sec'] - elapsed)
        # Poll _stop_flag in 100ms chunks so stop() responds quickly.
        slept = 0.0
        while slept < wait:
            if _stop_flag:
                return
            chunk = min(0.1, wait - slept)
            time.sleep(chunk)
            slept += chunk

"""Keychain filesystem — deterministic FS layered over a regenerable
quine-derived byte stream.

Three ideas come together here:

1.  **Deterministic regeneration.** Same seed + same chain params =
    byte-identical multi-MB binary database. The seed is the only
    thing that has to be persisted (or carried on a USB stick / ESP32).

2.  **Tag-only persistence.** The "files" the user sees are byte-range
    annotations into the regenerated DB. The annotations (name, mime,
    tags, content sha) live in a tiny JSON index on the host; the
    actual file bytes are derived on demand and discarded on unmount.

3.  **Multiple clocks per seed (v2).** A keychain has one *or more*
    named ``Clock``s. Each clock has a ``start_epoch`` and a
    ``ticks_per_second`` — the chain's level-0 rule for that clock is
    the seed evolved for ``(now - start) * ticks_per_second`` ticks.
    The static keychain is the degenerate case (ticks_per_second=0).
    Multiple clocks let the same seed produce both stable filesystem
    content and slowly-evolving time-series data side by side.

Files keyed by ``seed_sha256`` — plug in a different keychain device
or load a different quine = different filesystem.

Per-clock DB layout:

    DB[clock c, level i, stream s] = pack_k4_stream(
        run_ca_stream(
            chain_seeds(L0(c))[i],                # L0 is time-shifted
            init_seed = stream_init_seed(seed_sha, c, i, s),
            ticks      = stream_ticks,
            packed     = True,
        )
    )

A tag is ``(clock, level, stream, byte_start, byte_end, wall_anchor)``.
``wall_anchor`` is the unix-time snapshot the tag refers to (so the
content can be reproduced even after the clock has ticked past).
On a static clock ``wall_anchor`` is ignored.

The keychain root on disk:

    <BASE>/.keychains/<seed_sha256>/
        seed.bin              # 16,384 bytes (so the device can be lost)
        index.json            # tag index — format v2 with clocks list
        cache/<clock>/db.bin  # optional regenerated DB per clock
        archive/<clock>/      # optional per-clock time-series archive
        overlays/<file_id>    # optional per-file write overlays (P2)

Everything except ``index.json`` and ``seed.bin`` is rebuildable.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, Optional

# ─── Defaults ─────────────────────────────────────────────────────────
#
# These values are pinned in every index header.  Changing them shifts
# every byte offset, so a new index has to be created.

DEFAULT_DEPTH             = 64
DEFAULT_TICKS_PER_LEVEL   = 16
DEFAULT_STREAM_TICKS      = 64
DEFAULT_STREAMS_PER_LEVEL = 1
DEFAULT_PACKED            = True

BYTES_PER_TICK_RAW        = 16384        # 128×128 cells, 1 byte each
BYTES_PER_TICK_PACKED     = 4096         # 4 cells per byte

SEED_SIZE                 = 16384        # bytes


# ─── Per-level LCG init seed ─────────────────────────────────────────
#
# Each (seed, level, stream_index) needs a deterministic LCG init so
# the bytes are reproducible without storing them.  Adding the third
# axis lets you generate arbitrarily large databases without making
# the chain deeper: same 64 rules, different init grids per "stream".
# At streams_per_level=1 the behaviour is identical to the old
# 2-axis scheme.

def stream_init_seed(seed_sha256: str, level: int,
                       stream_index: int = 0,
                       clock_name: str = 'static',
                       tick_n: int = 0) -> int:
    """Deterministic 32-bit LCG init for one stream.

    Args:
        seed_sha256: hex of the keychain's seed sha — keeps two
            keychains with different seeds from colliding on streams.
        level:       chain depth index (0..depth-1).
        stream_index: per-level stream multiplicity index.
        clock_name:  which clock this stream belongs to.  Different
            clocks must produce different LCG inits even at the same
            (level, stream) — otherwise time-anchored content would
            coincide with the static DB at tick 0.
        tick_n: integer tick offset of the clock — bytes change as the
            clock ticks because the LCG init does too.

    For backward compatibility, ``clock_name='static'`` and
    ``tick_n=0`` reproduce the v1 LCG init exactly.
    """
    # v1-compatible fast path so existing keychains keep working.
    if clock_name == 'static' and tick_n == 0:
        h = hashlib.sha256(
            seed_sha256.encode('ascii')
            + struct.pack('<II', level, stream_index)
        ).digest()
        return struct.unpack('<I', h[:4])[0]
    h = hashlib.sha256(
        seed_sha256.encode('ascii')
        + b'|' + clock_name.encode('ascii')
        + struct.pack('<III', level, stream_index, tick_n & 0xFFFFFFFF)
    ).digest()
    return struct.unpack('<I', h[:4])[0]


def compute_seed_sha(seed_bytes: bytes) -> str:
    if len(seed_bytes) != SEED_SIZE:
        raise ValueError(
            f'seed must be {SEED_SIZE} bytes; got {len(seed_bytes)}')
    return hashlib.sha256(seed_bytes).hexdigest()


# ─── DB regeneration ─────────────────────────────────────────────────

@dataclass
class ChainParams:
    """Pin every input that affects DB offsets.  Mismatched params =
    different DB, even if the seed matches.

    The ``streams_per_level`` knob is the cheap way to scale the
    addressable DB without making the chain deeper.  Each
    (level, stream_index) pair has its own LCG init grid and therefore
    its own 256 KB of output bytes.  Setting it to 65,536 raises the
    addressable space from 16 MiB to 1 TiB without changing anything
    else — bytes are only ever materialised on demand."""
    depth:              int  = DEFAULT_DEPTH
    ticks_per_level:    int  = DEFAULT_TICKS_PER_LEVEL
    stream_ticks:       int  = DEFAULT_STREAM_TICKS
    streams_per_level:  int  = DEFAULT_STREAMS_PER_LEVEL
    packed:             bool = DEFAULT_PACKED
    init_seed_fn:       str  = 'spoeqi-v1'

    def bytes_per_stream(self) -> int:
        per_tick = (BYTES_PER_TICK_PACKED if self.packed
                    else BYTES_PER_TICK_RAW)
        return per_tick * self.stream_ticks

    def bytes_per_level(self) -> int:
        return self.bytes_per_stream() * self.streams_per_level

    def total_bytes(self) -> int:
        return self.depth * self.bytes_per_level()

    def as_dict(self) -> dict:
        return asdict(self)


# ─── Clock — one time-axis on a keychain ──────────────────────────────
#
# A keychain has one or more named clocks.  Each clock is "the same
# CA at a different speed":
#
#   - 'static' (ticks_per_second=0): the classic frozen DB. The chain
#     starts from the seed itself (L0 = seed LUT applied to itself for
#     ticks_per_level ticks, same as before).
#
#   - 'slow' (ticks_per_second=1/86400): the mother CA advances one
#     tick per day from start_epoch.  The chain's L0 at wall-clock
#     time t is the seed evolved by floor((t - start)/86400) ticks.
#     Anyone with (seed, start_epoch, t) can reproduce the bytes —
#     the device does not need to actually run the CA to keep state.
#
#   - 'gigabyte-per-day' (ticks_per_second ≈ 2.83): a fast clock whose
#     output rate produces ~1 GB/day if every tick state is archived.
#
# Different clocks coexist; each has its own derivative DB; tags can
# reference any clock.

DEFAULT_CLOCK_NAME = 'static'


@dataclass
class Clock:
    """One time axis on a keychain.

    Static clock:   ticks_per_second=0, start_epoch ignored.
    Time clock:     ticks_per_second>0; L0 is seed evolved by
                    floor((now - start_epoch) * ticks_per_second) ticks.

    ``chain_params`` is per-clock so different clocks can have
    different depth / ticks_per_level / stream_ticks / packing.
    """
    name:             str
    start_epoch:      float
    ticks_per_second: float
    chain_params:     ChainParams = field(default_factory=ChainParams)

    @property
    def is_static(self) -> bool:
        return self.ticks_per_second <= 0.0

    def tick_n_at(self, wall_time: Optional[float] = None) -> int:
        """How many CA ticks the mother has advanced by ``wall_time``.
        Defaults to ``time.time()``.  Always 0 for static clocks."""
        if self.is_static:
            return 0
        t = time.time() if wall_time is None else wall_time
        dt = max(0.0, t - self.start_epoch)
        return int(dt * self.ticks_per_second)

    @classmethod
    def static(cls, params: Optional[ChainParams] = None) -> 'Clock':
        return cls(name=DEFAULT_CLOCK_NAME, start_epoch=0.0,
                       ticks_per_second=0.0,
                       chain_params=params or ChainParams())

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def parse_tick_rate(spec: str) -> float:
    """Parse a human tick-rate spec into ticks_per_second.

    Accepts:  "1/sec", "3/sec", "1/min", "1/hour", "1/day",
              "365/year", "0.5", or a bare float (ticks_per_second).
    """
    s = spec.strip().lower()
    if '/' not in s:
        return float(s)
    n_str, denom = s.split('/', 1)
    n = float(n_str.strip())
    denom = denom.strip()
    units = {
        'sec': 1, 's': 1, 'second': 1, 'seconds': 1,
        'min': 60, 'minute': 60, 'minutes': 60, 'm': 60,
        'hour': 3600, 'hours': 3600, 'hr': 3600, 'h': 3600,
        'day': 86400, 'days': 86400, 'd': 86400,
        'week': 604800, 'weeks': 604800, 'w': 604800,
        'year': 31557600, 'years': 31557600, 'yr': 31557600, 'y': 31557600,
    }
    if denom not in units:
        raise ValueError(f'unknown time unit: {denom!r}')
    return n / units[denom]


def format_tick_rate(tps: float) -> str:
    """Human-readable inverse of parse_tick_rate."""
    if tps <= 0:
        return 'static'
    if tps >= 1.0:
        return f'{tps:.3f}/sec'
    if tps * 60 >= 1.0:
        return f'{tps*60:.3f}/min'
    if tps * 3600 >= 1.0:
        return f'{tps*3600:.3f}/hour'
    if tps * 86400 >= 1.0:
        return f'{tps*86400:.3f}/day'
    return f'{tps*31557600:.3f}/year'


def _time_shifted_seed(seed_bytes: bytes, clock: Clock,
                           wall_time: Optional[float] = None) -> bytes:
    """Return the mother CA's LUT bytes at this clock's current tick.

    For a static clock this is the original seed.  For a time clock,
    we run the seed rule on its own LUT for ``clock.tick_n_at(t)``
    ticks — the result becomes the L0 rule for the chain.
    """
    if clock.is_static:
        return seed_bytes
    tick_n = clock.tick_n_at(wall_time)
    if tick_n == 0:
        return seed_bytes
    # Run the seed rule against its own LUT as image for tick_n ticks.
    # That's exactly what chain_seeds(depth=2, ticks_per_level=tick_n)
    # computes for level 1 — but reified to one shot for clarity.
    from .metachain import _initial_grid, _run_ca
    import numpy as np
    state = _initial_grid(seed_bytes)
    final, _act = _run_ca(state, seed_bytes, tick_n)
    return bytes(final.flatten().tolist())


def regenerate_db(seed_bytes: bytes,
                    params_or_clock,
                    wall_time: Optional[float] = None) -> dict[int, bytes]:
    """Materialise the full DB (eager mode).

    ``params_or_clock`` accepts either a bare ``ChainParams`` (legacy)
    or a ``Clock`` (preferred).  Static clock = old behaviour.
    """
    from .metachain import chain_seeds, run_ca_stream
    seed_sha = compute_seed_sha(seed_bytes)
    if isinstance(params_or_clock, Clock):
        clock = params_or_clock
    else:
        clock = Clock.static(params_or_clock)
    params = clock.chain_params
    l0 = _time_shifted_seed(seed_bytes, clock, wall_time)
    levels = chain_seeds(l0, depth=params.depth,
                            ticks_per_level=params.ticks_per_level)
    out: dict[int, bytes] = {}
    tick_n = clock.tick_n_at(wall_time)
    for i, rule in enumerate(levels):
        chunks = []
        for s in range(params.streams_per_level):
            init = stream_init_seed(seed_sha, i, s,
                                          clock.name, tick_n)
            chunks.append(run_ca_stream(
                rule, init_seed=init, ticks=params.stream_ticks,
                packed=params.packed))
        out[i] = b''.join(chunks)
    return out


def regenerate_db_concat(seed_bytes: bytes,
                            params: ChainParams) -> bytes:
    """Same DB but emitted as one flat blob so ``offset`` is a single
    absolute integer.  Handy for FUSE / mmap-style consumers."""
    levels = regenerate_db(seed_bytes, params)
    parts = [levels[i] for i in sorted(levels)]
    return b''.join(parts)


# ─── Lazy backend — regenerate-on-read ───────────────────────────────
#
# Lets a 16 GB or 1 TB DB be "mounted" instantly: nothing is computed
# until something reads it.  Each (level, stream_index) tuple is
# cached on first touch with an LRU policy so re-reading the same
# stream is free, but unread streams cost nothing.

class ChainBackend:
    """On-demand byte producer for one (seed, clock) keychain axis.

    Reads honour the 3-D address ``(level, stream_index, byte_offset)``;
    the clock determines the L0 rule (static = seed itself; time clock
    = seed evolved by N ticks where N depends on wall-clock time).

    Pass ``wall_time`` to freeze the backend at a specific instant
    (handy for time-anchored tags so re-reads stay consistent).
    """

    def __init__(self, seed_bytes: bytes,
                    params_or_clock,
                    rule_cache: int = 64, stream_cache: int = 16,
                    wall_time: Optional[float] = None):
        from collections import OrderedDict
        if isinstance(params_or_clock, Clock):
            self.clock = params_or_clock
        else:
            self.clock = Clock.static(params_or_clock)
        self.params = self.clock.chain_params
        self.seed = seed_bytes
        self.seed_sha = compute_seed_sha(seed_bytes)
        self.wall_time = wall_time
        self.tick_n = self.clock.tick_n_at(wall_time)
        # L0 for this clock at this wall time:
        self._l0: Optional[bytes] = None
        self._rule_cache: 'OrderedDict[int, bytes]' = OrderedDict()
        self._stream_cache: 'OrderedDict[tuple, bytes]' = OrderedDict()
        self._rule_cap = rule_cache
        self._stream_cap = stream_cache

    def _ensure_l0(self) -> bytes:
        if self._l0 is None:
            self._l0 = _time_shifted_seed(self.seed, self.clock,
                                                self.wall_time)
        return self._l0

    def _rule(self, level: int) -> bytes:
        if level in self._rule_cache:
            self._rule_cache.move_to_end(level)
            return self._rule_cache[level]
        from .metachain import chain_seeds
        levels = chain_seeds(
            self._ensure_l0(), depth=level + 1,
            ticks_per_level=self.params.ticks_per_level)
        for i, rb in enumerate(levels):
            self._rule_cache[i] = rb
        while len(self._rule_cache) > self._rule_cap:
            self._rule_cache.popitem(last=False)
        return self._rule_cache[level]

    def _stream(self, level: int, stream_index: int) -> bytes:
        key = (level, stream_index)
        if key in self._stream_cache:
            self._stream_cache.move_to_end(key)
            return self._stream_cache[key]
        from .metachain import run_ca_stream
        init = stream_init_seed(self.seed_sha, level, stream_index,
                                       self.clock.name, self.tick_n)
        s = run_ca_stream(
            self._rule(level), init_seed=init,
            ticks=self.params.stream_ticks,
            packed=self.params.packed)
        self._stream_cache[key] = s
        if len(self._stream_cache) > self._stream_cap:
            self._stream_cache.popitem(last=False)
        return s

    def read(self, level: int, stream_index: int,
                start: int, end: int) -> bytes:
        bps = self.params.bytes_per_stream()
        if not (0 <= start < end <= bps):
            raise ValueError(
                f'slice [{start}:{end}) outside stream of size {bps}')
        return self._stream(level, stream_index)[start:end]

    def cells_per_stream(self) -> int:
        """How many K=4 cells (0..3) live in one stream — depends on
        whether the stream is packed (4 cells/byte) or raw (1 cell/byte).
        """
        bps = self.params.bytes_per_stream()
        return bps * 4 if self.params.packed else bps

    def read_cells(self, level: int, stream_index: int,
                      cell_start: int, cell_end: int) -> bytes:
        """Return ``cell_end - cell_start`` cell values (each byte ∈ {0,1,2,3}).

        Coordinates are in *cells*, not packed bytes — so for a 16-KB
        packed stream the valid range is ``[0, 65536)``.  Reads the
        underlying packed bytes from the same on-disk source as
        :meth:`read`, then unpacks just the needed slice.  No extra
        storage; the cell view is a free interpretation of the data
        already in the DB.

        Use this for UI masks (visibility, palette index, 4-state
        regions, etc.) while ``read()`` continues to serve file content.
        """
        from .metachain import unpack_k4_bytes
        total = self.cells_per_stream()
        if not (0 <= cell_start < cell_end <= total):
            raise ValueError(
                f'cell slice [{cell_start}:{cell_end}) outside stream of '
                f'{total} cells')
        stream = self._stream(level, stream_index)
        if not self.params.packed:
            # Stream is already 1-byte-per-cell; just slice.
            return stream[cell_start:cell_end]
        byte_start = cell_start // 4
        byte_end   = (cell_end + 3) // 4
        chunk      = stream[byte_start:byte_end]
        unpacked   = unpack_k4_bytes(chunk)
        # The unpacked chunk starts at cell `byte_start * 4`; offset
        # within it is the residual.
        off = cell_start - byte_start * 4
        return unpacked[off:off + (cell_end - cell_start)]

    def read_concat(self, abs_start: int, abs_end: int) -> bytes:
        bps = self.params.bytes_per_stream()
        bpl = self.params.bytes_per_level()
        total = self.params.total_bytes()
        if not (0 <= abs_start < abs_end <= total):
            raise ValueError(
                f'slice [{abs_start}:{abs_end}) outside DB of size {total}')
        out = bytearray()
        cursor = abs_start
        while cursor < abs_end:
            level = cursor // bpl
            in_level = cursor - level * bpl
            stream_index = in_level // bps
            in_stream = in_level - stream_index * bps
            chunk_end = min(bps, in_stream + (abs_end - cursor))
            out.extend(self._stream(level, stream_index)[in_stream:chunk_end])
            cursor += chunk_end - in_stream
        return bytes(out)

    def mother_state(self, wall_time: Optional[float] = None) -> bytes:
        """Return the mother CA's 16,384-byte LUT state at ``wall_time``
        (defaults to the backend's pinned time, then to ``time.time()``)
        — useful for archive snapshots."""
        if wall_time is None and self.wall_time is None:
            return self._ensure_l0()
        return _time_shifted_seed(self.seed, self.clock, wall_time)


# ─── Tag index ───────────────────────────────────────────────────────

@dataclass
class FileEntry:
    """One tagged byte-range = one virtual file.

    ``clock_name`` says which clock this tag is addressed against
    (default ``'static'``).  When the clock is time-evolving,
    ``wall_anchor`` is the unix-time at which the bytes were captured
    — the tag stays valid by reading the backend pinned to that
    instant.  ``wall_anchor=None`` on a non-static clock means
    "always read at current wall-clock time" (live).
    """
    id:            str
    name:          str
    level:         int
    byte_start:    int
    byte_end:      int                  # exclusive
    stream_index:  int          = 0
    clock_name:    str          = DEFAULT_CLOCK_NAME
    wall_anchor:   Optional[float] = None
    mime:          str          = 'application/octet-stream'
    tags:          list[str]    = field(default_factory=list)
    sha256:        str          = ''
    created_at:    float        = field(default_factory=time.time)
    overlay_path:  Optional[str] = None
    # Read interpretation: 'packed' = 1 byte per 4 cells (file
    # content); 'cells' = 1 byte per cell ∈ {0,1,2,3} (UI masks,
    # 4-state regions).  When 'cells', byte_start/byte_end are
    # *cell* indices and slice_from() returns 4× more bytes than
    # the same range in 'packed' mode.
    mode:          str          = 'packed'

    @property
    def size(self) -> int:
        return self.byte_end - self.byte_start

    def as_dict(self) -> dict:
        return asdict(self)

    def slice_from(self, backend_or_db) -> bytes:
        """Read this file's content.

        ``backend_or_db`` accepts either:
          - a ``ChainBackend`` (preferred — clock-aware)
          - a ``KeychainIndex`` (looks up the right backend by
            ``clock_name`` and ``wall_anchor`` automatically)
          - a legacy ``{level: bytes}`` dict (static, single-stream).

        Dispatches on :attr:`mode`:
          - ``'packed'`` (default): byte_start/byte_end are packed-byte
            indices; returns the raw file content.
          - ``'cells'``: byte_start/byte_end are CELL indices into the
            unpacked 4-color stream; returns one byte per cell ∈ {0..3}
            for use as UI masks.
        """
        if self.overlay_path:
            try:
                return Path(self.overlay_path).read_bytes()
            except FileNotFoundError:
                pass
        if isinstance(backend_or_db, KeychainIndex):
            backend = backend_or_db.backend(self.clock_name,
                                                  wall_time=self.wall_anchor)
        elif isinstance(backend_or_db, ChainBackend):
            backend = backend_or_db
        else:
            # Legacy dict: only supports packed mode (no chain backend
            # to unpack from).  Mode='cells' on a legacy dict raises.
            if self.mode == 'cells':
                raise NotImplementedError(
                    'cells-mode slice requires a ChainBackend; '
                    'got a legacy {level: bytes} dict')
            return backend_or_db[self.level][self.byte_start:self.byte_end]
        if self.mode == 'cells':
            return backend.read_cells(self.level, self.stream_index,
                                          self.byte_start, self.byte_end)
        return backend.read(self.level, self.stream_index,
                                self.byte_start, self.byte_end)


@dataclass
class KeychainIndex:
    """Multi-clock keychain index (format_version=2).

    The legacy v1 index (single ``chain_params``, no clocks) loads
    transparently — see ``from_json`` for the migration rule.
    """
    seed_sha256:    str
    clocks:         list[Clock]      = field(default_factory=list)
    format_version: int              = 2
    files:          list[FileEntry]  = field(default_factory=list)
    notes:          str              = ''

    # ─── construction helpers ─────────────────────────────────────

    @classmethod
    def fresh(cls, seed_bytes: bytes,
                params: Optional[ChainParams] = None) -> 'KeychainIndex':
        return cls(
            seed_sha256=compute_seed_sha(seed_bytes),
            clocks=[Clock.static(params)],
        )

    @property
    def chain_params(self) -> ChainParams:
        """Convenience: params for the 'static' clock (back-compat)."""
        c = self.get_clock(DEFAULT_CLOCK_NAME)
        return c.chain_params if c else ChainParams()

    def get_clock(self, name: str) -> Optional[Clock]:
        for c in self.clocks:
            if c.name == name:
                return c
        return None

    def add_clock(self, clock: Clock) -> None:
        if self.get_clock(clock.name):
            raise ValueError(f'clock {clock.name!r} already exists')
        self.clocks.append(clock)

    def remove_clock(self, name: str) -> bool:
        if name == DEFAULT_CLOCK_NAME:
            raise ValueError("can't remove the 'static' clock")
        # Refuse if any file references it.
        in_use = [f.id for f in self.files if f.clock_name == name]
        if in_use:
            raise ValueError(
                f'clock {name!r} is referenced by {len(in_use)} file(s): '
                f'{in_use[:5]}{"…" if len(in_use) > 5 else ""}')
        before = len(self.clocks)
        self.clocks = [c for c in self.clocks if c.name != name]
        return len(self.clocks) != before

    def backend(self, clock_name: str = DEFAULT_CLOCK_NAME,
                  wall_time: Optional[float] = None) -> ChainBackend:
        clock = self.get_clock(clock_name)
        if clock is None:
            raise KeyError(f'no clock named {clock_name!r}')
        return ChainBackend(self._seed_bytes(), clock,
                              wall_time=wall_time)

    def _seed_bytes(self) -> bytes:
        if not hasattr(self, '_seed_cache') or self._seed_cache is None:
            self._seed_cache = load_seed(self.seed_sha256)
        return self._seed_cache

    # ─── serialisation ────────────────────────────────────────────

    def to_json(self) -> str:
        payload = {
            'format_version': self.format_version,
            'seed_sha256':    self.seed_sha256,
            'clocks':         [c.as_dict() for c in self.clocks],
            'notes':          self.notes,
            'files':          [f.as_dict() for f in self.files],
        }
        return json.dumps(payload, indent=2, sort_keys=False)

    @classmethod
    def from_json(cls, text: str) -> 'KeychainIndex':
        payload = json.loads(text)
        fmt = int(payload.get('format_version', 1))
        if fmt == 1:
            # v1 → v2 migration: wrap the single chain_params as a
            # 'static' clock; every file inherits clock_name='static'.
            params = ChainParams(**payload.get('chain_params', {}))
            idx = cls(
                seed_sha256=payload['seed_sha256'],
                clocks=[Clock.static(params)],
                format_version=2,
                notes=payload.get('notes', ''),
            )
            for f in payload.get('files', []):
                # FileEntry gained new fields in v2; pass everything we
                # know about plus the defaults.
                f.setdefault('clock_name', DEFAULT_CLOCK_NAME)
                f.setdefault('wall_anchor', None)
                idx.files.append(FileEntry(**f))
            return idx
        # v2 path.
        clocks = []
        for cd in payload.get('clocks', []):
            params = ChainParams(**(cd.get('chain_params') or {}))
            clocks.append(Clock(
                name=cd['name'],
                start_epoch=float(cd['start_epoch']),
                ticks_per_second=float(cd['ticks_per_second']),
                chain_params=params,
            ))
        idx = cls(
            seed_sha256=payload['seed_sha256'],
            clocks=clocks,
            format_version=fmt,
            notes=payload.get('notes', ''),
        )
        for f in payload.get('files', []):
            idx.files.append(FileEntry(**f))
        return idx

    # ─── CRUD ────────────────────────────────────────────────────

    def _next_id(self) -> str:
        used = {f.id for f in self.files}
        n = len(self.files)
        while True:
            cand = f'f{n+1:04d}'
            if cand not in used:
                return cand
            n += 1

    def add(self, *, name: str, level: int, byte_start: int,
              byte_end: int, stream_index: int = 0,
              clock_name: str = DEFAULT_CLOCK_NAME,
              wall_anchor: Optional[float] = None,
              mime: str = 'application/octet-stream',
              tags: Optional[Iterable[str]] = None,
              mode: str = 'packed',
              db=None) -> FileEntry:
        """Register a new file.  ``db`` (a ChainBackend or KeychainIndex)
        captures the content sha at tag time.  ``wall_anchor`` snapshots
        a specific instant for time-evolving clocks.

        ``mode`` selects the read interpretation: ``'packed'`` (default,
        file content — 1 byte per 4 cells) or ``'cells'`` (UI mask — 1
        byte per cell ∈ {0..3}, indices are in cells not bytes)."""
        clock = self.get_clock(clock_name)
        if clock is None:
            raise ValueError(f'no clock named {clock_name!r}')
        params = clock.chain_params
        if byte_end <= byte_start:
            raise ValueError('byte_end must be > byte_start')
        if level < 0 or level >= params.depth:
            raise ValueError(
                f'level {level} outside [0, {params.depth})')
        if not (0 <= stream_index < params.streams_per_level):
            raise ValueError(
                f'stream_index {stream_index} outside '
                f'[0, {params.streams_per_level})')
        if mode == 'cells':
            max_units = (params.bytes_per_stream() * 4
                              if params.packed else params.bytes_per_stream())
            unit = 'cells'
        else:
            max_units = params.bytes_per_stream()
            unit = 'bytes'
        if byte_end > max_units:
            raise ValueError(
                f'byte_end {byte_end} > stream size {max_units} ({unit})')
        if wall_anchor is None and not clock.is_static:
            wall_anchor = time.time()
        entry = FileEntry(
            id=self._next_id(), name=name, level=level,
            byte_start=byte_start, byte_end=byte_end,
            stream_index=stream_index, clock_name=clock_name,
            wall_anchor=wall_anchor,
            mime=mime, tags=list(tags or []),
            mode=mode,
        )
        if db is not None:
            entry.sha256 = hashlib.sha256(entry.slice_from(db)).hexdigest()
        self.files.append(entry)
        return entry

    def remove(self, file_id: str) -> bool:
        before = len(self.files)
        self.files = [f for f in self.files if f.id != file_id]
        return len(self.files) != before

    def get(self, file_id: str) -> Optional[FileEntry]:
        for f in self.files:
            if f.id == file_id:
                return f
        return None

    def find_by_name(self, name: str) -> Optional[FileEntry]:
        for f in self.files:
            if f.name == name:
                return f
        return None

    # ─── verification ────────────────────────────────────────────

    def verify(self, db=None) -> list[tuple[str, str]]:
        """Recompute every file's content sha256 and report drift.

        Returns ``[(file_id, reason)]`` for any mismatches.  If ``db``
        is None we resolve each file's backend via its clock.
        """
        problems: list[tuple[str, str]] = []
        for f in self.files:
            if not f.sha256:
                continue
            source = db if db is not None else self
            try:
                got = hashlib.sha256(f.slice_from(source)).hexdigest()
            except (IndexError, KeyError, ValueError) as e:
                problems.append((f.id, f'cannot read slice: {e}'))
                continue
            if got != f.sha256:
                problems.append((f.id, f'sha mismatch '
                                          f'(expected {f.sha256[:8]}…, got {got[:8]}…)'))
        return problems


# ─── On-disk store ────────────────────────────────────────────────────

def keychain_root(base_dir: Optional[Path] = None) -> Path:
    """The directory that holds every keychain on this machine."""
    if base_dir is None:
        from django.conf import settings
        base_dir = Path(settings.BASE_DIR)
    return Path(base_dir) / '.keychains'


def keychain_dir(seed_sha256: str,
                    base_dir: Optional[Path] = None) -> Path:
    return keychain_root(base_dir) / seed_sha256


def index_path(seed_sha256: str,
                 base_dir: Optional[Path] = None) -> Path:
    return keychain_dir(seed_sha256, base_dir) / 'index.json'


def seed_path(seed_sha256: str,
                base_dir: Optional[Path] = None) -> Path:
    return keychain_dir(seed_sha256, base_dir) / 'seed.bin'


def list_known(base_dir: Optional[Path] = None) -> list[str]:
    """Return every seed_sha256 we have an index for."""
    root = keychain_root(base_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def load_index(seed_sha256: str,
                 base_dir: Optional[Path] = None) -> KeychainIndex:
    p = index_path(seed_sha256, base_dir)
    if not p.exists():
        raise FileNotFoundError(f'no index for {seed_sha256[:12]}')
    return KeychainIndex.from_json(p.read_text())


def save_index(idx: KeychainIndex,
                 base_dir: Optional[Path] = None) -> Path:
    d = keychain_dir(idx.seed_sha256, base_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / 'index.json'
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(idx.to_json())
    os.replace(tmp, p)
    return p


def save_seed(seed_bytes: bytes,
                 base_dir: Optional[Path] = None) -> Path:
    sha = compute_seed_sha(seed_bytes)
    d = keychain_dir(sha, base_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / 'seed.bin'
    p.write_bytes(seed_bytes)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def load_seed(seed_sha256: str,
                base_dir: Optional[Path] = None) -> bytes:
    p = seed_path(seed_sha256, base_dir)
    if not p.exists():
        raise FileNotFoundError(f'no seed for {seed_sha256[:12]}')
    return p.read_bytes()


def register_keychain(seed_bytes: bytes, *,
                         params: Optional[ChainParams] = None,
                         notes: str = '',
                         base_dir: Optional[Path] = None) -> KeychainIndex:
    """Create a keychain dir + seed + empty index in one call.

    Idempotent on the seed sha: if the keychain already exists, returns
    the existing index untouched (so re-registering doesn't blow away
    your tags)."""
    sha = compute_seed_sha(seed_bytes)
    try:
        existing = load_index(sha, base_dir)
        return existing
    except FileNotFoundError:
        pass
    idx = KeychainIndex.fresh(seed_bytes, params)
    idx.notes = notes
    save_seed(seed_bytes, base_dir)
    save_index(idx, base_dir)
    return idx


# ─── Region scanner — find candidate file boundaries ─────────────────
#
# Useful when the user wants to "look through the binary outputs" and
# tag interesting spans without having to scroll byte-by-byte.

def scan_regions(stream: bytes, *,
                   min_run: int = 16,
                   ascii_window: int = 32) -> list[dict]:
    """Heuristic boundary finder for a single level's packed stream.

    Returns a list of candidate regions, each:

        {
          'kind':   'zero-run' | 'ascii-burst' | 'entropy-shift',
          'start':  int,   # byte offset within the stream
          'end':    int,   # exclusive
          'length': int,
          'note':   str,
        }

    Three cheap detectors:

    - zero-runs of ≥ ``min_run`` bytes  → potential padding / break
    - sliding windows where ≥75% of bytes are printable ASCII → text
    - sliding-window entropy shifts > 1 bit / byte between adjacent
      windows  → potential file-format boundary
    """
    import math
    from collections import Counter

    out: list[dict] = []
    n = len(stream)

    # Zero runs.
    i = 0
    while i < n:
        if stream[i] == 0:
            j = i
            while j < n and stream[j] == 0:
                j += 1
            if j - i >= min_run:
                out.append({
                    'kind':   'zero-run',
                    'start':  i,
                    'end':    j,
                    'length': j - i,
                    'note':   f'{j - i} consecutive 0x00 bytes',
                })
            i = j
        else:
            i += 1

    # ASCII bursts.
    def is_printable(b: int) -> bool:
        return 0x20 <= b < 0x7F or b in (0x09, 0x0A, 0x0D)
    win = ascii_window
    in_burst = False
    burst_start = 0
    for i in range(0, n - win, win // 2):
        sl = stream[i:i + win]
        printable = sum(1 for b in sl if is_printable(b))
        ratio = printable / win
        if ratio >= 0.75 and not in_burst:
            in_burst = True
            burst_start = i
        elif ratio < 0.5 and in_burst:
            in_burst = False
            if i - burst_start >= win:
                out.append({
                    'kind':   'ascii-burst',
                    'start':  burst_start,
                    'end':    i,
                    'length': i - burst_start,
                    'note':   f'{(i - burst_start)} bytes ≥75% printable',
                })

    # Entropy shifts.
    block = 256
    if n >= 2 * block:
        def H(buf: bytes) -> float:
            c = Counter(buf)
            total = sum(c.values())
            return -sum((v/total) * math.log2(v/total) for v in c.values())
        prev_H = H(stream[:block])
        for j in range(block, n - block, block):
            cur_H = H(stream[j:j + block])
            if abs(cur_H - prev_H) >= 1.0:
                out.append({
                    'kind':   'entropy-shift',
                    'start':  j,
                    'end':    j + 1,
                    'length': 1,
                    'note':   f'ΔH = {cur_H - prev_H:+.2f} bits/byte across boundary',
                })
            prev_H = cur_H

    return sorted(out, key=lambda r: (r['start'], r['kind']))

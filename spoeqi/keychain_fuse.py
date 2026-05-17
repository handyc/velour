"""FUSE adapter for the keychain virtual filesystem.

Mounts a keychain's tagged files at a real mountpoint so they appear
as actual files to ``ls``, ``cat``, ``cp``, ``grep``, file managers,
etc.  Read-only; writes are denied.

Layout under the mountpoint:

    /<mount>/
        files/                 — tagged files at their human names
            <file.bin>         — each FileEntry's name (deduped on collision)
            <another.dat>
        levels/                — raw per-clock per-level dumps
            <clock>/L00.bin
            <clock>/L01.bin
            ...
        meta/                  — read-only metadata
            index.json
            seed-sha256
            clocks.txt

The static-clock files live at the top of /files/; time-evolving
clocks get sub-directories so wall_anchor disambiguates collisions:

    /files/static/notes.txt
    /files/slow/2026-05-20T08:00/morning.bin
    /files/fast/0000003142.bin

Read calls go through ``ChainBackend.read`` so bytes are produced on
demand.  Backends are cached per (clock, wall_anchor) so repeated
reads within one mount session don't re-compute the chain.
"""
from __future__ import annotations

import errno
import os
import re
import stat
import time
from typing import Optional

# fusepy's module-level code tries to load ``libfuse.so.2`` from the
# system and raises EnvironmentError if it is missing.  We want this
# module to be importable everywhere so the rest of the keychain CLI
# still works on systems without FUSE.

try:
    from fuse import FUSE, FuseOSError, Operations as _Operations
    HAS_FUSE = True
    FUSE_IMPORT_ERROR: 'Optional[Exception]' = None
except (ImportError, EnvironmentError) as _e:
    HAS_FUSE = False
    FUSE = None
    FuseOSError = OSError                          # type: ignore
    _Operations = object                            # type: ignore
    FUSE_IMPORT_ERROR = _e

from .keychain import (KeychainIndex, ChainBackend, FileEntry,
                         load_index, load_seed, keychain_dir)


_SAFE = re.compile(r'[^A-Za-z0-9._-]+')


def _safe_name(name: str) -> str:
    """Make a name filesystem-safe (no /, no NULs)."""
    s = _SAFE.sub('_', name.strip()).strip('._')
    return s or 'unnamed'


class KeychainFS(_Operations):
    """One FUSE filesystem per keychain (one seed_sha)."""

    def __init__(self, seed_sha256: str):
        self.idx = load_index(seed_sha256)
        self.seed = load_seed(seed_sha256)
        self.seed_sha = seed_sha256
        # Per-clock backend cache.  Wall-anchored tags get their own
        # backend keyed by (clock_name, wall_anchor); live tags share
        # the live backend per clock.
        self._backends: dict = {}
        # Build the virtual tree once at mount time.  Re-mounting picks
        # up any new tags written since.
        self._tree = self._build_tree()

    # ─── tree construction ───────────────────────────────────────

    def _build_tree(self) -> dict:
        """Return a nested dict mapping path → dict (dir) or FileEntry."""
        tree: dict = {
            'files':  {},
            'levels': {},
            'meta':   {},
        }

        # /files/<clock>/<name>
        for f in self.idx.files:
            clock_dir = tree['files'].setdefault(f.clock_name, {})
            name = _safe_name(f.name)
            # If the file is anchored to a wall time, put it in a date
            # subdir so multiple snapshots at different times don't
            # collide on name.
            if f.wall_anchor:
                t = time.gmtime(f.wall_anchor)
                date_dir = time.strftime('%Y-%m-%dT%H-%M-%S', t)
                d = clock_dir.setdefault(date_dir, {})
                d[name] = f
            else:
                # Static clock — just by name (with index suffix on
                # collision).
                if name in clock_dir:
                    j = 2
                    while f'{name}.{j}' in clock_dir:
                        j += 1
                    name = f'{name}.{j}'
                clock_dir[name] = f

        # /levels/<clock>/L<NN>.bin (one virtual per-level dump)
        for c in self.idx.clocks:
            depth = c.chain_params.depth
            level_dir = {}
            for i in range(depth):
                level_dir[f'L{i:02d}.bin'] = ('level', c.name, i)
            tree['levels'][c.name] = level_dir

        # /meta/...
        tree['meta']['index.json']  = ('text', self.idx.to_json())
        tree['meta']['seed-sha256'] = ('text', self.seed_sha + '\n')
        clocks_lines = []
        for c in self.idx.clocks:
            from .keychain import format_tick_rate
            clocks_lines.append(
                f'{c.name:<12s}  rate={format_tick_rate(c.ticks_per_second)}  '
                f'start_epoch={c.start_epoch:.0f}  '
                f'tick_n_now={c.tick_n_at()}')
        tree['meta']['clocks.txt'] = ('text', '\n'.join(clocks_lines) + '\n')

        return tree

    # ─── path resolution ─────────────────────────────────────────

    def _resolve(self, path: str):
        """Return the tree node at ``path``.  None if missing.

        Returns either a dict (directory) or a tuple/FileEntry (leaf).
        """
        if path == '/':
            return self._tree
        parts = [p for p in path.split('/') if p]
        node = self._tree
        for p in parts:
            if isinstance(node, dict):
                if p not in node:
                    return None
                node = node[p]
            else:
                return None
        return node

    def _backend_for(self, clock_name: str,
                       wall_anchor: Optional[float]) -> ChainBackend:
        key = (clock_name, wall_anchor)
        if key in self._backends:
            return self._backends[key]
        clock = self.idx.get_clock(clock_name)
        if clock is None:
            raise FuseOSError(errno.ENOENT)
        be = ChainBackend(self.seed, clock, wall_time=wall_anchor)
        self._backends[key] = be
        return be

    # ─── FUSE operations ─────────────────────────────────────────

    def getattr(self, path, fh=None):
        now = time.time()
        node = self._resolve(path)
        if node is None:
            raise FuseOSError(errno.ENOENT)
        attr = {
            'st_uid':   os.getuid(),
            'st_gid':   os.getgid(),
            'st_atime': now,
            'st_mtime': now,
            'st_ctime': now,
            'st_nlink': 1,
        }
        if isinstance(node, dict):
            attr['st_mode'] = stat.S_IFDIR | 0o555
            attr['st_size'] = 0
            attr['st_nlink'] = 2 + len(node)
            return attr

        if isinstance(node, FileEntry):
            attr['st_mode'] = stat.S_IFREG | 0o444
            attr['st_size'] = node.size
            attr['st_mtime'] = node.created_at
            return attr

        # Synthetic leaves: ('text', body) or ('level', clock, i)
        if isinstance(node, tuple):
            kind = node[0]
            if kind == 'text':
                body = node[1].encode('utf-8')
                attr['st_mode'] = stat.S_IFREG | 0o444
                attr['st_size'] = len(body)
                return attr
            if kind == 'level':
                _, clock_name, level = node
                clock = self.idx.get_clock(clock_name)
                if clock is None:
                    raise FuseOSError(errno.ENOENT)
                attr['st_mode'] = stat.S_IFREG | 0o444
                attr['st_size'] = (clock.chain_params.bytes_per_level()
                                       if level < clock.chain_params.depth
                                       else 0)
                return attr
        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        node = self._resolve(path)
        if not isinstance(node, dict):
            raise FuseOSError(errno.ENOTDIR)
        return ['.', '..'] + sorted(node.keys())

    def open(self, path, flags):
        # Read-only: deny write flags.
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_TRUNC):
            raise FuseOSError(errno.EROFS)
        node = self._resolve(path)
        if node is None or isinstance(node, dict):
            raise FuseOSError(errno.ENOENT)
        return 0

    def read(self, path, size, offset, fh):
        node = self._resolve(path)
        if node is None:
            raise FuseOSError(errno.ENOENT)

        if isinstance(node, FileEntry):
            be = self._backend_for(node.clock_name, node.wall_anchor)
            # Slice carefully — the file's byte range is into one
            # stream; size+offset are *within* that file.
            start = node.byte_start + offset
            end   = min(node.byte_start + offset + size, node.byte_end)
            if start >= node.byte_end:
                return b''
            return be.read(node.level, node.stream_index, start, end)

        if isinstance(node, tuple):
            kind = node[0]
            if kind == 'text':
                body = node[1].encode('utf-8')
                return body[offset:offset + size]
            if kind == 'level':
                _, clock_name, level = node
                be = self._backend_for(clock_name, None)
                clock = self.idx.get_clock(clock_name)
                bps = clock.chain_params.bytes_per_stream()
                # For multi-stream levels, the "L<NN>.bin" file is the
                # full level (all streams concatenated).
                spl = clock.chain_params.streams_per_level
                if spl == 1:
                    end = min(offset + size, bps)
                    return be.read(level, 0, offset, end)
                # Multi-stream: stream chunks together.
                out = bytearray()
                cursor = offset
                target_end = offset + size
                level_size = bps * spl
                target_end = min(target_end, level_size)
                while cursor < target_end:
                    stream_index = cursor // bps
                    in_stream = cursor - stream_index * bps
                    chunk_end = min(bps, in_stream + (target_end - cursor))
                    out.extend(be.read(level, stream_index, in_stream,
                                           chunk_end))
                    cursor += chunk_end - in_stream
                return bytes(out)

        raise FuseOSError(errno.ENOENT)

    # Read-only filesystem — deny mutating operations.

    def write(self, *a, **kw):    raise FuseOSError(errno.EROFS)
    def truncate(self, *a, **kw): raise FuseOSError(errno.EROFS)
    def create(self, *a, **kw):   raise FuseOSError(errno.EROFS)
    def unlink(self, *a, **kw):   raise FuseOSError(errno.EROFS)
    def mkdir(self, *a, **kw):    raise FuseOSError(errno.EROFS)
    def rmdir(self, *a, **kw):    raise FuseOSError(errno.EROFS)
    def chmod(self, *a, **kw):    raise FuseOSError(errno.EROFS)
    def chown(self, *a, **kw):    raise FuseOSError(errno.EROFS)


def mount_keychain(seed_sha256: str, mountpoint: str,
                       foreground: bool = True,
                       debug: bool = False) -> None:
    """Mount a keychain at ``mountpoint``.  In foreground mode the
    call blocks until the FS is unmounted (Ctrl-C or fusermount -u).
    """
    if not HAS_FUSE:
        raise RuntimeError(
            'fusepy + libfuse2 are required for keychain mount.\n'
            '  Install fusepy: venv/bin/python -m pip install fusepy\n'
            '  Install libfuse2 (Linux): sudo apt-get install libfuse2\n'
            '  (macOS: macFUSE from osxfuse.github.io)\n'
            f'  original error: {FUSE_IMPORT_ERROR}')
    fs = KeychainFS(seed_sha256)
    FUSE(fs, mountpoint, foreground=foreground, ro=True,
              nothreads=True, allow_other=False, debug=debug)

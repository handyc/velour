"""manage.py keychain — quine-keychain filesystem CLI.

Subcommands:

    register <quine_pk_or_seed_path>     create a new keychain
    list                                  list known keychains
    info <sha-prefix>                     show one keychain's summary
    regen <sha-prefix>                    regenerate the DB to disk
    dump <sha-prefix> <level>             write one level's stream to a file
    scan <sha-prefix> <level>             list candidate file boundaries
    ls <sha-prefix>                       list tagged files
    tag <sha-prefix> --level N \
         --start S --end E --name NAME    add a virtual file
    untag <sha-prefix> <file_id>          remove a virtual file
    rename <sha-prefix> <file_id> <new>   rename a virtual file
    extract <sha-prefix> <file_id>        write a file's bytes to stdout
                                          (or to -o PATH)
    verify <sha-prefix>                   recompute every file sha and
                                          report drift (firmware /
                                          chain-param mismatch detector)

All commands accept a partial sha (anything that uniquely matches a
known keychain).  Use ``list`` to see the full sha for each.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from spoeqi import keychain as kc


# ─── helpers ──────────────────────────────────────────────────────────

def _resolve_sha(prefix: str) -> str:
    known = kc.list_known()
    if not known:
        raise CommandError('no keychains registered. '
                              'Use `keychain register <quine_pk>` first.')
    matches = [s for s in known if s.startswith(prefix)]
    if len(matches) == 0:
        raise CommandError(f'no keychain matches "{prefix}". '
                              f'Known: {", ".join(s[:8] for s in known)}')
    if len(matches) > 1:
        raise CommandError(
            f'sha prefix "{prefix}" is ambiguous: '
            + ', '.join(s[:12] for s in matches))
    return matches[0]


def _backend(sha: str, clock_name: str = kc.DEFAULT_CLOCK_NAME,
                 wall_time=None) -> 'kc.ChainBackend':
    """Lazy regenerator for one clock — no I/O until a read happens."""
    idx = kc.load_index(sha)
    clock = idx.get_clock(clock_name)
    if clock is None:
        raise CommandError(
            f'no clock named {clock_name!r} on this keychain. '
            f'Known: {[c.name for c in idx.clocks]}')
    seed = kc.load_seed(sha)
    return kc.ChainBackend(seed, clock, wall_time=wall_time)


def _regen_or_load(sha: str, force: bool = False) -> dict[int, bytes]:
    """Eager full-DB materialisation.  Refuses to run if the DB would
    exceed 1 GiB unless ``force=True`` — past that threshold callers
    should use the lazy backend (``_backend``) instead."""
    idx = kc.load_index(sha)
    total = idx.chain_params.total_bytes()
    if total > (1 << 30) and not force:
        raise CommandError(
            f'eager regen would materialise {total/2**30:.2f} GiB; '
            f'pass --force or use a lazy command (`ls`, `extract`, `tag`) '
            f'which only regenerates touched streams.')
    cache = kc.keychain_dir(sha) / 'cache' / 'db.bin'
    if cache.exists() and not force:
        if cache.stat().st_size == total:
            blob = cache.read_bytes()
            per = idx.chain_params.bytes_per_level()
            return {i: blob[i*per:(i+1)*per]
                    for i in range(idx.chain_params.depth)}
    seed = kc.load_seed(sha)
    db = kc.regenerate_db(seed, idx.chain_params)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b''.join(db[i] for i in sorted(db)))
    return db


def _summarise(idx: kc.KeychainIndex) -> str:
    lines = [
        f'  seed sha256       {idx.seed_sha256}',
        f'  format version    {idx.format_version}',
        f'  clocks            {len(idx.clocks)}',
    ]
    for c in idx.clocks:
        p = c.chain_params
        total = p.total_bytes()
        unit = 'GiB' if total >= (1 << 30) else 'MiB'
        div  = (1 << 30) if total >= (1 << 30) else (1 << 20)
        tick_n = c.tick_n_at()
        rate = kc.format_tick_rate(c.ticks_per_second)
        lines.append(
            f'    • {c.name:<12s}  rate={rate}  tick_n_now={tick_n}  '
            f'depth={p.depth} ticks_per_level={p.ticks_per_level} '
            f'stream_ticks={p.stream_ticks} streams_per_level={p.streams_per_level} '
            f'packed={p.packed}  DB={total/div:.2f} {unit}')
    lines.append(f'  tagged files      {len(idx.files)}')
    if idx.notes:
        lines.append(f'  notes             {idx.notes}')
    return '\n'.join(lines) + '\n'


# ─── argparse plumbing ────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Quine-keychain filesystem operations.'

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        sp = parser.add_subparsers(dest='cmd', required=True,
                                       metavar='subcommand')

        p = sp.add_parser('register', help='Create a new keychain.')
        p.add_argument('source',
                          help='Either a quine ComponentChampion pk '
                               '(integer) or a path to a 16,384-byte '
                               'seed.bin file.')
        p.add_argument('--notes', default='',
                          help='Free-form notes for the index header.')
        p.add_argument('--depth', type=int, default=kc.DEFAULT_DEPTH)
        p.add_argument('--ticks-per-level', type=int,
                          default=kc.DEFAULT_TICKS_PER_LEVEL)
        p.add_argument('--stream-ticks', type=int,
                          default=kc.DEFAULT_STREAM_TICKS)
        p.add_argument('--streams-per-level', type=int,
                          default=kc.DEFAULT_STREAMS_PER_LEVEL,
                          help='Per-level LCG-init multiplicity. Raises '
                               'addressable DB size linearly: 64 levels '
                               '× 64 ticks × N streams ≈ N × 16 MiB.')
        p.add_argument('--raw', action='store_true',
                          help='Use raw 1-byte-per-cell streams instead '
                               'of packed 4-cells/byte (4× the size).')
        p.add_argument('--reset', action='store_true',
                          help='If a keychain already exists for this '
                               'seed, replace it (drops cache + index).')

        sp.add_parser('list', help='List known keychains.')

        for name, helpmsg in (
            ('info',  'Show keychain summary.'),
            ('verify','Recompute file shas and report drift.'),
            ('ls',    'List tagged files.'),
        ):
            p = sp.add_parser(name, help=helpmsg)
            p.add_argument('sha', help='Seed sha256 (prefix OK).')

        p = sp.add_parser('regen',
                              help='Eagerly rebuild the full DB cache on '
                                    'disk (refuses if > 1 GiB without '
                                    '--force).')
        p.add_argument('sha')
        p.add_argument('--force', action='store_true')

        p = sp.add_parser('dump',
                              help='Write one level\'s stream to disk.')
        p.add_argument('sha')
        p.add_argument('level', type=int)
        p.add_argument('-o', '--out', default='-',
                          help='Output path, "-" = stdout (default).')

        p = sp.add_parser('scan',
                              help='Heuristic file-boundary candidates '
                                    'within one level.')
        p.add_argument('sha')
        p.add_argument('level', type=int)
        p.add_argument('--min-run', type=int, default=16)

        p = sp.add_parser('tag', help='Tag a byte range as a file.')
        p.add_argument('sha')
        p.add_argument('--clock', default=kc.DEFAULT_CLOCK_NAME,
                          help='Which clock to tag against '
                               '(default: static).')
        p.add_argument('--at',
                          help='Pin the bytes to a specific wall-clock '
                               'instant on a time-evolving clock '
                               '(unix or ISO8601). Default: "now" for '
                               'time clocks; ignored for static.')
        p.add_argument('--level',  type=int, required=True)
        p.add_argument('--stream', type=int, default=0,
                          help='Stream index within the level '
                               '(default 0; ignored unless the '
                               'clock has streams_per_level > 1).')
        p.add_argument('--start',  type=lambda x: int(x, 0),
                            required=True,
                            help='Byte start within the stream (decimal '
                                 'or 0x… hex).')
        p.add_argument('--end',    type=lambda x: int(x, 0),
                            required=True,
                            help='Byte end (exclusive).')
        p.add_argument('--name',   required=True)
        p.add_argument('--mime',   default='application/octet-stream')
        p.add_argument('--tags',   nargs='*', default=[])
        p.add_argument('--mode',   default='packed',
                          choices=('packed', 'cells'),
                          help='Read interpretation: "packed" (default) '
                               'gives 1 byte per 4 cells for file '
                               'content; "cells" gives 1 byte per cell '
                               '∈ {0..3} for UI masks. In cells mode, '
                               '--start/--end are CELL indices.')

        p = sp.add_parser('untag', help='Remove a tagged file.')
        p.add_argument('sha')
        p.add_argument('file_id')

        p = sp.add_parser('rename', help='Rename a tagged file.')
        p.add_argument('sha')
        p.add_argument('file_id')
        p.add_argument('new_name')

        p = sp.add_parser('extract', help='Read a file\'s bytes out.')
        p.add_argument('sha')
        p.add_argument('file_id')
        p.add_argument('-o', '--out', default='-',
                          help='Output path, "-" = stdout (default).')

        # ─── Clock management ────────────────────────────────────

        p = sp.add_parser('clocks',
                              help='List clocks attached to this keychain.')
        p.add_argument('sha')

        p = sp.add_parser('clock-add',
                              help='Add a time-evolving clock to this '
                                    'keychain (the same seed at a '
                                    'different speed).')
        p.add_argument('sha')
        p.add_argument('--name', required=True,
                          help='Slug for the clock (e.g. "slow").')
        p.add_argument('--rate', required=True,
                          help='Tick rate: "1/day", "1/hour", "3/sec", '
                               'or a bare ticks_per_second float.')
        p.add_argument('--start', default='now',
                          help='Start epoch: "now" (default), a unix '
                               'time, or an ISO8601 timestamp '
                               '(2026-05-17T20:00:00).')
        p.add_argument('--depth', type=int, default=kc.DEFAULT_DEPTH)
        p.add_argument('--ticks-per-level', type=int,
                          default=kc.DEFAULT_TICKS_PER_LEVEL)
        p.add_argument('--stream-ticks', type=int,
                          default=kc.DEFAULT_STREAM_TICKS)
        p.add_argument('--streams-per-level', type=int,
                          default=kc.DEFAULT_STREAMS_PER_LEVEL)
        p.add_argument('--raw', action='store_true')

        p = sp.add_parser('clock-remove',
                              help='Remove a clock (refuses if any file '
                                    'tags reference it).')
        p.add_argument('sha')
        p.add_argument('name')

        p = sp.add_parser('archive',
                              help='Snapshot the mother CA state for one '
                                    'clock at the current wall-clock tick. '
                                    'Stores 16,384 bytes per tick under '
                                    'archive/<clock>/<tick>.bin.')
        p.add_argument('sha')
        p.add_argument('--clock', default=kc.DEFAULT_CLOCK_NAME)
        p.add_argument('--at',
                          help='Snapshot the state at a specific time '
                               '(unix or ISO8601) instead of now.')
        p.add_argument('--packed', action='store_true',
                          help='Store packed 4-cells/byte (4 KB) instead '
                               'of raw 1-cell/byte (16 KB).')

        # ─── FUSE mount ──────────────────────────────────────────

        p = sp.add_parser('mount',
                              help='Mount a keychain as a read-only FUSE '
                                    'filesystem. Blocks until unmounted '
                                    'with Ctrl-C or `keychain umount`.')
        p.add_argument('sha')
        p.add_argument('mountpoint',
                          help='Directory to mount at (must exist + be '
                               'empty).')
        p.add_argument('--background', action='store_true',
                          help='Daemonise; return immediately.  Use '
                               '`keychain umount` to unmount.')
        p.add_argument('--debug', action='store_true',
                          help='Print FUSE operation trace.')

        p = sp.add_parser('umount', help='Unmount a FUSE mountpoint.')
        p.add_argument('mountpoint')

        p = sp.add_parser('sync',
                              help='Read the seed off an attached ESP32-S3 '
                                    'keychain device, register the keychain '
                                    'if new, and prepare the DB.')
        p.add_argument('--port',
                          help='Serial port (e.g. /dev/ttyACM0). Auto-'
                               'detects if omitted.')
        p.add_argument('--baud', type=int, default=115200)
        p.add_argument('--seed-file',
                          help='Use a local seed.bin file as the source '
                               'instead of a real device (testing / no-'
                               'hardware development).')
        p.add_argument('--eager', action='store_true',
                          help='Eagerly regenerate the full DB to '
                               'cache/db.bin (default: lazy — no compute '
                               'until something reads).')
        p.add_argument('--depth', type=int, default=kc.DEFAULT_DEPTH)
        p.add_argument('--ticks-per-level', type=int,
                          default=kc.DEFAULT_TICKS_PER_LEVEL)
        p.add_argument('--stream-ticks', type=int,
                          default=kc.DEFAULT_STREAM_TICKS)
        p.add_argument('--raw', action='store_true',
                          help='Use raw 1-byte-per-cell streams '
                               '(4× larger DB).')
        p.add_argument('--list', dest='do_list', action='store_true',
                          help='After sync, also print the file index.')

    # ─── dispatch ────────────────────────────────────────────────

    def handle(self, *args, **opts):
        cmd = opts['cmd'].replace('-', '_')
        try:
            getattr(self, f'_{cmd}')(opts)
        except AttributeError:
            raise CommandError(f'unknown subcommand "{opts["cmd"]}"')

    # ─── register ────────────────────────────────────────────────

    def _register(self, opts):
        src = opts['source']
        if src.isdigit():
            from caformer.models import ComponentChampion
            try:
                c = ComponentChampion.objects.get(
                    pk=int(src), component_slug='class4_quine')
            except ComponentChampion.DoesNotExist:
                raise CommandError(
                    f'no saved class4_quine champion with pk={src}.')
            seed = bytes(c.rules_blob)
            note = (opts['notes']
                       or f'spoeqi quine #{c.pk} (fit={c.fitness:.4f})')
        else:
            p = Path(src)
            if not p.exists():
                raise CommandError(f'no such file: {src}')
            seed = p.read_bytes()
            note = opts['notes'] or f'imported from {src}'
        params = kc.ChainParams(
            depth=opts['depth'],
            ticks_per_level=opts['ticks_per_level'],
            stream_ticks=opts['stream_ticks'],
            streams_per_level=opts['streams_per_level'],
            packed=not opts['raw'],
        )
        if opts.get('reset'):
            import shutil
            sha = kc.compute_seed_sha(seed)
            d = kc.keychain_dir(sha)
            if d.exists():
                shutil.rmtree(d)
                self.stdout.write(self.style.WARNING(
                    f'reset existing keychain {sha[:12]}…'))
        idx = kc.register_keychain(seed, params=params, notes=note)
        self.stdout.write(self.style.SUCCESS(
            f'registered keychain {idx.seed_sha256[:12]}…'))
        self.stdout.write(_summarise(idx))

    # ─── list ────────────────────────────────────────────────────

    def _list(self, opts):
        for sha in kc.list_known():
            try:
                idx = kc.load_index(sha)
            except FileNotFoundError:
                continue
            self.stdout.write(
                f'  {sha[:16]}…  depth={idx.chain_params.depth:>2}  '
                f'files={len(idx.files):>4}   {idx.notes}')
        if not kc.list_known():
            self.stdout.write(self.style.WARNING(
                'no keychains. Use `keychain register <quine_pk>`.'))

    # ─── info ────────────────────────────────────────────────────

    def _info(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        self.stdout.write(_summarise(idx))

    # ─── regen ───────────────────────────────────────────────────

    def _regen(self, opts):
        sha = _resolve_sha(opts['sha'])
        import time as _t
        t0 = _t.time()
        db = _regen_or_load(sha, force=opts.get('force', False))
        dt = _t.time() - t0
        total = sum(len(v) for v in db.values())
        self.stdout.write(self.style.SUCCESS(
            f'regenerated {total:,} bytes ({total/1048576:.2f} MiB) '
            f'across {len(db)} levels in {dt:.3f}s '
            f'({total/dt/1048576:.1f} MiB/s)'))

    # ─── verify ──────────────────────────────────────────────────

    def _verify(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        # verify() resolves the right backend per-file based on each
        # file's clock_name + wall_anchor — don't hand it one backend.
        problems = idx.verify()
        if not problems:
            self.stdout.write(self.style.SUCCESS(
                f'all {len(idx.files)} file shas match.'))
            return
        self.stdout.write(self.style.ERROR(
            f'{len(problems)} mismatch(es):'))
        for fid, why in problems:
            self.stdout.write(f'  {fid}  {why}')

    # ─── dump ────────────────────────────────────────────────────

    def _dump(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        if opts['level'] < 0 or opts['level'] >= idx.chain_params.depth:
            raise CommandError(
                f'level {opts["level"]} outside [0, {idx.chain_params.depth})')
        backend = _backend(sha)
        # Emit every stream in this level concatenated.
        parts = []
        for s in range(idx.chain_params.streams_per_level):
            parts.append(backend.read(
                opts['level'], s, 0, idx.chain_params.bytes_per_stream()))
        data = b''.join(parts)
        if opts['out'] == '-':
            sys.stdout.buffer.write(data)
        else:
            Path(opts['out']).write_bytes(data)
            self.stdout.write(self.style.SUCCESS(
                f'wrote {len(data):,} bytes → {opts["out"]}'))

    # ─── scan ────────────────────────────────────────────────────

    def _scan(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        if opts['level'] >= idx.chain_params.depth:
            raise CommandError(
                f'level {opts["level"]} outside [0, {idx.chain_params.depth})')
        backend = _backend(sha)
        # Scan only stream 0 of the level — N>0 streams have identical
        # statistics by construction, so one is representative.
        stream = backend.read(opts['level'], 0, 0,
                                  idx.chain_params.bytes_per_stream())
        regions = kc.scan_regions(stream, min_run=opts['min_run'])
        if not regions:
            self.stdout.write('  no obvious file boundaries found.')
            return
        self.stdout.write(f'  {"kind":>15s}  {"start":>9s}  {"end":>9s}  '
                              f'{"length":>9s}  note')
        self.stdout.write('  ' + '─' * 70)
        for r in regions:
            self.stdout.write(
                f'  {r["kind"]:>15s}  0x{r["start"]:07x}  0x{r["end"]:07x}  '
                f'{r["length"]:>9}  {r["note"]}')

    # ─── tag / untag / rename ─────────────────────────────────────

    def _tag(self, opts):
        import time as _t
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        clock_name = opts.get('clock', kc.DEFAULT_CLOCK_NAME)
        clock = idx.get_clock(clock_name)
        if clock is None:
            raise CommandError(f'no clock named {clock_name!r}')
        # Wall anchor
        wall_anchor = None
        if opts.get('at'):
            try:
                wall_anchor = float(opts['at'])
            except ValueError:
                try:
                    wall_anchor = _t.mktime(_t.strptime(
                        opts['at'], '%Y-%m-%dT%H:%M:%S'))
                except ValueError:
                    raise CommandError(f'bad --at: {opts["at"]!r}')
        backend = _backend(sha, clock_name, wall_time=wall_anchor)
        entry = idx.add(
            name=opts['name'], level=opts['level'],
            byte_start=opts['start'], byte_end=opts['end'],
            stream_index=opts['stream'],
            clock_name=clock_name, wall_anchor=wall_anchor,
            mime=opts['mime'], tags=opts['tags'],
            mode=opts.get('mode', 'packed'), db=backend,
        )
        kc.save_index(idx)
        bits = [f'L{entry.level}']
        if clock.chain_params.streams_per_level > 1:
            bits.append(f'S{entry.stream_index}')
        if not clock.is_static:
            bits.append(f'@{entry.wall_anchor:.0f}')
        self.stdout.write(self.style.SUCCESS(
            f'tagged {entry.id}  {entry.name}  '
            f'clock={clock_name} {" ".join(bits)} '
            f'[{entry.byte_start:#x}:{entry.byte_end:#x}]  '
            f'{entry.size:,} B  sha={entry.sha256[:8]}…'))

    def _untag(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        if not idx.remove(opts['file_id']):
            raise CommandError(f'no file with id "{opts["file_id"]}"')
        kc.save_index(idx)
        self.stdout.write(self.style.SUCCESS(
            f'removed {opts["file_id"]}'))

    def _rename(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        f = idx.get(opts['file_id'])
        if not f:
            raise CommandError(f'no file with id "{opts["file_id"]}"')
        old = f.name
        f.name = opts['new_name']
        kc.save_index(idx)
        self.stdout.write(self.style.SUCCESS(
            f'renamed {f.id}: {old} → {f.name}'))

    # ─── ls / extract ────────────────────────────────────────────

    def _ls(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        if not idx.files:
            self.stdout.write('  (no tagged files)')
            return
        has_clocks = len(idx.clocks) > 1
        self.stdout.write(
            f'  {"id":>6s}  {"clock":<10s}  {"lvl":>3s}  {"start":>9s}  '
            f'{"size":>10s}  {"mime":<22s}  name')
        self.stdout.write('  ' + '─' * 80)
        for f in idx.files:
            self.stdout.write(
                f'  {f.id:>6s}  {f.clock_name:<10s}  '
                f'{f.level:>3}  0x{f.byte_start:07x}  '
                f'{f.size:>10,}  {f.mime[:22]:<22s}  {f.name}')

    def _extract(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        f = idx.get(opts['file_id'])
        if not f:
            raise CommandError(f'no file with id "{opts["file_id"]}"')
        backend = _backend(sha, f.clock_name, wall_time=f.wall_anchor)
        data = f.slice_from(backend)
        if opts['out'] == '-':
            sys.stdout.buffer.write(data)
        else:
            Path(opts['out']).write_bytes(data)
            self.stdout.write(self.style.SUCCESS(
                f'wrote {len(data):,} bytes → {opts["out"]}'))

    # ─── clock management ──────────────────────────────────────────

    def _clocks(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        import time as _t
        now = _t.time()
        self.stdout.write(
            f'  {"name":<14s} {"rate":>16s} {"start":>14s} '
            f'{"tick_n_now":>11s}  depth/tpl/st  DB size')
        self.stdout.write('  ' + '─' * 80)
        for c in idx.clocks:
            p = c.chain_params
            total = p.total_bytes()
            unit = 'GiB' if total >= (1 << 30) else 'MiB'
            div = (1 << 30) if total >= (1 << 30) else (1 << 20)
            start = ('—' if c.is_static
                     else _t.strftime('%Y-%m-%d %H:%M',
                                          _t.localtime(c.start_epoch)))
            self.stdout.write(
                f'  {c.name:<14s} {kc.format_tick_rate(c.ticks_per_second):>16s} '
                f'{start:>14s} {c.tick_n_at(now):>11d}  '
                f'{p.depth}/{p.ticks_per_level}/{p.stream_ticks}  '
                f'{total/div:.2f} {unit}')

    def _clock_add(self, opts):
        import time as _t
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        # Parse rate
        try:
            tps = kc.parse_tick_rate(opts['rate'])
        except ValueError as e:
            raise CommandError(f'bad --rate: {e}')
        # Parse start
        start_raw = opts['start']
        if start_raw == 'now':
            start = _t.time()
        else:
            try:
                start = float(start_raw)
            except ValueError:
                try:
                    start = _t.mktime(_t.strptime(
                        start_raw, '%Y-%m-%dT%H:%M:%S'))
                except ValueError:
                    raise CommandError(
                        f'bad --start: expected "now", unix time, or '
                        f'ISO8601 (got {start_raw!r})')
        params = kc.ChainParams(
            depth=opts['depth'],
            ticks_per_level=opts['ticks_per_level'],
            stream_ticks=opts['stream_ticks'],
            streams_per_level=opts['streams_per_level'],
            packed=not opts['raw'],
        )
        clock = kc.Clock(
            name=opts['name'], start_epoch=start,
            ticks_per_second=tps, chain_params=params,
        )
        try:
            idx.add_clock(clock)
        except ValueError as e:
            raise CommandError(str(e))
        kc.save_index(idx)
        rate = kc.format_tick_rate(tps)
        self.stdout.write(self.style.SUCCESS(
            f'added clock {clock.name!r}: {rate}, '
            f'start={_t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(start))}, '
            f'tick_n_now={clock.tick_n_at()}'))

    def _clock_remove(self, opts):
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        try:
            idx.remove_clock(opts['name'])
        except ValueError as e:
            raise CommandError(str(e))
        kc.save_index(idx)
        self.stdout.write(self.style.SUCCESS(
            f'removed clock {opts["name"]!r}'))

    def _archive(self, opts):
        """Snapshot mother CA state for one clock at this instant."""
        import time as _t
        sha = _resolve_sha(opts['sha'])
        idx = kc.load_index(sha)
        clock_name = opts['clock']
        clock = idx.get_clock(clock_name)
        if clock is None:
            raise CommandError(f'no clock named {clock_name!r}')
        # Resolve wall_time
        if opts.get('at'):
            try:
                wt = float(opts['at'])
            except ValueError:
                try:
                    wt = _t.mktime(_t.strptime(opts['at'],
                                                   '%Y-%m-%dT%H:%M:%S'))
                except ValueError:
                    raise CommandError(f'bad --at: {opts["at"]!r}')
        else:
            wt = _t.time()
        backend = _backend(sha, clock_name, wall_time=wt)
        state = backend.mother_state()
        out_bytes = state
        if opts.get('packed'):
            from spoeqi.metachain import pack_k4_stream
            out_bytes = pack_k4_stream(state)
        tick_n = clock.tick_n_at(wt)
        archive_dir = kc.keychain_dir(sha) / 'archive' / clock_name
        archive_dir.mkdir(parents=True, exist_ok=True)
        out_path = archive_dir / f'{tick_n:08d}.bin'
        out_path.write_bytes(out_bytes)
        when = _t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(wt))
        self.stdout.write(self.style.SUCCESS(
            f'archived tick {tick_n} of clock {clock_name!r} '
            f'@ {when}: {len(out_bytes):,} bytes → {out_path}'))

    # ─── FUSE mount / umount ─────────────────────────────────────

    def _mount(self, opts):
        sha = _resolve_sha(opts['sha'])
        mp = Path(opts['mountpoint']).resolve()
        if not mp.exists():
            raise CommandError(f'mountpoint does not exist: {mp}')
        if not mp.is_dir():
            raise CommandError(f'mountpoint is not a directory: {mp}')
        # Guard against mounting over a non-empty dir
        if any(mp.iterdir()):
            raise CommandError(
                f'mountpoint is not empty: {mp}\n'
                f'  refusing to shadow existing content.')
        try:
            from spoeqi.keychain_fuse import mount_keychain
        except ImportError as e:
            raise CommandError(
                f'fusepy is required for mount.  '
                f'Install with `venv/bin/python -m pip install fusepy`.\n'
                f'  ({e})')
        self.stdout.write(self.style.SUCCESS(
            f'mounting keychain {sha[:12]}… at {mp}'))
        self.stdout.write('  Ctrl-C or `keychain umount` to release.')
        try:
            mount_keychain(sha, str(mp),
                              foreground=not opts['background'],
                              debug=opts['debug'])
        except KeyboardInterrupt:
            self.stdout.write('unmounted.')
        except RuntimeError as e:
            raise CommandError(str(e))

    def _umount(self, opts):
        import subprocess
        mp = Path(opts['mountpoint']).resolve()
        # Prefer fusermount on Linux, umount elsewhere.
        for tool in ('fusermount', 'fusermount3', 'umount'):
            try:
                cmd = [tool, '-u', str(mp)] if 'fuser' in tool else [tool, str(mp)]
                subprocess.check_call(cmd)
                self.stdout.write(self.style.SUCCESS(f'unmounted {mp}'))
                return
            except FileNotFoundError:
                continue
            except subprocess.CalledProcessError as e:
                raise CommandError(f'{tool} failed: {e}')
        raise CommandError(
            'no unmount tool found (tried fusermount, fusermount3, umount)')

    # ─── sync — talk to an attached device ────────────────────────

    def _sync(self, opts):
        from spoeqi import keychain_device as kdev
        import time as _t

        # Pick a seed source: explicit file > explicit port > auto-detect.
        if opts.get('seed_file'):
            src = kdev.FileSeedSource(Path(opts['seed_file']))
            self.stdout.write(f'• source : {src.description()}')
        else:
            port = opts.get('port')
            if not port:
                self.stdout.write('• scanning USB serial ports…')
                hits = kdev.detect_devices()
                if not hits:
                    raise CommandError(
                        'no ESP32-S3 keychain detected.\n'
                        '  Pass --port /dev/ttyACM0 explicitly, '
                        'or --seed-file <path> to test without hardware.')
                if len(hits) > 1:
                    self.stdout.write(self.style.WARNING(
                        f'  multiple candidate ports found:'))
                    for h in hits:
                        self.stdout.write(
                            f'    {h["device"]:<16}  {h["manufacturer"]} '
                            f'{h["product"]}  (vid={h["vid"]:#06x} '
                            f'pid={h["pid"]:#06x})')
                    raise CommandError(
                        'pass --port to choose which one.')
                port = hits[0]['device']
                self.stdout.write(f'  found device at {port} '
                                      f'({hits[0]["product"]})')
            try:
                src = kdev.SerialSeedSource(port, baud=opts['baud'])
            except kdev.DeviceError as e:
                raise CommandError(f'device error: {e}')
            except Exception as e:
                raise CommandError(
                    f'failed to open {port}: {e}\n'
                    f'  (check the port is free; only one process can '
                    f'hold the CDC at a time)')
            self.stdout.write(f'• source : {src.description()}')

        # Read seed.
        t0 = _t.time()
        try:
            seed, sha = src.read_seed()
        except kdev.DeviceError as e:
            raise CommandError(f'sync failed: {e}')
        finally:
            close = getattr(src, 'close', None)
            if callable(close):
                try: close()
                except Exception: pass
        self.stdout.write(
            f'• seed   : sha256 = {sha}\n'
            f'           {len(seed):,} bytes in {(_t.time()-t0)*1000:.0f} ms')

        # Register (idempotent on sha; pre-existing tags survive).
        params = kc.ChainParams(
            depth=opts['depth'],
            ticks_per_level=opts['ticks_per_level'],
            stream_ticks=opts['stream_ticks'],
            packed=not opts['raw'],
        )
        existed = sha in kc.list_known()
        idx = kc.register_keychain(seed, params=params,
                                          notes=f'synced from {src.description()}')
        if existed:
            self.stdout.write(self.style.SUCCESS(
                f'• keychain: known device, '
                f'{len(idx.files)} existing file tag'
                f'{"s" if len(idx.files) != 1 else ""} preserved.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                '• keychain: new device registered.'))

        # DB readiness.
        if opts['eager']:
            t1 = _t.time()
            db = _regen_or_load(sha)
            total = sum(len(v) for v in db.values())
            dt = _t.time() - t1
            self.stdout.write(
                f'• DB     : {total:,} bytes eagerly regenerated '
                f'in {dt:.2f} s ({total/dt/1048576:.1f} MiB/s)')
        else:
            backend = _backend(sha)
            self.stdout.write(
                f'• DB     : {idx.chain_params.total_bytes():,} bytes '
                f'addressable, lazy backend ready '
                f'(reads compute on demand).')

        # Tail with the next-step hint.
        short = sha[:12]
        self.stdout.write('')
        self.stdout.write(f'  keychain ready: {short}…')
        self.stdout.write('  next:')
        self.stdout.write(f'    manage.py keychain ls   {short}')
        self.stdout.write(f'    manage.py keychain scan {short} 0')
        self.stdout.write(f'    manage.py keychain tag  {short} '
                              f'--level L --start S --end E --name FN')
        self.stdout.write(f'    manage.py keychain extract {short} <id>')

        if opts.get('do_list'):
            self.stdout.write('')
            self._ls({'sha': sha})

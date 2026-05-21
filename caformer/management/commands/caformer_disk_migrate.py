"""Migrate caformer bulk data to an external drive (e.g. /mnt/d/CAFORMER).

Today's policy (2026-05-22 — user reviewed and approved):

  STAY LOCAL:  db.sqlite3, .artifacts/, code
                  these are small + write-heavy + locking-sensitive

  MOVE EXTERNAL: conduit/alice/bundles/<slug>/outputs/
                  these are the natural bulk — .rules files from ALICE
                  pulls.  Hundreds to thousands per bundle, ~65 KB each.

The command is idempotent.  For each bundle's outputs/ directory:
  - already a symlink → skip
  - real dir, empty   → make external mirror dir + replace with symlink
  - real dir, files   → cp -r contents, verify count + sizes match,
                         delete local files, replace dir with symlink

**Important history (2026-05-22):** the first version used
``rsync -a --remove-source-files`` which on exFAT fails with EPERM
on every chgrp / set-times call.  rsync still exits non-zero (rc=23)
AND still removes source files for each successful per-file
transfer — i.e. it can delete from source even when its overall
exit looks like failure.  Losing data is silent.

The fix: use ``cp -r`` (no metadata preservation by default, so
exFAT-friendly), then verify file count + total bytes match
between src and dst before deleting source files explicitly in
Python.  Never trust an external command's exit code as the
sole gate on data deletion.

The system never DEPENDS on the external drive being present:
new bundles still generate locally; pull.sh follows the symlink and
writes to whichever side is there.  When the drive is unplugged,
the symlinks dangle but the rest of the system keeps working.

  manage.py caformer_disk_migrate [--dry-run] [--external-root /mnt/d/CAFORMER]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _human(n: int) -> str:
    x = float(n)
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if x < 1024:
            return f'{x:.1f} {u}' if u != 'B' else f'{int(x)} {u}'
        x /= 1024
    return f'{x:.1f} PB'


def _dir_size(p: Path) -> int:
    total = 0
    for root, _ds, files in __import__('os').walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


class Command(BaseCommand):
    help = ('Move conduit/alice/bundles/*/outputs/ directories to an '
            'external drive + symlink back.  Safe to re-run.')

    def add_arguments(self, parser):
        parser.add_argument('--external-root', type=str,
                              default='/mnt/d/CAFORMER',
                              help='external drive root containing the '
                                     '4-directory layout (artifacts/, '
                                     'bundle-outputs/, archive/, scratch/)')
        parser.add_argument('--dry-run', action='store_true',
                              help='show what would happen, do not move')

    def handle(self, *, external_root, dry_run, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        base = Path(settings.BASE_DIR).resolve()
        ext_root = Path(external_root).resolve()
        ext_bundle_outputs = ext_root / 'bundle-outputs'
        bundles_dir = base / 'conduit' / 'alice' / 'bundles'

        log(f'=== caformer_disk_migrate ===')
        log(f'  project base:  {base}')
        log(f'  external root: {ext_root}')
        log(f'  dry-run:       {dry_run}')

        # Sanity: external root must exist + be writable + have the 4 dirs.
        if not ext_root.is_dir():
            self.stderr.write(self.style.ERROR(
                f'external root {ext_root} does not exist or is not '
                f'a directory.  Plug in the drive and / or run '
                f"`sudo mount -t drvfs D: /mnt/d`."))
            return
        if not ext_bundle_outputs.is_dir():
            if dry_run:
                log(f'  WOULD mkdir {ext_bundle_outputs}')
            else:
                ext_bundle_outputs.mkdir(parents=True, exist_ok=True)
                log(f'  + created {ext_bundle_outputs}')

        try:
            test_file = ext_root / '.write_test'
            test_file.write_text('ok')
            test_file.unlink()
        except OSError as e:
            self.stderr.write(self.style.ERROR(
                f'external root not writable: {e}'))
            return

        if not bundles_dir.is_dir():
            log(f'no bundles dir at {bundles_dir}; nothing to do')
            return

        # Pre-flight: how much would we move?
        candidates: list[dict] = []
        for b in sorted(bundles_dir.iterdir()):
            if not b.is_dir():
                continue
            outputs = b / 'outputs'
            if outputs.is_symlink():
                target = outputs.resolve()
                candidates.append({
                    'bundle':   b.name,
                    'outputs':  outputs,
                    'state':    'symlinked',
                    'target':   target,
                    'size':     0,
                    'n_files':  0,
                })
                continue
            if not outputs.is_dir():
                candidates.append({
                    'bundle':   b.name,
                    'outputs':  outputs,
                    'state':    'missing',
                    'size':     0,
                    'n_files':  0,
                })
                continue
            sz = _dir_size(outputs)
            n  = len([f for f in outputs.iterdir() if f.is_file()])
            candidates.append({
                'bundle':   b.name,
                'outputs':  outputs,
                'state':    'local' if n > 0 else 'local-empty',
                'size':     sz,
                'n_files':  n,
            })

        log('')
        log(f'  {len(candidates)} bundle(s) found')
        total_to_move = 0
        for c in candidates:
            tag = c['state']
            if tag == 'symlinked':
                log(f"    · {c['bundle']:<26} → symlink → "
                    f"{c['target']}")
            elif tag == 'local-empty':
                log(f"    + {c['bundle']:<26} (empty; will create "
                    f"external dir + symlink)")
            elif tag == 'local':
                total_to_move += c['size']
                log(f"    M {c['bundle']:<26} {_human(c['size']):>10}  "
                    f"{c['n_files']:>5} files (will move)")
            elif tag == 'missing':
                log(f"    ? {c['bundle']:<26} (no outputs/ dir; "
                    f"skipping)")

        # Free-space check.
        try:
            usage = shutil.disk_usage(str(ext_root))
            log('')
            log(f'  external drive: '
                f'{_human(usage.free)} free of {_human(usage.total)}')
            log(f'  total to move:  {_human(total_to_move)}')
            if total_to_move > usage.free:
                self.stderr.write(self.style.ERROR(
                    f'not enough free space on external drive'))
                return
        except OSError:
            pass

        if dry_run:
            log('')
            log('(--dry-run: stopping before any writes)')
            return

        # ── Execute migration ─────────────────────────────────────
        log('')
        log(f'-- migrating --')
        n_moved = 0
        n_skipped = 0
        for c in candidates:
            if c['state'] == 'symlinked':
                n_skipped += 1
                continue
            if c['state'] == 'missing':
                n_skipped += 1
                continue
            outputs = c['outputs']
            dst = ext_bundle_outputs / c['bundle']
            if dst.exists() and any(dst.iterdir()):
                # Already populated externally — only safe action is to
                # skip + symlink the local side over (if it's not a
                # symlink already).  Warn so the user can resolve.
                if c['state'] == 'local' and c['n_files'] > 0:
                    log(f"  ! {c['bundle']}: external dst already has "
                        f"files; refusing to clobber.  Resolve "
                        f"manually then re-run.")
                    continue
            dst.mkdir(parents=True, exist_ok=True)
            if c['state'] == 'local' and c['n_files'] > 0:
                log(f"  moving {c['bundle']:<26} → {dst}  "
                    f"({_human(c['size'])}, {c['n_files']} files)")
                # exFAT (via drvfs) can't store Unix perms / owner /
                # group / mtimes, so rsync's preservation flags
                # all fail with EPERM.  Use plain cp -r (no
                # metadata preservation by default), then verify by
                # comparing file count + total bytes before deleting
                # the source.
                rc = subprocess.run(
                    ['cp', '-r', '--', str(outputs) + '/.',
                     str(dst) + '/'],
                    check=False)
                if rc.returncode != 0:
                    log(f"  ! cp failed (rc={rc.returncode}); "
                        f"skipping symlink swap for safety")
                    continue
                # Verify the destination matches.
                src_files = sorted(p.name for p in outputs.iterdir()
                                    if p.is_file())
                dst_files = sorted(p.name for p in dst.iterdir()
                                    if p.is_file())
                if src_files != dst_files:
                    log(f"  ! verify failed: src has "
                        f"{len(src_files)} files, dst has "
                        f"{len(dst_files)}.  Leaving source intact.")
                    continue
                src_sz = sum((outputs / n).stat().st_size for n in src_files)
                dst_sz = sum((dst / n).stat().st_size     for n in dst_files)
                if src_sz != dst_sz:
                    log(f"  ! size mismatch: src={src_sz} dst={dst_sz}. "
                        f"Leaving source intact.")
                    continue
                # Safe to delete source.
                for f in outputs.iterdir():
                    if f.is_file():
                        f.unlink()
                try:
                    outputs.rmdir()
                except OSError as e:
                    log(f"  ! could not rmdir {outputs}: {e}")
                    continue
            else:
                # Empty dir → just remove the local dir.
                try:
                    outputs.rmdir()
                except OSError as e:
                    log(f"  ! could not rmdir empty {outputs}: {e}")
                    continue
            # Replace with symlink.
            outputs.symlink_to(dst)
            log(f"  symlinked {outputs} → {dst}")
            n_moved += 1

        log('')
        log(self.style.SUCCESS(
            f'migrated {n_moved} bundle(s).  {n_skipped} skipped.'))
        # Final disk usage.
        try:
            after = shutil.disk_usage(str(ext_root))
            log(f'  external drive after: '
                f'{_human(after.free)} free of {_human(after.total)}')
        except OSError:
            pass

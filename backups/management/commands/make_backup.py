"""Produce a single tar.gz snapshot of the load-bearing state.

What gets packed:
  - db.sqlite3                    (the live SQLite database)
  - secret_key.txt                (Django SECRET_KEY)
  - health_token.txt              (health-check API token)
  - mail_relay_token.txt          (mail relay token)
  - provisioning_secret.txt       (ESP fleet provisioning secret)
  - llm_*.key                     (LLM provider API keys, chmod 600)

Tarball lands at <BASE_DIR>/backups/snapshots/
<retention>-<YYYY-MM-DDTHH-MM-SS>.tar.gz. A Snapshot row is
recorded with size + sha256 + the file list. Old snapshots in the
same retention class beyond the window are pruned (file + row).

Retention windows:
  daily=7, weekly=4, monthly=12, manual=infinite

    python manage.py make_backup
    python manage.py make_backup --retention=weekly
    python manage.py make_backup --dry-run
"""

from __future__ import annotations

import hashlib
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from backups.models import Snapshot


CANDIDATES = [
    'db.sqlite3',
    'secret_key.txt',
    'health_token.txt',
    'mail_relay_token.txt',
    'provisioning_secret.txt',
]
GLOB_CANDIDATES = ['llm_*.key']

RETENTION_WINDOW = {
    'daily':   7,
    'weekly':  4,
    'monthly': 12,
    'manual':  None,  # never prune
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class Command(BaseCommand):
    help = 'Produce a tar.gz snapshot of Velour state.'

    def add_arguments(self, parser):
        parser.add_argument('--retention', default='manual',
                            choices=list(RETENTION_WINDOW))
        parser.add_argument('--dry-run', action='store_true',
                            help="Print what would be packed, don't write.")

    def handle(self, *args, **opts):
        base = Path(settings.BASE_DIR)
        snap_dir = base / 'backups' / 'snapshots'
        snap_dir.mkdir(parents=True, exist_ok=True)

        # Discover the candidate files actually present.
        files: list[Path] = []
        for name in CANDIDATES:
            p = base / name
            if p.is_file():
                files.append(p)
        for pat in GLOB_CANDIDATES:
            files.extend(p for p in base.glob(pat) if p.is_file())

        if not files:
            self.stdout.write(self.style.WARNING(
                'no candidate files found — nothing to back up'))
            return

        contents = '\n'.join(
            f'- {p.relative_to(base)} ({p.stat().st_size} bytes)'
            for p in files)

        if opts['dry_run']:
            self.stdout.write('Would pack:')
            self.stdout.write(contents)
            return

        retention = opts['retention']
        ts = timezone.localtime().strftime('%Y-%m-%dT%H-%M-%S')
        out_path = snap_dir / f'{retention}-{ts}.tar.gz'

        with tarfile.open(out_path, 'w:gz') as tar:
            for p in files:
                tar.add(p, arcname=p.relative_to(base))

        size = out_path.stat().st_size
        sha = _sha256(out_path)
        snap = Snapshot.objects.create(
            path=str(out_path), size_bytes=size, sha256=sha,
            retention=retention, contents_summary=contents)

        # Prune older snapshots in this retention class beyond the
        # window. Manual snapshots never prune.
        window = RETENTION_WINDOW[retention]
        pruned = 0
        if window is not None:
            stale = (Snapshot.objects.filter(retention=retention)
                     .order_by('-created_at')[window:])
            for s in stale:
                try:
                    Path(s.path).unlink(missing_ok=True)
                except OSError:
                    pass
                s.delete()
                pruned += 1

        self.stdout.write(self.style.SUCCESS(
            f'wrote {out_path.name} '
            f'({snap.size_mb} MB, {len(files)} file(s), pruned {pruned})'))

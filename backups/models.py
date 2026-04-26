"""Backup snapshot ledger.

Each Snapshot row records one tarball produced by `manage.py
make_backup`. The tarball lives at <BASE_DIR>/backups/snapshots/
<retention>-<YYYY-MM-DDTHH-MM-SS>.tar.gz; the row stores its
path, size, sha256, and the retention class (daily / weekly /
monthly) that governs when it gets pruned.

The retention policy:
  - daily   — keep the most recent 7
  - weekly  — keep the most recent 4
  - monthly — keep the most recent 12

When `make_backup --retention=daily` runs, the new snapshot is
added and any daily snapshots beyond the 7-row window are
deleted (file + row). Same idea for weekly and monthly.
"""

from __future__ import annotations

from django.db import models


class Snapshot(models.Model):
    RETENTION_CHOICES = [
        ('daily',   'Daily'),
        ('weekly',  'Weekly'),
        ('monthly', 'Monthly'),
        ('manual',  'Manual (no auto-prune)'),
    ]

    path = models.CharField(max_length=500,
        help_text='Absolute path to the tarball.')
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True,
        help_text='SHA-256 of the tarball, hex-encoded.')
    retention = models.CharField(max_length=10,
        choices=RETENTION_CHOICES, default='manual')
    contents_summary = models.TextField(blank=True,
        help_text='What was packed: a short bulleted list of '
                  'files / database tables / secret files included.')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['retention', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.retention}] {self.created_at:%Y-%m-%d %H:%M}'

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)

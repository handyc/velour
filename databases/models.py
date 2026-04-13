"""Databases — registry of MySQL / PostgreSQL / SQLite connections.

Stores connection credentials (MySQL, PostgreSQL) or local file paths
(SQLite) per record. SQLite databases are first-class filesystem
entities — they live under MEDIA_ROOT/databases/ with slug-based
filenames and can be browsed, queried, created, and moved around like
any other file.

Credentials are stored in plaintext on the velour SQLite database.
Same trust model as the mailboxes app — fine for a single-user lab
control panel.
"""

import os

from django.conf import settings
from django.db import models
from django.utils.text import slugify


ENGINE_CHOICES = [
    ('sqlite',     'SQLite (local file)'),
    ('mysql',      'MySQL / MariaDB'),
    ('postgresql', 'PostgreSQL'),
]

DEFAULT_PORTS = {
    'mysql':      3306,
    'postgresql': 5432,
}

SSL_MODE_CHOICES = [
    ('',         'Default (no preference)'),
    ('disable',  'disable'),
    ('allow',    'allow'),
    ('prefer',   'prefer'),
    ('require',  'require'),
    ('verify-ca','verify-ca'),
    ('verify-full', 'verify-full'),
]

TEST_STATUS_CHOICES = [
    ('untested',  'Not yet tested'),
    ('ok',        'OK'),
    ('failed',    'Failed'),
]

SQLITE_DIR = os.path.join(settings.MEDIA_ROOT, 'databases')


class Database(models.Model):
    """A MySQL, PostgreSQL, or SQLite database known to Velour.

    SQLite databases are local files under MEDIA_ROOT/databases/ whose
    filename is derived from the slug. Remote databases store host/port/
    credentials as before.
    """

    nickname = models.CharField(
        max_length=120,
        help_text='Human label, e.g. "Production users", "Gary aquarium logs".',
    )
    slug = models.SlugField(
        max_length=140, unique=True, blank=True,
        help_text='URL-safe unique ID. Auto-derived from nickname if blank.',
    )
    engine = models.CharField(
        max_length=16, choices=ENGINE_CHOICES, default='sqlite',
    )

    # Remote connection fields (MySQL / PostgreSQL)
    host = models.CharField(
        max_length=253, default='localhost', blank=True,
        help_text='Hostname or IP. Not used for SQLite.',
    )
    port = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='TCP port. Leave blank to use the engine default.',
    )
    username = models.CharField(max_length=120, blank=True)
    password = models.CharField(max_length=255, blank=True)
    database_name = models.CharField(
        max_length=120, blank=True,
        help_text='Database / schema name. Not used for SQLite.',
    )
    ssl_mode = models.CharField(
        max_length=16, choices=SSL_MODE_CHOICES, blank=True, default='',
    )

    # SQLite file path (auto-set from slug for created databases,
    # can also point to an externally-produced file like Datalift output)
    file_path = models.CharField(
        max_length=500, blank=True,
        help_text='Absolute path to the .sqlite3 file. Auto-set for new SQLite databases.',
    )

    notes = models.TextField(blank=True)

    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_status = models.CharField(
        max_length=16, choices=TEST_STATUS_CHOICES, default='untested',
    )
    last_test_error = models.TextField(blank=True)
    last_test_server_version = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nickname', 'slug']

    def __str__(self):
        return f'{self.nickname} ({self.get_engine_display()})'

    def save(self, *args, **kwargs):
        if not self.slug and self.nickname:
            base = slugify(self.nickname)[:120] or 'database'
            candidate = base
            n = 2
            while Database.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        # Auto-set file_path for new SQLite databases
        if self.engine == 'sqlite' and not self.file_path and self.slug:
            os.makedirs(SQLITE_DIR, exist_ok=True)
            self.file_path = os.path.join(SQLITE_DIR, f'{self.slug}.sqlite3')
        super().save(*args, **kwargs)
        # Create the file if it doesn't exist yet
        if self.engine == 'sqlite' and self.file_path and not os.path.isfile(self.file_path):
            import sqlite3 as _sqlite3
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            _sqlite3.connect(self.file_path).close()

    @property
    def effective_port(self):
        return self.port or DEFAULT_PORTS.get(self.engine)

    @property
    def is_sqlite(self):
        return self.engine == 'sqlite'

    @property
    def file_exists(self):
        return self.is_sqlite and self.file_path and os.path.isfile(self.file_path)

    @property
    def file_size_display(self):
        if not self.file_exists:
            return '—'
        size = os.path.getsize(self.file_path)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}' if unit != 'B' else f'{size} {unit}'
            size /= 1024
        return f'{size:.1f} TB'

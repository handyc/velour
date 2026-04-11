"""Databases — registry of MySQL / PostgreSQL connections.

Phase 1 scope: store connection credentials per record, with a "test
connection" button that runs a trivial query (SELECT 1) and updates
last_tested_at / last_test_status / last_test_error so the list view can
show a green/red dot per database.

Phase 2 (planned, not in this app yet) will add table browsing, row
editing, and a raw SQL shell rendered into the detail page. The model
already carries enough information to support all of that — Phase 2 is
purely views + templates + driver helpers.

Credentials are stored in plaintext on the velour SQLite database. The
SQLite file lives at BASE_DIR/db.sqlite3 with whatever permissions
adminsetup.sh assigned (chown'd to the project user, 600). This is the
same trust model as the mailboxes app's SMTP/IMAP password storage —
fine for a single-user lab control panel, not appropriate for a
multi-tenant SaaS.
"""

from django.db import models
from django.utils.text import slugify


ENGINE_CHOICES = [
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


class Database(models.Model):
    """One MySQL or PostgreSQL connection target.

    Identity:
      - nickname : human label, "Production users DB"
      - slug     : URL-safe unique ID, auto-derived from nickname

    Connection: engine + host + port + username + password + database
    name. ssl_mode is optional and free-form (different drivers honour
    different values).

    Status: last_tested_at + last_test_status + last_test_error are
    written by the test_connection view; the list page renders a dot
    per row from these.
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
        max_length=16, choices=ENGINE_CHOICES, default='postgresql',
    )

    host = models.CharField(
        max_length=253, default='localhost',
        help_text='Hostname or IP, e.g. "db.internal", "10.0.0.5", "localhost".',
    )
    port = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='TCP port. Leave blank to use the engine default '
                  '(MySQL 3306, PostgreSQL 5432).',
    )
    username = models.CharField(max_length=120, blank=True)
    password = models.CharField(max_length=255, blank=True)
    database_name = models.CharField(
        max_length=120, blank=True,
        help_text='Database / schema to connect to. Optional — leave blank '
                  'to connect to the server without selecting one.',
    )
    ssl_mode = models.CharField(
        max_length=16, choices=SSL_MODE_CHOICES, blank=True, default='',
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
        return f'{self.nickname} ({self.engine})'

    def save(self, *args, **kwargs):
        if not self.slug and self.nickname:
            base = slugify(self.nickname)[:120] or 'database'
            candidate = base
            n = 2
            while Database.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def effective_port(self):
        return self.port or DEFAULT_PORTS.get(self.engine)

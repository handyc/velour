from django.apps import apps
from django.db import models
from django.utils.text import slugify


class LiftJob(models.Model):
    """A conversion or anonymization job."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]
    JOB_TYPE_CHOICES = [
        ('convert', 'MySQL → Django + SQLite'),
        ('anonymize', 'Anonymize Database'),
    ]

    name = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Source database connection (MySQL/MariaDB)
    source_host = models.CharField(max_length=300, default='localhost')
    source_port = models.PositiveIntegerField(default=3306)
    source_user = models.CharField(max_length=200)
    source_password = models.CharField(max_length=500, blank=True)
    source_database = models.CharField(max_length=200)

    # Optional reference to a databases.Database record (PK only).
    # Stored as a plain integer so datalift has no hard dependency on
    # the velour databases app — the resolved_source_db property
    # lazily fetches the Database instance iff the app is installed.
    source_db_ref = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='PK of a `databases.Database` row to pull '
                  'host/port/user/password/database from. Ignored '
                  'silently if the databases app is not installed.',
    )

    # Output
    output_models_py = models.TextField(blank=True, help_text='Generated Django models.py')
    output_sqlite = models.FileField(upload_to='datalift/', blank=True)
    output_anonymized = models.FileField(upload_to='datalift/anon/', blank=True)

    # Stats
    tables_found = models.PositiveIntegerField(default=0)
    rows_converted = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def resolved_source_db(self):
        """Lazily resolve ``source_db_ref`` (an int PK) to a
        ``databases.Database`` instance. Returns None if unset or if
        the databases app is not installed in this project."""
        if not self.source_db_ref:
            return None
        try:
            Model = apps.get_model('databases', 'Database')
        except LookupError:
            return None
        return Model.objects.filter(pk=self.source_db_ref).first()

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug, n = base, 1
            while LiftJob.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        # If source_db_ref set, pull connection details from the
        # referenced Database row (when the databases app is
        # available — otherwise leave the manually-entered values
        # alone).
        db = self.resolved_source_db
        if db is not None:
            self.source_host = db.host
            self.source_port = db.port
            self.source_user = db.username
            self.source_password = db.password
            self.source_database = db.database_name
        super().save(*args, **kwargs)

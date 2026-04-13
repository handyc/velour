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

    # Or use an existing Database app connection
    source_db_ref = models.ForeignKey(
        'databases.Database', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='lift_jobs',
        help_text='Use connection from Databases app instead of manual entry',
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

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug, n = base, 1
            while LiftJob.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        # If source_db_ref set, pull connection details from it
        if self.source_db_ref:
            self.source_host = self.source_db_ref.host
            self.source_port = self.source_db_ref.port
            self.source_user = self.source_db_ref.username
            self.source_password = self.source_db_ref.password
            self.source_database = self.source_db_ref.database_name
        super().save(*args, **kwargs)

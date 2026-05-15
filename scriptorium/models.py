"""Models for Scriptorium — the Velour app that manages philology-project
syncs (analyse, repair, extend, deploy).

Phase 1 is DANWSI-specific in spirit but the data model is generic so
later phases can plug in other Excel-fed Django philology projects
(the "language app studio" direction).
"""
from django.conf import settings
from django.db import models


class PhilologyProject(models.Model):
    """A target philology project that Scriptorium controls.

    For phase 1 there is exactly one row (DANWSI), but the shape is
    deliberately generic: each project declares where its code lives
    locally, how to ingest its data, how to reach its staging host,
    and which Django settings module it uses. Anything that varies
    per-project lives here, not in code.
    """

    KIND_CHOICES = [
        ('danwsi', 'DANWSI (NW Semitic)'),
        ('generic_django', 'Generic Django + Excel'),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    kind = models.CharField(max_length=40, choices=KIND_CHOICES, default='danwsi')
    description = models.TextField(blank=True)

    # Local checkout
    local_path = models.CharField(
        max_length=500,
        help_text="Absolute path to the local Django project (the dir containing manage.py).",
    )
    venv_python = models.CharField(
        max_length=500,
        help_text="Absolute path to the venv python (e.g. /home/x/proj/venv/bin/python).",
    )
    django_settings_module = models.CharField(
        max_length=200,
        help_text="DJANGO_SETTINGS_MODULE value for this project (e.g. 'danwsi_project.settings').",
    )

    # Where new data drops land (relative to local_path). Supports a glob
    # so Scriptorium can list all data-drop dirs (Data_files, Data_files2,
    # Data_files3, ...).
    data_dir_glob = models.CharField(
        max_length=200,
        default='Data_files*',
        help_text="Glob (relative to local_path) for data-drop directories.",
    )
    data_files_dir_env = models.CharField(
        max_length=80,
        default='DATA_FILES_DIR',
        help_text="Env var the ingest command honours to override the data-drop dir.",
    )
    ingest_command = models.CharField(
        max_length=200,
        default='ingest_ground_truth',
        help_text="manage.py command name that ingests a data drop.",
    )

    # SSH / remote staging
    remote_host = models.CharField(max_length=200, blank=True)
    remote_user = models.CharField(max_length=100, blank=True)
    remote_path = models.CharField(max_length=500, blank=True)
    remote_python = models.CharField(
        max_length=500, blank=True,
        help_text="Remote python path (e.g. /home/x/proj/venv/bin/python).",
    )
    ssh_key_path = models.CharField(max_length=500, blank=True)
    deploy_script = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the deploy script relative to local_path (e.g. deploy/deploy.sh).",
    )
    public_url = models.URLField(blank=True)

    # Backups
    local_backup_dir = models.CharField(
        max_length=500, blank=True,
        help_text="Where to write local db.sqlite3 backups before risky operations.",
    )
    db_filename = models.CharField(
        max_length=200, default='db.sqlite3',
        help_text="Name of the sqlite database file inside the project root.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SyncRun(models.Model):
    """One operation against a PhilologyProject — ingest, deploy, backup, restore.

    Persisted so the dashboard has history and so the user can drill in
    and see exactly what Scriptorium did.
    """

    OP_CHOICES = [
        ('ingest_local', 'Ingest (local)'),
        ('ingest_remote', 'Ingest (remote)'),
        ('deploy', 'Deploy code to remote'),
        ('backup_local', 'Backup local DB'),
        ('backup_remote', 'Backup remote DB'),
        ('restore_local', 'Restore local DB from backup'),
        ('restore_remote', 'Restore remote DB from backup'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('ok', 'OK'),
        ('failed', 'Failed'),
    ]

    project = models.ForeignKey(
        PhilologyProject, on_delete=models.CASCADE, related_name='runs',
    )
    op = models.CharField(max_length=40, choices=OP_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Inputs
    data_dir = models.CharField(
        max_length=300, blank=True,
        help_text="For ingest ops: the data-drop dir name that was used.",
    )
    extra_args = models.TextField(blank=True)

    # Outputs
    exit_code = models.IntegerField(null=True, blank=True)
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    summary = models.JSONField(default=dict, blank=True)
    backup_path = models.CharField(max_length=500, blank=True)

    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='scriptorium_runs',
    )

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['project', '-started_at']),
            models.Index(fields=['op', '-started_at']),
        ]

    def __str__(self):
        return f"{self.project.slug} · {self.get_op_display()} · {self.status} · {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None

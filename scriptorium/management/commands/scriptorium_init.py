"""Create or update a PhilologyProject row from environment variables.

Reads (with sensible defaults):

    SCRIPTORIUM_PROJECT_SLUG    (default: danwsi)
    SCRIPTORIUM_PROJECT_NAME    (default: DANWSI)
    SCRIPTORIUM_PROJECT_KIND    (default: danwsi)
    DANWSI_LOCAL_PATH           required for kind=danwsi
    DANWSI_VENV_PYTHON          default: <local_path>/venv/bin/python
    DANWSI_DJANGO_SETTINGS      default: danwsi_project.settings
    DANWSI_INGEST_COMMAND       default: ingest_ground_truth
    DANWSI_DATA_DIR_GLOB        default: Data_files*
    DANWSI_REMOTE_HOST          (optional)
    DANWSI_REMOTE_USER
    DANWSI_REMOTE_PATH
    DANWSI_REMOTE_PYTHON
    DANWSI_SSH_KEY_PATH
    DANWSI_DEPLOY_SCRIPT        default: deploy/deploy.sh
    DANWSI_PUBLIC_URL
    DANWSI_LOCAL_BACKUP_DIR     default: ~/danwsi-backups
    DANWSI_DB_FILENAME          default: db.sqlite3

Idempotent: re-running updates the row in place.
"""
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from scriptorium.models import PhilologyProject


def _env(key, default=''):
    return os.environ.get(key, default)


class Command(BaseCommand):
    help = "Create/update a PhilologyProject row from environment variables (no paths baked into the repo)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        slug = _env('SCRIPTORIUM_PROJECT_SLUG', 'danwsi')
        name = _env('SCRIPTORIUM_PROJECT_NAME', 'DANWSI')
        kind = _env('SCRIPTORIUM_PROJECT_KIND', 'danwsi')

        local_path = _env('DANWSI_LOCAL_PATH')
        if not local_path:
            raise CommandError(
                "DANWSI_LOCAL_PATH is required. Set it to the absolute path "
                "of your DANWSI Django project root (the dir with manage.py)."
            )
        local_path = str(Path(local_path).expanduser().resolve())

        venv_python = _env(
            'DANWSI_VENV_PYTHON',
            str(Path(local_path) / 'venv' / 'bin' / 'python'),
        )
        defaults = {
            'name': name,
            'kind': kind,
            'description': 'Auto-created by scriptorium_init from env vars.',
            'local_path': local_path,
            'venv_python': venv_python,
            'django_settings_module': _env('DANWSI_DJANGO_SETTINGS', 'danwsi_project.settings'),
            'data_dir_glob': _env('DANWSI_DATA_DIR_GLOB', 'Data_files*'),
            'data_files_dir_env': _env('DANWSI_DATA_FILES_DIR_ENV', 'DATA_FILES_DIR'),
            'ingest_command': _env('DANWSI_INGEST_COMMAND', 'ingest_ground_truth'),
            'remote_host': _env('DANWSI_REMOTE_HOST'),
            'remote_user': _env('DANWSI_REMOTE_USER'),
            'remote_path': _env('DANWSI_REMOTE_PATH'),
            'remote_python': _env('DANWSI_REMOTE_PYTHON'),
            'ssh_key_path': _env('DANWSI_SSH_KEY_PATH'),
            'deploy_script': _env('DANWSI_DEPLOY_SCRIPT', 'deploy/deploy.sh'),
            'public_url': _env('DANWSI_PUBLIC_URL'),
            'local_backup_dir': _env('DANWSI_LOCAL_BACKUP_DIR', str(Path.home() / 'danwsi-backups')),
            'db_filename': _env('DANWSI_DB_FILENAME', 'db.sqlite3'),
        }

        if opts['dry_run']:
            self.stdout.write(self.style.NOTICE(f"Would upsert PhilologyProject slug={slug}:"))
            for k, v in defaults.items():
                self.stdout.write(f"  {k}: {v}")
            return

        obj, created = PhilologyProject.objects.update_or_create(
            slug=slug, defaults=defaults,
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f"{action} PhilologyProject: {obj.slug} ({obj.name})"))

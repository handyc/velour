"""Regenerate deploy artifacts (gunicorn/supervisor/nginx + setup.sh/adminsetup.sh)
for a project directory, using the templates under app_factory/templates/deploy/.

This is how velour dogfoods its own factory: running this against the velour
source tree produces the exact same deploy artifacts the factory produces for
generated apps, keeping them in lockstep with whatever the templates currently
emit.
"""

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string


# (template_path, output_path_relative_to_target, executable)
DEPLOY_ARTIFACTS = [
    ('deploy/gunicorn.conf.py', 'deploy/gunicorn.conf.py', False),
    ('deploy/supervisor.conf',  'deploy/supervisor.conf',  False),
    ('deploy/nginx.conf',       'deploy/nginx.conf',       False),
    ('deploy/setup.sh',         'setup.sh',                True),
    ('deploy/adminsetup.sh',    'adminsetup.sh',           True),
    ('deploy/hotswap.sh',       'hotswap.sh',              True),
    ('deploy/install-macos.sh', 'install-macos.sh',        True),
]


def _default_server_name(deploy_user):
    """Compose a default nginx server_name from the Identity singleton.

    The base domain is read from identity.models.Identity.hostname, so an
    operator who sets their hostname to 'lucdh.nl' in the Identity settings
    gets all generated nginx configs pointing at <deploy_user>.lucdh.nl
    without ever passing --server-name. A fresh velour install with no
    Identity row falls back to 'example.com' — an obviously-placeholder
    domain that won't accidentally collide with a real production host.
    """
    try:
        from identity.models import Identity
        identity = Identity.get_self()
        base = (identity.hostname or 'example.com').strip()
    except Exception:
        # This path runs at Django management command time, so the ORM
        # should be available — but if the migration hasn't been applied
        # yet (fresh checkout, pre-migrate), fall back to the placeholder.
        base = 'example.com'
    return f'{deploy_user}.{base}'


def render_deploy_artifacts(target_dir, project_name, deploy_user,
                            app_label=None, server_name=None,
                            maintenance_root=None):
    """Render all deploy templates into target_dir. Returns the list of written paths."""
    target = Path(target_dir).resolve()
    if not target.is_dir():
        raise CommandError(f'Target directory does not exist: {target}')

    context = {
        'project_name': project_name,
        'deploy_user': deploy_user,
        'app_label': app_label or project_name,
        # If no explicit override, derive from the Identity singleton —
        # Identity.hostname is the single source of truth for this
        # instance's base domain.
        'server_name': server_name or _default_server_name(deploy_user),
        # Host-wide directory nginx falls back to when the upstream socket
        # is unreachable. Shared across all apps so a single maintenance
        # page covers the whole server; adminsetup.sh creates it on first
        # provision with a default index.html if nothing exists there yet.
        'maintenance_root': maintenance_root or '/var/www/maintenance',
    }

    (target / 'deploy').mkdir(parents=True, exist_ok=True)

    written = []
    for tmpl, out_rel, executable in DEPLOY_ARTIFACTS:
        content = render_to_string(tmpl, context)
        out_path = target / out_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content)
        if executable:
            os.chmod(out_path, 0o755)
        written.append(out_path)
    return written


class Command(BaseCommand):
    help = (
        'Generate deploy artifacts (gunicorn, supervisor, nginx, setup.sh, '
        'adminsetup.sh) for a project directory.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--target', required=True,
            help='Directory to write artifacts into (e.g., the project root).',
        )
        parser.add_argument(
            '--project', required=True,
            help='Python package name, used in wsgi + settings module (e.g. "velour").',
        )
        parser.add_argument(
            '--user', required=True, dest='deploy_user',
            help='Linux username the app runs as (e.g. "velour"). Drives all /var/www/webapps/<user>/ paths.',
        )
        parser.add_argument(
            '--label', default=None,
            help='Human-readable label used in generated comments/echoes. Defaults to --project.',
        )
        parser.add_argument(
            '--server-name', default=None, dest='server_name',
            help='nginx server_name directive. If omitted, derived from '
                 'Identity.hostname in the DB as <user>.<hostname>, '
                 'falling back to <user>.example.com.',
        )
        parser.add_argument(
            '--maintenance-root', default=None, dest='maintenance_root',
            help='Host directory nginx serves as a fallback when the upstream '
                 'socket is down. Defaults to /var/www/maintenance.',
        )

    def handle(self, *args, **opts):
        written = render_deploy_artifacts(
            target_dir=opts['target'],
            project_name=opts['project'],
            deploy_user=opts['deploy_user'],
            app_label=opts['label'],
            server_name=opts['server_name'],
            maintenance_root=opts['maintenance_root'],
        )
        for p in written:
            self.stdout.write(f'  wrote {p}')
        self.stdout.write(self.style.SUCCESS('Deploy artifacts generated.'))

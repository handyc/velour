"""Backfill workspace_share_token for pacts created before the field
existed.  Each row gets a fresh secrets.token_urlsafe(32); the value
is stable thereafter so a researcher who bookmarks a URL keeps using
the same token until somebody explicitly rotates it.
"""

import secrets

from django.db import migrations


def backfill(apps, schema_editor):
    Pact = apps.get_model('spoeqi', 'Pact')
    for p in Pact.objects.filter(workspace_share_token=''):
        p.workspace_share_token = secrets.token_urlsafe(32)
        p.save(update_fields=['workspace_share_token'])


def noop(apps, schema_editor):
    # Tokens are non-secret in the sense of "intentionally derivable
    # from a fresh secret" — there's nothing to undo on rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('spoeqi', '0007_pact_workspace_share_token'),
    ]
    operations = [
        migrations.RunPython(backfill, noop),
    ]

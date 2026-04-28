"""Consume a ``clone_init.json`` written at the project root by the
App Factory's clone flow, and apply its values to the Identity
singleton. Renames the file to ``.applied`` afterwards so re-runs are
no-ops — the operator can edit Identity normally from then on.

Idempotent. Safe to run on every boot, but typically called once
right after the first ``migrate`` on a fresh clone.

The file shape:

    {
      "instance_label": "Velour at the lab",
      "hostname":       "lab.example.com",
      "admin_email":    "ops@example.com"
    }

Empty/missing fields are skipped — they don't overwrite existing
Identity values with blanks.
"""

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from identity.models import Identity


CLONE_INIT_FILENAME = 'clone_init.json'


class Command(BaseCommand):
    help = 'Apply clone_init.json to the Identity singleton (idempotent).'

    def handle(self, *args, **opts):
        path = os.path.join(settings.BASE_DIR, CLONE_INIT_FILENAME)
        if not os.path.isfile(path):
            self.stdout.write(f'No {CLONE_INIT_FILENAME} at {settings.BASE_DIR} — nothing to do.')
            return

        with open(path) as f:
            try:
                payload = json.load(f)
            except json.JSONDecodeError as e:
                self.stderr.write(self.style.ERROR(
                    f'{CLONE_INIT_FILENAME} is not valid JSON: {e}',
                ))
                return

        identity = Identity.get_self()
        applied = []

        label = (payload.get('instance_label') or '').strip()
        if label and identity.name != label:
            identity.name = label
            applied.append(f'name → {label!r}')

        hostname = (payload.get('hostname') or '').strip()
        if hostname and identity.hostname != hostname:
            identity.hostname = hostname
            applied.append(f'hostname → {hostname!r}')

        email = (payload.get('admin_email') or '').strip()
        if email and identity.admin_email != email:
            identity.admin_email = email
            applied.append(f'admin_email → {email!r}')

        if applied:
            identity.save()
            self.stdout.write(self.style.SUCCESS(
                f'Applied clone_init: {", ".join(applied)}'
            ))
        else:
            self.stdout.write('clone_init.json had nothing to apply.')

        applied_path = path + '.applied'
        os.rename(path, applied_path)
        self.stdout.write(f'Renamed {CLONE_INIT_FILENAME} → '
                          f'{os.path.basename(applied_path)}')

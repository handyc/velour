"""Seed the three known settings.json scopes.  Re-runnable: upserts by
scope name (which is unique)."""

from __future__ import annotations

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from claudecode.models import SettingsScope


class Command(BaseCommand):
    help = 'Seed the user/project/local SettingsScope rows.'

    def handle(self, *args, **opts):
        base = settings.BASE_DIR
        targets = [
            ('user',    os.path.expanduser('~/.claude/settings.json')),
            ('project', os.path.join(base, '.claude', 'settings.json')),
            ('local',   os.path.join(base, '.claude', 'settings.local.json')),
        ]
        for name, path in targets:
            obj, created = SettingsScope.objects.update_or_create(
                name=name,
                defaults={'path': path, 'is_active': True},
            )
            verb = 'created' if created else 'updated'
            self.stdout.write(f'  {verb}: {name} -> {path}')

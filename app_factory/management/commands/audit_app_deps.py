"""Report inter-app import drift in app_factory.app_registry.

Useful when adding a new Velour app or refactoring imports — run
this and you'll see whether the registry's ``depends_on`` lists
still match the actual code.

    venv/bin/python manage.py audit_app_deps

A clean run prints "registry matches code, no drift" and exits 0.
A dirty run prints the missing/stale entries and exits 1.
"""

import sys

from django.core.management.base import BaseCommand

from app_factory.dep_audit import audit_optional_app_deps


class Command(BaseCommand):
    help = 'Audit OPTIONAL_APPS depends_on against scanned code imports.'

    def handle(self, *args, **opts):
        result = audit_optional_app_deps()
        missing, stale = result['missing'], result['stale']

        if not missing and not stale:
            self.stdout.write(self.style.SUCCESS(
                'registry matches code, no drift'
            ))
            return

        if missing:
            self.stdout.write(self.style.ERROR('Missing depends_on declarations:'))
            for app, deps in sorted(missing.items()):
                self.stdout.write(
                    f"  {app}: imports {sorted(deps)} but registry has none"
                )

        if stale:
            self.stdout.write(self.style.WARNING('\nStale depends_on declarations:'))
            for app, deps in sorted(stale.items()):
                self.stdout.write(
                    f"  {app}: registry declares {sorted(deps)} but no import found"
                )

        # Missing is the dangerous case (stripped clones may crash).
        # Stale is just cleanup.
        if missing:
            sys.exit(1)

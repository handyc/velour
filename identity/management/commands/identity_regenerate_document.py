"""Regenerate Velour's Identity Document.

Wipes the auto-derived IdentityAssertion rows and rebuilds them
from current system state, then pushes the result into the
'velours-identity-document' Codex manual as four sections (one
per frame — philosophical, social, mathematical, documentary).

Operator-authored and seed assertions are preserved across
regeneration — only rows with source='auto' are replaced.

Usage:
    python manage.py identity_regenerate_document
    python manage.py identity_regenerate_document --no-codex
        Skip the Codex push — rewrite the DB only.
"""

from django.core.management.base import BaseCommand

from identity.identity_document import rebuild_document, push_document_to_codex


class Command(BaseCommand):
    help = "Regenerate Velour's auto-derived identity assertions."

    def add_arguments(self, parser):
        parser.add_argument('--no-codex', action='store_true',
                            help='Skip pushing the document into '
                                 "Velour's Identity Document Codex manual.")

    def handle(self, *args, **opts):
        count = rebuild_document()
        self.stdout.write(self.style.SUCCESS(
            f'Rewrote {count} auto-derived IdentityAssertion rows'))
        if not opts['no_codex']:
            push_document_to_codex()
            self.stdout.write(self.style.SUCCESS(
                "Pushed into Codex manual 'velours-identity-document'"))

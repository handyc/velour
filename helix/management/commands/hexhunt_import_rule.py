"""Import a genome.bin (s3lab / ESP32-S3) as a Helix HuntRule.

Usage:
    manage.py hexhunt_import_rule path/to/genome.bin \\
        [--slug ...] [--name ...] [--notes ...]

The 4,096-byte payload is the same PackedRuleset blob Helix already
uses internally, so the imported rule can immediately be replayed at
``/helix/hexhunt/rules/<slug>/`` or fed to ``hexhunt_scan``.
"""

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from automaton.packed import parse_genome_bin

from helix.models import HuntRule


class Command(BaseCommand):
    help = 'Import an s3lab genome.bin as a HuntRule.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--slug', default='',
                            help='Rule slug; auto-generated if blank.')
        parser.add_argument('--name', default='',
                            help='Human label; defaults to file stem.')
        parser.add_argument('--notes', default='')

    def handle(self, *args, **opts):
        path = Path(opts['path'])
        if not path.exists():
            raise CommandError(f'no such file: {path}')
        try:
            data = path.read_bytes()
        except OSError as e:
            raise CommandError(f'cannot read {path}: {e}')
        try:
            palette, packed = parse_genome_bin(data)
        except ValueError as e:
            raise CommandError(f'bad genome.bin: {e}')

        sha1 = hashlib.sha1(packed.data).hexdigest()
        existing = HuntRule.objects.filter(
            provenance_json__blob_sha1=sha1,
        ).first()
        if existing:
            self.stdout.write(self.style.WARNING(
                f'identical rule already imported as {existing.slug} '
                f'({existing.name or "—"}). Skipping.'
            ))
            return

        slug = opts['slug'] or HuntRule.make_slug()
        if HuntRule.objects.filter(slug=slug).exists():
            raise CommandError(f'rule slug {slug!r} already exists')

        rule = HuntRule.objects.create(
            slug=slug,
            table=bytes(packed.data),
            name=opts['name'] or path.stem,
            notes=opts['notes'],
            provenance_json={
                'origin':       'imported',
                'source':       's3lab',
                'source_path':  str(path),
                'blob_sha1':    sha1,
                'palette_hex':  palette.hex(),
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f'Imported {path.name} as HuntRule {rule.slug} ({rule.name}).'
        ))
        self.stdout.write(
            f'  /helix/hexhunt/rules/{rule.slug}/'
        )

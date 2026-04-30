"""Import a genome.bin (s3lab / ESP32-S3) as an automaton RuleSet.

Usage:
    manage.py automaton_import_rule path/to/genome.bin \\
        [--name ...] [--notes ...]

The packed K=4 rule is materialised into ExactRule rows via
``PackedRuleset.to_explicit(skip_identity=True)`` — identity outputs
(where the cell keeps its own colour) are skipped, which compresses
typical evolved rules to a few thousand non-trivial patterns. The
resulting RuleSet replays through the existing ``step_exact`` and
``step_packed`` engines.
"""

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from automaton.models import ExactRule, RuleSet
from automaton.packed import parse_genome_bin


class Command(BaseCommand):
    help = 'Import an s3lab genome.bin as an automaton RuleSet.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--name', default='',
                            help='RuleSet name; defaults to file stem.')
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

        # Reuse existing import by sha1 if name not forced — automaton
        # does not have a stable hash field on RuleSet, so we look up
        # by source_metadata.blob_sha1 (set on previous imports).
        sha1 = hashlib.sha1(packed.data).hexdigest()
        existing = RuleSet.objects.filter(
            source_metadata__blob_sha1=sha1,
        ).first()
        if existing:
            self.stdout.write(self.style.WARNING(
                f'identical rule already imported as RuleSet '
                f'{existing.slug!r} ({existing.name}). Skipping.'
            ))
            return

        name = opts['name'] or f's3lab · {path.stem}'
        if RuleSet.objects.filter(name=name).exists():
            raise CommandError(f'RuleSet name {name!r} already exists')

        # Palette: 4 ANSI-256-style indices in s3lab. We don't know the
        # operator's preferred web palette here, so leave it blank and
        # fall back to automaton's DEFAULT_PALETTE; record the bytes in
        # source_metadata so the operator can reconstruct it later.
        palette_hex = palette.hex()

        explicit = packed.to_explicit(skip_identity=True)
        n_explicit = len(explicit)

        with transaction.atomic():
            ruleset = RuleSet.objects.create(
                name=name,
                description=opts['notes'] or (
                    f'Imported from s3lab genome.bin '
                    f'({path.name}, sha1 {sha1[:10]}…). '
                    f'{n_explicit} non-identity patterns + '
                    f'{4**7 - n_explicit} identity-default situations.'
                ),
                n_colors=4,
                source='operator',
                source_metadata={
                    'origin':       'imported',
                    'source':       's3lab',
                    'source_path':  str(path),
                    'blob_sha1':    sha1,
                    'palette_hex':  palette_hex,
                    'n_explicit':   n_explicit,
                },
            )
            ExactRule.objects.bulk_create([
                ExactRule(
                    ruleset=ruleset,
                    self_color=er['s'],
                    n0_color=er['n'][0], n1_color=er['n'][1],
                    n2_color=er['n'][2], n3_color=er['n'][3],
                    n4_color=er['n'][4], n5_color=er['n'][5],
                    result_color=er['r'],
                    priority=i,
                )
                for i, er in enumerate(explicit)
            ])

        self.stdout.write(self.style.SUCCESS(
            f'Imported {path.name} as RuleSet {ruleset.slug!r} '
            f'with {n_explicit:,} non-identity ExactRule rows.'
        ))

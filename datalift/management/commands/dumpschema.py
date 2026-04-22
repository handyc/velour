"""Extract schema from a mysqldump, discarding every row value.

    python manage.py dumpschema path/to/full_dump.sql --out schema.sql

Output contains CREATE TABLE blocks, standalone CREATE INDEX, and
ALTER TABLE … ADD … FOREIGN KEY statements — nothing else. No
INSERT statements, no AUTO_INCREMENT row counts, no LOCK TABLES
boilerplate.

This is the Claude-safe half of the mysqldump → Django workflow:
the resulting schema.sql has no data values, so you can share it
with a model-generating assistant without leaking anything from
the original database.
"""

from __future__ import annotations

import re
import sys

from django.core.management.base import BaseCommand, CommandError

from datalift.dump_parser import iter_create_tables, strip_auto_increment


_ALTER_RE = re.compile(
    r"ALTER\s+TABLE\s+[`\"]?[^\s`\"]+[`\"]?\s+[^;]+?FOREIGN\s+KEY[^;]*;",
    re.IGNORECASE | re.DOTALL,
)

_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+[^;]+;",
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = 'Extract schema-only SQL from a mysqldump (no data values).'

    def add_arguments(self, parser):
        parser.add_argument(
            'input',
            help='Path to the mysqldump .sql file.',
        )
        parser.add_argument(
            '--out', default='-',
            help='Output path; "-" writes to stdout (default).',
        )
        parser.add_argument(
            '--keep-auto-increment', action='store_true',
            help='Preserve AUTO_INCREMENT=<n> counters (leaks row totals).',
        )

    def handle(self, *args, **opts):
        path = opts['input']
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError as e:
            raise CommandError(f'cannot read {path}: {e}')

        parts: list[str] = []
        n_tables = 0
        for name, ddl in iter_create_tables(text):
            if not opts['keep_auto_increment']:
                ddl = strip_auto_increment(ddl)
            parts.append(ddl)
            n_tables += 1

        for m in _CREATE_INDEX_RE.finditer(text):
            parts.append(m.group(0))
        for m in _ALTER_RE.finditer(text):
            parts.append(m.group(0))

        out = (
            '-- Schema extracted from ' + path + '\n'
            '-- Data rows omitted.\n\n'
            + '\n\n'.join(parts)
            + '\n'
        )

        target = opts['out']
        if target == '-':
            sys.stdout.write(out)
        else:
            with open(target, 'w', encoding='utf-8') as fh:
                fh.write(out)
            self.stdout.write(
                f'Wrote {n_tables} table(s) + indexes + FK constraints → {target}'
            )

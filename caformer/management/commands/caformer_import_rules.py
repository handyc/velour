"""Ingest one or more flat-file rule artifacts into the QRPair DB.

Each input file is a stream of RuleRecords (see caformer/io/rule_blob.py).
Records are grouped by (pair_pk, rule_shape, port_src), sorted by
position, concatenated into a per-pair blob, and written to the
appropriate QRPair field:

  - rule_shape = cell8  → QRPair.cell8_b256_rules_blob
                          QRPair.cell8_input_source = <port_src>
                          QRPair.cell8_b256_exact = True iff
                              every position 0..n-1 is present
  - rule_shape = 7to1   → QRPair.board128_rules_blob
                          QRPair.board128_exact = True iff every
                              position present

Last-write-wins per pair; conflicts are logged.  --dry-run prints
what would change without touching the DB.

  manage.py caformer_import_rules chunk_a.rules chunk_b.rules
  manage.py caformer_import_rules outputs/*.rules --dry-run
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Merge one or more .rules files into QRPair.cell8_b256_rules_blob '
            '(or board128_rules_blob for 7→1 records).')

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='+', type=str,
                              help='one or more .rules files to ingest')
        parser.add_argument('--dry-run', action='store_true',
                              help='print what would change but do not write')
        parser.add_argument('--require-complete', action='store_true',
                              help='abort upsert for any pair where some '
                                     'positions are missing (default: write '
                                     'whatever positions we have, mark exact=False)')

    def handle(self, *, files, dry_run, require_complete, **opts):
        from caformer.models import QRPair
        from caformer.io.rule_blob import (read_records, SHAPE_CELL8,
                                                   SHAPE_7TO1, SHAPE_LEN,
                                                   SHAPE_NAME)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        log(f'=== caformer_import_rules ===')
        log(f'  files:        {len(files)}  ({", ".join(files)})')
        log(f'  dry-run:      {dry_run}')
        log(f'  require-full: {require_complete}\n')

        # Bucket records by (pair_pk, shape, port_src), then by position.
        # bucket[(pk, shape, port_src)] = {position: (rule_blob, byte_matched)}
        bucket = defaultdict(dict)
        n_records = 0
        n_files_read = 0
        for fname in files:
            p = Path(fname)
            if not p.exists():
                log(f'  skip {fname}: not found')
                continue
            n_files_read += 1
            file_recs = 0
            for rec in read_records(p):
                key = (rec.pair_pk, rec.rule_shape, rec.port_src)
                prev = bucket[key].get(rec.position)
                if prev is not None and prev[0] != rec.rule_blob:
                    log(f'  conflict {p.name}: pk={rec.pair_pk} '
                        f'pos={rec.position} shape={SHAPE_NAME[rec.rule_shape]} '
                        f'port={rec.port_src} (last-write-wins)')
                bucket[key][rec.position] = (rec.rule_blob, rec.byte_matched)
                file_recs += 1
            n_records += file_recs
            log(f'  read {p.name}: {file_recs} records')
        log(f'  total records: {n_records} from {n_files_read} files')
        log(f'  pair × shape × port_src buckets: {len(bucket)}\n')

        # For each pair_pk, find what the expected response length is —
        # this is the canonical n_positions for that pair.  Pull it from
        # the DB so we can decide "exact" correctly.
        pks_needed = sorted({k[0] for k in bucket.keys()})
        pairs = {p.pk: p for p in QRPair.objects.filter(pk__in=pks_needed)}
        missing = [pk for pk in pks_needed if pk not in pairs]
        if missing:
            log(f'  WARNING: {len(missing)} pks have no QRPair row: {missing}')

        # Plan + execute upserts.
        n_writes = 0
        n_exact = 0
        for (pk, shape, port_src), pos_info in sorted(bucket.items()):
            pair = pairs.get(pk)
            if pair is None:
                log(f'  skip pk={pk}: no QRPair row')
                continue
            expected_n = len(pair.expected.encode('utf-8'))
            positions = sorted(pos_info.keys())
            have_n = len(positions)
            present = (positions == list(range(expected_n)))
            # True "exact" requires every position to be both present
            # AND byte-matched (per-record byte_matched flag).  Older
            # v1 records read with byte_matched=True (legacy default).
            all_matched = all(pos_info[i][1] for i in positions)
            exact = present and all_matched
            shape_name = SHAPE_NAME[shape]
            rule_len = SHAPE_LEN[shape]

            if require_complete and not present:
                log(f'  skip pk={pk} shape={shape_name} port={port_src}: '
                    f'incomplete ({have_n}/{expected_n})')
                continue

            # Concatenate positions 0..max in order, padding gaps with
            # zero blobs (rare; happens only if some position failed to
            # train and we're not requiring complete).
            max_pos = max(positions)
            zero_blob = bytes(rule_len)
            concat = b''.join(pos_info.get(i, (zero_blob, False))[0]
                                  for i in range(max_pos + 1))

            if shape == SHAPE_CELL8:
                field, exact_field = 'cell8_b256_rules_blob', 'cell8_b256_exact'
            elif shape == SHAPE_7TO1:
                field, exact_field = 'board128_rules_blob', 'board128_exact'
            else:
                log(f'  skip pk={pk}: unknown shape {shape}')
                continue

            matched_n = sum(1 for i in positions if pos_info[i][1])
            log(f'  pk={pk:4d} shape={shape_name:5s} port={port_src:9s} '
                f'positions={have_n}/{expected_n} present  '
                f'{matched_n}/{have_n} byte-matched  '
                f'{"EXACT ✓" if exact else "partial"}  '
                f'blob={len(concat)} B')

            if dry_run:
                continue

            setattr(pair, field, concat)
            setattr(pair, exact_field, exact)
            if shape == SHAPE_CELL8:
                pair.cell8_input_source = port_src
            pair.save(update_fields=[field, exact_field] +
                          (['cell8_input_source'] if shape == SHAPE_CELL8 else []))
            n_writes += 1
            if exact:
                n_exact += 1

        log(f'\n=== done ===')
        log(f'  upserts:  {n_writes}'
            + (' (dry-run, nothing saved)' if dry_run else ''))
        log(f'  exact:    {n_exact}')

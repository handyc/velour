"""Bulk-import a corpus as QRPair rows.

Currently supports Shakespeare extraction (sonnets baked in, plays
loaded from a text file).  The extractor produces (prompt, expected,
label, ...) dicts; this command turns them into QRPair rows via
bulk_create with sensible defaults so the existing trainer pipeline
can train them at any tier (board128 / cell8+256).

Usage examples:

  # Sonnets (baked into caformer/internalize.py, no file needed)
  manage.py caformer_import_corpus --source sonnets \\
      --strategy continuation --limit 80

  # A play text file (drop /tmp/hamlet.txt from Folger / Gutenberg)
  manage.py caformer_import_corpus --source-file /tmp/hamlet.txt \\
      --strategy all --label shakespeare-hamlet

  # Just Hamlet's lines, internal speech continuation
  manage.py caformer_import_corpus --source-file /tmp/hamlet.txt \\
      --strategy speaker_continuation --speaker HAMLET

  # Dry-run shows the first 10 pairs without writing
  manage.py caformer_import_corpus --source-file /tmp/hamlet.txt \\
      --strategy speaker --dry-run --preview 10
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Bulk-import a text corpus as QRPair rows (Shakespeare etc.)')

    def add_arguments(self, parser):
        src = parser.add_mutually_exclusive_group(required=True)
        src.add_argument('--source', choices=['sonnets'],
                            help='use a baked-in corpus')
        src.add_argument('--source-file', type=str,
                            help='path to a UTF-8 text file (a play, novel, etc.)')

        parser.add_argument('--strategy', type=str, default='continuation',
                              choices=['continuation', 'speaker',
                                          'speaker_continuation', 'all'])
        parser.add_argument('--speaker', type=str, default=None,
                              help='for speaker_continuation: only this speaker')
        parser.add_argument('--label', type=str, default='shakespeare',
                              help='QRPair.label value (default: shakespeare)')
        parser.add_argument('--limit', type=int, default=0,
                              help='cap on pairs imported (0 = no cap)')
        parser.add_argument('--preview', type=int, default=5,
                              help='how many pairs to print as preview')
        parser.add_argument('--min-prompt-len', type=int, default=6)
        parser.add_argument('--max-prompt-len', type=int, default=180)
        parser.add_argument('--min-expected-len', type=int, default=2)
        parser.add_argument('--max-expected-len', type=int, default=180)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *, source, source_file, strategy, speaker, label,
                 limit, preview, min_prompt_len, max_prompt_len,
                 min_expected_len, max_expected_len, dry_run, **opts):
        from caformer.corpora.shakespeare import extract_pairs
        from caformer.models import QRPair

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        # Load the text.
        if source == 'sonnets':
            from caformer.internalize import SHAKESPEARE_SONNETS
            text = SHAKESPEARE_SONNETS.decode('utf-8', errors='replace')
            text_source = 'baked sonnets (~3.2 KB)'
        else:
            p = Path(source_file)
            if not p.exists():
                raise CommandError(f'source-file not found: {p}')
            text = p.read_text(encoding='utf-8', errors='replace')
            text_source = f'{p} ({len(text)} chars)'

        log(f'=== caformer_import_corpus ===')
        log(f'  source:    {text_source}')
        log(f'  strategy:  {strategy}'
            + (f' (speaker={speaker})' if speaker else ''))
        log(f'  label:     {label}')
        log(f'  limit:     {limit or "no cap"}')
        log(f'  dry-run:   {dry_run}\n')

        pairs = extract_pairs(text, strategy=strategy, label=label,
                                  speaker_filter=speaker)
        log(f'  extracted: {len(pairs)} raw pairs')

        # Length filters.
        filtered = []
        for p in pairs:
            pl = len(p['prompt'])
            el = len(p['expected'])
            if not (min_prompt_len <= pl <= max_prompt_len):
                continue
            if not (min_expected_len <= el <= max_expected_len):
                continue
            filtered.append(p)
        log(f'  filtered:  {len(filtered)} (after length constraints)')

        if limit and len(filtered) > limit:
            filtered = filtered[:limit]
            log(f'  capped at: {limit}')

        # Preview.
        if preview:
            log(f'\n--- first {min(preview, len(filtered))} pairs ---')
            for p in filtered[:preview]:
                extra = f' [{p.get("speaker", "")}]' if p.get('speaker') else ''
                log(f'  {p["strategy"]:22s}{extra}')
                log(f'    prompt:   {p["prompt"][:80]!r}')
                log(f'    expected: {p["expected"][:80]!r}')

        # Bulk-create.
        if dry_run:
            log(f'\n  DRY RUN: would create {len(filtered)} QRPair rows '
                f'with label={label!r}')
            return

        # Skip pairs already in the DB (idempotent).
        existing_keys = set(
            QRPair.objects.filter(label__startswith=label)
                              .values_list('prompt', 'expected'))
        rows_to_create = []
        n_dup = 0
        for p in filtered:
            key = (p['prompt'], p['expected'])
            if key in existing_keys:
                n_dup += 1
                continue
            existing_keys.add(key)
            # Use the pair's own label (may include speaker suffix).
            rows_to_create.append(QRPair(
                prompt=p['prompt'],
                expected=p['expected'],
                label=(p.get('label') or label)[:40],
                notes=f'imported: source=shakespeare strategy={p.get("strategy")}',
            ))
        log(f'\n  skipping {n_dup} duplicates already in DB')
        log(f'  creating {len(rows_to_create)} new QRPair rows…')
        QRPair.objects.bulk_create(rows_to_create, batch_size=500)
        log(f'  done.')

"""Fetch a curated corpus of GenBank records from NCBI for Helix.

Default set is a small + medium mix designed to be fully playable in
the browser viewer (under ~5 MB per record). Larger records are gated
behind explicit flags:

    --include-bacteria          adds E. coli K-12 (4.6 Mb, ~5,000 features)
    --include-drosophila-nuclear  adds D. mel chr 2L/2R/3L/3R/X/Y
                                  (~140 Mb total — slow to load in the viewer)

Idempotent: records already present (matched by accession) are skipped
unless --force is passed. NCBI Entrez requires a contact email; defaults
to the project user's address.
"""

import time

from django.core.management.base import BaseCommand
from django.db import transaction

from helix.models import AnnotationFeature, SequenceRecord
from helix.parsers import parse_text


# (accession, friendly title, group)
DEFAULT_CORPUS = [
    ('L09137.2',    'pUC19 cloning vector',                   'classic'),
    ('NC_001416.1', 'Enterobacteria phage λ',                 'classic'),
    ('NC_045512.2', 'SARS-CoV-2 (Wuhan-Hu-1) reference',      'classic'),
    ('NC_001133.9', 'Saccharomyces cerevisiae chromosome I',  'yeast'),
    ('NC_024511.2', 'Drosophila melanogaster mitochondrion',  'drosophila'),
    ('NC_004353.4', 'Drosophila melanogaster chromosome 4',   'drosophila'),
]

BACTERIAL_CORPUS = [
    ('U00096.3',    'Escherichia coli K-12 substr. MG1655',   'bacteria'),
]

DROSOPHILA_NUCLEAR_CORPUS = [
    ('NT_033779.5', 'Drosophila melanogaster chromosome 2L',  'drosophila'),
    ('NT_033778.4', 'Drosophila melanogaster chromosome 2R',  'drosophila'),
    ('NT_037436.4', 'Drosophila melanogaster chromosome 3L',  'drosophila'),
    ('NT_033777.3', 'Drosophila melanogaster chromosome 3R',  'drosophila'),
    ('NC_004354.4', 'Drosophila melanogaster chromosome X',   'drosophila'),
    ('NC_024512.1', 'Drosophila melanogaster chromosome Y',   'drosophila'),
]


class Command(BaseCommand):
    help = 'Fetch curated GenBank records from NCBI for Helix to play with.'

    def add_arguments(self, parser):
        parser.add_argument('--include-bacteria', action='store_true',
                            help='Add E. coli K-12 MG1655 (4.6 Mb, ~5,000 features).')
        parser.add_argument('--include-drosophila-nuclear', action='store_true',
                            help='Add Dmel chromosomes 2L/2R/3L/3R/X/Y (~140 Mb total).')
        parser.add_argument('--only', default='',
                            help='Comma-separated accessions to fetch instead of the default set.')
        parser.add_argument('--force', action='store_true',
                            help='Re-download and replace records that already exist.')
        parser.add_argument('--list', action='store_true',
                            help='Print what would be fetched and exit.')
        parser.add_argument('--email', default='c.a.handy@hum.leidenuniv.nl',
                            help='Contact address for NCBI Entrez (required by their policy).')
        parser.add_argument('--api-key', default='',
                            help='Optional NCBI API key — raises rate limit from 3/s to 10/s.')

    def handle(self, *args, **opts):
        from Bio import Entrez

        Entrez.email = opts['email']
        if opts['api_key']:
            Entrez.api_key = opts['api_key']

        targets = list(DEFAULT_CORPUS)
        if opts['include_bacteria']:
            targets += BACTERIAL_CORPUS
        if opts['include_drosophila_nuclear']:
            targets += DROSOPHILA_NUCLEAR_CORPUS

        if opts['only']:
            keep = {x.strip() for x in opts['only'].split(',') if x.strip()}
            # Allow --only with accessions outside the curated lists.
            known = {t[0] for t in targets}
            extras = [(a, f'(custom) {a}', 'custom') for a in keep if a not in known]
            targets = [t for t in targets if t[0] in keep] + extras
            if not targets:
                self.stderr.write('--only matched no targets; aborting.')
                return

        if opts['list']:
            for a, t, g in targets:
                self.stdout.write(f'  {a:<14} {g:<11} {t}')
            return

        existing = set(
            SequenceRecord.objects
            .filter(accession__in=[t[0] for t in targets])
            .values_list('accession', flat=True)
        )

        # Strip the version suffix when comparing — Biopython sometimes
        # returns the un-versioned form ("NC_001416" vs "NC_001416.1").
        existing_unver = {a.split('.')[0] for a in existing}

        self.stdout.write(self.style.NOTICE(
            f'Helix corpus: {len(targets)} record(s) to consider '
            f'({sum(1 for a, _, _ in targets if a in existing or a.split(".")[0] in existing_unver)} already imported).'
        ))

        for i, (accession, title, group) in enumerate(targets, 1):
            already = (accession in existing
                       or accession.split('.')[0] in existing_unver)
            if already and not opts['force']:
                self.stdout.write(f'  [{i}/{len(targets)}] {accession:<14} skip — already imported')
                continue

            self.stdout.write(
                f'  [{i}/{len(targets)}] {accession:<14} fetching {title}…',
                ending=' ',
            )
            self.stdout.flush()

            try:
                t0 = time.time()
                with Entrez.efetch(db='nuccore', id=accession,
                                   rettype='gbwithparts', retmode='text') as h:
                    text = h.read()
                fetch_s = time.time() - t0
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'fetch failed: {e}'))
                continue

            if not text or not text.lstrip().startswith('LOCUS'):
                # NCBI sometimes returns an HTML error page on rate-limit
                # or transient failure; surface that instead of crashing.
                self.stdout.write(self.style.ERROR(
                    f'unexpected response (first 80 chars: {text[:80]!r})'
                ))
                continue

            try:
                fmt, records = parse_text(text, filename=f'{accession}.gb')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'parse failed: {e}'))
                continue

            if not records:
                self.stdout.write(self.style.WARNING('no records parsed'))
                continue

            saved = self._persist(records, title_override=title,
                                  replace_existing=already and opts['force'])
            n_feat = sum(r.features.count() for r in saved)
            mb = sum(r.length_bp for r in saved) / 1_000_000.0
            self.stdout.write(self.style.SUCCESS(
                f'OK · {fetch_s:.1f}s · {mb:.2f} Mb · {n_feat} features'
            ))

            # Polite pacing for Entrez (3 req/s without an API key).
            time.sleep(0.4)

        self.stdout.write(self.style.SUCCESS('done.'))

    def _persist(self, record_dicts, title_override='', replace_existing=False):
        saved = []
        with transaction.atomic():
            for i, rd in enumerate(record_dicts):
                if replace_existing:
                    SequenceRecord.objects.filter(accession=rd['accession']).delete()
                features = rd.pop('features', [])
                if title_override and i == 0:
                    rd['title'] = title_override
                rec = SequenceRecord.objects.create(**rd)
                AnnotationFeature.objects.bulk_create([
                    AnnotationFeature(record=rec, **f) for f in features
                ])
                saved.append(rec)
        return saved

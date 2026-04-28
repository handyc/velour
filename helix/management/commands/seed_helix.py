"""Seed Helix with a small annotated GenBank-style demo so the app
isn't empty on first boot.

The demo is hand-built (not downloaded) to keep the seeder offline-safe:
a 1.2 KB synthetic prokaryotic-style sequence with two genes / CDSs and
a ribosomal binding site. Idempotent — re-runs replace the demo record
in place.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from helix.models import AnnotationFeature, SequenceRecord


DEMO_TITLE = 'Demo · Helix synthetic genome'
DEMO_ACCESSION = 'HX-DEMO-001'

# Hand-built ~1200 bp prokaryotic-flavour sequence. ATG starts at 100
# and 700, both ending in stop codons (TAA / TGA). Some pretty noise
# in between so the GC plot looks real.
DEMO_SEQ = (
    'ATGCGGTAACTGTACCGGAATCCGGAATTCGCGTAGCTAGGCATGCAATCGCATGCATGC'   # 0
    'GGCGTACGTAGCATGCAATCGGATCGAATCGCATCGCATCGCATCGCAGCGCATCGAACG'   # 60
    'AAGGAGGTGAATAAATG'                                              # 120 (RBS + ATG @ 137? — see below)
    'CAATATGCAGGTGAACTACAACGCAGTGGAGTACGGCAACGAACGCATCGTGAACGGCGG'   # 137
    'CAACAACGGCAACGGCGGCAACGGCAACGGCAACAACGGCAACTGCAACGCAACTGTGAA'   # 197
    'CTACAACGCAGTGGAGTACTAA'                                          # 257
    'CGCAGCAGCAGCAGCATCATCATCATCATCATCATCATCATCATGCATGGCATCGCAGCG'   # 279
    'CTGCAGCAGCAGCATCATGCATGCAGCATGCATCATGCAGTACGCAGTGCAGCATGCATG'   # 339
    'CAGCATGCAGCAGCAGCATCATGCAGCAGCAGCATCATCAGCAGCAGCAGCATCATCATG'   # 399
    'CAGCAGCAGCAGCATCAGCATCAGCATCAGCAGCATCATCATCATCAGCAGCAGCAGCAT'   # 459
    'CAGCATGCATGCATGCAGCATGCATCAGCATGCAGCATGCAGCATGCAGCATGCAGCATG'   # 519
    'CAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGC'   # 579
    'ATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGCAGCATGC'   # 639
    'AGGAGGTGAACGAAATG'                                              # 699 (RBS + 2nd ATG @ 716)
    'GCAACAGCAGCAGCATCATGCATCATCAGCAGCAGCATCATCATCAGCAGCAGCAGCATC'   # 716
    'ATCAGCAGCAGCAGCATCATGCAGCAGCAGCATCAGCAGCAGCAGCATCAGCAGCAGCAG'   # 776
    'CATCAGCAGCAGCAGCATCATGCAGCAGCAGCATCAGCAGCAGCAGCATCATGCAGCAGC'   # 836
    'AGCAGCAGCATCATGCAGCAGCAGCATCAGCAGCATCATGCAGCAGCAGCATCATGCAGC'   # 896
    'AGCAGCAGCATCATGCAGCAGCAGCATCAGCAGCAGCAGCATGA'                  # 956 (TGA stop)
    'GCATCATCAGCAGCAGCAGCATCAGCAGCATCATGCAGCAGCAGCATCATGCAGCAGCAG'   # 1000
    'CAGCAGCATCATGCAGCAGCAGCATCAGCAGCATCATGCAGCAGCAGCATCATGCAGCAG'   # 1060
    'CAGCAGCAGCATCATGCAGCAGCAGCATCAGCAGCATCATGCAGCAGCAGCATCATGCAG'   # 1120
    'CAGCAGCAGCAGCATCATGCAGCAGCAGCATCAG'                             # 1180
)

# Coordinates are 0-based half-open.
DEMO_FEATURES = [
    {'feature_type': 'source',     'start': 0,    'end': len(DEMO_SEQ),
     'strand': 1,
     'qualifiers': {'organism': ['synthetic construct'], 'mol_type': ['genomic DNA']}},

    {'feature_type': 'regulatory', 'start': 120,  'end': 134, 'strand': 1,
     'qualifiers': {'regulatory_class': ['ribosome_binding_site'],
                    'note': ['putative Shine-Dalgarno upstream of helX-1']}},
    {'feature_type': 'gene',       'start': 137,  'end': 280, 'strand': 1,
     'qualifiers': {'gene': ['helX-1'], 'locus_tag': ['HX001']}},
    {'feature_type': 'CDS',        'start': 137,  'end': 280, 'strand': 1,
     'qualifiers': {'gene': ['helX-1'], 'product': ['hypothetical protein 1'],
                    'locus_tag': ['HX001'], 'codon_start': ['1'],
                    'transl_table': ['11']}},

    {'feature_type': 'regulatory', 'start': 699,  'end': 713, 'strand': 1,
     'qualifiers': {'regulatory_class': ['ribosome_binding_site'],
                    'note': ['putative Shine-Dalgarno upstream of helX-2']}},
    {'feature_type': 'gene',       'start': 716,  'end': 1000, 'strand': 1,
     'qualifiers': {'gene': ['helX-2'], 'locus_tag': ['HX002']}},
    {'feature_type': 'CDS',        'start': 716,  'end': 1000, 'strand': 1,
     'qualifiers': {'gene': ['helX-2'], 'product': ['hypothetical protein 2'],
                    'locus_tag': ['HX002'], 'codon_start': ['1'],
                    'transl_table': ['11']}},

    {'feature_type': 'misc_feature', 'start': 600, 'end': 700, 'strand': 1,
     'qualifiers': {'note': ['low-complexity GC-rich linker']}},
]


class Command(BaseCommand):
    help = 'Seed Helix with a small annotated demo genome (idempotent).'

    @transaction.atomic
    def handle(self, *args, **opts):
        existing = SequenceRecord.objects.filter(accession=DEMO_ACCESSION).first()
        if existing:
            existing.delete()

        rec = SequenceRecord.objects.create(
            title=DEMO_TITLE,
            accession=DEMO_ACCESSION,
            organism='synthetic construct',
            sequence_type='DNA',
            sequence=DEMO_SEQ,
            source_format='genbank',
            source_filename='seed_helix.py',
            description='Synthetic prokaryotic-style demo with two genes/CDSs '
                        'and matching ribosome-binding-site annotations.',
            metadata={'molecule_type': 'genomic DNA',
                      'topology': 'linear', 'date': 'seeded'},
        )
        AnnotationFeature.objects.bulk_create([
            AnnotationFeature(record=rec, **f) for f in DEMO_FEATURES
        ])
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {DEMO_TITLE} ({rec.length_bp} bp, '
            f'{len(DEMO_FEATURES)} features) at /helix/{rec.pk}/'
        ))

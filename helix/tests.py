"""Helix tests — parser correctness + model invariants + view smoke.

The parser tests are the load-bearing ones: they lock in that
SeqIO output keeps mapping cleanly into our record-dict shape,
which is what the import view consumes.
"""

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from helix.models import AnnotationFeature, SequenceRecord
from helix.parsers import (
    _detect_seq_type,
    parse_fasta,
    parse_genbank,
    parse_text,
)


SAMPLE_FASTA = """>HX-TEST hypothetical
ATGCAGTAACGCAGCAGCAGCATCATGCAACTGTGAACTACAACGCAGTGGAGTACTAA
"""

SAMPLE_FASTA_RNA = """>HX-RNA-TEST short RNA
AUGCAGUAACGCAGCAG
"""

# A minimal valid GenBank with one CDS feature.
SAMPLE_GENBANK = """LOCUS       HXTEST                    100 bp    DNA     linear   SYN 28-APR-2026
DEFINITION  Helix test record.
ACCESSION   HXTEST
VERSION     HXTEST.1
SOURCE      synthetic construct
  ORGANISM  synthetic construct
            other; artificial sequences.
FEATURES             Location/Qualifiers
     source          1..100
                     /organism="synthetic construct"
                     /mol_type="genomic DNA"
     gene            10..60
                     /gene="testGene"
                     /locus_tag="HXT001"
     CDS             10..60
                     /gene="testGene"
                     /product="test protein"
                     /codon_start=1
                     /transl_table=11
ORIGIN
        1 atgcagtaac gcagcagcag catcatgcaa ctgtgaacta caacgcagtg gagtactaaa
       61 cgcagcagca gcatcatgca actgtgaact acaacgcagt
//
"""


class SeqTypeDetectionTests(SimpleTestCase):
    def test_dna_default(self):
        self.assertEqual(_detect_seq_type('ACGTACGTACGT'), 'DNA')

    def test_rna_via_uracil(self):
        self.assertEqual(_detect_seq_type('AUGCAUGCAUGC'), 'RNA')

    def test_protein_via_amino_letters(self):
        self.assertEqual(_detect_seq_type('MKVLWAALLVTFLAGCQAKVEQAVE'), 'protein')

    def test_declared_molecule_type_wins(self):
        # Declared mRNA → RNA even with no Us in the sequence.
        self.assertEqual(_detect_seq_type('ACGTACGT', declared_molecule_type='mRNA'),
                         'RNA')


class FastaParserTests(SimpleTestCase):
    def test_parse_single_record(self):
        recs = parse_fasta(SAMPLE_FASTA, filename='test.fa')
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r['accession'], 'HX-TEST')
        self.assertEqual(r['sequence_type'], 'DNA')
        self.assertEqual(r['source_format'], 'fasta')
        self.assertEqual(r['source_filename'], 'test.fa')
        self.assertEqual(r['features'], [])
        self.assertTrue(r['sequence'].startswith('ATGCAG'))

    def test_parse_rna_via_uracil(self):
        recs = parse_fasta(SAMPLE_FASTA_RNA)
        self.assertEqual(recs[0]['sequence_type'], 'RNA')


class GenBankParserTests(SimpleTestCase):
    def test_parse_extracts_features_and_metadata(self):
        recs = parse_genbank(SAMPLE_GENBANK, filename='hxtest.gb')
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r['source_format'], 'genbank')
        self.assertEqual(r['organism'], 'synthetic construct')
        self.assertIn('molecule_type', r['metadata'])

        feature_types = [f['feature_type'] for f in r['features']]
        self.assertIn('source', feature_types)
        self.assertIn('gene', feature_types)
        self.assertIn('CDS', feature_types)

        cds = [f for f in r['features'] if f['feature_type'] == 'CDS'][0]
        # GenBank "10..60" → 0-based half-open [9, 60].
        self.assertEqual(cds['start'], 9)
        self.assertEqual(cds['end'], 60)
        self.assertEqual(cds['qualifiers']['gene'], ['testGene'])


class FormatSniffingTests(SimpleTestCase):
    def test_sniff_fasta(self):
        fmt, recs = parse_text(SAMPLE_FASTA)
        self.assertEqual(fmt, 'fasta')
        self.assertEqual(len(recs), 1)

    def test_sniff_genbank(self):
        fmt, recs = parse_text(SAMPLE_GENBANK)
        self.assertEqual(fmt, 'genbank')
        self.assertEqual(len(recs), 1)

    def test_sniff_unknown_raises(self):
        with self.assertRaises(ValueError):
            parse_text('not actually a sequence file at all')


class SequenceRecordModelTests(TestCase):
    def test_save_strips_whitespace_and_uppercases(self):
        r = SequenceRecord.objects.create(
            title='ws test',
            sequence='at gc\nat\tgc atgc',
            sequence_type='DNA',
            source_format='fasta',
        )
        self.assertEqual(r.sequence, 'ATGCATGCATGC')
        self.assertEqual(r.length_bp, 12)

    def test_gc_content(self):
        r = SequenceRecord.objects.create(
            title='gc',
            sequence='AAGGCC',  # 4/6 = 0.6666...
            sequence_type='DNA',
            source_format='fasta',
        )
        self.assertAlmostEqual(r.gc_content(), 4 / 6)

    def test_gc_content_none_for_protein(self):
        r = SequenceRecord.objects.create(
            title='p', sequence='MKVL',
            sequence_type='protein', source_format='fasta',
        )
        self.assertIsNone(r.gc_content())


class AnnotationFeatureModelTests(TestCase):
    def setUp(self):
        self.rec = SequenceRecord.objects.create(
            title='r', sequence='A' * 100,
            sequence_type='DNA', source_format='fasta',
        )

    def test_display_name_prefers_gene_then_product(self):
        f = AnnotationFeature.objects.create(
            record=self.rec, feature_type='CDS', start=0, end=10,
            qualifiers={'gene': ['gX'], 'product': ['protein X']},
        )
        self.assertEqual(f.display_name(), 'gX')

        f2 = AnnotationFeature.objects.create(
            record=self.rec, feature_type='CDS', start=10, end=20,
            qualifiers={'product': ['protein only']},
        )
        self.assertEqual(f2.display_name(), 'protein only')

        f3 = AnnotationFeature.objects.create(
            record=self.rec, feature_type='regulatory', start=20, end=30,
            qualifiers={},
        )
        # Falls back to the feature_type.
        self.assertEqual(f3.display_name(), 'regulatory')


class ViewSmokeTests(TestCase):
    """Stripped-down smoke tests — auth-gated views require a login."""

    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw')
        self.client.force_login(self.user)

    def test_list_renders(self):
        resp = self.client.get(reverse('helix:list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Helix')

    def test_upload_get_renders(self):
        resp = self.client.get(reverse('helix:upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Upload sequence')

    def test_upload_fasta_creates_record(self):
        resp = self.client.post(reverse('helix:upload'), {
            'pasted': SAMPLE_FASTA,
        })
        # Single record → redirects to detail
        self.assertEqual(resp.status_code, 302)
        rec = SequenceRecord.objects.get(accession='HX-TEST')
        self.assertEqual(rec.source_format, 'fasta')
        self.assertEqual(rec.created_by, self.user)

    def test_upload_genbank_extracts_features(self):
        resp = self.client.post(reverse('helix:upload'), {
            'pasted': SAMPLE_GENBANK,
        })
        self.assertEqual(resp.status_code, 302)
        rec = SequenceRecord.objects.get(accession__startswith='HXTEST')
        self.assertGreaterEqual(rec.features.count(), 3)  # source + gene + CDS

    def test_detail_renders_after_seed(self):
        rec = SequenceRecord.objects.create(
            title='x', accession='X1', sequence='ACGT' * 25,
            sequence_type='DNA', source_format='fasta',
        )
        resp = self.client.get(reverse('helix:detail', args=[rec.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'X1')

    def test_download_fasta(self):
        rec = SequenceRecord.objects.create(
            title='dl', accession='DL1', sequence='ACGT' * 30,
            sequence_type='DNA', source_format='fasta',
        )
        resp = self.client.get(reverse('helix:download_fasta', args=[rec.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/plain; charset=utf-8')
        self.assertIn('attachment', resp['Content-Disposition'])
        body = resp.content.decode('utf-8')
        self.assertTrue(body.startswith('>DL1'))

    def test_delete_post(self):
        rec = SequenceRecord.objects.create(
            title='del', sequence='A' * 4, sequence_type='DNA',
            source_format='fasta',
        )
        resp = self.client.post(reverse('helix:delete', args=[rec.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(SequenceRecord.objects.filter(pk=rec.pk).exists())


class ToEvolutionTests(TestCase):
    """Helix → Evolution Engine bridge: slice a sequence and create a run."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('eve', password='pw')
        cls.rec = SequenceRecord.objects.create(
            title='evolve-test', accession='EV1',
            # 200 bp deterministic sequence — long enough for the
            # min-length gate, short enough to fit the 5,000 bp cap
            # several times over.
            sequence='ACGT' * 50,
            sequence_type='DNA', source_format='fasta',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_toward_creates_run_with_goal_only(self):
        from evolution.models import EvolutionRun
        resp = self.client.post(
            reverse('helix:to_evolution', args=[self.rec.pk]),
            {'start': 0, 'end': 100, 'mode': 'toward'},
        )
        self.assertEqual(resp.status_code, 302)
        run = EvolutionRun.objects.latest('created')
        self.assertEqual(run.goal_string, 'ACGT' * 25)
        self.assertEqual(run.params['gene_type'], 'dna')
        self.assertNotIn('seed_string', run.params)
        origin = run.params['helix_origin']
        self.assertEqual(origin['record_pk'], self.rec.pk)
        self.assertEqual(origin['start'], 0)
        self.assertEqual(origin['end'], 100)
        self.assertEqual(origin['mode'], 'toward')

    def test_from_creates_run_with_seed(self):
        from evolution.models import EvolutionRun
        resp = self.client.post(
            reverse('helix:to_evolution', args=[self.rec.pk]),
            {'start': 20, 'end': 80, 'mode': 'from'},
        )
        self.assertEqual(resp.status_code, 302)
        run = EvolutionRun.objects.latest('created')
        # Same slice in goal AND seed.
        self.assertEqual(run.goal_string, ('ACGT' * 50)[20:80])
        self.assertEqual(run.params['seed_string'], ('ACGT' * 50)[20:80])
        self.assertEqual(run.params['helix_origin']['mode'], 'from')

    def test_rejects_too_long_slice(self):
        rec = SequenceRecord.objects.create(
            title='big', accession='BIG1', sequence='A' * 6000,
            sequence_type='DNA', source_format='fasta',
        )
        resp = self.client.post(
            reverse('helix:to_evolution', args=[rec.pk]),
            {'start': 0, 'end': 5500, 'mode': 'toward'},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b'too long', resp.content)

    def test_rejects_too_short_slice(self):
        resp = self.client.post(
            reverse('helix:to_evolution', args=[self.rec.pk]),
            {'start': 0, 'end': 5, 'mode': 'toward'},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b'too short', resp.content)

    def test_invalid_mode_falls_back_to_toward(self):
        from evolution.models import EvolutionRun
        resp = self.client.post(
            reverse('helix:to_evolution', args=[self.rec.pk]),
            {'start': 0, 'end': 50, 'mode': 'sideways'},
        )
        self.assertEqual(resp.status_code, 302)
        run = EvolutionRun.objects.latest('created')
        self.assertEqual(run.params['helix_origin']['mode'], 'toward')

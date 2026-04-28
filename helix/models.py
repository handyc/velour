"""Helix — genome viewer / annotator data model.

Two tables hold what we parse out of FASTA / GenBank uploads:

- SequenceRecord: one DNA / RNA / protein sequence. FASTA and GenBank
  both produce records; GenBank records additionally carry organism,
  accession, molecule_type, and a list of features.
- AnnotationFeature: one annotated region on a SequenceRecord —
  gene / CDS / mRNA / regulatory / etc. Mirrors GenBank's feature
  shape. FASTA records have no features; GenBank records typically
  have many.

Coordinates are 0-based, half-open ``[start, end)`` — Biopython's
convention, easier for slicing than the 1-based inclusive form GenBank
uses on disk.
"""

from django.db import models


SEQ_TYPE_CHOICES = [
    ('DNA',     'DNA'),
    ('RNA',     'RNA'),
    ('protein', 'Protein'),
]

SOURCE_FORMAT_CHOICES = [
    ('fasta',   'FASTA'),
    ('genbank', 'GenBank'),
]

STRAND_CHOICES = [
    (1,  '+ (forward)'),
    (-1, '- (reverse)'),
    (0,  '. (unstranded)'),
]


class SequenceRecord(models.Model):
    """One sequence — a single FASTA record or a single GenBank LOCUS."""

    title = models.CharField(
        max_length=300,
        help_text='Human label — defaults to FASTA description or GenBank '
                  'definition line.',
    )
    accession = models.CharField(
        max_length=80, blank=True,
        help_text='NCBI/EMBL accession if the source had one.',
    )
    organism = models.CharField(
        max_length=200, blank=True,
        help_text='From GenBank ORGANISM field. Blank for FASTA.',
    )
    sequence_type = models.CharField(
        max_length=10, choices=SEQ_TYPE_CHOICES, default='DNA',
    )
    sequence = models.TextField(
        help_text='Bases or amino acids, uppercase, no whitespace.',
    )
    length_bp = models.PositiveIntegerField(
        default=0,
        help_text='Cached length of `sequence` for fast list / detail '
                  'rendering. Recomputed on save.',
    )
    source_format = models.CharField(
        max_length=20, choices=SOURCE_FORMAT_CHOICES,
    )
    source_filename = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text='Format-specific metadata: GenBank molecule_type, '
                  'date, keywords, etc.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['accession']),
        ]

    def __str__(self):
        return f'{self.title} ({self.length_bp} {self.sequence_type})'

    def save(self, *args, **kwargs):
        # Strip any whitespace from the sequence before persisting so
        # callers can hand us pretty-printed input. Recompute length so
        # the cached value never lies.
        self.sequence = ''.join(self.sequence.split()).upper()
        self.length_bp = len(self.sequence)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('helix:detail', args=[self.pk])

    def gc_content(self):
        """Return G+C as a fraction, or None for non-DNA/RNA."""
        if self.sequence_type not in ('DNA', 'RNA') or not self.sequence:
            return None
        gc = self.sequence.count('G') + self.sequence.count('C')
        return gc / len(self.sequence)

    def feature_type_counts(self):
        """{'gene': 12, 'CDS': 12, ...} — for the detail-page summary."""
        counts = {}
        for ft in self.features.values_list('feature_type', flat=True):
            counts[ft] = counts.get(ft, 0) + 1
        return counts


class AnnotationFeature(models.Model):
    """One annotated region — gene, CDS, mRNA, regulatory, etc.

    Coordinates are 0-based half-open: ``sequence[start:end]``.
    """

    record = models.ForeignKey(
        SequenceRecord, on_delete=models.CASCADE, related_name='features',
    )
    feature_type = models.CharField(
        max_length=40,
        help_text="GenBank feature type — 'gene', 'CDS', 'mRNA', "
                  "'regulatory', 'misc_feature', etc.",
    )
    start = models.PositiveIntegerField(help_text='0-based inclusive start.')
    end = models.PositiveIntegerField(help_text='0-based exclusive end.')
    strand = models.IntegerField(default=1, choices=STRAND_CHOICES)
    qualifiers = models.JSONField(
        default=dict, blank=True,
        help_text='GenBank qualifiers — gene name, product, locus_tag, '
                  'note, db_xref, etc.',
    )

    class Meta:
        ordering = ['start', 'end']
        indexes = [
            models.Index(fields=['record', 'start']),
            models.Index(fields=['feature_type']),
        ]

    def __str__(self):
        return f'{self.feature_type} {self.start}-{self.end} on {self.record_id}'

    def length(self):
        return self.end - self.start

    def display_name(self):
        """Best human label: gene name, product, locus_tag, or feature_type."""
        q = self.qualifiers or {}
        for key in ('gene', 'product', 'locus_tag', 'note'):
            v = q.get(key)
            if v:
                # Biopython qualifiers are usually lists.
                if isinstance(v, list):
                    return v[0]
                return str(v)
        return self.feature_type

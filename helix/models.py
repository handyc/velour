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
from django.utils.crypto import get_random_string


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


# ── Hex-CA hunt on organic sequences ─────────────────────────────────
#
# A hunt is the same shape as Velour's automaton/s3lab work — K=4,
# 7-cell positional hex CA, ``automaton.packed.PackedRuleset`` as the
# canonical 4,096-byte rule blob — but the *corpus* is windows of real
# DNA / RNA from SequenceRecord, never random seeds. Tournament fitness
# is "richness under rule X averaged across organic windows."
#
# Rules discovered here can be exported as JSON (slug + base64 table +
# provenance) and replayed in s3lab on synthetic seeds, but the corpora
# never mix.


class HuntCorpus(models.Model):
    """A named set of equal-length DNA windows pulled from real records.

    One corpus = one biological hypothesis ("Drosophila CDS at 256 bp").
    A tournament evolves rules against this corpus; a filter scan
    applies a rule across a whole record. Windows are materialised once
    via ``hexhunt_seed_corpus`` and frozen so successive runs score
    against identical input.
    """

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    feature_type = models.CharField(
        max_length=40, blank=True,
        help_text='AnnotationFeature.feature_type the windows were drawn '
                  'from. Blank = mixed / no feature filter.',
    )
    window_size = models.PositiveIntegerField(default=256)
    windows_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} (n={self.windows_count}, w={self.window_size})'


class HuntWindow(models.Model):
    """One DNA window in a HuntCorpus — coords, no sequence stored.

    The window's bases are sliced from ``record.sequence`` on demand;
    that keeps the corpus small even when it points at a 32 Mb
    chromosome.
    """

    corpus = models.ForeignKey(
        HuntCorpus, on_delete=models.CASCADE, related_name='windows',
    )
    record = models.ForeignKey(
        SequenceRecord, on_delete=models.CASCADE, related_name='+',
    )
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    feature = models.ForeignKey(
        AnnotationFeature, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    idx = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['corpus', 'idx']
        indexes = [
            models.Index(fields=['corpus', 'idx']),
        ]

    def __str__(self):
        return f'{self.corpus.slug}#{self.idx} {self.record_id}:{self.start}-{self.end}'

    def sequence(self):
        return self.record.sequence[self.start:self.end]


class HuntRule(models.Model):
    """One K=4 hex-CA ruleset, packed into 4,096 bytes.

    The byte layout matches ``automaton.packed.PackedRuleset`` and
    s3lab's in-browser rule format — same indexing
    (``self*K^6 + n0*K^5 + ... + n5``), same neighbour order
    (N, NE, SE, S, SW, NW). A rule discovered here can be loaded into
    s3lab or automaton without translation.

    ``provenance_json`` records how the rule came to be:
      {"origin": "random", "seed": 1234}
      {"origin": "mutation", "parent_slug": "...", "rate": 0.001}
      {"origin": "crossover", "parent_a": "...", "parent_b": "..."}
      {"origin": "tournament_winner", "run_slug": "..."}
      {"origin": "imported", "source": "s3lab", "blob_sha1": "..."}
    """

    slug = models.SlugField(max_length=80, unique=True)
    table = models.BinaryField(
        help_text='4,096 bytes — PackedRuleset.data for K=4.',
    )
    name = models.CharField(max_length=200, blank=True)
    parent_rule = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='children',
    )
    class_label = models.CharField(
        max_length=8, blank=True,
        help_text="Wolfram class best-guess: 'I' / 'II' / 'III' / 'IV'. "
                  'Optional; populated by analysis, not the engine.',
    )
    provenance_json = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name or self.slug

    @classmethod
    def make_slug(cls):
        """Compact unique slug — collision-checked."""
        while True:
            s = get_random_string(8).lower()
            if not cls.objects.filter(slug=s).exists():
                return s

    def packed(self):
        """Return an ``automaton.packed.PackedRuleset`` view of this rule."""
        from automaton.packed import PackedRuleset
        return PackedRuleset(n_colors=4, data=bytes(self.table))


class HuntRun(models.Model):
    """One tournament run: corpus + GA params → ranked rules.

    ``params_json`` keeps everything the engine needs to reproduce the
    run from scratch — population_size, generations, mutation_rate,
    scoring_fn, mapping, board shape, step budget, RNG seed.
    """

    STATUS_CHOICES = [
        ('pending',  'Pending'),
        ('running',  'Running'),
        ('done',     'Done'),
        ('failed',   'Failed'),
    ]

    slug = models.SlugField(max_length=80, unique=True)
    corpus = models.ForeignKey(
        HuntCorpus, on_delete=models.CASCADE, related_name='runs',
    )
    params_json = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default='pending',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    top_rule = models.ForeignKey(
        HuntRule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    scoreboard_json = models.JSONField(
        default=list, blank=True,
        help_text='Top-N entries from the final generation: '
                  '[{"rule_slug":..., "score":..., "rank":...}].',
    )
    generation_log_json = models.JSONField(
        default=list, blank=True,
        help_text='Per-generation summary: [{"gen":i,"best":x,"mean":y}].',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.corpus.slug}/{self.slug} ({self.status})'

    @classmethod
    def make_slug(cls):
        while True:
            s = get_random_string(8).lower()
            if not cls.objects.filter(slug=s).exists():
                return s


class RuleFilterScan(models.Model):
    """Apply one rule across a whole SequenceRecord, store per-window richness.

    The "rule as motif detector" use case: an evolved Class-IV rule
    becomes a 4 KB ab-initio scanner. Output ``track_json`` lays
    alongside Helix's existing annotation tracks at any zoom.
    """

    slug = models.SlugField(max_length=80, unique=True)
    rule = models.ForeignKey(
        HuntRule, on_delete=models.CASCADE, related_name='scans',
    )
    record = models.ForeignKey(
        SequenceRecord, on_delete=models.CASCADE, related_name='+',
    )
    window_size = models.PositiveIntegerField(default=256)
    stride = models.PositiveIntegerField(default=128)
    scoring_fn = models.CharField(max_length=40, default='gzip')
    track_json = models.JSONField(
        default=list, blank=True,
        help_text='[[start, end, score], ...] — sorted by start.',
    )
    n_windows = models.PositiveIntegerField(
        default=0,
        help_text='Windows processed so far. Equals total_windows when done.',
    )
    total_windows = models.PositiveIntegerField(
        default=0,
        help_text='Expected window count, set at launch time.',
    )
    score_min = models.FloatField(default=0.0)
    score_max = models.FloatField(default=0.0)
    score_mean = models.FloatField(default=0.0)
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('done',    'Done'),
        ('failed',  'Failed'),
    ]
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='done',
        help_text="Default 'done' so historical rows remain valid.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.rule.slug} × {self.record_id} ({self.n_windows}w)'

    @classmethod
    def make_slug(cls):
        while True:
            s = get_random_string(8).lower()
            if not cls.objects.filter(slug=s).exists():
                return s

"""Umbra — homomorphic encryption workbench.

Phase 1 (this file): catalogue + experiment scaffold.  Real
ciphertext generation lands in phase 2 once Pyfhel / Concrete are
pip-installed and a runner is wired up.
"""
from django.db import models
from django.utils.text import slugify


class Scheme(models.Model):
    """One FHE scheme (BFV / BGV / CKKS / TFHE / etc.).  Catalogues
    the broad shape — datatype, exactness, intended workload — so
    Experiments can pick the right one without re-deriving the
    landscape every time."""

    DATATYPE_INT      = 'int'
    DATATYPE_FLOAT    = 'float'
    DATATYPE_BOOL     = 'bool'
    DATATYPE_VECTOR   = 'vector'
    DATATYPE_CHOICES  = [
        (DATATYPE_INT,    'integer (exact)'),
        (DATATYPE_FLOAT,  'float (approximate)'),
        (DATATYPE_BOOL,   'boolean / bit'),
        (DATATYPE_VECTOR, 'packed vector'),
    ]

    name             = models.CharField(max_length=64, unique=True)
    slug             = models.SlugField(max_length=64, unique=True)
    family           = models.CharField(max_length=64, blank=True,
                                        help_text='RLWE / LWE / GSW / etc.')
    datatype         = models.CharField(max_length=16,
                                        choices=DATATYPE_CHOICES,
                                        default=DATATYPE_INT)
    bootstrappable   = models.BooleanField(default=False,
        help_text='Does the scheme support full bootstrapping in practice?')
    year_introduced  = models.PositiveIntegerField(null=True, blank=True)
    paper_title      = models.CharField(max_length=256, blank=True)
    paper_url        = models.URLField(blank=True)
    summary          = models.TextField(blank=True,
        help_text='One-paragraph plain-English description.')
    parameter_notes  = models.TextField(blank=True,
        help_text='Typical poly-modulus / plaintext-modulus / scale '
                  'choices people use.')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Reference(models.Model):
    """External resource — paper, library repo, awesome-list, blog post,
    talk.  Catalogued so /umbra/ becomes a curated entry-point into the
    field, not just a code editor."""

    KIND_PAPER     = 'paper'
    KIND_LIBRARY   = 'library'
    KIND_AWESOME   = 'awesome'
    KIND_BLOG      = 'blog'
    KIND_TALK      = 'talk'
    KIND_REPO      = 'repo'
    KIND_TUTORIAL  = 'tutorial'
    KIND_CHOICES   = [
        (KIND_PAPER,    'paper'),
        (KIND_LIBRARY,  'library'),
        (KIND_AWESOME,  'awesome-list'),
        (KIND_BLOG,     'blog post'),
        (KIND_TALK,     'talk / video'),
        (KIND_REPO,     'repository'),
        (KIND_TUTORIAL, 'tutorial'),
    ]

    title    = models.CharField(max_length=256)
    slug     = models.SlugField(max_length=128, unique=True)
    url      = models.URLField()
    kind     = models.CharField(max_length=16, choices=KIND_CHOICES,
                                default=KIND_LIBRARY)
    authors  = models.CharField(max_length=256, blank=True)
    year     = models.PositiveIntegerField(null=True, blank=True)
    summary  = models.TextField(blank=True)
    schemes  = models.ManyToManyField(Scheme, blank=True,
        related_name='references',
        help_text='Schemes implemented or discussed by this resource.')
    tags     = models.CharField(max_length=128, blank=True,
        help_text='Comma-separated topical tags.')

    class Meta:
        ordering = ['kind', 'title']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:120] or 'reference'
        super().save(*args, **kwargs)

    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]


class Experiment(models.Model):
    """A user-authored FHE pipeline.  In phase 1 it stores the source
    code + notes; phase 2 will add an execution runner that pipes the
    code through Pyfhel / Concrete and captures timing + ciphertext-
    size measurements."""

    STATUS_DRAFT   = 'draft'
    STATUS_SAVED   = 'saved'
    STATUS_RUNNING = 'running'
    STATUS_DONE    = 'done'
    STATUS_FAILED  = 'failed'
    STATUS_CHOICES = [
        (STATUS_DRAFT,   'draft'),
        (STATUS_SAVED,   'saved'),
        (STATUS_RUNNING, 'running'),
        (STATUS_DONE,    'done'),
        (STATUS_FAILED,  'failed'),
    ]

    name        = models.CharField(max_length=128)
    slug        = models.SlugField(max_length=128, unique=True)
    scheme      = models.ForeignKey(Scheme, on_delete=models.PROTECT,
                                    related_name='experiments',
                                    null=True, blank=True)
    description = models.TextField(blank=True)
    code        = models.TextField(blank=True,
        help_text='Python source.  In phase 1 this is just stored; '
                  'phase 2 pipes it through a runner.')
    status      = models.CharField(max_length=16, choices=STATUS_CHOICES,
                                   default=STATUS_DRAFT)
    last_output = models.TextField(blank=True,
        help_text='Captured stdout from the most recent run (phase 2+).')
    last_error  = models.TextField(blank=True)
    last_run_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:120] or 'experiment'
            slug = base
            i = 2
            while Experiment.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class CorpusLabSession(models.Model):
    """Linguistic CSV (one form per cell) encrypted byte-by-byte under
    Concrete TFHE.  Each cell becomes a fixed-length byte array padded
    with 0-sentinels; ops are per-cell sealed transformations applied
    via programmable bootstrapping (PBS) — table-lookups under seal.

    Same threat model as CsvLabSession: key, encryption, ops, decryption
    all in one Django request.  Pedagogical demo of the sealed
    linguistic-CSV pipeline shape, not a real privacy boundary.

    Ops schema lives in corpuslab.py."""

    name           = models.CharField(max_length=128, blank=True)
    slug           = models.SlugField(max_length=128, unique=True)
    original_csv   = models.TextField()
    result_csv     = models.TextField(blank=True)
    ops_json       = models.TextField(blank=True, default='[]',
        help_text='JSON list of {op, ...} dicts; see corpuslab.OP_*.')
    rows           = models.PositiveIntegerField(default=0)
    cols           = models.PositiveIntegerField(default=0)
    cells          = models.PositiveIntegerField(default=0,
        help_text='Non-empty cells in the grid.')
    max_cell_len   = models.PositiveIntegerField(default=0,
        help_text='Padded length each cell was zero-padded to before encrypt.')
    chars_total    = models.PositiveIntegerField(default=0,
        help_text='Total bytes encrypted (cells × max_cell_len).')
    compile_ms     = models.PositiveIntegerField(default=0)
    encrypt_ms     = models.PositiveIntegerField(default=0)
    ops_ms         = models.PositiveIntegerField(default=0)
    decrypt_ms     = models.PositiveIntegerField(default=0)
    last_error     = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name or f'corpuslab-{self.pk}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:120] or 'corpus'
            slug = base
            i = 2
            while CorpusLabSession.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class CsvLabSession(models.Model):
    """CSV uploaded, parsed, encrypted cell-by-cell with CKKS, then
    mutated by a queued list of ops, then decrypted back to a CSV.
    All in-process — the secret key, ops, and decryption share one
    Django request, so this is a *demonstration* of the round-trip,
    not a real privacy boundary.  See ops_json schema in csvlab.py."""

    name          = models.CharField(max_length=128, blank=True)
    slug          = models.SlugField(max_length=128, unique=True)
    original_csv  = models.TextField()
    result_csv    = models.TextField(blank=True)
    ops_json      = models.TextField(blank=True, default='[]',
        help_text='JSON list of {op, ...} dicts; see csvlab.OP_*.')
    rows          = models.PositiveIntegerField(default=0)
    cols          = models.PositiveIntegerField(default=0)
    numeric_cells = models.PositiveIntegerField(default=0)
    ciphertext_bytes = models.PositiveIntegerField(default=0,
        help_text='Total serialized size of all cell ciphertexts.')
    encrypt_ms    = models.PositiveIntegerField(default=0)
    ops_ms        = models.PositiveIntegerField(default=0)
    decrypt_ms    = models.PositiveIntegerField(default=0)
    last_error    = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name or f'csvlab-{self.pk}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:120] or 'csv'
            slug = base
            i = 2
            while CsvLabSession.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

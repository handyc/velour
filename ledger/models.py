"""Ledger — spreadsheet data model.

Five tables back the Phase 1 spreadsheet:

- Workbook — bound artefact, owner, slug.
- Sheet — one tab inside a workbook. Has a name and an order index.
- Cell — one row/col on a sheet. Stores the raw `value` (what the user
  typed, including a leading `=` for a formula), the parsed
  `formula` text, and the `computed_value` of the formula or value.
  `format_json` carries display hints (number format, alignment).
- NamedRange — workbook-scoped name → A1-style range string.
- FormulaLanguage — registry row identifying a pluggable formula
  evaluator. Default seed is "excel" (formulas pkg). Velour's pattern:
  data-as-registry rather than hard-coded language IDs, so a custom
  language can be added as a row + a Python class without a migration.

Coordinates are 0-based internally — row=0, col=0 is A1 — and converted
to A1 strings only at the boundary (UI + named-range strings).
"""

from django.db import models
from django.utils.text import slugify


class FormulaLanguage(models.Model):
    """Registry row for a pluggable formula evaluator.

    The actual evaluator class is resolved by `slug` in
    ``ledger.engine.LANGUAGES``. Adding a new language = adding a row
    here AND a class in the engine module.
    """

    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    version = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.slug})'


class Workbook(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    owner = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_workbooks',
    )
    formula_language = models.ForeignKey(
        FormulaLanguage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='workbooks',
        help_text='Default formula language for this workbook. Per-cell '
                  'override planned for Phase 2.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:300] or 'workbook'
            candidate, n = base, 2
            while Workbook.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('ledger:detail', args=[self.slug])

    def cell_count(self):
        from django.db.models import Count
        return Cell.objects.filter(sheet__workbook=self).count()


class Sheet(models.Model):
    workbook = models.ForeignKey(
        Workbook, on_delete=models.CASCADE, related_name='sheets',
    )
    name = models.CharField(max_length=80, default='Sheet1')
    order = models.PositiveIntegerField(default=0)
    rows = models.PositiveIntegerField(
        default=20,
        help_text='Visible row count for the grid. Cells beyond this are '
                  'kept; the UI just doesn\'t draw them by default.',
    )
    cols = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ['workbook', 'order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['workbook', 'name'], name='ledger_sheet_name_per_wb',
            ),
        ]

    def __str__(self):
        return f'{self.workbook.title} · {self.name}'

    def cells_as_grid(self):
        """Return a {(row, col): Cell} dict — handy for templates."""
        return {(c.row, c.col): c for c in self.cells.all()}


class Cell(models.Model):
    sheet = models.ForeignKey(
        Sheet, on_delete=models.CASCADE, related_name='cells',
    )
    row = models.PositiveIntegerField()
    col = models.PositiveIntegerField()
    value = models.TextField(
        blank=True,
        help_text='Raw user-entered text. Starts with "=" for a formula.',
    )
    formula = models.TextField(
        blank=True,
        help_text='Trimmed formula source — value with the leading "=" '
                  'stripped. Empty for plain values.',
    )
    computed_value = models.TextField(
        blank=True,
        help_text='String form of the evaluated result, or "" for empty / '
                  'unparsed cells.',
    )
    format_json = models.JSONField(
        default=dict, blank=True,
        help_text='Display hints — {"align": "right", "format": "0.00"}.',
    )

    class Meta:
        ordering = ['sheet', 'row', 'col']
        constraints = [
            models.UniqueConstraint(
                fields=['sheet', 'row', 'col'], name='ledger_cell_unique_rc',
            ),
        ]
        indexes = [
            models.Index(fields=['sheet', 'row']),
            models.Index(fields=['sheet', 'col']),
        ]

    def __str__(self):
        return f'{self.a1}: {self.value!r}'

    @property
    def a1(self):
        return col_to_letter(self.col) + str(self.row + 1)

    def is_formula(self):
        return self.value.startswith('=')


class NamedRange(models.Model):
    workbook = models.ForeignKey(
        Workbook, on_delete=models.CASCADE, related_name='named_ranges',
    )
    name = models.CharField(max_length=80)
    a1_range = models.CharField(
        max_length=120,
        help_text='A1-style range, e.g. "Sheet1!A1:A10".',
    )

    class Meta:
        ordering = ['workbook', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['workbook', 'name'], name='ledger_named_range_unique',
            ),
        ]

    def __str__(self):
        return f'{self.name} = {self.a1_range}'


def col_to_letter(col):
    """0 → A, 25 → Z, 26 → AA, 27 → AB, ..."""
    out = ''
    n = col
    while True:
        out = chr(ord('A') + n % 26) + out
        n = n // 26 - 1
        if n < 0:
            break
    return out


def letter_to_col(letters):
    """'A' → 0, 'Z' → 25, 'AA' → 26."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n - 1

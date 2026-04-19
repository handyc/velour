from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone as djtz


# Rolling-window: prefer recent snapshots so a stale 2024 price doesn't
# drag the average after we've got fresh 2026 data.
PRICE_WINDOW_DAYS = 90
PRICE_WINDOW_MAX_SNAPS = 10


class Part(models.Model):
    """A component in the parts library.

    Grows as circuits are designed — every new component encountered
    gets a Part row so we end up with a living inventory and price sheet.
    """

    CATEGORY_CHOICES = [
        ('resistor',   'Resistor'),
        ('capacitor',  'Capacitor'),
        ('supercap',   'Supercapacitor'),
        ('inductor',   'Inductor'),
        ('diode',      'Diode'),
        ('schottky',   'Schottky diode'),
        ('zener',      'Zener diode'),
        ('led',        'LED'),
        ('transistor', 'Transistor (BJT)'),
        ('mosfet',     'MOSFET'),
        ('ic',         'IC'),
        ('mcu',        'MCU'),
        ('regulator',  'Regulator / LDO'),
        ('comparator', 'Comparator'),
        ('opamp',      'Op-amp'),
        ('connector',  'Connector'),
        ('switch',     'Switch'),
        ('panel',      'Solar panel'),
        ('battery',    'Battery'),
        ('crystal',    'Crystal / oscillator'),
        ('misc',       'Misc'),
    ]

    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    mpn = models.CharField(
        max_length=120, blank=True,
        help_text="Manufacturer part number.",
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='misc',
    )
    specs = models.JSONField(
        default=dict, blank=True,
        help_text='Structured specs, e.g. {"vf_mv": 450, "if_a": 1.0}.',
    )
    datasheet_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    est_unit_price_usd = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Average unit price, recomputed from price snapshots.",
    )
    price_last_checked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name}"

    def recompute_avg_price(self):
        """Average the most recent snapshots inside PRICE_WINDOW_DAYS,
        capped at PRICE_WINDOW_MAX_SNAPS. Falls back to all-time if the
        window is empty (useful right after a fresh seed with no recent
        observations)."""
        cutoff = djtz.now() - timedelta(days=PRICE_WINDOW_DAYS)
        window = list(
            self.price_snapshots
                .filter(observed_at__gte=cutoff)
                .order_by('-observed_at')[:PRICE_WINDOW_MAX_SNAPS]
        )
        if not window:
            window = list(
                self.price_snapshots.all()[:PRICE_WINDOW_MAX_SNAPS]
            )
        if not window:
            return
        total = sum((s.unit_price_usd for s in window), Decimal('0'))
        avg = (total / len(window)).quantize(Decimal('0.0001'))
        self.est_unit_price_usd = avg
        self.price_last_checked_at = djtz.now()
        self.save(update_fields=['est_unit_price_usd',
                                 'price_last_checked_at'])

    def avg_price_by_vendor(self):
        """Rolling-window unit price per vendor. Same window/cap as the
        blended average, applied per-vendor bucket. Returns a dict of
        {vendor: Decimal}; vendors with zero snapshots are omitted."""
        cutoff = djtz.now() - timedelta(days=PRICE_WINDOW_DAYS)
        buckets = {}
        for snap in self.price_snapshots.all():
            buckets.setdefault(snap.vendor, []).append(snap)
        out = {}
        for vendor, snaps in buckets.items():
            snaps.sort(key=lambda s: s.observed_at, reverse=True)
            window = [s for s in snaps if s.observed_at >= cutoff][:PRICE_WINDOW_MAX_SNAPS]
            if not window:
                window = snaps[:PRICE_WINDOW_MAX_SNAPS]
            if not window:
                continue
            total = sum((s.unit_price_usd for s in window), Decimal('0'))
            out[vendor] = (total / len(window)).quantize(Decimal('0.0001'))
        return out


class PartPriceSnapshot(models.Model):
    """One observed price for a Part from some vendor."""

    part = models.ForeignKey(
        Part, on_delete=models.CASCADE, related_name='price_snapshots',
    )
    vendor = models.CharField(max_length=100)
    unit_price_usd = models.DecimalField(max_digits=10, decimal_places=4)
    qty_break = models.PositiveIntegerField(
        default=1,
        help_text="Quantity break the price was quoted at (1 = single unit).",
    )
    source_url = models.URLField(blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-observed_at']

    def __str__(self):
        return f"{self.part.name} @ {self.vendor}: ${self.unit_price_usd}"


class Circuit(models.Model):
    """A power-supply / circuit experiment: description + schematic + BOM."""

    STATUS_DRAFT = 'draft'
    STATUS_BREADBOARD = 'breadboard'
    STATUS_PERFBOARD = 'perfboard'
    STATUS_PCB = 'pcb'
    STATUS_SHELVED = 'shelved'
    STATUS_CHOICES = [
        (STATUS_DRAFT,      'draft'),
        (STATUS_BREADBOARD, 'breadboard'),
        (STATUS_PERFBOARD,  'perfboard'),
        (STATUS_PCB,        'pcb'),
        (STATUS_SHELVED,    'shelved'),
    ]

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=160)
    tagline = models.CharField(max_length=240, blank=True)
    body_md = models.TextField(blank=True)

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT,
    )

    diagram_kind = models.CharField(
        max_length=20, blank=True,
        help_text="Kroki diagram kind (e.g. 'svgbob', 'tikz', 'ditaa').",
    )
    diagram_source = models.TextField(
        blank=True,
        help_text="Diagram source — rendered via codex.rendering.diagrams.",
    )

    # MVP browser schematic editor: nodes + wires in a single JSON blob.
    # See powerlab/schematic.py for shape and SVG rendering.
    schematic_json = models.JSONField(
        default=dict, blank=True,
        help_text="Browser-edited schematic — { nodes: [...], wires: [...] }.",
    )

    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.title

    @property
    def bom_total_usd(self):
        total = Decimal('0')
        for line in self.bom.select_related('part').all():
            if line.part.est_unit_price_usd is None:
                continue
            total += line.part.est_unit_price_usd * line.qty
        return total.quantize(Decimal('0.01'))

    @property
    def bom_has_unpriced(self):
        return self.bom.filter(part__est_unit_price_usd__isnull=True).exists()


class CircuitPart(models.Model):
    """One BOM line on a Circuit."""

    circuit = models.ForeignKey(
        Circuit, on_delete=models.CASCADE, related_name='bom',
    )
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name='circuit_uses',
    )
    designator = models.CharField(
        max_length=32, blank=True,
        help_text="Reference designator, e.g. D1, C2, U1.",
    )
    qty = models.PositiveIntegerField(default=1)
    notes = models.CharField(max_length=200, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'designator', 'id']

    def __str__(self):
        return f"{self.designator or self.part.name} ({self.qty}x)"

    @property
    def line_total_usd(self):
        if self.part.est_unit_price_usd is None:
            return None
        return (self.part.est_unit_price_usd * self.qty).quantize(
            Decimal('0.01'),
        )

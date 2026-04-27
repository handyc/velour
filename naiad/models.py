"""Naiad — design & testing of water purification systems.

A purification system is an ordered sequence of `Stage`s, each
referencing a `StageType` from the catalog. A `StageType` describes
how it attenuates a set of contaminants (particulates, bacteria,
heavy metals, organics…) along with its flow rate, energy draw,
and maintenance cadence. A `TestRun` pushes a `WaterProfile` (the
input water quality) through the chain, multiplying the remaining
concentration by each stage's (1 - removal_fraction) in sequence
and recording the output profile plus a pass/fail against a target
profile.

Phase 1 is intentionally a very simple steady-state model — stages
are treated as ideal attenuators in series, flow bottlenecks aren't
modelled, and no kinetics. The model is accurate enough for
first-pass system design (picking the right mix of pre-filter +
membrane + disinfection for a given source water) and the data
model is open enough that later phases can add CFD, kinetics, or
membrane-fouling simulation without reshaping the schema.
"""

from django.db import models


# Canonical contaminant keys used in WaterProfile.values and in
# StageType.removal JSON. Keeping these as a module constant rather
# than a Django choice list lets later phases add contaminants
# without a migration — just seed new StageType rows with the new
# keys and any profile that doesn't mention them falls through the
# simulation untouched.
CONTAMINANTS = [
    # (key,            label,                               unit)
    ('turbidity',      'Turbidity',                         'NTU'),
    ('tds',            'Total dissolved solids',            'mg/L'),
    ('bacteria',       'Bacteria (coliforms)',              'CFU/100mL'),
    ('viruses',        'Viruses',                           'log10'),
    ('protozoa',       'Protozoa (cysts)',                  'count/L'),
    ('chlorine',       'Free chlorine',                     'mg/L'),
    ('lead',           'Lead',                              'µg/L'),
    ('nitrate',        'Nitrate (as N)',                    'mg/L'),
    ('fluoride',       'Fluoride',                          'mg/L'),
    ('iron',           'Iron',                              'mg/L'),
    ('arsenic',        'Arsenic',                           'µg/L'),
    ('voc',            'Volatile organic compounds',        'µg/L'),
    ('pfas',           'PFAS (total)',                      'ng/L'),
    # Urine-treatment contaminants. Concentrations in fresh human urine
    # range from ~10 g/L (urea) down to ng/L (hormone residues). Keys
    # below track what matters for urine-to-drinkable designs; sources
    # where they don't apply simply omit the key.
    ('urea',           'Urea',                              'mg/L'),
    ('ammonia',        'Ammonia / ammonium (as N)',         'mg/L'),
    ('creatinine',     'Creatinine',                        'mg/L'),
    ('phosphate',      'Phosphate (as P)',                  'mg/L'),
    ('potassium',      'Potassium',                         'mg/L'),
    ('sodium',         'Sodium',                            'mg/L'),
    ('hormones',       'Hormone residues (e.g. estrogens)', 'ng/L'),
    ('pharma',         'Pharmaceutical residues',           'ng/L'),
]
CONTAMINANT_KEYS = [c[0] for c in CONTAMINANTS]
CONTAMINANT_LABELS = {k: label for (k, label, _unit) in CONTAMINANTS}
CONTAMINANT_UNITS = {k: unit for (k, _label, unit) in CONTAMINANTS}


class StageType(models.Model):
    """A catalog entry for a kind of treatment stage — "activated
    carbon block", "UV sterilizer", "reverse osmosis membrane",
    "slow sand filter"… The `removal` JSON maps contaminant keys to
    a fraction in 0..1 of how much of that contaminant this stage
    eliminates per pass. A blank entry means "no effect".

    Flow / energy / cost are nominal and only drive sanity checks in
    Phase 1 — they don't yet constrain system throughput."""

    KIND_CHOICES = [
        ('physical',    'Physical filtration'),
        ('adsorption',  'Adsorption (carbon, resin)'),
        ('membrane',    'Membrane (RO, NF, UF, MF)'),
        ('biological',  'Biological filter'),
        ('uv',          'UV sterilisation'),
        ('ozone',       'Ozone disinfection'),
        ('chemical',    'Chemical dosing'),
        ('ion_exchange','Ion exchange'),
        ('other',       'Other'),
    ]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES,
                            default='other')
    description = models.TextField(blank=True)

    # Fraction of each contaminant removed per pass, 0..1.
    # e.g. {"bacteria": 0.9999, "turbidity": 0.95}
    removal = models.JSONField(default=dict, blank=True)

    # Conversion of removed mass into downstream contaminants, keyed
    # by input contaminant. `{"urea": {"ammonia": 0.467}}` means: per
    # unit of urea this stage removes, add 0.467 units to ammonia.
    # Used by stages that transform rather than destroy — urea
    # hydrolysis (urea → NH₄⁺-N), nitrification (NH₄⁺-N → NO₃⁻-N).
    # Empty/missing = pure removal, no transformation.
    converts = models.JSONField(default=dict, blank=True)

    flow_lpm = models.FloatField(
        default=0.0,
        help_text='Nominal flow rate in litres per minute.')
    energy_watts = models.FloatField(
        default=0.0,
        help_text='Power draw while operating, watts.')
    cost_eur = models.FloatField(
        default=0.0,
        help_text='Replacement / consumable cost per interval, EUR.')
    maintenance_days = models.PositiveIntegerField(
        default=0,
        help_text='Typical replacement or cleaning interval in days. '
                  '0 = maintenance-free in Phase 1 terms.')

    # Physical bounding box for shelf-pack into a 1 m³ cube. Order-of-
    # magnitude — a 5 gal bucket settles at 300×300×300; a folded
    # solar still array at 500×500×300; etc. Used by the GA's volume
    # penalty and by the per-system physical-layout view.
    width_mm  = models.PositiveIntegerField(default=200)
    depth_mm  = models.PositiveIntegerField(default=200)
    height_mm = models.PositiveIntegerField(default=200)

    class Meta:
        ordering = ['kind', 'name']

    def __str__(self):
        return self.name

    @property
    def volume_litres(self) -> float:
        """Bounding-box volume in litres — 1 mm³ = 1 µL = 1e-6 L."""
        return (self.width_mm * self.depth_mm * self.height_mm) / 1e6


class WaterProfile(models.Model):
    """A snapshot of water quality — either a named source preset
    (tap water, well water, greywater) or a target spec (drinking
    water, irrigation, aquaculture). `values` maps contaminant keys
    to absolute concentrations in the unit declared in CONTAMINANTS.
    Missing keys mean "unknown / not measured" — simulation passes
    those through untouched.
    """

    SCOPE_CHOICES = [
        ('source', 'Source water (input)'),
        ('target', 'Target water (desired)'),
    ]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    scope = models.CharField(max_length=8, choices=SCOPE_CHOICES,
                             default='source')
    values = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['scope', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_scope_display()})'


class System(models.Model):
    """A proposed purification system — a named, ordered chain of
    Stage rows. The system references an input profile (the source
    water) and an optional target profile (pass/fail spec)."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    source = models.ForeignKey(
        WaterProfile, on_delete=models.PROTECT,
        related_name='systems_as_source',
        limit_choices_to={'scope': 'source'},
        help_text='Input water this system is being designed for.')
    target = models.ForeignKey(
        WaterProfile, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='systems_as_target',
        limit_choices_to={'scope': 'target'},
        help_text='Optional output spec. TestRun compares against this.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Stage(models.Model):
    """One slot in a System's treatment chain. Order determines the
    simulation sequence — contaminants flow top-to-bottom."""

    system = models.ForeignKey(System, on_delete=models.CASCADE,
                               related_name='stages')
    stage_type = models.ForeignKey(StageType, on_delete=models.PROTECT,
                                   related_name='stage_instances')
    position = models.PositiveIntegerField(
        help_text='0-based index of this stage within the system.')
    label = models.CharField(max_length=120, blank=True,
        help_text='Optional local name; overrides stage_type.name in the UI.')
    notes = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ['system', 'position']
        unique_together = [('system', 'position')]

    def __str__(self):
        return f'{self.system.slug}[{self.position}] {self.label or self.stage_type.name}'


class TestRun(models.Model):
    """A simulation of a System against a chosen input profile.
    Stores the per-stage trace so the UI can render a funnel of
    contaminant attenuation. `passed` is true when the output meets
    the System's target profile (if set)."""

    system = models.ForeignKey(System, on_delete=models.CASCADE,
                               related_name='test_runs')
    source = models.ForeignKey(
        WaterProfile, on_delete=models.PROTECT,
        related_name='test_runs_as_source',
        limit_choices_to={'scope': 'source'})
    target = models.ForeignKey(
        WaterProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='test_runs_as_target',
        limit_choices_to={'scope': 'target'})
    trace = models.JSONField(
        default=list,
        help_text='List of {position, stage, values_after} dicts, one '
                  'entry per stage in order, plus a final "output" entry.')
    output = models.JSONField(default=dict, blank=True)
    passed = models.BooleanField(null=True, blank=True,
        help_text='True if every target-defined contaminant is <= its '
                  'target. NULL when no target profile was set.')
    failures = models.JSONField(
        default=list,
        help_text='List of contaminant keys that exceeded the target.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = ('passed' if self.passed is True else
                  'failed' if self.passed is False else 'no-target')
        return f'{self.system.slug} @ {self.created_at:%Y-%m-%d %H:%M} ({status})'

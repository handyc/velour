"""Radiant — Foundation-style forecasting for LUCDH's server fleet.

Named after Hari Seldon's *Prime Radiant*, the device that displayed the
equations of psychohistory across time. The app answers one concrete
question ("what should we buy in May 2026?") while also staring into
the deep-time horizons where extrapolation is no longer honest.

Shape of the data:
  * Server          — a physical or virtual machine LUCDH runs
  * WorkloadClass   — the *kind* of thing a server hosts (prod Django,
                      WordPress-for-class, experimental-isolated, dev,
                      admin-pipeline). Carries the per-class growth
                      assumptions.
  * HostedProject   — individual projects on a server, keyed to a class.
  * GrowthAssumption — named global knobs (e.g. "logistic saturation for
                      Django projects", "storage growth rate / project / yr").

Projections are computed on the fly in the view — see
`radiant.forecast` — not persisted. The model layer is just the
editable state.
"""

from django.db import models
from django.utils.text import slugify


HORIZON_YEARS = [0, 1, 2, 3, 4, 5, 10, 20, 50, 100, 200, 500, 1000, 5000, 10000]

# Regime labels keyed to horizon depth. Linear math is reliable for a
# decade at most; logistic saturation buys another century; beyond that,
# the output becomes narrative, because the hardware, the institution,
# and arguably the discipline itself are all unstable on those scales.
def regime_for(years):
    if years <= 10:
        return 'linear'
    if years <= 100:
        return 'logistic'
    return 'speculative'


class Server(models.Model):
    """A machine LUCDH currently runs or plans to acquire."""

    ROLE_CHOICES = [
        ('main',         'Main — mixed production'),
        ('wordpress',    'WordPress — classroom'),
        ('experimental', 'Experimental — isolated'),
        ('development',  'Development'),
        ('admin',        'Admin / pipeline'),
        ('planned',      'Planned purchase'),
    ]
    STATUS_CHOICES = [
        ('active',        'Active'),
        ('planned',       'Planned'),
        ('decommissioned','Decommissioned'),
    ]

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES,
                            default='main')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='active')
    ram_gb = models.PositiveIntegerField(default=16)
    storage_gb = models.PositiveIntegerField(default=200)
    cpu_cores = models.PositiveIntegerField(default=4)
    ram_used_gb = models.FloatField(default=0,
        help_text='Snapshot of current RAM usage in GB.')
    storage_used_gb = models.FloatField(default=0,
        help_text='Snapshot of current storage usage in GB.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['role', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:120] or 'server'
            candidate = base
            n = 2
            while Server.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class WorkloadClass(models.Model):
    """A category of project with its own resource + growth profile.

    Each project the university runs gets assigned to one of these. The
    class carries the knobs the forecast uses: how much RAM a typical
    project in this class eats, how many new projects arrive per year,
    and (optionally) an asymptotic ceiling used by the logistic regime.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    typical_ram_mb = models.PositiveIntegerField(default=100,
        help_text='RAM footprint of a typical project in this class, in MB.')
    typical_storage_mb = models.PositiveIntegerField(default=500,
        help_text='Storage footprint of a typical project, in MB.')
    peak_concurrency = models.PositiveIntegerField(default=1,
        help_text='Peak concurrent users per project when that project '
                  'is actually in session.')
    active_fraction = models.FloatField(default=0.3,
        help_text='Fraction of projects in this class that are at peak '
                  'simultaneously. WordPress classroom is typically 0.1-'
                  '0.2 (only a few classes in session at once); quiet '
                  'Django production is ~0.2-0.4.')
    new_per_year = models.FloatField(default=0,
        help_text='Rate of new projects per year in this class.')
    saturation_count = models.PositiveIntegerField(default=0,
        help_text='Asymptotic ceiling used by the logistic regime. '
                  '0 = unbounded growth (not realistic; only for early sanity).')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Workload classes'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:120] or 'class'
            candidate = base
            n = 2
            while WorkloadClass.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def current_count(self):
        return self.hosted_projects.count()


class HostedProject(models.Model):
    """One project running on one server. Hung off a WorkloadClass."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    server = models.ForeignKey(Server, on_delete=models.CASCADE,
                               related_name='projects')
    workload_class = models.ForeignKey(WorkloadClass,
                                       on_delete=models.PROTECT,
                                       related_name='hosted_projects')
    framework = models.CharField(max_length=60, blank=True,
        help_text='django, wordpress, custom, etc.')
    ram_mb = models.PositiveIntegerField(default=0,
        help_text='Measured RAM; 0 = use class default.')
    storage_mb = models.PositiveIntegerField(default=0,
        help_text='Measured storage; 0 = use class default.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['server', 'name']

    def __str__(self):
        return f'{self.name} @ {self.server.name}'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'project'
            candidate = base
            n = 2
            while HostedProject.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class GrowthAssumption(models.Model):
    """A named global knob the forecast reads.

    Kept as key/value rows so the operator can tweak the model from the
    admin without a migration. Values are stored as text — the view
    casts them to float/int when needed.
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=200)
    unit = models.CharField(max_length=60, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f'{self.key} = {self.value} {self.unit}'

    @classmethod
    def get_float(cls, key, default=0.0):
        row = cls.objects.filter(key=key).first()
        if not row:
            return default
        try:
            return float(row.value)
        except (TypeError, ValueError):
            return default


class Candidate(models.Model):
    """A piece of hardware under consideration for purchase.

    Think of these as rows in a quote sheet: a name, the spec sheet,
    an approximate price, and a purpose tag so scenarios know which
    workload the box would carry.
    """

    PURPOSE_CHOICES = [
        ('unified',     'Unified — everything'),
        ('django',      'Django production'),
        ('wordpress',   'WordPress classroom'),
        ('experimental','Experimental / isolated'),
        ('development', 'Development'),
        ('admin',       'Admin / pipeline'),
    ]

    name = models.CharField(max_length=140, unique=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES,
                               default='unified')
    ram_gb = models.PositiveIntegerField(default=32)
    storage_gb = models.PositiveIntegerField(default=500)
    cpu_cores = models.PositiveIntegerField(default=8)
    approximate_cost_eur = models.PositiveIntegerField(default=0,
        help_text='One-time upfront cost in euros (purchase or setup). '
                  '0 = none / rental.')
    monthly_cost_eur = models.PositiveIntegerField(default=0,
        help_text='Monthly rental cost in euros for hosted options. '
                  '0 = owned hardware.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def five_year_tco_eur(self):
        return self.approximate_cost_eur + self.monthly_cost_eur * 60

    class Meta:
        ordering = ['purpose', 'ram_gb']

    def __str__(self):
        return f'{self.name} ({self.ram_gb} GB / {self.storage_gb} GB)'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:140] or 'candidate'
            candidate = base
            n = 2
            while Candidate.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class Scenario(models.Model):
    """A named bundle of Candidates — a hypothetical purchase.

    The scenario is evaluated against the forecast to report how many
    years of headroom it buys before RAM, storage, or cores run out.
    """

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    candidates = models.ManyToManyField(Candidate, related_name='scenarios',
                                        blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'scenario'
            candidate = base
            n = 2
            while Scenario.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def total_ram_gb(self):
        return sum(c.ram_gb for c in self.candidates.all())

    @property
    def total_storage_gb(self):
        return sum(c.storage_gb for c in self.candidates.all())

    @property
    def total_cpu_cores(self):
        return sum(c.cpu_cores for c in self.candidates.all())

    @property
    def total_upfront_eur(self):
        return sum(c.approximate_cost_eur for c in self.candidates.all())

    @property
    def total_monthly_eur(self):
        return sum(c.monthly_cost_eur for c in self.candidates.all())

    @property
    def total_cost_eur(self):
        """5-year TCO: upfront + 60 months of rental."""
        return self.total_upfront_eur + self.total_monthly_eur * 60


class EvoPopulation(models.Model):
    """A genetic-algorithm population of hypothetical purchase bundles.

    Each *individual* is a bundle of Candidate IDs (a multiset — duplicates
    allowed, e.g. two Dedicated Pro 64GB). Fitness combines 5-year lifetime
    from :func:`forecast.evaluate_scenario` with TCO, failure-domain
    isolation, and simplicity. The population is persisted so the browser
    or a cron can step generations asynchronously.
    """

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    notes = models.TextField(blank=True)

    population_size = models.PositiveSmallIntegerField(default=32)
    min_boxes = models.PositiveSmallIntegerField(default=1)
    max_boxes = models.PositiveSmallIntegerField(default=5)
    mutation_rate = models.FloatField(default=0.3)
    elitism = models.PositiveSmallIntegerField(default=2)

    # Fitness weights — each knob normalised so 1.0 == "one unit of this
    # matters as much as one lifetime-year".
    weight_lifetime    = models.FloatField(default=1.0)
    weight_tco         = models.FloatField(default=0.5)
    weight_isolation   = models.FloatField(default=2.0)
    weight_simplicity  = models.FloatField(default=0.3)
    weight_headroom    = models.FloatField(default=1.0)

    generation = models.PositiveIntegerField(default=0)
    best_fitness = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-modified_at']
        verbose_name = 'evolved population'
        verbose_name_plural = 'evolved populations'

    def __str__(self):
        return f'{self.name} (gen {self.generation})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'population'
            candidate = base
            n = 2
            while EvoPopulation.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class EvoIndividual(models.Model):
    """One genome in a population. genome_ids is a list of Candidate.pk values."""

    population = models.ForeignKey(EvoPopulation, on_delete=models.CASCADE,
                                   related_name='individuals')
    generation = models.PositiveIntegerField(default=0)
    genome_ids = models.JSONField(default=list,
        help_text='List of Candidate.pk values — the bundle this genome encodes.')
    fitness = models.FloatField(default=0.0)
    breakdown = models.JSONField(default=dict, blank=True,
        help_text='Fitness components: lifetime_years, tco_eur, '
                  'isolation_bonus, simplicity_bonus, headroom_bonus, plus '
                  'totals so the detail page doesn\'t need to re-evaluate.')
    parent_a = models.ForeignKey('self', null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name='offspring_a')
    parent_b = models.ForeignKey('self', null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name='offspring_b')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fitness', 'id']

    def __str__(self):
        return f'Ind#{self.pk} gen{self.generation} fit={self.fitness:.2f}'


class EvoTournament(models.Model):
    """A head-to-head evolution of N populations from varied seeds.

    Running a tournament spins up `rounds` fresh populations, evolves
    each `generations` steps, and records the winner. Compare single-run
    luck against the best of a bracket.
    """

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    notes = models.TextField(blank=True)
    rounds = models.PositiveSmallIntegerField(default=8)
    generations = models.PositiveIntegerField(default=30)
    population_size = models.PositiveSmallIntegerField(default=24)
    mutation_rate = models.FloatField(default=0.3)
    weights_json = models.JSONField(default=dict, blank=True,
        help_text='Snapshot of the weight vector used for scoring.')
    leaderboard = models.JSONField(default=list, blank=True,
        help_text='[{round, fitness, genome_ids, summary}, ...] sorted '
                  'by fitness desc. Top row is the tournament champion.')
    champion_genome_ids = models.JSONField(default=list, blank=True)
    champion_fitness = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} (champ {self.champion_fitness:.2f})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'tournament'
            candidate = base
            n = 2
            while EvoTournament.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class EvoMetaTournament(models.Model):
    """A tournament of tournaments.

    Runs `rounds` tournaments — each with a perturbed weight vector —
    and promotes the best *champion* as the meta-champion. The point is
    to test how stable a winning bundle is across reasonable variation in
    what you care about (more budget vs. more headroom vs. more isolation).
    """

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    notes = models.TextField(blank=True)
    rounds = models.PositiveSmallIntegerField(default=4)
    tournament_rounds = models.PositiveSmallIntegerField(default=6)
    generations = models.PositiveIntegerField(default=25)
    population_size = models.PositiveSmallIntegerField(default=20)
    weight_jitter = models.FloatField(default=0.35,
        help_text='+/- fraction by which each weight is perturbed per round.')
    leaderboard = models.JSONField(default=list, blank=True)
    champion_genome_ids = models.JSONField(default=list, blank=True)
    champion_fitness = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} (meta-champ {self.champion_fitness:.2f})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'meta-tournament'
            candidate = base
            n = 2
            while EvoMetaTournament.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class Snapshot(models.Model):
    """A frozen copy of the forecast + recommendation at a moment in time.

    The whole output is stored as JSON so the operator can re-visit
    what Radiant predicted on a given date even after the assumptions
    have drifted. The Seldon move: record your predictions so you can
    check them later.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    notes = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True,
        help_text='forecast_rows + recommendation + classes + servers '
                  'captured at snapshot time.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.created_at:%Y-%m-%d})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'snapshot'
            candidate = base
            n = 2
            while Snapshot.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

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


HORIZON_YEARS = [0, 1, 5, 10, 20, 50, 100, 200, 500, 1000, 5000, 10000]

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
        help_text='Peak concurrent users per project under load.')
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

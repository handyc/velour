"""Reckoner — project the full cost of a compute task.

Energy is the anchor: every task has an estimated energy cost in
joules, spanning from ~10 picojoules (a single integer add) up to
~10^16 joules (a frontier-scale LLM training run on a global
cluster for a year). Four more dimensions sit alongside:

    environmental  — ecological / biosphere damage
    political      — alignment with or erosion of democratic norms
    economic       — euros and dollars; effect on the wider economy
    social         — benefit or harm to society at large

Each task is matched to the closest `EnergyComparable` — a
real-world signpost (heartbeat, candy bar, car trip, Hiroshima
bomb, etc.) so the number has a shape the reader already knows.

All numbers here are rough order-of-magnitude estimates sourced
from public literature and vendor disclosures. They exist to give
the *shape* of the cost gradient, not to be audited.
"""

import math

from django.db import models

# Unit conversions anchored in the joule.
J_PER_CAL = 4.184          # physics calorie (small c)
J_PER_KCAL = 4184.0        # dietary Calorie (big C)


class EnergyComparable(models.Model):
    """A real-world signpost on the energy number line.

    Ordered roughly from a blink of an eye up to a hurricane, so
    that any compute task can be matched to its nearest neighbour
    in log-space.
    """

    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    icon = models.CharField(
        max_length=12,
        help_text='Unicode glyph or emoji representing this signpost.',
    )
    energy_joules = models.FloatField()
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ['energy_joules']

    def __str__(self):
        return f'{self.icon} {self.name}'


FACTOR_MIN = -5
FACTOR_MAX = 5


class ComputeTask(models.Model):
    """One reckonable computing task.

    Factor scores all use the same signed 0..5 (or -5..+5 for
    social) scale so they can share a bar chart.
    """

    CATEGORY_CHOICES = [
        ('arithmetic', 'Arithmetic'),
        ('scripting', 'Scripting'),
        ('web', 'Web & network'),
        ('db', 'Database'),
        ('media', 'Media'),
        ('llm', 'LLM inference'),
        ('training', 'LLM training'),
        ('industrial', 'Industrial compute'),
    ]

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    category = models.CharField(
        max_length=16, choices=CATEGORY_CHOICES, default='scripting'
    )

    # The joule anchor. Positive float, any magnitude.
    energy_joules = models.FloatField()

    # Economic cost in the two currencies the user cares about.
    # Typical small values; large training runs push into millions.
    cost_eur = models.FloatField(default=0.0)
    cost_usd = models.FloatField(default=0.0)

    # Four-factor ESES scores — see module docstring.
    # Environmental / political / economic use 0..5 severity
    # (0 = benign, 5 = catastrophic).
    # Social is signed: -5 = actively harmful, +5 = net good.
    environmental_score = models.IntegerField(default=0)
    political_score = models.IntegerField(default=0)
    economic_score = models.IntegerField(default=0)
    social_score = models.IntegerField(default=0)

    environmental_note = models.TextField(blank=True)
    political_note = models.TextField(blank=True)
    economic_note = models.TextField(blank=True)
    social_note = models.TextField(blank=True)

    class Meta:
        ordering = ['energy_joules']

    def __str__(self):
        return self.name

    # ── unit conversions ────────────────────────────────────
    @property
    def energy_cal(self):
        """Energy in physics calories (small c)."""
        return self.energy_joules / J_PER_CAL

    @property
    def energy_kcal(self):
        """Energy in dietary Calories (big C, kcal)."""
        return self.energy_joules / J_PER_KCAL

    # ── signpost lookup ─────────────────────────────────────
    def nearest_comparable(self):
        """EnergyComparable closest to this task's energy in log10 space."""
        if self.energy_joules <= 0:
            return None
        target = math.log10(self.energy_joules)
        best = None
        best_dist = None
        for c in EnergyComparable.objects.all():
            if c.energy_joules <= 0:
                continue
            d = abs(math.log10(c.energy_joules) - target)
            if best_dist is None or d < best_dist:
                best = c
                best_dist = d
        return best

    def log_position(self, lo=-12.0, hi=17.0):
        """Position on a [lo..hi] log10 axis as a 0..1 fraction.

        Used to place the task as a bar on the index strip.
        """
        if self.energy_joules <= 0:
            return 0.0
        x = (math.log10(self.energy_joules) - lo) / (hi - lo)
        return max(0.0, min(1.0, x))


class AppProfile(models.Model):
    """A Velour app reckoning with its own compute cost.

    Each profile enumerates a typical-day mix of ComputeTasks via
    AppTaskUsage rows. The aggregate energy is just the sum of
    (task.energy_joules × usage.count_per_day) over the mix, so
    Reckoner can answer "how much does Velour itself cost?".
    """

    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240)
    order = models.PositiveIntegerField(default=100)

    tasks = models.ManyToManyField(
        ComputeTask, through='AppTaskUsage', related_name='app_profiles',
    )

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def total_energy_joules(self):
        total = 0.0
        for u in self.usages.all():
            total += u.task.energy_joules * u.count_per_day
        return total

    def nearest_comparable(self):
        total = self.total_energy_joules()
        if total <= 0:
            return None
        target = math.log10(total)
        best = None
        best_dist = None
        for c in EnergyComparable.objects.all():
            if c.energy_joules <= 0:
                continue
            d = abs(math.log10(c.energy_joules) - target)
            if best_dist is None or d < best_dist:
                best = c
                best_dist = d
        return best

    def log_position(self, lo=0.0, hi=6.0):
        """Same idea as ComputeTask.log_position but over a narrower
        window — per-day app energies span roughly 10^0..10^6 J."""
        total = self.total_energy_joules()
        if total <= 0:
            return 0.0
        x = (math.log10(total) - lo) / (hi - lo)
        return max(0.0, min(1.0, x))


class AppTaskUsage(models.Model):
    """How many of a given ComputeTask an AppProfile does per day."""

    app = models.ForeignKey(
        AppProfile, related_name='usages', on_delete=models.CASCADE,
    )
    task = models.ForeignKey(ComputeTask, on_delete=models.CASCADE)
    count_per_day = models.FloatField(default=1.0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-count_per_day']
        unique_together = [('app', 'task')]

    def contribution_joules(self):
        return self.task.energy_joules * self.count_per_day

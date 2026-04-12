from django.db import models
from django.utils.text import slugify


class HPCCluster(models.Model):
    """A high-performance computing cluster the operator has SSH
    access to. Phase 1 is a registry only — stores the cluster's
    identity, scheduler type, and notes. Phase 2 will add actual
    remote access (SSH job submission, queue polling, file transfer)
    and will likely grow a Job and JobHistory model alongside this.

    The backlog note (project_hpc_app_backlog) has the full planning
    sketch for what HPC access should eventually look like. For now,
    this app exists so the operator has a place to *catalog* which
    clusters they work with — like a lab notebook for remote compute.
    """

    SCHEDULER_CHOICES = [
        ('slurm',     'SLURM'),
        ('pbs',       'PBS / Torque'),
        ('sge',       'SGE / UGE'),
        ('lsf',       'LSF'),
        ('kubernetes','Kubernetes'),
        ('ray',       'Ray'),
        ('none',      'No scheduler (interactive only)'),
        ('other',     'Other / unknown'),
    ]

    nickname = models.CharField(
        max_length=100,
        help_text='Human-friendly name for this cluster, e.g. '
                  '"Leiden Alice" or "SURFsara Snellius".',
    )
    slug = models.SlugField(
        max_length=120, unique=True, blank=True,
        help_text='URL-safe unique identifier. Auto-derived from '
                  'nickname if blank.',
    )

    hostname = models.CharField(
        max_length=253,
        help_text='Hostname used for SSH, e.g. "alice.leidenuniv.nl" '
                  'or "snellius.surf.nl".',
    )
    ssh_user = models.CharField(
        max_length=64, blank=True,
        help_text='Username to connect as. Leave blank if it varies '
                  'per-login or if you use a stanza in ~/.ssh/config.',
    )
    ssh_port = models.PositiveIntegerField(default=22)

    scheduler = models.CharField(
        max_length=16, choices=SCHEDULER_CHOICES, default='slurm',
    )
    institution = models.CharField(
        max_length=200, blank=True,
        help_text='Organization that owns this cluster, e.g. '
                  '"Leiden University" or "SURF".',
    )
    grant_code = models.CharField(
        max_length=100, blank=True,
        help_text='Optional funding account / allocation code for '
                  'job accounting, e.g. "NWO-EW.2026.1234".',
    )

    description = models.TextField(
        blank=True,
        help_text='What kinds of jobs you run here. Free-form. '
                  'Shows on the cluster detail page.',
    )
    notes = models.TextField(
        blank=True,
        help_text='Operator notes — quirks of this cluster, login '
                  'steps, specific module loads, lessons learned.',
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_touched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nickname']

    def __str__(self):
        return self.nickname

    def save(self, *args, **kwargs):
        if not self.slug and self.nickname:
            base = slugify(self.nickname)[:100] or 'cluster'
            candidate = base
            n = 2
            while HPCCluster.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def ssh_command(self):
        """Render a canonical `ssh user@host` command line. For
        display only — copy/paste into the operator's terminal."""
        user = f'{self.ssh_user}@' if self.ssh_user else ''
        port = f' -p {self.ssh_port}' if self.ssh_port != 22 else ''
        return f'ssh {user}{self.hostname}{port}'

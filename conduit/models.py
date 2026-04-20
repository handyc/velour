"""Conduit — route work to the right execution backend.

A `Job` describes a unit of work. A `JobTarget` is a registered
backend (local shell, VPS SSH, Slurm auto-submit, Slurm manual-submit,
Pi, ESP, ATtiny, code agent, generic HTTP). The routing function in
`conduit.routing` picks the best `JobTarget` for a `Job`. Executors
in `conduit.executors` dispatch the `Job` on its target.

Phase 1 ships two real executors — local shell and Slurm-manual. The
manual path is load-bearing: Leiden's ALICE HPC cluster prohibits
automated `sbatch` submission, so ALICE-bound jobs land in a
`JobHandoff` row and wait for a human operator to submit them,
then paste the Slurm job ID and outcome back in. Other target kinds
are stubbed until the corresponding hardware / agent is actually
wired up.

Security note: the local executor runs shell commands as the Velour
web process uid. It is intentionally NOT a sandbox. `login_required`
+ single-trusted-user Velour installs are the operating assumption;
any future multi-tenant use would need proper isolation.
"""

from django.contrib.auth import get_user_model
from django.db import models


User = get_user_model()


class JobTarget(models.Model):
    """A registered execution backend."""

    KIND_CHOICES = [
        ('local',         'Local shell'),
        ('vps',           'VPS (SSH)'),
        ('slurm',         'HPC (Slurm auto-submit)'),
        ('slurm_manual',  'HPC (Slurm manual submit)'),
        ('pi',            'Raspberry Pi'),
        ('esp',           'ESP node'),
        ('attiny',        'ATtiny firmware'),
        ('agent',         'Code agent'),
        ('http',          'Generic HTTP'),
    ]

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    host = models.CharField(
        max_length=200, blank=True,
        help_text='SSH hostname, API base URL, mDNS name, or '
                  'identifier — kind-specific.')
    config = models.JSONField(
        default=dict, blank=True,
        help_text='Kind-specific config: {ssh_user, ssh_port, '
                  'partition, account, base_url, ...}')
    enabled = models.BooleanField(default=True)
    priority = models.IntegerField(
        default=0,
        help_text='Higher priority wins when routing picks between '
                  'eligible targets of the same kind.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['kind', '-priority', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_kind_display()})'


class Job(models.Model):
    """A unit of work routed through Conduit."""

    KIND_CHOICES = [
        ('shell',          'Shell command'),
        ('slurm_script',   'Slurm sbatch script'),
        ('http',           'HTTP request'),
        ('agent_task',     'Agent task'),
        ('sensor_read',    'Sensor read'),
        ('firmware_flash', 'Firmware flash'),
    ]

    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('routing',    'Routing'),
        ('dispatched', 'Dispatched'),
        ('running',    'Running'),
        ('handoff',    'Waiting for human submit'),
        ('done',       'Done'),
        ('failed',     'Failed'),
        ('cancelled',  'Cancelled'),
    ]

    slug = models.SlugField(unique=True, max_length=200)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES,
                            default='shell')
    payload = models.JSONField(
        default=dict,
        help_text='Kind-specific: '
                  'shell={command, cwd?, env?, timeout?}; '
                  'slurm_script={script, cluster_hint?}; '
                  'http={method, url, body?, headers?}.')
    requester = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conduit_jobs')
    requested_target = models.ForeignKey(
        JobTarget, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='requested_jobs',
        help_text='If set and eligible, the router picks this target '
                  'over anything else.')
    target = models.ForeignKey(
        JobTarget, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='dispatched_jobs',
        help_text='Filled in by route(). The target that actually ran it.')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default='pending')
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    result = models.JSONField(default=dict, blank=True,
        help_text='Executor-specific extra return data (HTTP body, '
                  'sensor reading, etc.).')
    exit_code = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} [{self.get_status_display()}]'

    @property
    def duration_seconds(self):
        if not self.dispatched_at or not self.finished_at:
            return None
        return (self.finished_at - self.dispatched_at).total_seconds()


class JobHandoff(models.Model):
    """Human-submit queue row. Created when a manual-submit executor
    (Slurm-manual today; other "I can't dispatch this automatically"
    kinds later) needs an operator to execute the step physically."""

    STATUS_CHOICES = [
        ('pending',      'Waiting for submission'),
        ('submitted',    'Submitted externally'),
        ('acknowledged', 'Acknowledged / outcome recorded'),
        ('cancelled',    'Cancelled'),
    ]

    job = models.OneToOneField(
        Job, on_delete=models.CASCADE, related_name='handoff')
    script_text = models.TextField(
        help_text='The rendered script (e.g. sbatch file) ready to '
                  'copy to the cluster and submit.')
    submit_instructions = models.TextField(
        help_text='Copy-pasteable shell commands for the operator.')
    status = models.CharField(max_length=14, choices=STATUS_CHOICES,
                              default='pending')
    external_id = models.CharField(
        max_length=120, blank=True,
        help_text='External queue ID (e.g. Slurm job number).')
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='submitted_handoffs')
    submitted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['status', '-job__created_at']

    def __str__(self):
        return f'handoff({self.job.name})'

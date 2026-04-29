from django.db import models


class RemoteHost(models.Model):
    """A registered velour instance this node polls for health data.

    The token is stored in the DB rather than on disk because it belongs to
    the *remote* host, not this one; each polling node can be pointed at many
    remotes, each with its own token. It's essentially a shared secret the
    remote host gave us out-of-band (copy-paste from `manage.py init_health_token`).
    """

    name = models.CharField(
        max_length=100,
        help_text='Human label, e.g. "production" or "raspberry pi".',
    )
    url = models.CharField(
        max_length=500,
        help_text='Base URL of the remote velour, e.g. https://myapp.example.com',
    )
    token = models.CharField(
        max_length=200,
        help_text='Bearer token the remote gave you (contents of its health_token.txt).',
    )
    enabled = models.BooleanField(
        default=True,
        help_text='Uncheck to skip this host in "Refresh all" polls.',
    )

    # Populated on each poll.
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(
        max_length=16, blank=True,
        help_text='Last classified traffic-light status: green/yellow/red/unreachable.',
    )
    last_snapshot = models.JSONField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def health_url(self):
        """Canonical URL for the health JSON endpoint on this remote."""
        return self.url.rstrip('/') + '/sysinfo/health.json'

    @property
    def status_reasons(self):
        """Best-effort extraction of why the last poll classified as it did.
        Reads from the snapshot if present, otherwise from last_error."""
        if self.last_status in ('', 'unreachable'):
            return [self.last_error] if self.last_error else []
        if isinstance(self.last_snapshot, dict):
            return self.last_snapshot.get('status_reasons', []) or []
        return []


class HostPoll(models.Model):
    """One row per poll — the history that the live last_* fields on
    RemoteHost overwrite. Denormalised cpu/mem/disk columns so charts
    don't have to dig into the JSON snapshot. Auto-pruned to the
    most recent N polls per host (see polling._record_poll)."""

    host = models.ForeignKey(
        RemoteHost, on_delete=models.CASCADE, related_name='polls',
    )
    at       = models.DateTimeField(auto_now_add=True, db_index=True)
    status   = models.CharField(max_length=16)
    cpu_load = models.FloatField(null=True, blank=True)
    mem_pct  = models.FloatField(null=True, blank=True)
    disk_pct = models.FloatField(null=True, blank=True)
    error    = models.TextField(blank=True)
    snapshot = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-at']
        indexes = [models.Index(fields=['host', '-at'])]

    def __str__(self):
        return f'{self.host.name} @ {self.at:%Y-%m-%d %H:%M} ({self.status})'

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
        help_text='Human label, e.g. "lucdh.nl prod" or "raspberry pi".',
    )
    url = models.CharField(
        max_length=500,
        help_text='Base URL of the remote velour, e.g. https://swibliq.lucdh.nl',
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

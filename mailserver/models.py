"""Internal mail server models.

LocalDelivery stores every email the internal aiosmtpd server
receives. Unlike mailroom's InboundMessage (which requires an
IMAP MailAccount FK), LocalDelivery is self-contained — no
external mail provider needed. The SMTP server accepts mail on
localhost:2525 (configurable) and writes directly to this table.

This gives Velour a closed loop for mail testing: the mailboxes
app's DynamicMailboxBackend can be pointed at localhost:2525
via Django's EMAIL_HOST / EMAIL_PORT settings, and any mail
Velour sends (password resets, notifications, codex reports)
lands here instead of going to an external relay. The operator
sees the result in /mailserver/ without needing a real email
account.
"""

from django.db import models


class LocalDelivery(models.Model):
    """One email received by the internal SMTP server."""

    from_addr = models.CharField(max_length=500, db_index=True)
    to_addrs = models.JSONField(default=list,
        help_text='List of recipient addresses (RCPT TO values).')
    subject = models.CharField(max_length=500, blank=True)
    body_text = models.TextField(blank=True,
        help_text='Plain-text body (text/plain part or decoded fallback).')
    body_html = models.TextField(blank=True,
        help_text='HTML body (text/html part) if present.')

    raw = models.TextField(blank=True,
        help_text='Full RFC822 source. Stored for reprocessing.')

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    peer_ip = models.GenericIPAddressField(null=True, blank=True,
        help_text='IP address of the sending client.')

    read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-received_at']
        verbose_name_plural = 'local deliveries'
        indexes = [
            models.Index(fields=['-received_at']),
            models.Index(fields=['read', '-received_at']),
        ]

    def __str__(self):
        return f'{self.from_addr} → {", ".join(self.to_addrs)}: {self.subject[:60]}'

    @property
    def best_body(self):
        if self.body_text:
            return self.body_text
        if self.body_html:
            import re
            return re.sub(r'<[^>]+>', '', self.body_html)
        return ''

    @property
    def recipient_display(self):
        return ', '.join(self.to_addrs) if self.to_addrs else '(none)'


class SMTPServerConfig(models.Model):
    """Singleton configuration for the internal SMTP server.
    Stored in the database so the operator can change the port
    or hostname from the admin without editing settings.py."""

    host = models.CharField(max_length=253, default='127.0.0.1',
        help_text='Address the SMTP server binds to. 127.0.0.1 for '
                  'local-only; 0.0.0.0 to accept from LAN (including '
                  'ESP nodes with mail capability).')
    port = models.IntegerField(default=2525,
        help_text='Port the SMTP server listens on. 2525 is the '
                  'conventional non-privileged testing port.')
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SMTP server config'
        verbose_name_plural = 'SMTP server config'

    def __str__(self):
        state = 'enabled' if self.is_enabled else 'disabled'
        return f'SMTP {self.host}:{self.port} ({state})'

    @classmethod
    def get_self(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

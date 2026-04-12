from django.db import models
from django.db.models import Q


class MailAccount(models.Model):
    """A configured outgoing (and optionally incoming) mail account.

    Velour can hold many of these — e.g. a snel SMTP relay for system notices,
    a Gmail app-password account for development, a Postmark account for
    transactional mail. One is marked `is_default=True` and used by Django's
    built-in mail facilities (including password reset). Any Django app can
    route explicitly through a specific account by name via the helper
    mail.sending.send_mail(..., mailbox='<name>'), and external apps
    (legacy PHP, curl, shell scripts) can POST to /mail/accounts/relay/ with a
    token and a JSON payload naming the mailbox.

    Credentials are stored plaintext in the DB — the same security model as
    secret_key.txt and health_token.txt. If you need encrypted-at-rest, that
    is a cross-cutting change and should happen to all secret storage at once.
    """

    name = models.CharField(
        max_length=100, unique=True,
        help_text='Human label used for routing, e.g. "snel-relay" or "gmail-dev".',
    )
    enabled = models.BooleanField(
        default=True,
        help_text='Disabled accounts are hidden from the default selection '
                  'and cannot be targeted by routing.',
    )
    is_default = models.BooleanField(
        default=False,
        help_text='Exactly one account may be the default. Marking this one '
                  'as default automatically unmarks any other.',
    )

    # --- outgoing ---------------------------------------------------
    smtp_host = models.CharField(max_length=255)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password = models.CharField(max_length=500, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_use_ssl = models.BooleanField(default=False)

    from_email = models.EmailField(
        help_text='Address that will appear in the From: header of outgoing '
                  'mail. Usually matches smtp_username.',
    )
    from_name = models.CharField(
        max_length=100, blank=True,
        help_text='Optional display name shown alongside from_email.',
    )

    # --- incoming (deferred for this iteration but recorded up-front) --
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.PositiveIntegerField(default=993)
    imap_username = models.CharField(max_length=255, blank=True)
    imap_password = models.CharField(max_length=500, blank=True)
    imap_use_ssl = models.BooleanField(default=True)

    notes = models.TextField(blank=True)

    # --- health / last test ----------------------------------------
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_status = models.CharField(max_length=16, blank=True)  # ok / error
    last_test_error = models.TextField(blank=True)

    class Meta:
        ordering = ['-is_default', 'name']

    def __str__(self):
        tag = ' (default)' if self.is_default else ''
        return f'{self.name}{tag}'

    def save(self, *args, **kwargs):
        """Enforce single-default invariant: marking this account as default
        atomically unmarks any other default. Done in save() so admin edits,
        form POSTs, and shell assignments all behave the same way."""
        super().save(*args, **kwargs)
        if self.is_default:
            MailAccount.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)

    def formatted_from(self):
        """Return the RFC 5322 `Name <email>` form if from_name is set,
        otherwise just the bare email address."""
        if self.from_name:
            return f'{self.from_name} <{self.from_email}>'
        return self.from_email

    @classmethod
    def get_default(cls):
        """Return the default enabled MailAccount, or None if none is set.

        Callers that need to send mail should generally not call this directly
        — use mail.sending.send_mail, which handles fallbacks. This is
        here for the custom Django email backend, which runs at connection
        construction time and needs a best-effort answer."""
        return cls.objects.filter(is_default=True, enabled=True).first()

    @classmethod
    def get_by_name(cls, name):
        """Look up an enabled account by name, or return None."""
        if not name:
            return None
        return cls.objects.filter(name=name, enabled=True).first()


class InboundMessage(models.Model):
    """One email fetched from a MailAccount's IMAP inbox.

    The raw RFC822 source is stored verbatim so nothing is lost — if the
    parser misses a header or an attachment handler lands in a later release,
    old messages can be re-processed without re-fetching. The polling logic
    uses the (mailbox, uid) unique constraint to skip messages it has
    already seen, so polls are idempotent.

    handled/read are independent: "read" is the human-in-the-loop viewing
    flag (like any webmail), while "handled" is the machine-in-the-loop
    processing flag used by future handler registries (e.g. "this submission
    mail has been parsed and its attachment saved to the filesystem").
    """

    mailbox = models.ForeignKey(
        MailAccount,
        on_delete=models.CASCADE,
        related_name='inbound_messages',
    )
    uid = models.CharField(
        max_length=64,
        help_text='IMAP UID for this message within the mailbox. Used for '
                  'dedup across polls.',
    )

    # Parsed headers
    from_addr = models.CharField(max_length=500, blank=True)
    to_addr = models.CharField(max_length=1000, blank=True)
    subject = models.CharField(max_length=500, blank=True)

    # Bodies — both captured if available; either may be empty
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    attachment_names = models.JSONField(default=list, blank=True)

    # Timestamps: received_at is the Date: header if parseable, fetched_at
    # is when velour pulled it off the server.
    received_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    # Full RFC822 source for reprocessing / debugging. Indexed by PK only.
    raw = models.TextField(blank=True)

    # User/handler flags — orthogonal: "read" = human saw it, "handled" =
    # a handler module processed it and extracted whatever it needed.
    read = models.BooleanField(default=False)
    handled = models.BooleanField(default=False)
    handler_notes = models.TextField(blank=True)

    class Meta:
        unique_together = [('mailbox', 'uid')]
        ordering = ['-received_at', '-fetched_at']
        indexes = [
            models.Index(fields=['mailbox', 'read']),
            models.Index(fields=['-fetched_at']),
        ]

    def __str__(self):
        return f'{self.from_addr}: {self.subject[:60]}'

    @property
    def best_body(self):
        """Prefer plain text for display; fall back to HTML stripped of tags."""
        if self.body_text:
            return self.body_text
        if self.body_html:
            import re
            return re.sub(r'<[^>]+>', '', self.body_html)
        return ''


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
        return f'{self.from_addr} \u2192 {", ".join(self.to_addrs)}: {self.subject[:60]}'

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

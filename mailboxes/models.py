from django.db import models
from django.db.models import Q


class MailAccount(models.Model):
    """A configured outgoing (and optionally incoming) mail account.

    Velour can hold many of these — e.g. a snel SMTP relay for system notices,
    a Gmail app-password account for development, a Postmark account for
    transactional mail. One is marked `is_default=True` and used by Django's
    built-in mail facilities (including password reset). Any Django app can
    route explicitly through a specific account by name via the helper
    mailboxes.sending.send_mail(..., mailbox='<name>'), and external apps
    (legacy PHP, curl, shell scripts) can POST to /mailboxes/relay/ with a
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
        — use mailboxes.sending.send_mail, which handles fallbacks. This is
        here for the custom Django email backend, which runs at connection
        construction time and needs a best-effort answer."""
        return cls.objects.filter(is_default=True, enabled=True).first()

    @classmethod
    def get_by_name(cls, name):
        """Look up an enabled account by name, or return None."""
        if not name:
            return None
        return cls.objects.filter(name=name, enabled=True).first()

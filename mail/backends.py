"""Django email backend that routes through the MailAccount table.

Wiring this in via `EMAIL_BACKEND = 'mail.backends.DynamicMailboxBackend'`
lets Django's built-in mail facilities (password reset views, admin error
emails, `django.core.mail.send_mail`) use whatever the user has configured
as the default MailAccount — without a settings.py edit when they swap
providers, and without any custom glue code per use-case.

If no default MailAccount exists (e.g. on a fresh install), the backend
falls through to the console backend so local dev and first-run stay
functional and loud rather than silently swallowing mail.
"""

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend


class DynamicMailboxBackend(BaseEmailBackend):
    """Dispatcher: at construction time, look up the default MailAccount and
    build an inner backend configured with that account's credentials. If
    nothing is configured, use the console backend so outgoing mail goes to
    stdout instead of blowing up.

    Each send_messages() call rewrites messages whose from_email is the
    Django DEFAULT_FROM_EMAIL placeholder so they reflect the account's
    actual sender identity — this is how we keep settings.py static while
    still having the From: header come from the DB.
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self._account = self._load_account()
        if self._account:
            self._inner = SMTPBackend(
                host=self._account.smtp_host,
                port=self._account.smtp_port,
                username=self._account.smtp_username,
                password=self._account.smtp_password,
                use_tls=self._account.smtp_use_tls,
                use_ssl=self._account.smtp_use_ssl,
                fail_silently=fail_silently,
            )
        else:
            self._inner = ConsoleBackend(fail_silently=fail_silently)

    def _load_account(self):
        """Best-effort lookup. The DB may not be ready (migrations pending)
        during initial project setup, so we swallow exceptions and fall
        through to the console backend."""
        try:
            from .models import MailAccount
            return MailAccount.get_default()
        except Exception:
            return None

    def open(self):
        return self._inner.open()

    def close(self):
        return self._inner.close()

    def send_messages(self, email_messages):
        if self._account:
            account_from = self._account.formatted_from()
            default_from = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            for msg in email_messages:
                if not msg.from_email or msg.from_email == default_from:
                    msg.from_email = account_from
        return self._inner.send_messages(email_messages)

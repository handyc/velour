"""Public API for sending mail from arbitrary Django apps.

    from mail.sending import send_mail

    # Defaults: uses the account marked is_default, sends to Identity.admin_email
    send_mail('System notice', 'Disk is filling up.')

    # Explicit recipient
    send_mail('Welcome!', 'Hi there.', to='alice@example.com')

    # Route through a specific account by name
    send_mail('Invoice', 'See attached.', to='customer@x.com', mailbox='billing')

    # HTML alternative
    send_mail('Alert', 'plain text', html='<b>HTML version</b>', to='ops@x.com')

The helper is intentionally stdlib-only beyond Django itself — no requests,
no third-party SDKs. If you want the Django global email plumbing (password
reset, etc.) to use your default MailAccount without calling this helper,
make sure EMAIL_BACKEND = 'mail.backends.DynamicMailboxBackend' in
settings.py (that wiring already exists).
"""

from django.core.mail import EmailMultiAlternatives, get_connection

from .models import MailAccount


class NoMailboxConfigured(Exception):
    """Raised when send_mail is asked to send but no MailAccount exists."""


def _resolve_account(mailbox):
    if mailbox:
        account = MailAccount.get_by_name(mailbox)
        if account is None:
            raise NoMailboxConfigured(
                f'No enabled MailAccount named "{mailbox}". '
                f'Create one at /mail/accounts/ or pass a different name.'
            )
        return account
    account = MailAccount.get_default()
    if account is None:
        raise NoMailboxConfigured(
            'No default MailAccount configured. Create one at /mail/accounts/ '
            'and mark it as default.'
        )
    return account


def _resolve_recipients(to):
    if to is None:
        try:
            from identity.models import Identity
            admin = Identity.get_self().admin_email
        except Exception:
            admin = ''
        if not admin:
            raise ValueError(
                '`to` argument is required: no Identity.admin_email set as fallback.'
            )
        return [admin]
    if isinstance(to, str):
        return [to]
    return list(to)


def _build_connection(account):
    """Construct a fresh SMTP connection scoped to this account."""
    return get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=account.smtp_host,
        port=account.smtp_port,
        username=account.smtp_username,
        password=account.smtp_password,
        use_tls=account.smtp_use_tls,
        use_ssl=account.smtp_use_ssl,
    )


def send_mail(subject, body, to=None, html=None, from_email=None,
              reply_to=None, mailbox=None, fail_silently=False):
    """Send one message through a configured MailAccount.

    Returns the number of successfully delivered messages (0 or 1).
    """
    account = _resolve_account(mailbox)
    recipients = _resolve_recipients(to)
    sender = from_email or account.formatted_from()

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=sender,
        to=recipients,
        reply_to=[reply_to] if reply_to else None,
        connection=_build_connection(account),
    )
    if html:
        msg.attach_alternative(html, 'text/html')

    return msg.send(fail_silently=fail_silently)

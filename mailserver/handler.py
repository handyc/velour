"""aiosmtpd handler that writes received emails to LocalDelivery rows.

This is the bridge between the SMTP wire protocol and the Django
ORM. When a client connects to the internal SMTP server and sends
a message, aiosmtpd calls handle_DATA with the envelope (sender,
recipients, raw data). This handler parses the message, extracts
headers and bodies, and writes a LocalDelivery row.

The handler is intentionally simple — no spam filtering, no relay,
no authentication. It accepts everything and stores it. The
internal SMTP server is for TESTING, not for production mail
delivery. It's the equivalent of mailhog or mailtrap but built
into Velour so the operator doesn't need an external tool.
"""

import email
import email.policy
import logging

from aiosmtpd.handlers import AsyncMessage

logger = logging.getLogger(__name__)


class VelourSMTPHandler:
    """aiosmtpd handler that writes to Django's LocalDelivery model.

    aiosmtpd expects a handler object with an async handle_DATA
    method. We use Django's ORM synchronously inside the async
    handler via sync_to_async — aiosmtpd runs in an asyncio loop
    but the Django ORM is sync-only.
    """

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        """Accept all recipients unconditionally."""
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session, envelope):
        """Parse the incoming message and store it."""
        try:
            from asgiref.sync import sync_to_async
            await sync_to_async(self._store)(
                envelope.mail_from,
                list(envelope.rcpt_tos),
                envelope.content,
                session.peer[0] if session.peer else None,
            )
            return '250 Message accepted for delivery'
        except Exception as e:
            logger.exception('Failed to store incoming message')
            return f'451 Temporary failure: {e}'

    def _store(self, mail_from, rcpt_tos, data, peer_ip):
        """Synchronous Django ORM write. Called from handle_DATA
        via sync_to_async."""
        import django
        django.setup()
        from .models import LocalDelivery

        # Parse the raw RFC822 data
        if isinstance(data, bytes):
            raw_str = data.decode('utf-8', errors='replace')
        else:
            raw_str = str(data)

        msg = email.message_from_string(
            raw_str, policy=email.policy.default)

        subject = str(msg.get('Subject', ''))[:500]
        from_header = str(msg.get('From', mail_from or ''))

        # Extract bodies
        body_text = ''
        body_html = ''
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == 'text/plain' and not body_text:
                    body_text = part.get_content() or ''
                elif ct == 'text/html' and not body_html:
                    body_html = part.get_content() or ''
        else:
            ct = msg.get_content_type()
            content = msg.get_content() or ''
            if ct == 'text/html':
                body_html = content
            else:
                body_text = content

        LocalDelivery.objects.create(
            from_addr=from_header[:500],
            to_addrs=rcpt_tos,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            raw=raw_str,
            peer_ip=peer_ip,
        )
        logger.info('Stored message from %s to %s: %s',
                     from_header, rcpt_tos, subject[:60])

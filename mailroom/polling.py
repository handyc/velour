"""Stdlib-only IMAP poller.

Connects to a MailAccount's IMAP server using the credentials already stored
in the mailboxes app, lists every UID in INBOX, filters out the ones we've
already fetched (dedup via InboundMessage.unique_together(mailbox, uid)),
and fetches the new ones via BODY.PEEK so the IMAP SEEN flag is NOT set —
other mail clients accessing the same mailbox see the messages as unread.

Parsing uses the email.policy.default flow so headers are RFC-compliant,
decoded to unicode, and multipart/alternative bodies split into plain and
HTML text cleanly.
"""

from __future__ import annotations

import email
import imaplib
import logging
import socket
from datetime import datetime, timezone
from email import policy
from email.utils import parsedate_to_datetime

from django.utils import timezone as django_tz

from .models import InboundMessage


log = logging.getLogger(__name__)

IMAP_TIMEOUT_SECONDS = 20
BATCH_LIMIT = 200  # cap fetches per poll so huge backfills don't block


class PollError(Exception):
    """Raised for any poll-blocking failure so the caller can surface it."""


def poll_account(account):
    """Fetch unseen messages for one MailAccount and store them.

    Returns a dict summarizing the poll: {'account': name, 'fetched': N,
    'skipped': M, 'errors': [...], 'total_known': K}.

    Does NOT mark messages as SEEN on the IMAP server. Uses BODY.PEEK[]
    during fetch so the read/unread state remains whatever it was.
    """
    result = {
        'account': account.name,
        'fetched': 0,
        'skipped': 0,
        'errors': [],
        'total_known': 0,
    }

    if not account.imap_host or not account.imap_username or not account.imap_password:
        raise PollError(f'Account "{account.name}" has no IMAP credentials set.')

    socket.setdefaulttimeout(IMAP_TIMEOUT_SECONDS)
    try:
        if account.imap_use_ssl:
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port)
    except (OSError, imaplib.IMAP4.error) as e:
        raise PollError(f'Could not connect to {account.imap_host}:{account.imap_port} — {e}')

    try:
        try:
            conn.login(account.imap_username, account.imap_password)
        except imaplib.IMAP4.error as e:
            raise PollError(f'IMAP login failed for {account.imap_username}: {e}')

        typ, _ = conn.select('INBOX', readonly=True)
        if typ != 'OK':
            raise PollError('INBOX could not be selected.')

        # List every UID currently in the mailbox, regardless of SEEN state.
        # Dedup is entirely on our side via (mailbox, uid) uniqueness.
        typ, data = conn.uid('search', None, 'ALL')
        if typ != 'OK':
            raise PollError(f'UID SEARCH failed: {data}')

        all_uids = [u.decode('ascii') for u in data[0].split()] if data and data[0] else []
        result['total_known'] = len(all_uids)

        existing = set(
            InboundMessage.objects
            .filter(mailbox=account, uid__in=all_uids)
            .values_list('uid', flat=True)
        )
        new_uids = [u for u in all_uids if u not in existing]
        result['skipped'] = len(all_uids) - len(new_uids)
        to_fetch = new_uids[-BATCH_LIMIT:]  # newest N when the list is huge

        for uid in to_fetch:
            try:
                typ, msg_data = conn.uid('fetch', uid, '(BODY.PEEK[])')
                if typ != 'OK' or not msg_data or msg_data[0] is None:
                    result['errors'].append(f'uid {uid}: fetch returned {typ}')
                    continue
                raw_bytes = msg_data[0][1]
                record = _parse_and_store(account, uid, raw_bytes)
                if record:
                    result['fetched'] += 1
            except Exception as e:
                result['errors'].append(f'uid {uid}: {type(e).__name__}: {e}')

    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    return result


def _parse_and_store(account, uid, raw_bytes):
    """Parse a raw RFC822 blob and save an InboundMessage row for it."""
    try:
        msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    except Exception as e:
        log.warning('parse failed for uid %s: %s', uid, e)
        return None

    from_addr = _header(msg, 'From')
    to_addr = _header(msg, 'To')
    subject = _header(msg, 'Subject')

    received_at = None
    date_hdr = msg.get('Date')
    if date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr)
            # parsedate_to_datetime can return a naive datetime for some
            # malformed Date: headers; coerce to aware UTC in that case.
            if received_at and received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            received_at = None

    body_text = ''
    body_html = ''
    attachments = []

    for part in msg.walk():
        ctype = part.get_content_type()
        disp = (part.get('Content-Disposition') or '').lower()
        filename = part.get_filename()
        if filename and ('attachment' in disp or 'inline' in disp):
            attachments.append(filename)
            continue
        if ctype == 'text/plain' and not filename:
            try:
                body_text += part.get_content()
            except Exception:
                pass
        elif ctype == 'text/html' and not filename:
            try:
                body_html += part.get_content()
            except Exception:
                pass

    try:
        raw_text = raw_bytes.decode('utf-8', errors='replace')
    except Exception:
        raw_text = ''

    record, created = InboundMessage.objects.get_or_create(
        mailbox=account,
        uid=uid,
        defaults={
            'from_addr': (from_addr or '')[:500],
            'to_addr': (to_addr or '')[:1000],
            'subject': (subject or '')[:500],
            'body_text': body_text,
            'body_html': body_html,
            'attachment_names': attachments,
            'received_at': received_at,
            'raw': raw_text,
        },
    )
    return record if created else None


def _header(msg, name):
    """Safely extract a (possibly-decoded) header value as a plain string."""
    val = msg.get(name)
    if val is None:
        return ''
    try:
        return str(val)
    except Exception:
        return ''

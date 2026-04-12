import json
import smtplib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import InboundMessage, LocalDelivery, MailAccount, SMTPServerConfig
from .polling import poll_account, PollError
from .sending import send_mail, NoMailboxConfigured

import hmac


# =====================================================================
# Accounts (from mailboxes)
# =====================================================================

# --- field helpers ----------------------------------------------------

_TEXT_FIELDS = (
    'name', 'smtp_host', 'smtp_username', 'from_email', 'from_name',
    'imap_host', 'imap_username', 'notes',
)

_INT_FIELDS  = ('smtp_port', 'imap_port')

_BOOL_FIELDS = ('enabled', 'is_default', 'smtp_use_tls', 'smtp_use_ssl', 'imap_use_ssl')


def _apply_post(account, post, is_new):
    """Copy POST fields onto an account instance. Passwords are only
    written when the POST actually contains a non-empty value, so editing
    an existing account without retyping the password preserves it."""
    for f in _TEXT_FIELDS:
        setattr(account, f, post.get(f, '').strip())
    for f in _INT_FIELDS:
        raw = post.get(f, '').strip()
        if raw:
            try:
                setattr(account, f, int(raw))
            except ValueError:
                pass
    for f in _BOOL_FIELDS:
        setattr(account, f, bool(post.get(f)))

    smtp_pw = post.get('smtp_password', '')
    if is_new or smtp_pw:
        account.smtp_password = smtp_pw
    imap_pw = post.get('imap_password', '')
    if is_new or imap_pw:
        account.imap_password = imap_pw


@login_required
def mailbox_list(request):
    accounts = MailAccount.objects.all()
    return render(request, 'mail/accounts_list.html', {'accounts': accounts})


@login_required
def mailbox_add(request):
    account = MailAccount()
    if request.method == 'POST':
        _apply_post(account, request.POST, is_new=True)
        if not account.name or not account.smtp_host or not account.from_email:
            messages.error(request, 'Name, SMTP host, and From address are required.')
        else:
            try:
                account.save()
                messages.success(request, f'Added mail account "{account.name}".')
                return redirect('mail:list')
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'mail/accounts_form.html', {
        'account': account,
        'action': 'Add',
    })


@login_required
def mailbox_edit(request, pk):
    account = get_object_or_404(MailAccount, pk=pk)
    if request.method == 'POST':
        _apply_post(account, request.POST, is_new=False)
        if not account.name or not account.smtp_host or not account.from_email:
            messages.error(request, 'Name, SMTP host, and From address are required.')
        else:
            try:
                account.save()
                messages.success(request, f'Updated "{account.name}".')
                return redirect('mail:list')
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'mail/accounts_form.html', {
        'account': account,
        'action': 'Edit',
    })


@login_required
@require_POST
def mailbox_delete(request, pk):
    account = get_object_or_404(MailAccount, pk=pk)
    name = account.name
    account.delete()
    messages.success(request, f'Removed "{name}".')
    return redirect('mail:list')


@login_required
def mailbox_detail(request, pk):
    account = get_object_or_404(MailAccount, pk=pk)
    return render(request, 'mail/accounts_detail.html', {'account': account})


@login_required
@require_POST
def mailbox_test(request, pk):
    """Fire a test email through this specific account and record whether it
    worked."""
    account = get_object_or_404(MailAccount, pk=pk)
    to = request.POST.get('to', '').strip()
    if not to:
        messages.error(request, 'Enter a recipient to test with.')
        return redirect('mail:detail', pk=pk)

    subject = request.POST.get('subject', '').strip() or f'Velour test from {account.name}'
    body = request.POST.get('body', '').strip() or (
        f'This is a test message sent from velour via the "{account.name}" '
        f'mail account. If you received this, the SMTP credentials and '
        f'network path are working.'
    )

    account.last_tested_at = timezone.now()
    try:
        sent = send_mail(subject, body, to=to, mailbox=account.name)
        if sent:
            account.last_test_status = 'ok'
            account.last_test_error = ''
            messages.success(request, f'Test email sent via "{account.name}" to {to}.')
        else:
            account.last_test_status = 'error'
            account.last_test_error = 'send_mail returned 0 (no message delivered)'
            messages.error(request, account.last_test_error)
    except (smtplib.SMTPException, NoMailboxConfigured, OSError) as e:
        account.last_test_status = 'error'
        account.last_test_error = f'{type(e).__name__}: {e}'
        messages.error(request, account.last_test_error)
    except Exception as e:
        account.last_test_status = 'error'
        account.last_test_error = f'unexpected: {type(e).__name__}: {e}'
        messages.error(request, account.last_test_error)
    account.save(update_fields=['last_tested_at', 'last_test_status', 'last_test_error'])
    return redirect('mail:detail', pk=pk)


# --- HTTP relay endpoint for non-velour apps (PHP, curl, shell) ------

def _read_relay_token():
    """Read mail_relay_token.txt; None if missing or empty."""
    from django.conf import settings
    token_file = settings.BASE_DIR / 'mail_relay_token.txt'
    if not token_file.is_file():
        return None
    try:
        t = token_file.read_text().strip()
        return t or None
    except OSError:
        return None


def _extract_bearer(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    return None


@csrf_exempt
@require_POST
def relay_send(request):
    """Accept a JSON POST from any external app and relay it via velour's
    configured mail accounts."""
    server_token = _read_relay_token()
    if server_token is None:
        raise Http404('mail relay not configured')

    client_token = _extract_bearer(request)
    if not client_token or not hmac.compare_digest(server_token, client_token):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        return JsonResponse({'error': f'invalid JSON: {e}'}, status=400)

    subject = payload.get('subject', '').strip() if isinstance(payload.get('subject'), str) else ''
    body    = payload.get('body', '')
    to      = payload.get('to')
    mailbox = payload.get('mailbox')
    html    = payload.get('html')
    reply_to = payload.get('reply_to')

    if not subject or not body or not to:
        return JsonResponse({
            'error': 'subject, body, and to are required fields',
        }, status=400)

    try:
        sent = send_mail(
            subject=subject, body=body, to=to, html=html,
            reply_to=reply_to, mailbox=mailbox,
        )
    except NoMailboxConfigured as e:
        return JsonResponse({'error': str(e)}, status=503)
    except (smtplib.SMTPException, OSError) as e:
        return JsonResponse({
            'error': f'{type(e).__name__}: {e}',
        }, status=502)
    except Exception as e:
        return JsonResponse({
            'error': f'unexpected: {type(e).__name__}: {e}',
        }, status=500)

    return JsonResponse({
        'ok': bool(sent),
        'delivered': sent,
        'mailbox': mailbox or 'default',
    })


# =====================================================================
# Inbound (from mailroom)
# =====================================================================

@login_required
def inbox_list(request):
    """Paginated list of received messages, optionally filtered by mailbox
    or by unread/unhandled flags."""
    qs = InboundMessage.objects.select_related('mailbox').all()

    mailbox_filter = request.GET.get('mailbox', '').strip()
    if mailbox_filter:
        qs = qs.filter(mailbox__name=mailbox_filter)
    if request.GET.get('unread'):
        qs = qs.filter(read=False)
    if request.GET.get('unhandled'):
        qs = qs.filter(handled=False)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page') or 1)

    accounts = MailAccount.objects.filter(enabled=True).values_list('name', flat=True)
    return render(request, 'mail/inbound_list.html', {
        'page': page,
        'accounts': accounts,
        'mailbox_filter': mailbox_filter,
        'unread_only': bool(request.GET.get('unread')),
        'unhandled_only': bool(request.GET.get('unhandled')),
    })


@login_required
def inbox_detail(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    if not msg.read:
        msg.read = True
        msg.save(update_fields=['read'])
    return render(request, 'mail/inbound_detail.html', {'msg': msg})


@login_required
@require_POST
def inbox_delete(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    subject = msg.subject or '(no subject)'
    msg.delete()
    messages.success(request, f'Deleted "{subject[:60]}".')
    return redirect('mail:inbound_list')


@login_required
@require_POST
def inbox_mark_unread(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    msg.read = False
    msg.save(update_fields=['read'])
    return redirect('mail:inbound_list')


@login_required
@require_POST
def inbox_mark_handled(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    msg.handled = not msg.handled
    msg.save(update_fields=['handled'])
    return redirect('mail:inbound_detail', pk=pk)


@login_required
@require_POST
def poll_mailbox(request, mailbox_pk):
    """Trigger an IMAP poll for a specific mailbox."""
    account = get_object_or_404(MailAccount, pk=mailbox_pk)
    try:
        result = poll_account(account)
    except PollError as e:
        messages.error(request, f'{account.name}: {e}')
        return redirect('mail:detail', pk=mailbox_pk)
    except Exception as e:
        messages.error(request, f'{account.name}: unexpected {type(e).__name__}: {e}')
        return redirect('mail:detail', pk=mailbox_pk)

    summary = f'{account.name}: fetched {result["fetched"]} new, skipped {result["skipped"]} existing'
    if result['errors']:
        summary += f', {len(result["errors"])} error(s)'
        messages.warning(request, summary)
    else:
        messages.success(request, summary)
    return redirect('mail:inbound_list')


# =====================================================================
# Server (from mailserver)
# =====================================================================

@login_required
def server_inbox(request):
    deliveries = LocalDelivery.objects.all()[:50]
    config = SMTPServerConfig.get_self()
    unread = LocalDelivery.objects.filter(read=False).count()
    total = LocalDelivery.objects.count()
    return render(request, 'mail/server_inbox.html', {
        'deliveries': deliveries,
        'config':     config,
        'unread':     unread,
        'total':      total,
    })


@login_required
def server_detail(request, pk):
    msg = get_object_or_404(LocalDelivery, pk=pk)
    if not msg.read:
        msg.read = True
        msg.save(update_fields=['read'])
    return render(request, 'mail/server_detail.html', {'msg': msg})


@login_required
@require_POST
def server_delete(request, pk):
    msg = get_object_or_404(LocalDelivery, pk=pk)
    msg.delete()
    return redirect('mail:server_inbox')

import json
import smtplib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import MailAccount
from .sending import send_mail, NoMailboxConfigured


# --- field helpers ----------------------------------------------------

# POST fields that map straight onto model attributes without any
# coercion beyond str() (the form renders text inputs for everything).
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

    # Passwords: empty field on edit means "keep existing".
    smtp_pw = post.get('smtp_password', '')
    if is_new or smtp_pw:
        account.smtp_password = smtp_pw
    imap_pw = post.get('imap_password', '')
    if is_new or imap_pw:
        account.imap_password = imap_pw


# --- views ------------------------------------------------------------

@login_required
def mailbox_list(request):
    accounts = MailAccount.objects.all()
    return render(request, 'mailboxes/list.html', {'accounts': accounts})


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
                return redirect('mailboxes:list')
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'mailboxes/form.html', {
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
                return redirect('mailboxes:list')
            except Exception as e:
                messages.error(request, f'Could not save: {e}')
    return render(request, 'mailboxes/form.html', {
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
    return redirect('mailboxes:list')


@login_required
def mailbox_detail(request, pk):
    account = get_object_or_404(MailAccount, pk=pk)
    return render(request, 'mailboxes/detail.html', {'account': account})


@login_required
@require_POST
def mailbox_test(request, pk):
    """Fire a test email through this specific account and record whether it
    worked. Uses the helper with mailbox=account.name so routing is exercised
    end-to-end, not just the default path."""
    account = get_object_or_404(MailAccount, pk=pk)
    to = request.POST.get('to', '').strip()
    if not to:
        messages.error(request, 'Enter a recipient to test with.')
        return redirect('mailboxes:detail', pk=pk)

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
    return redirect('mailboxes:detail', pk=pk)


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


from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import hmac


@csrf_exempt
@require_POST
def relay_send(request):
    """Accept a JSON POST from any external app and relay it via velour's
    configured mail accounts. Request body:

        {
            "subject":  "Hello",
            "body":     "Plain text body",
            "to":       "user@example.com",   # or a list
            "mailbox":  "billing",            # optional; default account if omitted
            "html":     "<b>HTML body</b>",   # optional
            "reply_to": "support@example.com" # optional
        }

    Auth: Authorization: Bearer <mail_relay_token.txt contents>. If the token
    file is missing, the endpoint 404s (invisible) — same pattern as health.
    """
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

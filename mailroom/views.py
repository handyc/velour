from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from mailboxes.models import MailAccount

from .models import InboundMessage
from .polling import poll_account, PollError


@login_required
def inbox_list(request):
    """Paginated list of received messages, optionally filtered by mailbox
    or by unread/unhandled flags. Query params: mailbox, unread, unhandled."""
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
    return render(request, 'mailroom/list.html', {
        'page': page,
        'accounts': accounts,
        'mailbox_filter': mailbox_filter,
        'unread_only': bool(request.GET.get('unread')),
        'unhandled_only': bool(request.GET.get('unhandled')),
    })


@login_required
def inbox_detail(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    # Mark as read on first view — mirrors any webmail client behavior.
    if not msg.read:
        msg.read = True
        msg.save(update_fields=['read'])
    return render(request, 'mailroom/detail.html', {'msg': msg})


@login_required
@require_POST
def inbox_delete(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    subject = msg.subject or '(no subject)'
    msg.delete()
    messages.success(request, f'Deleted "{subject[:60]}".')
    return redirect('mailroom:list')


@login_required
@require_POST
def inbox_mark_unread(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    msg.read = False
    msg.save(update_fields=['read'])
    return redirect('mailroom:list')


@login_required
@require_POST
def inbox_mark_handled(request, pk):
    msg = get_object_or_404(InboundMessage, pk=pk)
    msg.handled = not msg.handled
    msg.save(update_fields=['handled'])
    return redirect('mailroom:detail', pk=pk)


@login_required
@require_POST
def poll_mailbox(request, mailbox_pk):
    """Trigger an IMAP poll for a specific mailbox. Wired from the
    mailboxes detail page "Poll now" button."""
    account = get_object_or_404(MailAccount, pk=mailbox_pk)
    try:
        result = poll_account(account)
    except PollError as e:
        messages.error(request, f'{account.name}: {e}')
        return redirect('mailboxes:detail', pk=mailbox_pk)
    except Exception as e:
        messages.error(request, f'{account.name}: unexpected {type(e).__name__}: {e}')
        return redirect('mailboxes:detail', pk=mailbox_pk)

    summary = f'{account.name}: fetched {result["fetched"]} new, skipped {result["skipped"]} existing'
    if result['errors']:
        summary += f', {len(result["errors"])} error(s)'
        messages.warning(request, summary)
    else:
        messages.success(request, summary)
    return redirect('mailroom:list', )

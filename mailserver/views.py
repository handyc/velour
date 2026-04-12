from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import LocalDelivery, SMTPServerConfig


@login_required
def inbox(request):
    deliveries = LocalDelivery.objects.all()[:50]
    config = SMTPServerConfig.get_self()
    unread = LocalDelivery.objects.filter(read=False).count()
    total = LocalDelivery.objects.count()
    return render(request, 'mailserver/inbox.html', {
        'deliveries': deliveries,
        'config':     config,
        'unread':     unread,
        'total':      total,
    })


@login_required
def message_detail(request, pk):
    msg = get_object_or_404(LocalDelivery, pk=pk)
    if not msg.read:
        msg.read = True
        msg.save(update_fields=['read'])
    return render(request, 'mailserver/detail.html', {'msg': msg})


@login_required
@require_POST
def message_delete(request, pk):
    msg = get_object_or_404(LocalDelivery, pk=pk)
    msg.delete()
    return redirect('mailserver:inbox')

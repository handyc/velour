from django.shortcuts import render, get_object_or_404

from .models import Policy, IrcContact, BotSession, VibegamePush


def dashboard(request):
    return render(request, 'h4kslnk/dashboard.html', {
        'policies': Policy.objects.all(),
        'contacts': IrcContact.objects.all(),
        'sessions': BotSession.objects.all()[:20],
        'pushes':   VibegamePush.objects.all()[:10],
    })


def policy(request, slug):
    return render(request, 'h4kslnk/policy.html', {
        'policy': get_object_or_404(Policy, slug=slug),
    })


def contact(request, nick):
    c = get_object_or_404(IrcContact, nick=nick)
    return render(request, 'h4kslnk/contact.html', {
        'contact':  c,
        'sessions': BotSession.objects.filter(target=c.nick),
    })


def session(request, pk):
    s = get_object_or_404(BotSession, pk=pk)
    return render(request, 'h4kslnk/session.html', {
        'session':  s,
        'messages': s.messages.all(),
    })


def pushes(request):
    return render(request, 'h4kslnk/pushes.html', {
        'pushes': VibegamePush.objects.all(),
    })

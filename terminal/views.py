from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render


# A web shell here is full RCE as the project user. Gate on
# is_superuser, not is_staff — staff users may admin specific apps
# without deserving shell access. Mirrored in TerminalConsumer.
# TODO(multi-user): once we add MFA on the Django login, the path
# from "stolen session cookie" to "shell on the host" stops being
# one click. Until then, this gate is the only thing in the way.
@user_passes_test(lambda u: u.is_active and u.is_superuser, login_url='/accounts/login/')
def terminal_view(request):
    return render(request, 'terminal/terminal.html')

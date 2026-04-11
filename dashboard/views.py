import os
import platform
import subprocess

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def landing(request):
    if request.user.is_authenticated:
        return dashboard_home(request)
    # Delegate to the newspaper-style landing page
    from landingpage.views import landing as lp_landing
    return lp_landing(request)


@login_required
def dashboard_home(request):
    try:
        uptime = subprocess.check_output(['uptime', '-p'], text=True).strip()
    except Exception:
        uptime = 'N/A'

    try:
        load = subprocess.check_output(
            ['cat', '/proc/loadavg'], text=True
        ).strip().split()[:3]
        load = ' '.join(load)
    except Exception:
        load = 'N/A'

    system_info = {
        'user': os.environ.get('USER', 'unknown'),
        'hostname': platform.node(),
        'uptime': uptime,
        'load': load,
    }
    return render(request, 'dashboard/home.html', {'system_info': system_info})

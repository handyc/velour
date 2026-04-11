import json
import subprocess

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


@login_required
def terminal_view(request):
    return render(request, 'terminal/terminal.html')


@login_required
@require_POST
def terminal_execute(request):
    """Execute a command on the host system and return the output."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    command = data.get('command', '').strip()
    use_sudo = data.get('sudo', False)
    cwd = data.get('cwd', None)

    if not command:
        return JsonResponse({'error': 'No command provided'}, status=400)

    if use_sudo and request.user.is_superuser:
        command = f'sudo {command}'

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return JsonResponse({
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        return JsonResponse({
            'stdout': '',
            'stderr': 'Command timed out after 30 seconds.',
            'returncode': -1,
        })
    except Exception as e:
        return JsonResponse({
            'stdout': '',
            'stderr': str(e),
            'returncode': -1,
        })

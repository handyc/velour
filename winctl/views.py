import json
import os
import subprocess

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


def _ps(command, timeout=15):
    """Run a PowerShell command via powershell.exe and return stdout."""
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return '', 'powershell.exe not found. Is this running inside WSL?', -1
    except subprocess.TimeoutExpired:
        return '', 'Command timed out.', -1
    except Exception as e:
        return '', str(e), -1


def _is_wsl():
    """Check if we're running inside WSL."""
    try:
        with open('/proc/version') as f:
            return 'microsoft' in f.read().lower()
    except Exception:
        return False


# ---------- System Info ----------

@login_required
def winctl_home(request):
    wsl = _is_wsl()
    info = {}
    if wsl:
        # Gather basic Windows info
        stdout, _, _ = _ps(
            'Get-CimInstance Win32_OperatingSystem | '
            'Select-Object Caption, Version, OSArchitecture, '
            'TotalVisibleMemorySize, FreePhysicalMemory, '
            'LastBootUpTime | ConvertTo-Json'
        )
        if stdout:
            try:
                info['os'] = json.loads(stdout)
            except json.JSONDecodeError:
                info['os_raw'] = stdout

        stdout, _, _ = _ps(
            'Get-CimInstance Win32_Processor | '
            'Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, '
            'CurrentClockSpeed | ConvertTo-Json'
        )
        if stdout:
            try:
                info['cpu'] = json.loads(stdout)
            except json.JSONDecodeError:
                pass

        stdout, _, _ = _ps(
            'Get-CimInstance Win32_ComputerSystem | '
            'Select-Object Name, Domain, UserName, Manufacturer, Model | ConvertTo-Json'
        )
        if stdout:
            try:
                info['system'] = json.loads(stdout)
            except json.JSONDecodeError:
                pass

    return render(request, 'winctl/home.html', {'wsl': wsl, 'info': info})


# ---------- API Endpoints ----------

@login_required
def win_processes(request):
    """List Windows processes."""
    stdout, err, rc = _ps(
        'Get-Process | Sort-Object -Property WorkingSet64 -Descending | '
        'Select-Object -First 30 Name, Id, CPU, '
        '@{N="MemMB";E={[math]::Round($_.WorkingSet64/1MB,1)}} | '
        'ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'processes': data})


@login_required
def win_services(request):
    """List Windows services."""
    stdout, err, rc = _ps(
        'Get-Service | Select-Object Name, DisplayName, Status | ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'services': data})


@login_required
def win_disks(request):
    """Disk info."""
    stdout, err, rc = _ps(
        'Get-CimInstance Win32_LogicalDisk | '
        'Select-Object DeviceID, VolumeName, '
        '@{N="SizeGB";E={[math]::Round($_.Size/1GB,1)}}, '
        '@{N="FreeGB";E={[math]::Round($_.FreeSpace/1GB,1)}}, '
        'DriveType | ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'disks': data})


@login_required
def win_network(request):
    """Network adapters."""
    stdout, err, rc = _ps(
        'Get-NetAdapter | Where-Object Status -eq "Up" | '
        'Select-Object Name, InterfaceDescription, MacAddress, '
        'LinkSpeed, Status | ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'adapters': data})


@login_required
def win_installed(request):
    """Installed programs."""
    stdout, err, rc = _ps(
        'Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | '
        'Where-Object DisplayName | '
        'Select-Object DisplayName, DisplayVersion, Publisher, InstallDate | '
        'Sort-Object DisplayName | ConvertTo-Json',
        timeout=20,
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'programs': data})


@login_required
def win_startup(request):
    """Startup programs."""
    stdout, err, rc = _ps(
        'Get-CimInstance Win32_StartupCommand | '
        'Select-Object Name, Command, Location, User | ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'startup': data})


@login_required
def win_eventlog(request):
    """Recent Windows event log errors/warnings."""
    log_name = request.GET.get('log', 'System')
    count = min(int(request.GET.get('count', 50)), 200)
    stdout, err, rc = _ps(
        f'Get-EventLog -LogName {log_name} -Newest {count} -EntryType Error,Warning 2>$null | '
        f'Select-Object TimeGenerated, EntryType, Source, Message | ConvertTo-Json',
        timeout=20,
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'events': data, 'log_name': log_name})


@login_required
def win_env(request):
    """Windows environment variables."""
    stdout, err, rc = _ps(
        '[System.Environment]::GetEnvironmentVariables("Machine") | '
        'ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = {}
    return JsonResponse({'env': data})


@login_required
def win_scheduled_tasks(request):
    """Scheduled tasks."""
    stdout, err, rc = _ps(
        'Get-ScheduledTask | Where-Object State -ne "Disabled" | '
        'Select-Object -First 40 TaskName, TaskPath, State, '
        '@{N="NextRun";E={($_ | Get-ScheduledTaskInfo).NextRunTime}} | '
        'ConvertTo-Json',
        timeout=20,
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'tasks': data})


@login_required
def win_firewall(request):
    """Windows firewall status."""
    stdout, err, rc = _ps(
        'Get-NetFirewallProfile | Select-Object Name, Enabled, '
        'DefaultInboundAction, DefaultOutboundAction | ConvertTo-Json'
    )
    if rc != 0:
        return JsonResponse({'error': err}, status=500)
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = []
    return JsonResponse({'profiles': data})


@login_required
@require_POST
def win_run(request):
    """Run a custom PowerShell command."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    command = body.get('command', '').strip()
    if not command:
        return JsonResponse({'error': 'No command provided'}, status=400)

    stdout, stderr, rc = _ps(command)
    return JsonResponse({
        'stdout': stdout,
        'stderr': stderr,
        'returncode': rc,
    })

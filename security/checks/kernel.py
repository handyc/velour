"""Kernel hardening audit — cross-platform."""

from security.platform import PlatformInfo
from security.runner import run, run_powershell, read_sysctl


def check_kernel(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_kernel_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_kernel_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_kernel_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_kernel_bsd(pinfo)
    return []


def _check_kernel_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    checks = [
        ('kernel.randomize_va_space', '2', 'ASLR',
         'Address Space Layout Randomization should be fully enabled (2).',
         'critical', 'sysctl -w kernel.randomize_va_space=2'),
        ('net.ipv4.conf.all.rp_filter', '1', 'Reverse Path Filtering',
         'Prevents IP spoofing by verifying source addresses.',
         'medium', 'sysctl -w net.ipv4.conf.all.rp_filter=1'),
        ('net.ipv4.icmp_echo_ignore_broadcasts', '1', 'ICMP Broadcast Ignore',
         'Prevents Smurf attacks via ICMP broadcast responses.',
         'medium', 'sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1'),
        ('net.ipv4.conf.all.accept_redirects', '0', 'ICMP Redirects (IPv4)',
         'ICMP redirects can be used for MITM attacks.',
         'medium', 'sysctl -w net.ipv4.conf.all.accept_redirects=0'),
        ('net.ipv6.conf.all.accept_redirects', '0', 'ICMP Redirects (IPv6)',
         'IPv6 ICMP redirects should be disabled.',
         'medium', 'sysctl -w net.ipv6.conf.all.accept_redirects=0'),
        ('net.ipv4.conf.all.send_redirects', '0', 'Send Redirects',
         'System should not send ICMP redirects (unless acting as a router).',
         'medium', 'sysctl -w net.ipv4.conf.all.send_redirects=0'),
        ('net.ipv4.conf.all.accept_source_route', '0', 'Source Routing',
         'Source-routed packets can bypass security controls.',
         'high', 'sysctl -w net.ipv4.conf.all.accept_source_route=0'),
        ('net.ipv4.tcp_syncookies', '1', 'TCP SYN Cookies',
         'SYN cookies protect against SYN flood DoS attacks.',
         'high', 'sysctl -w net.ipv4.tcp_syncookies=1'),
        ('kernel.dmesg_restrict', '1', 'Dmesg Restrict',
         'Restricts unprivileged access to kernel log messages.',
         'low', 'sysctl -w kernel.dmesg_restrict=1'),
        ('kernel.kptr_restrict', '1', 'Kernel Pointer Restrict',
         'Hides kernel memory addresses from unprivileged users.',
         'medium', 'sysctl -w kernel.kptr_restrict=1'),
        ('fs.protected_hardlinks', '1', 'Protected Hardlinks',
         'Prevents hardlink-based privilege escalation attacks.',
         'medium', 'sysctl -w fs.protected_hardlinks=1'),
        ('fs.protected_symlinks', '1', 'Protected Symlinks',
         'Prevents symlink-based attacks in world-writable directories.',
         'medium', 'sysctl -w fs.protected_symlinks=1'),
        ('fs.suid_dumpable', '0', 'SUID Core Dumps',
         'Core dumps of SUID programs can leak sensitive data.',
         'medium', 'sysctl -w fs.suid_dumpable=0'),
    ]

    for key, expected, name, desc, severity, fix in checks:
        actual = read_sysctl(key)
        if actual == '':
            continue  # key not present on this kernel
        if actual == expected:
            findings.append({
                'name': f'Kernel: {name}',
                'status': 'pass',
                'detail': f'{key} = {actual}',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': f'Kernel: {name}',
                'status': 'fail' if severity in ('critical', 'high') else 'warn',
                'detail': f'{key} = {actual} (expected {expected}). {desc}',
                'severity': severity,
                'fix': f'{fix}  (persist in /etc/sysctl.d/99-hardening.conf)',
            })

    # IP forwarding (should be 0 unless intentional)
    ip_fwd = read_sysctl('net.ipv4.ip_forward')
    if ip_fwd == '1' and not pinfo.is_container:
        findings.append({
            'name': 'Kernel: IP Forwarding Enabled',
            'status': 'warn',
            'detail': 'net.ipv4.ip_forward = 1. Unless this is a router or container host, disable it.',
            'severity': 'medium',
            'fix': 'sysctl -w net.ipv4.ip_forward=0',
        })

    # Yama ptrace scope
    ptrace = read_sysctl('kernel.yama.ptrace_scope')
    if ptrace and ptrace == '0':
        findings.append({
            'name': 'Kernel: Ptrace Unrestricted',
            'status': 'warn',
            'detail': 'kernel.yama.ptrace_scope = 0. Any process can ptrace any other.',
            'severity': 'medium',
            'fix': 'sysctl -w kernel.yama.ptrace_scope=1',
        })

    return findings


def _check_kernel_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # SIP (also checked in filesystem, but core kernel protection)
    sip = run(['csrutil', 'status'])
    if sip and 'enabled' in sip.lower():
        findings.append({
            'name': 'Kernel: System Integrity Protection',
            'status': 'pass',
            'detail': 'SIP is enabled, protecting kernel and system files.',
            'severity': 'ok', 'fix': None,
        })
    elif sip:
        findings.append({
            'name': 'Kernel: SIP Disabled',
            'status': 'fail',
            'detail': 'System Integrity Protection is disabled.',
            'severity': 'critical',
            'fix': 'Reboot to Recovery Mode and run: csrutil enable',
        })

    # AMFI (Apple Mobile File Integrity)
    amfi = run(['sysctl', '-n', 'cs_enforcement_disable'])
    if amfi and amfi.strip() == '1':
        findings.append({
            'name': 'Kernel: Code Signing Enforcement Disabled',
            'status': 'fail',
            'detail': 'Code signing enforcement is disabled.',
            'severity': 'critical', 'fix': None,
        })

    # kern.securelevel
    sl = run(['sysctl', '-n', 'kern.securelevel'])
    if sl:
        findings.append({
            'name': f'Kernel: Securelevel = {sl.strip()}',
            'status': 'info',
            'detail': f'kern.securelevel = {sl.strip()}',
            'severity': 'info', 'fix': None,
        })

    return findings


def _check_kernel_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check DEP / NX
    dep = run_powershell(
        '(Get-CimInstance Win32_OperatingSystem).DataExecutionPrevention_SupportPolicy'
    )
    if dep:
        policies = {'0': 'Off', '1': 'OptIn', '2': 'OptOut', '3': 'AlwaysOn'}
        policy = policies.get(dep.strip(), dep.strip())
        if dep.strip() in ('2', '3'):
            findings.append({
                'name': f'DEP/NX: {policy}',
                'status': 'pass',
                'detail': f'Data Execution Prevention policy: {policy}.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': f'DEP/NX: {policy}',
                'status': 'warn',
                'detail': f'DEP policy is {policy}. Consider enabling OptOut or AlwaysOn.',
                'severity': 'medium',
                'fix': 'bcdedit /set nx OptOut',
            })

    # Credential Guard
    cg = run_powershell(
        '(Get-CimInstance -ClassName Win32_DeviceGuard '
        '-Namespace root\\Microsoft\\Windows\\DeviceGuard '
        '-ErrorAction SilentlyContinue).SecurityServicesRunning'
    )
    if cg and '1' in cg:
        findings.append({
            'name': 'Credential Guard: Active',
            'status': 'pass',
            'detail': 'Windows Credential Guard is running.',
            'severity': 'ok', 'fix': None,
        })
    elif cg is not None:
        findings.append({
            'name': 'Credential Guard: Not Active',
            'status': 'info',
            'detail': 'Credential Guard is not running. Available on Enterprise/Education editions.',
            'severity': 'low', 'fix': None,
        })

    # Secure Boot
    sb = run_powershell('Confirm-SecureBootUEFI 2>$null')
    if sb:
        if 'true' in sb.lower():
            findings.append({
                'name': 'Secure Boot: Enabled',
                'status': 'pass',
                'detail': 'UEFI Secure Boot is enabled.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Secure Boot: Disabled',
                'status': 'warn',
                'detail': 'Secure Boot is not enabled.',
                'severity': 'medium',
                'fix': 'Enable Secure Boot in UEFI/BIOS settings.',
            })

    return findings


def _check_kernel_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    sl = run(['sysctl', '-n', 'kern.securelevel'])
    if sl:
        try:
            level = int(sl.strip())
            if level >= 1:
                findings.append({
                    'name': f'Kernel: Securelevel = {level}',
                    'status': 'pass',
                    'detail': f'kern.securelevel = {level}.',
                    'severity': 'ok', 'fix': None,
                })
            else:
                findings.append({
                    'name': f'Kernel: Securelevel = {level}',
                    'status': 'warn',
                    'detail': 'Securelevel is low. Consider raising to 1 or 2.',
                    'severity': 'medium',
                    'fix': 'Set kern.securelevel=1 in /etc/sysctl.conf.',
                })
        except ValueError:
            pass

    return findings

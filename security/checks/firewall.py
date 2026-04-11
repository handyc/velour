"""Firewall status audit — cross-platform."""

from security.platform import PlatformInfo, is_debian_family, is_rhel_family
from security.runner import run, run_powershell, command_exists


def check_firewall(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_firewall_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_firewall_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_firewall_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd'):
        return _check_firewall_bsd(pinfo)
    return [{'name': 'Firewall', 'status': 'skip',
             'detail': f'Unsupported platform: {pinfo.os_family}',
             'severity': 'info', 'fix': None}]


# ── Linux ───────────────────────────────────────────────────────────

def _check_firewall_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Try UFW first (Debian/Ubuntu family)
    if is_debian_family(pinfo) or command_exists('ufw'):
        ufw = run(['ufw', 'status', 'verbose'])
        if ufw:
            if 'inactive' in ufw.lower():
                findings.append({
                    'name': 'Firewall (UFW): Inactive',
                    'status': 'fail',
                    'detail': 'UFW is installed but not enabled.',
                    'severity': 'high',
                    'fix': 'sudo ufw enable && sudo ufw allow ssh',
                })
            elif 'active' in ufw.lower():
                findings.append({
                    'name': 'Firewall (UFW): Active',
                    'status': 'pass',
                    'detail': ufw[:300],
                    'severity': 'ok', 'fix': None,
                })
                # Check default policies
                if 'default: allow (incoming)' in ufw.lower():
                    findings.append({
                        'name': 'UFW: Default Incoming ALLOW',
                        'status': 'fail',
                        'detail': 'Default incoming policy is ALLOW. Should be DENY.',
                        'severity': 'high',
                        'fix': 'sudo ufw default deny incoming',
                    })
            return findings

    # Try firewalld (RHEL/Fedora family)
    if is_rhel_family(pinfo) or command_exists('firewall-cmd'):
        state = run(['firewall-cmd', '--state'])
        if state and 'running' in state.lower():
            zone_info = run(['firewall-cmd', '--list-all'])
            findings.append({
                'name': 'Firewall (firewalld): Active',
                'status': 'pass',
                'detail': zone_info[:300] if zone_info else 'firewalld is running.',
                'severity': 'ok', 'fix': None,
            })
            return findings
        elif state:
            findings.append({
                'name': 'Firewall (firewalld): Inactive',
                'status': 'fail',
                'detail': 'firewalld is installed but not running.',
                'severity': 'high',
                'fix': 'sudo systemctl enable --now firewalld',
            })
            return findings

    # Fall back to nftables
    nft = run(['nft', 'list', 'ruleset'])
    if nft and len(nft.strip().splitlines()) > 1:
        findings.append({
            'name': 'Firewall (nftables): Rules Found',
            'status': 'pass',
            'detail': f'{len(nft.splitlines())} lines of nftables rules loaded.',
            'severity': 'ok', 'fix': None,
        })
        return findings

    # Fall back to iptables
    ipt = run(['iptables', '-L', '-n', '--line-numbers'])
    if ipt and 'ACCEPT' in ipt:
        findings.append({
            'name': 'Firewall (iptables): Rules Found',
            'status': 'pass',
            'detail': f'{len(ipt.splitlines())} iptables rules loaded.',
            'severity': 'ok', 'fix': None,
        })
        return findings

    # Nothing found
    fix = 'sudo apt install ufw && sudo ufw enable' if is_debian_family(pinfo) \
        else 'sudo systemctl enable --now firewalld' if is_rhel_family(pinfo) \
        else 'Install and configure a firewall (ufw, firewalld, or nftables).'
    findings.append({
        'name': 'Firewall: None Detected',
        'status': 'fail',
        'detail': 'No active firewall found.',
        'severity': 'high',
        'fix': fix,
    })
    return findings


# ── macOS ───────────────────────────────────────────────────────────

def _check_firewall_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Application Layer Firewall (ALF)
    alf = run(['defaults', 'read', '/Library/Preferences/com.apple.alf', 'globalstate'])
    if alf:
        state = alf.strip()
        if state == '0':
            findings.append({
                'name': 'macOS Application Firewall: Disabled',
                'status': 'fail',
                'detail': 'The built-in application firewall is turned off.',
                'severity': 'high',
                'fix': 'System Settings → Network → Firewall → Turn On. Or: sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on',
            })
        elif state in ('1', '2'):
            findings.append({
                'name': 'macOS Application Firewall: Active',
                'status': 'pass',
                'detail': f'Firewall state = {state} (1=on, 2=on+block all incoming).',
                'severity': 'ok', 'fix': None,
            })

            # Check stealth mode
            stealth = run(['defaults', 'read', '/Library/Preferences/com.apple.alf', 'stealthenabled'])
            if stealth and stealth.strip() == '0':
                findings.append({
                    'name': 'macOS Firewall: Stealth Mode Off',
                    'status': 'info',
                    'detail': 'Stealth mode is disabled. The system responds to ICMP probes.',
                    'severity': 'low',
                    'fix': 'sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on',
                })
    else:
        findings.append({
            'name': 'macOS Application Firewall',
            'status': 'unknown',
            'detail': 'Could not determine firewall status.',
            'severity': 'info', 'fix': None,
        })

    # PF (Packet Filter)
    pf_info = run(['pfctl', '-s', 'info'])
    if pf_info:
        if 'enabled' in pf_info.lower():
            findings.append({
                'name': 'macOS PF (Packet Filter): Enabled',
                'status': 'pass',
                'detail': 'PF packet filter is active.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'macOS PF (Packet Filter): Disabled',
                'status': 'info',
                'detail': 'PF is not active. The Application Firewall is typically sufficient for desktops.',
                'severity': 'low', 'fix': None,
            })

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_firewall_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    profiles = run_powershell(
        'Get-NetFirewallProfile | Select-Object Name, Enabled | Format-List'
    )
    if profiles:
        disabled = []
        for line in profiles.splitlines():
            line = line.strip()
            if line.startswith('Name'):
                current_name = line.split(':', 1)[1].strip()
            elif line.startswith('Enabled') and 'False' in line:
                disabled.append(current_name)

        if disabled:
            findings.append({
                'name': f'Windows Firewall: Disabled Profiles',
                'status': 'fail',
                'detail': f'Firewall disabled for: {", ".join(disabled)}.',
                'severity': 'high',
                'fix': 'Enable via: Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True',
            })
        else:
            findings.append({
                'name': 'Windows Firewall: All Profiles Active',
                'status': 'pass',
                'detail': 'Domain, Private, and Public profiles are all enabled.',
                'severity': 'ok', 'fix': None,
            })
    else:
        # Fallback to netsh
        netsh = run(['netsh', 'advfirewall', 'show', 'allprofiles', 'state'])
        if netsh:
            if 'off' in netsh.lower():
                findings.append({
                    'name': 'Windows Firewall: Profile(s) Disabled',
                    'status': 'fail',
                    'detail': netsh[:300],
                    'severity': 'high',
                    'fix': 'netsh advfirewall set allprofiles state on',
                })
            else:
                findings.append({
                    'name': 'Windows Firewall: Active',
                    'status': 'pass',
                    'detail': 'All firewall profiles appear enabled.',
                    'severity': 'ok', 'fix': None,
                })
        else:
            findings.append({
                'name': 'Windows Firewall',
                'status': 'unknown',
                'detail': 'Could not determine firewall status.',
                'severity': 'info', 'fix': None,
            })

    return findings


# ── BSD ─────────────────────────────────────────────────────────────

def _check_firewall_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    pf_info = run(['pfctl', '-s', 'info'])
    if pf_info and 'enabled' in pf_info.lower():
        rules = run(['pfctl', '-s', 'rules'])
        rule_count = len(rules.splitlines()) if rules else 0
        findings.append({
            'name': 'Firewall (PF): Active',
            'status': 'pass',
            'detail': f'PF is enabled with {rule_count} rules.',
            'severity': 'ok', 'fix': None,
        })
    elif pf_info:
        findings.append({
            'name': 'Firewall (PF): Disabled',
            'status': 'fail',
            'detail': 'PF packet filter is not enabled.',
            'severity': 'high',
            'fix': 'Enable PF in /etc/pf.conf and run: pfctl -e -f /etc/pf.conf',
        })
    else:
        # Check ipfw (FreeBSD alternative)
        ipfw = run(['ipfw', 'list'])
        if ipfw:
            findings.append({
                'name': 'Firewall (IPFW): Active',
                'status': 'pass',
                'detail': f'{len(ipfw.splitlines())} IPFW rules loaded.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Firewall: None Detected',
                'status': 'fail',
                'detail': 'No PF or IPFW firewall rules found.',
                'severity': 'high',
                'fix': 'Configure PF in /etc/pf.conf.',
            })

    return findings

"""DNS security audit — cross-platform."""

import re

from security.platform import PlatformInfo, is_unix
from security.runner import run, run_powershell, read_file


def check_dns(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_dns_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_dns_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_dns_windows(pinfo)
    return []


# Well-known privacy/security DNS resolvers
SECURE_DNS = {
    '1.1.1.1', '1.0.0.1',                      # Cloudflare
    '8.8.8.8', '8.8.4.4',                       # Google
    '9.9.9.9', '149.112.112.112',               # Quad9
    '208.67.222.222', '208.67.220.220',          # OpenDNS
}


def _check_dns_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check resolv.conf
    resolv = read_file('/etc/resolv.conf')
    if resolv:
        nameservers = re.findall(r'^nameserver\s+(\S+)', resolv, re.MULTILINE)
        if nameservers:
            findings.append({
                'name': f'DNS Resolvers: {", ".join(nameservers)}',
                'status': 'info',
                'detail': f'Configured nameservers: {", ".join(nameservers)}',
                'severity': 'info', 'fix': None,
            })

            # Check for localhost (systemd-resolved or local resolver)
            if any(ns in ('127.0.0.53', '127.0.0.1', '::1') for ns in nameservers):
                findings.append({
                    'name': 'DNS: Local Resolver',
                    'status': 'pass',
                    'detail': 'Using a local DNS resolver (systemd-resolved or similar).',
                    'severity': 'ok', 'fix': None,
                })

    # Check systemd-resolved for DNS-over-TLS
    if pinfo.init_system == 'systemd':
        resolved = run(['resolvectl', 'status'])
        if resolved:
            if 'dns over tls' in resolved.lower():
                if 'yes' in resolved.lower().split('dns over tls')[1][:20]:
                    findings.append({
                        'name': 'DNS-over-TLS: Enabled',
                        'status': 'pass',
                        'detail': 'systemd-resolved is using DNS-over-TLS.',
                        'severity': 'ok', 'fix': None,
                    })
            if 'dnssec' in resolved.lower():
                if 'yes' in resolved.lower().split('dnssec')[1][:20]:
                    findings.append({
                        'name': 'DNSSEC: Enabled',
                        'status': 'pass',
                        'detail': 'DNSSEC validation is enabled.',
                        'severity': 'ok', 'fix': None,
                    })

    # DNSSEC validation check
    dnssec = run(['dig', '+short', '+dnssec', 'cloudflare.com', 'A'], timeout=10)
    if dnssec and 'rrsig' in dnssec.lower():
        findings.append({
            'name': 'DNSSEC Validation',
            'status': 'pass',
            'detail': 'DNSSEC signatures are being returned.',
            'severity': 'ok', 'fix': None,
        })

    return findings


def _check_dns_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    dns_config = run(['scutil', '--dns'])
    if dns_config:
        nameservers = re.findall(r'nameserver\[\d+\]\s*:\s*(\S+)', dns_config)
        unique_ns = list(dict.fromkeys(nameservers))
        if unique_ns:
            findings.append({
                'name': f'DNS Resolvers: {", ".join(unique_ns[:5])}',
                'status': 'info',
                'detail': f'Configured nameservers: {", ".join(unique_ns)}',
                'severity': 'info', 'fix': None,
            })

    return findings


def _check_dns_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    dns = run_powershell(
        'Get-DnsClientServerAddress -AddressFamily IPv4 | '
        'Select-Object InterfaceAlias, ServerAddresses | Format-List'
    )
    if dns:
        servers = re.findall(r'(\d+\.\d+\.\d+\.\d+)', dns)
        unique = list(dict.fromkeys(servers))
        if unique:
            findings.append({
                'name': f'DNS Resolvers: {", ".join(unique[:5])}',
                'status': 'info',
                'detail': f'Configured DNS servers: {", ".join(unique)}',
                'severity': 'info', 'fix': None,
            })

    # Check DNS-over-HTTPS
    doh = run_powershell(
        'Get-DnsClientDohServerAddress -ErrorAction SilentlyContinue | '
        'Select-Object ServerAddress, DohTemplate | Format-List'
    )
    if doh and 'dohtemplate' in doh.lower():
        findings.append({
            'name': 'DNS-over-HTTPS: Configured',
            'status': 'pass',
            'detail': 'DoH server addresses are configured.',
            'severity': 'ok', 'fix': None,
        })

    return findings

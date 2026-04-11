"""Listening services and port audit — cross-platform, professional grade."""

import re

from security.platform import PlatformInfo, is_unix
from security.runner import run, run_powershell


# Extended risky port map
RISKY_PORTS = {
    '21': ('FTP', 'high', 'FTP transmits credentials in cleartext.'),
    '23': ('Telnet', 'critical', 'Telnet is unencrypted. Use SSH instead.'),
    '25': ('SMTP', 'medium', 'SMTP relay could be abused for spam.'),
    '53': ('DNS', 'medium', 'DNS server exposed. Ensure it is intentional.'),
    '69': ('TFTP', 'high', 'TFTP has no authentication.'),
    '110': ('POP3', 'medium', 'POP3 transmits credentials in cleartext.'),
    '111': ('RPCBind', 'high', 'RPCBind can expose NFS and other services.'),
    '135': ('MSRPC', 'high', 'Microsoft RPC endpoint mapper.'),
    '139': ('NetBIOS', 'high', 'NetBIOS session service — common attack vector.'),
    '143': ('IMAP', 'medium', 'IMAP transmits credentials in cleartext.'),
    '161': ('SNMP', 'high', 'SNMP often uses default community strings.'),
    '445': ('SMB', 'high', 'SMB file sharing — frequent target for exploits.'),
    '512': ('rexec', 'critical', 'rexec has no encryption. Should be disabled.'),
    '513': ('rlogin', 'critical', 'rlogin is insecure. Use SSH instead.'),
    '514': ('rsh', 'critical', 'Remote shell is insecure.'),
    '1433': ('MSSQL', 'high', 'Microsoft SQL Server.'),
    '1521': ('Oracle DB', 'high', 'Oracle Database listener.'),
    '2049': ('NFS', 'high', 'NFS file sharing.'),
    '2375': ('Docker (unencrypted)', 'critical', 'Docker API without TLS — full host compromise.'),
    '2376': ('Docker (TLS)', 'medium', 'Docker API — verify TLS certificates.'),
    '2379': ('etcd', 'critical', 'etcd stores Kubernetes secrets.'),
    '3306': ('MySQL', 'high', 'MySQL database.'),
    '3389': ('RDP', 'high', 'Remote Desktop Protocol — brute-force target.'),
    '4444': ('Metasploit', 'critical', 'Common reverse shell / Metasploit handler port.'),
    '5432': ('PostgreSQL', 'high', 'PostgreSQL database.'),
    '5900': ('VNC', 'high', 'VNC remote desktop — often weakly secured.'),
    '5985': ('WinRM HTTP', 'high', 'Windows Remote Management (HTTP).'),
    '5986': ('WinRM HTTPS', 'medium', 'Windows Remote Management (HTTPS).'),
    '6379': ('Redis', 'high', 'Redis — often has no authentication by default.'),
    '6443': ('Kubernetes API', 'high', 'Kubernetes API server.'),
    '8080': ('HTTP Alt', 'medium', 'Alternative HTTP — may be admin panel or proxy.'),
    '8443': ('HTTPS Alt', 'low', 'Alternative HTTPS endpoint.'),
    '9090': ('Admin Panel', 'medium', 'Common admin/monitoring panel port.'),
    '9200': ('Elasticsearch', 'high', 'Elasticsearch — often no auth by default.'),
    '9300': ('Elasticsearch Transport', 'high', 'Elasticsearch cluster transport.'),
    '10250': ('Kubelet', 'critical', 'Kubelet API — can execute containers.'),
    '11211': ('Memcached', 'high', 'Memcached — no authentication.'),
    '27017': ('MongoDB', 'high', 'MongoDB — check authentication.'),
    '50070': ('HDFS NameNode', 'high', 'Hadoop HDFS web UI.'),
}


def check_services(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_services_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_services_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_services_windows(pinfo)
    elif pinfo.os_family in ('freebsd', 'openbsd', 'netbsd'):
        return _check_services_bsd(pinfo)
    return []


# ── Linux ───────────────────────────────────────────────────────────

def _check_services_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # TCP listeners
    tcp_raw = run(['ss', '-tlnp'])
    if not tcp_raw:
        tcp_raw = run(['netstat', '-tlnp'])

    # UDP listeners
    udp_raw = run(['ss', '-ulnp'])
    if not udp_raw:
        udp_raw = run(['netstat', '-ulnp'])

    tcp_listeners = _parse_ss_output(tcp_raw, 'TCP') if tcp_raw else []
    udp_listeners = _parse_ss_output(udp_raw, 'UDP') if udp_raw else []
    all_listeners = tcp_listeners + udp_listeners

    if all_listeners:
        findings.append({
            'name': f'Listening Services: {len(all_listeners)} ({len(tcp_listeners)} TCP, {len(udp_listeners)} UDP)',
            'status': 'info',
            'detail': '\n'.join(f'{l["proto"]:4} {l["addr"]:30} {l["process"]}'
                                for l in all_listeners[:25]),
            'severity': 'info', 'fix': None,
        })

        _check_risky_ports(all_listeners, findings)
        _check_wildcard_binds(all_listeners, findings)
    else:
        findings.append({
            'name': 'Listening Services',
            'status': 'unknown',
            'detail': 'Could not enumerate listening services.',
            'severity': 'info', 'fix': None,
        })

    return findings


def _parse_ss_output(raw: str, proto: str) -> list[dict]:
    """Parse ss or netstat output into structured listener info."""
    listeners = []
    for line in raw.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 4:
            continue
        addr = parts[3] if ':' in parts[3] else parts[4] if len(parts) > 4 else ''
        process = ''
        # ss puts process info in last column with users:((...))
        for p in parts:
            if 'users:' in p or p.startswith('"'):
                process = p
                break

        # Extract port from address
        port = ''
        if addr:
            port = addr.rsplit(':', 1)[-1] if ':' in addr else ''

        listeners.append({
            'proto': proto,
            'addr': addr,
            'port': port,
            'process': process,
            'is_wildcard': addr.startswith('0.0.0.0') or addr.startswith(':::') or addr.startswith('*:'),
        })
    return listeners


# ── macOS ───────────────────────────────────────────────────────────

def _check_services_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Use lsof for TCP
    tcp_raw = run(['lsof', '-iTCP', '-sTCP:LISTEN', '-P', '-n'], timeout=15)
    # Use lsof for UDP
    udp_raw = run(['lsof', '-iUDP', '-P', '-n'], timeout=15)

    listeners = []
    if tcp_raw:
        for line in tcp_raw.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 9:
                process = parts[0]
                addr = parts[8]
                port = addr.rsplit(':', 1)[-1] if ':' in addr else ''
                listeners.append({
                    'proto': 'TCP',
                    'addr': addr,
                    'port': port,
                    'process': process,
                    'is_wildcard': '*:' in addr,
                })

    if udp_raw:
        for line in udp_raw.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 9:
                process = parts[0]
                addr = parts[8]
                port = addr.rsplit(':', 1)[-1] if ':' in addr else ''
                listeners.append({
                    'proto': 'UDP',
                    'addr': addr,
                    'port': port,
                    'process': process,
                    'is_wildcard': '*:' in addr,
                })

    if listeners:
        findings.append({
            'name': f'Listening Services: {len(listeners)}',
            'status': 'info',
            'detail': '\n'.join(f'{l["proto"]:4} {l["addr"]:30} {l["process"]}'
                                for l in listeners[:25]),
            'severity': 'info', 'fix': None,
        })
        _check_risky_ports(listeners, findings)
        _check_wildcard_binds(listeners, findings)
    else:
        # Fallback to netstat
        ns = run(['netstat', '-an', '-p', 'tcp'])
        if ns:
            listen_lines = [l for l in ns.splitlines() if 'LISTEN' in l]
            findings.append({
                'name': f'Listening TCP Ports: {len(listen_lines)}',
                'status': 'info',
                'detail': '\n'.join(listen_lines[:20]),
                'severity': 'info', 'fix': None,
            })

    return findings


# ── Windows ─────────────────────────────────────────────────────────

def _check_services_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    result = run_powershell(
        'Get-NetTCPConnection -State Listen | '
        'Select-Object LocalAddress, LocalPort, OwningProcess | '
        'Sort-Object LocalPort | Format-Table -AutoSize',
        timeout=15,
    )
    if not result:
        result = run(['netstat', '-ano'], timeout=10)

    listeners = []
    if result:
        for line in result.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    port = str(int(parts[1]))
                    addr = parts[0]
                    pid = parts[2] if len(parts) > 2 else ''
                    listeners.append({
                        'proto': 'TCP',
                        'addr': f'{addr}:{port}',
                        'port': port,
                        'process': f'PID {pid}',
                        'is_wildcard': addr in ('0.0.0.0', '::'),
                    })
                except (ValueError, IndexError):
                    continue

    if listeners:
        findings.append({
            'name': f'Listening Services: {len(listeners)}',
            'status': 'info',
            'detail': '\n'.join(f'{l["addr"]:30} {l["process"]}' for l in listeners[:25]),
            'severity': 'info', 'fix': None,
        })
        _check_risky_ports(listeners, findings)
        _check_wildcard_binds(listeners, findings)

    return findings


# ── BSD ─────────────────────────────────────────────────────────────

def _check_services_bsd(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    raw = run(['sockstat', '-l'])
    if not raw:
        raw = run(['netstat', '-an'])

    if raw:
        listen_lines = [l for l in raw.splitlines() if 'LISTEN' in l or 'tcp' in l.lower()]
        findings.append({
            'name': f'Listening Services: {len(listen_lines)}',
            'status': 'info',
            'detail': '\n'.join(listen_lines[:20]),
            'severity': 'info', 'fix': None,
        })

    return findings


# ── Shared analysis ─────────────────────────────────────────────────

def _check_risky_ports(listeners: list, findings: list):
    """Flag known-risky ports that are listening."""
    seen = set()
    for l in listeners:
        port = l.get('port', '')
        if port in RISKY_PORTS and port not in seen:
            seen.add(port)
            name, severity, desc = RISKY_PORTS[port]
            if l['is_wildcard']:
                findings.append({
                    'name': f'{name} (port {port}): Exposed on All Interfaces',
                    'status': 'fail',
                    'detail': f'{desc} Listening on {l["addr"]} ({l["process"]}).',
                    'severity': severity,
                    'fix': f'Bind {name} to 127.0.0.1 only, or restrict with firewall rules.',
                })
            else:
                findings.append({
                    'name': f'{name} (port {port}): Listening',
                    'status': 'info',
                    'detail': f'{desc} Bound to {l["addr"]} ({l["process"]}).',
                    'severity': 'low', 'fix': None,
                })


def _check_wildcard_binds(listeners: list, findings: list):
    """Count services on wildcard addresses."""
    wildcard = [l for l in listeners if l['is_wildcard']]
    if len(wildcard) > 5:
        findings.append({
            'name': f'Wildcard Listeners: {len(wildcard)} services on 0.0.0.0/::',
            'status': 'warn',
            'detail': 'Many services are bound to all interfaces. Consider binding to localhost where possible.',
            'severity': 'medium',
            'fix': 'Review each service configuration and bind to 127.0.0.1 if external access is not needed.',
        })

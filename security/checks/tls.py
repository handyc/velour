"""TLS/SSL configuration audit — cross-platform."""

import re

from security.platform import PlatformInfo, is_unix
from security.runner import run, read_file


def check_tls(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    if not is_unix(pinfo) and pinfo.os_family != 'windows':
        return []

    # OpenSSL version check
    ssl_ver = run(['openssl', 'version'])
    if ssl_ver:
        findings.append({
            'name': f'OpenSSL Version: {ssl_ver}',
            'status': 'info',
            'detail': ssl_ver,
            'severity': 'info', 'fix': None,
        })

        # Check for known-vulnerable versions
        version_match = re.search(r'(\d+\.\d+\.\d+)', ssl_ver)
        if version_match:
            ver = version_match.group(1)
            major, minor, patch = [int(x) for x in ver.split('.')]
            if major < 1 or (major == 1 and minor == 0):
                findings.append({
                    'name': 'OpenSSL: Critically Outdated',
                    'status': 'fail',
                    'detail': f'OpenSSL {ver} has known vulnerabilities (e.g., Heartbleed for 1.0.1).',
                    'severity': 'critical',
                    'fix': 'Upgrade OpenSSL to 1.1.1+ or 3.x.',
                })
            elif major == 1 and minor == 1 and patch < 1:
                findings.append({
                    'name': 'OpenSSL: Outdated',
                    'status': 'warn',
                    'detail': f'OpenSSL {ver} is outdated. Upgrade recommended.',
                    'severity': 'medium',
                    'fix': 'Upgrade OpenSSL to latest 1.1.1 or 3.x release.',
                })

    # Check system-wide crypto policy (RHEL/Fedora)
    crypto_policy = read_file('/etc/crypto-policies/config')
    if crypto_policy:
        policy = crypto_policy.strip()
        if policy == 'LEGACY':
            findings.append({
                'name': 'Crypto Policy: LEGACY',
                'status': 'fail',
                'detail': 'System-wide crypto policy is set to LEGACY, allowing weak algorithms.',
                'severity': 'high',
                'fix': 'update-crypto-policies --set DEFAULT',
            })
        else:
            findings.append({
                'name': f'Crypto Policy: {policy}',
                'status': 'pass',
                'detail': f'System crypto policy: {policy}',
                'severity': 'ok', 'fix': None,
            })

    # Check for expired/self-signed certs in common locations
    cert_dirs = ['/etc/ssl/certs', '/etc/pki/tls/certs']
    for cert_dir in cert_dirs:
        expired = run(
            f'find {cert_dir} -name "*.pem" -o -name "*.crt" 2>/dev/null '
            f'| head -20 '
            f'| xargs -I{{}} openssl x509 -checkend 0 -noout -in {{}} 2>/dev/null '
            f'| grep -c "will expire"',
            shell=True, timeout=15,
        )
        if expired and expired.strip() != '0':
            findings.append({
                'name': f'Expired Certificates in {cert_dir}',
                'status': 'warn',
                'detail': f'{expired.strip()} expired certificate(s) found.',
                'severity': 'medium',
                'fix': f'Review and renew expired certificates in {cert_dir}.',
            })

    # CA bundle presence
    ca_bundles = [
        '/etc/ssl/certs/ca-certificates.crt',
        '/etc/pki/tls/certs/ca-bundle.crt',
        '/etc/ssl/cert.pem',
        '/usr/local/etc/ssl/cert.pem',
    ]
    found = False
    for bundle in ca_bundles:
        content = read_file(bundle)
        if content and 'BEGIN CERTIFICATE' in content:
            found = True
            break
    if not found and pinfo.os_family != 'windows':
        findings.append({
            'name': 'CA Certificate Bundle',
            'status': 'warn',
            'detail': 'System CA certificate bundle not found in standard locations.',
            'severity': 'medium', 'fix': None,
        })

    return findings

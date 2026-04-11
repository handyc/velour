"""Password policy audit — cross-platform."""

import re

from security.platform import PlatformInfo, is_debian_family, is_rhel_family
from security.runner import run, run_powershell, read_file


def check_password_policy(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_pw_linux(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_pw_macos(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_pw_windows(pinfo)
    return []


def _check_pw_linux(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # /etc/login.defs
    login_defs = read_file('/etc/login.defs')
    if login_defs:
        checks = {
            'PASS_MAX_DAYS': ('90', 'Maximum password age', 'high'),
            'PASS_MIN_DAYS': ('1', 'Minimum password age', 'low'),
            'PASS_MIN_LEN': ('8', 'Minimum password length', 'medium'),
            'PASS_WARN_AGE': ('7', 'Password expiry warning days', 'low'),
        }
        for key, (recommended, desc, severity) in checks.items():
            match = re.search(rf'^{key}\s+(\d+)', login_defs, re.MULTILINE)
            if match:
                val = match.group(1)
                if key == 'PASS_MAX_DAYS' and int(val) > 365:
                    findings.append({
                        'name': f'Password Policy: {desc}',
                        'status': 'warn',
                        'detail': f'{key} = {val} (recommended: ≤{recommended}).',
                        'severity': severity,
                        'fix': f'Set {key} {recommended} in /etc/login.defs.',
                    })
                elif key == 'PASS_MIN_LEN' and int(val) < 8:
                    findings.append({
                        'name': f'Password Policy: {desc}',
                        'status': 'warn',
                        'detail': f'{key} = {val} (recommended: ≥{recommended}).',
                        'severity': severity,
                        'fix': f'Set {key} {recommended} in /etc/login.defs.',
                    })
                else:
                    findings.append({
                        'name': f'Password Policy: {desc}',
                        'status': 'pass',
                        'detail': f'{key} = {val}',
                        'severity': 'ok', 'fix': None,
                    })

    # PAM password quality
    pam_paths = [
        '/etc/pam.d/common-password',      # Debian/Ubuntu
        '/etc/pam.d/system-auth',           # RHEL/CentOS
        '/etc/pam.d/passwd',                # Some distros
    ]
    pam_content = None
    for path in pam_paths:
        pam_content = read_file(path)
        if pam_content:
            break

    if pam_content:
        if 'pam_pwquality' in pam_content or 'pam_cracklib' in pam_content:
            findings.append({
                'name': 'PAM Password Quality',
                'status': 'pass',
                'detail': 'Password quality module (pam_pwquality or pam_cracklib) is configured.',
                'severity': 'ok', 'fix': None,
            })
            # Check for specific settings
            minlen = re.search(r'minlen=(\d+)', pam_content)
            if minlen:
                length = int(minlen.group(1))
                if length < 8:
                    findings.append({
                        'name': 'PAM: Minimum Password Length',
                        'status': 'warn',
                        'detail': f'minlen = {length}. Recommend at least 12.',
                        'severity': 'medium',
                        'fix': 'Set minlen=12 in pam_pwquality configuration.',
                    })
        else:
            findings.append({
                'name': 'PAM Password Quality: Not Configured',
                'status': 'warn',
                'detail': 'No password quality enforcement module found in PAM config.',
                'severity': 'medium',
                'fix': 'Install and configure pam_pwquality.',
            })

    return findings


def _check_pw_macos(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check password policy
    pw_policy = run(['pwpolicy', 'getaccountpolicies'])
    if pw_policy:
        if 'policyAttributeMinimumLength' in pw_policy:
            min_len = re.search(r'policyAttributeMinimumLength.*?(\d+)', pw_policy)
            if min_len:
                findings.append({
                    'name': f'Password Policy: Min Length = {min_len.group(1)}',
                    'status': 'pass' if int(min_len.group(1)) >= 8 else 'warn',
                    'detail': f'Minimum password length: {min_len.group(1)}',
                    'severity': 'ok' if int(min_len.group(1)) >= 8 else 'medium',
                    'fix': 'Configure via MDM or pwpolicy.',
                })
        findings.append({
            'name': 'Password Policy: Configured',
            'status': 'pass',
            'detail': 'Account password policies are in place.',
            'severity': 'ok', 'fix': None,
        })
    else:
        findings.append({
            'name': 'Password Policy',
            'status': 'info',
            'detail': 'Could not retrieve password policy. May require MDM for enforcement.',
            'severity': 'info', 'fix': None,
        })

    # Screen saver lock
    ss = run(['defaults', '-currentHost', 'read', 'com.apple.screensaver', 'askForPassword'])
    if ss and ss.strip() == '0':
        findings.append({
            'name': 'Screen Lock: Not Required',
            'status': 'warn',
            'detail': 'Password is not required after screen saver activates.',
            'severity': 'medium',
            'fix': 'System Settings → Lock Screen → Require password after screen saver begins.',
        })

    return findings


def _check_pw_windows(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    net_accounts = run(['net', 'accounts'])
    if net_accounts:
        for line in net_accounts.splitlines():
            line_lower = line.lower()
            parts = line.split(':')
            if len(parts) < 2:
                continue
            val = parts[-1].strip()

            if 'minimum password length' in line_lower:
                try:
                    length = int(val)
                    if length < 8:
                        findings.append({
                            'name': f'Password Policy: Min Length = {length}',
                            'status': 'fail',
                            'detail': f'Minimum password length is {length}. Recommend 12+.',
                            'severity': 'high',
                            'fix': 'net accounts /minpwlen:12',
                        })
                    else:
                        findings.append({
                            'name': f'Password Policy: Min Length = {length}',
                            'status': 'pass',
                            'detail': f'Minimum password length: {length}',
                            'severity': 'ok', 'fix': None,
                        })
                except ValueError:
                    pass

            elif 'maximum password age' in line_lower:
                if val.lower() == 'unlimited':
                    findings.append({
                        'name': 'Password Policy: No Expiration',
                        'status': 'warn',
                        'detail': 'Passwords never expire.',
                        'severity': 'medium',
                        'fix': 'net accounts /maxpwage:90',
                    })

            elif 'password history' in line_lower:
                try:
                    history = int(val)
                    if history < 5:
                        findings.append({
                            'name': f'Password History: {history}',
                            'status': 'warn',
                            'detail': f'Only {history} passwords remembered. Recommend 10+.',
                            'severity': 'low',
                            'fix': 'net accounts /uniquepw:10',
                        })
                except ValueError:
                    pass

    # Complexity requirements
    complexity = run_powershell(
        '(Get-ADDefaultDomainPasswordPolicy -ErrorAction SilentlyContinue).ComplexityEnabled'
    )
    if complexity:
        if 'true' in complexity.lower():
            findings.append({
                'name': 'Password Complexity: Enabled',
                'status': 'pass',
                'detail': 'Password complexity requirements are enabled.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Password Complexity: Disabled',
                'status': 'fail',
                'detail': 'Password complexity requirements are not enforced.',
                'severity': 'high',
                'fix': 'Enable via Group Policy: Computer Configuration → Policies → Windows Settings → '
                       'Security Settings → Account Policies → Password Policy.',
            })

    return findings

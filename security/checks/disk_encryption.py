"""Disk encryption audit — cross-platform."""

from security.platform import PlatformInfo
from security.runner import run, run_powershell


def check_disk_encryption(pinfo: PlatformInfo) -> list[dict]:
    if pinfo.os_family == 'linux':
        return _check_luks(pinfo)
    elif pinfo.os_family == 'darwin':
        return _check_filevault(pinfo)
    elif pinfo.os_family == 'windows':
        return _check_bitlocker(pinfo)
    return []


def _check_luks(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Check for LUKS/dm-crypt
    lsblk = run(['lsblk', '-o', 'NAME,FSTYPE,TYPE,MOUNTPOINT', '--noheadings'])
    if lsblk:
        has_crypt = any('crypt' in line.lower() for line in lsblk.splitlines())
        if has_crypt:
            findings.append({
                'name': 'Disk Encryption: LUKS/dm-crypt Active',
                'status': 'pass',
                'detail': 'Encrypted volumes detected.',
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'Disk Encryption: Not Detected',
                'status': 'warn',
                'detail': 'No LUKS/dm-crypt encrypted volumes found. Data at rest is not encrypted.',
                'severity': 'medium',
                'fix': 'Consider encrypting disk partitions with LUKS during OS installation.',
            })
    else:
        findings.append({
            'name': 'Disk Encryption',
            'status': 'unknown',
            'detail': 'Could not determine disk encryption status.',
            'severity': 'info', 'fix': None,
        })

    # Check swap encryption
    swap_info = run(['swapon', '--show=NAME,TYPE', '--noheadings'])
    if swap_info:
        for line in swap_info.splitlines():
            if 'partition' in line.lower() or 'file' in line.lower():
                # Check if swap device is on an encrypted volume
                swap_dev = line.split()[0]
                dmsetup = run(['dmsetup', 'info', swap_dev])
                if not dmsetup or 'does not exist' in str(dmsetup):
                    findings.append({
                        'name': 'Swap: Not Encrypted',
                        'status': 'warn',
                        'detail': f'Swap at {swap_dev} does not appear to be on an encrypted volume.',
                        'severity': 'medium',
                        'fix': 'Use encrypted swap or disable swap if not needed.',
                    })

    return findings


def _check_filevault(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    fv_status = run(['fdesetup', 'status'])
    if fv_status:
        if 'on' in fv_status.lower():
            findings.append({
                'name': 'FileVault: Enabled',
                'status': 'pass',
                'detail': fv_status.strip(),
                'severity': 'ok', 'fix': None,
            })
        else:
            findings.append({
                'name': 'FileVault: Disabled',
                'status': 'fail',
                'detail': 'FileVault disk encryption is not enabled.',
                'severity': 'high',
                'fix': 'System Settings → Privacy & Security → FileVault → Turn On.',
            })
    else:
        findings.append({
            'name': 'FileVault',
            'status': 'unknown',
            'detail': 'Could not determine FileVault status.',
            'severity': 'info', 'fix': None,
        })

    return findings


def _check_bitlocker(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    bl_status = run_powershell(
        'Get-BitLockerVolume | Select-Object MountPoint, VolumeStatus, '
        'ProtectionStatus, EncryptionPercentage | Format-List'
    )
    if bl_status:
        if 'fullyencrypted' in bl_status.lower().replace(' ', ''):
            findings.append({
                'name': 'BitLocker: Enabled',
                'status': 'pass',
                'detail': bl_status.strip()[:300],
                'severity': 'ok', 'fix': None,
            })
        elif 'protectionoff' in bl_status.lower().replace(' ', ''):
            findings.append({
                'name': 'BitLocker: Protection Off',
                'status': 'fail',
                'detail': 'BitLocker protection is suspended or off.',
                'severity': 'high',
                'fix': 'Resume-BitLockerProtection -MountPoint "C:"',
            })
        else:
            findings.append({
                'name': 'BitLocker Status',
                'status': 'info',
                'detail': bl_status.strip()[:300],
                'severity': 'info', 'fix': None,
            })
    else:
        # Fallback to manage-bde
        bde = run(['manage-bde', '-status'])
        if bde:
            if 'fully encrypted' in bde.lower():
                findings.append({
                    'name': 'BitLocker: Enabled',
                    'status': 'pass',
                    'detail': 'System drive is fully encrypted.',
                    'severity': 'ok', 'fix': None,
                })
            else:
                findings.append({
                    'name': 'BitLocker: Not Fully Encrypted',
                    'status': 'warn',
                    'detail': 'BitLocker may not be fully configured.',
                    'severity': 'medium',
                    'fix': 'Enable BitLocker via Control Panel or manage-bde.',
                })
        else:
            findings.append({
                'name': 'Disk Encryption',
                'status': 'unknown',
                'detail': 'Could not determine BitLocker status.',
                'severity': 'info', 'fix': None,
            })

    return findings

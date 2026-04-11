"""
Platform detection for cross-platform security auditing.

Detects OS family, distribution, package manager, init system,
and environment details (container, WSL).
"""

import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlatformInfo:
    os_family: str = ''          # 'linux', 'darwin', 'windows', 'freebsd', 'openbsd', 'netbsd'
    distro: str = ''             # 'ubuntu', 'debian', 'rhel', 'centos', 'fedora', 'arch', 'alpine', 'suse', ''
    distro_version: str = ''     # e.g. '22.04', '9.3', ''
    distro_name: str = ''        # Pretty name e.g. 'Ubuntu 22.04 LTS'
    pkg_manager: str = ''        # 'apt', 'yum', 'dnf', 'brew', 'pacman', 'apk', 'pkg', 'zypper', ''
    init_system: str = ''        # 'systemd', 'launchd', 'openrc', 'sysvinit', 'windows_scm', ''
    is_container: bool = False
    is_wsl: bool = False
    arch: str = ''               # 'x86_64', 'arm64', etc.
    kernel_version: str = ''


_cached_platform: Optional[PlatformInfo] = None


def detect_platform() -> PlatformInfo:
    """Detect the current platform. Result is cached after first call."""
    global _cached_platform
    if _cached_platform is not None:
        return _cached_platform

    info = PlatformInfo()
    system = platform.system().lower()
    info.arch = platform.machine()
    info.kernel_version = platform.release()

    if system == 'linux':
        info.os_family = 'linux'
        _detect_linux(info)
    elif system == 'darwin':
        info.os_family = 'darwin'
        _detect_darwin(info)
    elif system == 'windows':
        info.os_family = 'windows'
        _detect_windows(info)
    elif system == 'freebsd':
        info.os_family = 'freebsd'
        _detect_bsd(info)
    elif system == 'openbsd':
        info.os_family = 'openbsd'
        _detect_bsd(info)
    elif system == 'netbsd':
        info.os_family = 'netbsd'
        _detect_bsd(info)
    else:
        info.os_family = system

    _cached_platform = info
    return info


def _detect_linux(info: PlatformInfo):
    """Detect Linux distribution, package manager, init system, container/WSL."""
    # Parse /etc/os-release (present on all modern distros)
    os_release = _read_os_release()
    if os_release:
        raw_id = os_release.get('ID', '').lower()
        id_like = os_release.get('ID_LIKE', '').lower()
        info.distro_version = os_release.get('VERSION_ID', '')
        info.distro_name = os_release.get('PRETTY_NAME', '')

        # Normalize distro ID
        if raw_id in ('ubuntu', 'pop', 'linuxmint', 'elementary', 'zorin'):
            info.distro = 'ubuntu' if raw_id == 'ubuntu' else raw_id
            if 'debian' in id_like or 'ubuntu' in id_like:
                info.pkg_manager = 'apt'
        elif raw_id in ('debian', 'raspbian', 'kali'):
            info.distro = raw_id
            info.pkg_manager = 'apt'
        elif raw_id in ('rhel', 'redhat'):
            info.distro = 'rhel'
            info.pkg_manager = _rhel_pkg_manager(info.distro_version)
        elif raw_id == 'centos':
            info.distro = 'centos'
            info.pkg_manager = _rhel_pkg_manager(info.distro_version)
        elif raw_id in ('fedora',):
            info.distro = 'fedora'
            info.pkg_manager = 'dnf'
        elif raw_id in ('rocky', 'almalinux', 'ol', 'oracle'):
            info.distro = raw_id
            info.pkg_manager = _rhel_pkg_manager(info.distro_version)
        elif raw_id == 'arch' or raw_id == 'manjaro':
            info.distro = raw_id
            info.pkg_manager = 'pacman'
        elif raw_id == 'alpine':
            info.distro = 'alpine'
            info.pkg_manager = 'apk'
        elif raw_id in ('opensuse-leap', 'opensuse-tumbleweed', 'sles', 'suse'):
            info.distro = 'suse'
            info.pkg_manager = 'zypper'
        elif raw_id == 'gentoo':
            info.distro = 'gentoo'
            info.pkg_manager = 'emerge'
        elif raw_id == 'void':
            info.distro = 'void'
            info.pkg_manager = 'xbps'
        else:
            info.distro = raw_id
            # Try to infer from ID_LIKE
            if 'debian' in id_like or 'ubuntu' in id_like:
                info.pkg_manager = 'apt'
            elif 'rhel' in id_like or 'fedora' in id_like or 'centos' in id_like:
                info.pkg_manager = _rhel_pkg_manager(info.distro_version)
            elif 'arch' in id_like:
                info.pkg_manager = 'pacman'
            elif 'suse' in id_like:
                info.pkg_manager = 'zypper'
    else:
        # Fallback detection
        if os.path.isfile('/etc/debian_version'):
            info.distro = 'debian'
            info.pkg_manager = 'apt'
        elif os.path.isfile('/etc/redhat-release'):
            info.distro = 'rhel'
            info.pkg_manager = 'yum'
        elif os.path.isfile('/etc/alpine-release'):
            info.distro = 'alpine'
            info.pkg_manager = 'apk'
        elif os.path.isfile('/etc/arch-release'):
            info.distro = 'arch'
            info.pkg_manager = 'pacman'

    # Init system
    if os.path.isdir('/run/systemd/system'):
        info.init_system = 'systemd'
    elif os.path.isfile('/sbin/openrc'):
        info.init_system = 'openrc'
    elif os.path.isfile('/sbin/init'):
        info.init_system = 'sysvinit'

    # Container detection
    info.is_container = (
        os.path.isfile('/.dockerenv')
        or os.path.isfile('/run/.containerenv')
        or _cgroup_indicates_container()
    )

    # WSL detection
    try:
        with open('/proc/version', 'r') as f:
            proc_ver = f.read().lower()
        info.is_wsl = 'microsoft' in proc_ver or 'wsl' in proc_ver
    except (FileNotFoundError, PermissionError):
        pass


def _detect_darwin(info: PlatformInfo):
    """Detect macOS details."""
    mac_ver = platform.mac_ver()
    info.distro = 'macos'
    info.distro_version = mac_ver[0] if mac_ver[0] else ''
    info.distro_name = f'macOS {info.distro_version}'
    info.pkg_manager = 'brew' if _command_exists('brew') else ''
    info.init_system = 'launchd'


def _detect_windows(info: PlatformInfo):
    """Detect Windows details."""
    win_ver = platform.win32_ver()
    info.distro = 'windows'
    info.distro_version = win_ver[1] if len(win_ver) > 1 else ''
    info.distro_name = f'Windows {win_ver[0]}' if win_ver[0] else 'Windows'
    info.init_system = 'windows_scm'


def _detect_bsd(info: PlatformInfo):
    """Detect BSD variant details."""
    info.distro = info.os_family
    info.distro_version = platform.release()
    info.distro_name = f'{info.os_family.capitalize()} {info.distro_version}'
    if info.os_family == 'freebsd':
        info.pkg_manager = 'pkg'
    elif info.os_family == 'openbsd':
        info.pkg_manager = 'pkg_add'


def _read_os_release() -> dict:
    """Parse /etc/os-release into a dict."""
    result = {}
    for path in ('/etc/os-release', '/usr/lib/os-release'):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, _, val = line.partition('=')
                        result[key] = val.strip('"').strip("'")
            return result
        except (FileNotFoundError, PermissionError):
            continue
    return result


def _rhel_pkg_manager(version: str) -> str:
    """Return yum or dnf based on RHEL version."""
    try:
        major = int(version.split('.')[0])
        return 'dnf' if major >= 8 else 'yum'
    except (ValueError, IndexError):
        return 'dnf'


def _cgroup_indicates_container() -> bool:
    """Check if cgroup info suggests we're in a container."""
    try:
        with open('/proc/1/cgroup', 'r') as f:
            content = f.read()
        return 'docker' in content or 'lxc' in content or 'kubepods' in content
    except (FileNotFoundError, PermissionError):
        return False


def _command_exists(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    try:
        subprocess.check_output(['which', cmd], stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:
        return False


def is_debian_family(info: PlatformInfo) -> bool:
    """Check if platform is Debian/Ubuntu family."""
    return info.pkg_manager == 'apt'


def is_rhel_family(info: PlatformInfo) -> bool:
    """Check if platform is RHEL/CentOS/Fedora family."""
    return info.pkg_manager in ('yum', 'dnf')


def is_unix(info: PlatformInfo) -> bool:
    """Check if platform is any Unix-like system."""
    return info.os_family in ('linux', 'darwin', 'freebsd', 'openbsd', 'netbsd')

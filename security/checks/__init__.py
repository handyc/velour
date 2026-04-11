"""
Security check registry.

Each check is a dict with:
    id       — URL-safe anchor identifier
    name     — Human-readable display name
    desc     — Short description for the home page card
    fn       — Callable(PlatformInfo) -> list[dict]
    category — Grouping category
    action   — Button label on the home card
"""

from .ssh import check_ssh
from .firewall import check_firewall
from .intrusion import check_intrusion_prevention
from .users import check_users
from .services import check_services
from .filesystem import check_filesystem
from .updates import check_updates
from .auth_logs import check_auth_logs
from .kernel import check_kernel
from .password_policy import check_password_policy
from .mac_policy import check_mac_policy
from .audit_framework import check_audit_framework
from .tls import check_tls
from .disk_encryption import check_disk_encryption
from .containers import check_containers
from .scheduled_tasks import check_scheduled_tasks
from .suid_sgid import check_suid_sgid
from .world_writable import check_world_writable
from .dns import check_dns
from .ntp import check_ntp


CHECK_REGISTRY = [
    # ── Access Control ──────────────────────────────────────────
    {
        'id': 'ssh', 'name': 'SSH Hardening',
        'desc': 'Root login, password auth, port, ciphers, key exchange.',
        'fn': check_ssh, 'category': 'Access Control', 'action': 'Check',
    },
    {
        'id': 'users', 'name': 'User Accounts',
        'desc': 'UID-0 accounts, login shells, empty passwords, sudoers.',
        'fn': check_users, 'category': 'Access Control', 'action': 'Audit',
    },
    {
        'id': 'password', 'name': 'Password Policy',
        'desc': 'Password aging, complexity, PAM quality modules.',
        'fn': check_password_policy, 'category': 'Access Control', 'action': 'Check',
    },
    # ── Network Security ────────────────────────────────────────
    {
        'id': 'firewall', 'name': 'Firewall',
        'desc': 'UFW, firewalld, pf, nftables, or Windows Firewall.',
        'fn': check_firewall, 'category': 'Network', 'action': 'Check',
    },
    {
        'id': 'services', 'name': 'Open Ports & Services',
        'desc': 'Listening TCP/UDP, risky ports, wildcard binds.',
        'fn': check_services, 'category': 'Network', 'action': 'Scan',
    },
    {
        'id': 'tls', 'name': 'TLS / SSL',
        'desc': 'OpenSSL version, crypto policy, certificate health.',
        'fn': check_tls, 'category': 'Network', 'action': 'Check',
    },
    {
        'id': 'dns', 'name': 'DNS Security',
        'desc': 'Resolvers, DNSSEC validation, DNS-over-TLS.',
        'fn': check_dns, 'category': 'Network', 'action': 'Check',
    },
    # ── System Hardening ────────────────────────────────────────
    {
        'id': 'kernel', 'name': 'Kernel Hardening',
        'desc': 'ASLR, sysctl parameters, DEP, Secure Boot.',
        'fn': check_kernel, 'category': 'System', 'action': 'Check',
    },
    {
        'id': 'filesystem', 'name': 'File Permissions',
        'desc': 'Sensitive files, SIP, Gatekeeper, UAC, home dirs.',
        'fn': check_filesystem, 'category': 'System', 'action': 'Check',
    },
    {
        'id': 'suid', 'name': 'SUID / SGID Binaries',
        'desc': 'Scan for unexpected setuid/setgid executables.',
        'fn': check_suid_sgid, 'category': 'System', 'action': 'Scan',
    },
    {
        'id': 'worldwrite', 'name': 'World-Writable Files',
        'desc': 'Files and directories writable by any user.',
        'fn': check_world_writable, 'category': 'System', 'action': 'Scan',
    },
    {
        'id': 'encryption', 'name': 'Disk Encryption',
        'desc': 'LUKS, FileVault, BitLocker — data at rest.',
        'fn': check_disk_encryption, 'category': 'System', 'action': 'Check',
    },
    {
        'id': 'updates', 'name': 'System Updates',
        'desc': 'Pending patches, auto-update configuration.',
        'fn': check_updates, 'category': 'System', 'action': 'Check',
    },
    {
        'id': 'ntp', 'name': 'Time Sync (NTP)',
        'desc': 'Clock synchronization — critical for logs and TLS.',
        'fn': check_ntp, 'category': 'System', 'action': 'Check',
    },
    # ── Policy & Compliance ─────────────────────────────────────
    {
        'id': 'mac', 'name': 'Mandatory Access Control',
        'desc': 'SELinux, AppArmor, SIP, or AppLocker.',
        'fn': check_mac_policy, 'category': 'Policy', 'action': 'Check',
    },
    {
        'id': 'audit', 'name': 'Audit Framework',
        'desc': 'auditd, OpenBSM, or Windows audit policy.',
        'fn': check_audit_framework, 'category': 'Policy', 'action': 'Check',
    },
    # ── Monitoring & Defense ────────────────────────────────────
    {
        'id': 'intrusion', 'name': 'Intrusion Prevention',
        'desc': 'Fail2ban, CrowdSec, Defender, XProtect.',
        'fn': check_intrusion_prevention, 'category': 'Monitoring', 'action': 'Check',
    },
    {
        'id': 'auth', 'name': 'Auth Logs',
        'desc': 'Failed logins, top offending IPs, brute-force detection.',
        'fn': check_auth_logs, 'category': 'Monitoring', 'action': 'Analyze',
    },
    # ── Infrastructure ──────────────────────────────────────────
    {
        'id': 'containers', 'name': 'Container Security',
        'desc': 'Docker daemon, privileged containers, Kubernetes.',
        'fn': check_containers, 'category': 'Infrastructure', 'action': 'Check',
    },
    {
        'id': 'scheduled', 'name': 'Scheduled Tasks',
        'desc': 'Cron jobs, LaunchDaemons, Windows Task Scheduler.',
        'fn': check_scheduled_tasks, 'category': 'Infrastructure', 'action': 'Audit',
    },
]

# Category ordering for template rendering
CATEGORIES = [
    'Access Control',
    'Network',
    'System',
    'Policy',
    'Monitoring',
    'Infrastructure',
]

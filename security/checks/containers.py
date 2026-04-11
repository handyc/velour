"""Container security audit."""

import os

from security.platform import PlatformInfo
from security.runner import run, read_file, command_exists


def check_containers(pinfo: PlatformInfo) -> list[dict]:
    findings = []

    # Are we inside a container?
    if pinfo.is_container:
        findings.append({
            'name': 'Running Inside Container',
            'status': 'info',
            'detail': 'This system is running inside a container.',
            'severity': 'info', 'fix': None,
        })

        # Check if running as root inside container
        if os.getuid() == 0:
            findings.append({
                'name': 'Container: Running as Root',
                'status': 'warn',
                'detail': 'Process is running as root inside the container.',
                'severity': 'medium',
                'fix': 'Use a non-root USER in your Dockerfile.',
            })

        # Check if privileged
        cap_text = read_file('/proc/1/status')
        if cap_text:
            for line in cap_text.splitlines():
                if line.startswith('CapEff:'):
                    cap_val = int(line.split(':')[1].strip(), 16)
                    if cap_val == 0x3fffffffff or cap_val == 0x1ffffffffff:
                        findings.append({
                            'name': 'Container: Privileged Mode',
                            'status': 'fail',
                            'detail': 'Container is running in privileged mode with all capabilities.',
                            'severity': 'critical',
                            'fix': 'Remove --privileged flag. Use specific --cap-add flags instead.',
                        })

    # Check Docker installation on host
    if command_exists('docker') and not pinfo.is_container:
        _check_docker_host(findings)

    # Check Kubernetes
    if command_exists('kubectl') and not pinfo.is_container:
        _check_kubernetes(findings)

    return findings


def _check_docker_host(findings):
    """Check Docker daemon security on the host."""
    # Docker version
    ver = run(['docker', 'version', '--format', '{{.Server.Version}}'])
    if ver:
        findings.append({
            'name': f'Docker: Version {ver}',
            'status': 'info',
            'detail': f'Docker Engine {ver}',
            'severity': 'info', 'fix': None,
        })

    # Docker socket permissions
    socket_path = '/var/run/docker.sock'
    if os.path.exists(socket_path):
        try:
            mode = oct(os.stat(socket_path).st_mode)[-4:]
            if int(mode, 8) > int('0660', 8):
                findings.append({
                    'name': 'Docker Socket: Overly Permissive',
                    'status': 'warn',
                    'detail': f'Docker socket permissions: {mode}. Should be 0660 or stricter.',
                    'severity': 'high',
                    'fix': 'chmod 660 /var/run/docker.sock',
                })
        except PermissionError:
            pass

    # Docker daemon configuration
    daemon_config = read_file('/etc/docker/daemon.json')
    if daemon_config:
        import json
        try:
            config = json.loads(daemon_config)
            # Check for insecure registries
            if config.get('insecure-registries'):
                findings.append({
                    'name': 'Docker: Insecure Registries',
                    'status': 'warn',
                    'detail': f'Insecure registries configured: {config["insecure-registries"]}',
                    'severity': 'medium',
                    'fix': 'Use TLS for all container registries.',
                })
            # Check userns-remap
            if not config.get('userns-remap'):
                findings.append({
                    'name': 'Docker: No User Namespace Remapping',
                    'status': 'info',
                    'detail': 'User namespace remapping is not configured.',
                    'severity': 'low',
                    'fix': 'Consider adding "userns-remap": "default" to /etc/docker/daemon.json.',
                })
            # Check live-restore
            if not config.get('live-restore'):
                findings.append({
                    'name': 'Docker: Live Restore Disabled',
                    'status': 'info',
                    'detail': 'Live restore not enabled. Containers will stop on daemon restart.',
                    'severity': 'low',
                    'fix': 'Add "live-restore": true to /etc/docker/daemon.json.',
                })
        except (json.JSONDecodeError, TypeError):
            pass

    # Check for privileged containers running
    ps_out = run(['docker', 'ps', '--format', '{{.Names}} {{.ID}}'], timeout=10)
    if ps_out:
        for line in ps_out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                container_id = parts[1]
                inspect = run(['docker', 'inspect', '--format',
                               '{{.HostConfig.Privileged}}', container_id])
                if inspect and inspect.strip() == 'true':
                    findings.append({
                        'name': f'Docker: Privileged Container "{parts[0]}"',
                        'status': 'fail',
                        'detail': f'Container {parts[0]} is running in privileged mode.',
                        'severity': 'critical',
                        'fix': 'Recreate without --privileged. Use --cap-add for specific capabilities.',
                    })


def _check_kubernetes(findings):
    """Basic Kubernetes security checks."""
    # Check for anonymous auth on kubelet
    kubelet_config = read_file('/var/lib/kubelet/config.yaml')
    if kubelet_config:
        if 'anonymous:' in kubelet_config and 'enabled: true' in kubelet_config:
            findings.append({
                'name': 'Kubelet: Anonymous Auth Enabled',
                'status': 'fail',
                'detail': 'Kubelet allows anonymous authentication.',
                'severity': 'critical',
                'fix': 'Set authentication.anonymous.enabled to false in kubelet config.',
            })

    # Check kubectl access
    ctx = run(['kubectl', 'config', 'current-context'], timeout=5)
    if ctx:
        findings.append({
            'name': f'Kubernetes Context: {ctx}',
            'status': 'info',
            'detail': f'Current kubectl context: {ctx}',
            'severity': 'info', 'fix': None,
        })

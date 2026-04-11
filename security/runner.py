"""
Safe command execution helpers for security audit checks.
"""

import subprocess
import sys


def run(cmd, default='', timeout=10, shell=False):
    """Execute a command and return stdout, or default on any failure.

    Args:
        cmd: Command as list of strings, or string if shell=True.
        default: Value to return on failure.
        timeout: Command timeout in seconds.
        shell: Whether to use shell execution (needed for pipes, Windows builtins).
    """
    try:
        return subprocess.check_output(
            cmd, text=True, timeout=timeout,
            stderr=subprocess.STDOUT, shell=shell,
        ).strip()
    except Exception:
        return default


def run_powershell(script, default='', timeout=15):
    """Execute a PowerShell script and return stdout.

    Only works on Windows. Returns default on non-Windows or failure.
    """
    if sys.platform != 'win32':
        return default
    try:
        return subprocess.check_output(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
            text=True, timeout=timeout, stderr=subprocess.STDOUT,
        ).strip()
    except Exception:
        return default


def command_exists(cmd):
    """Check if a command is available on PATH."""
    try:
        if sys.platform == 'win32':
            subprocess.check_output(
                ['where', cmd], stderr=subprocess.DEVNULL, timeout=5,
            )
        else:
            subprocess.check_output(
                ['which', cmd], stderr=subprocess.DEVNULL, timeout=5,
            )
        return True
    except Exception:
        return False


def read_file(path, default=None, max_lines=None):
    """Safely read a file, returning default on failure.

    Args:
        path: File path to read.
        default: Value to return on failure (None means return None).
        max_lines: If set, read only last N lines.
    """
    try:
        with open(path) as f:
            if max_lines:
                return f.readlines()[-max_lines:]
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return default


def read_lines(path, skip_empty=True, skip_comments=True):
    """Read a file and return cleaned lines.

    Args:
        path: File path to read.
        skip_empty: Skip empty lines after stripping.
        skip_comments: Skip lines starting with #.

    Returns:
        List of stripped lines, or empty list on failure.
    """
    try:
        with open(path) as f:
            lines = []
            for line in f:
                line = line.strip()
                if skip_empty and not line:
                    continue
                if skip_comments and line.startswith('#'):
                    continue
                lines.append(line)
            return lines
    except (FileNotFoundError, PermissionError, OSError):
        return []


def read_sysctl(key, default=''):
    """Read a Linux sysctl value from /proc/sys/."""
    path = '/proc/sys/' + key.replace('.', '/')
    content = read_file(path)
    if content is not None:
        return content.strip()
    return default

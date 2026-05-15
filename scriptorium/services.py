"""Operational glue: ingest, deploy, backup, restore.

Everything that touches a subprocess or an SSH connection is funneled
through here so the views stay declarative.
"""
from __future__ import annotations

import datetime as _dt
import glob
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from django.utils import timezone

from .models import PhilologyProject, SyncRun


# ---------------------------------------------------------------------------
# Data-drop discovery
# ---------------------------------------------------------------------------

@dataclass
class DataDrop:
    """One candidate data-drop directory on disk."""
    name: str                   # 'Data_files2'
    path: Path                  # absolute
    xlsx_count: int             # number of *.xlsx files (top-level + 2 subdirs)
    last_modified: _dt.datetime


def list_data_drops(project: PhilologyProject) -> list[DataDrop]:
    base = Path(project.local_path)
    if not base.is_dir():
        return []
    matches = sorted(glob.glob(str(base / project.data_dir_glob)))
    drops: list[DataDrop] = []
    for p in matches:
        path = Path(p)
        if not path.is_dir():
            continue
        # Count .xlsx in path and direct subdirs (Palmyrene/, Old Syriac/, ...).
        xlsx_count = 0
        for root, _, files in os.walk(path):
            depth = len(Path(root).relative_to(path).parts)
            if depth > 2:
                continue
            xlsx_count += sum(
                1 for f in files
                if f.endswith('.xlsx') and not f.endswith('.xlsx:Zone.Identifier')
            )
        drops.append(DataDrop(
            name=path.name,
            path=path,
            xlsx_count=xlsx_count,
            last_modified=_dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.get_current_timezone(),
            ),
        ))
    return drops


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

@dataclass
class Backup:
    location: str               # 'local' or 'remote'
    name: str                   # filename
    path: str                   # absolute
    size_bytes: int
    modified: _dt.datetime


def _backup_dir(project: PhilologyProject) -> Path:
    if project.local_backup_dir:
        return Path(project.local_backup_dir).expanduser()
    return Path(project.local_path) / 'backups'


def list_local_backups(project: PhilologyProject) -> list[Backup]:
    bdir = _backup_dir(project)
    if not bdir.is_dir():
        return []
    out = []
    pattern = re.compile(rf'^{re.escape(project.db_filename)}\.bak[-_.]')
    for p in sorted(bdir.iterdir(), reverse=True):
        if pattern.match(p.name):
            st = p.stat()
            out.append(Backup(
                location='local', name=p.name, path=str(p),
                size_bytes=st.st_size,
                modified=_dt.datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.get_current_timezone(),
                ),
            ))
    return out


def list_remote_backups(project: PhilologyProject) -> list[Backup]:
    if not (project.remote_host and project.remote_path):
        return []
    cmd = (
        f"cd {shlex.quote(project.remote_path)} && "
        f"ls -la --time-style=full-iso {shlex.quote(project.db_filename)}.bak-* 2>/dev/null || true"
    )
    res = _ssh_run(project, cmd, capture=True)
    out: list[Backup] = []
    for line in (res.stdout or '').splitlines():
        # `ls -la` lines: perms links owner group size YYYY-MM-DD HH:MM:SS.ssss +ZZZZ name
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        try:
            size = int(parts[4])
            stamp = f"{parts[5]} {parts[6]}"
            dt = _dt.datetime.strptime(stamp.split('.')[0], '%Y-%m-%d %H:%M:%S')
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        except (ValueError, IndexError):
            continue
        name = parts[8].strip()
        out.append(Backup(
            location='remote', name=name,
            path=f"{project.remote_path.rstrip('/')}/{name}",
            size_bytes=size, modified=dt,
        ))
    return out


def make_local_backup(project: PhilologyProject, run: Optional[SyncRun] = None) -> Path:
    bdir = _backup_dir(project)
    bdir.mkdir(parents=True, exist_ok=True)
    src = Path(project.local_path) / project.db_filename
    if not src.is_file():
        raise FileNotFoundError(f"db file not found: {src}")
    ts = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    label = (run.data_dir or run.op) if run else 'manual'
    label = re.sub(r'[^A-Za-z0-9_.-]+', '_', label) or 'manual'
    dst = bdir / f"{project.db_filename}.bak-pre-{label}-{ts}"
    shutil.copy2(src, dst)
    return dst


def make_remote_backup(project: PhilologyProject, run: Optional[SyncRun] = None) -> str:
    if not (project.remote_host and project.remote_path):
        raise RuntimeError("Project has no remote configured.")
    ts = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    label = (run.data_dir or run.op) if run else 'manual'
    label = re.sub(r'[^A-Za-z0-9_.-]+', '_', label) or 'manual'
    bak_name = f"{project.db_filename}.bak-pre-{label}-{ts}"
    cmd = (
        f"cd {shlex.quote(project.remote_path)} && "
        f"cp {shlex.quote(project.db_filename)} {shlex.quote(bak_name)}"
    )
    _ssh_run(project, cmd)
    return f"{project.remote_path.rstrip('/')}/{bak_name}"


def restore_local_backup(project: PhilologyProject, backup_name: str) -> Path:
    bdir = _backup_dir(project)
    src = bdir / backup_name
    if not src.is_file():
        raise FileNotFoundError(f"backup not found: {src}")
    dst = Path(project.local_path) / project.db_filename
    # Take a safety copy of the current db first so a wrong restore isn't fatal.
    safety = dst.with_suffix(dst.suffix + f".pre-restore-{_dt.datetime.now():%Y%m%d-%H%M%S}")
    if dst.is_file():
        shutil.copy2(dst, safety)
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

INGEST_SUMMARY_RE = re.compile(
    r"(?P<created>\d+) created,\s*(?P<updated>\d+) updated", re.MULTILINE,
)
INGEST_TOTAL_RE = re.compile(
    r"Done!\s*(?P<inscriptions>\d+)\s+inscriptions,\s*"
    r"(?P<words>\d+)\s+word entries,\s*"
    r"(?P<content>\d+)\s+content entries",
)
INGEST_SECTION_RE = re.compile(r"^=== Ingesting (?P<corpus>\S+) ===", re.MULTILINE)
INGEST_SKIPPED_RE = re.compile(r"^\s+-\s+(.+)$", re.MULTILINE)


def parse_ingest_output(stdout: str) -> dict:
    """Pull a structured summary out of `ingest_ground_truth` output."""
    per_corpus = {}
    sections = list(INGEST_SECTION_RE.finditer(stdout))
    for i, m in enumerate(sections):
        end = sections[i + 1].start() if i + 1 < len(sections) else len(stdout)
        chunk = stdout[m.start():end]
        sm = INGEST_SUMMARY_RE.search(chunk)
        if sm:
            per_corpus[m.group('corpus')] = {
                'created': int(sm.group('created')),
                'updated': int(sm.group('updated')),
            }
    totals = INGEST_TOTAL_RE.search(stdout)
    skipped = []
    if 'Skipped' in stdout:
        # Take only lines between "Skipped" and the next blank line.
        chunk = stdout.split('Skipped', 1)[1].split('\n\n', 1)[0]
        for line in chunk.splitlines():
            m2 = re.match(r'\s+-\s+(.+)', line)
            if m2:
                skipped.append(m2.group(1).strip())
    return {
        'per_corpus': per_corpus,
        'totals': {
            'inscriptions': int(totals.group('inscriptions')) if totals else None,
            'words': int(totals.group('words')) if totals else None,
            'content': int(totals.group('content')) if totals else None,
        },
        'skipped': skipped,
    }


def run_local_ingest(project: PhilologyProject, data_drop: str, run: SyncRun) -> SyncRun:
    """Execute the project's ingest command locally with the chosen drop."""
    env = os.environ.copy()
    env['DJANGO_SETTINGS_MODULE'] = project.django_settings_module
    env[project.data_files_dir_env] = str(Path(project.local_path) / data_drop)
    cmd = [project.venv_python, 'manage.py', project.ingest_command]
    run.status = 'running'
    run.data_dir = data_drop
    run.save(update_fields=['status', 'data_dir'])
    proc = subprocess.run(
        cmd, cwd=project.local_path, env=env,
        capture_output=True, text=True, timeout=900,
    )
    run.stdout = proc.stdout
    run.stderr = proc.stderr
    run.exit_code = proc.returncode
    run.summary = parse_ingest_output(proc.stdout)
    run.status = 'ok' if proc.returncode == 0 else 'failed'
    run.finished_at = timezone.now()
    run.save()
    return run


def run_remote_ingest(project: PhilologyProject, data_drop: str, run: SyncRun) -> SyncRun:
    """Run the same ingest command via SSH on the staging host."""
    if not (project.remote_host and project.remote_path and project.remote_python):
        raise RuntimeError("Remote ingest requires remote_host/remote_path/remote_python.")
    remote_drop = f"{project.remote_path.rstrip('/')}/{data_drop}"
    inner = (
        f"cd {shlex.quote(project.remote_path)} && "
        f"{project.data_files_dir_env}={shlex.quote(remote_drop)} "
        f"{shlex.quote(project.remote_python)} manage.py {project.ingest_command}"
    )
    run.status = 'running'
    run.data_dir = data_drop
    run.save(update_fields=['status', 'data_dir'])
    res = _ssh_run(project, inner, capture=True, timeout=1800)
    run.stdout = res.stdout or ''
    run.stderr = res.stderr or ''
    run.exit_code = res.returncode
    run.summary = parse_ingest_output(run.stdout)
    run.status = 'ok' if res.returncode == 0 else 'failed'
    run.finished_at = timezone.now()
    run.save()
    return run


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

def run_deploy(project: PhilologyProject, run: SyncRun) -> SyncRun:
    if not project.deploy_script:
        raise RuntimeError("Project has no deploy_script configured.")
    script = Path(project.local_path) / project.deploy_script
    if not script.is_file():
        raise FileNotFoundError(f"deploy script not found: {script}")
    run.status = 'running'
    run.save(update_fields=['status'])
    proc = subprocess.run(
        ['bash', str(script)], cwd=project.local_path,
        capture_output=True, text=True, timeout=1800,
    )
    run.stdout = proc.stdout
    run.stderr = proc.stderr
    run.exit_code = proc.returncode
    run.status = 'ok' if proc.returncode == 0 else 'failed'
    run.finished_at = timezone.now()
    run.save()
    return run


# ---------------------------------------------------------------------------
# Inscription counts (read-through to the danwsi DB via the multi-DB router)
# ---------------------------------------------------------------------------

def local_counts() -> dict:
    """Counts straight from the danwsi DB via the inscriptions models."""
    try:
        from inscriptions.models import Inscription, Word, ContentData
    except Exception as exc:  # pragma: no cover — only on misconfig
        return {'error': f'Cannot import inscriptions: {exc}'}
    return {
        'inscriptions': Inscription.objects.count(),
        'palmyrene': Inscription.objects.filter(corpus='palmyrene').count(),
        'old_syriac': Inscription.objects.filter(corpus='old_syriac').count(),
        'hebrew': Inscription.objects.filter(corpus='hebrew').count(),
        'words': Word.objects.count(),
        'content': ContentData.objects.count(),
    }


REMOTE_COUNTS_SNIPPET = """
import sys
sys.path.insert(0, '%(remote_path)s')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', '%(settings)s')
django.setup()
from inscriptions.models import Inscription, Word, ContentData
print('INSCRIPTIONS', Inscription.objects.count())
print('PALMYRENE',   Inscription.objects.filter(corpus='palmyrene').count())
print('OLD_SYRIAC',  Inscription.objects.filter(corpus='old_syriac').count())
print('HEBREW',      Inscription.objects.filter(corpus='hebrew').count())
print('WORDS',       Word.objects.count())
print('CONTENT',     ContentData.objects.count())
"""


def remote_counts(project: PhilologyProject) -> dict:
    if not (project.remote_host and project.remote_python):
        return {'error': 'remote not configured'}
    snippet = REMOTE_COUNTS_SNIPPET % {
        'remote_path': project.remote_path,
        'settings': project.django_settings_module,
    }
    cmd = f"{shlex.quote(project.remote_python)} - <<'PYEOF'\n{snippet}\nPYEOF"
    res = _ssh_run(project, cmd, capture=True)
    if res.returncode != 0:
        return {'error': (res.stderr or '').strip() or f'exit {res.returncode}'}
    out: dict = {}
    for line in (res.stdout or '').splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].isdigit():
            out[parts[0].lower()] = int(parts[1])
    return out


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

@dataclass
class _Proc:
    returncode: int
    stdout: str = ''
    stderr: str = ''


def _ssh_run(project: PhilologyProject, remote_command: str, *,
             capture: bool = False, timeout: int = 600) -> _Proc:
    ssh = ['ssh']
    if project.ssh_key_path:
        ssh += ['-i', project.ssh_key_path, '-o', 'IdentitiesOnly=yes']
    ssh += ['-o', 'StrictHostKeyChecking=accept-new']
    user_host = f"{project.remote_user}@{project.remote_host}" if project.remote_user else project.remote_host
    ssh += [user_host, 'bash', '-lc', remote_command]
    proc = subprocess.run(
        ssh, capture_output=capture, text=True, timeout=timeout,
    )
    return _Proc(
        returncode=proc.returncode,
        stdout=proc.stdout or '' if capture else '',
        stderr=proc.stderr or '' if capture else '',
    )

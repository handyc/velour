"""Context injection — the cwd / time / persona-name / git block that
gets prepended (silently, behind the system prompt) to every turn.

Per the barding plan: implicit context is the "knows where I am"
trick.  Cheap (≈1 KB of code, a few dozen bytes of context text per
turn), high-feel.

Each toggle on HarnessProfile is wired here.  The block is rendered
as a single multi-line string so the deterministic core sees a stable
ordering — no model is reasoning about it, but bytes-in-bytes-out
needs to be reproducible.
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
from dataclasses import dataclass


@dataclass
class ContextBlock:
    """The rendered context injection for one turn.  Kept as
    structured fields so the UI can show the user what was actually
    inserted; ``text`` is the joined form fed to the composer."""
    persona_name: str = ''
    cwd: str = ''
    time_local: str = ''
    git_branch: str = ''
    identity_mood: str = ''
    text: str = ''


def _safe_git_branch() -> str:
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=2.0, check=False)
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return ''


def _safe_identity_mood() -> str:
    """Read the current Velour identity mood snapshot if available.
    Soft-fail: this is decoration, not a hard dependency."""
    try:
        from identity.models import Mood
        m = Mood.objects.order_by('-recorded_at').first()
        if m is not None:
            return f'{m.label} ({m.intensity:.2f})'
    except Exception:                              # noqa: BLE001
        pass
    return ''


def build(profile, now: _dt.datetime | None = None) -> ContextBlock:
    """Render the context block for ``profile``.  Each toggle on the
    profile decides whether that field is included; absent fields
    leave the block silent rather than printing 'unknown'."""
    cb = ContextBlock(persona_name=profile.persona_name or '')
    parts: list[str] = []

    if cb.persona_name:
        parts.append(f'persona: {cb.persona_name}')

    if profile.inject_time:
        now = now or _dt.datetime.now()
        cb.time_local = now.strftime('%Y-%m-%d %H:%M')
        parts.append(f'time: {cb.time_local}')

    if profile.inject_cwd:
        cb.cwd = os.getcwd()
        parts.append(f'cwd: {cb.cwd}')

    if profile.inject_git:
        cb.git_branch = _safe_git_branch()
        if cb.git_branch:
            parts.append(f'branch: {cb.git_branch}')

    if profile.inject_identity:
        cb.identity_mood = _safe_identity_mood()
        if cb.identity_mood:
            parts.append(f'mood: {cb.identity_mood}')

    cb.text = '\n'.join(parts)
    return cb

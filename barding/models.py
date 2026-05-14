"""barding — bookkeeping for Claude Code CLI configuration.

settings.json is the source of truth on disk; the SettingsScope rows
just record which paths we manage from the UI.  BundlePatchWish tracks
*unsupported* customisations (custom thinking verbs, spinner glyph)
that live inside the ELF binary — we never apply them automatically,
this table is a wishlist + paste-able recipe per row.
"""

from __future__ import annotations

from django.db import models


SCOPE_CHOICES = (
    ('user',    'user (~/.claude/settings.json)'),
    ('project', 'project (<repo>/.claude/settings.json)'),
    ('local',   'local  (<repo>/.claude/settings.local.json)'),
)


class SettingsScope(models.Model):
    """One row per settings.json path we know how to read/write."""

    name = models.CharField(max_length=32, choices=SCOPE_CHOICES, unique=True)
    path = models.CharField(max_length=512,
                            help_text='Absolute path to a settings.json file.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self) -> str:
        return f'{self.get_name_display()}'


PATCH_KINDS = (
    ('verb',    'thinking verb'),
    ('spinner', 'spinner glyph'),
    ('other',   'other binary string'),
)


class BundlePatchWish(models.Model):
    """A planned binary-string substitution.  Never auto-applied:
    Claude Code ships as a single ELF and every upgrade clobbers any
    in-place patch.  The UI surfaces this row as a paste-able recipe
    the operator may run by hand after each upgrade."""

    kind = models.CharField(max_length=16, choices=PATCH_KINDS,
                            default='verb')
    target = models.CharField(max_length=256,
                              help_text='Exact string currently in the binary.')
    replacement = models.CharField(
        max_length=256,
        help_text='Desired replacement.  Must be ≤ len(target) bytes '
                  'unless you intend to relocate (advanced).')
    notes = models.TextField(blank=True)
    applied = models.BooleanField(default=False,
                                  help_text='Operator-toggled flag — purely '
                                            'informational, the row is never '
                                            'auto-applied.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self) -> str:
        return f'{self.get_kind_display()}: {self.target!r} → {self.replacement!r}'

    @property
    def length_ok(self) -> bool:
        return len(self.replacement.encode('utf-8')) <= len(self.target.encode('utf-8'))

    def sed_recipe(self, binary_path: str) -> str:
        """A copy-paste sed/printf one-liner the operator can run after
        each Claude Code upgrade.  Pads the replacement with NULs to
        match the original length so offsets don't shift."""
        # Padding to keep the binary string length constant.
        old = self.target
        new = self.replacement
        pad = len(old.encode('utf-8')) - len(new.encode('utf-8'))
        padded = new + ('\\x00' * pad if pad > 0 else '')
        return (f"# Replace {self.get_kind_display()!s} string in {binary_path}\n"
                f"# Always back up first: cp {binary_path} {binary_path}.bak\n"
                f"python3 -c \"import sys; p=sys.argv[1]; "
                f"d=open(p,'rb').read(); "
                f"old={old.encode('utf-8')!r}; new={padded.encode('utf-8')!r}; "
                f"assert old in d, 'target not found'; "
                f"open(p,'wb').write(d.replace(old, new, 1))\" {binary_path}")

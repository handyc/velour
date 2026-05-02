"""s3lab persistent state.

The s3lab UI itself is browser-only (state in JS), but anything that
moves between the browser, Velour, and a device is worth keeping —
that's the audit trail of an experiment session.

`SlotPatch` is the obvious one: every successful compile_push.
Source, ELF, metadata, push history. Lets the user browse what's
been tried, see what crashed the device, and re-push any historical
slot without re-typing the C.
"""
from __future__ import annotations

import hashlib

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


SLOT_CHOICES = [
    ('',         '— (no slot, upload only)'),
    ('step',     'step'),
    ('render',   'render'),
    ('gpio',     'gpio'),
    ('fitness',  'fitness'),
]


class SlotPatch(models.Model):
    """One compile + push. Source + ELF + push history."""

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    source_text = models.TextField()
    source_bytes = models.PositiveIntegerField(default=0)
    elf_blob = models.BinaryField()
    elf_bytes = models.PositiveIntegerField(default=0)
    elf_sha1 = models.CharField(max_length=40, db_index=True)
    build_time_ms = models.PositiveSmallIntegerField(default=0)

    slot = models.CharField(max_length=12, choices=SLOT_CHOICES, blank=True)
    last_pushed_to = models.CharField(max_length=200, blank=True,
        help_text='Last device URL this patch was pushed to.')
    last_push_at = models.DateTimeField(null=True, blank=True)
    push_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL,
                             null=True, blank=True, related_name='+')

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['slot']),
            models.Index(fields=['elf_sha1']),
        ]

    def __str__(self) -> str:
        return f'{self.name or self.slug} ({self.elf_bytes} B, slot={self.slot or "—"})'

    @classmethod
    def upsert(cls, *, source_text: str, elf_blob: bytes,
               build_time_ms: int, slot: str = '',
               name: str = '', user=None,
               last_pushed_to: str = '',
               push_succeeded: bool = False) -> 'SlotPatch':
        """Look up by sha1(elf_blob); update existing if found."""
        sha = hashlib.sha1(elf_blob).hexdigest()
        existing = cls.objects.filter(elf_sha1=sha).first()
        now = timezone.now()
        if existing:
            existing.push_count += 1
            if push_succeeded:
                existing.success_count += 1
            if last_pushed_to:
                existing.last_pushed_to = last_pushed_to
                existing.last_push_at = now
            if slot and not existing.slot:
                existing.slot = slot
            existing.save()
            return existing

        base = slugify(name)[:60] or sha[:10]
        candidate = base
        n = 2
        while cls.objects.filter(slug=candidate).exists():
            candidate = f'{base}-{n}'
            n += 1
        return cls.objects.create(
            slug=candidate,
            name=name,
            source_text=source_text,
            source_bytes=len(source_text.encode('utf-8', errors='replace')),
            elf_blob=elf_blob,
            elf_bytes=len(elf_blob),
            elf_sha1=sha,
            build_time_ms=build_time_ms,
            slot=slot,
            last_pushed_to=last_pushed_to,
            last_push_at=now if last_pushed_to else None,
            push_count=1,
            success_count=1 if push_succeeded else 0,
            user=user,
        )

"""Attic — Velour's general-purpose media library.

Distinct from codex's `Figure` model. A `Figure` is document-embedded
content (an image or rendered diagram referenced from a Section's
markdown body). An `attic.MediaItem` is a free-floating uploaded file
that may or may not be embedded anywhere — a photo from the lab, an
audio recording of an interview, a video of a microcontroller doing
something, a diagram exported from another tool.

Phase 1 scope:
  - Upload images, audio, video, or arbitrary files
  - Auto-detect mime type and broad kind (image/video/audio/other)
  - SHA-256 hash on save for dedup detection
  - Auto-generated thumbnails for images (via Pillow, already in deps)
  - Tags, caption, alt text
  - List view (grid of thumbs), detail view (full preview), upload form,
    edit / delete

Phase 2 (planned):
  - Collections (album / playlist groupings)
  - Audio/video duration probing via ffprobe
  - Drag-drop multi-file uploads
  - Linking from codex Figure to MediaItem so the same file isn't
    stored twice
"""

import hashlib
import mimetypes
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import models
from django.utils.text import slugify


KIND_CHOICES = [
    ('image', 'Image'),
    ('video', 'Video'),
    ('audio', 'Audio'),
    ('document', 'Document'),
    ('other', 'Other'),
]


def _kind_from_mime(mime):
    if not mime:
        return 'other'
    if mime.startswith('image/'):
        return 'image'
    if mime.startswith('video/'):
        return 'video'
    if mime.startswith('audio/'):
        return 'audio'
    if mime in ('application/pdf', 'text/plain', 'text/markdown'):
        return 'document'
    return 'other'


def _media_upload_path(instance, filename):
    """Where uploaded files land. Bucketed by kind so the dev tree
    isn't a single huge flat directory."""
    return f'attic/{instance.kind}/{filename}'


def _thumb_upload_path(instance, filename):
    return f'attic/thumbs/{filename}'


class MediaItem(models.Model):
    """One uploaded media file.

    The file lives in MEDIA_ROOT/attic/<kind>/<slug>.<ext>. Thumbnails
    for images live in MEDIA_ROOT/attic/thumbs/. Non-image files get
    no thumbnail in Phase 1 — the list view shows a placeholder for
    them.
    """

    title = models.CharField(
        max_length=200,
        help_text='Human-readable label. If blank, the filename is used.',
    )
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    file = models.FileField(upload_to=_media_upload_path)
    thumbnail = models.ImageField(
        upload_to=_thumb_upload_path, blank=True, null=True,
        help_text='Auto-generated for image kind. Skipped for other kinds.',
    )

    kind = models.CharField(
        max_length=12, choices=KIND_CHOICES, default='other',
        help_text='Auto-derived from mime on save.',
    )
    mime = models.CharField(max_length=120, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(
        max_length=64, blank=True,
        help_text='Hash of the file contents. Used for dedup detection — '
                  'if two MediaItems have the same sha256 you have a '
                  'duplicate upload.',
    )

    caption = models.TextField(blank=True)
    alt_text = models.CharField(
        max_length=300, blank=True,
        help_text='Accessibility text for screen readers / image fallback.',
    )
    tags = models.CharField(
        max_length=300, blank=True,
        help_text='Comma-separated. Free-form.',
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='attic_uploads',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['kind', '-uploaded_at']),
            models.Index(fields=['sha256']),
        ]

    def __str__(self):
        return self.title or self.slug or '(unnamed)'

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    def save(self, *args, **kwargs):
        # Title fallback to filename
        if not self.title and self.file:
            self.title = Path(self.file.name).stem

        # Slug fallback
        if not self.slug:
            base = slugify(self.title)[:200] or 'media'
            candidate = base
            n = 2
            while MediaItem.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate

        # Mime + kind from filename
        if self.file and not self.mime:
            mime, _ = mimetypes.guess_type(self.file.name)
            self.mime = mime or 'application/octet-stream'
        self.kind = _kind_from_mime(self.mime)

        # Save once so the file is on disk and we can read it.
        super().save(*args, **kwargs)

        # Post-save: compute hash, size, and thumbnail. Doing this in a
        # second pass keeps the save() simple and lets us use the file
        # via its actual storage path rather than the in-memory upload.
        dirty = []

        try:
            with self.file.open('rb') as f:
                data = f.read()
            new_size = len(data)
            new_hash = hashlib.sha256(data).hexdigest()
            if self.size_bytes != new_size:
                self.size_bytes = new_size
                dirty.append('size_bytes')
            if self.sha256 != new_hash:
                self.sha256 = new_hash
                dirty.append('sha256')
        except Exception:
            data = None

        if self.kind == 'image' and not self.thumbnail and data:
            try:
                from PIL import Image
                img = Image.open(BytesIO(data))
                img.thumbnail((400, 400))
                buf = BytesIO()
                img_format = (img.format or 'PNG').upper()
                if img_format == 'JPEG' and img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(buf, format=img_format)
                ext = img_format.lower()
                if ext == 'jpeg':
                    ext = 'jpg'
                self.thumbnail.save(
                    f'{self.slug}.{ext}',
                    ContentFile(buf.getvalue()),
                    save=False,
                )
                dirty.append('thumbnail')
            except Exception:
                pass

        if dirty:
            super().save(update_fields=dirty)

    @property
    def size_h(self):
        """Human-readable size."""
        n = self.size_bytes
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if n < 1024:
                return f'{n:.1f} {unit}'.replace('.0 ', ' ')
            n /= 1024
        return f'{n:.1f} PB'

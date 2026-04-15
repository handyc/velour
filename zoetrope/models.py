"""Zoetrope — compile Attic images into short mp4 films.

A `Reel` is a declarative recipe (which images, how long, how fast)
plus a cached rendered mp4. Rendering is done by the `render()` method
which shells out to `ffmpeg` — it must be on PATH.

The pre-cinema toy of the same name was a slitted drum that made a
strip of still images look like motion when spun. Same idea here: a
strip of Attic images, spun at 24 or 30 fps.
"""

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


SELECTION_MODES = [
    ('recent', 'Most recent'),
    ('oldest', 'Oldest first'),
    ('random', 'Random sample'),
]

STATUS_CHOICES = [
    ('draft', 'Draft (not yet rendered)'),
    ('rendering', 'Rendering'),
    ('ready', 'Ready'),
    ('error', 'Error'),
]


def _reel_upload_path(instance, filename):
    return f'zoetrope/reels/{filename}'


def _poster_upload_path(instance, filename):
    return f'zoetrope/posters/{filename}'


class Reel(models.Model):
    """One short film assembled from Attic images."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    tag_filter = models.CharField(
        max_length=200, blank=True,
        help_text='Comma-separated tags. Blank = any image.',
    )
    selection_mode = models.CharField(
        max_length=10, choices=SELECTION_MODES, default='recent',
    )
    image_count = models.PositiveIntegerField(
        default=10,
        help_text='How many Attic images to pull into the reel.',
    )
    fps = models.PositiveSmallIntegerField(default=30)
    duration_seconds = models.FloatField(default=6.0)
    width = models.PositiveIntegerField(default=1280)
    height = models.PositiveIntegerField(default=720)

    output = models.FileField(
        upload_to=_reel_upload_path, blank=True, null=True,
    )
    poster = models.ImageField(
        upload_to=_poster_upload_path, blank=True, null=True,
    )

    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='draft',
    )
    status_message = models.TextField(blank=True)

    frames_used = models.PositiveIntegerField(default=0)
    size_bytes = models.BigIntegerField(default=0)

    share_url = models.URLField(
        blank=True,
        help_text='Public URL on s.h4ks.com. Expires ~4 hours after upload.',
    )
    shared_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    rendered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title or self.slug or f'Reel #{self.pk}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or 'reel'
            candidate = base
            n = 2
            while Reel.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tag_filter.split(',') if t.strip()]

    def select_items(self):
        """Return the ordered list of attic.MediaItem to include."""
        from attic.models import MediaItem

        qs = MediaItem.objects.filter(kind='image')
        for t in self.tag_list:
            qs = qs.filter(tags__icontains=t)

        if self.selection_mode == 'oldest':
            qs = qs.order_by('uploaded_at')
        elif self.selection_mode == 'random':
            qs = qs.order_by('?')
        else:
            qs = qs.order_by('-uploaded_at')

        return list(qs[: self.image_count])

    def render(self):
        """Shell out to ffmpeg and build the mp4. Synchronous."""
        from django.core.files.base import ContentFile

        items = self.select_items()
        if not items:
            self.status = 'error'
            self.status_message = 'No matching Attic images.'
            self.save(update_fields=['status', 'status_message'])
            return

        if shutil.which('ffmpeg') is None:
            self.status = 'error'
            self.status_message = (
                'ffmpeg not found on PATH. Install it: sudo apt install ffmpeg'
            )
            self.save(update_fields=['status', 'status_message'])
            return

        self.status = 'rendering'
        self.status_message = ''
        self.save(update_fields=['status', 'status_message'])

        per_image = float(self.duration_seconds) / len(items)

        # Build a concat-demuxer list. The final image needs a duration
        # line AND a second repetition without duration, otherwise
        # ffmpeg drops it. Keep paths absolute and quoted.
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / 'frames.txt'
            lines = []
            for item in items:
                p = Path(item.file.path).resolve().as_posix().replace("'", r"'\''")
                lines.append(f"file '{p}'")
                lines.append(f'duration {per_image:.4f}')
            last = Path(items[-1].file.path).resolve().as_posix().replace("'", r"'\''")
            lines.append(f"file '{last}'")
            list_path.write_text('\n'.join(lines) + '\n')

            out_path = Path(td) / 'reel.mp4'
            poster_path = Path(td) / 'poster.jpg'

            vf = (
                f'scale={self.width}:{self.height}:'
                'force_original_aspect_ratio=decrease,'
                f'pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black,'
                'setsar=1'
            )
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0',
                '-i', str(list_path),
                '-vf', vf,
                '-r', str(self.fps),
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-preset', 'veryfast',
                '-movflags', '+faststart',
                str(out_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not out_path.exists():
                self.status = 'error'
                self.status_message = (proc.stderr or 'ffmpeg failed')[-2000:]
                self.save(update_fields=['status', 'status_message'])
                return

            # First frame as poster (best effort).
            subprocess.run(
                ['ffmpeg', '-y', '-i', str(out_path),
                 '-vframes', '1', '-q:v', '3', str(poster_path)],
                capture_output=True,
            )

            # Swap in the new file. Delete the old one if present.
            if self.output:
                try:
                    self.output.delete(save=False)
                except Exception:
                    pass
            if self.poster:
                try:
                    self.poster.delete(save=False)
                except Exception:
                    pass

            data = out_path.read_bytes()
            self.output.save(
                f'{self.slug}.mp4', ContentFile(data), save=False,
            )
            if poster_path.exists():
                self.poster.save(
                    f'{self.slug}.jpg',
                    ContentFile(poster_path.read_bytes()),
                    save=False,
                )

            self.size_bytes = len(data)
            self.frames_used = len(items)
            self.status = 'ready'
            self.status_message = ''
            self.rendered_at = timezone.now()
            self.save()

    def share_to_h4ks(self):
        """Upload the rendered mp4 to s.h4ks.com. Returns the public URL
        or raises. Retains for ~4h, 64MB limit."""
        import requests

        if not self.output:
            raise ValueError('Reel has no rendered output to share.')

        with self.output.open('rb') as f:
            resp = requests.post(
                'https://s.h4ks.com/',
                files={'file': (Path(self.output.name).name, f, 'video/mp4')},
                timeout=120,
            )
        resp.raise_for_status()
        url = resp.text.strip()
        if not url.startswith('http'):
            raise ValueError(f'Unexpected response from h4ks: {url[:200]}')
        self.share_url = url
        self.shared_at = timezone.now()
        self.save(update_fields=['share_url', 'shared_at'])
        return url

    @property
    def size_h(self):
        n = self.size_bytes
        for unit in ('B', 'KB', 'MB', 'GB'):
            if n < 1024:
                return f'{n:.1f} {unit}'.replace('.0 ', ' ')
            n /= 1024
        return f'{n:.1f} TB'

"""Persisted escher compositions.

A Composition records "which group + which motif + which physical
size".  Stock motifs are referenced by slug; CA-frame motifs carry
a tiny spec dict pointing at the source pact/component/generation.
"""

from __future__ import annotations

from django.db import models

import hashlib

from django.utils.text import slugify

from . import groups, motifs


MOTIF_KIND_CHOICES = [
    ('stock', 'Stock motif'),
    ('spoeqi_component', 'spoeqi component frame'),
    ('tilesmith_tile', 'tilesmith tile silhouette'),
    ('upload', 'Uploaded bitmap'),
]


def _upload_to(instance, filename: str) -> str:
    """Place uploads under ``MEDIA_ROOT/escher/motifs/<sha256>.<ext>``
    so the same image content lands at a stable, dedupe-friendly path.
    The ``instance.content_hash`` is set in ``save()`` before the
    storage callback fires, but for new uploads we don't yet have it;
    fall back to the original filename's slug to give Django a path.
    """
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else 'bin').lower()
    h = getattr(instance, 'content_hash', '') or slugify(filename) or 'image'
    return f'escher/motifs/{h}.{ext}'


class UploadedMotif(models.Model):
    """A user-uploaded image to be used as an escher motif.

    The image bytes live on disk under MEDIA_ROOT/escher/motifs/ named
    by their SHA-256 (so two uploads of the same image dedupe).  The
    escher renderer embeds the raw image as an SVG <image> element
    sized to fit [0, 1]² with the aspect ratio preserved.
    """
    slug = models.SlugField(unique=True, max_length=80)
    original_name = models.CharField(max_length=200, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    file = models.FileField(upload_to=_upload_to)
    content_type = models.CharField(max_length=80, default='image/png')
    width  = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.slug} ({self.original_name})'


class Composition(models.Model):
    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160)
    group_slug = models.CharField(max_length=8, default='p4m')
    motif_kind = models.CharField(
        max_length=24, choices=MOTIF_KIND_CHOICES, default='stock')
    motif_spec = models.JSONField(
        default=dict,
        help_text='Stock: {"slug": "comma"}.  '
                  'spoeqi_component: {"pact": "<slug>", "component": K, '
                  '"generation": N}.')
    tile_mm = models.FloatField(default=30.0)
    landscape = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} ({self.group_slug})'

    @property
    def group(self):
        return groups.get(self.group_slug)

    def motif_label(self) -> str:
        if self.motif_kind == 'stock':
            slug = (self.motif_spec or {}).get('slug') or motifs.DEFAULT_MOTIF
            try:
                return motifs.get(slug).name
            except KeyError:
                return slug
        if self.motif_kind == 'spoeqi_component':
            s = self.motif_spec or {}
            return (f'spoeqi {s.get("pact", "?")} '
                    f'· cmp {s.get("component", 0)} '
                    f'· gen {s.get("generation", 0)}')
        return self.motif_kind

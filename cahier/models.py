"""Cahier — catalogue of Jupyter notebook projects.

A `NotebookProject` is a pointer to an .ipynb file under `notebooks/` at
the repo root plus a bit of curation metadata.  No copy of the bytes
lives in the DB — the file system is the source of truth; renaming a
notebook means updating its row.
"""
from __future__ import annotations

from django.db import models


class NotebookProject(models.Model):
    """One catalogued .ipynb file."""
    title       = models.CharField(max_length=200)
    slug        = models.SlugField(max_length=80, unique=True)
    path        = models.CharField(
        max_length=400,
        help_text='Path to the .ipynb file relative to BASE_DIR '
                  '(e.g. "notebooks/spoeqi_quine_pact_pipeline.ipynb").')
    summary     = models.TextField(
        blank=True,
        help_text='One-line description shown in the catalogue.')
    description = models.TextField(
        blank=True,
        help_text='Longer prose; markdown OK. Shown on the detail page.')
    tags        = models.CharField(
        max_length=200, blank=True,
        help_text='Comma-separated tags (e.g. "spoeqi, quines, demo").')
    related_apps = models.CharField(
        max_length=200, blank=True,
        help_text='Comma-separated Velour app slugs the notebook '
                  'touches (e.g. "spoeqi, caformer").')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    pinned      = models.BooleanField(
        default=False,
        help_text='Show at the top of the catalogue.')

    class Meta:
        ordering = ['-pinned', '-updated_at']

    def __str__(self):
        return f'{self.title} ({self.slug})'

    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    def app_list(self) -> list[str]:
        return [a.strip() for a in self.related_apps.split(',') if a.strip()]

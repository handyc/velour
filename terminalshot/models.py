"""Optional persistence — store named ANSI captures so the web UI
can list + replay them without uploading each time.  Live captures
work without DB rows; this is just a registry."""

from django.db import models
from django.utils.text import slugify


class Capture(models.Model):
    """A captured ANSI byte stream + the parameters needed to decode
    it back into a 2D grid."""

    name      = models.CharField(max_length=120, unique=True)
    slug      = models.SlugField(max_length=120, unique=True)
    cols      = models.PositiveIntegerField(default=80)
    rows      = models.PositiveIntegerField(default=24)
    notes     = models.TextField(blank=True)
    blob      = models.BinaryField(
        help_text='Raw ANSI bytes — exactly what the program would '
                  'have written to the terminal.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = slugify(self.name)[:120] or f'cap-{self.pk or "new"}'
        super().save(*a, **kw)

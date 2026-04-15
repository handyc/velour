from django.db import models
from django.utils.text import slugify

from . import gubify as G


class GubiWorld(models.Model):
    """An 80x25 text screen + everything Gubi derives from it.

    The text is stored verbatim (as the user typed it); normalisation
    to exactly 2000 code points happens at gubify time.
    """

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    text = models.TextField(
        blank=True,
        help_text='80×25 screen. <2000 chars is padded, >2000 is truncated.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base = slugify(self.title)[:120] or 'world'
            candidate = base
            n = 2
            while GubiWorld.objects.filter(
                    slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def gubified(self):
        return G.gubify(self.text)

    def scene(self):
        return G.lsystem_scene(self.gubified())

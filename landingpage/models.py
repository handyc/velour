from django.db import models


class Section(models.Model):
    """Topic sections set by the administrator."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    order = models.IntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Article(models.Model):
    title = models.CharField(max_length=300)
    subtitle = models.CharField(max_length=500, blank=True)
    body = models.TextField()
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True)
    image_url = models.URLField(
        blank=True,
        help_text='URL to a header image (use picsum.photos or similar for placeholders)',
    )
    image_caption = models.CharField(max_length=300, blank=True)
    is_featured = models.BooleanField(default=False, help_text='Show as the large hero article')
    is_published = models.BooleanField(default=True)
    author = models.CharField(max_length=100, default='Editorial Staff')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', '-created_at']

    def __str__(self):
        return self.title

    @property
    def reading_time(self):
        words = len(self.body.split())
        return max(1, words // 200)


class SiteSettings(models.Model):
    """Singleton for the newspaper name and tagline."""
    newspaper_name = models.CharField(max_length=200, default='The Velour Chronicle')
    tagline = models.CharField(max_length=300, default='Dispatches from the digital frontier')

    class Meta:
        verbose_name_plural = 'site settings'

    def __str__(self):
        return self.newspaper_name

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

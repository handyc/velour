"""Displacement — a Django CMS seeded from displace.nl.

displace.nl is a Zotonic (Erlang) oral-history site about living with
disabilities in the Netherlands. The Django port here preserves the
public look-and-feel while giving non-technical editors a simple
back-end: list / create / edit articles, upload images, organise by
Theme and Category.

Content taxonomy:

    Theme      — top-level topical bucket (e.g. 'Wonen', 'Werk'). One
                 article belongs to 0+ Themes.
    Category   — short editorial label shown above an article's title
                 (e.g. 'Gebeurtenis', 'Persoonlijk verhaal').
    Article    — the main content type — title, summary, rich body,
                 optional hero image, credits.
    Page       — static pages (About, Privacy, Accessibility) rendered
                 in the same chrome.
    Person     — credited individuals (authors + 'thanks to').
    MediaAsset — images and their metadata. Reused across articles.

The Zotonic id is preserved in `zotonic_id` so a re-ingest is
idempotent: we match on zotonic_id first, fall back to slug.
"""

from django.db import models
from django.utils.text import slugify


# --- Shared mixin ---------------------------------------------------


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def _unique_slug(instance, base, *, field='slug', manager=None):
    """Return a slug unique for the given instance's class."""
    manager = manager or instance.__class__.objects
    candidate = base or 'item'
    n = 2
    while manager.filter(**{field: candidate}).exclude(pk=instance.pk).exists():
        candidate = f'{base}-{n}'
        n += 1
    return candidate


# --- Core models ----------------------------------------------------


class Theme(TimestampedModel):
    """Top-level topical bucket. Displayed on THEMA'S index."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    zotonic_id = models.PositiveIntegerField(
        null=True, blank=True, unique=True,
        help_text='Original numeric id in the Zotonic source site.',
    )
    subtitle = models.CharField(max_length=400, blank=True)
    summary = models.TextField(
        blank=True,
        help_text='Short teaser shown on the themes index.',
    )
    body_html = models.TextField(
        blank=True,
        help_text='Rich HTML body — paragraphs, figures, embeds.',
    )
    hero_image = models.ForeignKey(
        'MediaAsset', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='hero_of_themes',
    )
    order = models.IntegerField(default=100)
    published = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    original_url = models.URLField(
        max_length=400, blank=True,
        help_text='Canonical URL on the original Zotonic site.',
    )

    class Meta:
        ordering = ['order', 'title']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, slugify(self.title)[:220])
        super().save(*args, **kwargs)


class Category(models.Model):
    """Short editorial label shown above an article title."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, slugify(self.name)[:100])
        super().save(*args, **kwargs)


class Person(models.Model):
    """A named human: author, contributor, interviewee.

    Kept as a separate model so the same name appears consistently
    across articles and we can fix a typo in one place.
    """

    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    bio = models.TextField(blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, slugify(self.name)[:180])
        super().save(*args, **kwargs)


class MediaAsset(TimestampedModel):
    """An image (or other asset) uploaded once, reused across content.

    `file` is the canonical stored file. `original_url` remembers where
    we got it from if ingested — useful for audit and re-download.
    """

    title = models.CharField(
        max_length=240, blank=True,
        help_text='Short title for admin use (search-friendly).',
    )
    file = models.FileField(
        upload_to='displacer/%Y/%m/',
        help_text='The image / asset itself.',
    )
    caption = models.TextField(
        blank=True,
        help_text='Shown as the figcaption under the image on the public site.',
    )
    credit = models.CharField(
        max_length=240, blank=True,
        help_text='Photographer / archive credit line.',
    )
    alt_text = models.CharField(
        max_length=240, blank=True,
        help_text='Alt text for screen readers (accessibility).',
    )
    original_url = models.URLField(
        max_length=500, blank=True,
        help_text='Where the file was ingested from, if applicable.',
    )
    sha256 = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text='Hex digest of the file contents — used to dedup re-ingested assets.',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title or self.file.name


# Authorship / credit roles on an article.
AUTHOR_ROLES = [
    ('author',   'Written by'),
    ('thanks',   'With thanks to'),
    ('editor',   'Edited by'),
    ('photographer', 'Photography by'),
]


class Article(TimestampedModel):
    """A story.

    Articles are the core content type. Themes group them topically;
    categories label them editorially. Body is rich HTML — editors
    work in a WYSIWYG or paste from Word; the public template just
    drops the HTML straight into a container styled with the original
    displace.nl CSS.
    """

    title = models.CharField(max_length=240)
    slug = models.SlugField(
        max_length=260, unique=True, blank=True,
        help_text='Auto-filled from the title. Edit carefully — '
                  'changing it breaks existing links.',
    )
    zotonic_id = models.PositiveIntegerField(
        null=True, blank=True, unique=True,
        help_text='Original numeric id in the Zotonic source site. '
                  'Used to keep re-ingests idempotent.',
    )
    summary = models.TextField(
        blank=True,
        help_text='Lede paragraph shown at the top of the article and '
                  'in social-media previews. Keep it under 400 chars.',
    )
    body_html = models.TextField(
        blank=True,
        help_text='Full article body in HTML. Use the rich-text editor.',
    )
    hero_image = models.ForeignKey(
        MediaAsset, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='hero_of_articles',
        help_text='Image shown at the top of the article and on list cards.',
    )
    themes = models.ManyToManyField(
        Theme, blank=True, related_name='articles',
        help_text='Topical groupings this story belongs to.',
    )
    categories = models.ManyToManyField(
        Category, blank=True, related_name='articles',
        help_text='Editorial labels shown above the article title.',
    )
    credits = models.ManyToManyField(
        Person, through='ArticleCredit',
        related_name='articles',
        help_text='Authors, thanks-to, editors.',
    )

    published = models.BooleanField(
        default=False,
        help_text='Unchecked = draft, only visible to staff.',
    )
    published_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the article was (or will be) published. '
                  'Used as the sort date on index pages.',
    )
    featured = models.BooleanField(
        default=False,
        help_text='If True, appears in the "Uitgelicht" strip on the home page.',
    )
    featured_order = models.IntegerField(
        default=100,
        help_text='Lower values appear first when Featured.',
    )
    display_order = models.IntegerField(
        default=1000, db_index=True,
        help_text='Position on the public Verhalen list. The first 6 are '
                  'set from the curated source list at ingest time; the '
                  'rest fall back to recency by zotonic_id.',
    )
    original_url = models.URLField(
        max_length=400, blank=True,
        help_text='Canonical URL on the original Zotonic site, if ingested.',
    )

    class Meta:
        ordering = ['display_order', '-zotonic_id']
        indexes = [
            models.Index(fields=['published', 'display_order']),
            models.Index(fields=['featured', 'featured_order']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, slugify(self.title)[:260])
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('displacer:article_detail', args=[self.slug])

    def primary_category(self):
        return self.categories.first()

    def authors(self):
        return self.credits.filter(articlecredit__role='author')

    def thanks_to(self):
        return self.credits.filter(articlecredit__role='thanks')


class ArticleCredit(models.Model):
    """Through-table so the same Person can be credited in different
    roles on different articles."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=AUTHOR_ROLES, default='author')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['role', 'order']
        unique_together = [('article', 'person', 'role')]

    def __str__(self):
        return f'{self.person.name} ({self.get_role_display()})'


class Page(TimestampedModel):
    """A static page — About, Privacy, Accessibility, Submit."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    zotonic_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    body_html = models.TextField(blank=True)
    show_in_footer = models.BooleanField(default=False)
    show_in_menu = models.BooleanField(default=False)
    order = models.IntegerField(default=100)
    published = models.BooleanField(default=True)
    original_url = models.URLField(max_length=400, blank=True)

    class Meta:
        ordering = ['order', 'title']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, slugify(self.title)[:220])
        super().save(*args, **kwargs)


class SiteSettings(models.Model):
    """Singleton — site-wide settings tweakable by an editor.

    Things like the homepage intro, the contact email, whether to
    enable the GA snippet. Always pk=1.
    """

    home_intro = models.TextField(
        blank=True,
        help_text='Plain-text intro shown at the very top of the home page.',
    )
    contact_email = models.EmailField(
        default='info@displace.nl',
        help_text='Shown in the footer.',
    )
    site_name = models.CharField(max_length=80, default='Displace')
    ga_tracking_id = models.CharField(
        max_length=40, blank=True,
        help_text='Google Analytics / GA4 id. Leave blank to disable tracking.',
    )

    class Meta:
        verbose_name = 'Site settings'
        verbose_name_plural = 'Site settings'

    def __str__(self):
        return f'SiteSettings({self.site_name})'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class HomeBlock(TimestampedModel):
    """An editorial text block in the lower 'home-blocks' strip on
    the homepage. The source has two — 'Toegankelijk voor iedereen'
    and 'Waarom DisPLACE?' — each with a heading, a short paragraph,
    and a 'Lees meer' button to a related Page. Captured from the
    source homepage at ingest time so the homepage layout stays
    faithful."""

    block_id = models.CharField(
        max_length=120, blank=True,
        help_text="Source HTML id (e.g. 'waarom-displacetext2'). "
                  "Used as the rendered <div id=...> for CSS parity.",
    )
    title = models.CharField(max_length=200)
    body_html = models.TextField(blank=True)
    link_zotonic_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Zid of the Page/Theme/Article the 'Lees meer' "
                  "button targets. Resolved at render time.",
    )
    link_label = models.CharField(
        max_length=120, blank=True,
        help_text="Visually-hidden text after 'Lees meer' (e.g. "
                  "'over Toegankelijkheid').",
    )
    order = models.IntegerField(default=100)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

    @property
    def link_url(self) -> str:
        """Resolve link_zotonic_id to a slug-based URL on our site.
        Falls back to the legacy_zotonic redirect if the target isn't
        in any of the obvious models."""
        if not self.link_zotonic_id:
            return ''
        from django.urls import reverse
        for model, viewname in [
            (Page,    'displacer:page_detail'),
            (Theme,   'displacer:theme_detail'),
            (Article, 'displacer:article_detail'),
        ]:
            obj = model.objects.filter(
                zotonic_id=self.link_zotonic_id, published=True,
            ).first()
            if obj:
                return reverse(viewname, kwargs={'slug': obj.slug})
        return reverse('displacer:legacy_zotonic',
                       kwargs={'zotonic_id': self.link_zotonic_id})

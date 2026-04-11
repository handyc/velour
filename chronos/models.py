"""Chronos — velour's sense of time.

Phase 1: ClockPrefs singleton + WatchedTimezone wall.

Phase 2a (current): CalendarEvent model + month grid + day detail.

Phase 2b (planned): Holiday data from religious traditions
(Vedic Hinduism, Daoism, Confucianism, Shinto, Buddhism, Chinese
calendar, Islam, Judaism, Christianity, Wicca) and civic holidays.

Phase 2c (planned): Astronomical events (eclipses, equinoxes,
solstices, planetary conjunctions, meteor showers) via skyfield.

Phase 2d (planned): Deep-time browsing modes — month → year →
decade → century → millennium → 10K-yr → 100K-yr.
"""

from django.db import models
from django.utils.text import slugify


class ClockPrefs(models.Model):
    """Singleton — there is exactly one ClockPrefs row, pk=1.

    Fetched everywhere via `ClockPrefs.load()` which guarantees a row
    exists with sensible defaults (Europe/Amsterdam, 24h, 10 min sync).
    """

    home_tz = models.CharField(
        max_length=64,
        default='Europe/Amsterdam',
        help_text='IANA timezone name for the local clock shown in the topbar.',
    )
    format_24h = models.BooleanField(
        default=True,
        help_text='If True, display times as 14:32:09. If False, 2:32:09 pm.',
    )
    auto_sync_seconds = models.PositiveIntegerField(
        default=600,
        help_text='How often the in-page JS clock re-syncs against the server '
                  '(seconds). Set to 0 to disable auto-sync — manual only.',
    )
    show_seconds = models.BooleanField(
        default=True,
        help_text='If True, the topbar clock ticks at 1Hz showing seconds.',
    )

    class Meta:
        verbose_name = 'Clock preferences'
        verbose_name_plural = 'Clock preferences'

    def __str__(self):
        return f'ClockPrefs(home={self.home_tz}, 24h={self.format_24h})'

    def save(self, *args, **kwargs):
        # Force singleton: only ever pk=1.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WatchedTimezone(models.Model):
    """A pinned world clock shown on the /chronos/ wall view.

    `label` is the human name you want to see ("NYC", "Denver", "Mum
    in Auckland"). `tz_name` is the IANA identifier ("America/New_York").
    `sort_order` lets the user arrange them however they like — lower
    numbers appear first.
    """

    label = models.CharField(
        max_length=80,
        help_text='Display name, e.g. "NYC", "Denver", "Tokyo office".',
    )
    tz_name = models.CharField(
        max_length=64,
        help_text='IANA timezone, e.g. "America/New_York", "Asia/Tokyo".',
    )
    sort_order = models.IntegerField(
        default=0,
        help_text='Lower values shown first. Ties broken by label.',
    )
    color = models.CharField(
        max_length=9,
        blank=True,
        help_text='Optional hex color (e.g. "#B7410E") applied to the label '
                  'and time on the world-clocks page. Cities of special '
                  'interest to the project get unique colors; leave blank '
                  'for the default neutral grey.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'label']

    def __str__(self):
        return f'{self.label} ({self.tz_name})'


# --- Calendar (Phase 2a) --------------------------------------------------


class CalendarEvent(models.Model):
    """One scheduled event on the chronos calendar.

    The model is deliberately simple in Phase 2a:
      - title, optional notes
      - start datetime, optional end datetime
      - all_day flag (renders as a colored bar across the day cell
        instead of a time-stamped row)
      - color (hex), so events can be visually grouped
      - tags (free-text comma-separated), for ad-hoc grouping
      - source: 'user' for user-created, reserved for future
        'holiday', 'astro', 'feed' kinds in later phases.

    Recurrence is NOT modeled in Phase 2a — every event is a single
    occurrence. Phase 2c will add an RRULE field if needed.
    """

    SOURCE_CHOICES = [
        ('user',    'User-scheduled'),
        ('holiday', 'Holiday (auto)'),
        ('astro',   'Astronomical (auto)'),
        ('feed',    'External feed'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    notes = models.TextField(blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    all_day = models.BooleanField(
        default=False,
        help_text='If True, the event spans the whole day(s) regardless '
                  'of the start/end times.',
    )
    color = models.CharField(
        max_length=9, blank=True,
        help_text='Optional hex color (e.g. "#58A6FF") used to tint the '
                  'event in the month grid.',
    )
    tags = models.CharField(
        max_length=200, blank=True,
        help_text='Free-form comma-separated tags.',
    )
    source = models.CharField(
        max_length=16, choices=SOURCE_CHOICES, default='user',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start', 'pk']
        indexes = [
            models.Index(fields=['start']),
            models.Index(fields=['source', 'start']),
        ]

    def __str__(self):
        return f'{self.title} @ {self.start.isoformat()}'

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base = slugify(self.title)[:200] or 'event'
            candidate = base
            n = 2
            while CalendarEvent.objects.filter(
                slug=candidate,
            ).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]

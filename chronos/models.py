"""Chronos — velour's sense of time.

Phase 1: ClockPrefs singleton + WatchedTimezone wall.

Phase 2: CalendarEvent across month / day, religious + civic
holidays, astronomical events from skyfield (equinoxes, solstices,
eclipses, moon phases, meteor showers, planetary conjunctions), and
the deep-time zoom chain day → month → year → decade → century →
millennium → 10Ky → 100Ky.

Phase 2e: Task + morning Briefing, daily Codex push.
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
    country = models.CharField(
        max_length=2,
        default='NL',
        help_text='ISO-3166-1 alpha-2 country code, used by the civic '
                  'holiday adapter to pick which national calendar to pull. '
                  'NL = Netherlands.',
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


# --- Calendar (Phase 2a–2b) -----------------------------------------------


class Tradition(models.Model):
    """A holiday tradition — civic / religious / observance source.

    Used by Phase 2b seeding to attach holidays to a parent grouping
    so the calendar can color them and (eventually) toggle each
    tradition on or off.
    """

    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    color = models.CharField(
        max_length=9, blank=True,
        help_text='Hex color used to tint holidays from this tradition.',
    )
    enabled = models.BooleanField(
        default=True,
        help_text='If unchecked, holidays from this tradition are hidden '
                  'from calendar views (rows are kept in the database).',
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


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
    tradition = models.ForeignKey(
        Tradition, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='events',
        help_text='If this event came from a holiday tradition, link to '
                  'the Tradition for color + toggleability. Null for '
                  'user-created events.',
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


# --- Tasks (Phase 2e) ----------------------------------------------------


class Task(models.Model):
    """A thing to do. Lightweight on purpose: title + optional notes,
    optional due date, a priority, and a status. `source_app` lets
    other apps tag a task so it can be grouped (e.g. 'displacement',
    'aether'); `source_url` jumps back to whatever the task is about.

    Concerns in the Identity app already capture Velour's persistent
    self-attention, so Tasks here are for the operator's own to-dos —
    deliberately separate.
    """

    STATUS_OPEN = 'open'
    STATUS_DONE = 'done'
    STATUS_DROPPED = 'dropped'
    STATUS_CHOICES = [
        (STATUS_OPEN,    'Open'),
        (STATUS_DONE,    'Done'),
        (STATUS_DROPPED, 'Dropped'),
    ]

    PRIORITY_LOW = 'low'
    PRIORITY_NORMAL = 'normal'
    PRIORITY_HIGH = 'high'
    PRIORITY_CHOICES = [
        (PRIORITY_LOW,    'Low'),
        (PRIORITY_NORMAL, 'Normal'),
        (PRIORITY_HIGH,   'High'),
    ]

    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    source_app = models.CharField(
        max_length=40, blank=True,
        help_text='Free-text app/tag this task belongs to '
                  '(e.g. "displacement", "aether"). Optional.',
    )
    source_url = models.URLField(
        max_length=400, blank=True,
        help_text='Jump-back URL — the page or admin row this task '
                  'is about. Optional.',
    )
    due_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(
        max_length=8, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL,
    )
    status = models.CharField(
        max_length=8, choices=STATUS_CHOICES, default=STATUS_OPEN,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = [
            models.F('due_at').asc(nulls_last=True),
            'priority',
            '-created_at',
        ]
        indexes = [
            models.Index(fields=['status', 'due_at']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

"""Chronos — velour's sense of time.

Phase 1 scope:
  - A singleton ClockPrefs row holding the user's home timezone, 12/24h
    preference, and how often the in-page JS clock should re-sync against
    the server (so JS drift never accumulates past N minutes).
  - WatchedTimezone rows: a hand-curated list of "I want to see what time
    it is in NYC, Denver, etc." entries shown on the /chronos/ page.

Future phases will add a CalendarEvent model for the monthly calendar
plus religion/country holiday tagging.
"""

from django.db import models


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

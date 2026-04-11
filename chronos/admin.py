from django.contrib import admin

from .models import ClockPrefs, WatchedTimezone


@admin.register(ClockPrefs)
class ClockPrefsAdmin(admin.ModelAdmin):
    list_display = ('home_tz', 'format_24h', 'show_seconds', 'auto_sync_seconds')


@admin.register(WatchedTimezone)
class WatchedTimezoneAdmin(admin.ModelAdmin):
    list_display = ('label', 'tz_name', 'sort_order')
    list_editable = ('sort_order',)
    search_fields = ('label', 'tz_name')

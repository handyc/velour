from django.contrib import admin

from .models import (
    CalendarEvent, ClockPrefs, Task, TrackedObject, WatchedTimezone,
)


@admin.register(ClockPrefs)
class ClockPrefsAdmin(admin.ModelAdmin):
    list_display = ('home_tz', 'format_24h', 'show_seconds', 'auto_sync_seconds')


@admin.register(WatchedTimezone)
class WatchedTimezoneAdmin(admin.ModelAdmin):
    list_display = ('label', 'tz_name', 'sort_order')
    list_editable = ('sort_order',)
    search_fields = ('label', 'tz_name')


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'start', 'end', 'all_day', 'source')
    list_filter = ('source', 'all_day')
    search_fields = ('title', 'notes', 'tags')
    date_hierarchy = 'start'


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'priority', 'due_at',
                    'source_app', 'created_at')
    list_filter = ('status', 'priority', 'source_app')
    search_fields = ('title', 'notes', 'source_app')
    date_hierarchy = 'created_at'


@admin.register(TrackedObject)
class TrackedObjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'designation', 'is_watched',
                    'magnitude', 'elements_fetched_at')
    list_filter = ('kind', 'is_watched')
    search_fields = ('name', 'slug', 'designation')
    list_editable = ('is_watched',)
    readonly_fields = ('elements_fetched_at', 'created_at')

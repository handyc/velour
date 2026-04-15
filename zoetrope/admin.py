from django.contrib import admin

from .models import Reel


@admin.register(Reel)
class ReelAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'fps', 'duration_seconds',
                    'image_count', 'frames_used', 'created_at', 'rendered_at')
    list_filter = ('status', 'selection_mode')
    search_fields = ('title', 'slug', 'tag_filter')
    readonly_fields = ('slug', 'status', 'status_message', 'frames_used',
                       'size_bytes', 'created_at', 'rendered_at',
                       'output', 'poster')

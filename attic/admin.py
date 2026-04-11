from django.contrib import admin

from .models import MediaItem


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'kind', 'mime', 'size_h', 'uploaded_at')
    list_filter = ('kind', 'uploaded_at')
    search_fields = ('title', 'caption', 'tags', 'sha256')
    readonly_fields = ('sha256', 'size_bytes', 'mime', 'kind')

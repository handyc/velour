from django.contrib import admin

from .models import NotebookProject


@admin.register(NotebookProject)
class NotebookProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'path', 'tags', 'pinned',
                       'updated_at')
    list_filter  = ('pinned',)
    search_fields = ('title', 'slug', 'tags', 'related_apps')
    prepopulated_fields = {'slug': ('title',)}

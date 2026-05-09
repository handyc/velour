from django.contrib import admin

from .models import Capture


@admin.register(Capture)
class CaptureAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'cols', 'rows', 'created_at')
    search_fields = ('name', 'slug', 'notes')
    readonly_fields = ('created_at',)

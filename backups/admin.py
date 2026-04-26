from django.contrib import admin
from .models import Snapshot


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'retention', 'size_mb', 'path')
    list_filter = ('retention',)
    readonly_fields = ('created_at', 'sha256', 'size_bytes',
                       'path', 'contents_summary')

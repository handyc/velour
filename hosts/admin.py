from django.contrib import admin

from .models import RemoteHost


@admin.register(RemoteHost)
class RemoteHostAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'enabled', 'last_status', 'last_polled_at')
    list_filter = ('enabled', 'last_status')
    search_fields = ('name', 'url')

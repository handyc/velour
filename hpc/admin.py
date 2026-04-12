from django.contrib import admin

from .models import HPCCluster


@admin.register(HPCCluster)
class HPCClusterAdmin(admin.ModelAdmin):
    list_display = ('nickname', 'hostname', 'scheduler', 'institution',
                    'is_active', 'created_at')
    list_filter = ('scheduler', 'is_active', 'institution')
    search_fields = ('nickname', 'hostname', 'institution', 'notes')
    prepopulated_fields = {'slug': ('nickname',)}
    readonly_fields = ('created_at', 'last_touched_at')

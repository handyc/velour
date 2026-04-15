from django.contrib import admin

from .models import Planet


@admin.register(Planet)
class PlanetAdmin(admin.ModelAdmin):
    list_display = ('name', 'ptype', 'visit_count', 'last_visited', 'discovered')
    list_filter = ('ptype',)
    search_fields = ('name', 'seed')
    readonly_fields = ('features', 'seed', 'discovered')
    ordering = ('-last_visited',)

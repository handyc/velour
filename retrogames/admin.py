from django.contrib import admin

from .models import Platform, Game


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display  = ('name', 'manufacturer', 'year_release', 'bit_depth')
    search_fields = ('name', 'manufacturer')
    ordering      = ('year_release', 'name')


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display  = ('name', 'platform', 'year', 'genre', 'developer')
    list_filter   = ('platform', 'genre', 'year')
    search_fields = ('name', 'developer', 'publisher', 'description', 'mechanics')
    ordering      = ('platform__year_release', 'year', 'name')

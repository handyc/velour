from django.contrib import admin

from .models import MapPrefs, Place


@admin.register(MapPrefs)
class MapPrefsAdmin(admin.ModelAdmin):
    list_display = ('default_scale', 'default_lat', 'default_lon', 'default_zoom')


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'scale', 'lat', 'lon', 'zoom')
    list_filter = ('scale',)
    search_fields = ('name', 'notes')

from django.contrib import admin

from .models import TessSet


@admin.register(TessSet)
class TessSetAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'seed', 'tile_px', 'method',
                     'blend_power', 'created_at')
    search_fields = ('name', 'slug')
    list_filter   = ('method',)
    readonly_fields = ('created_at',)

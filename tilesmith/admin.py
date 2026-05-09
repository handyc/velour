from django.contrib import admin

from .models import TileSpec


@admin.register(TileSpec)
class TileSpecAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'base_w', 'base_h', 'lattice',
                    'is_preset', 'updated_at')
    list_filter = ('lattice', 'is_preset')
    search_fields = ('name', 'slug', 'notes')
    prepopulated_fields = {'slug': ('name',)}

from django.contrib import admin

from .models import Tile, TileSet


class TileInline(admin.TabularInline):
    model = Tile
    extra = 1


@admin.register(TileSet)
class TileSetAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'tile_count', 'created_at')
    search_fields = ('name', 'description', 'notes')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [TileInline]


@admin.register(Tile)
class TileAdmin(admin.ModelAdmin):
    list_display = ('tileset', 'name', 'n_color', 'e_color',
                    's_color', 'w_color', 'sort_order')
    list_filter = ('tileset',)
    search_fields = ('name', 'tileset__name')
